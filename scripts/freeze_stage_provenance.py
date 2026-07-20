#!/usr/bin/env python3
"""Freeze WGS preflight/gather evidence from expiring work storage.

The source bucket is deliberately unversioned.  This helper therefore binds
each small JSON source with an ETag precondition, re-heads it after the copy,
and proves byte identity by SHA-256 against the exact destination VersionId.
The receipt is uploaded under its own SHA-256 in the private versioned bucket.
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
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
)
from capture_batch_provenance import EXPECTED_BATCH_WORKER_CHECKS

SOURCE_NAMES = ("preflight.json", "gather.json")
REFERENCE_LABEL = "ucsc_hg38_analysis_set_full"
PREFLIGHT_REFERENCE_LABEL = "UCSC hg38 analysis set full"
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
EXPECTED_DRY_RUN_CHECKS = {
    "get_matches_head": True,
    "local_bytes_exact": True,
    "semantic_binding": True,
    "source_kms_exact": True,
}
EXPECTED_DRY_RUN_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "generated_at",
        "run_id",
        "batch_job_id",
        "batch_status",
        "execution_receipt_sha256",
        "source_prefix",
        "destination_prefix",
        "kms_key_arn",
        "source_bucket_versioning",
        "destination_bucket_versioning",
        "destination_initial_version_history_count",
        "script_sha256",
        "receipt_anchor_strategy",
        "objects",
        "completed_at",
        "object_count",
        "passed_count",
    }
)
EXPECTED_DRY_RUN_OBJECT_KEYS = frozenset(
    {"name", "source", "destination", "checks", "status"}
)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_real_hash_input(path: Path) -> None:
    label = f"{path.name} SHA-256 input"
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent must not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent must be a directory: {parent}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def sha256(path: Path) -> str:
    require_real_hash_input(path)
    data = path.read_bytes()
    digest = sha256_bytes(data)
    if sha256_bytes(path.read_bytes()) != digest:
        raise ValueError(f"{path.name} SHA-256 input changed during read")
    return digest


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exact_schema_version(payload: dict[str, Any], expected: int) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def is_positive_exact_int(value: Any) -> bool:
    return type(value) is int and value > 0


def exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and type(expected) is int and value == expected


def exact_batch_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an exact integer")
    return value


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def load_json_with_sha256(path: Path) -> tuple[dict[str, Any], str]:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"JSON document parent must not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"JSON document parent must be a directory: {parent}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"JSON document must be a real file: {path}")
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in JSON document: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    if sha256(path) != digest:
        raise ValueError(f"JSON document changed during read: {path}")
    return value, digest


def load_json(path: Path) -> dict[str, Any]:
    return load_json_with_sha256(path)[0]


def valid_version_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value
        and value.lower() not in {"null", "none"}
        and not any(character.isspace() for character in value)
    )


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def exact_full_object_checksum_type(value: Any, label: str) -> str:
    if not isinstance(value, str) or value != "FULL_OBJECT":
        raise RuntimeError(f"{label} omitted an exact full-object checksum type")
    return value


def exact_version_id(value: Any, label: str) -> str:
    if not valid_version_id(value):
        raise RuntimeError(f"{label} omitted an exact S3 VersionId")
    return value


def exact_s3_etag(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() for character in value)
        or value.lower() in {"none", "null"}
    ):
        raise RuntimeError(f"{label} omitted an exact S3 ETag")
    return value


def same_exact_s3_etag(left: Any, right: Any) -> bool:
    try:
        return exact_s3_etag(left, "left S3 ETag") == exact_s3_etag(
            right,
            "right S3 ETag",
        )
    except RuntimeError:
        return False


def null_version_id(value: Any) -> bool:
    return value is None or value == "null"


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


def require_safe_new_output(path: Path, label: str) -> None:
    require_safe_output_parent(path, label)
    if path.exists():
        raise ValueError(f"{label} already exists: {path}")


def require_safe_download_destination(path: Path, label: str) -> None:
    require_safe_output_parent(path, label)


def require_real_downloaded_file(path: Path, label: str) -> None:
    require_safe_download_destination(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def write_bytes_once(path: Path, payload: bytes) -> None:
    """Atomically create a local receipt without replacing prior evidence."""
    require_safe_output_parent(path, "local evidence output")
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    fd, temporary_value = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_value)
    linked = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            linked = True
        except FileExistsError as error:
            raise RuntimeError(f"refusing to replace existing local evidence: {path}") from error
        fsync_directory(path.parent)
        require_installed_local_evidence(path, expected_sha256)
    except Exception:
        if linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def require_installed_local_evidence(path: Path, expected_sha256: str) -> None:
    require_real_downloaded_file(path, "local evidence output")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"local evidence output mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"local evidence output changed during write: {path}")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    write_bytes_once(
        path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def aws_json(arguments: list[str], region: str) -> dict[str, Any]:
    command = ["aws", *arguments, "--region", region, "--output", "json"]
    value = json.loads(subprocess.check_output(command, text=True))
    if not isinstance(value, dict):
        raise RuntimeError(f"AWS command did not return an object: {' '.join(command)}")
    return value


def checksums(head: dict[str, Any]) -> dict[str, str]:
    return {
        field: value
        for field in CHECKSUM_FIELDS
        if isinstance((value := head.get(field)), str) and value.strip()
    }


def preferred_checksum_algorithm(head: dict[str, Any]) -> str:
    for field in CHECKSUM_FIELDS:
        value = head.get(field)
        if isinstance(value, str) and value.strip():
            return CHECKSUM_ALGORITHMS[field]
    raise ValueError("source object has no supported checksum")


def head_object(
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


def download_object(
    bucket: str,
    key: str,
    destination: Path,
    region: str,
    *,
    etag: str = "",
    version_id: str = "",
) -> dict[str, Any]:
    require_safe_download_destination(destination, "downloaded provenance object")
    arguments = [
        "s3api",
        "get-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--checksum-mode",
        "ENABLED",
    ]
    if etag:
        arguments.extend(["--if-match", etag])
    if version_id:
        arguments.extend(["--version-id", version_id])
    arguments.append(str(destination))
    response = aws_json(arguments, region)
    require_real_downloaded_file(destination, "downloaded provenance object")
    return response


def copy_object(
    source_bucket: str,
    source_key: str,
    source_etag: str,
    destination_bucket: str,
    destination_key: str,
    kms_key_arn: str,
    checksum_algorithm: str,
    region: str,
) -> dict[str, Any]:
    return aws_json(
        [
            "s3api",
            "copy-object",
            "--copy-source",
            f"{source_bucket}/{quote(source_key, safe='/')}",
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
        payload = aws_json(arguments, region)
        for field in ("Versions", "DeleteMarkers"):
            value = payload.get(field, [])
            if not isinstance(value, list) or any(
                not isinstance(row, dict) for row in value
            ):
                raise RuntimeError("destination version history is malformed")
            rows.extend({"history_type": field, **row} for row in value)
        if payload.get("IsTruncated") is not True:
            return rows
        key_marker, version_id_marker = require_next_version_history_markers(payload)
        marker = (key_marker, version_id_marker)
        if marker in seen_markers:
            raise RuntimeError("destination version history pagination did not advance")
        seen_markers.add(marker)


def require_next_version_history_markers(payload: dict[str, Any]) -> tuple[str, str]:
    key_marker = payload.get("NextKeyMarker")
    version_id_marker = payload.get("NextVersionIdMarker")
    if (
        not isinstance(key_marker, str)
        or not isinstance(version_id_marker, str)
        or not key_marker
        or not version_id_marker
    ):
        raise RuntimeError(
            "truncated version history omitted its next key/version markers"
        )
    return key_marker, version_id_marker


def bucket_versioning(bucket: str, region: str) -> str:
    return str(
        aws_json(["s3api", "get-bucket-versioning", "--bucket", bucket], region).get(
            "Status", ""
        )
    )


def validate_kms_arn(kms_key_arn: str, account_id: str, region: str) -> None:
    expected = re.compile(
        rf"^arn:aws:kms:{re.escape(region)}:{re.escape(account_id)}:key/[A-Za-z0-9-]+$"
    )
    if not expected.fullmatch(kms_key_arn):
        raise ValueError("KMS key ARN is outside the exact destination account and region")


def expected_execution_command(source_bucket: str, run_id: str, region: str) -> list[str]:
    launch_uri = (
        f"s3://{source_bucket}/runs/diana-hrd/{run_id}/inputs/"
        "diana_hrd_wgs_worker.py"
    )
    return [
        "bash",
        "-lc",
        "set -euo pipefail; mkdir -p /work/runner; "
        f"/opt/diana-aws/bin/aws s3 cp {launch_uri} /work/runner/worker.py "
        f"--region {region} --only-show-errors; "
        f"python3 -u /work/runner/worker.py evidence --run-id {run_id}",
    ]


def validate_execution(
    receipt: dict[str, Any],
    job: dict[str, Any],
    job_id: str,
    run_id: str,
    region: str,
    kms_key_arn: str,
) -> str:
    batch = receipt.get("batch")
    worker = receipt.get("worker")
    captured_container = receipt.get("container")
    live_container = job.get("container")
    worker_checks = worker.get("checks") if isinstance(worker, dict) else None
    if not isinstance(batch, dict) or not isinstance(worker, dict):
        raise ValueError("execution receipt omits Batch or worker evidence")
    if not isinstance(captured_container, dict) or not isinstance(live_container, dict):
        raise ValueError("execution receipt omits container evidence")
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
                "started_at_epoch_ms": exact_batch_int(
                    attempt.get("startedAt"),
                    "Batch startedAt",
                ),
                "stopped_at_epoch_ms": exact_batch_int(
                    attempt.get("stoppedAt"),
                    "Batch stoppedAt",
                ),
                "status_reason": str(attempt.get("statusReason", "")),
                "container_instance_arn": str(
                    attempt_container.get("containerInstanceArn", "")
                ),
                "task_arn": str(attempt_container.get("taskArn", "")),
                "log_stream": str(attempt_container.get("logStreamName", "")),
                "exit_code": (
                    exact_batch_int(exit_code, "Batch exitCode")
                    if exit_code is not None
                    else None
                ),
                "reason": str(attempt_container.get("reason", "")),
            }
        )
    arn = str(job.get("jobArn", "")).split(":", 5)
    if (
        len(arn) != 6
        or arn[:3] != ["arn", "aws", "batch"]
        or arn[3] != region
        or arn[5] != f"job/{job_id}"
        or not re.fullmatch(r"\d{12}", arn[4])
    ):
        raise ValueError("successful Batch job has an invalid ARN")
    account_id = arn[4]
    source_bucket = f"diana-omics-work-{account_id}-{region}"
    destination_bucket = f"diana-omics-private-results-{account_id}-{region}"
    expected_command = expected_execution_command(source_bucket, run_id, region)
    worker_sha = worker.get("sha256")
    launch_uri = (
        f"s3://{source_bucket}/runs/diana-hrd/{run_id}/inputs/"
        "diana_hrd_wgs_worker.py"
    )
    executed_uri = (
        f"s3://{destination_bucket}/runs/subject01/{run_id}/deterministic/"
        f"provenance/executed-workers/{worker_sha}.py"
    )
    if (
        not exact_schema_version(receipt, 1)
        or receipt.get("run_id") != run_id
        or receipt.get("region") != region
        or not isinstance(batch, dict)
        or batch.get("job_id") != job_id
        or batch.get("status") != "SUCCEEDED"
        or job.get("jobId") != job_id
        or job.get("status") != "SUCCEEDED"
        or batch.get("job_name") != job.get("jobName")
        or batch.get("job_definition_arn") != job.get("jobDefinition")
        or batch.get("job_queue_arn") != job.get("jobQueue")
        or batch.get("job_role_arn") != live_container.get("jobRoleArn")
        or batch.get("log_stream") != live_container.get("logStreamName")
        or batch.get("command") != live_container.get("command")
        or batch.get("command") != expected_command
        or batch.get("retry_strategy") != job.get("retryStrategy")
        or batch.get("timeout") != job.get("timeout")
        or not exact_int(batch.get("attempt_count"), len(normalized_attempts))
        or captured_attempts != normalized_attempts
        or len(normalized_attempts) != 1
        or normalized_attempts[0].get("exit_code") != 0
        or captured_container.get("image_reference") != live_container.get("image")
        or captured_container.get("task_arn") != live_container.get("taskArn")
        or worker.get("launch_uri") != launch_uri
        or worker.get("executed_uri") != executed_uri
        or not valid_version_id(worker.get("executed_version_id"))
        or not valid_version_id(worker.get("freeze_receipt_version_id"))
        or not valid_sha256(worker_sha)
        or not is_positive_exact_int(worker.get("bytes"))
        or worker.get("server_side_encryption") != "aws:kms"
        or worker.get("kms_key_id") != kms_key_arn
        or worker_checks != EXPECTED_BATCH_WORKER_CHECKS
    ):
        raise ValueError("execution receipt does not match the exact successful Batch job")
    expected_worker_checksum = base64.b64encode(bytes.fromhex(worker_sha)).decode("ascii")
    if (worker.get("checksums") or {}).get("ChecksumSHA256") != expected_worker_checksum:
        raise ValueError("executed worker SHA-256 checksum is not exact")
    return account_id


def source_stable(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        is_positive_exact_int(before.get("ContentLength"))
        and exact_int(after.get("ContentLength"), before["ContentLength"])
        and same_exact_s3_etag(before.get("ETag"), after.get("ETag"))
        and checksums(before) == checksums(after)
        and before.get("ChecksumType") == after.get("ChecksumType") == "FULL_OBJECT"
        and null_version_id(before.get("VersionId"))
        and null_version_id(after.get("VersionId"))
        and before.get("ContentType") == after.get("ContentType") == "application/json"
        and before.get("ServerSideEncryption")
        == after.get("ServerSideEncryption")
        == "aws:kms"
        and before.get("SSEKMSKeyId") == after.get("SSEKMSKeyId")
    )


def response_matches_head(
    response: dict[str, Any],
    head: dict[str, Any],
    local_path: Path,
    *,
    expected_version_id: str,
) -> bool:
    response_version = response.get("VersionId")
    return (
        response_version == expected_version_id
        and exact_int(response.get("ContentLength"), local_path.stat().st_size)
        and exact_int(head.get("ContentLength"), local_path.stat().st_size)
        and same_exact_s3_etag(response.get("ETag"), head.get("ETag"))
        and checksums(response) == checksums(head)
        and response.get("ChecksumType") == head.get("ChecksumType") == "FULL_OBJECT"
        and response.get("ServerSideEncryption")
        == head.get("ServerSideEncryption")
        == "aws:kms"
        and response.get("SSEKMSKeyId") == head.get("SSEKMSKeyId")
        and response.get("ContentType")
        == head.get("ContentType")
        == "application/json"
    )


def validate_source_document(name: str, document: dict[str, Any], run_id: str) -> None:
    if document.get("status") != "passed" or document.get("run_id") != run_id:
        raise ValueError(f"{name} is not bound to the exact passed run")
    if name == "preflight.json":
        tools = document.get("tools")
        if (
            document.get("reference") != PREFLIGHT_REFERENCE_LABEL
            or document.get("wgs_lanes") != 8
            or not is_positive_exact_int(document.get("wgs_bytes"))
            or document.get("boundary")
            != "Preflight only; no sample interpretation."
            or not isinstance(tools, dict)
            or set(tools) != {"bwa", "samtools", "bcftools", "java", "aws"}
            or not all(isinstance(path, str) and path.startswith("/") for path in tools.values())
        ):
            raise ValueError("preflight.json has invalid WGS stage semantics")
        return
    if name != "gather.json":
        raise ValueError(f"unexpected stage provenance source: {name}")
    samples = document.get("samples")
    if not isinstance(samples, list) or len(samples) != 2:
        raise ValueError("gather.json does not contain exactly two sample roles")
    by_role = {
        str(sample.get("role", "")): sample
        for sample in samples
        if isinstance(sample, dict)
    }
    if set(by_role) != {"normal", "tumor"}:
        raise ValueError("gather.json roles are not exactly normal and tumor")
    for role, sample in by_role.items():
        if (
            sample.get("status") != "passed"
            or not exact_int(sample.get("lane_count"), 4)
            or sample.get("output_bam") != f"{role}.markdup.bam"
            or not is_positive_exact_int(sample.get("output_bam_bytes"))
        ):
            raise ValueError(f"gather.json has invalid {role} sample semantics")
    if (
        document.get("reference") != REFERENCE_LABEL
        or document.get("duplicate_marking")
        != "samtools fixmate -m per lane followed by merged samtools markdup"
    ):
        raise ValueError("gather.json has invalid reference or duplicate-marking semantics")


def prepare_source_row(
    *,
    name: str,
    source_bucket: str,
    source_prefix: str,
    destination_bucket: str,
    destination_prefix: str,
    kms_key_arn: str,
    run_id: str,
    region: str,
    temp: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    source_key = source_prefix + name
    destination_key = destination_prefix + name
    before = head_object(source_bucket, source_key, region)
    source_size = before.get("ContentLength")
    try:
        source_etag = exact_s3_etag(before.get("ETag"), f"source {name}")
    except RuntimeError as error:
        raise RuntimeError(f"invalid unversioned source object: {name}") from error
    if (
        not is_positive_exact_int(source_size)
        or before.get("ChecksumType") != "FULL_OBJECT"
        or not checksums(before)
        or not null_version_id(before.get("VersionId"))
        or before.get("ContentType") != "application/json"
        or before.get("ServerSideEncryption") != "aws:kms"
        or before.get("SSEKMSKeyId") != kms_key_arn
    ):
        raise RuntimeError(f"invalid unversioned source object: {name}")
    source_local = temp / f"source-{name}"
    downloaded_source = download_object(
        source_bucket,
        source_key,
        source_local,
        region,
        etag=source_etag,
    )
    require_real_downloaded_file(
        source_local,
        f"downloaded source {name}",
    )
    if not response_matches_head(
        downloaded_source,
        before,
        source_local,
        expected_version_id="null",
    ):
        raise RuntimeError(f"source get response did not match head: {name}")
    try:
        source_document, source_sha = load_json_with_sha256(source_local)
        validate_source_document(name, source_document, run_id)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    return (
        {
            "name": name,
            "source": {
                "bucket": source_bucket,
                "key": source_key,
                "version_id": "null",
                "bytes": source_size,
                "etag": source_etag,
                "checksums": checksums(before),
                "checksum_type": "FULL_OBJECT",
                "sha256": source_sha,
                "server_side_encryption": "aws:kms",
                "kms_key_id": kms_key_arn,
                "get_response": downloaded_source,
            },
            "destination": {
                "bucket": destination_bucket,
                "key": destination_key,
            },
            "checks": dict(EXPECTED_DRY_RUN_CHECKS),
            "status": "dry_run",
        },
        before,
        source_sha,
    )


def validate_dry_run_receipt(path: Path, expected: dict[str, Any]) -> None:
    receipt = load_json(path)
    observed_keys = set(receipt)
    if observed_keys != EXPECTED_DRY_RUN_RECEIPT_KEYS:
        raise ValueError(
            "stage provenance dry-run receipt has stale or missing metadata: "
            f"missing={sorted(EXPECTED_DRY_RUN_RECEIPT_KEYS - observed_keys)} "
            f"unexpected={sorted(observed_keys - EXPECTED_DRY_RUN_RECEIPT_KEYS)}"
        )
    if (
        not exact_schema_version(receipt, 1)
        or receipt.get("status") != "dry_run"
        or receipt.get("batch_status") != "SUCCEEDED"
        or not exact_int(receipt.get("object_count"), len(SOURCE_NAMES))
        or not exact_int(receipt.get("passed_count"), 0)
        or not exact_int(
            receipt.get("destination_initial_version_history_count"),
            0,
        )
        or not isinstance(receipt.get("generated_at"), str)
        or not receipt.get("generated_at")
        or not isinstance(receipt.get("completed_at"), str)
        or not receipt.get("completed_at")
    ):
        raise ValueError("stage provenance dry-run receipt did not pass preflight")

    bound_fields = (
        "run_id",
        "batch_job_id",
        "execution_receipt_sha256",
        "source_prefix",
        "destination_prefix",
        "kms_key_arn",
        "source_bucket_versioning",
        "destination_bucket_versioning",
        "destination_initial_version_history_count",
        "script_sha256",
        "receipt_anchor_strategy",
        "object_count",
    )
    if any(receipt.get(field) != expected.get(field) for field in bound_fields):
        raise ValueError(
            "stage provenance dry-run receipt does not match this apply"
        )

    observed_objects = receipt.get("objects")
    expected_objects = expected.get("objects")
    if not isinstance(observed_objects, list) or observed_objects != expected_objects:
        raise ValueError(
            "stage provenance dry-run receipt object evidence does not "
            "match this apply"
        )
    for row in observed_objects:
        if (
            not isinstance(row, dict)
            or set(row) != EXPECTED_DRY_RUN_OBJECT_KEYS
            or row.get("checks") != EXPECTED_DRY_RUN_CHECKS
            or row.get("status") != "dry_run"
        ):
            raise ValueError(
                "stage provenance dry-run receipt has stale or malformed "
                "object metadata"
            )


def exact_history_matches(
    actual: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> bool:
    def normalized(row: dict[str, Any]) -> tuple[Any, ...] | None:
        size = row.get("Size")
        version_id = row.get("VersionId")
        if not is_positive_exact_int(size) or not valid_version_id(version_id):
            return None
        try:
            etag = exact_s3_etag(row.get("ETag"), "destination history")
        except RuntimeError:
            return None
        return (
            str(row.get("history_type", "")),
            str(row.get("Key", "")),
            version_id,
            row.get("IsLatest") is True,
            size,
            etag,
        )

    actual_normalized = [normalized(row) for row in actual]
    expected_normalized = [normalized(row) for row in expected]
    return (
        None not in actual_normalized
        and None not in expected_normalized
        and sorted(actual_normalized) == sorted(expected_normalized)
    )


def put_receipt(
    path: Path, bucket: str, key: str, kms_key_arn: str, region: str
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execution-receipt", required=True, type=Path)
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
    try:
        require_safe_new_output(args.output, "freeze receipt output")
        require_safe_new_output(args.anchor_output, "freeze receipt anchor output")
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    job_payload = aws_json(["batch", "describe-jobs", "--jobs", args.job_id], args.region)
    jobs = job_payload.get("jobs", [])
    if not isinstance(jobs, list) or len(jobs) != 1:
        raise SystemExit("Fail-closed: exact deterministic Batch job was not found")
    execution = load_json(args.execution_receipt)
    try:
        account_id = validate_execution(
            execution,
            jobs[0],
            args.job_id,
            args.run_id,
            args.region,
            args.kms_key_arn,
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    source_bucket = f"diana-omics-work-{account_id}-{args.region}"
    source_prefix = f"runs/diana-hrd/{args.run_id}/private-results/"
    destination_bucket = f"diana-omics-private-results-{account_id}-{args.region}"
    destination_prefix = (
        f"runs/subject01/{args.run_id}/deterministic/provenance/wgs-stage/"
    )
    try:
        validate_kms_arn(args.kms_key_arn, account_id, args.region)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    source_versioning = bucket_versioning(source_bucket, args.region)
    destination_versioning = bucket_versioning(destination_bucket, args.region)
    if source_versioning != "Suspended" or destination_versioning != "Enabled":
        raise SystemExit(
            "Fail-closed: source must be versioning-suspended and destination versioning-enabled"
        )
    initial_destination_history = version_history(
        destination_bucket, destination_prefix, args.region
    )
    if initial_destination_history:
        raise SystemExit("Fail-closed: private provenance destination has version history")

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress" if args.apply else "dry_run",
        "generated_at": now(),
        "run_id": args.run_id,
        "batch_job_id": args.job_id,
        "batch_status": "SUCCEEDED",
        "execution_receipt_sha256": sha256(args.execution_receipt),
        "source_prefix": f"s3://{source_bucket}/{source_prefix}",
        "destination_prefix": f"s3://{destination_bucket}/{destination_prefix}",
        "kms_key_arn": args.kms_key_arn,
        "source_bucket_versioning": source_versioning,
        "destination_bucket_versioning": destination_versioning,
        "destination_initial_version_history_count": len(initial_destination_history),
        "script_sha256": sha256(Path(__file__)),
        "receipt_anchor_strategy": "sha256_content_addressed_never_overwritten",
        "objects": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.anchor_output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="diana-wgs-provenance-") as temp_value:
        temp = Path(temp_value)
        expected_history: list[dict[str, Any]] = []
        try:
            prepared_sources = [
                prepare_source_row(
                    name=name,
                    source_bucket=source_bucket,
                    source_prefix=source_prefix,
                    destination_bucket=destination_bucket,
                    destination_prefix=destination_prefix,
                    kms_key_arn=args.kms_key_arn,
                    run_id=args.run_id,
                    region=args.region,
                    temp=temp,
                )
                for name in SOURCE_NAMES
            ]
            dry_run_receipt = {
                **receipt,
                "status": "dry_run",
                "objects": [
                    deepcopy(row) for row, _before, _source_sha in prepared_sources
                ],
                "completed_at": "dry-run-preflight",
                "object_count": len(prepared_sources),
                "passed_count": 0,
            }
            if args.dry_run_receipt is not None:
                validate_dry_run_receipt(args.dry_run_receipt, dry_run_receipt)

            for row, before, source_sha in prepared_sources:
                receipt["objects"].append(row)
                source_name = str(row["name"])
                if args.apply:
                    source = row["source"]
                    source_key = str(source["key"])
                    destination_key = str(row["destination"]["key"])
                    row["status"] = "copy_started"
                    copied = copy_object(
                        source_bucket,
                        source_key,
                        exact_s3_etag(
                            before.get("ETag"),
                            f"copy source {source_name}",
                        ),
                        destination_bucket,
                        destination_key,
                        args.kms_key_arn,
                        preferred_checksum_algorithm(before),
                        args.region,
                    )
                    version_id = exact_version_id(
                        copied.get("VersionId"),
                        f"copy response {source_name}",
                    )
                    row["destination"]["version_id"] = version_id
                    row["destination"]["copy_response"] = copied
                    row["status"] = "copy_returned"
                    after_source = head_object(source_bucket, source_key, args.region)
                    row["source"]["post_copy_head"] = after_source
                    destination = head_object(
                        destination_bucket,
                        destination_key,
                        args.region,
                        version_id,
                    )
                    destination_size = destination.get("ContentLength")
                    destination_checksum_type = exact_full_object_checksum_type(
                        destination.get("ChecksumType"),
                        f"destination {source_name}",
                    )
                    if not is_positive_exact_int(destination_size):
                        raise RuntimeError(
                            "destination ContentLength is not an exact positive "
                            f"integer: {source_name}"
                        )
                    destination_etag = exact_s3_etag(
                        destination.get("ETag"),
                        f"destination {source_name}",
                    )
                    destination_local = temp / f"destination-{source_name}"
                    downloaded = download_object(
                        destination_bucket,
                        destination_key,
                        destination_local,
                        args.region,
                        version_id=version_id,
                    )
                    require_real_downloaded_file(
                        destination_local,
                        f"downloaded destination {source_name}",
                    )
                    destination_sha = sha256(destination_local)
                    row["destination"].update(
                        {
                            "version_id": version_id,
                            "bytes": destination_size,
                            "etag": destination_etag,
                            "checksums": checksums(destination),
                            "checksum_type": destination_checksum_type,
                            "sha256": destination_sha,
                            "kms_key_id": str(destination.get("SSEKMSKeyId", "")),
                            "get_response": downloaded,
                        }
                    )
                    row["checks"].update({
                        "source_unchanged": source_stable(before, after_source),
                        "copy_version_exact": version_id
                        == destination.get("VersionId")
                        == downloaded.get("VersionId"),
                        "destination_get_matches_head": response_matches_head(
                            downloaded,
                            destination,
                            destination_local,
                            expected_version_id=version_id,
                        ),
                        "bytes_equal": exact_int(
                            destination_size,
                            before["ContentLength"],
                        )
                        and exact_int(
                            destination_size,
                            destination_local.stat().st_size,
                        ),
                        "sha256_equal": source_sha == destination_sha,
                        "full_object_checksum": destination.get("ChecksumType")
                        == "FULL_OBJECT"
                        and bool(checksums(destination)),
                        "exact_kms": destination.get("ServerSideEncryption") == "aws:kms"
                        and destination.get("SSEKMSKeyId") == args.kms_key_arn,
                    })
                    row["status"] = (
                        "passed" if all(row["checks"].values()) else "failed"
                    )
                    if row["status"] != "passed":
                        raise RuntimeError(
                            "private provenance copy failed validation: "
                            f"{source_name}"
                        )
                    expected_history.append(
                        {
                            "history_type": "Versions",
                            "Key": destination_key,
                            "VersionId": version_id,
                            "IsLatest": True,
                            "Size": destination_size,
                            "ETag": destination_etag,
                        }
                    )
                else:
                    row["status"] = "dry_run"
            if args.apply:
                actual_history = version_history(
                    destination_bucket, destination_prefix, args.region
                )
                if not exact_history_matches(actual_history, expected_history):
                    raise RuntimeError(
                        "destination version history is not exactly the two copied stage objects"
                    )
                receipt["destination_history_exact"] = True
        except Exception as error:
            receipt["status"] = "failed"
            receipt["error"] = f"{type(error).__name__}: {error}"
            receipt["completed_at"] = now()
            receipt["object_count"] = len(receipt["objects"])
            try:
                receipt["destination_history_at_failure"] = version_history(
                    destination_bucket, destination_prefix, args.region
                )
            except Exception as history_error:
                receipt["destination_history_error"] = (
                    f"{type(history_error).__name__}: {history_error}"
                )
            write_json_once(args.output, receipt)
            if args.apply:
                write_json_once(
                    args.anchor_output,
                    {
                        "schema_version": 1,
                        "status": "failed_before_receipt_anchor",
                        "generated_at": now(),
                        "run_id": args.run_id,
                        "receipt_path": str(args.output.resolve()),
                        "receipt_sha256": sha256(args.output),
                        "error": receipt["error"],
                    },
                )
            raise

    receipt["status"] = "passed" if args.apply else "dry_run"
    receipt["completed_at"] = now()
    receipt["object_count"] = len(receipt["objects"])
    receipt["passed_count"] = sum(
        row.get("status") == "passed" for row in receipt["objects"]
    )
    write_json_once(args.output, receipt)

    if args.apply:
        receipt_sha = sha256(args.output)
        receipt_key = destination_prefix + f"receipts/{receipt_sha}.json"
        anchor_state: dict[str, Any] = {
            "schema_version": 1,
            "status": "receipt_anchor_started",
            "generated_at": now(),
            "run_id": args.run_id,
            "receipt_sha256": receipt_sha,
            "receipt_bytes": args.output.stat().st_size,
            "receipt_uri": f"s3://{destination_bucket}/{receipt_key}",
        }
        try:
            if version_history(destination_bucket, receipt_key, args.region):
                raise RuntimeError("content-addressed receipt key was previously used")
            uploaded = put_receipt(
                args.output,
                destination_bucket,
                receipt_key,
                args.kms_key_arn,
                args.region,
            )
            version_id = exact_version_id(
                uploaded.get("VersionId"),
                "receipt put response",
            )
            anchor_state["status"] = "receipt_put_returned"
            anchor_state["receipt_version_id"] = version_id
            anchor_state["put_response"] = uploaded
            anchored = head_object(
                destination_bucket, receipt_key, args.region, version_id
            )
            anchored_size = anchored.get("ContentLength")
            with tempfile.TemporaryDirectory(
                prefix="diana-wgs-anchor-"
            ) as anchor_temp_value:
                anchored_local = Path(anchor_temp_value) / "receipt.json"
                anchored_get = download_object(
                    destination_bucket,
                    receipt_key,
                    anchored_local,
                    args.region,
                    version_id=version_id,
                )
                require_real_downloaded_file(
                    anchored_local,
                    "downloaded freeze receipt anchor",
                )
                expected_checksum = base64.b64encode(
                    bytes.fromhex(receipt_sha)
                ).decode("ascii")
                checks = {
                    "version_exact": version_id
                    == anchored.get("VersionId")
                    == anchored_get.get("VersionId"),
                    "get_matches_head": response_matches_head(
                        anchored_get,
                        anchored,
                        anchored_local,
                        expected_version_id=version_id,
                    ),
                    "bytes_exact": exact_int(
                        anchored_size,
                        args.output.stat().st_size,
                    )
                    and exact_int(
                        anchored_size,
                        anchored_local.stat().st_size,
                    ),
                    "local_sha256_exact": sha256(anchored_local) == receipt_sha,
                    "sha256_checksum_exact": anchored.get("ChecksumType")
                    == "FULL_OBJECT"
                    and anchored.get("ChecksumSHA256") == expected_checksum,
                    "exact_kms": anchored.get("ServerSideEncryption") == "aws:kms"
                    and anchored.get("SSEKMSKeyId") == args.kms_key_arn,
                    "content_type_exact": anchored.get("ContentType")
                    == "application/json",
                }
            final_expected_history = [
                *expected_history,
                {
                    "history_type": "Versions",
                    "Key": receipt_key,
                    "VersionId": version_id,
                    "IsLatest": True,
                    "Size": anchored_size,
                    "ETag": exact_s3_etag(
                        anchored.get("ETag"),
                        "receipt anchor",
                    ),
                },
            ]
            checks["history_exact"] = exact_history_matches(
                version_history(destination_bucket, destination_prefix, args.region),
                final_expected_history,
            )
            if not all(checks.values()):
                raise RuntimeError(f"receipt anchor validation failed: {checks}")
            anchor = {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": receipt_sha,
                "receipt_bytes": args.output.stat().st_size,
                "receipt_uri": f"s3://{destination_bucket}/{receipt_key}",
                "receipt_version_id": version_id,
                "checks": checks,
            }
            write_json_once(args.anchor_output, anchor)
        except Exception as error:
            anchor_state["status"] = "failed"
            anchor_state["error"] = f"{type(error).__name__}: {error}"
            try:
                anchor_state["destination_history_at_failure"] = version_history(
                    destination_bucket, destination_prefix, args.region
                )
            except Exception as history_error:
                anchor_state["destination_history_error"] = (
                    f"{type(history_error).__name__}: {history_error}"
                )
            if not args.anchor_output.exists():
                write_json_once(args.anchor_output, anchor_state)
            raise
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "objects": len(receipt["objects"]),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
