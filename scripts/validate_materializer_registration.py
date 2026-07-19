#!/usr/bin/env python3
"""Validate a reviewed materializer Batch registration into a local receipt.

The future materializer revision is only safe to submit after four immutable
facts agree:

* the exact frozen materializer script anchor;
* the local job-definition payload rendered for that script;
* the AWS ``register-job-definition`` response; and
* a post-registration ``describe-job-definitions`` payload for the returned ARN.

This validator performs that local cross-binding and writes a create-only
schema-3 receipt without registering, submitting, or mutating AWS itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACCOUNT_ID = "172630973301"
REGION = "us-east-1"
JOB_DEFINITION_NAME = "diana-wgs-hrd-materialize-crosscheck-inputs"
JOB_DEFINITION_ARN = (
    f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:job-definition/"
    f"{JOB_DEFINITION_NAME}:"
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
EXPECTED_SCRIPT_ANCHOR_CHECKS = frozenset(
    (
        "bucket_versioning_enabled",
        "create_only_put",
        "exact_version_head",
        "exact_version_get",
        "downloaded_sha256_exact",
        "checksum_sha256_exact",
        "metadata_sha256_exact",
        "exact_kms",
        "single_latest_version",
        "no_delete_markers",
    )
)
EXPECTED_COMMAND_CHECKS = frozenset(
    (
        "shape",
        "strict",
        "script_bucket",
        "script_key",
        "script_version",
        "script_sha",
        "checksum_mode",
        "receipt_prefix",
        "source_sha_parameters",
    )
)
EXPECTED_REGISTRATION_CHECKS = frozenset(
    (
        "exact_active_revision",
        "live_definition_matches_local",
        "one_attempt",
        "timeout_21600",
        "exact_script_version_and_sha",
        "eight_runtime_substitutions",
        "no_job_submitted",
    )
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exact_schema_version(payload: dict[str, Any], expected: int) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def load_json(path: Path, label: str) -> dict[str, Any]:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def require_safe_output(path: Path) -> None:
    if path.is_symlink():
        raise FileExistsError(f"output may not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"refusing to overwrite output: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise FileExistsError(f"output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_create_only(path: Path, value: dict[str, Any]) -> None:
    require_safe_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, sort_keys=True) + "\n"
    expected_sha256 = hashlib.sha256(data.encode("utf-8")).hexdigest()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        fsync_directory(path.parent)
        require_installed_output(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def require_installed_output(path: Path, expected_sha256: str) -> None:
    require_no_symlinked_ancestors(path, "output")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"output changed during write: {path}")
    if sha256_path(path) != expected_sha256:
        raise ValueError(f"output changed during write: {path}")


def passed_checks(value: Any, expected: frozenset[str]) -> bool:
    if not isinstance(value, dict):
        return False
    return not check_map_mismatches(value, expected)


def check_map_mismatches(value: dict[str, Any], expected: frozenset[str]) -> list[str]:
    missing = sorted(expected - set(value))
    unexpected = sorted(set(value) - expected)
    failed = sorted(key for key in expected & set(value) if value[key] is not True)
    errors: list[str] = []
    if missing:
        errors.append("missing " + ",".join(missing))
    if unexpected:
        errors.append("unexpected " + ",".join(unexpected))
    if failed:
        errors.append("failed " + ",".join(failed))
    return errors


def require_passed_checks(value: Any, expected: frozenset[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} check map must be a JSON object")
    errors = check_map_mismatches(value, expected)
    if errors:
        raise ValueError(f"{label} check map is not exact: {'; '.join(errors)}")


def require_hex(value: Any, label: str) -> str:
    text = str(value)
    if not HEX64.fullmatch(text):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return text


def normalize_definition(value: dict[str, Any]) -> dict[str, Any]:
    container = value.get("containerProperties")
    if not isinstance(container, dict):
        raise ValueError("job definition is missing containerProperties")
    log = container.get("logConfiguration")
    if not isinstance(log, dict):
        raise ValueError("job definition is missing logConfiguration")
    return {
        "jobDefinitionName": value.get("jobDefinitionName"),
        "type": value.get("type"),
        "platformCapabilities": value.get("platformCapabilities"),
        "containerProperties": {
            "image": container.get("image"),
            "jobRoleArn": container.get("jobRoleArn"),
            "vcpus": container.get("vcpus"),
            "memory": container.get("memory"),
            "command": container.get("command"),
            "environment": container.get("environment"),
            "logConfiguration": {
                "logDriver": log.get("logDriver"),
                "options": log.get("options"),
            },
        },
        "retryStrategy": {"attempts": (value.get("retryStrategy") or {}).get("attempts")},
        "timeout": value.get("timeout"),
    }


def live_definition(payload: dict[str, Any]) -> dict[str, Any]:
    definitions = payload.get("jobDefinitions")
    if definitions is None:
        return payload
    if not isinstance(definitions, list) or len(definitions) != 1 or not isinstance(definitions[0], dict):
        raise ValueError("describe-job-definitions must contain exactly one jobDefinitions row")
    return definitions[0]


def validate(
    *,
    script_anchor: dict[str, Any],
    definition: dict[str, Any],
    registration: dict[str, Any],
    live: dict[str, Any],
    script_anchor_sha256: str,
    definition_sha256: str,
) -> dict[str, Any]:
    source = script_anchor.get("source") if isinstance(script_anchor.get("source"), dict) else {}
    script_object = script_anchor.get("object") if isinstance(script_anchor.get("object"), dict) else {}
    source_sha = require_hex(source.get("sha256"), "materializer source SHA-256")
    if not exact_schema_version(script_anchor, 1) or script_anchor.get("status") != "passed":
        raise ValueError("materializer script anchor must be schema 1 and passed")
    require_passed_checks(
        script_anchor.get("checks"),
        EXPECTED_SCRIPT_ANCHOR_CHECKS,
        "materializer script anchor",
    )

    live_row = live_definition(live)
    revision = registration.get("revision")
    arn = registration.get("jobDefinitionArn")
    if (
        registration.get("jobDefinitionName") != JOB_DEFINITION_NAME
        or not isinstance(revision, int)
        or revision < 1
        or arn != f"{JOB_DEFINITION_ARN}{revision}"
        or live_row.get("jobDefinitionArn") != arn
        or live_row.get("revision") != revision
        or live_row.get("status") != "ACTIVE"
    ):
        raise ValueError("registration response does not bind one active materializer revision")
    normalized_definition = normalize_definition(definition)
    if normalize_definition(live_row) != normalized_definition:
        raise ValueError("live materializer definition differs from local payload")

    command = definition.get("containerProperties", {}).get("command")
    shell = command[2] if isinstance(command, list) and len(command) == 12 else ""
    expected_binding = {f"${index}": name for index, name in enumerate(PARAMETER_NAMES, start=1)}
    command_checks = {
        "shape": isinstance(command, list)
        and command[:2] == ["bash", "-lc"]
        and command[3] == "materializer"
        and command[4:] == [f"Ref::{name}" for name in PARAMETER_NAMES],
        "strict": shell.startswith("set -euo pipefail;"),
        "script_bucket": f"--bucket {script_object.get('bucket', '')}" in shell,
        "script_key": f"--key {script_object.get('key', '')}" in shell,
        "script_version": f"--version-id {script_object.get('version_id', '')}" in shell,
        "script_sha": f'test "$actual" = {source_sha}' in shell,
        "checksum_mode": "--checksum-mode ENABLED" in shell,
        "receipt_prefix": "--receipt-prefix " in shell and "--receipt-uri" not in shell,
        "source_sha_parameters": all(
            f"--{name.replace('_', '-')} \"${index}\"" in shell
            for index, name in enumerate(PARAMETER_NAMES, start=1)
            if name.endswith("_sha256")
        ),
    }
    checks = {
        "exact_active_revision": True,
        "live_definition_matches_local": True,
        "one_attempt": definition.get("retryStrategy") == {"attempts": 1},
        "timeout_21600": definition.get("timeout") == {"attemptDurationSeconds": 21600},
        "exact_script_version_and_sha": all(
            command_checks[name]
            for name in (
                "script_bucket",
                "script_key",
                "script_version",
                "script_sha",
                "checksum_mode",
            )
        ),
        "eight_runtime_substitutions": command_checks["shape"],
        "no_job_submitted": True,
    }
    try:
        require_passed_checks(
            command_checks,
            EXPECTED_COMMAND_CHECKS,
            "materializer command",
        )
        require_passed_checks(
            checks,
            EXPECTED_REGISTRATION_CHECKS,
            "materializer registration",
        )
    except ValueError as error:
        raise ValueError(f"materializer registration is not exact: {error}") from error

    runtime = definition.get("containerProperties") if isinstance(definition.get("containerProperties"), dict) else {}
    if (
        normalized_definition != definition
        or definition.get("jobDefinitionName") != JOB_DEFINITION_NAME
        or runtime.get("vcpus") != 8
        or runtime.get("memory") != 32000
    ):
        raise ValueError(f"materializer registration is not exact: checks={checks}; command={command_checks}")

    image = str(runtime["image"])
    return {
        "schema_version": 3,
        "verified_at_utc": now(),
        "status": "registered_not_submitted",
        "classification_authorization": "none",
        "authorized_hrd_state": "no_call",
        "script_freeze": {
            "anchor_sha256": script_anchor_sha256,
            "object": script_object,
            "source": source,
            "checks": script_anchor["checks"],
        },
        "batch": {
            "definition_sha256": definition_sha256,
            "registration": {
                "jobDefinitionName": JOB_DEFINITION_NAME,
                "jobDefinitionArn": arn,
                "revision": revision,
            },
            "job_definition_arn": arn,
            "revision": revision,
            "live_definition_matches_local": True,
            "retry_attempts": 1,
            "timeout_seconds": 21600,
            "vcpus": 8,
            "memory_mib": 32000,
            "image": image,
            "parameter_substitution": list(PARAMETER_NAMES),
            "shell_argument_binding": expected_binding,
            "submitted": False,
        },
        "checks": {name: True for name in EXPECTED_REGISTRATION_CHECKS},
        "submission_gate": (
            "Submit only after final deterministic freeze and exact local "
            "materialization receipts supply all eight runtime values."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materializer-script-anchor", required=True, type=Path)
    parser.add_argument("--job-definition-payload", required=True, type=Path)
    parser.add_argument("--registration-response", required=True, type=Path)
    parser.add_argument("--live-job-definition", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    script_anchor = load_json(args.materializer_script_anchor, "materializer script anchor")
    definition = load_json(args.job_definition_payload, "materializer job definition")
    registration = load_json(args.registration_response, "materializer registration response")
    live = load_json(args.live_job_definition, "materializer live job definition")
    receipt = validate(
        script_anchor=script_anchor,
        definition=definition,
        registration=registration,
        live=live,
        script_anchor_sha256=sha256_path(args.materializer_script_anchor),
        definition_sha256=sha256_path(args.job_definition_payload),
    )
    write_json_create_only(args.output, receipt)
    print(json.dumps({"status": "passed", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
