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

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
)

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
EXPECTED_MATERIALIZER_OUTPUTS = (
    "somatic.pass.vcf.gz",
    "somatic.pass.vcf.gz.tbi",
    "sbs96.csv",
    "staged_input_validation.json",
)
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
EXPECTED_SOURCE_VERSION_PARAMETERS = {
    "vcf": "source_vcf_version_id",
    "vcf_index": "source_vcf_index_version_id",
    "matrix": "source_matrix_version_id",
    "fasta": "reference_fasta_version_id",
    "fai": "reference_fai_version_id",
}
EXPECTED_SOURCE_SHA_PARAMETERS = {
    "vcf": "source_vcf_sha256",
    "vcf_index": "source_vcf_index_sha256",
    "matrix": "source_matrix_sha256",
}
EXPECTED_INPUT_SHA256_KEYS = {
    "filtered_vcf",
    "filtered_vcf_index",
    "source_sbs96_matrix",
    "reference_fasta",
    "reference_fai",
}
INPUT_SHA256_SOURCE_FIELDS = {
    "vcf": "filtered_vcf",
    "vcf_index": "filtered_vcf_index",
    "matrix": "source_sbs96_matrix",
    "fasta": "reference_fasta",
    "fai": "reference_fai",
}
EXPECTED_SOURCE_CUSTODY_KEYS = {
    "uri",
    "version_id",
    "bytes",
    "etag",
    "checksums",
    "sha256",
    "expected_sha256",
    "kms_key_arn",
}
EXPECTED_OUTPUT_CUSTODY_KEYS = {
    "uri",
    "version_id",
    "bytes",
    "etag",
    "checksums",
    "sha256",
    "kms_key_arn",
    "checks",
}
EXPECTED_DESTINATION_INVENTORY_KEYS = {
    "filename",
    "key",
    "version_id",
    "bytes",
    "sha256",
    "checksums",
}
EXPECTED_MATERIALIZER_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "generated_at_utc",
    "run_alias",
    "script_sha256",
    "destination_prefix",
    "destination_bucket_versioning",
    "destination_initial_version_history_count",
    "receipt_anchor_strategy",
    "source_custody",
    "validation",
    "input_sha256",
    "outputs",
    "destination_inventory",
    "checks",
    "classification_authorization",
    "authorized_hrd_state",
}
EXPECTED_RECEIPT_UPLOAD_CHECKS = {
    "create_only_put": True,
    "version_exact": True,
    "bytes_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_version_history": True,
}
EXPECTED_MATERIALIZER_RECEIPT_CHECKS = {
    "all_sources_exact_version_and_sha256": True,
    "alias_only_pass_snv_vcf": True,
    "sbs96_matches_independent_pass_vcf_derivation": True,
    "destination_prefix_initially_empty": True,
    "all_outputs_create_only": True,
    "destination_exact_single_version_history": True,
}
EXPECTED_RECEIPT_ANCHOR_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_create_only_version": True,
}
EXPECTED_BATCH_IDENTITY_CHECKS = {
    "job_id_exact": True,
    "succeeded": True,
    "terminal_timestamps": True,
    "exact_job_definition": True,
    "exact_queue": True,
    "one_retry_attempt": True,
    "one_terminal_attempt": True,
    "job_exit_zero": True,
    "attempt_exit_zero": True,
    "parameters_exact": True,
    "log_stream_exact": True,
    "definition_exact": True,
    "definition_log_exact": True,
    "queue_live_exact": True,
    "arm_compute_environment_exact": True,
}
EXPECTED_LOGGED_RECEIPT_ANCHOR_CHECKS = {
    "outer_status": True,
    "anchor_schema_status": True,
    "anchor_checks_exact": True,
    "receipt_sha256_well_formed": True,
    "receipt_bytes_positive": True,
    "receipt_version_nonempty": True,
    "receipt_uri_content_addressed": True,
    "upload_binding": True,
    "upload_checks_exact": True,
    "logged_checksum_sha256": True,
}
EXPECTED_EXACT_RECEIPT_DOWNLOAD_CHECKS = {
    "logged_local_sha256_exact": True,
    "logged_local_bytes_exact": True,
    "get_version_exact": True,
    "head_version_exact": True,
    "get_bytes_exact": True,
    "head_bytes_exact": True,
    "get_sha256_checksum_exact": True,
    "head_sha256_checksum_exact": True,
    "get_kms_exact": True,
    "head_kms_exact": True,
    "get_metadata_sha256_exact": True,
    "head_metadata_sha256_exact": True,
    "single_version_no_delete_history": True,
    "receipt_schema_status": True,
    "receipt_script_exact": True,
    "receipt_checks_exact": True,
    "receipt_keys_exact": True,
    "receipt_destination_exact": True,
    "receipt_source_custody_exact": True,
    "receipt_input_sha256_exact": True,
    "receipt_outputs_exact": True,
    "receipt_destination_inventory_exact": True,
    "receipt_boundary_no_call": True,
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def decode_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is not an exact SHA-256 checksum string")
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception as error:
        raise ValueError(f"{label} is not valid base64: {error}") from error
    if len(decoded) != 32:
        raise ValueError(f"{label} is not a SHA-256 checksum")
    return decoded.hex()


def encode_sha256(value: str) -> str:
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def is_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and bool(re.fullmatch(r"\S+", value))


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def valid_version_id(value: Any) -> bool:
    return is_nonempty_text(value) and value.lower() not in {"none", "null"}


def is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and type(expected) is int and value == expected


def exact_terminal_timestamps(started_at: Any, stopped_at: Any) -> bool:
    return (
        type(started_at) is int
        and type(stopped_at) is int
        and started_at > 0
        and stopped_at >= started_at
    )


def exact_schema_version(payload: dict[str, Any], expected: int) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def s3_key_or_none(uri: Any) -> str | None:
    if not isinstance(uri, str):
        return None
    try:
        _, key = s3_location(uri)
    except ValueError:
        return None
    return key


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
    require_safe_download_destination(destination, "downloaded materialization receipt")
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
    require_real_downloaded_file(destination, "downloaded materialization receipt")
    return payload


def require_one(payload: dict[str, Any], key: str) -> dict[str, Any]:
    rows = payload.get(key)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"expected exactly one {key} record")
    return rows[0]


def check_map_mismatches(value: dict[str, Any], expected: dict[str, bool]) -> list[str]:
    missing = sorted(set(expected) - set(value))
    unexpected = sorted(set(value) - set(expected))
    failed = sorted(key for key in set(expected) & set(value) if value[key] is not expected[key])
    errors: list[str] = []
    if missing:
        errors.append("missing " + ",".join(missing))
    if unexpected:
        errors.append("unexpected " + ",".join(unexpected))
    if failed:
        errors.append("failed " + ",".join(failed))
    return errors


def exact_check_map(value: Any, expected: dict[str, bool]) -> bool:
    return isinstance(value, dict) and not check_map_mismatches(value, expected)


def require_exact_checks(checks: dict[str, bool], expected: dict[str, bool], label: str) -> None:
    errors = check_map_mismatches(checks, expected)
    if errors:
        raise ValueError(f"{label} check map is not exact: {'; '.join(errors)}")


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
        elif not valid_version_id(value):
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
        next_token = page.get("nextForwardToken")
        if not isinstance(next_token, str) or not next_token:
            raise ValueError("CloudWatch nextForwardToken is malformed")
        if not next_token or next_token == token:
            return events
        if next_token in observed_tokens:
            raise ValueError("CloudWatch pagination token loop detected")
        observed_tokens.add(next_token)
        token = next_token
    raise ValueError("CloudWatch log pagination exceeded the safety limit")


def exact_cloudwatch_event_timestamps(events: list[dict[str, Any]]) -> list[int]:
    timestamps: list[int] = []
    for index, event in enumerate(events):
        timestamp = event.get("timestamp")
        if type(timestamp) is not int or timestamp <= 0:
            raise ValueError(
                f"CloudWatch event timestamp {index} is not an exact positive integer"
            )
        timestamps.append(timestamp)
    if not timestamps:
        raise ValueError("CloudWatch event timestamps are empty")
    if any(previous > current for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("CloudWatch event timestamps are not ordered")
    return timestamps


def parse_terminal_payload(events: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    messages: list[str] = []
    for event in events:
        message = event.get("message")
        if not isinstance(message, str):
            raise ValueError("CloudWatch event message is not text")
        messages.append(message.rstrip("\n"))
    text = "\n".join(messages)
    decoder = json.JSONDecoder(object_pairs_hook=reject_duplicate_json_object_names)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for start, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        except DuplicateJsonKeyError as error:
            raise ValueError(
                f"duplicate JSON object name in terminal materialization payload: {error}"
            ) from error
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
    seen_markers: set[tuple[str, str]] = set()
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
        key_marker, version_marker = require_next_version_history_markers(page)
        marker = (key_marker, version_marker)
        if marker in seen_markers:
            raise ValueError("S3 receipt history pagination did not advance")
        seen_markers.add(marker)
    raise ValueError("S3 receipt history pagination exceeded the safety limit")


def require_next_version_history_markers(page: dict[str, Any]) -> tuple[str, str]:
    key_marker = page.get("NextKeyMarker")
    version_marker = page.get("NextVersionIdMarker")
    if (
        not isinstance(key_marker, str)
        or not isinstance(version_marker, str)
        or not key_marker
        or not version_marker
    ):
        raise ValueError(
            "truncated receipt history omitted its next key/version markers"
        )
    return key_marker, version_marker


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
    definition_retry = definition.get("retryStrategy")
    definition_timeout = definition.get("timeout")
    started_at = job.get("startedAt")
    stopped_at = job.get("stoppedAt")
    checks = {
        "job_id_exact": job.get("jobId") == job_id,
        "succeeded": job.get("status") == "SUCCEEDED",
        "terminal_timestamps": exact_terminal_timestamps(started_at, stopped_at),
        "exact_job_definition": job.get("jobDefinition") == EXPECTED_JOB_DEFINITION,
        "exact_queue": job.get("jobQueue") == EXPECTED_QUEUE_ARN,
        "one_retry_attempt": isinstance(retry, dict) and exact_int(retry.get("attempts"), 1),
        "one_terminal_attempt": len(attempts) == 1,
        "job_exit_zero": exact_int(container.get("exitCode"), 0),
        "attempt_exit_zero": exact_int(attempt_container.get("exitCode"), 0),
        "parameters_exact": normalized_parameters == expected_parameters,
        "log_stream_exact": (
            bool(job_log_stream) and job_log_stream == attempt_log_stream and job_log_stream.startswith(LOG_STREAM_PREFIX)
        ),
        "definition_exact": (
            definition.get("jobDefinitionArn") == EXPECTED_JOB_DEFINITION
            and definition.get("jobDefinitionName") == EXPECTED_JOB_DEFINITION_NAME
            and exact_int(definition.get("revision"), 4)
            and definition.get("status") == "ACTIVE"
            and isinstance(definition_retry, dict)
            and set(definition_retry) == {"attempts"}
            and exact_int(definition_retry.get("attempts"), 1)
            and isinstance(definition_timeout, dict)
            and set(definition_timeout) == {"attemptDurationSeconds"}
            and exact_int(definition_timeout.get("attemptDurationSeconds"), 21600)
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
    try:
        require_exact_checks(
            checks,
            EXPECTED_BATCH_IDENTITY_CHECKS,
            "terminal materializer Batch identity",
        )
    except ValueError as error:
        raise ValueError(f"terminal materializer Batch identity failed: {error}") from error
    return {
        "job_id": job_id,
        "job_name": str(job.get("jobName", "")),
        "status": "SUCCEEDED",
        "started_at_epoch_ms": started_at,
        "stopped_at_epoch_ms": stopped_at,
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
    receipt_sha = anchor.get("receipt_sha256")
    receipt_uri = anchor.get("receipt_uri")
    receipt_version = anchor.get("receipt_version_id")
    receipt_bytes = anchor.get("receipt_bytes")
    bucket = ""
    key = ""
    if isinstance(receipt_uri, str):
        with contextlib.suppress(ValueError):
            bucket, key = s3_location(receipt_uri)
    expected_prefix = expected_receipt_prefix.rstrip("/") + "/"
    expected_bucket, expected_prefix_key = s3_location(expected_prefix + "sentinel")
    expected_key = (
        expected_prefix_key.removesuffix("sentinel") + receipt_sha + ".json"
        if isinstance(receipt_sha, str)
        else ""
    )
    checks = {
        "outer_status": payload.get("status") == "passed",
        "anchor_schema_status": (exact_schema_version(anchor, 1) and anchor.get("status") == "passed"),
        "anchor_checks_exact": exact_check_map(
            anchor_checks,
            EXPECTED_RECEIPT_ANCHOR_CHECKS,
        ),
        "receipt_sha256_well_formed": is_sha256(receipt_sha),
        "receipt_bytes_positive": (isinstance(receipt_bytes, int) and not isinstance(receipt_bytes, bool) and receipt_bytes > 0),
        "receipt_version_nonempty": valid_version_id(receipt_version),
        "receipt_uri_content_addressed": (bucket == expected_bucket and key == expected_key),
        "upload_binding": (
            receipt_upload.get("uri") == receipt_uri
            and receipt_upload.get("version_id") == receipt_version
            and receipt_upload.get("sha256") == receipt_sha
            and exact_int(receipt_upload.get("bytes"), receipt_bytes)
            and receipt_upload.get("kms_key_arn") == expected_kms_key_arn
        ),
        "upload_checks_exact": exact_check_map(
            upload_checks,
            EXPECTED_RECEIPT_UPLOAD_CHECKS,
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
    try:
        require_exact_checks(
            checks,
            EXPECTED_LOGGED_RECEIPT_ANCHOR_CHECKS,
            "logged materialization receipt anchor",
        )
    except ValueError as error:
        raise ValueError(
            f"logged materialization receipt anchor failed: {error}"
        ) from error
    if (
        not isinstance(receipt_uri, str)
        or not isinstance(receipt_sha, str)
        or not isinstance(receipt_version, str)
    ):
        raise AssertionError("validated materialization receipt anchor has non-string fields")
    return {
        "bucket": bucket,
        "key": key,
        "uri": receipt_uri,
        "version_id": receipt_version,
        "sha256": receipt_sha,
        "bytes": receipt_bytes,
        "kms_key_arn": expected_kms_key_arn,
        "checks": checks,
    }


def materializer_destination_prefix(expected_receipt_prefix: str) -> str:
    bucket, sentinel = s3_location(expected_receipt_prefix.rstrip("/") + "/sentinel")
    receipt_prefix = sentinel.removesuffix("/sentinel").rstrip("/")
    receipt_suffix = "/deterministic/provenance/crosscheck-materialization-receipts"
    if not receipt_prefix.endswith(receipt_suffix):
        raise ValueError(
            "expected receipt prefix is not the materializer provenance prefix"
        )
    run_prefix = receipt_prefix[: -len(receipt_suffix)]
    return f"s3://{bucket}/{run_prefix}/deterministic/final/"


def upload_checksum_exact(output: dict[str, Any]) -> bool:
    sha256 = output.get("sha256")
    if not is_sha256(sha256):
        return False
    return output.get("checksums") == {
        "ChecksumSHA256": encode_sha256(sha256),
        "ChecksumType": "FULL_OBJECT",
    }


def source_custody_is_exact(
    receipt: dict[str, Any],
    expected_parameters: dict[str, str],
    expected_kms_key_arn: str,
) -> bool:
    source_custody = receipt.get("source_custody")
    input_sha256 = receipt.get("input_sha256")
    if not isinstance(source_custody, dict) or not isinstance(input_sha256, dict):
        return False
    if set(source_custody) != set(EXPECTED_SOURCE_VERSION_PARAMETERS):
        return False

    for source_name, version_parameter in EXPECTED_SOURCE_VERSION_PARAMETERS.items():
        row = source_custody.get(source_name)
        if not isinstance(row, dict) or set(row) != EXPECTED_SOURCE_CUSTODY_KEYS:
            return False
        sha256 = row.get("sha256")
        expected_sha256 = row.get("expected_sha256")
        input_field = INPUT_SHA256_SOURCE_FIELDS[source_name]
        if (
            not is_nonempty_text(row.get("uri"))
            or s3_key_or_none(row.get("uri")) is None
            or row.get("version_id") != expected_parameters[version_parameter]
            or not is_positive_int(row.get("bytes"))
            or not is_nonempty_text(row.get("etag"))
            or not isinstance(row.get("checksums"), dict)
            or not is_sha256(sha256)
            or row.get("kms_key_arn") != expected_kms_key_arn
            or input_sha256.get(input_field) != sha256
        ):
            return False
        sha_parameter = EXPECTED_SOURCE_SHA_PARAMETERS.get(source_name)
        if sha_parameter is not None:
            if (
                sha256 != expected_parameters[sha_parameter]
                or expected_sha256 != expected_parameters[sha_parameter]
            ):
                return False
        elif expected_sha256 not in {None, sha256}:
            return False
    return True


def input_sha256_is_exact(receipt: dict[str, Any]) -> bool:
    source_custody = receipt.get("source_custody")
    input_sha256 = receipt.get("input_sha256")
    if not isinstance(source_custody, dict) or not isinstance(input_sha256, dict):
        return False
    if set(input_sha256) != EXPECTED_INPUT_SHA256_KEYS:
        return False
    for source_name, input_field in INPUT_SHA256_SOURCE_FIELDS.items():
        row = source_custody.get(source_name)
        if not isinstance(row, dict) or input_sha256.get(input_field) != row.get("sha256"):
            return False
    return True


def outputs_are_exact(
    receipt: dict[str, Any],
    expected_destination_prefix: str,
    expected_kms_key_arn: str,
) -> bool:
    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != set(EXPECTED_MATERIALIZER_OUTPUTS):
        return False
    expected_prefix = expected_destination_prefix.rstrip("/") + "/"
    for filename in EXPECTED_MATERIALIZER_OUTPUTS:
        output = outputs.get(filename)
        if not isinstance(output, dict) or set(output) != EXPECTED_OUTPUT_CUSTODY_KEYS:
            return False
        expected_uri = expected_prefix + filename
        if (
            output.get("uri") != expected_uri
            or not valid_version_id(output.get("version_id"))
            or not is_positive_int(output.get("bytes"))
            or not is_nonempty_text(output.get("etag"))
            or not is_sha256(output.get("sha256"))
            or output.get("kms_key_arn") != expected_kms_key_arn
            or not exact_check_map(
                output.get("checks"),
                EXPECTED_RECEIPT_UPLOAD_CHECKS,
            )
            or not upload_checksum_exact(output)
            or s3_key_or_none(output.get("uri")) is None
        ):
            return False
    return True


def destination_inventory_is_exact(receipt: dict[str, Any]) -> bool:
    outputs = receipt.get("outputs")
    inventory = receipt.get("destination_inventory")
    if (
        not isinstance(outputs, dict)
        or not isinstance(inventory, list)
        or len(inventory) != len(EXPECTED_MATERIALIZER_OUTPUTS)
        or any(not isinstance(row, dict) for row in inventory)
    ):
        return False
    by_filename = {str(row.get("filename", "")): row for row in inventory}
    if set(by_filename) != set(EXPECTED_MATERIALIZER_OUTPUTS):
        return False

    for filename in EXPECTED_MATERIALIZER_OUTPUTS:
        output = outputs.get(filename)
        row = by_filename[filename]
        if not isinstance(output, dict) or set(row) != EXPECTED_DESTINATION_INVENTORY_KEYS:
            return False
        key = s3_key_or_none(output.get("uri"))
        if (
            key is None
            or row.get("key") != key
            or row.get("version_id") != output.get("version_id")
            or not exact_int(row.get("bytes"), output.get("bytes"))
            or row.get("sha256") != output.get("sha256")
            or row.get("checksums") != output.get("checksums")
        ):
            return False
    return True


def validate_exact_receipt(
    receipt_bytes: bytes,
    get_response: dict[str, Any],
    head_response: dict[str, Any],
    history: list[dict[str, Any]],
    location: dict[str, Any],
    expected_parameters: dict[str, str],
    expected_destination_prefix: str,
    expected_kms_key_arn: str,
) -> tuple[dict[str, Any], dict[str, bool]]:
    local_sha = sha256_bytes(receipt_bytes)
    try:
        receipt = json.loads(
            receipt_bytes,
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(
            f"duplicate JSON object name in downloaded materialization receipt: {error}"
        ) from error
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
        "logged_local_bytes_exact": exact_int(location["bytes"], len(receipt_bytes)),
        "get_version_exact": get_response.get("VersionId") == location["version_id"],
        "head_version_exact": head_response.get("VersionId") == location["version_id"],
        "get_bytes_exact": exact_int(
            get_response.get("ContentLength"), location["bytes"]
        ),
        "head_bytes_exact": exact_int(
            head_response.get("ContentLength"), location["bytes"]
        ),
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
        "receipt_schema_status": (exact_schema_version(receipt, 2) and receipt.get("status") == "passed"),
        "receipt_script_exact": receipt.get("script_sha256") == EXPECTED_MATERIALIZER_SHA256,
        "receipt_checks_exact": exact_check_map(
            receipt_checks,
            EXPECTED_MATERIALIZER_RECEIPT_CHECKS,
        ),
        "receipt_keys_exact": set(receipt) == EXPECTED_MATERIALIZER_RECEIPT_KEYS,
        "receipt_destination_exact": (
            receipt.get("destination_prefix") == expected_destination_prefix
            and receipt.get("destination_bucket_versioning") == "Enabled"
            and exact_int(receipt.get("destination_initial_version_history_count"), 0)
            and receipt.get("receipt_anchor_strategy") == "sha256_content_addressed_create_only"
        ),
        "receipt_source_custody_exact": source_custody_is_exact(
            receipt,
            expected_parameters,
            expected_kms_key_arn,
        ),
        "receipt_input_sha256_exact": input_sha256_is_exact(receipt),
        "receipt_outputs_exact": outputs_are_exact(
            receipt,
            expected_destination_prefix,
            expected_kms_key_arn,
        ),
        "receipt_destination_inventory_exact": destination_inventory_is_exact(
            receipt
        ),
        "receipt_boundary_no_call": (
            receipt.get("classification_authorization") == "none" and receipt.get("authorized_hrd_state") == "no_call"
        ),
    }
    try:
        require_exact_checks(
            checks,
            EXPECTED_EXACT_RECEIPT_DOWNLOAD_CHECKS,
            "exact materialization receipt verification",
        )
    except ValueError as error:
        raise ValueError(
            f"exact materialization receipt verification failed: {error}"
        ) from error
    return receipt, checks


def create_private(path: Path, content: bytes) -> None:
    require_safe_private_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_sha256 = sha256_bytes(content)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if (path.stat().st_mode & 0o777) != 0o600:
                raise ValueError(f"private output mode is not 0600: {path}")
            fsync_directory(path.parent)
            require_installed_private_output(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_installed_private_output(path: Path, expected_sha256: str) -> None:
    require_no_symlinked_ancestors(path, "private output")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"private output changed during write: {path}")
    if sha256_bytes(path.read_bytes()) != expected_sha256:
        raise ValueError(f"private output changed during write: {path}")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_safe_private_output_parent(path: Path) -> None:
    if path.is_symlink():
        raise FileExistsError(f"private output may not be a symlink: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise FileExistsError(
                f"private output parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def require_safe_download_destination(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, label)


def require_real_downloaded_file(path: Path, label: str) -> None:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def require_new_distinct_outputs(paths: Iterable[Path]) -> list[Path]:
    values = list(paths)
    if not values:
        raise ValueError("private output paths must be distinct")
    for path in values:
        require_safe_private_output_parent(path)
    resolved = [path.resolve(strict=False) for path in values]
    if len(set(resolved)) != len(resolved):
        raise ValueError("private output paths must be distinct")
    for path in values:
        if path.exists():
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
    event_timestamps = exact_cloudwatch_event_timestamps(events)
    terminal_payload, terminal_json = parse_terminal_payload(events)
    location = validate_logged_anchor(terminal_payload, args.expected_receipt_prefix, args.expected_kms_key_arn)
    expected_destination_prefix = materializer_destination_prefix(args.expected_receipt_prefix)
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
        require_real_downloaded_file(temporary_path, "downloaded materialization receipt")
        downloaded = temporary_path.read_bytes()
    receipt, receipt_checks = validate_exact_receipt(
        downloaded,
        get_response,
        head_response,
        history,
        location,
        expected_parameters,
        expected_destination_prefix,
        args.expected_kms_key_arn,
    )
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
            "first_event_timestamp": event_timestamps[0],
            "last_event_timestamp": event_timestamps[-1],
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
            "head_checksum_sha256": head_response["ChecksumSHA256"],
            "get_checksum_sha256": get_response["ChecksumSHA256"],
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
