#!/usr/bin/env python3
"""Wrap one validated independent AI review in the shared report contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from build_ai_review_bundle import (
    BUNDLE_EVIDENCE_SOURCE_KEYS,
    BUNDLE_MANIFEST_KEYS,
    BUNDLE_REVIEW_BUNDLE_KEYS,
    DuplicateJsonKeyError,
    is_exact_int,
    require_bundle_manifest,
    reject_duplicate_json_object_names,
    validate_report_manifest_support,
)
from validate_ai_review import (
    CLAIMS_FIELDS,
    REVIEW_MANIFEST_KEYS,
    VALIDATION_KEYS,
    require_exact_review_invocation,
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
REVIEW_SUMMARY_KEYS = {
    "overall",
    "reviewer_id",
    "model",
    "invocation_id",
    "required_method_ids",
    "method_inventory",
    "method_inventory_sha256",
    "claim_count",
    "covered_evidence_ids",
    "disagreement_claim_count",
    "limitations",
}
REVIEW_SUMMARY_MODEL_KEYS = {
    "catalog_verified_at",
    "latest_available_attested",
    "model_id",
    "provider",
}


def sha256(path: Path) -> str:
    return read_stable_file_with_sha256(
        path,
        f"{path.name} SHA-256 input",
    )[1]


def load_object(path: Path, label: str) -> dict[str, Any]:
    value, _ = load_object_with_sha256(path, label)
    return value


def load_object_with_sha256(path: Path, label: str) -> tuple[dict[str, Any], str]:
    path = resolve_real_file(path, label)
    data, digest = read_stable_file_with_sha256(path, label)
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, digest


def read_stable_file_with_sha256(path: Path, label: str) -> tuple[bytes, str]:
    data, identity = read_real_hash_input_once(path, label)
    digest = hashlib.sha256(data).hexdigest()
    stable_data, stable_identity = read_real_hash_input_once(path, label)
    if (
        not data
        or stable_identity != identity
        or hashlib.sha256(stable_data).hexdigest() != digest
    ):
        raise ValueError(f"{label} changed during read: {path}")
    return data, digest


def read_real_hash_input_once(
    path: Path,
    label: str,
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    require_real_hash_input(path)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{label} must be a real file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read()
            after_read = os.fstat(handle.fileno())
        current = path.lstat()
    except OSError as error:
        raise ValueError(f"{label} changed during read: {path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    require_no_symlinked_ancestors(path, label)
    if not os.path.samestat(opened, after_read) or not os.path.samestat(
        after_read,
        current,
    ):
        raise ValueError(f"{label} changed during read: {path}")
    return data, stat_identity(opened)


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_stable_text_with_sha256(path: Path, label: str) -> tuple[str, str]:
    data, digest = read_stable_file_with_sha256(path, label)
    try:
        return data.decode("utf-8"), digest
    except UnicodeError as error:
        raise ValueError(f"invalid UTF-8 in {label}") from error


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


def require_real_hash_input(path: Path) -> None:
    label = f"{path.name} SHA-256 input"
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


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


def require_exact_review_summary(
    manifest: Mapping[str, Any],
    reviewer: str,
) -> None:
    summary = manifest.get("review_summary")
    if not isinstance(summary, dict) or set(summary) != REVIEW_SUMMARY_KEYS:
        raise ValueError("AI review summary envelope is not exact")
    if summary.get("overall") != {
        "evidence_status": manifest.get("evidence_status"),
        "authorized_hrd_state": manifest.get("authorized_hrd_state"),
        "classification_authorization": "none",
    }:
        raise ValueError("AI review overall summary is stale")
    if (
        summary.get("reviewer_id") != reviewer
        or not require_exact_summary_string(summary.get("invocation_id"))
    ):
        raise ValueError("AI review summary reviewer binding is not exact")
    require_exact_review_model_summary(summary.get("model"))
    inventory_id = require_inventory_binding(
        summary.get("method_inventory"),
        summary.get("method_inventory_sha256"),
        "AI review summary method inventory",
        None,
    )
    require_pinned_methods(
        summary.get("required_method_ids", ()),
        "AI review summary method inventory",
        inventory_id,
    )
    claim_count = summary.get("claim_count")
    covered_evidence_ids = summary.get("covered_evidence_ids")
    disagreement_claim_count = summary.get("disagreement_claim_count")
    limitations = summary.get("limitations")
    if (
        not is_positive_exact_int(claim_count)
        or not isinstance(covered_evidence_ids, list)
        or not covered_evidence_ids
        or any(
            not require_exact_summary_string(evidence_id)
            for evidence_id in covered_evidence_ids
        )
        or covered_evidence_ids != sorted(covered_evidence_ids)
        or len(set(covered_evidence_ids)) != len(covered_evidence_ids)
        or not is_nonnegative_exact_int(disagreement_claim_count)
        or disagreement_claim_count > claim_count
        or not isinstance(limitations, list)
        or not limitations
        or any(
            not require_exact_summary_string(limitation)
            for limitation in limitations
        )
    ):
        raise ValueError("AI review summary counts are not exact")


def require_exact_summary_string(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return ""
    return value


def require_exact_review_model_summary(model: Any) -> None:
    provider = model.get("provider") if isinstance(model, dict) else None
    model_id = model.get("model_id") if isinstance(model, dict) else None
    catalog_verified_at = (
        model.get("catalog_verified_at") if isinstance(model, dict) else None
    )
    if (
        not isinstance(model, dict)
        or set(model) != REVIEW_SUMMARY_MODEL_KEYS
        or not require_exact_summary_string(provider)
        or not require_exact_summary_string(model_id)
        or not require_exact_summary_string(catalog_verified_at)
        or model.get("latest_available_attested") is not True
    ):
        raise ValueError("AI review summary model is not exact")
    try:
        verified_at = datetime.fromisoformat(catalog_verified_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("AI review summary model is not exact") from error
    if verified_at.tzinfo is None:
        raise ValueError("AI review summary model is not exact")


def is_nonnegative_exact_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def is_positive_exact_int(value: Any) -> bool:
    return type(value) is int and value > 0


def split_semicolon(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def validated_claim_summary(
    claims_path: Path,
    evidence_sources: Sequence[Any],
) -> tuple[dict[str, Any], str]:
    evidence_ids = []
    for row in evidence_sources:
        if not isinstance(row, dict):
            raise ValueError("review bundle evidence source is malformed")
        if set(row) != BUNDLE_EVIDENCE_SOURCE_KEYS:
            raise ValueError("review bundle evidence source envelope is not exact")
        if not isinstance(row.get("evidence_id"), str):
            raise ValueError("review bundle evidence IDs are not exact")
        evidence_ids.append(row["evidence_id"])
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("review bundle evidence IDs are not exact")

    claims_text, claims_hash = read_stable_text_with_sha256(
        claims_path,
        "claims.csv",
    )
    handle = io.StringIO(claims_text, newline="")
    reader = csv.DictReader(handle)
    if reader.fieldnames != CLAIMS_FIELDS:
        raise ValueError("claims.csv header does not match the required schema")
    claims = list(reader)
    if not claims:
        raise ValueError("claims.csv contains no claims")
    if any(
        None in row or any(not isinstance(row.get(field), str) for field in CLAIMS_FIELDS)
        for row in claims
    ):
        raise ValueError("claims.csv row does not match the required schema")

    covered = sorted(
        {
            evidence_id
            for row in claims
            for evidence_id in split_semicolon(row["evidence_ids"])
        }
    )
    if covered != sorted(evidence_ids):
        raise ValueError("claims do not preserve every evidence source and state")

    return (
        {
            "claim_count": len(claims),
            "covered_evidence_ids": covered,
            "disagreement_claim_count": sum(
                row["disagreement_status"].strip() != "none" for row in claims
            ),
        },
        claims_hash,
    )


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
    review_manifest, review_manifest_hash = load_object_with_sha256(
        review_manifest_path,
        "review manifest",
    )
    validation, validation_hash = load_object_with_sha256(
        validation_path,
        "validation",
    )
    bundle, bundle_hash = load_object_with_sha256(bundle_path, "review bundle")
    bundle_manifest, bundle_manifest_hash = load_object_with_sha256(
        bundle_manifest_path,
        "bundle manifest",
    )
    catalog, catalog_hash = load_object_with_sha256(
        model_catalog_receipt,
        "model catalog receipt",
    )
    if set(review_manifest) != REVIEW_MANIFEST_KEYS:
        raise ValueError("review manifest envelope is not exact")
    if set(validation) != VALIDATION_KEYS:
        raise ValueError("validation envelope is not exact")
    if set(bundle) != BUNDLE_REVIEW_BUNDLE_KEYS:
        raise ValueError("AI review bundle envelope is not exact")
    if set(bundle_manifest) != BUNDLE_MANIFEST_KEYS:
        raise ValueError("AI review bundle manifest envelope is not exact")
    if not is_exact_int(
        review_manifest.get("schema_version"),
        2,
    ) or not is_exact_int(validation.get("schema_version"), 2):
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

    prompt_hash = sha256(prompt_path)
    expected_inputs = {
        "review_bundle.json": bundle_hash,
        prompt_path.name: prompt_hash,
    }
    if review_manifest.get("input_artifact_sha256") != expected_inputs:
        raise ValueError("review input inventory is not exact")
    if not (
        review_manifest.get("input_bundle_sha256") == bundle_hash
        and validation.get("review_bundle_sha256") == bundle_hash
        and validation.get("bundle_manifest_sha256") == bundle_manifest_hash
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
        and is_exact_int(catalog.get("schema_version"), 1)
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
    claim_count = validation.get("claim_count")
    disagreement_claim_count = validation.get("disagreement_claim_count")
    forbidden_token_count = validation.get("forbidden_token_count")
    if (
        not is_positive_exact_int(claim_count)
        or not is_nonnegative_exact_int(disagreement_claim_count)
        or disagreement_claim_count > claim_count
    ):
        raise ValueError("review validation counts are not exact")
    if not is_positive_exact_int(forbidden_token_count):
        raise ValueError("review validation forbidden-token count is not exact")
    evidence_sources = bundle.get("evidence_sources")
    if not isinstance(evidence_sources, list) or not evidence_sources:
        raise ValueError("review bundle has no evidence sources")
    expected_claim_summary, claims_hash = validated_claim_summary(
        claims_path,
        evidence_sources,
    )
    report_hash = sha256(report_path)
    source_sha256 = {
        "bundle_manifest.json": bundle_manifest_hash,
        "claims.csv": claims_hash,
        "model_catalog_receipt.json": catalog_hash,
        prompt_path.name: prompt_hash,
        "review_bundle.json": bundle_hash,
        "review_manifest.json": review_manifest_hash,
        "validation.json": validation_hash,
    }
    expected_outputs = {"report.md": report_hash, "claims.csv": claims_hash}
    if review_manifest.get("output_sha256") != expected_outputs:
        raise ValueError("review output hashes differ from review_manifest.json")
    if not (
        validation.get("report_sha256") == report_hash
        and validation.get("claims_sha256") == claims_hash
        and validation.get("review_manifest_sha256") == review_manifest_hash
    ):
        raise ValueError("validation output hashes differ from the review files")

    if any(
        validation.get(key) != expected
        for key, expected in expected_claim_summary.items()
    ):
        raise ValueError("review validation claim summary is stale")
    invocation = require_exact_review_invocation(review_manifest.get("invocation", {}))

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
            "validation.json": validation_hash,
        },
        "source_sha256": source_sha256,
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
            **expected_claim_summary,
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
        require_exact_review_summary(manifest, reviewer)
        require_installed_manifest(output, manifest_sha256)
    except ValueError:
        output.unlink(missing_ok=True)
        raise
    except OSError as error:
        output.unlink(missing_ok=True)
        raise ValueError("AI review final manifest support changed during write") from error
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
