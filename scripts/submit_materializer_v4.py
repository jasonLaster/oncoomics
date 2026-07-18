#!/usr/bin/env python3
"""Render and, only with two explicit guards, submit materializer revision 4.

This private helper turns already-frozen custody evidence into the eight exact
Batch parameters consumed by the immutable materializer.  Every AWS operation
before ``--submit`` is read-only.  The request receipt is written create-only
before submission; a distinct response receipt is reserved create-only before
the AWS mutation and completed with either the exact response or an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REGION = "us-east-1"
ACCOUNT_ID = "172630973301"
QUEUE_NAME = "diana-omics-prod-use1-ondemand"
QUEUE_ARN = f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:job-queue/{QUEUE_NAME}"
COMPUTE_ENVIRONMENT_ARN = f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:compute-environment/{QUEUE_NAME}"
JOB_DEFINITION_NAME = "diana-wgs-hrd-materialize-crosscheck-inputs"
JOB_DEFINITION_ARN = f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:job-definition/{JOB_DEFINITION_NAME}:4"
EXPECTED_JOB_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/diana-omics-prod-use1-batch-job"
EXPECTED_IMAGE = (
    f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/diana-omics@sha256:ac58e717f64ccd585a040d5ad5baa6527014d76993301606c49888ed0cb06076"
)
EXPECTED_IMAGE_DIGEST = EXPECTED_IMAGE.rsplit("@", 1)[1]
EXPECTED_IMAGE_REPOSITORY = "diana-omics"
EXPECTED_MATERIALIZER_SHA256 = "513c55b347a4c57e5f7231642e851d03aa4dcdac9159781e4d1a79815dc1f35f"
EXPECTED_INSTANCE_TYPES = ("c7g", "c7gn", "m7g", "r7g")
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
SOURCE_RELATIVES = {
    "source_vcf": "variants/diana.wgs.mutect2.filtered.vcf.gz",
    "source_vcf_index": "variants/diana.wgs.mutect2.filtered.vcf.gz.tbi",
    "source_matrix": "signatures/wgs_sbs96_matrix.csv",
}
REFERENCE_ARTIFACTS = {
    "reference_fasta": "reference.fa",
    "reference_fai": "reference.fa.fai",
}
JOB_STATUSES = (
    "SUBMITTED",
    "PENDING",
    "RUNNABLE",
    "STARTING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
VERSION_ID = re.compile(r"^\S+$")
RUN_ID = re.compile(r"^diana-wgs-hrd-([0-9]{8}T[0-9]{6}Z)$")
S3_URI = re.compile(r"^s3://([^/]+)/(.+)$")
EXPECTED_ANCHOR_CHECKS = {
    "version_exact",
    "bytes_exact",
    "sha256_exact",
    "sha256_checksum_exact",
    "exact_kms",
    "single_create_only_version",
}
EXPECTED_FINAL_FREEZE_CHECKS = {
    "execution_receipt_bound",
    "complete_source_inventory_unchanged",
    "destination_exact_history_and_receipt_match",
}
EXPECTED_FINAL_ROW_CHECKS = {
    "listed_inventory_stable",
    "source_stable",
    "size_matches",
    "common_checksum_matches",
    "exact_kms_matches",
    "destination_versioned",
    "copy_response_version_matches",
}
EXPECTED_MATERIALIZATION_ROW_CHECKS = {
    "version_id",
    "content_length",
    "local_bytes",
    "checksums",
    "checksum_type",
    "sse",
    "kms",
}
EXPECTED_REFERENCE_ROW_CHECKS = {
    "content_length_matches",
    "crc64nvme_matches",
    "crc64nvme_present",
    "destination_bucket_matches",
    "destination_kms_key_matches",
    "destination_sse_kms",
    "destination_versioned",
}
EXPECTED_SCRIPT_ANCHOR_CHECKS = {
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
}
EXPECTED_REGISTRATION_CHECKS = {
    "exact_active_revision_4",
    "live_definition_matches_local",
    "one_attempt",
    "timeout_21600",
    "exact_script_version_and_sha",
    "eight_runtime_substitutions",
    "no_job_submitted",
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def passed_checks(value: Any, *, exact: set[str] | None = None) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    if exact is not None and set(value) != exact:
        return False
    return all(item is True for item in value.values())


def valid_version(value: Any) -> bool:
    text = str(value)
    return bool(VERSION_ID.fullmatch(text) and text.lower() not in {"none", "null"})


def valid_sha(value: Any) -> bool:
    return bool(HEX64.fullmatch(str(value)))


def parse_s3(uri: Any) -> tuple[str, str]:
    match = S3_URI.fullmatch(str(uri))
    if not match:
        raise ValueError(f"invalid S3 object URI: {uri}")
    return match.group(1), match.group(2)


def require_private_uri(uri: Any, expected_key: str | None = None) -> tuple[str, str]:
    bucket, key = parse_s3(uri)
    if bucket != f"diana-omics-private-results-{ACCOUNT_ID}-{REGION}":
        raise ValueError(f"object is outside the exact private-results bucket: {uri}")
    if expected_key is not None and key != expected_key:
        raise ValueError(f"private object key differs from the exact expected key: {uri}")
    return bucket, key


def require_anchor(
    path: Path,
    receipt_path: Path,
    *,
    run_id: str | None,
    batch_job_id: str | None,
    expected_key_prefix: str | None = None,
) -> dict[str, Any]:
    anchor = load_object(path, "freeze anchor")
    receipt_sha = sha256_path(receipt_path)
    receipt_bytes = receipt_path.stat().st_size
    uri = str(anchor.get("receipt_uri", ""))
    _bucket, key = require_private_uri(uri)
    expected_suffix = f"/{receipt_sha}.json"
    checks = {
        "schema_status": anchor.get("schema_version") == 1 and anchor.get("status") == "passed",
        "receipt_hash": anchor.get("receipt_sha256") == receipt_sha,
        "receipt_bytes": anchor.get("receipt_bytes") == receipt_bytes,
        "content_addressed_uri": key.endswith(expected_suffix.lstrip("/")) or uri.endswith(expected_suffix),
        "expected_prefix": expected_key_prefix is None or key == f"{expected_key_prefix}{receipt_sha}.json",
        "receipt_version": valid_version(anchor.get("receipt_version_id")),
        "checks_exact": passed_checks(anchor.get("checks"), exact=EXPECTED_ANCHOR_CHECKS),
        "run_id": run_id is None or anchor.get("run_id") == run_id,
        "batch_job_id": batch_job_id is None or anchor.get("batch_job_id") == batch_job_id,
    }
    if not all(checks.values()):
        raise ValueError(f"freeze anchor does not bind the exact receipt: {checks}")
    return anchor


def require_unique_rows(
    rows: Any,
    *,
    key_field: str,
    expected_count: int,
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ValueError(f"{label} row count differs from its receipt")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{label} contains a non-object row")
        key = str(row.get(key_field, ""))
        if not key or key in result:
            raise ValueError(f"{label} contains an empty or duplicate {key_field}")
        result[key] = row
    return result


def validate_final_sources(
    run_id: str,
    freeze_path: Path,
    anchor_path: Path,
    materialization_path: Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    freeze = load_object(freeze_path, "final freeze receipt")
    expected_count = freeze.get("object_count")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count <= 0:
        raise ValueError("final freeze object_count must be a positive integer")
    job_id = str(freeze.get("batch_job_id", ""))
    expected_prefix = f"s3://diana-omics-private-results-{ACCOUNT_ID}-{REGION}/runs/subject01/{run_id}/deterministic/final/"
    freeze_rows = require_unique_rows(
        freeze.get("objects"),
        key_field="relative_key",
        expected_count=expected_count,
        label="final freeze",
    )
    initial_inventory = require_unique_rows(
        freeze.get("initial_inventory_identity"),
        key_field="relative_key",
        expected_count=expected_count,
        label="final freeze initial inventory",
    )
    final_inventory = require_unique_rows(
        freeze.get("final_inventory_identity"),
        key_field="relative_key",
        expected_count=expected_count,
        label="final freeze final inventory",
    )
    destination_inventory = require_unique_rows(
        freeze.get("destination_inventory"),
        key_field="relative_key",
        expected_count=expected_count,
        label="final freeze destination inventory",
    )
    freeze_checks = {
        "schema_status": freeze.get("schema_version") == 1 and freeze.get("status") == "passed",
        "run_id": freeze.get("run_id") == run_id,
        "batch_job_id": bool(job_id),
        "batch_status": freeze.get("batch_status") == "SUCCEEDED",
        "destination_prefix": freeze.get("destination_prefix") == expected_prefix,
        "versioning": freeze.get("destination_bucket_versioning") == "Enabled",
        "empty_initial_history": freeze.get("destination_initial_version_history_count") == 0,
        "anchor_strategy": freeze.get("receipt_anchor_strategy") == "sha256_content_addressed_create_only",
        "passed_count": freeze.get("passed_count") == expected_count,
        "receipt_checks": passed_checks(freeze.get("checks"), exact=EXPECTED_FINAL_FREEZE_CHECKS),
        "required_sources": set(SOURCE_RELATIVES.values()).issubset(freeze_rows),
        "complete_inventories": set(initial_inventory) == set(final_inventory) == set(destination_inventory) == set(freeze_rows),
    }
    if not all(freeze_checks.values()):
        raise ValueError(f"final freeze receipt is incomplete: {freeze_checks}")
    kms = str(freeze.get("kms_key_arn", ""))
    if not re.fullmatch(rf"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/[A-Za-z0-9-]+", kms):
        raise ValueError("final freeze KMS key ARN is malformed")
    for relative, row in freeze_rows.items():
        source = row.get("source")
        destination = row.get("destination")
        row_checks = row.get("checks")
        if not isinstance(source, dict) or not isinstance(destination, dict):
            raise ValueError(f"final freeze row lacks source/destination: {relative}")
        expected_key = f"runs/subject01/{run_id}/deterministic/final/{relative}"
        row_valid = (
            row.get("status") == "passed"
            and passed_checks(row_checks, exact=EXPECTED_FINAL_ROW_CHECKS)
            and destination.get("bucket") == f"diana-omics-private-results-{ACCOUNT_ID}-{REGION}"
            and destination.get("key") == expected_key
            and valid_version(destination.get("version_id"))
            and isinstance(destination.get("bytes"), int)
            and not isinstance(destination.get("bytes"), bool)
            and int(destination.get("bytes")) > 0
            and destination.get("checksum_type") == "FULL_OBJECT"
            and isinstance(destination.get("checksums"), dict)
            and bool(destination.get("checksums"))
            and destination.get("server_side_encryption") == "aws:kms"
            and destination.get("kms_key_id") == kms
        )
        if not row_valid:
            raise ValueError(f"final freeze row is not exact and passed: {relative}")
        source_identity = {
            "relative_key": relative,
            "key": source.get("key"),
            "bytes": source.get("bytes"),
            "etag": source.get("etag"),
            "version_id": source.get("version_id"),
        }
        destination_identity = {
            "relative_key": relative,
            "key": destination.get("key"),
            "version_id": destination.get("version_id"),
            "bytes": destination.get("bytes"),
            "etag": destination.get("etag"),
            "checksums": destination.get("checksums"),
            "checksum_type": destination.get("checksum_type"),
            "kms_key_id": destination.get("kms_key_id"),
        }
        if (
            initial_inventory[relative] != source_identity
            or final_inventory[relative] != source_identity
            or destination_inventory[relative] != destination_identity
        ):
            raise ValueError(f"final freeze source/destination inventories do not bind row: {relative}")

    require_anchor(
        anchor_path,
        freeze_path,
        run_id=run_id,
        batch_job_id=job_id,
        expected_key_prefix=(f"runs/subject01/{run_id}/deterministic/provenance/final-artifact-freeze-receipts/"),
    )
    materialized = load_object(materialization_path, "exact local materialization receipt")
    materialized_count = materialized.get("object_count")
    materialized_rows = require_unique_rows(
        materialized.get("objects"),
        key_field="relative_key",
        expected_count=expected_count,
        label="exact local materialization",
    )
    materialized_checks = {
        "schema_status": materialized.get("schema_version") == 1 and materialized.get("status") == "passed",
        "run_id": materialized.get("run_id") == run_id,
        "batch_job_id": materialized.get("batch_job_id") == job_id,
        "freeze_hash": materialized.get("freeze_receipt_sha256") == sha256_path(freeze_path),
        "kms": materialized.get("expected_kms_key_arn") == kms,
        "object_count": materialized_count == expected_count,
        "passed_count": materialized.get("passed_count") == expected_count,
        "complete_inventory": set(materialized_rows) == set(freeze_rows),
    }
    if not all(materialized_checks.values()):
        raise ValueError(f"exact local materialization is incomplete: {materialized_checks}")
    for relative, row in materialized_rows.items():
        frozen = freeze_rows[relative]["destination"]
        exact = (
            row.get("bucket") == frozen.get("bucket")
            and row.get("key") == frozen.get("key")
            and row.get("version_id") == frozen.get("version_id")
            and row.get("bytes") == frozen.get("bytes")
            and row.get("checksums") == frozen.get("checksums")
            and row.get("checksum_type") == frozen.get("checksum_type") == "FULL_OBJECT"
            and row.get("server_side_encryption") == "aws:kms"
            and row.get("kms_key_id") == kms
            and valid_sha(row.get("sha256"))
            and passed_checks(row.get("checks"), exact=EXPECTED_MATERIALIZATION_ROW_CHECKS)
        )
        if not exact:
            raise ValueError(f"local materialization does not bind frozen row: {relative}")

    values: dict[str, str] = {}
    for logical, relative in SOURCE_RELATIVES.items():
        frozen = freeze_rows[relative]["destination"]
        local = materialized_rows[relative]
        values[f"{logical}_uri"] = f"s3://{frozen['bucket']}/{frozen['key']}"
        values[f"{logical}_version_id"] = str(frozen["version_id"])
        values[f"{logical}_sha256"] = str(local["sha256"])
    return values, {
        "kms_key_arn": kms,
        "batch_job_id": job_id,
        "final_freeze_sha256": sha256_path(freeze_path),
        "final_freeze_anchor_sha256": sha256_path(anchor_path),
        "exact_materialization_sha256": sha256_path(materialization_path),
        "object_count": expected_count,
    }


def validate_reference_sources(
    run_id: str,
    freeze_path: Path,
    sha_path: Path,
    anchor_path: Path | None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Validate the exact existing two-receipt reference custody shape.

    The existing reference freeze predates content-addressed local anchors.  Its
    companion AWS-side SHA receipt binds the freeze receipt hash and exact
    VersionIds.  A later anchor may additionally be supplied and is then
    required to pass the same strict content-addressed checks.
    """

    freeze = load_object(freeze_path, "reference freeze receipt")
    sha_receipt = load_object(sha_path, "reference SHA-256 receipt")
    count = freeze.get("object_count")
    if count != 3:
        raise ValueError("reference freeze must contain exactly FASTA, FAI, and dict")
    rows = freeze.get("objects")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("reference freeze row count is not exact")
    by_artifact: dict[str, dict[str, Any]] = {}
    kms_values: set[str] = set()
    expected_prefix = f"runs/subject01/{run_id}/deterministic/reference/"
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("status") != "passed"
            or not passed_checks(row.get("checks"), exact=EXPECTED_REFERENCE_ROW_CHECKS)
        ):
            raise ValueError("reference freeze contains a non-passed row")
        destination = row.get("destination")
        if not isinstance(destination, dict):
            raise ValueError("reference freeze row lacks a destination")
        uri = str(destination.get("uri", ""))
        bucket, key = require_private_uri(uri)
        if not key.startswith(expected_prefix):
            raise ValueError("reference destination is outside the exact run prefix")
        artifact = key.removeprefix(expected_prefix)
        if artifact not in {"reference.fa", "reference.fa.fai", "reference.dict"} or artifact in by_artifact:
            raise ValueError("reference freeze artifact inventory is not exact")
        if (
            destination.get("version_id") in {"", None, "null"}
            or not valid_version(destination.get("version_id"))
            or not isinstance(destination.get("bytes"), int)
            or isinstance(destination.get("bytes"), bool)
            or int(destination.get("bytes")) <= 0
            or not str(destination.get("crc64nvme", ""))
            or destination.get("kms_key_id") is None
        ):
            raise ValueError(f"reference freeze destination is incomplete: {artifact}")
        kms_values.add(str(destination["kms_key_id"]))
        by_artifact[artifact] = {**row, "bucket": bucket, "key": key}
    if set(by_artifact) != {"reference.fa", "reference.fa.fai", "reference.dict"} or len(kms_values) != 1:
        raise ValueError("reference freeze inventory or KMS identity is ambiguous")
    kms = next(iter(kms_values))
    if freeze.get("schema_version") != 1 or freeze.get("status") != "passed":
        raise ValueError("reference freeze schema/status is not passed")

    sha_count = sha_receipt.get("object_count")
    sha_rows = require_unique_rows(
        sha_receipt.get("objects"),
        key_field="artifact",
        expected_count=3,
        label="reference SHA-256 receipt",
    )
    sha_checks = {
        "schema_status": sha_receipt.get("schema_version") == 1 and sha_receipt.get("status") == "passed",
        "count": sha_count == 3,
        "freeze_hash": sha_receipt.get("freeze_receipt_sha256") == sha256_path(freeze_path),
        "algorithm": sha_receipt.get("algorithm") == "sha256_full_object_aws_side_stream",
        "hash_status": isinstance(sha_receipt.get("execution"), dict)
        and sha_receipt["execution"].get("hash_computation_status") == "passed",
        "exact_existing_execution": isinstance(sha_receipt.get("execution"), dict)
        and sha_receipt["execution"].get("batch_terminal_status") == "FAILED_AFTER_ALL_HASHES_DURING_RECEIPT_UPLOAD"
        and sha_receipt["execution"].get("image") == EXPECTED_IMAGE
        and sha_receipt["execution"].get("job_definition")
        == (f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:job-definition/diana-hrd-private-sha256-202607:2")
        and sha_receipt["execution"].get("cloudwatch_log_group") == "/aws/batch/job"
        and valid_sha(sha_receipt["execution"].get("cloudwatch_events_sha256")),
        "exact_existing_recovery": sha_receipt.get("receipt_delivery") == "recovered_locally_from_complete_immutable_cloudwatch_hash_log"
        and valid_sha(sha_receipt.get("script_sha256")),
        "artifacts": set(sha_rows) == set(by_artifact),
    }
    if not all(sha_checks.values()):
        raise ValueError(f"reference SHA-256 receipt is incomplete: {sha_checks}")
    for artifact, row in sha_rows.items():
        frozen = by_artifact[artifact]["destination"]
        exact = (
            row.get("status") == "passed"
            and row.get("version_id") == frozen.get("version_id")
            and row.get("bytes") == frozen.get("bytes")
            and row.get("crc64nvme") == frozen.get("crc64nvme")
            and row.get("server_side_encryption") == "aws:kms"
            and row.get("kms_key_id") == frozen.get("kms_key_id") == kms
            and valid_sha(row.get("sha256"))
        )
        if not exact:
            raise ValueError(f"reference SHA-256 row does not bind freeze: {artifact}")
    if anchor_path is not None:
        require_anchor(
            anchor_path,
            freeze_path,
            run_id=None,
            batch_job_id=None,
        )

    values: dict[str, str] = {}
    for logical, artifact in REFERENCE_ARTIFACTS.items():
        frozen = by_artifact[artifact]
        sha_row = sha_rows[artifact]
        values[f"{logical}_uri"] = f"s3://{frozen['bucket']}/{frozen['key']}"
        values[f"{logical}_version_id"] = str(frozen["destination"]["version_id"])
        values[f"{logical}_sha256"] = str(sha_row["sha256"])
    return values, {
        "kms_key_arn": kms,
        "reference_freeze_sha256": sha256_path(freeze_path),
        "reference_sha256_receipt_sha256": sha256_path(sha_path),
        "reference_freeze_anchor_sha256": sha256_path(anchor_path) if anchor_path else None,
        "object_count": 3,
        "custody_mode": "anchored_receipt_plus_aws_sha" if anchor_path else "exact_existing_freeze_plus_aws_sha_receipts",
    }


def normalize_definition(value: dict[str, Any]) -> dict[str, Any]:
    container = value.get("containerProperties")
    if not isinstance(container, dict):
        raise ValueError("job definition containerProperties is missing")
    log = container.get("logConfiguration")
    if not isinstance(log, dict):
        raise ValueError("job definition logConfiguration is missing")
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


def validate_registration(
    receipt_path: Path,
    script_anchor_path: Path,
    definition_path: Path,
    expected_shell_values: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = load_object(receipt_path, "materializer registration receipt v4")
    script_anchor = load_object(script_anchor_path, "materializer script freeze anchor")
    definition = load_object(definition_path, "materializer job definition payload")
    expected_refs = list(PARAMETER_NAMES)
    command = definition.get("containerProperties", {}).get("command")
    shell = command[2] if isinstance(command, list) and len(command) == 12 else ""
    script_object = script_anchor.get("object") if isinstance(script_anchor.get("object"), dict) else {}
    script_source = script_anchor.get("source") if isinstance(script_anchor.get("source"), dict) else {}
    batch = receipt.get("batch") if isinstance(receipt.get("batch"), dict) else {}
    receipt_script = receipt.get("script_freeze") if isinstance(receipt.get("script_freeze"), dict) else {}
    registration = batch.get("registration") if isinstance(batch.get("registration"), dict) else {}
    command_checks = {
        "command_shape": isinstance(command, list)
        and command[:2] == ["bash", "-lc"]
        and command[3] == "materializer"
        and command[4:] == [f"Ref::{name}" for name in expected_refs],
        "strict_shell": shell.startswith("set -euo pipefail;"),
        "script_uri": (
            f"--bucket {script_object.get('bucket', '')}" in shell
            and f"--key {script_object.get('key', '')}" in shell
            and script_object.get("uri") == f"s3://{script_object.get('bucket', '')}/{script_object.get('key', '')}"
        ),
        "script_version": f"--version-id {script_object.get('version_id', '')}" in shell,
        "script_sha": f'test "$actual" = {EXPECTED_MATERIALIZER_SHA256}' in shell,
    }
    for name, value in expected_shell_values.items():
        command_checks[f"shell_{name}"] = f"--{name.replace('_', '-')} {value}" in shell
    expected_binding = {f"${index}": name for index, name in enumerate(expected_refs, start=1)}
    checks = {
        "schema_status": receipt.get("schema_version") == 3 and receipt.get("status") == "registered_not_submitted",
        "no_call_boundary": receipt.get("classification_authorization") == "none" and receipt.get("authorized_hrd_state") == "no_call",
        "receipt_checks": passed_checks(receipt.get("checks"), exact=EXPECTED_REGISTRATION_CHECKS),
        "script_anchor_hash": receipt_script.get("anchor_sha256") == sha256_path(script_anchor_path),
        "script_status": script_anchor.get("schema_version") == 1 and script_anchor.get("status") == "passed",
        "script_sha": script_source.get("sha256") == EXPECTED_MATERIALIZER_SHA256,
        "script_object_version": valid_version(script_object.get("version_id")),
        "script_checks": passed_checks(script_anchor.get("checks"), exact=EXPECTED_SCRIPT_ANCHOR_CHECKS),
        "script_receipt_binding": receipt_script.get("object") == script_object
        and receipt_script.get("source") == script_source
        and receipt_script.get("checks") == script_anchor.get("checks"),
        "definition_hash": batch.get("definition_sha256") == sha256_path(definition_path),
        "definition_arn": batch.get("job_definition_arn") == JOB_DEFINITION_ARN
        and registration.get("jobDefinitionArn") == JOB_DEFINITION_ARN,
        "definition_revision": batch.get("revision") == 4 and registration.get("revision") == 4,
        "definition_runtime": batch.get("retry_attempts") == 1
        and batch.get("timeout_seconds") == 21600
        and batch.get("vcpus") == 8
        and batch.get("memory_mib") == 32000,
        "image": batch.get("image") == EXPECTED_IMAGE,
        "substitutions": batch.get("parameter_substitution") == expected_refs,
        "shell_argument_binding": batch.get("shell_argument_binding") == expected_binding,
        "command": all(command_checks.values()),
        "normalized_definition": normalize_definition(definition) == definition,
    }
    if not all(checks.values()):
        raise ValueError(f"materializer registration receipt/definition is not exact: {checks}; command={command_checks}")
    return receipt, definition


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


def validate_live_definition(local: dict[str, Any], region: str) -> dict[str, Any]:
    live = require_one(
        aws_json(
            region,
            "batch",
            "describe-job-definitions",
            "--job-definitions",
            JOB_DEFINITION_ARN,
        ),
        "jobDefinitions",
    )
    checks = {
        "arn": live.get("jobDefinitionArn") == JOB_DEFINITION_ARN,
        "revision": live.get("revision") == 4,
        "active": live.get("status") == "ACTIVE",
        "exact_payload": normalize_definition(live) == local,
        "one_attempt": (live.get("retryStrategy") or {}).get("attempts") == 1,
        "immutable_image": (live.get("containerProperties") or {}).get("image") == EXPECTED_IMAGE,
    }
    if not all(checks.values()):
        raise ValueError(f"live materializer revision 4 differs from frozen payload: {checks}")
    return {"job_definition_arn": JOB_DEFINITION_ARN, "checks": checks}


def validate_live_image(region: str) -> dict[str, Any]:
    payload = aws_json(
        region,
        "ecr",
        "batch-get-image",
        "--repository-name",
        EXPECTED_IMAGE_REPOSITORY,
        "--image-ids",
        f"imageDigest={EXPECTED_IMAGE_DIGEST}",
        "--accepted-media-types",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
    image = require_one(payload, "images")
    if payload.get("failures") not in (None, []):
        raise ValueError("ECR returned failures for the immutable materializer image")
    manifest = json.loads(str(image.get("imageManifest", "")))
    manifests = manifest.get("manifests") if isinstance(manifest, dict) else None
    if not isinstance(manifests, list) or not manifests:
        raise ValueError("materializer image is not an OCI/Docker image index")
    runnable = [
        row
        for row in manifests
        if isinstance(row, dict)
        and isinstance(row.get("platform"), dict)
        and row["platform"].get("os") != "unknown"
        and row["platform"].get("architecture") != "unknown"
    ]
    attestations = [row for row in manifests if row not in runnable]
    attestation_valid = all(
        isinstance(row, dict)
        and row.get("platform") == {"architecture": "unknown", "os": "unknown"}
        and isinstance(row.get("annotations"), dict)
        and row["annotations"].get("vnd.docker.reference.type") == "attestation-manifest"
        for row in attestations
    )
    checks = {
        "digest": (image.get("imageId") or {}).get("imageDigest") == EXPECTED_IMAGE_DIGEST,
        "index_media_type": image.get("imageManifestMediaType")
        in {
            "application/vnd.oci.image.index.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
        },
        "one_runnable_manifest": len(runnable) == 1,
        "linux_arm64_only": len(runnable) == 1 and runnable[0].get("platform") == {"architecture": "arm64", "os": "linux"},
        "other_manifests_are_attestations": attestation_valid,
    }
    if not all(checks.values()):
        raise ValueError(f"immutable materializer image is not ARM64-only: {checks}")
    return {
        "image": EXPECTED_IMAGE,
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
    resources = compute.get("computeResources") if isinstance(compute.get("computeResources"), dict) else {}
    checks = {
        "queue_identity": queue.get("jobQueueArn") == QUEUE_ARN and queue.get("jobQueueName") == QUEUE_NAME,
        "queue_live": queue.get("state") == "ENABLED" and queue.get("status") == "VALID",
        "queue_exact_ce": queue.get("computeEnvironmentOrder") == [{"order": 1, "computeEnvironment": COMPUTE_ENVIRONMENT_ARN}],
        "ce_identity": compute.get("computeEnvironmentArn") == COMPUTE_ENVIRONMENT_ARN
        and compute.get("computeEnvironmentName") == QUEUE_NAME,
        "ce_live": compute.get("state") == "ENABLED" and compute.get("status") == "VALID",
        "ce_ec2": resources.get("type") == "EC2",
        "ce_arm_instances": isinstance(resources.get("instanceTypes"), list)
        and sorted(str(value) for value in resources["instanceTypes"]) == sorted(EXPECTED_INSTANCE_TYPES),
    }
    if not all(checks.values()):
        raise ValueError(f"live materializer queue/compute environment is not exact: {checks}")
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
        raise ValueError("Batch queue inventory omitted the explicit materializer queue")
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
        raise ValueError(f"an exact materializer job name already exists: {matches}")
    return {
        "job_name": job_name,
        "queue_count": len(queue_arns),
        "status_count_per_queue": len(JOB_STATUSES),
        "job_summaries_scanned": scanned,
        "exact_name_match_count": 0,
    }


def require_empty_history(uri: str, region: str) -> dict[str, Any]:
    match = re.fullmatch(r"s3://([^/]+)/(.+/)", uri)
    if not match:
        raise ValueError("history target must be an S3 prefix ending in slash")
    bucket, prefix = match.groups()
    if bucket != f"diana-omics-private-results-{ACCOUNT_ID}-{REGION}":
        raise ValueError("history target is outside the exact private-results bucket")
    key_marker = ""
    version_marker = ""
    observed: set[tuple[str, str]] = set()
    for page_count in range(1, 1001):
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
        if version_marker:
            arguments.extend(["--version-id-marker", version_marker])
        page = aws_json(region, *arguments)
        if page.get("Versions") or page.get("DeleteMarkers"):
            raise ValueError(f"destination prefix has object or delete-marker history: {uri}")
        if page.get("IsTruncated") is not True:
            return {"uri": uri, "page_count": page_count, "history_count": 0}
        next_key = str(page.get("NextKeyMarker", ""))
        next_version = str(page.get("NextVersionIdMarker", ""))
        if not next_key or not next_version or (next_key, next_version) in observed:
            raise ValueError("truncated S3 version history omitted or repeated its marker")
        observed.add((next_key, next_version))
        key_marker, version_marker = next_key, next_version
    raise ValueError("S3 history pagination exceeded the safety limit")


def validate_identity(region: str) -> dict[str, Any]:
    identity = aws_json(region, "sts", "get-caller-identity")
    if identity.get("Account") != ACCOUNT_ID or not str(identity.get("Arn", "")).startswith(f"arn:aws:iam::{ACCOUNT_ID}:"):
        raise ValueError("AWS caller is not an IAM principal in the destination account")
    return {"account": ACCOUNT_ID, "arn": identity.get("Arn")}


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
    content = canonical_bytes(value)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def require_new_outputs(paths: Iterable[Path]) -> None:
    values = list(paths)
    resolved = [path.resolve(strict=False) for path in values]
    if len(set(resolved)) != len(resolved):
        raise ValueError("private request/response output paths must be distinct")
    for path in values:
        if path.is_symlink():
            raise FileExistsError(f"private output may not be a symlink: {path}")
        require_safe_new_output_parent(path)
        if path.exists():
            raise FileExistsError(f"refusing to overwrite private output: {path}")


def require_safe_new_output_parent(path: Path) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise FileExistsError(
                f"private output parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def build_parameters(sources: dict[str, str], references: dict[str, str]) -> dict[str, str]:
    values = {
        "source_vcf_version_id": sources["source_vcf_version_id"],
        "source_vcf_index_version_id": sources["source_vcf_index_version_id"],
        "source_matrix_version_id": sources["source_matrix_version_id"],
        "source_vcf_sha256": sources["source_vcf_sha256"],
        "source_vcf_index_sha256": sources["source_vcf_index_sha256"],
        "source_matrix_sha256": sources["source_matrix_sha256"],
        "reference_fasta_version_id": references["reference_fasta_version_id"],
        "reference_fai_version_id": references["reference_fai_version_id"],
    }
    if list(values) != list(PARAMETER_NAMES):
        raise AssertionError("internal parameter order differs from the immutable definition")
    for name, value in values.items():
        if name.endswith("_sha256"):
            if not valid_sha(value):
                raise ValueError(f"materializer parameter is not SHA-256: {name}")
        elif not valid_version(value):
            raise ValueError(f"materializer parameter is not an exact VersionId: {name}")
    return values


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    run_match = RUN_ID.fullmatch(args.run_id)
    if not run_match:
        raise ValueError("run-id must be diana-wgs-hrd-YYYYMMDDTHHMMSSZ")
    job_name = f"diana-wgs-hrd-materialize-{run_match.group(1)}"
    sources, final_custody = validate_final_sources(
        args.run_id,
        args.final_freeze_receipt,
        args.final_freeze_anchor,
        args.exact_materialization_receipt,
    )
    references, reference_custody = validate_reference_sources(
        args.run_id,
        args.reference_freeze_receipt,
        args.reference_sha256_receipt,
        args.reference_freeze_anchor,
    )
    if final_custody["kms_key_arn"] != reference_custody["kms_key_arn"]:
        raise ValueError("final-artifact and reference custody use different KMS keys")
    destination_prefix = f"s3://diana-omics-private-results-{ACCOUNT_ID}-{REGION}/runs/subject01/{args.run_id}/deterministic/final/"
    receipt_prefix = (
        f"s3://diana-omics-private-results-{ACCOUNT_ID}-{REGION}/runs/subject01/"
        f"{args.run_id}/deterministic/provenance/crosscheck-materialization-receipts/"
    )
    shell_values = {
        "source_vcf_uri": sources["source_vcf_uri"],
        "source_vcf_index_uri": sources["source_vcf_index_uri"],
        "source_matrix_uri": sources["source_matrix_uri"],
        "reference_fasta_uri": references["reference_fasta_uri"],
        "reference_fai_uri": references["reference_fai_uri"],
        "reference_fasta_sha256": references["reference_fasta_sha256"],
        "reference_fai_sha256": references["reference_fai_sha256"],
        "destination_prefix": destination_prefix.rstrip("/"),
        "receipt_prefix": receipt_prefix.rstrip("/"),
        "kms_key_arn": final_custody["kms_key_arn"],
    }
    _registration, definition = validate_registration(
        args.registration_receipt,
        args.materializer_script_anchor,
        args.job_definition_payload,
        shell_values,
    )
    parameters = build_parameters(sources, references)
    identity = validate_identity(args.region)
    live_definition = validate_live_definition(definition, args.region)
    live_image = validate_live_image(args.region)
    live_queue = validate_live_queue(args.region)
    job_uniqueness = require_no_existing_job(job_name, args.region)
    destination_history = require_empty_history(destination_prefix, args.region)
    receipt_history = require_empty_history(receipt_prefix, args.region)
    submit_request = {
        "jobName": job_name,
        "jobQueue": QUEUE_NAME,
        "jobDefinition": JOB_DEFINITION_ARN,
        "parameters": parameters,
        "retryStrategy": {"attempts": 1},
    }
    return {
        "schema_version": 1,
        "status": "submission_authorized" if args.submit else "rendered_only",
        "generated_at_utc": now(),
        "scope": "private one-shot materializer-v4 submission preflight",
        "run_id": args.run_id,
        "classification_authorization": "none",
        "authorized_hrd_state": "no_call",
        "input_receipts": {
            "final_freeze": {
                "path": str(args.final_freeze_receipt.resolve()),
                "sha256": final_custody["final_freeze_sha256"],
            },
            "final_freeze_anchor": {
                "path": str(args.final_freeze_anchor.resolve()),
                "sha256": final_custody["final_freeze_anchor_sha256"],
            },
            "exact_materialization": {
                "path": str(args.exact_materialization_receipt.resolve()),
                "sha256": final_custody["exact_materialization_sha256"],
            },
            "reference_freeze": {
                "path": str(args.reference_freeze_receipt.resolve()),
                "sha256": reference_custody["reference_freeze_sha256"],
            },
            "reference_sha256": {
                "path": str(args.reference_sha256_receipt.resolve()),
                "sha256": reference_custody["reference_sha256_receipt_sha256"],
            },
            "reference_freeze_anchor": (
                {
                    "path": str(args.reference_freeze_anchor.resolve()),
                    "sha256": reference_custody["reference_freeze_anchor_sha256"],
                }
                if args.reference_freeze_anchor
                else None
            ),
            "materializer_script_anchor": {
                "path": str(args.materializer_script_anchor.resolve()),
                "sha256": sha256_path(args.materializer_script_anchor),
            },
            "registration_v4": {
                "path": str(args.registration_receipt.resolve()),
                "sha256": sha256_path(args.registration_receipt),
            },
            "job_definition_v4": {
                "path": str(args.job_definition_payload.resolve()),
                "sha256": sha256_path(args.job_definition_payload),
            },
        },
        "custody": {
            "final": final_custody,
            "reference": reference_custody,
            "source_uris": {name: value for name, value in sources.items() if name.endswith("_uri")},
            "reference_uris": {name: value for name, value in references.items() if name.endswith("_uri")},
        },
        "live_preflight": {
            "identity": identity,
            "job_definition": live_definition,
            "image": live_image,
            "queue": live_queue,
            "job_name_uniqueness": job_uniqueness,
            "destination_history": destination_history,
            "receipt_history": receipt_history,
        },
        "submit_job_request": submit_request,
        "checks": {
            "receipt_hashes_cross_bound": True,
            "three_exact_source_versions_and_local_sha256": True,
            "two_exact_reference_versions_and_aws_sha256": True,
            "exact_active_revision_4": True,
            "immutable_arm64_image": True,
            "exact_live_arm_queue": True,
            "one_attempt": True,
            "zero_existing_exact_job_name": True,
            "empty_destination_history": True,
            "empty_receipt_history": True,
            "default_dry_run_behavior_preserved": True,
            "submission_guard_satisfied": not args.submit or os.environ.get("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN") == "YES",
        },
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
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--final-freeze-receipt", required=True, type=Path)
    parser.add_argument("--final-freeze-anchor", required=True, type=Path)
    parser.add_argument("--exact-materialization-receipt", required=True, type=Path)
    parser.add_argument("--reference-freeze-receipt", required=True, type=Path)
    parser.add_argument("--reference-sha256-receipt", required=True, type=Path)
    parser.add_argument("--reference-freeze-anchor", type=Path)
    parser.add_argument("--materializer-script-anchor", required=True, type=Path)
    parser.add_argument("--registration-receipt", required=True, type=Path)
    parser.add_argument("--job-definition-payload", required=True, type=Path)
    parser.add_argument("--request-output", required=True, type=Path)
    parser.add_argument("--response-output", type=Path)
    parser.add_argument("--region", default=REGION, choices=[REGION])
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    outputs = [args.request_output]
    if args.submit:
        if os.environ.get("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN") != "YES":
            raise SystemExit("Fail-closed: --submit requires HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES")
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
                    "job_name": request_receipt["submit_job_request"]["jobName"],
                    "request_output": str(args.request_output),
                    "submitted": False,
                },
                sort_keys=True,
            )
        )
        return 0

    assert args.response_output is not None
    descriptor = reserve_private(args.response_output)
    try:
        response = submit(request_receipt["submit_job_request"], args.region)
        response_receipt = {
            "schema_version": 1,
            "status": "submitted",
            "submitted_at_utc": now(),
            "run_id": args.run_id,
            "request_receipt": {
                "path": str(args.request_output.resolve()),
                "sha256": sha256_path(args.request_output),
            },
            "submit_job_request_sha256": sha256_bytes(canonical_bytes(request_receipt["submit_job_request"])),
            "response": response,
            "checks": {
                "request_receipt_mode_0600": (args.request_output.stat().st_mode & 0o777) == 0o600,
                "exact_job_name": response.get("jobName") == request_receipt["submit_job_request"]["jobName"],
                "job_id_and_arn": True,
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
            "run_id": args.run_id,
            "request_receipt": {
                "path": str(args.request_output.resolve()),
                "sha256": sha256_path(args.request_output),
            },
            "error": f"{type(error).__name__}: {error}",
            "manual_reconciliation_required": True,
        }
        try:
            complete_reserved(descriptor, response_receipt)
        except Exception as receipt_error:
            raise SystemExit(
                "Fail-closed: submission failed or is ambiguous and its reserved response receipt "
                f"could not be finalized at {args.response_output}; do not retry before manual reconciliation"
            ) from receipt_error
        raise SystemExit(
            f"Fail-closed: submission failed or is ambiguous; do not retry before reconciling {args.response_output}"
        ) from error
    try:
        complete_reserved(descriptor, response_receipt)
    except Exception as error:
        raise SystemExit(
            "Fail-closed: Batch submission succeeded but its reserved response receipt could not be "
            f"finalized at {args.response_output}; do not retry before manual reconciliation"
        ) from error
    print(
        json.dumps(
            {
                "status": "submitted",
                "job_id": response["jobId"],
                "job_name": response["jobName"],
                "request_output": str(args.request_output),
                "response_output": str(args.response_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
