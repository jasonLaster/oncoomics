#!/usr/bin/env python3
"""Render and, only with explicit guards, submit one exact HRD route.

Every pre-submit AWS operation is read-only.  The request receipt is written
create-only and mode 0600 before submission.  A distinct response receipt is
reserved create-only before the AWS mutation and completed with either the
exact Batch response or a fail-closed ambiguity record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_contract import private_output, validate

REGION = "us-east-1"
ACCOUNT_ID = "172630973301"
PRIVATE_BUCKET = f"diana-omics-private-results-{ACCOUNT_ID}-{REGION}"
QUEUE_NAME = "diana-omics-prod-use1-hrd-x86-ondemand"
QUEUE_ARN = f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:job-queue/{QUEUE_NAME}"
COMPUTE_ENVIRONMENT_ARN = f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:compute-environment/{QUEUE_NAME}"
EXPECTED_JOB_ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/diana-omics-prod-use1-batch-job"
EXPECTED_INSTANCE_TYPES = ("c7i", "m7i", "r7i")
LOG_GROUP = "/aws/batch/diana-omics-prod-use1"
LOG_STREAM_PREFIX = "hrd-crosscheck"
JOB_STATUSES = (
    "SUBMITTED",
    "PENDING",
    "RUNNABLE",
    "STARTING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
)
SUBMISSION_ENVIRONMENT_NAMES = (
    "HRD_CROSSCHECK_INPUT_CONTRACT_URI",
    "HRD_CROSSCHECK_INPUT_CONTRACT_VERSION_ID",
    "HRD_CROSSCHECK_INPUT_CONTRACT_SHA256",
    "HRD_CROSSCHECK_OUTPUT_URI",
    "HRD_CROSSCHECK_ROUTE_OUTPUT_URI",
    "HRD_CROSSCHECK_PUBLICATION_RECEIPT_PREFIX",
    "HRD_CROSSCHECK_SUBMISSION_ID",
)

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
        "repository": "diana-hrd-sigprofiler",
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
        "repository": "diana-hrd-sequenza",
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


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def valid_version_id(value: str) -> bool:
    return bool(value and value.lower() not in {"none", "null"} and not any(character.isspace() for character in value))


def validate_contract_anchor(
    anchor_path: Path,
    contract_path: Path,
    contract_uri: str,
    contract_version_id: str,
) -> dict[str, Any]:
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    if not isinstance(anchor, dict):
        raise ValueError("contract publication anchor is not a JSON object")
    checks = anchor.get("checks")
    if (
        anchor.get("schema_version") != 1
        or anchor.get("status") != "passed"
        or anchor.get("receipt_uri") != contract_uri
        or anchor.get("receipt_version_id") != contract_version_id
        or str(anchor.get("receipt_sha256", "")).lower() != digest(contract_path)
        or int(anchor.get("receipt_bytes", -1)) != contract_path.stat().st_size
        or anchor.get("publication_strategy") != "sha256_content_addressed_create_only"
        or anchor.get("initial_version_history_count") != 0
        or not isinstance(checks, dict)
        or not checks
        or any(value is not True for value in checks.values())
    ):
        raise ValueError("contract publication anchor does not bind the exact contract version")
    return anchor


def aws_json(region: str, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["aws", *arguments, "--region", region, "--output", "json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"AWS command returned a non-object: {' '.join(arguments)}")
    return value


def require_one(payload: dict[str, Any], field: str) -> dict[str, Any]:
    values = payload.get(field)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError(f"expected exactly one AWS {field} row")
    return values[0]


def normalize_environment(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        raise ValueError("job-definition environment is not a list")
    result: dict[str, str] = {}
    for row in value:
        if not isinstance(row, dict) or set(row) != {"name", "value"}:
            raise ValueError("job-definition environment row is malformed")
        name = str(row["name"])
        if not name or name in result:
            raise ValueError("job-definition environment has an empty or duplicate name")
        result[name] = str(row["value"])
    return result


def validate_live_definition(route_name: str, region: str) -> dict[str, Any]:
    route = ROUTES[route_name]
    definition = require_one(
        aws_json(
            region,
            "batch",
            "describe-job-definitions",
            "--job-definitions",
            route["job_definition_arn"],
        ),
        "jobDefinitions",
    )
    properties = definition.get("containerProperties")
    if not isinstance(properties, dict):
        raise ValueError("live route definition lacks containerProperties")
    environment = normalize_environment(properties.get("environment"))
    log_configuration = properties.get("logConfiguration")
    checks = {
        "exact_arn": definition.get("jobDefinitionArn") == route["job_definition_arn"],
        "exact_name_revision": definition.get("jobDefinitionName") == route["job_definition_name"] and definition.get("revision") == 3,
        "active_container_ec2": definition.get("status") == "ACTIVE"
        and definition.get("type") == "container"
        and definition.get("platformCapabilities") == ["EC2"],
        "one_attempt": definition.get("retryStrategy") == {"attempts": 1, "evaluateOnExit": []},
        "exact_timeout": definition.get("timeout") == {"attemptDurationSeconds": route["timeout_seconds"]},
        "immutable_image": properties.get("image") == route["image"] and "@sha256:" in str(properties.get("image", "")),
        "exact_command_resources_role": properties.get("command") == route["command"]
        and properties.get("vcpus") == route["vcpus"]
        and properties.get("memory") == route["memory"]
        and properties.get("jobRoleArn") == EXPECTED_JOB_ROLE,
        "exact_static_environment": environment == route["definition_environment"],
        "exact_logging": log_configuration
        == {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": LOG_GROUP,
                "awslogs-region": REGION,
                "awslogs-stream-prefix": LOG_STREAM_PREFIX,
            },
            "secretOptions": [],
        },
    }
    if not all(checks.values()):
        raise ValueError(f"live route revision 3 differs from the exact expected definition: {checks}")
    return {
        "job_definition_arn": route["job_definition_arn"],
        "image": route["image"],
        "static_environment": environment,
        "checks": checks,
    }


def validate_live_image(route_name: str, region: str) -> dict[str, Any]:
    route = ROUTES[route_name]
    digest_value = str(route["image"]).rsplit("@", 1)[1]
    payload = aws_json(
        region,
        "ecr",
        "batch-get-image",
        "--repository-name",
        route["repository"],
        "--image-ids",
        f"imageDigest={digest_value}",
        "--accepted-media-types",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
    if payload.get("failures") not in (None, []):
        raise ValueError("ECR returned failures for the immutable route image")
    image = require_one(payload, "images")
    manifest = json.loads(str(image.get("imageManifest", "")))
    manifests = manifest.get("manifests") if isinstance(manifest, dict) else None
    if not isinstance(manifests, list) or not manifests:
        raise ValueError("route image is not an OCI/Docker image index")
    runnable = [
        row
        for row in manifests
        if isinstance(row, dict)
        and isinstance(row.get("platform"), dict)
        and row["platform"].get("os") != "unknown"
        and row["platform"].get("architecture") != "unknown"
    ]
    attestations = [row for row in manifests if row not in runnable]
    attestations_valid = all(
        isinstance(row, dict)
        and row.get("platform") == {"architecture": "unknown", "os": "unknown"}
        and isinstance(row.get("annotations"), dict)
        and row["annotations"].get("vnd.docker.reference.type") == "attestation-manifest"
        for row in attestations
    )
    checks = {
        "exact_index_digest": (image.get("imageId") or {}).get("imageDigest") == digest_value,
        "index_media_type": image.get("imageManifestMediaType")
        in {
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
        },
        "one_runnable_manifest": len(runnable) == 1,
        "linux_amd64_only": len(runnable) == 1 and runnable[0].get("platform") == {"architecture": "amd64", "os": "linux"},
        "other_manifests_are_attestations": attestations_valid,
    }
    if not all(checks.values()):
        raise ValueError(f"immutable route image is not exact amd64: {checks}")
    return {
        "image": route["image"],
        "runnable_digest": runnable[0].get("digest"),
        "attestation_count": len(attestations),
        "checks": checks,
    }


def validate_live_queue(region: str) -> dict[str, Any]:
    queue = require_one(
        aws_json(
            region,
            "batch",
            "describe-job-queues",
            "--job-queues",
            QUEUE_ARN,
        ),
        "jobQueues",
    )
    compute = require_one(
        aws_json(
            region,
            "batch",
            "describe-compute-environments",
            "--compute-environments",
            COMPUTE_ENVIRONMENT_ARN,
        ),
        "computeEnvironments",
    )
    resources = compute.get("computeResources")
    instance_types = resources.get("instanceTypes") if isinstance(resources, dict) else None
    checks = {
        "exact_queue": queue.get("jobQueueArn") == QUEUE_ARN and queue.get("jobQueueName") == QUEUE_NAME,
        "queue_live": queue.get("state") == "ENABLED" and queue.get("status") == "VALID",
        "queue_priority": queue.get("priority") == 30,
        "queue_exact_ce": queue.get("computeEnvironmentOrder") == [{"order": 1, "computeEnvironment": COMPUTE_ENVIRONMENT_ARN}],
        "exact_compute_environment": compute.get("computeEnvironmentArn") == COMPUTE_ENVIRONMENT_ARN
        and compute.get("computeEnvironmentName") == QUEUE_NAME,
        "compute_environment_live": compute.get("state") == "ENABLED"
        and compute.get("status") == "VALID"
        and compute.get("type") == "MANAGED"
        and compute.get("containerOrchestrationType") == "ECS",
        "exact_x86_resources": isinstance(resources, dict)
        and resources.get("type") == "EC2"
        and resources.get("allocationStrategy") == "BEST_FIT_PROGRESSIVE"
        and resources.get("minvCpus") == 0
        and resources.get("maxvCpus") == 128
        and isinstance(instance_types, list)
        and sorted(str(value) for value in instance_types) == sorted(EXPECTED_INSTANCE_TYPES)
        and resources.get("launchTemplate")
        == {
            "launchTemplateId": "lt-0b2375486d24af74a",
            "version": "3",
            "overrides": [],
        }
        and resources.get("ec2Configuration") == [{"imageType": "ECS_AL2023"}],
    }
    if not all(checks.values()):
        raise ValueError(f"live x86 queue/compute environment is not exact: {checks}")
    return {
        "job_queue_arn": QUEUE_ARN,
        "compute_environment_arn": COMPUTE_ENVIRONMENT_ARN,
        "instance_types": sorted(EXPECTED_INSTANCE_TYPES),
        "checks": checks,
    }


def paginated_rows(
    region: str,
    arguments: list[str],
    field: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    token = ""
    observed: set[str] = set()
    for _ in range(1000):
        call = list(arguments)
        if token:
            call.extend(["--next-token", token])
        page = aws_json(region, *call)
        values = page.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
            raise ValueError(f"AWS pagination returned malformed {field}")
        rows.extend(values)
        next_token = str(page.get("nextToken", ""))
        if not next_token:
            return rows
        if next_token in observed:
            raise ValueError("AWS pagination token loop detected")
        observed.add(next_token)
        token = next_token
    raise ValueError("AWS pagination exceeded the safety limit")


def require_no_existing_job(job_name: str, region: str) -> dict[str, Any]:
    queues = paginated_rows(
        region,
        ["batch", "describe-job-queues"],
        "jobQueues",
    )
    queue_arns = sorted({str(row.get("jobQueueArn", "")) for row in queues if str(row.get("jobQueueArn", ""))})
    if not queue_arns or QUEUE_ARN not in queue_arns:
        raise ValueError("Batch queue inventory omitted the explicit x86 queue")
    matches: list[dict[str, Any]] = []
    scanned = 0
    for queue_arn in queue_arns:
        for status in JOB_STATUSES:
            jobs = paginated_rows(
                region,
                [
                    "batch",
                    "list-jobs",
                    "--job-queue",
                    queue_arn,
                    "--job-status",
                    status,
                ],
                "jobSummaryList",
            )
            scanned += len(jobs)
            matches.extend(
                {
                    "jobId": row.get("jobId"),
                    "jobName": row.get("jobName"),
                    "status": row.get("status", status),
                    "jobQueue": queue_arn,
                }
                for row in jobs
                if row.get("jobName") == job_name
            )
    if matches:
        raise ValueError(f"an exact route job name already exists: {matches}")
    return {
        "job_name": job_name,
        "queue_count": len(queue_arns),
        "status_count_per_queue": len(JOB_STATUSES),
        "job_summaries_scanned": scanned,
        "exact_name_match_count": 0,
    }


def require_empty_history(uri: str, region: str) -> dict[str, Any]:
    match = re.fullmatch(rf"s3://{re.escape(PRIVATE_BUCKET)}/(.+/)", uri)
    if not match:
        raise ValueError("history target must be an exact private-results S3 prefix ending in slash")
    prefix = match.group(1)
    key_marker = ""
    version_marker = ""
    observed: set[tuple[str, str]] = set()
    for page_count in range(1, 1001):
        arguments = [
            "s3api",
            "list-object-versions",
            "--bucket",
            PRIVATE_BUCKET,
            "--prefix",
            prefix,
        ]
        if key_marker:
            arguments.extend(["--key-marker", key_marker])
        if version_marker:
            arguments.extend(["--version-id-marker", version_marker])
        page = aws_json(region, *arguments)
        if page.get("Versions") or page.get("DeleteMarkers"):
            raise ValueError(f"destination prefix has object or delete-marker history: {uri}")
        if page.get("IsTruncated") is not True:
            return {"uri": uri, "page_count": page_count, "history_count": 0}
        next_key = str(page.get("NextKeyMarker", ""))
        next_version = str(page.get("NextVersionIdMarker", ""))
        if not next_key or (next_key, next_version) in observed:
            raise ValueError("truncated S3 version history omitted or repeated its marker")
        observed.add((next_key, next_version))
        key_marker, version_marker = next_key, next_version
    raise ValueError("S3 history pagination exceeded the safety limit")


def validate_identity(region: str) -> dict[str, Any]:
    identity = aws_json(region, "sts", "get-caller-identity")
    arn = str(identity.get("Arn", ""))
    if identity.get("Account") != ACCOUNT_ID or not arn.startswith(f"arn:aws:iam::{ACCOUNT_ID}:"):
        raise ValueError("AWS caller is not an IAM principal in the destination account")
    return {"account": ACCOUNT_ID, "arn": arn}


def create_private(path: Path, content: bytes) -> None:
    require_safe_new_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reserve_private(path: Path) -> int:
    require_safe_new_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if (path.stat().st_mode & 0o777) != 0o600:
            raise ValueError(f"private output mode is not 0600: {path}")
        fsync_directory(path.parent)
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    return descriptor


def complete_reserved(descriptor: int, value: dict[str, Any]) -> None:
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


def require_new_outputs(paths: Iterable[Path]) -> None:
    values = list(paths)
    resolved = [path.resolve(strict=False) for path in values]
    if len(set(resolved)) != len(resolved):
        raise ValueError("private request/response output paths must be distinct")
    for path in values:
        require_safe_new_output_parent(path)
        if path.exists():
            raise FileExistsError(f"refusing to overwrite private output: {path}")


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_safe_new_output_parent(path: Path) -> None:
    if path.is_symlink():
        raise FileExistsError(f"private output may not be a symlink: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise FileExistsError(
                f"private output parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def build_submission_environment(
    *,
    contract_uri: str,
    contract_version_id: str,
    contract_sha256: str,
    output_uri: str,
    route_output_uri: str,
    publication_receipt_prefix: str,
    submission_id: str,
) -> list[dict[str, str]]:
    values = {
        "HRD_CROSSCHECK_INPUT_CONTRACT_URI": contract_uri,
        "HRD_CROSSCHECK_INPUT_CONTRACT_VERSION_ID": contract_version_id,
        "HRD_CROSSCHECK_INPUT_CONTRACT_SHA256": contract_sha256,
        "HRD_CROSSCHECK_OUTPUT_URI": output_uri,
        "HRD_CROSSCHECK_ROUTE_OUTPUT_URI": route_output_uri,
        "HRD_CROSSCHECK_PUBLICATION_RECEIPT_PREFIX": publication_receipt_prefix,
        "HRD_CROSSCHECK_SUBMISSION_ID": submission_id,
    }
    if tuple(values) != SUBMISSION_ENVIRONMENT_NAMES:
        raise AssertionError("submission environment order is not exact")
    return [{"name": name, "value": value} for name, value in values.items()]


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    if not re.match(rf"^s3://{re.escape(PRIVATE_BUCKET)}/.+", args.contract_uri):
        raise ValueError("contract-uri must be in the exact private-results bucket")
    if not valid_version_id(args.contract_version_id):
        raise ValueError("contract-version-id must be an exact S3 VersionId")
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[a-z0-9]{8,32}", args.submission_id):
        raise ValueError("submission-id must be a UTC timestamp plus unique lowercase token")
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("contract must be a JSON object")
    checked = validate(contract)
    if checked["routes"].get(args.route, {}).get("status") != "ready":
        raise ValueError("route is not ready: " + json.dumps(checked["routes"].get(args.route), sort_keys=True))
    if not private_output(contract["output_uri"]):
        raise ValueError("output destination is not an approved private work prefix")
    contract_sha256 = digest(args.contract)
    validate_contract_anchor(
        args.contract_publication_anchor,
        args.contract,
        args.contract_uri,
        args.contract_version_id,
    )
    output_root = str(contract["output_uri"]).rstrip("/")
    route_output_uri = f"{output_root}/crosschecks/{contract_sha256}/{args.route}/{args.submission_id}/"
    publication_receipt_prefix = f"{output_root}/crosscheck-publication-receipts/{contract_sha256}/{args.route}/{args.submission_id}/"
    alias = str(contract["run_alias"])
    job_name = (f"{alias}-{args.route.replace('_', '-')}-{args.submission_id[-8:]}-{contract_sha256[:8]}")[:128]
    route = ROUTES[args.route]
    submit_request = {
        "jobName": job_name,
        "jobQueue": QUEUE_NAME,
        "jobDefinition": route["job_definition_arn"],
        "containerOverrides": {
            "environment": build_submission_environment(
                contract_uri=args.contract_uri,
                contract_version_id=args.contract_version_id,
                contract_sha256=contract_sha256,
                output_uri=str(contract["output_uri"]),
                route_output_uri=route_output_uri,
                publication_receipt_prefix=publication_receipt_prefix,
                submission_id=args.submission_id,
            )
        },
        "retryStrategy": {"attempts": 1},
    }
    identity = validate_identity(args.region)
    live_definition = validate_live_definition(args.route, args.region)
    live_image = validate_live_image(args.route, args.region)
    live_queue = validate_live_queue(args.region)
    job_uniqueness = require_no_existing_job(job_name, args.region)
    output_history = require_empty_history(route_output_uri, args.region)
    receipt_history = require_empty_history(publication_receipt_prefix, args.region)
    return {
        "schema_version": 1,
        "status": "submission_authorized" if args.submit else "rendered_only",
        "generated_at_utc": now(),
        "scope": "private one-shot HRD cross-check route submission preflight",
        "route": args.route,
        "submission_id": args.submission_id,
        "contract": {
            "path": str(args.contract.resolve()),
            "uri": args.contract_uri,
            "version_id": args.contract_version_id,
            "sha256": contract_sha256,
            "publication_anchor_path": str(args.contract_publication_anchor.resolve()),
            "publication_anchor_sha256": digest(args.contract_publication_anchor),
        },
        "live_preflight": {
            "identity": identity,
            "job_definition": live_definition,
            "image": live_image,
            "queue": live_queue,
            "job_name_uniqueness": job_uniqueness,
            "route_output_history": output_history,
            "publication_receipt_history": receipt_history,
        },
        "submit_job_request": submit_request,
        "checks": {
            "exact_contract_version_bound": True,
            "exact_active_route_revision_3": True,
            "immutable_linux_amd64_image": True,
            "exact_static_environment": True,
            "exact_live_x86_queue_compute_environment": True,
            "one_attempt": True,
            "zero_existing_exact_job_name_across_all_queues_statuses": True,
            "empty_route_output_history": True,
            "empty_publication_receipt_history": True,
            "default_dry_run_behavior_preserved": True,
            "submission_guards_satisfied": not args.submit
            or (
                os.environ.get("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN") == "YES" and os.environ.get("HRD_CROSSCHECK_LICENSE_REVIEWED") == "YES"
            ),
        },
        "classification_authorization": "none",
        "authorized_hrd_state": "no_call",
    }


def submit(request: dict[str, Any], region: str) -> dict[str, Any]:
    response = aws_json(
        region,
        "batch",
        "submit-job",
        "--cli-input-json",
        json.dumps(request, sort_keys=True, separators=(",", ":")),
    )
    job_id = str(response.get("jobId", ""))
    job_arn = str(response.get("jobArn", ""))
    if (
        response.get("jobName") != request["jobName"]
        or not re.fullmatch(r"[0-9a-f-]{36}", job_id)
        or job_arn != f"arn:aws:batch:{region}:{ACCOUNT_ID}:job/{job_id}"
    ):
        raise ValueError("Batch submit response does not bind the exact request")
    return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, choices=sorted(ROUTES))
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--contract-uri", required=True)
    parser.add_argument("--contract-version-id", required=True)
    parser.add_argument("--contract-publication-anchor", required=True, type=Path)
    parser.add_argument(
        "--submission-id",
        required=True,
        help="one-shot identifier, e.g. 20260717T200000Z-a1b2c3d4",
    )
    parser.add_argument("--request-output", required=True, type=Path)
    parser.add_argument("--response-output", type=Path)
    parser.add_argument("--region", default=REGION, choices=[REGION])
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()

    outputs = [args.request_output]
    if args.submit:
        if os.environ.get("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN") != "YES":
            raise SystemExit("Fail-closed: --submit requires HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES")
        if os.environ.get("HRD_CROSSCHECK_LICENSE_REVIEWED") != "YES":
            raise SystemExit("Fail-closed: --submit requires HRD_CROSSCHECK_LICENSE_REVIEWED=YES")
        if args.response_output is None:
            raise SystemExit("Fail-closed: --submit requires --response-output")
        outputs.append(args.response_output)
    elif args.response_output is not None:
        raise SystemExit("Fail-closed: --response-output is valid only with --submit")

    try:
        require_new_outputs(outputs)
        request_receipt = preflight(args)
        create_private(args.request_output, canonical_bytes(request_receipt))
    except (
        FileExistsError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    if not args.submit:
        print(
            json.dumps(
                {
                    "status": "rendered_only",
                    "route": args.route,
                    "job_name": request_receipt["submit_job_request"]["jobName"],
                    "request_output": str(args.request_output),
                    "submitted": False,
                },
                sort_keys=True,
            )
        )
        return 0

    assert args.response_output is not None
    try:
        descriptor = reserve_private(args.response_output)
    except (FileExistsError, OSError, ValueError) as error:
        raise SystemExit(f"Fail-closed: response receipt could not be reserved; no job submitted: {error}") from error
    response: dict[str, Any] | None = None
    try:
        response = submit(request_receipt["submit_job_request"], args.region)
        response_receipt = {
            "schema_version": 1,
            "status": "submitted",
            "submitted_at_utc": now(),
            "route": args.route,
            "submission_id": args.submission_id,
            "request_receipt": {
                "path": str(args.request_output.resolve()),
                "sha256": digest(args.request_output),
            },
            "submit_job_request_sha256": sha256_bytes(canonical_bytes(request_receipt["submit_job_request"])),
            "job_id": response["jobId"],
            "job_arn": response["jobArn"],
            "response": response,
            "checks": {
                "request_receipt_mode_0600": (args.request_output.stat().st_mode & 0o777) == 0o600,
                "exact_job_name": response.get("jobName") == request_receipt["submit_job_request"]["jobName"],
                "job_id_and_arn_captured": True,
                "one_shot_no_retry": request_receipt["submit_job_request"].get("retryStrategy") == {"attempts": 1},
            },
            "classification_authorization": "none",
            "authorized_hrd_state": "no_call",
        }
    except Exception as error:
        response_receipt = {
            "schema_version": 1,
            "status": "submission_failed_or_ambiguous",
            "submitted_at_utc": now(),
            "route": args.route,
            "submission_id": args.submission_id,
            "job_name": request_receipt["submit_job_request"]["jobName"],
            "request_receipt": {
                "path": str(args.request_output.resolve()),
                "sha256": digest(args.request_output),
            },
            "error": f"{type(error).__name__}: {error}",
            "manual_reconciliation_required": True,
        }
        try:
            complete_reserved(descriptor, response_receipt)
        except Exception as receipt_error:
            raise SystemExit(
                "Fail-closed: submission failed or is ambiguous and the reserved "
                "response receipt could not be completed; do not retry; manually "
                f"reconcile exact job name {response_receipt['job_name']}: "
                f"{type(receipt_error).__name__}: {receipt_error}"
            ) from error
        raise SystemExit(
            f"Fail-closed: submission failed or is ambiguous; do not retry before reconciling {args.response_output}"
        ) from error
    try:
        complete_reserved(descriptor, response_receipt)
    except Exception as error:
        assert response is not None
        raise SystemExit(
            "Fail-closed: Batch submission succeeded but its reserved response "
            "receipt could not be completed; do not retry; manually reconcile "
            f"jobId={response['jobId']} jobArn={response['jobArn']}"
        ) from error
    print(
        json.dumps(
            {
                "status": "submitted",
                "route": args.route,
                "job_id": response["jobId"],
                "job_arn": response["jobArn"],
                "job_name": response["jobName"],
                "request_output": str(args.request_output),
                "response_output": str(args.response_output),
            },
            sort_keys=True,
        )
    )
    return 0


# FACETS_SNP_PILEUP_LICENSE_RESOLVED remains a launch blocker for the separate
# facets_scarhrd route; it is intentionally excluded from this exact :3 helper
# while the pinned snp-pileup source license is unresolved.


if __name__ == "__main__":
    sys.exit(main())
