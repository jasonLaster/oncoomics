#!/usr/bin/env python3
"""Finalize the alias-only cross-check contract from immutable custody receipts.

This is deliberately a local operation.  It does not inspect current S3 keys and
does not publish anything.  The only accepted final VCF, index, and SBS96
identities are the exact versions emitted by the passed cross-check
materialization receipt, whose inputs must in turn bind to the exact private
freeze and exact-version local materialization receipts.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")
FINAL_OUTPUTS = {
    "somatic_vcf": "somatic.pass.vcf.gz",
    "somatic_vcf_index": "somatic.pass.vcf.gz.tbi",
    "sbs96_matrix": "sbs96.csv",
}
ALL_MATERIALIZER_OUTPUTS = set(FINAL_OUTPUTS.values()) | {
    "staged_input_validation.json"
}
SOURCE_ROLES = {
    "vcf": "somatic_vcf",
    "vcf_index": "somatic_vcf_index",
    "matrix": "sbs96_matrix",
}
REFERENCE_ROLES = {"fasta": "fasta", "fai": "fai"}
EXPECTED_FINAL_FREEZE_ANCHOR_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "sha256_checksum_exact": True,
    "exact_kms": True,
    "single_create_only_version": True,
}
EXPECTED_FINAL_FREEZE_KEYS = frozenset(
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
        "destination_inventory",
        "checks",
        "completed_at",
        "passed_count",
    }
)
EXPECTED_FINAL_FREEZE_CHECKS = {
    "execution_receipt_bound": True,
    "complete_source_inventory_unchanged": True,
    "destination_exact_history_and_receipt_match": True,
}
EXPECTED_FINAL_ROW_KEYS = frozenset(
    {"relative_key", "source", "destination", "status", "checks"}
)
EXPECTED_FINAL_SOURCE_KEYS = frozenset(
    {"bucket", "key", "version_id", "bytes", "etag", "checksums", "checksum_type"}
)
EXPECTED_FINAL_DESTINATION_KEYS = frozenset(
    {
        "bucket",
        "key",
        "version_id",
        "bytes",
        "etag",
        "checksums",
        "checksum_type",
        "server_side_encryption",
        "kms_key_id",
    }
)
EXPECTED_FINAL_DESTINATION_INVENTORY_KEYS = frozenset(
    {
        "relative_key",
        "key",
        "version_id",
        "bytes",
        "etag",
        "checksums",
        "checksum_type",
        "kms_key_id",
    }
)
EXPECTED_FINAL_ROW_CHECKS = {
    "listed_inventory_stable": True,
    "source_stable": True,
    "size_matches": True,
    "common_checksum_matches": True,
    "exact_kms_matches": True,
    "destination_versioned": True,
    "copy_response_version_matches": True,
}
EXPECTED_MATERIALIZATION_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "run_id",
        "batch_job_id",
        "script_sha256",
        "freeze_receipt_sha256",
        "expected_kms_key_arn",
        "materialization_dir",
        "object_count",
        "objects",
        "passed_count",
    }
)
OPTIONAL_MATERIALIZATION_RECOVERY_KEYS = frozenset(
    {
        "recovered_from_status",
        "prior_receipt_sha256",
        "prior_error",
        "recovered_prepared_cutover",
    }
)
EXPECTED_MATERIALIZATION_ROW_KEYS = frozenset(
    {
        "relative_key",
        "bucket",
        "key",
        "bytes",
        "version_id",
        "checksums",
        "checksum_type",
        "server_side_encryption",
        "kms_key_id",
        "sha256",
        "checks",
    }
)
EXPECTED_MATERIALIZATION_CHECKS = {
    "version_id": True,
    "content_length": True,
    "local_bytes": True,
    "checksums": True,
    "checksum_type": True,
    "sse": True,
    "kms": True,
}
EXPECTED_CROSSCHECK_CHECKS = {
    "all_sources_exact_version_and_sha256": True,
    "alias_only_pass_snv_vcf": True,
    "sbs96_matches_independent_pass_vcf_derivation": True,
    "destination_prefix_initially_empty": True,
    "all_outputs_create_only": True,
    "destination_exact_single_version_history": True,
}
EXPECTED_CROSSCHECK_RECEIPT_KEYS = frozenset(
    {
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
)
EXPECTED_CROSSCHECK_SOURCE_KEYS = frozenset(
    {
        "uri",
        "version_id",
        "bytes",
        "etag",
        "checksums",
        "sha256",
        "expected_sha256",
        "kms_key_arn",
    }
)
EXPECTED_CROSSCHECK_OUTPUT_KEYS = frozenset(
    {"uri", "version_id", "bytes", "etag", "checksums", "sha256", "kms_key_arn", "checks"}
)
EXPECTED_CROSSCHECK_INVENTORY_KEYS = frozenset(
    {"filename", "key", "version_id", "bytes", "sha256", "checksums"}
)
EXPECTED_CROSSCHECK_OUTPUT_CHECKS = {
    "create_only_put": True,
    "version_exact": True,
    "bytes_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_version_history": True,
}
EXPECTED_CROSSCHECK_ANCHOR_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_create_only_version": True,
}
EXPECTED_FINALIZED_CUSTODY_CHECKS = {
    "successful_execution_freeze_bound": True,
    "full_freeze_exactly_materialized": True,
    "crosscheck_sources_match_exact_freeze": True,
    "alias_only_outputs_have_single_create_only_versions": True,
    "sbs96_independently_rederived_from_final_pass_vcf": True,
}


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def require_full_object_sha256(value: dict[str, Any], label: str) -> str:
    digest = require_hex(value.get("sha256"), label)
    checksums = value.get("checksums")
    if (
        not isinstance(checksums, dict)
        or checksums.get("ChecksumType") != "FULL_OBJECT"
        or checksums.get("ChecksumSHA256") != checksum_sha256(digest)
    ):
        raise ValueError(f"{label} lacks exact full-object SHA-256")
    return digest


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def load_object(path: Path, label: str) -> dict[str, Any]:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def require_hex(value: Any, label: str) -> str:
    text = str(value).lower()
    if not HEX64.fullmatch(text):
        raise ValueError(f"{label} is not an exact SHA-256")
    return text


def require_version(value: Any, label: str) -> str:
    text = str(value)
    if not text or text.lower() in {"none", "null"} or any(c.isspace() for c in text):
        raise ValueError(f"{label} lacks an exact S3 VersionId")
    return text


def require_all_true(value: Any, label: str) -> None:
    if not isinstance(value, dict) or not value or any(item is not True for item in value.values()):
        raise ValueError(f"{label} did not pass every custody check")


def require_exact_true(value: Any, expected: dict[str, bool], label: str) -> None:
    if value != expected:
        raise ValueError(f"{label} did not pass the exact custody checks")


def require_exact_keys(
    value: Any,
    expected: frozenset[str],
    label: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is malformed")
    observed = set(value)
    missing = expected - observed
    unexpected = observed - expected - optional
    if missing or unexpected:
        raise ValueError(
            f"{label} has stale or missing metadata: "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )
    return value


def require_final_destination_inventory(
    receipt: dict[str, Any],
    destination_by_relative: dict[str, dict[str, Any]],
) -> None:
    destination_inventory = receipt.get("destination_inventory")
    if (
        not isinstance(destination_inventory, list)
        or len(destination_inventory) != len(destination_by_relative)
    ):
        raise ValueError("final artifact freeze destination inventory is not exact")

    inventory_by_relative: dict[str, dict[str, Any]] = {}
    for raw in destination_inventory:
        row = require_exact_keys(
            raw,
            EXPECTED_FINAL_DESTINATION_INVENTORY_KEYS,
            "final artifact freeze destination inventory",
        )
        relative = str(row.get("relative_key", ""))
        if not relative:
            raise ValueError("final artifact freeze destination inventory is not exact")
        if relative in inventory_by_relative:
            raise ValueError("duplicate final artifact freeze destination inventory row")
        inventory_by_relative[relative] = row

    if set(inventory_by_relative) != set(destination_by_relative):
        raise ValueError(
            "final artifact freeze destination inventory differs from object rows"
        )

    for relative, destination in destination_by_relative.items():
        inventory = inventory_by_relative[relative]
        if (
            inventory.get("key") != destination.get("key")
            or inventory.get("version_id") != destination.get("version_id")
            or inventory.get("bytes") != destination.get("bytes")
            or inventory.get("etag") != destination.get("etag")
            or inventory.get("checksums") != destination.get("checksums")
            or inventory.get("checksum_type") != destination.get("checksum_type")
            or inventory.get("kms_key_id") != destination.get("kms_key_id")
        ):
            raise ValueError(
                "final artifact freeze destination inventory differs from object rows"
            )


def validate_anchor(
    receipt_path: Path,
    anchor_path: Path,
    label: str,
    expected_checks: dict[str, bool],
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = load_object(receipt_path, f"{label} receipt")
    anchor = load_object(anchor_path, f"{label} anchor")
    receipt_hash = sha256(receipt_path)
    if (
        anchor.get("schema_version") != 1
        or anchor.get("status") != "passed"
        or str(anchor.get("receipt_sha256", "")).lower() != receipt_hash
        or int(anchor.get("receipt_bytes", -1)) != receipt_path.stat().st_size
        or not str(anchor.get("receipt_uri", "")).startswith(
            "s3://diana-omics-private-results-"
        )
    ):
        raise ValueError(f"{label} anchor does not bind the local receipt")
    require_version(anchor.get("receipt_version_id"), f"{label} anchor")
    require_exact_true(anchor.get("checks"), expected_checks, f"{label} anchor")
    return receipt, anchor


def validate_freeze(
    receipt: dict[str, Any], anchor: dict[str, Any], receipt_sha256: str
) -> dict[str, dict[str, Any]]:
    require_exact_keys(
        receipt,
        EXPECTED_FINAL_FREEZE_KEYS,
        "final artifact freeze receipt",
    )
    rows = receipt.get("objects")
    checks = receipt.get("checks")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "passed"
        or receipt.get("batch_status") != "SUCCEEDED"
        or receipt.get("destination_bucket_versioning") != "Enabled"
        or receipt.get("destination_initial_version_history_count") != 0
        or receipt.get("receipt_anchor_strategy")
        != "sha256_content_addressed_create_only"
        or not isinstance(rows, list)
        or not rows
        or len(rows) != int(receipt.get("object_count", -1))
        or len(rows) != int(receipt.get("passed_count", -1))
        or receipt.get("initial_inventory_identity")
        != receipt.get("final_inventory_identity")
    ):
        raise ValueError("final artifact freeze receipt is not a complete one-shot freeze")
    require_exact_true(checks, EXPECTED_FINAL_FREEZE_CHECKS, "final artifact freeze")
    if anchor.get("receipt_sha256") != receipt_sha256:
        raise ValueError("final freeze anchor hash changed after validation")
    kms_key_arn = receipt.get("kms_key_arn")
    by_uri: dict[str, dict[str, Any]] = {}
    destination_by_relative: dict[str, dict[str, Any]] = {}
    for row in rows:
        row = require_exact_keys(
            row,
            EXPECTED_FINAL_ROW_KEYS,
            "final artifact freeze row",
        )
        if row.get("status") != "passed":
            raise ValueError("final artifact freeze contains a non-passed row")
        require_exact_keys(
            row.get("source"),
            EXPECTED_FINAL_SOURCE_KEYS,
            "final artifact freeze source",
        )
        require_exact_true(
            row.get("checks"),
            EXPECTED_FINAL_ROW_CHECKS,
            "final artifact freeze row",
        )
        destination = row.get("destination")
        destination = require_exact_keys(
            destination,
            EXPECTED_FINAL_DESTINATION_KEYS,
            "final artifact freeze destination",
        )
        uri = f"s3://{destination.get('bucket', '')}/{destination.get('key', '')}"
        if not uri.startswith("s3://diana-omics-private-results-"):
            raise ValueError("final artifact freeze destination is not private")
        require_version(destination.get("version_id"), "frozen destination")
        if (
            not isinstance(destination.get("bytes"), int)
            or isinstance(destination.get("bytes"), bool)
            or int(destination.get("bytes")) <= 0
            or destination.get("checksum_type") != "FULL_OBJECT"
            or not isinstance(destination.get("checksums"), dict)
            or not destination.get("checksums")
            or destination.get("server_side_encryption") != "aws:kms"
            or destination.get("kms_key_id") != kms_key_arn
        ):
            raise ValueError("final artifact freeze destination is not exact")
        if uri in by_uri:
            raise ValueError("duplicate final artifact freeze destination URI")
        relative = str(row.get("relative_key", ""))
        if not relative:
            raise ValueError("final artifact freeze row is missing its relative key")
        if relative in destination_by_relative:
            raise ValueError("duplicate final artifact freeze relative key")
        by_uri[uri] = destination
        destination_by_relative[relative] = destination
    require_final_destination_inventory(receipt, destination_by_relative)
    return by_uri


def validate_exact_materialization(
    receipt: dict[str, Any], freeze_sha256: str, freeze_by_uri: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    require_exact_keys(
        receipt,
        EXPECTED_MATERIALIZATION_KEYS,
        "exact-version materialization",
        optional=OPTIONAL_MATERIALIZATION_RECOVERY_KEYS,
    )
    rows = receipt.get("objects")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "passed"
        or str(receipt.get("freeze_receipt_sha256", "")).lower() != freeze_sha256
        or not isinstance(rows, list)
        or not rows
        or len(rows) != int(receipt.get("object_count", -1))
        or len(rows) != int(receipt.get("passed_count", -1))
    ):
        raise ValueError("exact-version materialization is incomplete or unbound")
    by_uri: dict[str, dict[str, Any]] = {}
    for row in rows:
        row = require_exact_keys(
            row,
            EXPECTED_MATERIALIZATION_ROW_KEYS,
            "exact-version materialization row",
        )
        require_exact_true(
            row.get("checks"),
            EXPECTED_MATERIALIZATION_CHECKS,
            "exact-version materialization row",
        )
        uri = f"s3://{row.get('bucket', '')}/{row.get('key', '')}"
        frozen = freeze_by_uri.get(uri)
        if (
            frozen is None
            or row.get("version_id") != frozen.get("version_id")
            or int(row.get("bytes", -1)) != int(frozen.get("bytes", -2))
            or row.get("checksums") != frozen.get("checksums")
            or row.get("checksum_type") != frozen.get("checksum_type")
            or row.get("checksum_type") != "FULL_OBJECT"
            or row.get("server_side_encryption") != "aws:kms"
            or row.get("kms_key_id") != receipt.get("expected_kms_key_arn")
        ):
            raise ValueError("exact-version materialization differs from final freeze")
        require_hex(row.get("sha256"), "exact-version materialization row")
        by_uri[uri] = row
    if set(by_uri) != set(freeze_by_uri):
        raise ValueError("exact-version materialization does not cover the full freeze")
    return by_uri


def output_blob(row: dict[str, Any], expected_uri: str, label: str) -> dict[str, Any]:
    if row.get("uri") != expected_uri:
        raise ValueError(f"{label} URI differs from the pending contract")
    require_all_true(row.get("checks"), f"{label} published output")
    digest = require_full_object_sha256(row, label)
    return {
        "uri": expected_uri,
        "version_id": require_version(row.get("version_id"), label),
        "sha256": digest,
        **({"derived_from_final_pass_vcf": True} if label == "sbs96_matrix" else {}),
    }


def finalize(
    pending: dict[str, Any],
    freeze_receipt: dict[str, Any],
    freeze_anchor: dict[str, Any],
    exact_materialization: dict[str, Any],
    crosscheck_receipt: dict[str, Any],
    crosscheck_anchor: dict[str, Any],
    *,
    freeze_receipt_sha256: str,
    exact_materialization_sha256: str,
    crosscheck_receipt_sha256: str,
    finalizer_sha256: str,
    expected_crosscheck_materializer_sha256: str,
) -> dict[str, Any]:
    require_exact_keys(
        crosscheck_receipt,
        EXPECTED_CROSSCHECK_RECEIPT_KEYS,
        "cross-check materialization receipt",
    )
    freeze_by_uri = validate_freeze(
        freeze_receipt, freeze_anchor, freeze_receipt_sha256
    )
    exact_by_uri = validate_exact_materialization(
        exact_materialization, freeze_receipt_sha256, freeze_by_uri
    )
    if (
        crosscheck_receipt.get("schema_version") != 2
        or crosscheck_receipt.get("status") != "passed"
        or crosscheck_receipt.get("run_alias") != pending.get("run_alias")
        or crosscheck_receipt.get("destination_bucket_versioning") != "Enabled"
        or crosscheck_receipt.get("destination_initial_version_history_count") != 0
        or crosscheck_receipt.get("receipt_anchor_strategy")
        != "sha256_content_addressed_create_only"
        or str(crosscheck_receipt.get("script_sha256", "")).lower()
        != require_hex(
            expected_crosscheck_materializer_sha256,
            "expected cross-check materializer script",
        )
        or crosscheck_receipt.get("classification_authorization") != "none"
        or crosscheck_receipt.get("authorized_hrd_state") != "no_call"
    ):
        raise ValueError("cross-check materialization is not a passed one-shot publication")
    require_exact_true(
        crosscheck_receipt.get("checks"),
        EXPECTED_CROSSCHECK_CHECKS,
        "cross-check materialization",
    )
    if crosscheck_anchor.get("receipt_sha256") != crosscheck_receipt_sha256:
        raise ValueError("cross-check materialization anchor hash changed after validation")

    source = crosscheck_receipt.get("source_custody")
    outputs = crosscheck_receipt.get("outputs")
    if not isinstance(source, dict) or not isinstance(outputs, dict):
        raise ValueError("cross-check materialization omits source or output custody")
    if set(source) != {"vcf", "vcf_index", "matrix", "fasta", "fai"}:
        raise ValueError("cross-check materialization source roles are not exact")
    if set(outputs) != ALL_MATERIALIZER_OUTPUTS:
        raise ValueError("cross-check materialization output inventory is not exact")
    destination_inventory = crosscheck_receipt.get("destination_inventory")
    if (
        not isinstance(destination_inventory, list)
        or len(destination_inventory) != len(outputs)
    ):
        raise ValueError("cross-check destination inventory is incomplete")
    inventory_by_name = {
        str(row.get("filename", "")): row
        for row in destination_inventory
        if isinstance(row, dict)
    }
    if set(inventory_by_name) != set(outputs):
        raise ValueError("cross-check destination inventory differs from outputs")
    for filename, row in outputs.items():
        row = require_exact_keys(
            row,
            EXPECTED_CROSSCHECK_OUTPUT_KEYS,
            "cross-check materialization output",
        )
        require_exact_true(
            row.get("checks"),
            EXPECTED_CROSSCHECK_OUTPUT_CHECKS,
            f"{filename} materializer output",
        )
        require_full_object_sha256(row, f"{filename} materializer output")
        inventory = inventory_by_name[filename]
        require_exact_keys(
            inventory,
            EXPECTED_CROSSCHECK_INVENTORY_KEYS,
            "cross-check destination inventory",
        )
        if (
            row.get("version_id") != inventory.get("version_id")
            or row.get("bytes") != inventory.get("bytes")
            or row.get("sha256") != inventory.get("sha256")
            or row.get("checksums") != inventory.get("checksums")
        ):
            raise ValueError(
                f"cross-check destination inventory differs for {filename}"
            )
    artifacts = pending.get("artifacts")
    reference = pending.get("reference")
    if not isinstance(artifacts, dict) or not isinstance(reference, dict):
        raise ValueError("pending contract omits artifacts or reference")

    for source_role in SOURCE_ROLES:
        row = require_exact_keys(
            source.get(source_role),
            EXPECTED_CROSSCHECK_SOURCE_KEYS,
            f"cross-check source custody {source_role}",
        )
        exact = exact_by_uri.get(str(row.get("uri", "")))
        if (
            exact is None
            or row.get("version_id") != exact.get("version_id")
            or str(row.get("sha256", "")).lower()
            != str(exact.get("sha256", "")).lower()
        ):
            raise ValueError(f"cross-check source {source_role} is not the exact final freeze")
    for source_role, reference_role in REFERENCE_ROLES.items():
        row = require_exact_keys(
            source.get(source_role),
            EXPECTED_CROSSCHECK_SOURCE_KEYS,
            f"cross-check reference custody {source_role}",
        )
        declared = reference.get(reference_role)
        if not isinstance(declared, dict):
            raise ValueError(f"cross-check reference custody omits {source_role}")
        if (
            row.get("uri") != declared.get("uri")
            or row.get("version_id") != declared.get("version_id")
            or str(row.get("sha256", "")).lower()
            != str(declared.get("sha256", "")).lower()
        ):
            raise ValueError(f"cross-check reference {source_role} differs from contract")

    finalized = json.loads(json.dumps(pending))
    finalized_artifacts = finalized["artifacts"]
    bound_outputs: dict[str, dict[str, Any]] = {}
    for artifact_role, filename in FINAL_OUTPUTS.items():
        row = outputs.get(filename)
        pending_blob = finalized_artifacts.get(artifact_role)
        if not isinstance(row, dict) or not isinstance(pending_blob, dict):
            raise ValueError(f"cross-check output custody omits {filename}")
        bound = output_blob(row, str(pending_blob.get("uri", "")), artifact_role)
        finalized_artifacts[artifact_role] = bound
        bound_outputs[artifact_role] = bound

    finalized.setdefault("attestations", {})["final_primary_wgs_artifacts"] = True
    finalized["custody"] = {
        "schema_version": 1,
        "status": "passed",
        "finalizer_script_sha256": require_hex(finalizer_sha256, "finalizer script"),
        "final_freeze_receipt_sha256": require_hex(
            freeze_receipt_sha256, "final freeze receipt"
        ),
        "final_freeze_receipt_uri": freeze_anchor["receipt_uri"],
        "final_freeze_receipt_version_id": freeze_anchor["receipt_version_id"],
        "exact_materialization_receipt_sha256": require_hex(
            exact_materialization_sha256, "exact materialization receipt"
        ),
        "crosscheck_materialization_receipt_sha256": require_hex(
            crosscheck_receipt_sha256, "cross-check materialization receipt"
        ),
        "crosscheck_materialization_receipt_uri": crosscheck_anchor["receipt_uri"],
        "crosscheck_materialization_receipt_version_id": crosscheck_anchor[
            "receipt_version_id"
        ],
        "crosscheck_materializer_script_sha256": require_hex(
            expected_crosscheck_materializer_sha256,
            "cross-check materializer script",
        ),
        "final_primary_artifacts": bound_outputs,
        "checks": dict(EXPECTED_FINALIZED_CUSTODY_CHECKS),
    }
    return finalized


def write_new_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    require_safe_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
            require_installed_contract_output(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_installed_contract_output(path: Path, expected_sha256: str) -> None:
    require_no_symlinked_ancestors(path, "contract output")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"contract output changed during write: {path}")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"contract output mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"contract output changed during write: {path}")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_safe_output_parent(path: Path) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"contract output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending-contract", required=True, type=Path)
    parser.add_argument("--final-freeze-receipt", required=True, type=Path)
    parser.add_argument("--final-freeze-anchor", required=True, type=Path)
    parser.add_argument("--exact-materialization-receipt", required=True, type=Path)
    parser.add_argument("--crosscheck-materialization-receipt", required=True, type=Path)
    parser.add_argument("--crosscheck-materialization-anchor", required=True, type=Path)
    parser.add_argument("--expected-crosscheck-materializer-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    freeze, freeze_anchor = validate_anchor(
        args.final_freeze_receipt,
        args.final_freeze_anchor,
        "final freeze",
        EXPECTED_FINAL_FREEZE_ANCHOR_CHECKS,
    )
    crosscheck, crosscheck_anchor = validate_anchor(
        args.crosscheck_materialization_receipt,
        args.crosscheck_materialization_anchor,
        "cross-check materialization",
        EXPECTED_CROSSCHECK_ANCHOR_CHECKS,
    )
    result = finalize(
        load_object(args.pending_contract, "pending contract"),
        freeze,
        freeze_anchor,
        load_object(args.exact_materialization_receipt, "exact materialization"),
        crosscheck,
        crosscheck_anchor,
        freeze_receipt_sha256=sha256(args.final_freeze_receipt),
        exact_materialization_sha256=sha256(args.exact_materialization_receipt),
        crosscheck_receipt_sha256=sha256(args.crosscheck_materialization_receipt),
        finalizer_sha256=sha256(Path(__file__)),
        expected_crosscheck_materializer_sha256=(
            args.expected_crosscheck_materializer_sha256
        ),
    )
    write_new_json(args.output, result)
    print(json.dumps({"status": "passed", "contract": str(args.output), "sha256": sha256(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
