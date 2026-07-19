#!/usr/bin/env python3
"""Copy a completed deterministic artifact tree into durable private storage.

The copy is intentionally gated on a successful AWS Batch job.  Each source
object is re-headed after the copy, and the destination must preserve byte size
and at least one S3 full-object checksum while using the exact KMS key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from capture_batch_provenance import EXPECTED_BATCH_WORKER_CHECKS

S3_URI = re.compile(r"^s3://([^/]+)/(.+)$")
CHECKSUM_FIELDS = (
    "ChecksumCRC64NVME",
    "ChecksumSHA256",
    "ChecksumSHA1",
    "ChecksumCRC32C",
    "ChecksumCRC32",
)
CHECKSUM_ALGORITHMS = {
    "ChecksumCRC64NVME": "CRC64NVME",
    "ChecksumSHA256": "SHA256",
    "ChecksumSHA1": "SHA1",
    "ChecksumCRC32C": "CRC32C",
    "ChecksumCRC32": "CRC32",
}
MAX_SINGLE_COPY_BYTES = 5_000_000_000
EXPECTED_DRY_RUN_CHECKS = {
    "execution_receipt_bound": True,
    "complete_source_inventory_unchanged": True,
}
EXPECTED_DRY_RUN_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "generated_at",
        "run_id",
        "batch_job_id",
        "batch_status",
        "execution_receipt",
        "source_prefix",
        "destination_prefix",
        "kms_key_arn",
        "script_sha256",
        "destination_bucket_versioning",
        "destination_initial_version_history_count",
        "receipt_anchor_strategy",
        "object_count",
        "initial_inventory_identity",
        "objects",
        "final_inventory_identity",
        "checks",
        "completed_at",
        "passed_count",
    }
)
EXPECTED_DRY_RUN_OBJECT_KEYS = frozenset(
    {"relative_key", "source", "destination", "status"}
)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exact_schema_version(payload: dict[str, Any], expected: int) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"JSON document parent must not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"JSON document parent must be a directory: {parent}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"JSON document must be a real file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    return value


def write_json_atomic(
    path: Path, value: dict[str, Any], *, create: bool = False
) -> None:
    require_safe_output_parent(path, "JSON receipt output")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    staging = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = -1
    linked = False
    try:
        descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if create:
            os.link(staging, path)
            linked = True
        else:
            staging.replace(path)
        fsync_directory(path.parent)
        require_installed_json(path, expected_sha256)
    except Exception:
        if create and linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        staging.unlink(missing_ok=True)


def require_installed_json(path: Path, expected_sha256: str) -> None:
    require_real_downloaded_file(path, "JSON receipt output")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"JSON receipt output mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"JSON receipt output changed during write: {path}")


def require_safe_output_parent(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(
                f"{label} parent must not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent must be a directory: {parent}")


def require_new_output(path: Path, label: str) -> None:
    require_safe_output_parent(path, label)
    if path.exists():
        try:
            status = load_json(path).get("status", "unknown")
        except Exception:
            status = "unreadable"
        raise ValueError(
            f"{label} already exists with status {status}; choose a new path so prior "
            "custody evidence is never overwritten"
        )


def require_safe_download_destination(path: Path, label: str) -> None:
    require_safe_output_parent(path, label)


def require_real_downloaded_file(path: Path, label: str) -> None:
    require_safe_download_destination(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def aws_json(arguments: list[str], region: str) -> dict[str, Any]:
    command = ["aws", *arguments, "--region", region, "--output", "json"]
    value = json.loads(subprocess.check_output(command, text=True))
    if not isinstance(value, dict):
        raise RuntimeError(f"AWS command did not return an object: {' '.join(command)}")
    return value


def parse_s3(uri: str) -> tuple[str, str]:
    match = S3_URI.fullmatch(uri.rstrip("/"))
    if not match:
        raise ValueError(f"invalid S3 URI: {uri}")
    return match.group(1), match.group(2)


def checksums(head: dict[str, Any]) -> dict[str, str]:
    return {
        field: str(head[field])
        for field in CHECKSUM_FIELDS
        if str(head.get(field, "")).strip()
    }


def common_checksum_matches(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("ChecksumType") != "FULL_OBJECT" or right.get("ChecksumType") != "FULL_OBJECT":
        return False
    left_values = checksums(left)
    right_values = checksums(right)
    shared = set(left_values) & set(right_values)
    return bool(shared) and all(left_values[field] == right_values[field] for field in shared)


def preferred_checksum_algorithm(value: dict[str, Any]) -> str:
    available = checksums(value)
    for field in CHECKSUM_FIELDS:
        if field in available:
            return CHECKSUM_ALGORITHMS[field]
    raise ValueError("object has no supported checksum algorithm")


def safe_relative_key(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or path.as_posix() != value
    ):
        raise ValueError(f"unsafe source relative key: {value}")
    return value


def head(
    bucket: str, key: str, region: str, version_id: str = ""
) -> dict[str, Any]:
    arguments = [
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--checksum-mode",
            "ENABLED",
        ]
    if version_id:
        arguments.extend(["--version-id", version_id])
    return aws_json(arguments, region)


def version_history(bucket: str, prefix: str, region: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    key_marker = ""
    version_id_marker = ""
    seen_markers: set[tuple[str, str]] = set()
    while True:
        arguments = [
            "s3api",
            "list-object-versions",
            "--bucket",
            bucket,
            "--prefix",
            prefix,
        ]
        if key_marker:
            arguments.extend(["--key-marker", key_marker])
        if version_id_marker:
            arguments.extend(["--version-id-marker", version_id_marker])
        page = aws_json(arguments, region)
        for field, kind in (("Versions", "version"), ("DeleteMarkers", "delete_marker")):
            values = page.get(field, [])
            if not isinstance(values, list) or any(
                not isinstance(row, dict) for row in values
            ):
                raise RuntimeError("S3 version history is malformed")
            rows.extend({**row, "history_kind": kind} for row in values)
        if page.get("IsTruncated") is not True:
            return rows
        key_marker = str(page.get("NextKeyMarker", ""))
        version_id_marker = str(page.get("NextVersionIdMarker", ""))
        if not key_marker or not version_id_marker:
            raise RuntimeError(
                "truncated version history omitted its next key/version markers"
            )
        marker = (key_marker, version_id_marker)
        if marker in seen_markers:
            raise RuntimeError("S3 version history pagination did not advance")
        seen_markers.add(marker)


def require_bucket_versioning(bucket: str, region: str) -> None:
    value = aws_json(["s3api", "get-bucket-versioning", "--bucket", bucket], region)
    if value.get("Status") != "Enabled":
        raise ValueError(f"destination bucket versioning is not Enabled: {bucket}")


def get_exact_object(
    bucket: str, key: str, version_id: str, destination: Path, region: str
) -> dict[str, Any]:
    require_safe_download_destination(destination, "downloaded final-freeze receipt")
    command = [
        "aws",
        "s3api",
        "get-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--version-id",
        version_id,
        "--checksum-mode",
        "ENABLED",
        "--region",
        region,
        "--output",
        "json",
        str(destination),
    ]
    value = json.loads(subprocess.check_output(command, text=True))
    if not isinstance(value, dict):
        raise RuntimeError("S3 get-object did not return an object")
    require_real_downloaded_file(destination, "downloaded final-freeze receipt")
    return value


def put_receipt(
    path: Path,
    bucket: str,
    key: str,
    kms_key_arn: str,
    region: str,
) -> dict[str, Any]:
    return aws_json(
        [
            "s3api",
            "put-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--body",
            str(path),
            "--if-none-match",
            "*",
            "--server-side-encryption",
            "aws:kms",
            "--sse-kms-key-id",
            kms_key_arn,
            "--checksum-algorithm",
            "SHA256",
            "--checksum-sha256",
            checksum_sha256(sha256(path)),
            "--content-type",
            "application/json",
        ],
        region,
    )


def list_objects(bucket: str, prefix: str, region: str) -> list[dict[str, Any]]:
    """Return the complete current-object inventory for one prefix."""
    objects: list[dict[str, Any]] = []
    continuation_token = ""
    seen_tokens: set[str] = set()
    while True:
        arguments = [
            "s3api",
            "list-objects-v2",
            "--bucket",
            bucket,
            "--prefix",
            prefix,
        ]
        if continuation_token:
            arguments.extend(["--continuation-token", continuation_token])
        page = aws_json(arguments, region)
        contents = page.get("Contents", [])
        if not isinstance(contents, list) or any(
            not isinstance(row, dict) for row in contents
        ):
            raise RuntimeError("S3 object inventory is malformed")
        objects.extend(contents)
        if page.get("IsTruncated") is not True:
            return objects
        continuation_token = str(page.get("NextContinuationToken", ""))
        if not continuation_token:
            raise RuntimeError("Truncated S3 inventory omitted NextContinuationToken")
        if continuation_token in seen_tokens:
            raise RuntimeError("S3 object inventory pagination did not advance")
        seen_tokens.add(continuation_token)


def snapshot_inventory(bucket: str, prefix: str, region: str) -> list[dict[str, Any]]:
    """Capture an exact current-object inventory, including each VersionId."""
    snapshot: list[dict[str, Any]] = []
    for listed_row in list_objects(bucket, prefix, region):
        source_key = str(listed_row.get("Key", ""))
        relative = safe_relative_key(source_key.removeprefix(prefix))
        if not relative or relative == source_key:
            raise RuntimeError(f"source key is outside declared prefix: {source_key}")
        current = head(bucket, source_key, region)
        version_id = str(current.get("VersionId", ""))
        size = int(current.get("ContentLength", -1))
        etag = str(current.get("ETag", ""))
        listed_stable = (
            int(listed_row.get("Size", -1)) == size
            and str(listed_row.get("ETag", "")) == etag
        )
        if (
            not listed_stable
            or size <= 0
            or size > MAX_SINGLE_COPY_BYTES
            or version_id in {"", "None"}
            or current.get("ChecksumType") != "FULL_OBJECT"
            or not checksums(current)
        ):
            raise RuntimeError(
                "source object changed during inventory or lacks a positive single-copy "
                f"size, exact VersionId, or full-object checksum: {relative}"
            )
        snapshot.append(
            {
                "relative_key": relative,
                "key": source_key,
                "bytes": size,
                "etag": etag,
                "version_id": version_id,
                "checksums": checksums(current),
                "checksum_type": str(current.get("ChecksumType", "")),
            }
        )
    snapshot.sort(key=lambda row: row["relative_key"])
    return snapshot


def inventory_identity(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the fields that must remain identical across the complete freeze."""
    return [
        {
            "relative_key": str(row["relative_key"]),
            "key": str(row["key"]),
            "bytes": int(row["bytes"]),
            "etag": str(row["etag"]),
            "version_id": str(row["version_id"]),
        }
        for row in snapshot
    ]


def dry_run_objects(
    inventory: list[dict[str, Any]],
    source_bucket: str,
    destination_bucket: str,
    destination_prefix: str,
) -> list[dict[str, Any]]:
    return [
        {
            "relative_key": str(row["relative_key"]),
            "source": {
                "bucket": source_bucket,
                "key": str(row["key"]),
                "version_id": str(row["version_id"]),
                "bytes": int(row["bytes"]),
                "etag": str(row["etag"]),
                "checksums": row["checksums"],
                "checksum_type": str(row["checksum_type"]),
            },
            "destination": {
                "bucket": destination_bucket,
                "key": destination_prefix + str(row["relative_key"]),
            },
            "status": "dry_run",
        }
        for row in inventory
    ]


def validate_dry_run_receipt(path: Path, expected: dict[str, Any]) -> None:
    receipt = load_json(path)
    observed_keys = set(receipt)
    if observed_keys != EXPECTED_DRY_RUN_RECEIPT_KEYS:
        raise ValueError(
            "final artifact freeze dry-run receipt has stale or missing metadata: "
            f"missing={sorted(EXPECTED_DRY_RUN_RECEIPT_KEYS - observed_keys)} "
            f"unexpected={sorted(observed_keys - EXPECTED_DRY_RUN_RECEIPT_KEYS)}"
        )
    if (
        not exact_schema_version(receipt, 1)
        or receipt.get("status") != "dry_run"
        or receipt.get("batch_status") != "SUCCEEDED"
        or receipt.get("passed_count") != 0
        or not isinstance(receipt.get("generated_at"), str)
        or not receipt.get("generated_at")
        or not isinstance(receipt.get("completed_at"), str)
        or not receipt.get("completed_at")
        or receipt.get("checks") != EXPECTED_DRY_RUN_CHECKS
    ):
        raise ValueError("final artifact freeze dry-run receipt did not pass preflight")

    bound_fields = (
        "run_id",
        "batch_job_id",
        "execution_receipt",
        "source_prefix",
        "destination_prefix",
        "kms_key_arn",
        "script_sha256",
        "destination_bucket_versioning",
        "destination_initial_version_history_count",
        "receipt_anchor_strategy",
        "object_count",
        "initial_inventory_identity",
        "final_inventory_identity",
    )
    if any(receipt.get(field) != expected.get(field) for field in bound_fields):
        raise ValueError(
            "final artifact freeze dry-run receipt does not match this apply"
        )

    observed_objects = receipt.get("objects")
    expected_objects = expected.get("objects")
    if not isinstance(observed_objects, list) or observed_objects != expected_objects:
        raise ValueError(
            "final artifact freeze dry-run receipt object inventory does not "
            "match this apply"
        )
    for row in observed_objects:
        if not isinstance(row, dict) or set(row) != EXPECTED_DRY_RUN_OBJECT_KEYS:
            raise ValueError(
                "final artifact freeze dry-run receipt has stale or malformed "
                "object metadata"
            )


def snapshot_destination(
    bucket: str, prefix: str, kms_key_arn: str, region: str
) -> list[dict[str, Any]]:
    """Require one durable current version per key and no hidden history."""
    history = version_history(bucket, prefix, region)
    if any(row.get("history_kind") != "version" for row in history):
        raise RuntimeError("destination contains a delete marker")
    keys = [str(row.get("Key", "")) for row in history]
    if len(keys) != len(set(keys)):
        raise RuntimeError("destination contains multiple versions for one key")
    current_keys = {
        str(row.get("Key", "")) for row in list_objects(bucket, prefix, region)
    }
    if current_keys != set(keys):
        raise RuntimeError("destination current-object and version inventories differ")

    snapshot: list[dict[str, Any]] = []
    for version in history:
        key = str(version.get("Key", ""))
        relative = safe_relative_key(key.removeprefix(prefix))
        version_id = str(version.get("VersionId", ""))
        if (
            not relative
            or relative == key
            or version_id in {"", "null", "None"}
            or version.get("IsLatest") is not True
        ):
            raise RuntimeError("destination history contains an invalid key/version")
        current = head(bucket, key, region, version_id)
        if (
            str(current.get("VersionId", "")) != version_id
            or int(current.get("ContentLength", -1)) <= 0
            or current.get("ChecksumType") != "FULL_OBJECT"
            or not checksums(current)
            or current.get("ServerSideEncryption") != "aws:kms"
            or current.get("SSEKMSKeyId") != kms_key_arn
        ):
            raise RuntimeError(
                f"destination exact-version custody failed: {relative}"
            )
        snapshot.append(
            {
                "relative_key": relative,
                "key": key,
                "version_id": version_id,
                "bytes": int(current.get("ContentLength", -1)),
                "etag": str(current.get("ETag", "")),
                "checksums": checksums(current),
                "checksum_type": str(current.get("ChecksumType", "")),
                "kms_key_id": str(current.get("SSEKMSKeyId", "")),
            }
        )
    snapshot.sort(key=lambda row: row["relative_key"])
    return snapshot


def destination_matches_receipt(
    source: list[dict[str, Any]],
    destination: list[dict[str, Any]],
    receipt_objects: list[dict[str, Any]],
) -> bool:
    source_by_relative = {str(row["relative_key"]): row for row in source}
    destination_by_relative = {
        str(row["relative_key"]): row for row in destination
    }
    receipt_by_relative = {
        str(row.get("relative_key", "")): row for row in receipt_objects
        if isinstance(row, dict)
    }
    if not (
        set(source_by_relative)
        == set(destination_by_relative)
        == set(receipt_by_relative)
    ):
        return False
    for relative, source_row in source_by_relative.items():
        destination_row = destination_by_relative[relative]
        receipt_destination = receipt_by_relative[relative].get("destination", {})
        if not isinstance(receipt_destination, dict):
            return False
        if (
            int(source_row.get("bytes", -1))
            != int(destination_row.get("bytes", -2))
            or destination_row.get("version_id")
            != receipt_destination.get("version_id")
            or destination_row.get("key") != receipt_destination.get("key")
            or receipt_by_relative[relative].get("status") != "passed"
        ):
            return False
    return True


def validate_execution_binding(
    receipt: dict[str, Any],
    *,
    job: dict[str, Any],
    job_id: str,
    run_id: str,
    source_bucket: str,
    source_prefix: str,
    region: str,
) -> tuple[str, str]:
    """Bind this freeze to the exact successful execution and its guarded tree."""
    batch = receipt.get("batch")
    worker = receipt.get("worker")
    captured_container = receipt.get("container")
    live_container = job.get("container")
    if (
        not isinstance(batch, dict)
        or not isinstance(worker, dict)
        or not isinstance(captured_container, dict)
        or not isinstance(live_container, dict)
    ):
        raise ValueError("execution receipt omits batch, container, or worker evidence")
    live_attempts = job.get("attempts")
    if not isinstance(live_attempts, list):
        raise ValueError("successful Batch job attempts are not a list")
    captured_attempts = batch.get("attempts")
    if not isinstance(captured_attempts, list):
        raise ValueError("execution receipt omits normalized Batch attempts")
    normalized_attempts = []
    for attempt in live_attempts:
        if not isinstance(attempt, dict):
            raise ValueError("successful Batch job attempt is not an object")
        attempt_container = attempt.get("container")
        if not isinstance(attempt_container, dict):
            attempt_container = {}
        exit_code = attempt_container.get("exitCode")
        normalized_attempts.append(
            {
                "started_at_epoch_ms": int(attempt.get("startedAt", 0)),
                "stopped_at_epoch_ms": int(attempt.get("stoppedAt", 0)),
                "status_reason": str(attempt.get("statusReason", "")),
                "container_instance_arn": str(
                    attempt_container.get("containerInstanceArn", "")
                ),
                "task_arn": str(attempt_container.get("taskArn", "")),
                "log_stream": str(attempt_container.get("logStreamName", "")),
                "exit_code": int(exit_code) if exit_code is not None else None,
                "reason": str(attempt_container.get("reason", "")),
            }
        )
    worker_checks = worker.get("checks")
    if (
        not exact_schema_version(receipt, 1)
        or receipt.get("run_id") != run_id
        or receipt.get("region") != region
        or batch.get("job_id") != job_id
        or batch.get("status") != "SUCCEEDED"
        or job.get("jobId") != job_id
        or job.get("status") != "SUCCEEDED"
        or batch.get("job_name") != job.get("jobName")
        or batch.get("job_definition_arn") != job.get("jobDefinition")
        or batch.get("command") != live_container.get("command")
        or batch.get("retry_strategy") != job.get("retryStrategy")
        or batch.get("timeout") != job.get("timeout")
        or batch.get("attempt_count") != len(normalized_attempts)
        or captured_attempts != normalized_attempts
        or len(normalized_attempts) != 1
        or normalized_attempts[0].get("exit_code") != 0
        or captured_container.get("task_arn") != live_container.get("taskArn")
        or batch.get("log_stream") != live_container.get("logStreamName")
        or worker_checks != EXPECTED_BATCH_WORKER_CHECKS
    ):
        raise ValueError("execution receipt does not match the exact successful Batch job")

    job_arn = str(job.get("jobArn", ""))
    arn_parts = job_arn.split(":", 5)
    if len(arn_parts) != 6 or arn_parts[0:3] != ["arn", "aws", "batch"]:
        raise ValueError("successful Batch job has an invalid ARN")
    arn_region, account_id = arn_parts[3], arn_parts[4]
    expected_bucket = f"diana-omics-work-{account_id}-{region}"
    expected_prefix = f"runs/diana-hrd/{run_id}/private-results/final/artifacts/"
    if arn_region != region or source_bucket != expected_bucket or source_prefix != expected_prefix:
        raise ValueError(
            "source prefix is not the guarded artifact tree for the captured execution"
        )
    worker_kms_key = str(worker.get("kms_key_id", ""))
    expected_kms_prefix = f"arn:aws:kms:{region}:{account_id}:key/"
    if not worker_kms_key.startswith(expected_kms_prefix):
        raise ValueError("execution receipt worker KMS key is outside the job account/region")
    return account_id, worker_kms_key


def copy_object(
    source_bucket: str,
    source_key: str,
    source_version_id: str,
    source_etag: str,
    destination_bucket: str,
    destination_key: str,
    kms_key_arn: str,
    checksum_algorithm: str,
    region: str,
) -> dict[str, Any]:
    encoded_source = f"{source_bucket}/{quote(source_key, safe='/')}"
    if source_version_id not in {"", "null", "None"}:
        encoded_source += f"?versionId={quote(source_version_id, safe='')}"
    return aws_json(
        [
            "s3api",
            "copy-object",
            "--copy-source",
            encoded_source,
            "--copy-source-if-match",
            source_etag,
            "--bucket",
            destination_bucket,
            "--key",
            destination_key,
            "--if-none-match",
            "*",
            "--server-side-encryption",
            "aws:kms",
            "--sse-kms-key-id",
            kms_key_arn,
            "--checksum-algorithm",
            checksum_algorithm,
        ],
        region,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execution-receipt", required=True, type=Path)
    parser.add_argument("--source-prefix", required=True)
    parser.add_argument("--destination-prefix", required=True)
    parser.add_argument("--kms-key-arn", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--anchor-output", required=True, type=Path)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run-receipt", type=Path)
    args = parser.parse_args()

    if args.dry_run_receipt is not None and not args.apply:
        raise SystemExit("Fail-closed: --dry-run-receipt is only valid with --apply")
    if args.apply and args.dry_run_receipt is None:
        raise SystemExit("Fail-closed: --apply requires --dry-run-receipt")

    resolved_paths = {
        args.execution_receipt.resolve(),
        args.output.resolve(),
        args.anchor_output.resolve(),
    }
    if len(resolved_paths) != 3:
        raise SystemExit("Fail-closed: receipt input/output paths must be distinct")
    try:
        require_new_output(args.output, "freeze receipt output")
        require_new_output(args.anchor_output, "freeze receipt anchor output")
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    source_bucket, source_prefix = parse_s3(args.source_prefix)
    destination_bucket, destination_prefix = parse_s3(args.destination_prefix)
    source_prefix = source_prefix.rstrip("/") + "/"
    destination_prefix = destination_prefix.rstrip("/") + "/"
    if source_bucket == destination_bucket and source_prefix == destination_prefix:
        raise SystemExit("Fail-closed: source and destination prefixes are identical")
    job_payload = aws_json(["batch", "describe-jobs", "--jobs", args.job_id], args.region)
    jobs = job_payload.get("jobs", [])
    if len(jobs) != 1 or jobs[0].get("status") != "SUCCEEDED":
        raise SystemExit("Fail-closed: deterministic Batch job is not SUCCEEDED")
    try:
        execution_receipt = load_json(args.execution_receipt)
        account_id, worker_kms_key = validate_execution_binding(
            execution_receipt,
            job=jobs[0],
            job_id=args.job_id,
            run_id=args.run_id,
            source_bucket=source_bucket,
            source_prefix=source_prefix,
            region=args.region,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: invalid execution receipt: {error}") from error

    expected_destination_bucket = (
        f"diana-omics-private-results-{account_id}-{args.region}"
    )
    expected_destination_prefix = (
        f"runs/subject01/{args.run_id}/deterministic/final/"
    )
    if (
        destination_bucket != expected_destination_bucket
        or destination_prefix != expected_destination_prefix
        or args.kms_key_arn != worker_kms_key
    ):
        raise SystemExit(
            "Fail-closed: destination bucket/prefix/KMS does not exactly match the "
            "captured alias-only execution"
        )
    try:
        require_bucket_versioning(destination_bucket, args.region)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    initial_inventory = snapshot_inventory(source_bucket, source_prefix, args.region)
    if not initial_inventory:
        raise SystemExit("Fail-closed: completed job has no source artifacts")
    initial_destination_history = version_history(
        destination_bucket, destination_prefix, args.region
    )
    if args.apply and initial_destination_history:
        raise SystemExit(
            "Fail-closed: durable destination prefix has object or delete-marker history"
        )

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "dry_run" if not args.apply else "in_progress",
        "generated_at": now(),
        "run_id": args.run_id,
        "batch_job_id": args.job_id,
        "batch_status": "SUCCEEDED",
        "execution_receipt": {
            "path": str(args.execution_receipt.resolve()),
            "sha256": sha256(args.execution_receipt),
        },
        "source_prefix": args.source_prefix.rstrip("/") + "/",
        "destination_prefix": args.destination_prefix.rstrip("/") + "/",
        "kms_key_arn": args.kms_key_arn,
        "script_sha256": sha256(Path(__file__)),
        "destination_bucket_versioning": "Enabled",
        "destination_initial_version_history_count": len(
            initial_destination_history
        ),
        "receipt_anchor_strategy": "sha256_content_addressed_create_only",
        "object_count": len(initial_inventory),
        "initial_inventory_identity": inventory_identity(initial_inventory),
        "objects": [],
    }
    dry_run_receipt = {
        **receipt,
        "status": "dry_run",
        "objects": dry_run_objects(
            initial_inventory,
            source_bucket,
            destination_bucket,
            destination_prefix,
        ),
        "final_inventory_identity": receipt["initial_inventory_identity"],
        "checks": dict(EXPECTED_DRY_RUN_CHECKS),
        "completed_at": "dry-run-preflight",
        "passed_count": 0,
    }
    if args.dry_run_receipt is not None:
        try:
            validate_dry_run_receipt(args.dry_run_receipt, dry_run_receipt)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise SystemExit(f"Fail-closed: {error}") from error
    write_json_atomic(args.output, receipt, create=True)

    try:
        for initial_row in initial_inventory:
            source_key = str(initial_row["key"])
            relative = str(initial_row["relative_key"])
            destination_key = destination_prefix + relative
            before = head(source_bucket, source_key, args.region)
            source_version_id = str(before.get("VersionId", ""))
            if (
                int(before.get("ContentLength", -1)) <= 0
                or int(before.get("ContentLength", -1)) > MAX_SINGLE_COPY_BYTES
                or source_version_id in {"", "None"}
                or before.get("ChecksumType") != "FULL_OBJECT"
                or not checksums(before)
            ):
                raise RuntimeError(
                    "source object lacks a positive single-copy size, current VersionId, "
                    f"or full-object checksum: {relative}"
                )
            listed_stable = (
                int(initial_row.get("bytes", -1)) == int(before.get("ContentLength", -2))
                and str(initial_row.get("etag", "")) == str(before.get("ETag", ""))
                and str(initial_row.get("version_id", "")) == source_version_id
            )
            if not listed_stable:
                raise RuntimeError(f"source inventory changed before freeze: {relative}")
            row: dict[str, Any] = {
                "relative_key": relative,
                "source": {
                    "bucket": source_bucket,
                    "key": source_key,
                    "version_id": source_version_id,
                    "bytes": int(before.get("ContentLength", -1)),
                    "etag": str(before.get("ETag", "")),
                    "checksums": checksums(before),
                    "checksum_type": str(before.get("ChecksumType", "")),
                },
                "destination": {"bucket": destination_bucket, "key": destination_key},
                "status": "in_progress" if args.apply else "dry_run",
            }
            receipt["objects"].append(row)
            write_json_atomic(args.output, receipt)
            if args.apply:
                copy_result = copy_object(
                    source_bucket,
                    source_key,
                    source_version_id,
                    str(before.get("ETag", "")),
                    destination_bucket,
                    destination_key,
                    args.kms_key_arn,
                    preferred_checksum_algorithm(before),
                    args.region,
                )
                copied_version_id = str(copy_result.get("VersionId", ""))
                row["copy_result"] = {
                    "version_id": copied_version_id,
                    "checksum_algorithm": preferred_checksum_algorithm(before),
                }
                write_json_atomic(args.output, receipt)
                if copied_version_id in {"", "null", "None"}:
                    raise RuntimeError(
                        f"copy response omitted a durable VersionId: {relative}"
                    )
                after_source = head(source_bucket, source_key, args.region)
                destination = head(
                    destination_bucket,
                    destination_key,
                    args.region,
                    copied_version_id,
                )
                source_stable = (
                    int(before.get("ContentLength", -1)) == int(after_source.get("ContentLength", -2))
                    and str(before.get("ETag", "")) == str(after_source.get("ETag", ""))
                    and source_version_id == str(after_source.get("VersionId", ""))
                    and checksums(before) == checksums(after_source)
                    and before.get("ChecksumType") == after_source.get("ChecksumType") == "FULL_OBJECT"
                )
                size_matches = int(before.get("ContentLength", -1)) == int(destination.get("ContentLength", -2))
                checksum_matches = common_checksum_matches(before, destination)
                kms_matches = (
                    destination.get("ServerSideEncryption") == "aws:kms"
                    and destination.get("SSEKMSKeyId") == args.kms_key_arn
                )
                versioned = str(destination.get("VersionId", "")) not in {"", "null", "None"}
                copy_version_matches = (
                    versioned
                    and copied_version_id
                    == str(destination.get("VersionId", ""))
                )
                row["destination"].update(
                    {
                        "version_id": str(destination.get("VersionId", "")),
                        "bytes": int(destination.get("ContentLength", -1)),
                        "etag": str(destination.get("ETag", "")),
                        "checksums": checksums(destination),
                        "checksum_type": str(destination.get("ChecksumType", "")),
                        "server_side_encryption": str(destination.get("ServerSideEncryption", "")),
                        "kms_key_id": str(destination.get("SSEKMSKeyId", "")),
                    }
                )
                row["checks"] = {
                    "listed_inventory_stable": listed_stable,
                    "source_stable": source_stable,
                    "size_matches": size_matches,
                    "common_checksum_matches": checksum_matches,
                    "exact_kms_matches": kms_matches,
                    "destination_versioned": versioned,
                    "copy_response_version_matches": copy_version_matches,
                }
                row["status"] = "passed" if all(row["checks"].values()) else "failed"
                write_json_atomic(args.output, receipt)
                if row["status"] != "passed":
                    raise RuntimeError(f"copy verification failed for {relative}: {row['checks']}")
        final_inventory = snapshot_inventory(source_bucket, source_prefix, args.region)
        receipt["final_inventory_identity"] = inventory_identity(final_inventory)
        receipt["checks"] = {
            "execution_receipt_bound": True,
            "complete_source_inventory_unchanged": (
                inventory_identity(initial_inventory)
                == inventory_identity(final_inventory)
            ),
        }
        if args.apply:
            destination_inventory = snapshot_destination(
                destination_bucket,
                destination_prefix,
                args.kms_key_arn,
                args.region,
            )
            receipt["destination_inventory"] = destination_inventory
            receipt["checks"]["destination_exact_history_and_receipt_match"] = (
                destination_matches_receipt(
                    initial_inventory,
                    destination_inventory,
                    receipt["objects"],
                )
            )
        if not all(receipt["checks"].values()):
            raise RuntimeError(
                f"complete freeze inventory validation failed: {receipt['checks']}"
            )
        receipt["status"] = "passed" if args.apply else "dry_run"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error"] = f"{type(error).__name__}: {error}"
        receipt["completed_at"] = now()
        receipt["passed_count"] = sum(
            row.get("status") == "passed"
            for row in receipt.get("objects", [])
            if isinstance(row, dict)
        )
        try:
            receipt["created_or_observed_versions"] = version_history(
                destination_bucket, destination_prefix, args.region
            )
        except Exception as history_error:
            receipt["destination_history_error"] = (
                f"{type(history_error).__name__}: {history_error}"
            )
        write_json_atomic(args.output, receipt)
        raise

    receipt["completed_at"] = now()
    receipt["passed_count"] = sum(
        row.get("status") == "passed"
        for row in receipt["objects"]
        if isinstance(row, dict)
    )
    write_json_atomic(args.output, receipt)

    if args.apply:
        receipt_sha = sha256(args.output)
        receipt_key = (
            f"runs/subject01/{args.run_id}/deterministic/provenance/"
            f"final-artifact-freeze-receipts/{receipt_sha}.json"
        )
        anchor: dict[str, Any] = {
            "schema_version": 1,
            "status": "in_progress",
            "run_id": args.run_id,
            "batch_job_id": args.job_id,
            "receipt_sha256": receipt_sha,
            "receipt_bytes": args.output.stat().st_size,
            "receipt_uri": f"s3://{destination_bucket}/{receipt_key}",
            "receipt_version_id": "",
            "checks": {},
        }
        write_json_atomic(args.anchor_output, anchor, create=True)
        try:
            if version_history(destination_bucket, receipt_key, args.region):
                raise RuntimeError(
                    "content-addressed receipt key already has version history"
                )
            uploaded = put_receipt(
                args.output,
                destination_bucket,
                receipt_key,
                args.kms_key_arn,
                args.region,
            )
            version_id = str(uploaded.get("VersionId", ""))
            anchor["receipt_version_id"] = version_id
            write_json_atomic(args.anchor_output, anchor)
            if version_id in {"", "null", "None"}:
                raise RuntimeError("receipt upload omitted a durable VersionId")
            anchored = head(
                destination_bucket, receipt_key, args.region, version_id
            )
            with tempfile.TemporaryDirectory(
                prefix="diana-final-freeze-receipt-"
            ) as temporary:
                downloaded = Path(temporary) / "receipt.json"
                get_result = get_exact_object(
                    destination_bucket,
                    receipt_key,
                    version_id,
                    downloaded,
                    args.region,
                )
                require_real_downloaded_file(
                    downloaded,
                    "downloaded final-freeze receipt",
                )
                downloaded_sha = sha256(downloaded)
                downloaded_bytes = downloaded.stat().st_size
            expected_checksum = base64.b64encode(
                bytes.fromhex(receipt_sha)
            ).decode("ascii")
            receipt_history = version_history(
                destination_bucket, receipt_key, args.region
            )
            anchor["checks"] = {
                "version_exact": anchored.get("VersionId")
                == get_result.get("VersionId")
                == version_id,
                "bytes_exact": int(anchored.get("ContentLength", -1))
                == downloaded_bytes
                == args.output.stat().st_size,
                "sha256_exact": downloaded_sha == receipt_sha,
                "sha256_checksum_exact": anchored.get("ChecksumType")
                == get_result.get("ChecksumType")
                == "FULL_OBJECT"
                and anchored.get("ChecksumSHA256")
                == get_result.get("ChecksumSHA256")
                == expected_checksum,
                "exact_kms": anchored.get("ServerSideEncryption")
                == get_result.get("ServerSideEncryption")
                == "aws:kms"
                and anchored.get("SSEKMSKeyId")
                == get_result.get("SSEKMSKeyId")
                == args.kms_key_arn,
                "single_create_only_version": len(receipt_history) == 1
                and receipt_history[0].get("history_kind") == "version"
                and receipt_history[0].get("Key") == receipt_key
                and receipt_history[0].get("VersionId") == version_id,
            }
            if not all(anchor["checks"].values()):
                raise RuntimeError(
                    f"receipt anchor validation failed: {anchor['checks']}"
                )
            anchor["status"] = "passed"
            anchor["completed_at"] = now()
            write_json_atomic(args.anchor_output, anchor)
        except Exception as error:
            anchor["status"] = "failed"
            anchor["error"] = f"{type(error).__name__}: {error}"
            anchor["completed_at"] = now()
            try:
                anchor["created_or_observed_versions"] = version_history(
                    destination_bucket, receipt_key, args.region
                )
            except Exception as history_error:
                anchor["history_error"] = (
                    f"{type(history_error).__name__}: {history_error}"
                )
            write_json_atomic(args.anchor_output, anchor)
            raise
    print(json.dumps({"status": receipt["status"], "objects": len(initial_inventory), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
