#!/usr/bin/env python3
"""Capture a terminal cross-check materializer job and its exact receipt.

This is a read-only, private custody helper.  It identifies the receipt only
from the terminal CloudWatch stream belonging to the exact successful Batch
attempt.  It never discovers a receipt by listing a mutable S3 prefix.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

REGION = "us-east-1"
ACCOUNT_ID = "172630973301"
LOG_GROUP = "/aws/batch/job"
LOG_STREAM_PREFIX = "diana-wgs-hrd-materialize/"
EXPECTED_JOB_DEFINITION = "arn:aws:batch:us-east-1:172630973301:job-definition/diana-wgs-hrd-materialize-crosscheck-inputs:4"
EXPECTED_JOB_DEFINITION_NAME = "diana-wgs-hrd-materialize-crosscheck-inputs"
EXPECTED_QUEUE_NAME = "diana-omics-prod-use1-ondemand"
EXPECTED_QUEUE_ARN = "arn:aws:batch:us-east-1:172630973301:job-queue/diana-omics-prod-use1-ondemand"
EXPECTED_COMPUTE_ENVIRONMENT = "arn:aws:batch:us-east-1:172630973301:compute-environment/diana-omics-prod-use1-ondemand"
EXPECTED_ARM_INSTANCE_TYPES = ("c7g", "c7gn", "m7g", "r7g")
EXPECTED_MATERIALIZER_SHA256 = "513c55b347a4c57e5f7231642e851d03aa4dcdac9159781e4d1a79815dc1f35f"
PARAMETER_NAMES = (
    "source_vcf_version_id",
    "source_vcf_index_version_id",
    "source_matrix_version_id",
    "source_vcf_sha256",
    "source_vcf_index_sha256",
    "source_matrix_sha256",
    "reference_fasta_version_id",
    "reference_fai_version_id",
)
SHA_PARAMETER_NAMES = {
    "source_vcf_sha256",
    "source_vcf_index_sha256",
    "source_matrix_sha256",
}
ANCHOR_CHECKS = {
    "version_exact",
    "bytes_exact",
    "sha256_exact",
    "sha256_checksum_exact",
    "metadata_sha256_exact",
    "exact_kms",
    "single_create_only_version",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def decode_sha256(value: Any, label: str) -> str:
    try:
        decoded = base64.b64decode(str(value), validate=True)
    except Exception as error:
        raise ValueError(f"{label} is not valid base64: {error}") from error
    if len(decoded) != 32:
        raise ValueError(f"{label} is not a SHA-256 checksum")
    return decoded.hex()


def aws_json(region: str, *args: str) -> dict[str, Any]:
    output = subprocess.check_output(
        ["aws", *args, "--region", region, "--output", "json"],
        text=True,
        stderr=subprocess.STDOUT,
    )
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise ValueError(f"AWS command did not return an object: {' '.join(args)}")
    return payload


def get_exact_object(region: str, bucket: str, key: str, version_id: str, destination: Path) -> dict[str, Any]:
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
    payload = json.loads(subprocess.check_output(command, text=True, stderr=subprocess.STDOUT))
    if not isinstance(payload, dict):
        raise ValueError("S3 get-object did not return an object")
    return payload


def require_one(payload: dict[str, Any], key: str) -> dict[str, Any]:
    rows = payload.get(key)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"expected exactly one {key} record")
    return rows[0]


def s3_location(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if parsed.scheme != "s3" or not parsed.netloc or not key:
        raise ValueError(f"expected an S3 object URI: {uri}")
    if not parsed.netloc.startswith("diana-omics-private-results-"):
        raise ValueError("receipt is outside the private-results bucket")
    return parsed.netloc, key


def parse_parameters(values: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, parameter_value = value.partition("=")
        if not separator or not name or not parameter_value:
            raise ValueError("expected parameters must use name=nonempty-value")
        if name in result:
            raise ValueError(f"duplicate expected parameter: {name}")
        result[name] = parameter_value
    if set(result) != set(PARAMETER_NAMES) or len(result) != len(PARAMETER_NAMES):
        raise ValueError("expected parameters must contain exactly the eight materializer keys")
    for name, value in result.items():
        if name in SHA_PARAMETER_NAMES:
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"expected parameter {name} is not lowercase SHA-256")
        elif not re.fullmatch(r"\S+", value):
            raise ValueError(f"expected parameter {name} is malformed")
    return {name: result[name] for name in PARAMETER_NAMES}


def collect_log_events(region: str, log_stream: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    token = ""
    observed_tokens: set[str] = set()
    for _ in range(100):
        arguments = [
            "logs",
            "get-log-events",
            "--log-group-name",
            LOG_GROUP,
            "--log-stream-name",
            log_stream,
            "--start-from-head",
        ]
        if token:
            arguments.extend(["--next-token", token])
        page = aws_json(region, *arguments)
        rows = page.get("events")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("CloudWatch events are malformed")
        events.extend(rows)
        next_token = str(page.get("nextForwardToken", ""))
        if not next_token or next_token == token:
            return events
        if next_token in observed_tokens:
            raise ValueError("CloudWatch pagination token loop detected")
        observed_tokens.add(next_token)
        token = next_token
    raise ValueError("CloudWatch log pagination exceeded the safety limit")


def parse_terminal_payload(events: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    messages: list[str] = []
    for event in events:
        message = event.get("message")
        if not isinstance(message, str):
            raise ValueError("CloudWatch event message is not text")
        messages.append(message.rstrip("\n"))
    text = "\n".join(messages)
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for start, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and value.get("status") == "passed"
            and isinstance(value.get("receipt"), dict)
            and isinstance(value.get("receipt_anchor"), dict)
            and isinstance(value.get("outputs"), dict)
        ):
            candidates.append((start, end, value))
    if len(candidates) != 1:
        raise ValueError("expected exactly one complete materialization terminal payload in CloudWatch")
    start, end, payload = candidates[0]
    if text[end:].strip():
        raise ValueError("materialization payload is not the terminal CloudWatch output")
    return payload, text[start:end]


def version_history(region: str, bucket: str, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    key_marker = ""
    version_marker = ""
    for _ in range(100):
        arguments = [
            "s3api",
            "list-object-versions",
            "--bucket",
            bucket,
            "--prefix",
            key,
        ]
        if key_marker:
            arguments.extend(["--key-marker", key_marker])
        if version_marker:
            arguments.extend(["--version-id-marker", version_marker])
        page = aws_json(region, *arguments)
        for field, kind in (("Versions", "version"), ("DeleteMarkers", "delete_marker")):
            values = page.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
                raise ValueError("S3 receipt version history is malformed")
            rows.extend({**value, "history_kind": kind} for value in values)
        if page.get("IsTruncated") is not True:
            return rows
        key_marker = str(page.get("NextKeyMarker", ""))
        version_marker = str(page.get("NextVersionIdMarker", ""))
        if not key_marker:
            raise ValueError("truncated receipt history omitted NextKeyMarker")
    raise ValueError("S3 receipt history pagination exceeded the safety limit")


def validate_job(
    job: dict[str, Any],
    definition: dict[str, Any],
    queue: dict[str, Any],
    compute_environment: dict[str, Any],
    job_id: str,
    expected_parameters: dict[str, str],
) -> dict[str, Any]:
    container = job.get("container")
    attempts = job.get("attempts")
    retry = job.get("retryStrategy")
    if not isinstance(container, dict):
        raise ValueError("Batch job container is missing")
    if not isinstance(attempts, list) or len(attempts) != 1 or not isinstance(attempts[0], dict):
        raise ValueError("Batch job must have exactly one terminal attempt")
    attempt_container = attempts[0].get("container")
    if not isinstance(attempt_container, dict):
        raise ValueError("Batch attempt container is missing")
    parameters = job.get("parameters")
    normalized_parameters = {str(key): str(value) for key, value in parameters.items()} if isinstance(parameters, dict) else {}
    job_log_stream = str(container.get("logStreamName", ""))
    attempt_log_stream = str(attempt_container.get("logStreamName", ""))
    queue_order = queue.get("computeEnvironmentOrder")
    resources = compute_environment.get("computeResources")
    instance_types = resources.get("instanceTypes") if isinstance(resources, dict) else None
    log_configuration = (
        definition.get("containerProperties", {}).get("logConfiguration", {})
        if isinstance(definition.get("containerProperties"), dict)
        else {}
    )
    log_options = log_configuration.get("options", {}) if isinstance(log_configuration, dict) else {}
    checks = {
        "job_id_exact": job.get("jobId") == job_id,
        "succeeded": job.get("status") == "SUCCEEDED",
        "terminal_timestamps": (int(job.get("startedAt", 0)) > 0 and int(job.get("stoppedAt", 0)) >= int(job.get("startedAt", 0))),
        "exact_job_definition": job.get("jobDefinition") == EXPECTED_JOB_DEFINITION,
        "exact_queue": job.get("jobQueue") == EXPECTED_QUEUE_ARN,
        "one_retry_attempt": isinstance(retry, dict) and retry.get("attempts") == 1,
        "one_terminal_attempt": len(attempts) == 1,
        "job_exit_zero": container.get("exitCode") == 0,
        "attempt_exit_zero": attempt_container.get("exitCode") == 0,
        "parameters_exact": normalized_parameters == expected_parameters,
        "log_stream_exact": (
            bool(job_log_stream) and job_log_stream == attempt_log_stream and job_log_stream.startswith(LOG_STREAM_PREFIX)
        ),
        "definition_exact": (
            definition.get("jobDefinitionArn") == EXPECTED_JOB_DEFINITION
            and definition.get("jobDefinitionName") == EXPECTED_JOB_DEFINITION_NAME
            and definition.get("revision") == 4
            and definition.get("status") == "ACTIVE"
            and definition.get("retryStrategy") == {"attempts": 1}
            and definition.get("timeout") == {"attemptDurationSeconds": 21600}
        ),
        "definition_log_exact": (
            log_configuration.get("logDriver") == "awslogs"
            and log_options.get("awslogs-group") == LOG_GROUP
            and log_options.get("awslogs-region") == REGION
            and log_options.get("awslogs-stream-prefix") == LOG_STREAM_PREFIX.rstrip("/")
        ),
        "queue_live_exact": (
            queue.get("jobQueueArn") == EXPECTED_QUEUE_ARN
            and queue.get("jobQueueName") == EXPECTED_QUEUE_NAME
            and queue.get("state") == "ENABLED"
            and queue.get("status") == "VALID"
            and queue_order == [{"order": 1, "computeEnvironment": EXPECTED_COMPUTE_ENVIRONMENT}]
        ),
        "arm_compute_environment_exact": (
            compute_environment.get("computeEnvironmentArn") == EXPECTED_COMPUTE_ENVIRONMENT
            and compute_environment.get("computeEnvironmentName") == EXPECTED_QUEUE_NAME
            and compute_environment.get("state") == "ENABLED"
            and compute_environment.get("status") == "VALID"
            and isinstance(instance_types, list)
            and len(instance_types) == len(EXPECTED_ARM_INSTANCE_TYPES)
            and sorted(str(value) for value in instance_types) == sorted(EXPECTED_ARM_INSTANCE_TYPES)
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"terminal materializer Batch identity failed: {checks}")
    return {
        "job_id": job_id,
        "job_name": str(job.get("jobName", "")),
        "status": "SUCCEEDED",
        "started_at_epoch_ms": int(job["startedAt"]),
        "stopped_at_epoch_ms": int(job["stoppedAt"]),
        "job_definition_arn": EXPECTED_JOB_DEFINITION,
        "job_queue_arn": EXPECTED_QUEUE_ARN,
        "compute_environment_arn": EXPECTED_COMPUTE_ENVIRONMENT,
        "attempt_count": 1,
        "exit_code": 0,
        "parameters": expected_parameters,
        "log_group": LOG_GROUP,
        "log_stream": job_log_stream,
        "checks": checks,
    }


def validate_logged_anchor(
    payload: dict[str, Any],
    expected_receipt_prefix: str,
    expected_kms_key_arn: str,
) -> dict[str, Any]:
    if set(payload) != {"status", "receipt", "receipt_anchor", "outputs"}:
        raise ValueError("terminal materialization payload keys are not exact")
    receipt_upload = payload["receipt"]
    anchor = payload["receipt_anchor"]
    if not isinstance(receipt_upload, dict) or not isinstance(anchor, dict):
        raise ValueError("terminal materialization receipt anchor is malformed")
    anchor_checks = anchor.get("checks")
    upload_checks = receipt_upload.get("checks")
    receipt_sha = str(anchor.get("receipt_sha256", ""))
    receipt_uri = str(anchor.get("receipt_uri", ""))
    receipt_version = str(anchor.get("receipt_version_id", ""))
    receipt_bytes = anchor.get("receipt_bytes")
    bucket, key = s3_location(receipt_uri)
    expected_prefix = expected_receipt_prefix.rstrip("/") + "/"
    expected_bucket, expected_prefix_key = s3_location(expected_prefix + "sentinel")
    expected_key = expected_prefix_key.removesuffix("sentinel") + receipt_sha + ".json"
    checks = {
        "outer_status": payload.get("status") == "passed",
        "anchor_schema_status": (anchor.get("schema_version") == 1 and anchor.get("status") == "passed"),
        "anchor_checks_exact": (
            isinstance(anchor_checks, dict)
            and set(anchor_checks) == ANCHOR_CHECKS
            and all(value is True for value in anchor_checks.values())
        ),
        "receipt_sha256_well_formed": bool(re.fullmatch(r"[0-9a-f]{64}", receipt_sha)),
        "receipt_bytes_positive": (isinstance(receipt_bytes, int) and not isinstance(receipt_bytes, bool) and receipt_bytes > 0),
        "receipt_version_nonempty": (
            bool(receipt_version) and receipt_version.lower() not in {"none", "null"} and bool(re.fullmatch(r"\S+", receipt_version))
        ),
        "receipt_uri_content_addressed": (bucket == expected_bucket and key == expected_key),
        "upload_binding": (
            receipt_upload.get("uri") == receipt_uri
            and receipt_upload.get("version_id") == receipt_version
            and receipt_upload.get("sha256") == receipt_sha
            and receipt_upload.get("bytes") == receipt_bytes
            and receipt_upload.get("kms_key_arn") == expected_kms_key_arn
        ),
        "upload_checks_passed": (
            isinstance(upload_checks, dict) and bool(upload_checks) and all(value is True for value in upload_checks.values())
        ),
        "logged_checksum_sha256": (
            isinstance(receipt_upload.get("checksums"), dict)
            and decode_sha256(
                receipt_upload.get("checksums", {}).get("ChecksumSHA256", ""),
                "logged receipt ChecksumSHA256",
            )
            == receipt_sha
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"logged materialization receipt anchor failed: {checks}")
    return {
        "bucket": bucket,
        "key": key,
        "uri": receipt_uri,
        "version_id": receipt_version,
        "sha256": receipt_sha,
        "bytes": int(receipt_bytes),
        "kms_key_arn": expected_kms_key_arn,
        "checks": checks,
    }


def validate_exact_receipt(
    receipt_bytes: bytes,
    get_response: dict[str, Any],
    head_response: dict[str, Any],
    history: list[dict[str, Any]],
    location: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bool]]:
    local_sha = sha256_bytes(receipt_bytes)
    try:
        receipt = json.loads(receipt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"downloaded materialization receipt is not JSON: {error}") from error
    if not isinstance(receipt, dict):
        raise ValueError("downloaded materialization receipt is not an object")
    receipt_checks = receipt.get("checks")
    exact_history = (
        len(history) == 1
        and history[0].get("history_kind") == "version"
        and history[0].get("Key") == location["key"]
        and history[0].get("VersionId") == location["version_id"]
        and history[0].get("IsLatest") is True
    )
    checks = {
        "logged_local_sha256_exact": local_sha == location["sha256"],
        "logged_local_bytes_exact": len(receipt_bytes) == location["bytes"],
        "get_version_exact": get_response.get("VersionId") == location["version_id"],
        "head_version_exact": head_response.get("VersionId") == location["version_id"],
        "get_bytes_exact": get_response.get("ContentLength") == location["bytes"],
        "head_bytes_exact": head_response.get("ContentLength") == location["bytes"],
        "get_sha256_checksum_exact": (
            decode_sha256(get_response.get("ChecksumSHA256", ""), "GET ChecksumSHA256") == local_sha
            and get_response.get("ChecksumType") == "FULL_OBJECT"
        ),
        "head_sha256_checksum_exact": (
            decode_sha256(head_response.get("ChecksumSHA256", ""), "HEAD ChecksumSHA256") == local_sha
            and head_response.get("ChecksumType") == "FULL_OBJECT"
        ),
        "get_kms_exact": (
            get_response.get("ServerSideEncryption") == "aws:kms" and get_response.get("SSEKMSKeyId") == location["kms_key_arn"]
        ),
        "head_kms_exact": (
            head_response.get("ServerSideEncryption") == "aws:kms" and head_response.get("SSEKMSKeyId") == location["kms_key_arn"]
        ),
        "get_metadata_sha256_exact": (
            isinstance(get_response.get("Metadata"), dict) and get_response["Metadata"].get("sha256") == local_sha
        ),
        "head_metadata_sha256_exact": (
            isinstance(head_response.get("Metadata"), dict) and head_response["Metadata"].get("sha256") == local_sha
        ),
        "single_version_no_delete_history": exact_history,
        "receipt_schema_status": (receipt.get("schema_version") == 2 and receipt.get("status") == "passed"),
        "receipt_script_exact": receipt.get("script_sha256") == EXPECTED_MATERIALIZER_SHA256,
        "receipt_checks_passed": (
            isinstance(receipt_checks, dict) and bool(receipt_checks) and all(value is True for value in receipt_checks.values())
        ),
        "receipt_boundary_no_call": (
            receipt.get("classification_authorization") == "none" and receipt.get("authorized_hrd_state") == "no_call"
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"exact materialization receipt verification failed: {checks}")
    return receipt, checks


def create_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"private output mode is not 0600: {path}")


def require_new_distinct_outputs(paths: Iterable[Path]) -> list[Path]:
    values = list(paths)
    resolved = [path.resolve(strict=False) for path in values]
    if len(set(resolved)) != len(resolved):
        raise ValueError("private output paths must be distinct")
    for path in values:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing to overwrite private output: {path}")
    return values


def create_private_group(outputs: Iterable[tuple[Path, bytes]]) -> None:
    values = list(outputs)
    require_new_distinct_outputs(path for path, _ in values)
    created: list[Path] = []
    try:
        for path, content in values:
            create_private(path, content)
            created.append(path)
    except Exception:
        for path in reversed(created):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        raise


def capture(args: argparse.Namespace) -> dict[str, Any]:
    require_new_distinct_outputs((args.capture_output, args.anchor_output, args.receipt_output))
    expected_parameters = parse_parameters(args.expected_parameter)
    job = require_one(
        aws_json(args.region, "batch", "describe-jobs", "--jobs", args.job_id),
        "jobs",
    )
    definition = require_one(
        aws_json(
            args.region,
            "batch",
            "describe-job-definitions",
            "--job-definitions",
            EXPECTED_JOB_DEFINITION,
        ),
        "jobDefinitions",
    )
    queue = require_one(
        aws_json(
            args.region,
            "batch",
            "describe-job-queues",
            "--job-queues",
            EXPECTED_QUEUE_ARN,
        ),
        "jobQueues",
    )
    compute_environment = require_one(
        aws_json(
            args.region,
            "batch",
            "describe-compute-environments",
            "--compute-environments",
            EXPECTED_COMPUTE_ENVIRONMENT,
        ),
        "computeEnvironments",
    )
    batch = validate_job(
        job,
        definition,
        queue,
        compute_environment,
        args.job_id,
        expected_parameters,
    )
    events = collect_log_events(args.region, batch["log_stream"])
    terminal_payload, terminal_json = parse_terminal_payload(events)
    location = validate_logged_anchor(terminal_payload, args.expected_receipt_prefix, args.expected_kms_key_arn)
    versioning = aws_json(
        args.region,
        "s3api",
        "get-bucket-versioning",
        "--bucket",
        location["bucket"],
    )
    if versioning.get("Status") != "Enabled":
        raise ValueError("receipt bucket versioning is not Enabled")
    head_response = aws_json(
        args.region,
        "s3api",
        "head-object",
        "--bucket",
        location["bucket"],
        "--key",
        location["key"],
        "--version-id",
        location["version_id"],
        "--checksum-mode",
        "ENABLED",
    )
    history = version_history(args.region, location["bucket"], location["key"])
    with tempfile.TemporaryDirectory(prefix="diana-materializer-terminal-") as temporary:
        temporary_path = Path(temporary) / "materialization-receipt.json"
        get_response = get_exact_object(
            args.region,
            location["bucket"],
            location["key"],
            location["version_id"],
            temporary_path,
        )
        downloaded = temporary_path.read_bytes()
    receipt, receipt_checks = validate_exact_receipt(downloaded, get_response, head_response, history, location)
    event_messages = [str(event.get("message", "")) for event in events]
    capture_payload = {
        "schema_version": 1,
        "status": "passed",
        "captured_at_utc": now(),
        "scope": "private read-only terminal materializer custody capture",
        "batch": batch,
        "cloudwatch": {
            "log_group": LOG_GROUP,
            "log_stream": batch["log_stream"],
            "event_count": len(events),
            "first_event_timestamp": int(events[0].get("timestamp", 0)) if events else 0,
            "last_event_timestamp": int(events[-1].get("timestamp", 0)) if events else 0,
            "messages_sha256": canonical_sha256(event_messages),
            "terminal_payload_sha256": canonical_sha256(terminal_payload),
            "terminal_json_sha256": sha256_bytes(terminal_json.encode("utf-8")),
            "receipt_anchor": terminal_payload["receipt_anchor"],
            "receipt_upload": terminal_payload["receipt"],
        },
        "receipt": {
            **location,
            "local_output": str(args.receipt_output.resolve()),
            "local_sha256": sha256_bytes(downloaded),
            "local_bytes": len(downloaded),
            "head_checksum_sha256": str(head_response.get("ChecksumSHA256", "")),
            "get_checksum_sha256": str(get_response.get("ChecksumSHA256", "")),
            "history": history,
            "checks": receipt_checks,
        },
        "local_anchor": {
            "output": str(args.anchor_output.resolve()),
            "sha256": "",
            "bytes": 0,
        },
        "checks": {
            "terminal_batch_identity": True,
            "exact_cloudwatch_stream": True,
            "single_terminal_anchor": True,
            "logged_receipt_binding": True,
            "bucket_versioning_enabled": True,
            "exact_version_get": True,
            "exact_version_head": True,
            "logged_local_sha256_and_bytes": True,
            "s3_sha256_checksums": True,
            "exact_kms": True,
            "single_version_no_delete_history": True,
            "private_mode_0600": True,
        },
        "classification_authorization": receipt["classification_authorization"],
        "authorized_hrd_state": receipt["authorized_hrd_state"],
    }
    anchor_bytes = (json.dumps(terminal_payload["receipt_anchor"], indent=2, sort_keys=True) + "\n").encode("utf-8")
    capture_payload["local_anchor"] = {
        "output": str(args.anchor_output.resolve()),
        "sha256": sha256_bytes(anchor_bytes),
        "bytes": len(anchor_bytes),
    }
    capture_bytes = (json.dumps(capture_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    create_private_group(
        (
            (args.receipt_output, downloaded),
            (args.anchor_output, anchor_bytes),
            (args.capture_output, capture_bytes),
        )
    )
    return capture_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument(
        "--expected-parameter",
        action="append",
        required=True,
        help="repeat exactly eight times as name=value",
    )
    parser.add_argument("--expected-receipt-prefix", required=True)
    parser.add_argument("--expected-kms-key-arn", required=True)
    parser.add_argument("--capture-output", required=True, type=Path)
    parser.add_argument("--anchor-output", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--region", default=REGION, choices=[REGION])
    args = parser.parse_args()
    try:
        result = capture(args)
    except (FileExistsError, OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    print(
        json.dumps(
            {
                "status": result["status"],
                "job_id": result["batch"]["job_id"],
                "receipt_uri": result["receipt"]["uri"],
                "receipt_version_id": result["receipt"]["version_id"],
                "capture_output": str(args.capture_output),
                "anchor_output": str(args.anchor_output),
                "receipt_output": str(args.receipt_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
