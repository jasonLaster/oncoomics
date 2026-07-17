#!/usr/bin/env python3
"""Wrap one validated independent AI review in the shared report contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

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
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a non-empty real file")


def build_manifest(
    bundle_dir: Path,
    review_dir: Path,
    reviewer: str,
    model_catalog_receipt: Path,
) -> dict[str, Any]:
    if reviewer not in REVIEWER_METHODS:
        raise ValueError("reviewer must be A or B")

    report_path = review_dir / "report.md"
    claims_path = review_dir / "claims.csv"
    review_manifest_path = review_dir / "review_manifest.json"
    validation_path = review_dir / "validation.json"
    bundle_path = bundle_dir / "review_bundle.json"
    bundle_manifest_path = bundle_dir / "bundle_manifest.json"
    prompt_path = bundle_dir / f"reviewer-{reviewer.lower()}.prompt.md"
    paths = {
        "report.md": report_path,
        "claims.csv": claims_path,
        "review_manifest.json": review_manifest_path,
        "validation.json": validation_path,
        "review_bundle.json": bundle_path,
        "bundle_manifest.json": bundle_manifest_path,
        prompt_path.name: prompt_path,
        "model_catalog_receipt.json": model_catalog_receipt,
    }
    for name, path in paths.items():
        require_file(path, name)

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
    require_pinned_methods(required_methods, "review bundle method inventory")
    require_inventory_binding(
        bundle.get("method_inventory"),
        bundle.get("method_inventory_sha256"),
        "review bundle method inventory binding",
    )
    require_inventory_binding(
        bundle_manifest.get("method_inventory"),
        bundle_manifest.get("method_inventory_sha256"),
        "bundle manifest method inventory binding",
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
        review_manifest.get("method_inventory_sha256") == inventory_sha256()
        and validation.get("method_inventory_sha256") == inventory_sha256()
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
        "source_sha256": {
            name: sha256(path)
            for name, path in sorted(paths.items())
            if name != "report.md"
        },
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
            "method_inventory": inventory_payload(),
            "method_inventory_sha256": inventory_sha256(),
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


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--reviewer", required=True, choices=("A", "B"))
    parser.add_argument("--model-catalog-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    args.output.unlink(missing_ok=True)
    review_dir = args.review_dir.resolve()
    output = args.output.resolve()
    if output != review_dir / "report_manifest.json":
        raise SystemExit(
            "Fail-closed: output must be report_manifest.json in the review directory"
        )
    try:
        manifest = build_manifest(
            args.bundle_dir.resolve(),
            review_dir,
            args.reviewer,
            args.model_catalog_receipt.resolve(),
        )
    except (ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    write_atomic(output, manifest)
    print(f"Finalized schema-1 AI review report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
