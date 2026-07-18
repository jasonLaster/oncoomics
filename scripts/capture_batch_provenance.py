#!/usr/bin/env python3
"""Capture a minimal, private, reproducible AWS Batch execution record.

The output intentionally excludes environment values, secrets, network-interface
details, and source-object contents.  It is suitable as a required input to the
deterministic report after the job reaches SUCCEEDED.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def aws(region: str, *args: str) -> dict[str, Any]:
    output = subprocess.check_output(
        ["aws", *args, "--region", region, "--output", "json"],
        text=True,
        stderr=subprocess.STDOUT,
    )
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise ValueError(f"AWS command did not return an object: {' '.join(args)}")
    return payload


def s3_location(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"Expected an S3 object URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def ecs_cluster(task_arn: str) -> str:
    marker = ":task/"
    if marker not in task_arn:
        raise ValueError(f"Unexpected ECS task ARN: {task_arn}")
    suffix = task_arn.split(marker, 1)[1]
    values = suffix.split("/", 1)
    if len(values) != 2 or not all(values):
        raise ValueError(f"ECS task ARN does not include a cluster: {task_arn}")
    return values[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reserve_json(path: Path, value: dict[str, Any]) -> None:
    """Exclusively reserve an evidence path before remote inspection."""
    require_safe_json_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    fsync_directory(path.parent)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace a reservation with complete evidence."""
    require_safe_json_parent(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def require_safe_json_parent(path: Path) -> None:
    if path.is_symlink():
        raise FileExistsError(f"JSON output may not be a symlink: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise FileExistsError(
                f"JSON output parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def parse_failure_context() -> dict[str, Any]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--job-id")
    parser.add_argument("--run-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-status")
    parser.add_argument("--region", default="us-east-1")
    args, _ = parser.parse_known_args()
    return {
        "run_id": args.run_id,
        "job_id": args.job_id,
        "expected_status": args.expected_status,
        "region": args.region,
        "output": args.output,
    }


def reserved_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "reserved",
        "run_id": context["run_id"],
        "job_id": context["job_id"],
        "expected_status": context["expected_status"],
        "region": context["region"],
    }


def failure_error(error: BaseException) -> str:
    if isinstance(error, SystemExit):
        return str(error.code if error.code is not None else "SystemExit")
    return f"{type(error).__name__}: {error}"


def is_output_collision(error: BaseException) -> bool:
    return isinstance(error, SystemExit) and "provenance output already exists" in str(
        error.code
    )


def write_failure_if_reserved(
    context: dict[str, Any], error: BaseException
) -> None:
    output = context.get("output")
    if (
        not isinstance(output, Path)
        or output.is_symlink()
        or not output.is_file()
        or is_output_collision(error)
    ):
        return

    try:
        current = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if current != reserved_payload(context):
        return

    write_json_atomic(
        output,
        {
            **current,
            "status": "failed",
            "error": failure_error(error),
        },
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def command_set_sha256(commands: list[str]) -> str:
    encoded = json.dumps(
        commands,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return sha256_text(encoded)


CHECKSUM_FIELDS = (
    "ChecksumCRC64NVME",
    "ChecksumSHA256",
    "ChecksumSHA1",
    "ChecksumCRC32C",
    "ChecksumCRC32",
)


def checksums(head: dict[str, Any]) -> dict[str, str]:
    return {
        field: str(head[field])
        for field in CHECKSUM_FIELDS
        if str(head.get(field, "")).strip()
    }


def load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} is not a JSON object")
    return payload


def get_exact_object(
    region: str, bucket: str, key: str, version_id: str, destination: Path
) -> dict[str, Any]:
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
    payload = json.loads(subprocess.check_output(command, text=True))
    if not isinstance(payload, dict):
        raise ValueError("S3 get-object did not return an object")
    return payload


def parse_hash_command_output(value: Any) -> tuple[str, int]:
    match = re.fullmatch(
        r"([0-9a-f]{64})\s+/work/runner/worker\.py\n([1-9][0-9]*)\n?",
        str(value),
    )
    if not match:
        raise ValueError("executed-worker hash command output is malformed")
    return match.group(1), int(match.group(2))


def require_one(payload: dict[str, Any], key: str) -> dict[str, Any]:
    rows = payload.get(key)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError(f"Expected exactly one {key} record")
    return rows[0]


def summarize_attempts(value: Any) -> list[dict[str, Any]]:
    """Retain terminal attempt identity without network or environment details."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Batch attempts are not a list")
    result: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("Batch attempt is not an object")
        container = row.get("container")
        if not isinstance(container, dict):
            container = {}
        exit_code = container.get("exitCode")
        result.append(
            {
                "started_at_epoch_ms": int(row.get("startedAt", 0)),
                "stopped_at_epoch_ms": int(row.get("stoppedAt", 0)),
                "status_reason": str(row.get("statusReason", "")),
                "container_instance_arn": str(
                    container.get("containerInstanceArn", "")
                ),
                "task_arn": str(container.get("taskArn", "")),
                "log_stream": str(container.get("logStreamName", "")),
                "exit_code": int(exit_code) if exit_code is not None else None,
                "reason": str(container.get("reason", "")),
            }
        )
    return result


def effective_job_controls(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return submitted job controls, which may override definition defaults."""
    retry_strategy = job.get("retryStrategy")
    timeout = job.get("timeout")
    if not isinstance(retry_strategy, dict) or not isinstance(timeout, dict):
        raise ValueError("Batch job omits effective retry or timeout controls")
    if int(retry_strategy.get("attempts", 0)) <= 0:
        raise ValueError("Batch job effective retry attempts are invalid")
    if int(timeout.get("attemptDurationSeconds", 0)) <= 0:
        raise ValueError("Batch job effective attempt timeout is invalid")
    return retry_strategy, timeout


def validate_host_binding(
    task: dict[str, Any],
    container_instance: dict[str, Any],
    worker_source: dict[str, Any],
    cluster: str,
) -> dict[str, Any]:
    task_container_instance_arn = str(task.get("containerInstanceArn", ""))
    mapped_container_instance_arn = str(
        container_instance.get("containerInstanceArn", "")
    )
    mapped_ec2_instance_id = str(container_instance.get("ec2InstanceId", ""))
    checks = {
        "receipt_cluster_matches_task": worker_source.get("ecs_cluster") == cluster,
        "receipt_container_instance_matches_task": (
            worker_source.get("container_instance_arn")
            == task_container_instance_arn
        ),
        "ecs_container_instance_matches_task": (
            bool(task_container_instance_arn)
            and mapped_container_instance_arn == task_container_instance_arn
        ),
        "receipt_ec2_instance_matches_ecs_mapping": (
            bool(mapped_ec2_instance_id)
            and worker_source.get("ec2_instance_id") == mapped_ec2_instance_id
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"Batch task host binding failed: {checks}")
    return {
        "ecs_cluster": cluster,
        "container_instance_arn": task_container_instance_arn,
        "ec2_instance_id": mapped_ec2_instance_id,
        "container_instance_status": str(container_instance.get("status", "")),
        "ecs_agent_connected": bool(container_instance.get("agentConnected", False)),
        "checks": checks,
    }


def validate_ssm_command(
    command: dict[str, Any],
    invocation: dict[str, Any],
    *,
    command_id: str,
    instance_id: str,
    expected_commands: list[str],
    label: str,
) -> dict[str, Any]:
    parameters = command.get("Parameters")
    if not isinstance(parameters, dict):
        parameters = {}
    raw_commands = parameters.get("commands")
    command_bodies = (
        [str(value) for value in raw_commands]
        if isinstance(raw_commands, list)
        and all(isinstance(value, str) for value in raw_commands)
        else []
    )
    instance_ids = command.get("InstanceIds")
    normalized_instance_ids = (
        [str(value) for value in instance_ids]
        if isinstance(instance_ids, list)
        else []
    )
    try:
        response_code = int(invocation.get("ResponseCode", -1))
    except (TypeError, ValueError):
        response_code = -1
    checks = {
        "command_id": command.get("CommandId") == command_id,
        "document": command.get("DocumentName") == "AWS-RunShellScript",
        "command_status": command.get("Status") == "Success",
        "single_exact_instance": normalized_instance_ids == [instance_id],
        "exact_command_bodies": command_bodies == expected_commands,
        "invocation_command_id": invocation.get("CommandId") == command_id,
        "invocation_instance_id": invocation.get("InstanceId") == instance_id,
        "invocation_status": invocation.get("Status") == "Success",
        "invocation_response_code": response_code == 0,
    }
    if not all(checks.values()):
        raise ValueError(f"{label} SSM command binding failed: {checks}")
    stdout = str(invocation.get("StandardOutputContent", ""))
    stderr = str(invocation.get("StandardErrorContent", ""))
    return {
        "command_id": command_id,
        "document_name": "AWS-RunShellScript",
        "status": "Success",
        "instance_ids": normalized_instance_ids,
        "requested_at": str(command.get("RequestedDateTime", "")),
        "command_bodies": command_bodies,
        "command_body_sha256": [sha256_text(value) for value in command_bodies],
        "command_set_sha256": command_set_sha256(command_bodies),
        "invocation": {
            "status": "Success",
            "response_code": 0,
            "execution_start": str(invocation.get("ExecutionStartDateTime", "")),
            "execution_end": str(invocation.get("ExecutionEndDateTime", "")),
            "stdout_sha256": sha256_text(stdout),
            "stderr_sha256": sha256_text(stderr),
        },
        "checks": checks,
    }


def expected_hash_commands(runtime_id: str) -> list[str]:
    return [
        f"docker exec {runtime_id} sha256sum /work/runner/worker.py",
        f"docker exec {runtime_id} stat -c %s /work/runner/worker.py",
    ]


def expected_freeze_commands(
    runtime_id: str,
    bucket: str,
    key: str,
    kms_key_id: str,
    worker_sha256: str,
    region: str,
) -> list[str]:
    return [
        " ".join(
            [
                "docker",
                "exec",
                runtime_id,
                "/opt/diana-aws/bin/aws",
                "s3api",
                "put-object",
                "--bucket",
                bucket,
                "--key",
                key,
                "--body",
                "/work/runner/worker.py",
                "--server-side-encryption",
                "aws:kms",
                "--ssekms-key-id",
                kms_key_id,
                "--checksum-algorithm",
                "SHA256",
                "--checksum-sha256",
                checksum_sha256(worker_sha256),
                "--metadata",
                f"sha256={worker_sha256},source=active-ecs-task,classification=private",
                "--region",
                region,
                "--output",
                "json",
            ]
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--worker-uri", required=True)
    parser.add_argument("--executed-worker-freeze-receipt", required=True, type=Path)
    parser.add_argument(
        "--executed-worker-freeze-receipt-upload", required=True, type=Path
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-status")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    resolved = {
        args.output.resolve(),
        args.executed_worker_freeze_receipt.resolve(),
        args.executed_worker_freeze_receipt_upload.resolve(),
    }
    if len(resolved) != 3:
        raise SystemExit("Fail-closed: provenance input/output paths must be distinct")
    for path, label in (
        (
            args.executed_worker_freeze_receipt,
            "executed-worker freeze receipt",
        ),
        (
            args.executed_worker_freeze_receipt_upload,
            "executed-worker freeze receipt upload",
        ),
    ):
        try:
            load_object(path, label)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise SystemExit(f"Fail-closed: invalid {label}: {error}") from error
    try:
        reserve_json(
            args.output,
            {
                "schema_version": 1,
                "status": "reserved",
                "run_id": args.run_id,
                "job_id": args.job_id,
                "expected_status": args.expected_status,
                "region": args.region,
            },
        )
    except FileExistsError as error:
        raise SystemExit(
            "Fail-closed: provenance output already exists; preserve it and use a new path"
        ) from error

    job = require_one(
        aws(args.region, "batch", "describe-jobs", "--jobs", args.job_id),
        "jobs",
    )
    container = job.get("container") if isinstance(job.get("container"), dict) else {}
    if args.expected_status and job.get("status") != args.expected_status:
        raise SystemExit(
            f"Fail-closed: Batch job status is {job.get('status')}, expected {args.expected_status}"
        )
    command = container.get("command") if isinstance(container.get("command"), list) else []
    if args.run_id not in " ".join(str(value) for value in command):
        raise SystemExit("Fail-closed: Batch command does not contain the expected run ID")
    s3_location(args.worker_uri)
    if args.worker_uri not in " ".join(str(value) for value in command):
        raise SystemExit("Fail-closed: Batch command does not contain the launch worker URI")
    task_arn = str(container.get("taskArn", ""))
    if not task_arn:
        raise SystemExit("Fail-closed: Batch job has no ECS task ARN yet")
    cluster = ecs_cluster(task_arn)
    task = require_one(
        aws(args.region, "ecs", "describe-tasks", "--cluster", cluster, "--tasks", task_arn),
        "tasks",
    )
    task_containers = task.get("containers") if isinstance(task.get("containers"), list) else []
    runtime_ids = {
        str(row.get("runtimeId", ""))
        for row in task_containers
        if isinstance(row, dict) and row.get("runtimeId")
    }
    digests = sorted(
        {
            str(row.get("imageDigest"))
            for row in task_containers
            if isinstance(row, dict) and str(row.get("imageDigest", "")).startswith("sha256:")
        }
    )
    if len(digests) != 1:
        raise SystemExit("Fail-closed: expected one immutable ECS image digest")

    queue = require_one(
        aws(args.region, "batch", "describe-job-queues", "--job-queues", str(job.get("jobQueue", ""))),
        "jobQueues",
    )
    definition = require_one(
        aws(
            args.region,
            "batch",
            "describe-job-definitions",
            "--job-definitions",
            str(job.get("jobDefinition", "")),
        ),
        "jobDefinitions",
    )

    worker_receipt = load_object(
        args.executed_worker_freeze_receipt, "executed-worker freeze receipt"
    )
    worker_source = (
        worker_receipt.get("source")
        if isinstance(worker_receipt.get("source"), dict)
        else {}
    )
    worker_freeze = (
        worker_receipt.get("freeze")
        if isinstance(worker_receipt.get("freeze"), dict)
        else {}
    )
    worker_receipt_checks = worker_receipt.get("checks")
    worker_receipt_upload = load_object(
        args.executed_worker_freeze_receipt_upload,
        "executed-worker freeze receipt upload",
    )
    worker_receipt_upload_object = (
        worker_receipt_upload.get("object")
        if isinstance(worker_receipt_upload.get("object"), dict)
        else {}
    )
    worker_receipt_upload_checks = worker_receipt_upload.get("checks")
    worker_bucket = str(worker_freeze.get("bucket", ""))
    worker_key = str(worker_freeze.get("key", ""))
    worker_version = str(worker_freeze.get("version_id", ""))
    task_container_instance_arn = str(task.get("containerInstanceArn", ""))
    if not task_container_instance_arn:
        raise SystemExit("Fail-closed: ECS task has no container-instance ARN")
    container_instance = require_one(
        aws(
            args.region,
            "ecs",
            "describe-container-instances",
            "--cluster",
            cluster,
            "--container-instances",
            task_container_instance_arn,
        ),
        "containerInstances",
    )
    try:
        host_binding = validate_host_binding(
            task, container_instance, worker_source, cluster
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    worker_head = aws(
        args.region,
        "s3api",
        "head-object",
        "--bucket",
        worker_bucket,
        "--key",
        worker_key,
        "--version-id",
        worker_version,
        "--checksum-mode",
        "ENABLED",
    )
    receipt_upload_head = aws(
        args.region,
        "s3api",
        "head-object",
        "--bucket",
        str(worker_receipt_upload_object.get("bucket", "")),
        "--key",
        str(worker_receipt_upload_object.get("key", "")),
        "--version-id",
        str(worker_receipt_upload_object.get("version_id", "")),
        "--checksum-mode",
        "ENABLED",
    )
    with tempfile.TemporaryDirectory(prefix="diana-worker-provenance-") as temporary:
        worker = Path(temporary) / "worker.py"
        worker_get = get_exact_object(
            args.region, worker_bucket, worker_key, worker_version, worker
        )
        worker_sha256 = sha256(worker)
        worker_bytes = worker.stat().st_size
    hash_command_id = str(worker_source.get("ssm_hash_command_id", ""))
    freeze_command_id = str(worker_freeze.get("ssm_command_id", ""))
    ec2_instance_id = str(host_binding["ec2_instance_id"])
    hash_command = require_one(
        aws(
            args.region,
            "ssm",
            "list-commands",
            "--command-id",
            hash_command_id,
        ),
        "Commands",
    )
    freeze_command = require_one(
        aws(
            args.region,
            "ssm",
            "list-commands",
            "--command-id",
            freeze_command_id,
        ),
        "Commands",
    )
    hash_invocation = aws(
        args.region,
        "ssm",
        "get-command-invocation",
        "--command-id",
        hash_command_id,
        "--instance-id",
        ec2_instance_id,
    )
    freeze_invocation = aws(
        args.region,
        "ssm",
        "get-command-invocation",
        "--command-id",
        freeze_command_id,
        "--instance-id",
        ec2_instance_id,
    )
    runtime_id = str(worker_source.get("container_runtime_id", ""))
    try:
        hash_command_evidence = validate_ssm_command(
            hash_command,
            hash_invocation,
            command_id=hash_command_id,
            instance_id=ec2_instance_id,
            expected_commands=expected_hash_commands(runtime_id),
            label="executed-worker hash",
        )
        freeze_command_evidence = validate_ssm_command(
            freeze_command,
            freeze_invocation,
            command_id=freeze_command_id,
            instance_id=ec2_instance_id,
            expected_commands=expected_freeze_commands(
                runtime_id,
                worker_bucket,
                worker_key,
                str(worker_freeze.get("kms_key_id", "")),
                str(worker_freeze.get("checksum_sha256_hex", "")),
                args.region,
            ),
            label="executed-worker freeze",
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    command_sha256, command_bytes = parse_hash_command_output(
        hash_invocation.get("StandardOutputContent")
    )
    freeze_output = json.loads(str(freeze_invocation.get("StandardOutputContent", "")))
    if not isinstance(freeze_output, dict):
        raise SystemExit("Fail-closed: worker freeze command output is malformed")
    expected_checksum_hex = str(worker_freeze.get("checksum_sha256_hex", ""))
    try:
        head_checksum_hex = base64.b64decode(
            str(worker_head.get("ChecksumSHA256", "")), validate=True
        ).hex()
        get_checksum_hex = base64.b64decode(
            str(worker_get.get("ChecksumSHA256", "")), validate=True
        ).hex()
    except Exception as error:
        raise SystemExit(
            f"Fail-closed: executed worker checksum is malformed: {error}"
        ) from error
    worker_checks = {
        "receipt_status": (
            worker_receipt.get("schema_version") == 1
            and worker_receipt.get("status") == "passed"
            and worker_receipt.get("run_id") == args.run_id
            and worker_receipt.get("batch_job_id") == args.job_id
        ),
        "receipt_checks": (
            isinstance(worker_receipt_checks, dict)
            and bool(worker_receipt_checks)
            and all(value is True for value in worker_receipt_checks.values())
        ),
        "receipt_upload": (
            worker_receipt_upload.get("schema_version") == 1
            and worker_receipt_upload.get("status") == "passed"
            and isinstance(worker_receipt_upload_checks, dict)
            and bool(worker_receipt_upload_checks)
            and all(value is True for value in worker_receipt_upload_checks.values())
            and worker_receipt_upload.get("local_receipt_sha256")
            == sha256(args.executed_worker_freeze_receipt)
            and receipt_upload_head.get("VersionId")
            == worker_receipt_upload_object.get("version_id")
            and int(receipt_upload_head.get("ContentLength", -1))
            == args.executed_worker_freeze_receipt.stat().st_size
            == int(worker_receipt_upload_object.get("bytes", -2))
            and receipt_upload_head.get("ChecksumType") == "FULL_OBJECT"
            and base64.b64decode(
                str(receipt_upload_head.get("ChecksumSHA256", "")), validate=True
            ).hex()
            == sha256(args.executed_worker_freeze_receipt)
            and receipt_upload_head.get("ServerSideEncryption") == "aws:kms"
            and receipt_upload_head.get("SSEKMSKeyId")
            == worker_receipt_upload_object.get("kms_key_id")
            == worker_freeze.get("kms_key_id")
        ),
        "task_identity": (
            worker_source.get("task_arn") == task_arn
            and worker_source.get("container_runtime_id") in runtime_ids
        ),
        "task_host_mapping": all(host_binding["checks"].values()),
        "hash_command_definition": all(
            hash_command_evidence["checks"].values()
        ),
        "freeze_command_definition": all(
            freeze_command_evidence["checks"].values()
        ),
        "live_hash_command": (
            hash_invocation.get("Status") == "Success"
            and int(hash_invocation.get("ResponseCode", -1)) == 0
            and command_sha256 == worker_source.get("sha256")
            and command_bytes == int(worker_source.get("bytes", -1))
        ),
        "live_freeze_command": (
            freeze_invocation.get("Status") == "Success"
            and int(freeze_invocation.get("ResponseCode", -1)) == 0
            and freeze_output.get("VersionId") == worker_version
            and freeze_output.get("ChecksumSHA256")
            == worker_freeze.get("checksum_sha256_base64")
        ),
        "exact_version": (
            worker_head.get("VersionId") == worker_get.get("VersionId") == worker_version
        ),
        "bytes": (
            int(worker_head.get("ContentLength", -1))
            == int(worker_get.get("ContentLength", -2))
            == worker_bytes
            == command_bytes
            == int(worker_freeze.get("bytes", -3))
        ),
        "sha256": (
            worker_sha256
            == command_sha256
            == expected_checksum_hex
            == head_checksum_hex
            == get_checksum_hex
            == str((worker_head.get("Metadata") or {}).get("sha256", ""))
        ),
        "full_object_checksum": (
            worker_head.get("ChecksumType")
            == worker_get.get("ChecksumType")
            == worker_freeze.get("checksum_type")
            == "FULL_OBJECT"
        ),
        "kms": (
            worker_head.get("ServerSideEncryption")
            == worker_get.get("ServerSideEncryption")
            == "aws:kms"
            and worker_head.get("SSEKMSKeyId")
            == worker_get.get("SSEKMSKeyId")
            == worker_freeze.get("kms_key_id")
        ),
    }
    if not all(worker_checks.values()):
        raise SystemExit(f"Fail-closed: executed worker verification failed: {worker_checks}")

    resource_requirements = container.get("resourceRequirements")
    if not isinstance(resource_requirements, list):
        resource_requirements = []
    attempts = summarize_attempts(job.get("attempts"))
    retry_strategy, timeout = effective_job_controls(job)
    result = {
        "schema_version": 1,
        "run_id": args.run_id,
        "region": args.region,
        "batch": {
            "job_id": str(job.get("jobId", "")),
            "job_name": str(job.get("jobName", "")),
            "status": str(job.get("status", "")),
            "status_reason": str(job.get("statusReason", "")),
            "created_at_epoch_ms": int(job.get("createdAt", 0)),
            "started_at_epoch_ms": int(job.get("startedAt", 0)),
            "stopped_at_epoch_ms": int(job.get("stoppedAt", 0)),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "retry_strategy": retry_strategy,
            "timeout": timeout,
            "job_queue_arn": str(job.get("jobQueue", "")),
            "job_definition_arn": str(job.get("jobDefinition", "")),
            "job_role_arn": str(container.get("jobRoleArn", "")),
            "resource_requirements": resource_requirements,
            "command": [str(value) for value in command],
            "log_group": "/aws/batch/job",
            "log_stream": str(container.get("logStreamName", "")),
        },
        "container": {
            "image_reference": str(container.get("image", "")),
            "image_digest": digests[0],
            "ecs_cluster": cluster,
            "task_arn": task_arn,
            "container_instance_arn": host_binding["container_instance_arn"],
            "ec2_instance_id": host_binding["ec2_instance_id"],
            "runtime_ids": sorted(runtime_ids),
            "platform_family": str(task.get("platformFamily", "")),
            "platform_version": str(task.get("platformVersion", "")),
            "cpu_architecture": str(
                (task.get("runtimePlatform") or {}).get("cpuArchitecture", "")
                if isinstance(task.get("runtimePlatform"), dict)
                else ""
            ),
        },
        "queue": {
            "name": str(queue.get("jobQueueName", "")),
            "state": str(queue.get("state", "")),
            "status": str(queue.get("status", "")),
            "scheduling_policy_arn": str(queue.get("schedulingPolicyArn", "")),
        },
        "job_definition": {
            "name": str(definition.get("jobDefinitionName", "")),
            "revision": int(definition.get("revision", 0)),
            "platform_capabilities": definition.get("platformCapabilities", []),
            "propagate_tags": bool(definition.get("propagateTags", False)),
            "retry_strategy": definition.get("retryStrategy", {}),
            "timeout": definition.get("timeout", {}),
        },
        "worker": {
            "launch_uri": args.worker_uri,
            "executed_uri": f"s3://{worker_bucket}/{worker_key}",
            "executed_version_id": worker_version,
            "freeze_receipt_path": str(args.executed_worker_freeze_receipt.resolve()),
            "freeze_receipt_sha256": sha256(args.executed_worker_freeze_receipt),
            "freeze_receipt_version_id": str(
                worker_receipt_upload_object.get("version_id", "")
            ),
            "freeze_receipt_upload_path": str(
                args.executed_worker_freeze_receipt_upload.resolve()
            ),
            "freeze_receipt_upload_sha256": sha256(
                args.executed_worker_freeze_receipt_upload
            ),
            "bytes": worker_bytes,
            "sha256": worker_sha256,
            "etag": str(worker_head.get("ETag", "")),
            "last_modified": str(worker_head.get("LastModified", "")),
            "checksums": checksums(worker_head),
            "checksum_type": str(worker_head.get("ChecksumType", "")),
            "server_side_encryption": str(worker_head.get("ServerSideEncryption", "")),
            "kms_key_id": str(worker_head.get("SSEKMSKeyId", "")),
            "ssm_evidence": {
                "host_binding": host_binding,
                "hash_command": hash_command_evidence,
                "freeze_command": freeze_command_evidence,
            },
            "checks": worker_checks,
        },
    }
    if not result["batch"]["job_id"] or not result["batch"]["log_stream"]:
        raise SystemExit("Fail-closed: incomplete Batch execution identity")
    if (
        result["worker"]["bytes"] <= 0
        or len(result["worker"]["sha256"]) != 64
        or not all(result["worker"]["checks"].values())
    ):
        raise SystemExit("Fail-closed: incomplete worker provenance")
    write_json_atomic(args.output, result)
    print(f"Wrote Batch provenance: {args.output}")


if __name__ == "__main__":
    failure_context = parse_failure_context()
    try:
        main()
    except SystemExit as error:
        write_failure_if_reserved(failure_context, error)
        raise
    except Exception as error:
        write_failure_if_reserved(failure_context, error)
        raise
