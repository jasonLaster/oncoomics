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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def valid_version_id(value: Any) -> bool:
    return str(value or "").strip().lower() not in {"", "null", "none"}


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


def write_bytes_once(path: Path, payload: bytes) -> None:
    """Atomically create a local receipt without replacing prior evidence."""
    require_safe_output_parent(path, "local evidence output")
    path.parent.mkdir(parents=True, exist_ok=True)
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
    except Exception:
        if linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


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
        field: str(head[field])
        for field in CHECKSUM_FIELDS
        if str(head.get(field, "")).strip()
    }


def preferred_checksum_algorithm(head: dict[str, Any]) -> str:
    for field in CHECKSUM_FIELDS:
        if str(head.get(field, "")).strip():
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
    return aws_json(arguments, region)


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
        key_marker = str(payload.get("NextKeyMarker", ""))
        version_id_marker = str(payload.get("NextVersionIdMarker", ""))
        if not key_marker or not version_id_marker:
            raise RuntimeError(
                "truncated version history omitted its next key/version markers"
            )
        marker = (key_marker, version_id_marker)
        if marker in seen_markers:
            raise RuntimeError("destination version history pagination did not advance")
        seen_markers.add(marker)


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
    worker_sha = str(worker.get("sha256", ""))
    launch_uri = (
        f"s3://{source_bucket}/runs/diana-hrd/{run_id}/inputs/"
        "diana_hrd_wgs_worker.py"
    )
    executed_uri = (
        f"s3://{destination_bucket}/runs/subject01/{run_id}/deterministic/"
        f"provenance/executed-workers/{worker_sha}.py"
    )
    if (
        receipt.get("schema_version") != 1
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
        or batch.get("attempt_count") != len(normalized_attempts)
        or captured_attempts != normalized_attempts
        or len(normalized_attempts) != 1
        or normalized_attempts[0].get("exit_code") != 0
        or captured_container.get("image_reference") != live_container.get("image")
        or captured_container.get("task_arn") != live_container.get("taskArn")
        or worker.get("launch_uri") != launch_uri
        or worker.get("executed_uri") != executed_uri
        or not valid_version_id(worker.get("executed_version_id"))
        or not valid_version_id(worker.get("freeze_receipt_version_id"))
        or not re.fullmatch(r"[0-9a-f]{64}", worker_sha)
        or int(worker.get("bytes", 0)) <= 0
        or worker.get("server_side_encryption") != "aws:kms"
        or worker.get("kms_key_id") != kms_key_arn
        or not isinstance(worker_checks, dict)
        or not worker_checks
        or not all(value is True for value in worker_checks.values())
    ):
        raise ValueError("execution receipt does not match the exact successful Batch job")
    expected_worker_checksum = base64.b64encode(bytes.fromhex(worker_sha)).decode("ascii")
    if (worker.get("checksums") or {}).get("ChecksumSHA256") != expected_worker_checksum:
        raise ValueError("executed worker SHA-256 checksum is not exact")
    return account_id


def source_stable(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        int(before.get("ContentLength", -1)) == int(after.get("ContentLength", -2))
        and str(before.get("ETag", "")) == str(after.get("ETag", ""))
        and checksums(before) == checksums(after)
        and before.get("ChecksumType") == after.get("ChecksumType") == "FULL_OBJECT"
        and str(before.get("VersionId", "null"))
        == str(after.get("VersionId", "null"))
        == "null"
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
    response_version = str(response.get("VersionId", "null"))
    return (
        response_version == expected_version_id
        and int(response.get("ContentLength", -1))
        == int(head.get("ContentLength", -2))
        == local_path.stat().st_size
        and str(response.get("ETag", "")) == str(head.get("ETag", ""))
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
            or int(document.get("wgs_bytes", 0)) <= 0
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
            or sample.get("lane_count") != 4
            or sample.get("output_bam") != f"{role}.markdup.bam"
            or int(sample.get("output_bam_bytes", 0)) <= 0
        ):
            raise ValueError(f"gather.json has invalid {role} sample semantics")
    if (
        document.get("reference") != REFERENCE_LABEL
        or document.get("duplicate_marking")
        != "samtools fixmate -m per lane followed by merged samtools markdup"
    ):
        raise ValueError("gather.json has invalid reference or duplicate-marking semantics")


def exact_history_matches(
    actual: list[dict[str, Any]], expected: list[dict[str, Any]]
) -> bool:
    def normalized(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            str(row.get("history_type", "")),
            str(row.get("Key", "")),
            str(row.get("VersionId", "")),
            row.get("IsLatest") is True,
            int(row.get("Size", -1)),
            str(row.get("ETag", "")),
        )

    return sorted(map(normalized, actual)) == sorted(map(normalized, expected))


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
    args = parser.parse_args()
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
    if args.apply and version_history(destination_bucket, destination_prefix, args.region):
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
            for name in SOURCE_NAMES:
                source_key = source_prefix + name
                destination_key = destination_prefix + name
                before = head_object(source_bucket, source_key, args.region)
                if (
                    int(before.get("ContentLength", -1)) <= 0
                    or before.get("ChecksumType") != "FULL_OBJECT"
                    or not checksums(before)
                    or str(before.get("VersionId", "null")) != "null"
                    or not str(before.get("ETag", "")).strip()
                    or before.get("ContentType") != "application/json"
                    or before.get("ServerSideEncryption") != "aws:kms"
                    or before.get("SSEKMSKeyId") != args.kms_key_arn
                ):
                    raise RuntimeError(f"invalid unversioned source object: {name}")
                source_local = temp / f"source-{name}"
                downloaded_source = download_object(
                    source_bucket,
                    source_key,
                    source_local,
                    args.region,
                    etag=str(before.get("ETag", "")),
                )
                if not response_matches_head(
                    downloaded_source,
                    before,
                    source_local,
                    expected_version_id="null",
                ):
                    raise RuntimeError(f"source get response did not match head: {name}")
                try:
                    validate_source_document(name, load_json(source_local), args.run_id)
                except ValueError as error:
                    raise RuntimeError(str(error)) from error
                source_sha = sha256(source_local)
                row: dict[str, Any] = {
                    "name": name,
                    "source": {
                        "bucket": source_bucket,
                        "key": source_key,
                        "version_id": "null",
                        "bytes": int(before["ContentLength"]),
                        "etag": str(before["ETag"]),
                        "checksums": checksums(before),
                        "checksum_type": "FULL_OBJECT",
                        "sha256": source_sha,
                        "server_side_encryption": "aws:kms",
                        "kms_key_id": args.kms_key_arn,
                        "get_response": downloaded_source,
                    },
                    "destination": {
                        "bucket": destination_bucket,
                        "key": destination_key,
                    },
                    "checks": {
                        "get_matches_head": True,
                        "local_bytes_exact": source_local.stat().st_size
                        == int(before["ContentLength"]),
                        "semantic_binding": True,
                        "source_kms_exact": True,
                    },
                    "status": "source_validated",
                }
                receipt["objects"].append(row)
                if args.apply:
                    row["status"] = "copy_started"
                    copied = copy_object(
                        source_bucket,
                        source_key,
                        str(before["ETag"]),
                        destination_bucket,
                        destination_key,
                        args.kms_key_arn,
                        preferred_checksum_algorithm(before),
                        args.region,
                    )
                    version_id = str(copied.get("VersionId", ""))
                    row["destination"]["version_id"] = version_id
                    row["destination"]["copy_response"] = copied
                    row["status"] = "copy_returned"
                    if not valid_version_id(version_id):
                        raise RuntimeError(
                            f"copy returned a null destination VersionId: {name}"
                        )
                    after_source = head_object(source_bucket, source_key, args.region)
                    row["source"]["post_copy_head"] = after_source
                    destination = head_object(
                        destination_bucket,
                        destination_key,
                        args.region,
                        version_id,
                    )
                    destination_local = temp / f"destination-{name}"
                    downloaded = download_object(
                        destination_bucket,
                        destination_key,
                        destination_local,
                        args.region,
                        version_id=version_id,
                    )
                    destination_sha = sha256(destination_local)
                    row["destination"].update(
                        {
                            "version_id": version_id,
                            "bytes": int(destination.get("ContentLength", -1)),
                            "etag": str(destination.get("ETag", "")),
                            "checksums": checksums(destination),
                            "checksum_type": str(destination.get("ChecksumType", "")),
                            "sha256": destination_sha,
                            "kms_key_id": str(destination.get("SSEKMSKeyId", "")),
                            "get_response": downloaded,
                        }
                    )
                    row["checks"].update({
                        "source_unchanged": source_stable(before, after_source),
                        "copy_version_exact": valid_version_id(version_id)
                        and version_id == str(destination.get("VersionId", ""))
                        and version_id == str(downloaded.get("VersionId", "")),
                        "destination_get_matches_head": response_matches_head(
                            downloaded,
                            destination,
                            destination_local,
                            expected_version_id=version_id,
                        ),
                        "bytes_equal": int(before["ContentLength"])
                        == int(destination.get("ContentLength", -1))
                        == destination_local.stat().st_size,
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
                            f"private provenance copy failed validation: {name}"
                        )
                    expected_history.append(
                        {
                            "history_type": "Versions",
                            "Key": destination_key,
                            "VersionId": version_id,
                            "IsLatest": True,
                            "Size": int(destination["ContentLength"]),
                            "ETag": str(destination["ETag"]),
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
            version_id = str(uploaded.get("VersionId", ""))
            anchor_state["status"] = "receipt_put_returned"
            anchor_state["receipt_version_id"] = version_id
            anchor_state["put_response"] = uploaded
            if not valid_version_id(version_id):
                raise RuntimeError("receipt put returned a null VersionId")
            anchored = head_object(
                destination_bucket, receipt_key, args.region, version_id
            )
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
                expected_checksum = base64.b64encode(
                    bytes.fromhex(receipt_sha)
                ).decode("ascii")
                checks = {
                    "version_exact": valid_version_id(version_id)
                    and version_id == str(anchored.get("VersionId", ""))
                    and version_id == str(anchored_get.get("VersionId", "")),
                    "get_matches_head": response_matches_head(
                        anchored_get,
                        anchored,
                        anchored_local,
                        expected_version_id=version_id,
                    ),
                    "bytes_exact": args.output.stat().st_size
                    == int(anchored.get("ContentLength", -1))
                    == anchored_local.stat().st_size,
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
                    "Size": int(anchored.get("ContentLength", -1)),
                    "ETag": str(anchored.get("ETag", "")),
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
