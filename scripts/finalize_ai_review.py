#!/usr/bin/env python3
"""Wrap one validated independent AI review in the shared report contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from build_ai_review_bundle import (
    require_bundle_manifest,
    validate_report_manifest_support,
)
from hrd_report_inventory import (
    inventory_payload,
    inventory_sha256,
    require_inventory_binding,
    require_pinned_methods,
)

REVIEWER_METHODS = {
    "A": "ai_review_reviewer_a",
    "B": "ai_review_reviewer_b",
}
REQUIRED_ATTESTATION = {
    "other_reviewer_outputs_received": False,
    "other_reviewer_context_received": False,
    "external_research_used": False,
    "raw_inputs_received": False,
    "isolated_session": True,
    "input_directory_contained_only_declared_artifacts": True,
}
HRD_STATES = {"no_call", "positive", "negative"}
REVIEW_PACKET_INPUT_FILES = {
    "claims.csv",
    "report.md",
    "review_manifest.json",
    "validation.json",
}
REVIEW_PACKET_FILES = REVIEW_PACKET_INPUT_FILES | {"report_manifest.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def require_file(path: Path, label: str) -> None:
    require_no_symlinked_ancestors(path, label)
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a non-empty real file")


def resolve_real_dir(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} is missing or a symlink")
    return path.resolve()


def resolve_real_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a non-empty real file")
    return path.resolve()


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_exact_review_dir(review_dir: Path, expected: set[str]) -> None:
    require_no_symlinked_ancestors(review_dir, "review directory")
    if review_dir.is_symlink() or not review_dir.is_dir():
        raise ValueError("review directory is missing or a symlink")

    observed = {path.name for path in review_dir.iterdir()}
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        details = []
        if missing:
            details.append("missing " + ",".join(missing))
        if unexpected:
            details.append("unexpected " + ",".join(unexpected))
        raise ValueError(
            "review directory inventory is not exact: " + "; ".join(details)
        )

    invalid = sorted(
        path.name
        for path in review_dir.iterdir()
        if path.is_symlink() or not path.is_file()
    )
    if invalid:
        raise ValueError("review directory contains invalid paths: " + ",".join(invalid))


def review_source_paths(
    bundle_dir: Path,
    review_dir: Path,
    reviewer: str,
    model_catalog_receipt: Path,
) -> dict[str, Path]:
    if reviewer not in REVIEWER_METHODS:
        raise ValueError("reviewer must be A or B")
    return {
        "report.md": review_dir / "report.md",
        "claims.csv": review_dir / "claims.csv",
        "review_manifest.json": review_dir / "review_manifest.json",
        "validation.json": review_dir / "validation.json",
        "review_bundle.json": bundle_dir / "review_bundle.json",
        "bundle_manifest.json": bundle_dir / "bundle_manifest.json",
        f"reviewer-{reviewer.lower()}.prompt.md": (
            bundle_dir / f"reviewer-{reviewer.lower()}.prompt.md"
        ),
        "model_catalog_receipt.json": model_catalog_receipt,
    }


def expected_source_sha256(paths: Mapping[str, Path]) -> dict[str, str]:
    hashes = {}
    for name, path in sorted(paths.items()):
        require_file(path, name)
        if name != "report.md":
            hashes[name] = sha256(path)
    return hashes


def require_exact_source_sha256(
    paths: Mapping[str, Path],
    manifest: Mapping[str, Any],
) -> None:
    if manifest.get("source_sha256") != expected_source_sha256(paths):
        raise ValueError("AI review source hashes are not exact")


def build_manifest(
    bundle_dir: Path,
    review_dir: Path,
    reviewer: str,
    model_catalog_receipt: Path,
) -> dict[str, Any]:
    paths = review_source_paths(
        bundle_dir,
        review_dir,
        reviewer,
        model_catalog_receipt,
    )
    for name, path in paths.items():
        require_file(path, name)
    require_bundle_manifest(bundle_dir)

    report_path = paths["report.md"]
    claims_path = paths["claims.csv"]
    review_manifest_path = paths["review_manifest.json"]
    validation_path = paths["validation.json"]
    bundle_path = paths["review_bundle.json"]
    bundle_manifest_path = paths["bundle_manifest.json"]
    prompt_path = paths[f"reviewer-{reviewer.lower()}.prompt.md"]
    review_manifest = load_object(review_manifest_path, "review manifest")
    validation = load_object(validation_path, "validation")
    bundle = load_object(bundle_path, "review bundle")
    bundle_manifest = load_object(bundle_manifest_path, "bundle manifest")
    catalog = load_object(model_catalog_receipt, "model catalog receipt")
    if review_manifest.get("schema_version") != 2 or validation.get("schema_version") != 2:
        raise ValueError("review and validation schemas must both be version 2")
    if validation.get("status") != "passed":
        raise ValueError("review validation is not passed")
    if (
        review_manifest.get("reviewer_id") != reviewer
        or validation.get("reviewer_id") != reviewer
    ):
        raise ValueError("reviewer identity mismatch")
    if (
        bundle.get("subject_alias") != review_manifest.get("subject_alias")
        or bundle_manifest.get("subject_alias") != bundle.get("subject_alias")
    ):
        raise ValueError("subject alias differs across artifacts")

    report_hash = sha256(report_path)
    claims_hash = sha256(claims_path)
    review_manifest_hash = sha256(review_manifest_path)
    bundle_hash = sha256(bundle_path)
    prompt_hash = sha256(prompt_path)
    catalog_hash = sha256(model_catalog_receipt)
    expected_outputs = {"report.md": report_hash, "claims.csv": claims_hash}
    if review_manifest.get("output_sha256") != expected_outputs:
        raise ValueError("review output hashes differ from review_manifest.json")
    if not (
        validation.get("report_sha256") == report_hash
        and validation.get("claims_sha256") == claims_hash
        and validation.get("review_manifest_sha256") == review_manifest_hash
    ):
        raise ValueError("validation output hashes differ from the review files")

    expected_inputs = {
        "review_bundle.json": bundle_hash,
        prompt_path.name: prompt_hash,
    }
    if review_manifest.get("input_artifact_sha256") != expected_inputs:
        raise ValueError("review input inventory is not exact")
    if not (
        review_manifest.get("input_bundle_sha256") == bundle_hash
        and validation.get("review_bundle_sha256") == bundle_hash
        and bundle_manifest.get("review_bundle_sha256") == bundle_hash
        and review_manifest.get("prompt_sha256") == prompt_hash
        and validation.get("prompt_sha256") == prompt_hash
        and (bundle_manifest.get("prompt_sha256") or {}).get(reviewer) == prompt_hash
    ):
        raise ValueError("bundle or prompt hash binding failed")
    if not (
        review_manifest.get("model")
        == validation.get("model")
        == (bundle_manifest.get("model_execution_contracts") or {}).get(reviewer)
    ):
        raise ValueError("pinned model contract differs across artifacts")
    if not (
        validation.get("model_catalog_receipt_sha256") == catalog_hash
        and bundle.get("model_catalog_receipt_sha256") == catalog_hash
        and bundle_manifest.get("model_catalog_receipt_sha256") == catalog_hash
        and catalog.get("schema_version") == 1
    ):
        raise ValueError("model catalog receipt binding failed")

    required_methods = bundle.get("required_method_ids")
    if not isinstance(required_methods, list) or not required_methods:
        raise ValueError("required method inventory is missing")
    inventory_id = require_inventory_binding(
        bundle.get("method_inventory"),
        bundle.get("method_inventory_sha256"),
        "review bundle method inventory binding",
        None,
    )
    require_pinned_methods(
        required_methods,
        "review bundle method inventory",
        inventory_id,
    )
    require_inventory_binding(
        bundle_manifest.get("method_inventory"),
        bundle_manifest.get("method_inventory_sha256"),
        "bundle manifest method inventory binding",
        inventory_id,
    )
    require_inventory_binding(
        validation.get("method_inventory"),
        validation.get("method_inventory_sha256"),
        "review validation method inventory binding",
        inventory_id,
    )
    if bundle.get("method_inventory_sha256") != bundle_manifest.get(
        "method_inventory_sha256"
    ):
        raise ValueError("bundle method inventory hashes disagree")
    if not (
        validation.get("required_method_ids") == required_methods
        and bundle_manifest.get("required_method_ids") == required_methods
    ):
        raise ValueError("required method inventory differs across artifacts")
    if not (
        review_manifest.get("method_inventory_sha256") == inventory_sha256(inventory_id)
    ):
        raise ValueError("review method inventory binding is missing or altered")

    authorized_state = bundle.get("authorized_hrd_state")
    if authorized_state not in HRD_STATES or not (
        validation.get("authorized_hrd_state") == authorized_state
        and bundle_manifest.get("authorized_hrd_state") == authorized_state
    ):
        raise ValueError("authorized HRD state differs across artifacts")
    if authorized_state != "no_call":
        raise ValueError(
            "narrative AI review wrapper cannot publish a categorical HRD classification"
        )
    if review_manifest.get("independence_attestation") != REQUIRED_ATTESTATION:
        raise ValueError("independence attestation is missing or altered")
    evidence_sources = bundle.get("evidence_sources")
    if not isinstance(evidence_sources, list) or not evidence_sources:
        raise ValueError("review bundle has no evidence sources")
    invocation = review_manifest.get("invocation")
    if not isinstance(invocation, dict) or not invocation.get("invocation_id"):
        raise ValueError("review invocation metadata is incomplete")

    return {
        "schema_version": 1,
        "method_id": REVIEWER_METHODS[reviewer],
        "report_kind": "independent_ai_hrd_evidence_review",
        "evidence_status": "partial_evidence",
        "authorized_hrd_state": authorized_state,
        "classification_authorized": False,
        "classification_qc_status": "not_applicable",
        "report_sha256": report_hash,
        "support_sha256": {
            "claims.csv": claims_hash,
            "review_manifest.json": review_manifest_hash,
            "validation.json": sha256(validation_path),
        },
        "source_sha256": expected_source_sha256(paths),
        "review_summary": {
            "overall": {
                "evidence_status": "partial_evidence",
                "authorized_hrd_state": authorized_state,
                "classification_authorization": "none",
            },
            "reviewer_id": reviewer,
            "model": review_manifest["model"],
            "invocation_id": invocation["invocation_id"],
            "required_method_ids": required_methods,
            "method_inventory": inventory_payload(inventory_id),
            "method_inventory_sha256": inventory_sha256(inventory_id),
            "claim_count": validation.get("claim_count"),
            "covered_evidence_ids": validation.get("covered_evidence_ids"),
            "disagreement_claim_count": validation.get("disagreement_claim_count"),
            "limitations": [
                "Narrative AI cross-check only; not an HRD algorithm or clinical interpretation.",
                "The review cannot promote the deterministic authorization ceiling.",
                "Raw sequencing inputs and external research were excluded from the reviewer session.",
            ],
        },
    }


def write_create_only(path: Path, value: dict[str, Any]) -> str:
    require_safe_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    expected_sha256 = hashlib.sha256(data).hexdigest()
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise ValueError("report_manifest.json already exists") from error

    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        require_installed_manifest(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return expected_sha256


def require_installed_manifest(path: Path, expected_sha256: str) -> None:
    require_no_symlinked_ancestors(path, "report_manifest.json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("report_manifest.json changed during write")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError("report_manifest.json changed during write")
    if sha256(path) != expected_sha256:
        raise ValueError("report_manifest.json changed during write")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_safe_parent(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("report_manifest.json already exists")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"output path may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def finalize(
    bundle_dir: Path,
    review_dir: Path,
    reviewer: str,
    model_catalog_receipt: Path,
    requested_output: Path,
) -> Path:
    bundle_dir = resolve_real_dir(bundle_dir, "bundle directory")
    review_dir = resolve_real_dir(review_dir, "review directory")
    model_catalog_receipt = resolve_real_file(
        model_catalog_receipt,
        "model catalog receipt",
    )
    require_safe_parent(requested_output)
    output = review_dir / "report_manifest.json"
    if requested_output.parent.resolve() / requested_output.name != output:
        raise ValueError(
            "output must be report_manifest.json in the review directory"
        )
    if output.exists() or output.is_symlink():
        raise ValueError("report_manifest.json already exists")

    require_exact_review_dir(review_dir, REVIEW_PACKET_INPUT_FILES)
    manifest = build_manifest(
        bundle_dir,
        review_dir,
        reviewer,
        model_catalog_receipt,
    )
    manifest_sha256 = write_create_only(output, manifest)
    try:
        source_paths = review_source_paths(
            bundle_dir,
            review_dir,
            reviewer,
            model_catalog_receipt,
        )
        require_exact_review_dir(review_dir, REVIEW_PACKET_FILES)
        validate_report_manifest_support(
            review_dir,
            manifest,
            REVIEWER_METHODS[reviewer],
        )
        require_exact_source_sha256(source_paths, manifest)
        require_installed_manifest(output, manifest_sha256)
    except ValueError:
        output.unlink(missing_ok=True)
        raise
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--reviewer", required=True, choices=("A", "B"))
    parser.add_argument("--model-catalog-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        output = finalize(
            args.bundle_dir,
            args.review_dir,
            args.reviewer,
            args.model_catalog_receipt,
            args.output,
        )
    except (ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    print(f"Finalized schema-1 AI review report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
