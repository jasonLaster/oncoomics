#!/usr/bin/env python3
"""Capture one successful HRD cross-check route and its exact receipt.

This private helper is read-only with respect to AWS.  It binds a successful,
single-attempt Batch execution to its exact revision-3 route definition, the
live x86 queue/compute environment, the submitted one-shot environment, the
attempt's CloudWatch stream, and the sole terminal content-addressed
publication receipt.  It never discovers receipts by listing a mutable prefix.
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
LOG_GROUP = "/aws/batch/diana-omics-prod-use1"
LOG_STREAM_PREFIX = "hrd-crosscheck"
EXPECTED_QUEUE_NAME = "diana-omics-prod-use1-hrd-x86-ondemand"
EXPECTED_QUEUE_ARN = "arn:aws:batch:us-east-1:172630973301:job-queue/diana-omics-prod-use1-hrd-x86-ondemand"
EXPECTED_COMPUTE_ENVIRONMENT = "arn:aws:batch:us-east-1:172630973301:compute-environment/diana-omics-prod-use1-hrd-x86-ondemand"
EXPECTED_JOB_ROLE = "arn:aws:iam::172630973301:role/diana-omics-prod-use1-batch-job"
EXPECTED_X86_INSTANCE_TYPES = ("c7i", "m7i", "r7i")

ROUTES: dict[str, dict[str, Any]] = {
    "sigprofiler_sbs3": {
        "job_definition_name": "diana-hrd-sigprofiler-sbs3",
        "job_definition_arn": ("arn:aws:batch:us-east-1:172630973301:job-definition/diana-hrd-sigprofiler-sbs3:3"),
        "revision": 3,
        "timeout_seconds": 21600,
        "command": ["sigprofiler_sbs3"],
        "image": (
            "172630973301.dkr.ecr.us-east-1.amazonaws.com/"
            "diana-hrd-sigprofiler@"
            "sha256:6b08418763e186399e176fa0286e9bdb1767e27bf0707acb77eeacabe2d43a7a"
        ),
        "vcpus": 4,
        "memory": 16384,
        "definition_environment": {
            "AWS_REGION": REGION,
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_CLI_HISTORY_FILE": "/dev/null",
            "LC_ALL": "C.UTF-8",
            "HRD_CROSSCHECK_IMAGE_REFERENCE": (
                "172630973301.dkr.ecr.us-east-1.amazonaws.com/"
                "diana-hrd-sigprofiler@"
                "sha256:6b08418763e186399e176fa0286e9bdb1767e27bf0707acb77eeacabe2d43a7a"
            ),
            "HRD_CROSSCHECK_IMAGE_SECURITY_RECEIPT_SHA256": ("7105a1568708ed575c201f78ca8eae257128b40d876a8c28716f4d01614b36b9"),
        },
    },
    "sequenza_scarhrd": {
        "job_definition_name": "diana-hrd-sequenza-scarhrd",
        "job_definition_arn": ("arn:aws:batch:us-east-1:172630973301:job-definition/diana-hrd-sequenza-scarhrd:3"),
        "revision": 3,
        "timeout_seconds": 259200,
        "command": ["sequenza_scarhrd"],
        "image": (
            "172630973301.dkr.ecr.us-east-1.amazonaws.com/"
            "diana-hrd-sequenza@"
            "sha256:4ba1c915409ecedfc0beb5373a2bddbbb0866823a554fafc5243e10670c5a151"
        ),
        "vcpus": 32,
        "memory": 122880,
        "definition_environment": {
            "AWS_REGION": REGION,
            "HRD_CROSSCHECK_IMAGE_REFERENCE": (
                "172630973301.dkr.ecr.us-east-1.amazonaws.com/"
                "diana-hrd-sequenza@"
                "sha256:4ba1c915409ecedfc0beb5373a2bddbbb0866823a554fafc5243e10670c5a151"
            ),
            "HRD_CROSSCHECK_IMAGE_SECURITY_RECEIPT_SHA256": ("7a8a59aef77788b44b85dec1c6b9dcd90be6513ad738c57bf1666f913ec31ac5"),
        },
    },
}

SUBMISSION_ENVIRONMENT_NAMES = (
    "HRD_CROSSCHECK_INPUT_CONTRACT_URI",
    "HRD_CROSSCHECK_INPUT_CONTRACT_VERSION_ID",
    "HRD_CROSSCHECK_INPUT_CONTRACT_SHA256",
    "HRD_CROSSCHECK_OUTPUT_URI",
    "HRD_CROSSCHECK_ROUTE_OUTPUT_URI",
    "HRD_CROSSCHECK_PUBLICATION_RECEIPT_PREFIX",
    "HRD_CROSSCHECK_SUBMISSION_ID",
)
ANCHOR_CHECKS = {
    "version_exact",
    "bytes_exact",
    "sha256_exact",
    "sha256_checksum_exact",
    "metadata_sha256_exact",
    "exact_kms",
    "single_create_only_version",
}
RECEIPT_CHECKS = {
    "exact_contract_version_bound",
    "route_prefix_initially_empty",
    "all_outputs_create_only",
    "all_output_versions_exact",
    "no_extra_versions_or_delete_markers",
}
OBJECT_CHECKS = {
    "create_only_put",
    "version_exact",
    "bytes_exact",
    "metadata_sha256_exact",
    "exact_kms",
}
HISTORY_AUDIT_CHECKS = {
    "version_exact",
    "bytes_exact",
    "metadata_sha256_exact",
    "checksum_sha256_exact",
    "exact_kms",
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
    try:
        decoded = base64.b64decode(str(value), validate=True)
    except Exception as error:
        raise ValueError(f"{label} is not valid base64: {error}") from error
    if len(decoded) != 32:
        raise ValueError(f"{label} is not a SHA-256 checksum")
    return decoded.hex()


def valid_version_id(value: str) -> bool:
    return bool(value and value.lower() not in {"none", "null"} and not any(character.isspace() for character in value))


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


def get_exact_object(
    region: str,
    bucket: str,
    key: str,
    version_id: str,
    destination: Path,
) -> dict[str, Any]:
    require_safe_download_destination(destination, "downloaded route receipt")
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
    require_real_downloaded_file(destination, "downloaded route receipt")
    return payload


def require_one(payload: dict[str, Any], key: str) -> dict[str, Any]:
    rows = payload.get(key)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"expected exactly one {key} record")
    return rows[0]


def s3_location(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if parsed.scheme != "s3" or not parsed.netloc or not key or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"expected an S3 object URI: {uri}")
    if not parsed.netloc.startswith("diana-omics-private-results-"):
        raise ValueError("object is outside the private-results bucket")
    return parsed.netloc, key


def normalize_environment(values: Any, label: str) -> dict[str, str]:
    if not isinstance(values, list):
        raise ValueError(f"{label} environment is not a list")
    result: dict[str, str] = {}
    for row in values:
        if not isinstance(row, dict) or set(row) != {"name", "value"}:
            raise ValueError(f"{label} environment row is malformed")
        name = row.get("name")
        value = row.get("value")
        if not isinstance(name, str) or not name or not isinstance(value, str):
            raise ValueError(f"{label} environment row is malformed")
        if name in result:
            raise ValueError(f"{label} environment has duplicate variable: {name}")
        result[name] = value
    return result


def expected_submission_environment(args: argparse.Namespace) -> dict[str, str]:
    route_root = args.expected_output_uri.rstrip("/")
    route_output_uri = f"{route_root}/crosschecks/{args.expected_contract_sha256}/{args.route}/{args.submission_id}/"
    receipt_prefix = f"{route_root}/crosscheck-publication-receipts/{args.expected_contract_sha256}/{args.route}/{args.submission_id}/"
    values = {
        "HRD_CROSSCHECK_INPUT_CONTRACT_URI": args.expected_contract_uri,
        "HRD_CROSSCHECK_INPUT_CONTRACT_VERSION_ID": (args.expected_contract_version_id),
        "HRD_CROSSCHECK_INPUT_CONTRACT_SHA256": (args.expected_contract_sha256),
        "HRD_CROSSCHECK_OUTPUT_URI": args.expected_output_uri,
        "HRD_CROSSCHECK_ROUTE_OUTPUT_URI": route_output_uri,
        "HRD_CROSSCHECK_PUBLICATION_RECEIPT_PREFIX": receipt_prefix,
        "HRD_CROSSCHECK_SUBMISSION_ID": args.submission_id,
    }
    if set(values) != set(SUBMISSION_ENVIRONMENT_NAMES):
        raise AssertionError("internal submission environment contract changed")
    return values


def require_new_private_output_paths(paths: Iterable[Path]) -> None:
    rows = list(paths)
    if not rows:
        raise ValueError("private output paths must be distinct and nonempty")
    for path in rows:
        require_safe_private_output_parent(path)
    resolved = {path.resolve(strict=False) for path in rows}
    if len(resolved) != len(rows):
        raise ValueError("private output paths must be distinct and nonempty")
    for path in rows:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite private output: {path}")


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


def validate_arguments(args: argparse.Namespace) -> dict[str, str]:
    output_paths = (
        args.capture_output,
        args.receipt_output,
        args.anchor_output,
    )
    require_new_private_output_paths(output_paths)
    if args.route not in ROUTES:
        raise ValueError("unsupported route")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_contract_sha256):
        raise ValueError("expected contract SHA-256 is malformed")
    if not valid_version_id(args.expected_contract_version_id):
        raise ValueError("expected contract VersionId is malformed")
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[a-z0-9]{8,32}", args.submission_id):
        raise ValueError("submission ID is malformed")
    s3_location(args.expected_contract_uri)
    output_bucket, output_key = s3_location(args.expected_output_uri.rstrip("/"))
    if not output_bucket or not output_key:
        raise AssertionError("validated output URI is unexpectedly empty")
    if not re.fullmatch(
        r"arn:aws:kms:us-east-1:172630973301:key/[A-Za-z0-9-]+",
        args.expected_kms_key_arn,
    ):
        raise ValueError("expected KMS key ARN is malformed")
    return expected_submission_environment(args)


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


def parse_terminal_payload(
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
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
        if isinstance(value, dict) and set(value) == {"publication_anchor"} and isinstance(value.get("publication_anchor"), dict):
            candidates.append((start, end, value))
    if len(candidates) != 1:
        raise ValueError("expected exactly one complete route publication anchor in CloudWatch")
    start, end, payload = candidates[0]
    if text[end:].strip():
        raise ValueError("route publication anchor is not terminal CloudWatch output")
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
        for field, kind in (
            ("Versions", "version"),
            ("DeleteMarkers", "delete_marker"),
        ):
            values = page.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
                raise ValueError("S3 receipt version history is malformed")
            rows.extend({**value, "history_kind": kind} for value in values)
        if page.get("IsTruncated") is not True:
            return rows
        key_marker = str(page.get("NextKeyMarker", ""))
        version_marker = str(page.get("NextVersionIdMarker", ""))
        if not key_marker or not version_marker:
            raise ValueError(
                "truncated receipt history omitted its next key/version markers"
            )
        marker = (key_marker, version_marker)
        if marker in seen_markers:
            raise ValueError("S3 receipt history pagination did not advance")
        seen_markers.add(marker)
    raise ValueError("S3 receipt history pagination exceeded the safety limit")


def validate_job(
    job: dict[str, Any],
    definition: dict[str, Any],
    queue: dict[str, Any],
    compute_environment: dict[str, Any],
    args: argparse.Namespace,
    submission_environment: dict[str, str],
) -> dict[str, Any]:
    route = ROUTES[args.route]
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
    properties = definition.get("containerProperties")
    if not isinstance(properties, dict):
        raise ValueError("Batch definition container properties are missing")
    definition_environment = normalize_environment(properties.get("environment"), "definition")
    job_environment = normalize_environment(container.get("environment"), "job")
    # DescribeJobs exposes the submit-job container overrides here, not the
    # job-definition environment.  Require exactly the seven one-shot
    # submission bindings; the static image/security environment is validated
    # independently against the live revision-3 definition below.
    expected_job_environment = submission_environment
    log_configuration = properties.get("logConfiguration")
    resources = compute_environment.get("computeResources")
    instance_types = resources.get("instanceTypes") if isinstance(resources, dict) else None
    queue_order = queue.get("computeEnvironmentOrder")
    job_log_stream = str(container.get("logStreamName", ""))
    attempt_log_stream = str(attempt_container.get("logStreamName", ""))
    checks = {
        "job_id_exact": job.get("jobId") == args.job_id,
        "succeeded": job.get("status") == "SUCCEEDED",
        "terminal_timestamps": (int(job.get("startedAt", 0)) > 0 and int(job.get("stoppedAt", 0)) >= int(job.get("startedAt", 0))),
        "exact_job_definition": (job.get("jobDefinition") == route["job_definition_arn"]),
        "exact_queue": job.get("jobQueue") == EXPECTED_QUEUE_ARN,
        "one_retry_attempt": (isinstance(retry, dict) and retry.get("attempts") == 1),
        "one_terminal_attempt": len(attempts) == 1,
        "job_exit_zero": container.get("exitCode") == 0,
        "attempt_exit_zero": attempt_container.get("exitCode") == 0,
        "job_environment_exact": job_environment == expected_job_environment,
        "submission_environment_exact": all(job_environment.get(name) == value for name, value in submission_environment.items()),
        "log_stream_exact": (
            bool(job_log_stream) and job_log_stream == attempt_log_stream and job_log_stream.startswith(LOG_STREAM_PREFIX + "/")
        ),
        "definition_identity_exact": (
            definition.get("jobDefinitionArn") == route["job_definition_arn"]
            and definition.get("jobDefinitionName") == route["job_definition_name"]
            and definition.get("revision") == route["revision"]
            and definition.get("status") == "ACTIVE"
            and definition.get("type") == "container"
            and definition.get("platformCapabilities") == ["EC2"]
            and definition.get("retryStrategy") == {"attempts": 1, "evaluateOnExit": []}
            and definition.get("timeout") == {"attemptDurationSeconds": route["timeout_seconds"]}
        ),
        "definition_container_exact": (
            properties.get("command") == route["command"]
            and properties.get("image") == route["image"]
            and properties.get("jobRoleArn") == EXPECTED_JOB_ROLE
            and properties.get("vcpus") == route["vcpus"]
            and properties.get("memory") == route["memory"]
            and definition_environment == route["definition_environment"]
        ),
        "definition_log_exact": (
            isinstance(log_configuration, dict)
            and log_configuration
            == {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": LOG_GROUP,
                    "awslogs-region": REGION,
                    "awslogs-stream-prefix": LOG_STREAM_PREFIX,
                },
                "secretOptions": [],
            }
        ),
        "queue_live_exact": (
            queue.get("jobQueueArn") == EXPECTED_QUEUE_ARN
            and queue.get("jobQueueName") == EXPECTED_QUEUE_NAME
            and queue.get("state") == "ENABLED"
            and queue.get("status") == "VALID"
            and queue.get("priority") == 30
            and queue_order == [{"order": 1, "computeEnvironment": EXPECTED_COMPUTE_ENVIRONMENT}]
        ),
        "x86_compute_environment_live_exact": (
            compute_environment.get("computeEnvironmentArn") == EXPECTED_COMPUTE_ENVIRONMENT
            and compute_environment.get("computeEnvironmentName") == EXPECTED_QUEUE_NAME
            and compute_environment.get("state") == "ENABLED"
            and compute_environment.get("status") == "VALID"
            and compute_environment.get("type") == "MANAGED"
            and compute_environment.get("containerOrchestrationType") == "ECS"
            and isinstance(resources, dict)
            and resources.get("type") == "EC2"
            and resources.get("allocationStrategy") == "BEST_FIT_PROGRESSIVE"
            and resources.get("minvCpus") == 0
            and resources.get("maxvCpus") == 128
            and isinstance(instance_types, list)
            and len(instance_types) == len(EXPECTED_X86_INSTANCE_TYPES)
            and sorted(str(value) for value in instance_types) == sorted(EXPECTED_X86_INSTANCE_TYPES)
            and resources.get("launchTemplate")
            == {
                "launchTemplateId": "lt-0b2375486d24af74a",
                "version": "3",
                "overrides": [],
            }
            and resources.get("ec2Configuration") == [{"imageType": "ECS_AL2023"}]
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"terminal route Batch identity failed: {checks}")
    return {
        "route": args.route,
        "job_id": args.job_id,
        "job_name": str(job.get("jobName", "")),
        "status": "SUCCEEDED",
        "started_at_epoch_ms": int(job["startedAt"]),
        "stopped_at_epoch_ms": int(job["stoppedAt"]),
        "job_definition_arn": route["job_definition_arn"],
        "job_queue_arn": EXPECTED_QUEUE_ARN,
        "compute_environment_arn": EXPECTED_COMPUTE_ENVIRONMENT,
        "attempt_count": 1,
        "exit_code": 0,
        "submission_environment": submission_environment,
        "effective_environment": job_environment,
        "log_group": LOG_GROUP,
        "log_stream": job_log_stream,
        "checks": checks,
    }


def validate_logged_anchor(
    payload: dict[str, Any],
    args: argparse.Namespace,
    submission_environment: dict[str, str],
) -> dict[str, Any]:
    if set(payload) != {"publication_anchor"}:
        raise ValueError("terminal route payload keys are not exact")
    anchor = payload.get("publication_anchor")
    if not isinstance(anchor, dict):
        raise ValueError("terminal route publication anchor is malformed")
    expected_anchor_keys = {
        "schema_version",
        "status",
        "receipt_sha256",
        "receipt_bytes",
        "receipt_uri",
        "receipt_version_id",
        "route_output_uri",
        "checks",
    }
    anchor_checks = anchor.get("checks")
    receipt_sha = str(anchor.get("receipt_sha256", ""))
    receipt_bytes = anchor.get("receipt_bytes")
    receipt_uri = str(anchor.get("receipt_uri", ""))
    receipt_version = str(anchor.get("receipt_version_id", ""))
    bucket, key = s3_location(receipt_uri)
    receipt_prefix = submission_environment["HRD_CROSSCHECK_PUBLICATION_RECEIPT_PREFIX"]
    expected_bucket, expected_prefix_key = s3_location(receipt_prefix + "sentinel")
    expected_key = expected_prefix_key.removesuffix("sentinel") + receipt_sha + ".json"
    checks = {
        "anchor_keys_exact": set(anchor) == expected_anchor_keys,
        "anchor_schema_status": (anchor.get("schema_version") == 1 and anchor.get("status") == "passed"),
        "anchor_checks_exact": (
            isinstance(anchor_checks, dict)
            and set(anchor_checks) == ANCHOR_CHECKS
            and all(value is True for value in anchor_checks.values())
        ),
        "receipt_sha256_well_formed": bool(re.fullmatch(r"[0-9a-f]{64}", receipt_sha)),
        "receipt_bytes_positive": (isinstance(receipt_bytes, int) and not isinstance(receipt_bytes, bool) and receipt_bytes > 0),
        "receipt_version_nonempty": valid_version_id(receipt_version),
        "receipt_uri_content_addressed": (bucket == expected_bucket and key == expected_key),
        "route_output_uri_exact": (anchor.get("route_output_uri") == submission_environment["HRD_CROSSCHECK_ROUTE_OUTPUT_URI"]),
    }
    if not all(checks.values()):
        raise ValueError(f"logged route publication anchor failed: {checks}")
    return {
        "bucket": bucket,
        "key": key,
        "uri": receipt_uri,
        "version_id": receipt_version,
        "sha256": receipt_sha,
        "bytes": int(receipt_bytes),
        "kms_key_arn": args.expected_kms_key_arn,
        "checks": checks,
    }


def validate_output_rows(
    receipt: dict[str, Any],
    route_output_uri: str,
    expected_kms_key_arn: str,
) -> dict[str, bool]:
    objects = receipt.get("objects")
    audit = receipt.get("history_audit")
    if (
        not isinstance(objects, list)
        or not objects
        or any(not isinstance(row, dict) for row in objects)
        or not isinstance(audit, list)
        or len(audit) != len(objects)
        or any(not isinstance(row, dict) for row in audit)
    ):
        raise ValueError("route receipt object/history rows are malformed")
    bucket, prefix = s3_location(route_output_uri + "sentinel")
    prefix = prefix.removesuffix("sentinel")
    object_bindings: set[tuple[str, str, str]] = set()
    relative_paths: set[str] = set()
    for row in objects:
        required = {
            "relative_path",
            "uri",
            "key",
            "sha256",
            "etag",
            "version_id",
            "content_length",
            "server_side_encryption",
            "ssekms_key_id",
            "checksum_sha256",
            "checks",
        }
        row_checks = row.get("checks")
        relative_path = row.get("relative_path")
        key = row.get("key")
        uri = row.get("uri")
        sha = str(row.get("sha256", ""))
        version_id = str(row.get("version_id", ""))
        row_bucket = ""
        row_key = ""
        if isinstance(uri, str):
            with contextlib.suppress(ValueError):
                row_bucket, row_key = s3_location(uri)
        valid = (
            set(row) == required
            and isinstance(relative_path, str)
            and bool(relative_path)
            and not relative_path.startswith("/")
            and ".." not in Path(relative_path).parts
            and isinstance(key, str)
            and key == row_key
            and row_bucket == bucket
            and key == prefix + relative_path
            and bool(re.fullmatch(r"[0-9a-f]{64}", sha))
            and valid_version_id(version_id)
            and isinstance(row.get("content_length"), int)
            and not isinstance(row.get("content_length"), bool)
            and row["content_length"] > 0
            and row.get("server_side_encryption") == "aws:kms"
            and row.get("ssekms_key_id") == expected_kms_key_arn
            and isinstance(row_checks, dict)
            and set(row_checks) == OBJECT_CHECKS
            and all(value is True for value in row_checks.values())
        )
        if valid:
            try:
                valid = (
                    decode_sha256(
                        row.get("checksum_sha256"),
                        f"output {relative_path} ChecksumSHA256",
                    )
                    == sha
                )
            except ValueError:
                valid = False
        if not valid:
            raise ValueError(f"route receipt output row failed: {relative_path}")
        binding = (key, version_id, sha)
        if binding in object_bindings or relative_path in relative_paths:
            raise ValueError("route receipt output rows are duplicated")
        object_bindings.add(binding)
        relative_paths.add(relative_path)

    audit_bindings: set[tuple[str, str, str]] = set()
    for row in audit:
        row_checks = row.get("checks")
        binding = (
            str(row.get("key", "")),
            str(row.get("version_id", "")),
            str(row.get("sha256", "")),
        )
        if (
            set(row) != {"key", "version_id", "sha256", "checks"}
            or not isinstance(row_checks, dict)
            or set(row_checks) != HISTORY_AUDIT_CHECKS
            or any(value is not True for value in row_checks.values())
            or binding in audit_bindings
        ):
            raise ValueError("route receipt history audit row failed")
        audit_bindings.add(binding)
    checks = {
        "output_rows_unique_and_exact_prefix": len(object_bindings) == len(objects),
        "history_audit_binds_every_output": audit_bindings == object_bindings,
        "successful_report_products_present": {
            "report.md",
            "report_manifest.json",
            "upload_receipt.json",
            "report_upload_receipt.json",
        }.issubset(relative_paths),
    }
    if not all(checks.values()):
        raise ValueError(f"route receipt output inventory failed: {checks}")
    return checks


def validate_exact_receipt(
    receipt_bytes: bytes,
    get_response: dict[str, Any],
    head_response: dict[str, Any],
    history: list[dict[str, Any]],
    location: dict[str, Any],
    args: argparse.Namespace,
    submission_environment: dict[str, str],
) -> tuple[dict[str, Any], dict[str, bool]]:
    local_sha = sha256_bytes(receipt_bytes)
    try:
        receipt = json.loads(receipt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"downloaded route receipt is not JSON: {error}") from error
    if not isinstance(receipt, dict):
        raise ValueError("downloaded route receipt is not an object")
    receipt_checks = receipt.get("checks")
    expected_receipt_keys = {
        "schema_version",
        "status",
        "route",
        "submission_id",
        "contract",
        "route_output_uri",
        "route_output_initial_version_history_count",
        "route_output_bucket_versioning",
        "publication_strategy",
        "objects",
        "history_audit",
        "checks",
    }
    expected_contract = {
        "uri": args.expected_contract_uri,
        "version_id": args.expected_contract_version_id,
        "sha256": args.expected_contract_sha256,
    }
    exact_history = (
        len(history) == 1
        and history[0].get("history_kind") == "version"
        and history[0].get("Key") == location["key"]
        and history[0].get("VersionId") == location["version_id"]
        and history[0].get("IsLatest") is True
    )
    output_checks = validate_output_rows(
        receipt,
        submission_environment["HRD_CROSSCHECK_ROUTE_OUTPUT_URI"],
        args.expected_kms_key_arn,
    )
    checks = {
        "receipt_keys_exact": set(receipt) == expected_receipt_keys,
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
            get_response.get("ServerSideEncryption") == "aws:kms" and get_response.get("SSEKMSKeyId") == args.expected_kms_key_arn
        ),
        "head_kms_exact": (
            head_response.get("ServerSideEncryption") == "aws:kms" and head_response.get("SSEKMSKeyId") == args.expected_kms_key_arn
        ),
        "get_metadata_sha256_exact": (
            isinstance(get_response.get("Metadata"), dict) and get_response["Metadata"].get("sha256") == local_sha
        ),
        "head_metadata_sha256_exact": (
            isinstance(head_response.get("Metadata"), dict) and head_response["Metadata"].get("sha256") == local_sha
        ),
        "single_version_no_delete_history": exact_history,
        "receipt_schema_status": (receipt.get("schema_version") == 1 and receipt.get("status") == "passed"),
        "receipt_route_submission_exact": (receipt.get("route") == args.route and receipt.get("submission_id") == args.submission_id),
        "receipt_contract_exact": receipt.get("contract") == expected_contract,
        "receipt_output_exact": (
            receipt.get("route_output_uri") == submission_environment["HRD_CROSSCHECK_ROUTE_OUTPUT_URI"]
            and receipt.get("route_output_initial_version_history_count") == 0
            and receipt.get("route_output_bucket_versioning") == "Enabled"
            and receipt.get("publication_strategy") == "one_shot_create_only_exact_version_history"
        ),
        "receipt_checks_exact": (
            isinstance(receipt_checks, dict)
            and set(receipt_checks) == RECEIPT_CHECKS
            and all(value is True for value in receipt_checks.values())
        ),
        "output_inventory_exact": all(output_checks.values()),
    }
    if not all(checks.values()):
        raise ValueError(f"exact route receipt verification failed: {checks}")
    return receipt, checks


def create_private_outputs(outputs: Iterable[tuple[Path, bytes]]) -> None:
    rows = list(outputs)
    require_new_private_output_paths(path for path, _ in rows)
    expected_sha256 = {path: sha256_bytes(content) for path, content in rows}
    descriptors: dict[Path, int] = {}
    created: list[Path] = []
    try:
        # Reserve every path before writing any content.  A concurrent
        # collision therefore leaves either all three outputs or none of the
        # paths created by this invocation.
        for path, _ in rows:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptors[path] = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
        for path, content in rows:
            descriptor = descriptors.pop(path)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        for path, _ in rows:
            if (path.stat().st_mode & 0o777) != 0o600:
                raise ValueError(f"private output mode is not 0600: {path}")
        for parent in dict.fromkeys(path.parent for path, _ in rows):
            fsync_directory(parent)
        require_installed_private_outputs(expected_sha256)
    except Exception:
        for descriptor in descriptors.values():
            with contextlib.suppress(OSError):
                os.close(descriptor)
        for path in created:
            with contextlib.suppress(OSError):
                path.unlink()
        raise


def require_installed_private_outputs(expected_sha256: dict[Path, str]) -> None:
    for path, expected in expected_sha256.items():
        require_no_symlinked_ancestors(path, "private output")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"private output changed during write: {path}")
        if sha256_bytes(path.read_bytes()) != expected:
            raise ValueError(f"private output changed during write: {path}")


def create_private(path: Path, content: bytes) -> None:
    create_private_outputs([(path, content)])


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def capture(args: argparse.Namespace) -> dict[str, Any]:
    submission_environment = validate_arguments(args)
    route = ROUTES[args.route]
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
            route["job_definition_arn"],
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
        args,
        submission_environment,
    )
    events = collect_log_events(args.region, batch["log_stream"])
    terminal_payload, terminal_json = parse_terminal_payload(events)
    location = validate_logged_anchor(terminal_payload, args, submission_environment)
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
    with tempfile.TemporaryDirectory(prefix="diana-route-terminal-") as temporary:
        temporary_path = Path(temporary) / "publication-receipt.json"
        get_response = get_exact_object(
            args.region,
            location["bucket"],
            location["key"],
            location["version_id"],
            temporary_path,
        )
        require_real_downloaded_file(temporary_path, "downloaded route receipt")
        downloaded = temporary_path.read_bytes()
    receipt, receipt_checks = validate_exact_receipt(
        downloaded,
        get_response,
        head_response,
        history,
        location,
        args,
        submission_environment,
    )
    anchor_bytes = (json.dumps(terminal_payload["publication_anchor"], indent=2, sort_keys=True) + "\n").encode("utf-8")
    event_messages = [str(event.get("message", "")) for event in events]
    capture_payload = {
        "schema_version": 1,
        "status": "passed",
        "captured_at_utc": now(),
        "scope": "private read-only terminal HRD cross-check route custody capture",
        "batch": batch,
        "cloudwatch": {
            "log_group": LOG_GROUP,
            "log_stream": batch["log_stream"],
            "event_count": len(events),
            "first_event_timestamp": (int(events[0].get("timestamp", 0)) if events else 0),
            "last_event_timestamp": (int(events[-1].get("timestamp", 0)) if events else 0),
            "messages_sha256": canonical_sha256(event_messages),
            "terminal_payload_sha256": canonical_sha256(terminal_payload),
            "terminal_json_sha256": sha256_bytes(terminal_json.encode("utf-8")),
            "publication_anchor": terminal_payload["publication_anchor"],
            "publication_anchor_local": {
                "output": str(args.anchor_output.resolve()),
                "sha256": sha256_bytes(anchor_bytes),
                "bytes": len(anchor_bytes),
            },
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
            "route": receipt["route"],
            "submission_id": receipt["submission_id"],
            "contract": receipt["contract"],
            "route_output_uri": receipt["route_output_uri"],
            "published_object_count": len(receipt["objects"]),
        },
        "checks": {
            "terminal_batch_identity": True,
            "exact_route_revision_3": True,
            "exact_live_x86_queue_and_compute_environment": True,
            "exact_submission_environment": True,
            "exact_attempt_cloudwatch_stream": True,
            "single_terminal_publication_anchor": True,
            "logged_receipt_binding": True,
            "bucket_versioning_enabled": True,
            "exact_version_get": True,
            "exact_version_head": True,
            "logged_local_sha256_and_bytes": True,
            "s3_sha256_checksums": True,
            "exact_kms": True,
            "single_version_no_delete_history": True,
            "receipt_contract_route_submission_exact": True,
            "receipt_output_inventory_exact": True,
            "private_mode_0600": True,
        },
        "boundary": {
            "classification_authorization": "none",
            "authorized_hrd_state": "no_call_until_downstream_report_review",
        },
    }
    capture_bytes = (json.dumps(capture_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    create_private_outputs(
        [
            (args.receipt_output, downloaded),
            (args.anchor_output, anchor_bytes),
            (args.capture_output, capture_bytes),
        ]
    )
    return capture_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, choices=sorted(ROUTES))
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--expected-contract-uri", required=True)
    parser.add_argument("--expected-contract-version-id", required=True)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--expected-output-uri", required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--expected-kms-key-arn", required=True)
    parser.add_argument("--capture-output", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--anchor-output", required=True, type=Path)
    parser.add_argument("--region", default=REGION, choices=[REGION])
    args = parser.parse_args()
    try:
        result = capture(args)
    except (
        FileExistsError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    print(
        json.dumps(
            {
                "status": result["status"],
                "route": result["batch"]["route"],
                "job_id": result["batch"]["job_id"],
                "receipt_uri": result["receipt"]["uri"],
                "receipt_version_id": result["receipt"]["version_id"],
                "capture_output": str(args.capture_output),
                "receipt_output": str(args.receipt_output),
                "anchor_output": str(args.anchor_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
