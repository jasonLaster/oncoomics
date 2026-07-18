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


def validate_anchor(
    receipt_path: Path, anchor_path: Path, label: str
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
    require_all_true(anchor.get("checks"), f"{label} anchor")
    return receipt, anchor


def validate_freeze(
    receipt: dict[str, Any], anchor: dict[str, Any], receipt_sha256: str
) -> dict[str, dict[str, Any]]:
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
    require_all_true(checks, "final artifact freeze")
    if anchor.get("receipt_sha256") != receipt_sha256:
        raise ValueError("final freeze anchor hash changed after validation")
    by_uri: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "passed":
            raise ValueError("final artifact freeze contains a non-passed row")
        require_all_true(row.get("checks"), "final artifact freeze row")
        destination = row.get("destination")
        if not isinstance(destination, dict):
            raise ValueError("final artifact freeze row lacks a destination")
        uri = f"s3://{destination.get('bucket', '')}/{destination.get('key', '')}"
        if not uri.startswith("s3://diana-omics-private-results-"):
            raise ValueError("final artifact freeze destination is not private")
        require_version(destination.get("version_id"), "frozen destination")
        if uri in by_uri:
            raise ValueError("duplicate final artifact freeze destination URI")
        by_uri[uri] = destination
    return by_uri


def validate_exact_materialization(
    receipt: dict[str, Any], freeze_sha256: str, freeze_by_uri: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
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
        if not isinstance(row, dict):
            raise ValueError("exact-version materialization contains a malformed row")
        require_all_true(row.get("checks"), "exact-version materialization row")
        uri = f"s3://{row.get('bucket', '')}/{row.get('key', '')}"
        frozen = freeze_by_uri.get(uri)
        if (
            frozen is None
            or row.get("version_id") != frozen.get("version_id")
            or int(row.get("bytes", -1)) != int(frozen.get("bytes", -2))
            or row.get("checksums") != frozen.get("checksums")
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
    return {
        "uri": expected_uri,
        "version_id": require_version(row.get("version_id"), label),
        "sha256": require_hex(row.get("sha256"), label),
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
    require_all_true(crosscheck_receipt.get("checks"), "cross-check materialization")
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
        inventory = inventory_by_name[filename]
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
        row = source.get(source_role)
        if not isinstance(row, dict):
            raise ValueError(f"cross-check source custody omits {source_role}")
        exact = exact_by_uri.get(str(row.get("uri", "")))
        if (
            exact is None
            or row.get("version_id") != exact.get("version_id")
            or str(row.get("sha256", "")).lower()
            != str(exact.get("sha256", "")).lower()
        ):
            raise ValueError(f"cross-check source {source_role} is not the exact final freeze")
    for source_role, reference_role in REFERENCE_ROLES.items():
        row = source.get(source_role)
        declared = reference.get(reference_role)
        if not isinstance(row, dict) or not isinstance(declared, dict):
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
        "checks": {
            "successful_execution_freeze_bound": True,
            "full_freeze_exactly_materialized": True,
            "crosscheck_sources_match_exact_freeze": True,
            "alias_only_outputs_have_single_create_only_versions": True,
            "sbs96_independently_rederived_from_final_pass_vcf": True,
        },
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
        args.final_freeze_receipt, args.final_freeze_anchor, "final freeze"
    )
    crosscheck, crosscheck_anchor = validate_anchor(
        args.crosscheck_materialization_receipt,
        args.crosscheck_materialization_anchor,
        "cross-check materialization",
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
