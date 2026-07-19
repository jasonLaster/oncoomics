#!/usr/bin/env python3
"""Generate a fail-closed comparative HRD synthesis from frozen reports.

The synthesis is deliberately offline. It consumes only de-identified,
hash-bound report manifests plus two independently validated AI-review
outputs; it never invokes a model, reads raw sequencing data, or contacts AWS.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from build_ai_review_bundle import (
    BUNDLE_MANIFEST_KEYS,
    BUNDLE_REVIEW_BUNDLE_KEYS,
    is_exact_int,
    validate_report_manifest_support,
)
from forbidden_text import has_unauthorized_hrd_classification
from hrd_report_inventory import (
    inventory_payload,
    inventory_sha256,
    require_inventory_binding,
    require_pinned_methods,
    required_method_ids,
)
from validate_ai_review import (
    REVIEW_INVOCATION_KEYS,
    REVIEW_MANIFEST_KEYS,
    VALIDATION_KEYS,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
METHOD_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")
EVIDENCE_ID = re.compile(r"^E[0-9]{3,}$")
CLAIM_ID = re.compile(r"^C[0-9]{3,}$")
SUBJECT_ALIAS = re.compile(r"^subject[0-9]{2,4}$")
SOURCE_ARTIFACT_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
RESERVED_JSON_OBJECT_NAMES = {"false", "null", "true"}
ALLOWED_EVIDENCE_STATES = {"ready", "partial_evidence", "no_call", "blocked"}
ALLOWED_HRD_STATES = {"no_call", "positive", "negative"}
ALLOWED_QC_STATES = {"passed", "failed", "not_applicable", "blocked", "not_run"}
ALLOWED_DISAGREEMENTS = {
    "none",
    "method_conflict",
    "insufficient_comparability",
    "missing_evidence",
}
ALLOWED_AGREEMENT_STATUSES = {"concordant", "discordant", "partial_agreement"}
ALLOWED_STRUCTURED_DISAGREEMENT_TYPES = {
    "method_conflict",
    "insufficient_comparability",
    "missing_evidence",
    "reviewer_disagreement_assessment_difference",
    "reviewer_disposition_difference",
    "reviewer_state_difference",
    "source_not_comparable",
    "source_partial_evidence",
}
REQUIRED_SYNTHESIS_PROCESS = {
    "ordered_source_manifests_verified": True,
    "source_reports_verified": True,
    "ai_bundle_and_manifest_verified": True,
    "reviewer_outputs_unchanged_after_validation": True,
    "distinct_models_verified": True,
    "distinct_invocations_verified": True,
    "same_ai_bundle_verified": True,
    "raw_inputs_used": False,
    "external_research_used": False,
}
CLAIMS_FIELDS = [
    "claim_id",
    "claim",
    "evidence_ids",
    "source_methods",
    "evidence_states",
    "support_level",
    "caveat",
    "disposition",
    "proposed_hrd_state",
    "quantitative_fact_ids",
    "disagreement_status",
    "disagreement_evidence_ids",
    "resolution_needed",
]
AGREEMENT_FIELDS = [
    "comparison_id",
    "evidence_id",
    "method_id",
    "report_kind",
    "source_evidence_status",
    "source_authorized_hrd_state",
    "reviewer_a_claim_ids",
    "reviewer_b_claim_ids",
    "reviewer_a_proposed_states",
    "reviewer_b_proposed_states",
    "reviewer_a_dispositions",
    "reviewer_b_dispositions",
    "reviewer_a_disagreement_statuses",
    "reviewer_b_disagreement_statuses",
    "agreement_status",
    "structured_disagreement_types",
    "resolution_needed",
]
REQUIRED_POLICY = {
    "raw_inputs_prohibited": True,
    "external_research_prohibited": True,
    "reviewers_independent": True,
    "other_reviewer_outputs_prohibited": True,
    "numerical_results_immutable": True,
    "classification_may_not_exceed_authorized_state": True,
}
REQUIRED_ATTESTATION = {
    "other_reviewer_outputs_received": False,
    "other_reviewer_context_received": False,
    "external_research_used": False,
    "raw_inputs_received": False,
    "isolated_session": True,
    "input_directory_contained_only_declared_artifacts": True,
}
REVIEW_FILES = {"validation.json", "review_manifest.json", "report.md", "claims.csv"}
OUTPUT_FILES = {"report.md", "agreement_disagreement.csv", "report_manifest.json"}
REPORT_MANIFEST_KEYS = {
    "schema_version",
    "report_kind",
    "method_id",
    "generated_at",
    "subject_alias",
    "evidence_status",
    "interpretation_status",
    "authorized_hrd_state",
    "classification_authorized",
    "classification_authorization",
    "classification_qc_status",
    "report_sha256",
    "agreement_disagreement_sha256",
    "support_sha256",
    "source_sha256",
    "review_summary",
}


class DuplicateJsonKeyError(ValueError):
    pass


def reject_duplicate_json_object_names(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise DuplicateJsonKeyError(key)
        parsed[key] = value
    return parsed


def sha256(path: Path) -> str:
    path = require_real_nonempty_file(path, f"{path.name} SHA-256 input")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_object(path: Path, label: str) -> Dict[str, Any]:
    require_real_nonempty_file(path, label)
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError("duplicate JSON object name in " + label + ": " + str(error)) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON in " + label) from error
    if not isinstance(value, dict):
        raise ValueError(label + " must be a JSON object")
    return value


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_nonempty_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError("missing or unsafe " + label)
    return path


def require_real_directory(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if not path.is_dir() or path.is_symlink():
        raise ValueError(label + " directory is missing or unsafe")
    return path


def checked_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError("malformed SHA-256 for " + label)
    return value


def checked_source_artifact_id(value: Any, method: str) -> str:
    if (
        not isinstance(value, str)
        or not SOURCE_ARTIFACT_ID.fullmatch(value)
        or value in RESERVED_JSON_OBJECT_NAMES
    ):
        raise ValueError("malformed source-artifact ID for " + method)
    return value


def is_nonnegative_exact_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def is_positive_exact_int(value: Any) -> bool:
    return type(value) is int and value > 0


def require_exact_csv_row(
    row: Dict[str, Any],
    fields: Sequence[str],
    label: str,
) -> Dict[str, str]:
    if None in row or any(not isinstance(row.get(field), str) for field in fields):
        raise ValueError(label + " contains a malformed row")
    for field in fields:
        value = row[field]
        if (
            value != value.strip()
            or "\n" in value
            or "\r" in value
            or "\0" in value
        ):
            raise ValueError(label + " contains a non-exact field: " + field)
    return {field: row[field] for field in fields}


def split_semicolon(value: str, label: str = "semicolon list") -> Tuple[str, ...]:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(label + " is not exact")
    parts = tuple(value.split(";"))
    if any(not item or item != item.strip() for item in parts):
        raise ValueError(label + " is not exact")
    return parts


def join_values(values: Iterable[str]) -> str:
    unique = sorted(set(str(value) for value in values if str(value)))
    return ";".join(unique) if unique else "none"


def summarize_agreement_status_counts(
    agreement_rows: Sequence[Dict[str, str]],
) -> Dict[str, int]:
    status_counts: Dict[str, int] = {}
    for row in agreement_rows:
        agreement_status = row.get("agreement_status")
        if agreement_status not in ALLOWED_AGREEMENT_STATUSES:
            raise ValueError("comparative synthesis agreement rows are malformed")
        status_counts[agreement_status] = status_counts.get(agreement_status, 0) + 1
    return status_counts


def summarize_structured_disagreements(
    agreement_rows: Sequence[Dict[str, str]],
) -> List[Dict[str, Any]]:
    disagreements = []
    for row in agreement_rows:
        structured_types = row.get("structured_disagreement_types")
        if structured_types == "none":
            continue
        types = split_semicolon(str(structured_types))
        if (
            not types
            or any(item not in ALLOWED_STRUCTURED_DISAGREEMENT_TYPES for item in types)
            or not str(row.get("evidence_id", "")).strip()
            or not str(row.get("method_id", "")).strip()
            or row.get("agreement_status") not in ALLOWED_AGREEMENT_STATUSES
            or not str(row.get("resolution_needed", "")).strip()
        ):
            raise ValueError("comparative synthesis agreement rows are malformed")
        disagreements.append(
            {
                "evidence_id": row["evidence_id"],
                "method_id": row["method_id"],
                "agreement_status": row["agreement_status"],
                "types": list(types),
                "resolution_needed": row["resolution_needed"],
            }
        )
    return disagreements


def expected_method_summary(
    agreement_rows: Sequence[Dict[str, str]],
    required_methods: Sequence[str],
) -> List[Dict[str, str]]:
    if len(agreement_rows) != len(required_methods):
        raise ValueError("comparative synthesis agreement rows are not exact")

    expected = []
    for index, (row, method_id) in enumerate(zip(agreement_rows, required_methods), 1):
        evidence_id = "E{0:03d}".format(index)
        if (
            row.get("comparison_id") != "X{0:03d}".format(index)
            or row.get("evidence_id") != evidence_id
            or row.get("method_id") != method_id
            or not str(row.get("report_kind", "")).strip()
            or row.get("source_evidence_status") not in ALLOWED_EVIDENCE_STATES
            or row.get("source_authorized_hrd_state") not in ALLOWED_HRD_STATES
        ):
            raise ValueError("comparative synthesis agreement rows are not exact")
        expected.append(
            {
                "evidence_id": evidence_id,
                "method_id": method_id,
                "report_kind": row["report_kind"],
                "evidence_status": row["source_evidence_status"],
                "authorized_hrd_state": row["source_authorized_hrd_state"],
            }
        )
    return expected


def markdown_text(value: Any) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def render_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def derive_authorized_state(rows: Sequence[Dict[str, Any]]) -> str:
    classified = set()
    for row in rows:
        state = str(row["authorized_hrd_state"])
        if state in {"positive", "negative"}:
            if row["evidence_status"] != "ready":
                raise ValueError("classified deterministic evidence is not ready")
            if row["classification_authorized"] is not True:
                raise ValueError("classified deterministic evidence lacks explicit authorization")
            if row["classification_qc_status"] != "passed":
                raise ValueError("classified deterministic evidence lacks passed classification QC")
            classified.add(state)
        elif (
            row["classification_authorized"] is not False
            or row["classification_qc_status"] != "not_applicable"
        ):
            raise ValueError(
                "no_call deterministic evidence cannot authorize classification "
                "or mark classification QC as applicable"
            )
    if len(classified) > 1:
        raise ValueError("deterministic sources contain conflicting authorized classifications")
    return next(iter(classified), "no_call")


def aggregate_evidence_state(rows: Sequence[Dict[str, Any]]) -> str:
    states = {str(row["evidence_status"]) for row in rows}
    if len(states) == 1:
        return next(iter(states))
    return "partial_evidence"


def verify_bundle(
    bundle_path: Path,
    bundle_manifest_path: Path,
    required_methods: Sequence[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], str, str]:
    bundle = load_object(bundle_path, "review_bundle.json")
    manifest = load_object(bundle_manifest_path, "bundle_manifest.json")
    if set(bundle) != BUNDLE_REVIEW_BUNDLE_KEYS:
        raise ValueError("AI review bundle envelope is not exact")
    if set(manifest) != BUNDLE_MANIFEST_KEYS:
        raise ValueError("AI review bundle manifest envelope is not exact")
    if not is_exact_int(bundle.get("schema_version"), 2) or not is_exact_int(
        manifest.get("schema_version"),
        2,
    ):
        raise ValueError("unsupported AI bundle schema")
    if bundle.get("purpose") != "deidentified_independent_narrative_crosscheck":
        raise ValueError("AI bundle purpose is missing or altered")
    if bundle.get("policy") != REQUIRED_POLICY:
        raise ValueError("AI bundle policy is missing or altered")
    bundle_hash = sha256(bundle_path)
    if checked_hash(manifest.get("review_bundle_sha256"), "AI bundle") != bundle_hash:
        raise ValueError("AI bundle hash differs from bundle_manifest.json")
    subject_alias = str(bundle.get("subject_alias", ""))
    if not SUBJECT_ALIAS.fullmatch(subject_alias) or manifest.get("subject_alias") != subject_alias:
        raise ValueError("AI bundle subject alias is missing, malformed, or altered")
    inventory_id = require_inventory_binding(
        bundle.get("method_inventory"),
        bundle.get("method_inventory_sha256"),
        "review bundle method inventory binding",
        None,
    )
    require_pinned_methods(
        required_methods,
        "synthesis required method inventory",
        inventory_id,
    )
    if bundle.get("required_method_ids") != list(required_methods):
        raise ValueError("AI bundle method inventory does not match the ordered required inventory")
    if manifest.get("required_method_ids") != list(required_methods):
        raise ValueError("bundle manifest method inventory does not match the ordered required inventory")
    require_inventory_binding(
        manifest.get("method_inventory"),
        manifest.get("method_inventory_sha256"),
        "bundle manifest method inventory binding",
        inventory_id,
    )
    if bundle.get("method_inventory_sha256") != manifest.get(
        "method_inventory_sha256"
    ):
        raise ValueError("bundle method inventory hashes disagree")
    models = bundle.get("model_execution_contracts")
    if not isinstance(models, dict) or set(models) != {"A", "B"}:
        raise ValueError("AI model contracts are missing")
    if manifest.get("model_execution_contracts") != models:
        raise ValueError("AI model contracts differ between bundle and manifest")
    catalog_receipt_hash = checked_hash(
        bundle.get("model_catalog_receipt_sha256"), "model catalog receipt"
    )
    if manifest.get("model_catalog_receipt_sha256") != catalog_receipt_hash:
        raise ValueError("model catalog receipt binding differs between bundle and manifest")
    model_identities: set[Tuple[str, str]] = set()
    catalog_timestamps: set[str] = set()
    for reviewer in ("A", "B"):
        provider, model_id, catalog_verified_at = require_reviewer_model_summary(
            models[reviewer],
            reviewer,
        )
        model_identities.add((provider, model_id))
        catalog_timestamps.add(catalog_verified_at)
    if len(model_identities) != 2:
        raise ValueError("reviewers must use distinct models")
    if len(catalog_timestamps) != 1:
        raise ValueError("reviewer model catalog timestamps differ")
    prompt_hashes = manifest.get("prompt_sha256")
    if not isinstance(prompt_hashes, dict) or set(prompt_hashes) != {"A", "B"}:
        raise ValueError("prompt hash inventory is missing")
    for reviewer in ("A", "B"):
        checked_hash(prompt_hashes[reviewer], "reviewer " + reviewer + " prompt")
    ceiling = str(bundle.get("authorized_hrd_state", ""))
    if ceiling not in ALLOWED_HRD_STATES or manifest.get("authorized_hrd_state") != ceiling:
        raise ValueError("AI bundle authorization is malformed or altered")
    evidence = bundle.get("evidence_sources")
    if not isinstance(evidence, list) or len(evidence) != len(required_methods):
        raise ValueError("AI bundle evidence inventory is incomplete")
    expected_ids = ["E{0:03d}".format(index) for index in range(1, len(evidence) + 1)]
    if [str(row.get("evidence_id", "")) for row in evidence if isinstance(row, dict)] != expected_ids:
        raise ValueError("AI bundle evidence IDs are missing, reordered, or malformed")
    if [str(row.get("method_id", "")) for row in evidence] != list(required_methods):
        raise ValueError("AI bundle evidence does not match the ordered method inventory")
    input_hashes = manifest.get("input_manifest_sha256")
    if not isinstance(input_hashes, dict) or set(input_hashes) != set(expected_ids):
        raise ValueError("source-manifest hash inventory is missing or altered")
    for evidence_id in expected_ids:
        checked_hash(input_hashes[evidence_id], evidence_id + " source manifest")
    return bundle, manifest, bundle_hash, inventory_id


def verify_sources(
    source_paths: Sequence[Path],
    required_methods: Sequence[str],
    bundle: Dict[str, Any],
    bundle_manifest: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if len(source_paths) != len(required_methods):
        raise ValueError("source manifests and required methods must have equal non-zero length")
    rows = []
    evidence_rows = bundle["evidence_sources"]
    input_hashes = bundle_manifest["input_manifest_sha256"]
    for index, (source_path, required_method) in enumerate(zip(source_paths, required_methods), 1):
        evidence_id = "E{0:03d}".format(index)
        source = load_object(source_path, evidence_id + " report_manifest.json")
        if not is_exact_int(source.get("schema_version"), 1):
            raise ValueError("unsupported source report schema for " + evidence_id)
        method = str(source.get("method_id") or source.get("route") or "")
        if method != required_method or not METHOD_ID.fullmatch(method):
            raise ValueError("source method does not match ordered required inventory at " + evidence_id)
        if sha256(source_path) != checked_hash(input_hashes[evidence_id], evidence_id + " source manifest"):
            raise ValueError("source manifest changed after AI bundle construction at " + evidence_id)
        report_hash = checked_hash(source.get("report_sha256"), method + " report")
        report_path = require_real_nonempty_file(
            source_path.parent / "report.md",
            method + " report.md",
        )
        if sha256(report_path) != report_hash:
            raise ValueError("source report hash mismatch for " + method)
        evidence_status = str(source.get("evidence_status", ""))
        authorized_state = str(source.get("authorized_hrd_state") or source.get("interpretation_status") or "")
        qc_status = str(source.get("classification_qc_status", "not_applicable"))
        if evidence_status not in ALLOWED_EVIDENCE_STATES:
            raise ValueError("invalid evidence status for " + method)
        if authorized_state not in ALLOWED_HRD_STATES:
            raise ValueError("invalid authorized HRD state for " + method)
        if qc_status not in ALLOWED_QC_STATES:
            raise ValueError("invalid classification QC state for " + method)
        source_hashes = source.get("source_sha256")
        if not isinstance(source_hashes, dict) or not source_hashes:
            raise ValueError("source-artifact hash inventory is missing for " + method)
        normalized_hashes = sorted(
            checked_hash(
                value,
                method + " source artifact " + checked_source_artifact_id(key, method),
            )
            for key, value in source_hashes.items()
        )
        validate_report_manifest_support(source_path.parent, source, method)
        summary = source.get("review_summary")
        if not isinstance(summary, dict) or not summary:
            raise ValueError("review summary is missing for " + method)
        expected = evidence_rows[index - 1]
        bindings = {
            "evidence_id": evidence_id,
            "method_id": method,
            "report_kind": str(source.get("report_kind", "method")),
            "evidence_status": evidence_status,
            "authorized_hrd_state": authorized_state,
            "classification_authorized": source.get("classification_authorized") is True,
            "classification_qc_status": qc_status,
            "report_sha256": report_hash,
            "source_artifact_sha256": normalized_hashes,
            "review_summary": summary,
        }
        if expected != bindings:
            raise ValueError("source evidence differs from the exact AI bundle at " + evidence_id)
        rows.append(bindings)
    derived = derive_authorized_state(rows)
    if bundle.get("authorized_hrd_state") != derived or bundle_manifest.get("authorized_hrd_state") != derived:
        raise ValueError("AI bundle authorization exceeds the deterministic authorized ceiling")
    return rows


def require_exact_review_invocation(invocation: Any, reviewer: str) -> Dict[str, str]:
    if (
        not isinstance(invocation, dict)
        or set(invocation) != REVIEW_INVOCATION_KEYS
        or any(
            not isinstance(invocation.get(key), str)
            or not invocation[key]
            or invocation[key] != invocation[key].strip()
            for key in REVIEW_INVOCATION_KEYS
        )
    ):
        raise ValueError(
            "reviewer " + reviewer + " invocation metadata is incomplete"
        )
    return dict(invocation)


def read_claims(path: Path, evidence_by_id: Dict[str, Dict[str, Any]], ceiling: str) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CLAIMS_FIELDS:
            raise ValueError("claims.csv header is missing or altered")
        rows = list(reader)
    if not rows:
        raise ValueError("claims.csv contains no claims")
    seen = set()
    covered = set()
    exact_rows = []
    for raw_row in rows:
        row = require_exact_csv_row(raw_row, CLAIMS_FIELDS, "claims.csv")
        exact_rows.append(row)
        claim_id = row["claim_id"]
        if not CLAIM_ID.fullmatch(claim_id) or claim_id in seen:
            raise ValueError("claims.csv contains a malformed or duplicate claim ID")
        seen.add(claim_id)
        evidence_ids = split_semicolon(
            row["evidence_ids"],
            "claim " + claim_id + " evidence_ids",
        )
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("claim " + claim_id + " has missing or duplicate evidence IDs")
        if any(item not in evidence_by_id for item in evidence_ids):
            raise ValueError("claim " + claim_id + " cites unknown evidence")
        expected_methods = tuple(str(evidence_by_id[item]["method_id"]) for item in evidence_ids)
        expected_states = tuple(str(evidence_by_id[item]["evidence_status"]) for item in evidence_ids)
        if (
            split_semicolon(
                row["source_methods"],
                "claim " + claim_id + " source_methods",
            )
            != expected_methods
        ):
            raise ValueError("claim " + claim_id + " method binding changed")
        if (
            split_semicolon(
                row["evidence_states"],
                "claim " + claim_id + " evidence_states",
            )
            != expected_states
        ):
            raise ValueError("claim " + claim_id + " evidence-state binding changed")
        proposed = row["proposed_hrd_state"]
        if proposed not in ALLOWED_HRD_STATES or proposed not in {"no_call", ceiling}:
            raise ValueError("claim " + claim_id + " exceeds deterministic authorization")
        if ceiling == "no_call" and proposed != "no_call":
            raise ValueError("claim " + claim_id + " promotes a no_call synthesis")
        disagreement = row["disagreement_status"]
        if disagreement not in ALLOWED_DISAGREEMENTS:
            raise ValueError("claim " + claim_id + " has an invalid disagreement state")
        if disagreement == "none" and row["resolution_needed"] != "not_applicable":
            raise ValueError("claim " + claim_id + " has inconsistent disagreement metadata")
        if disagreement != "none" and row["resolution_needed"] in {"", "not_applicable"}:
            raise ValueError("claim " + claim_id + " omits a disagreement resolution")
        covered.update(evidence_ids)
    if covered != set(evidence_by_id):
        raise ValueError("claims.csv does not preserve every source method and state")
    return exact_rows


def verify_review(
    directory: Path,
    reviewer: str,
    bundle: Dict[str, Any],
    bundle_manifest: Dict[str, Any],
    bundle_hash: str,
    inventory_id: str,
) -> Dict[str, Any]:
    directory = require_real_directory(directory, "reviewer " + reviewer)
    observed = {path.name for path in directory.iterdir()}
    if observed != REVIEW_FILES or any(path.is_symlink() or not path.is_file() for path in directory.iterdir()):
        raise ValueError("reviewer " + reviewer + " directory must contain exactly the four validated artifacts")
    validation_path = directory / "validation.json"
    manifest_path = directory / "review_manifest.json"
    report_path = directory / "report.md"
    claims_path = directory / "claims.csv"
    validation = load_object(validation_path, "reviewer " + reviewer + " validation")
    manifest = load_object(manifest_path, "reviewer " + reviewer + " manifest")
    if set(validation) != VALIDATION_KEYS:
        raise ValueError("reviewer " + reviewer + " validation envelope is not exact")
    if set(manifest) != REVIEW_MANIFEST_KEYS:
        raise ValueError("reviewer " + reviewer + " manifest envelope is not exact")
    if not is_exact_int(
        validation.get("schema_version"),
        2,
    ) or validation.get("status") != "passed":
        raise ValueError("reviewer " + reviewer + " is not validated")
    if validation.get("reviewer_id") != reviewer or manifest.get("reviewer_id") != reviewer:
        raise ValueError("reviewer identity is altered for reviewer " + reviewer)
    if not is_exact_int(manifest.get("schema_version"), 2):
        raise ValueError("unsupported review-manifest schema for reviewer " + reviewer)
    alias = str(bundle["subject_alias"])
    if validation.get("subject_alias") != alias or manifest.get("subject_alias") != alias:
        raise ValueError("reviewer " + reviewer + " alias binding changed")
    expected_model = bundle["model_execution_contracts"][reviewer]
    if validation.get("model") != expected_model or manifest.get("model") != expected_model:
        raise ValueError("reviewer " + reviewer + " model contract changed")
    if validation.get("authorized_hrd_state") != bundle["authorized_hrd_state"]:
        raise ValueError("reviewer " + reviewer + " authorization binding changed")
    if validation.get("required_method_ids") != bundle["required_method_ids"]:
        raise ValueError("reviewer " + reviewer + " ordered method inventory changed")
    require_inventory_binding(
        validation.get("method_inventory"),
        validation.get("method_inventory_sha256"),
        "reviewer " + reviewer + " validation method inventory",
        inventory_id,
    )
    if manifest.get("method_inventory_sha256") != inventory_sha256(inventory_id):
        raise ValueError("reviewer " + reviewer + " method inventory binding changed")
    if validation.get("model_catalog_receipt_sha256") != bundle.get(
        "model_catalog_receipt_sha256"
    ):
        raise ValueError("reviewer " + reviewer + " model catalog receipt binding changed")
    prompt_hash = checked_hash(bundle_manifest["prompt_sha256"][reviewer], reviewer + " prompt")
    if validation.get("review_bundle_sha256") != bundle_hash or manifest.get("input_bundle_sha256") != bundle_hash:
        raise ValueError("reviewer " + reviewer + " used a different AI bundle")
    if validation.get("prompt_sha256") != prompt_hash or manifest.get("prompt_sha256") != prompt_hash:
        raise ValueError("reviewer " + reviewer + " prompt binding changed")
    expected_inputs = {
        "review_bundle.json": bundle_hash,
        "reviewer-{0}.prompt.md".format(reviewer.lower()): prompt_hash,
    }
    if manifest.get("input_artifact_sha256") != expected_inputs:
        raise ValueError("reviewer " + reviewer + " input inventory is not exact")
    if manifest.get("independence_attestation") != REQUIRED_ATTESTATION:
        raise ValueError("reviewer " + reviewer + " independence attestation changed")
    if validation.get("review_manifest_sha256") != sha256(manifest_path):
        raise ValueError("reviewer " + reviewer + " manifest changed after validation")
    current_outputs = {"report.md": sha256(report_path), "claims.csv": sha256(claims_path)}
    if manifest.get("output_sha256") != current_outputs:
        raise ValueError("reviewer " + reviewer + " output differs from review_manifest.json")
    if validation.get("report_sha256") != current_outputs["report.md"]:
        raise ValueError("reviewer " + reviewer + " report changed after validation")
    if validation.get("claims_sha256") != current_outputs["claims.csv"]:
        raise ValueError("reviewer " + reviewer + " claims changed after validation")
    require_exact_review_invocation(manifest.get("invocation"), reviewer)
    evidence_by_id = {str(row["evidence_id"]): row for row in bundle["evidence_sources"]}
    claims = read_claims(claims_path, evidence_by_id, str(bundle["authorized_hrd_state"]))
    claim_count = validation.get("claim_count")
    if (
        not is_positive_exact_int(claim_count)
        or claim_count != len(claims)
    ):
        raise ValueError("reviewer " + reviewer + " claim count changed")
    disagreement_count = sum(row["disagreement_status"] != "none" for row in claims)
    validation_disagreement_count = validation.get("disagreement_claim_count")
    if (
        not is_nonnegative_exact_int(validation_disagreement_count)
        or validation_disagreement_count != disagreement_count
    ):
        raise ValueError("reviewer " + reviewer + " disagreement count changed")
    if validation.get("covered_evidence_ids") != sorted(evidence_by_id):
        raise ValueError("reviewer " + reviewer + " validation omits source evidence")
    narrative = report_path.read_text(encoding="utf-8") + "\n" + claims_path.read_text(encoding="utf-8")
    if bundle["authorized_hrd_state"] == "no_call" and has_unauthorized_hrd_classification(narrative):
        raise ValueError("reviewer " + reviewer + " contains an unauthorized categorical conclusion")
    return {
        "reviewer_id": reviewer,
        "validation": validation,
        "manifest": manifest,
        "claims": claims,
        "hashes": {
            "validation.json": sha256(validation_path),
            "review_manifest.json": sha256(manifest_path),
            "report.md": current_outputs["report.md"],
            "claims.csv": current_outputs["claims.csv"],
        },
    }


def verify_pair(review_a: Dict[str, Any], review_b: Dict[str, Any]) -> None:
    model_a = review_a["manifest"]["model"]
    model_b = review_b["manifest"]["model"]
    if (model_a["provider"], model_a["model_id"]) == (model_b["provider"], model_b["model_id"]):
        raise ValueError("reviewers used duplicate models")
    invocation_a = review_a["manifest"]["invocation"]["invocation_id"]
    invocation_b = review_b["manifest"]["invocation"]["invocation_id"]
    if invocation_a == invocation_b:
        raise ValueError("reviewers used a duplicate invocation ID")
    if review_a["hashes"]["report.md"] == review_b["hashes"]["report.md"]:
        raise ValueError("reviewers produced duplicate reports")
    if review_a["hashes"]["claims.csv"] == review_b["hashes"]["claims.csv"]:
        raise ValueError("reviewers produced duplicate claim tables")


def claims_for_evidence(claims: Sequence[Dict[str, str]], evidence_id: str) -> List[Dict[str, str]]:
    return [row for row in claims if evidence_id in split_semicolon(row["evidence_ids"])]


def build_agreement_rows(
    evidence_rows: Sequence[Dict[str, Any]],
    review_a: Dict[str, Any],
    review_b: Dict[str, Any],
) -> List[Dict[str, str]]:
    output = []
    for index, evidence in enumerate(evidence_rows, 1):
        evidence_id = str(evidence["evidence_id"])
        claims_a = claims_for_evidence(review_a["claims"], evidence_id)
        claims_b = claims_for_evidence(review_b["claims"], evidence_id)
        states_a = {row["proposed_hrd_state"] for row in claims_a}
        states_b = {row["proposed_hrd_state"] for row in claims_b}
        dispositions_a = {row["disposition"] for row in claims_a}
        dispositions_b = {row["disposition"] for row in claims_b}
        disagreements_a = {row["disagreement_status"] for row in claims_a}
        disagreements_b = {row["disagreement_status"] for row in claims_b}
        types = (disagreements_a | disagreements_b) - {"none"}
        if states_a != states_b:
            status = "discordant"
            types.add("reviewer_state_difference")
        elif dispositions_a == dispositions_b and disagreements_a == disagreements_b:
            status = "concordant"
        else:
            status = "partial_agreement"
            if dispositions_a != dispositions_b:
                types.add("reviewer_disposition_difference")
            if disagreements_a != disagreements_b:
                types.add("reviewer_disagreement_assessment_difference")
        if evidence["evidence_status"] in {"blocked", "no_call"}:
            types.add("source_not_comparable")
        elif evidence["evidence_status"] == "partial_evidence":
            types.add("source_partial_evidence")
        resolutions = {
            row["resolution_needed"]
            for row in claims_a + claims_b
            if row["resolution_needed"] not in {"", "not_applicable"}
        }
        output.append(
            {
                "comparison_id": "X{0:03d}".format(index),
                "evidence_id": evidence_id,
                "method_id": str(evidence["method_id"]),
                "report_kind": str(evidence["report_kind"]),
                "source_evidence_status": str(evidence["evidence_status"]),
                "source_authorized_hrd_state": str(evidence["authorized_hrd_state"]),
                "reviewer_a_claim_ids": join_values(row["claim_id"] for row in claims_a),
                "reviewer_b_claim_ids": join_values(row["claim_id"] for row in claims_b),
                "reviewer_a_proposed_states": join_values(states_a),
                "reviewer_b_proposed_states": join_values(states_b),
                "reviewer_a_dispositions": join_values(dispositions_a),
                "reviewer_b_dispositions": join_values(dispositions_b),
                "reviewer_a_disagreement_statuses": join_values(disagreements_a),
                "reviewer_b_disagreement_statuses": join_values(disagreements_b),
                "agreement_status": status,
                "structured_disagreement_types": join_values(types),
                "resolution_needed": " || ".join(sorted(resolutions)) if resolutions else "not_specified",
            }
        )
    return output


def collect_limitations(evidence_rows: Sequence[Dict[str, Any]], reviews: Sequence[Dict[str, Any]]) -> List[str]:
    values = set()
    for evidence in evidence_rows:
        limitations = evidence["review_summary"].get("limitations", [])
        if isinstance(limitations, list):
            values.update(str(value).strip() for value in limitations if str(value).strip())
    for review in reviews:
        values.update(row["caveat"] for row in review["claims"] if row["caveat"])
    return sorted(values)


def collect_unresolved(reviews: Sequence[Dict[str, Any]]) -> List[str]:
    return sorted(
        {
            row["resolution_needed"]
            for review in reviews
            for row in review["claims"]
            if row["resolution_needed"] not in {"", "not_applicable"}
        }
    )


def render_report(
    subject_alias: str,
    ceiling: str,
    evidence_rows: Sequence[Dict[str, Any]],
    review_a: Dict[str, Any],
    review_b: Dict[str, Any],
    agreement_rows: Sequence[Dict[str, str]],
    limitations: Sequence[str],
    unresolved: Sequence[str],
) -> str:
    lines = [
        "# Comparative HRD evidence synthesis",
        "",
        "Authorized HRD state: `{0}`".format(ceiling),
        "",
        "Subject alias: `{0}`".format(subject_alias),
        "",
        "## Process",
        "",
        "This synthesis was generated offline from the ordered deterministic and statistical report manifests, the exact de-identified AI bundle, and two independently validated reviewer outputs. Source reports, source manifests, bundle bindings, reviewer manifests, validations, reports, and claim tables were hash-checked again immediately before rendering. No raw sequencing data, external research, model invocation, or AWS access was used.",
        "",
        "The deterministic authorization is the ceiling. Reviewer agreement cannot create, strengthen, or replace an HRD classification; reviewer disagreement is retained as structured evidence rather than resolved by averaging or voting.",
        "",
        "## Per-approach results",
        "",
        "| Evidence | Method | Kind | Evidence state | Authorized state | Classification QC |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for evidence in evidence_rows:
        lines.append(
            "| {0} | `{1}` | `{2}` | `{3}` | `{4}` | `{5}` |".format(
                evidence["evidence_id"],
                markdown_text(evidence["method_id"]),
                markdown_text(evidence["report_kind"]),
                evidence["evidence_status"],
                evidence["authorized_hrd_state"],
                evidence["classification_qc_status"],
            )
        )
    for evidence in evidence_rows:
        lines.extend(
            [
                "",
                "### {0}: `{1}`".format(evidence["evidence_id"], markdown_text(evidence["method_id"])),
                "",
                "The exact, de-identified result summary supplied by this approach is:",
                "",
                *(
                    "    " + line
                    for line in json.dumps(
                        evidence["review_summary"], indent=2, sort_keys=True, ensure_ascii=False
                    ).splitlines()
                ),
            ]
        )
    for review in (review_a, review_b):
        reviewer = review["reviewer_id"]
        model = review["manifest"]["model"]
        lines.extend(
            [
                "",
                "### Independent AI reviewer {0}".format(reviewer),
                "",
                "Pinned latest-model contract: `{0}/{1}`, catalog-verified at `{2}`. "
                "The output remained bound to the same AI bundle and an independent invocation.".format(
                    markdown_text(model["provider"]),
                    markdown_text(model["model_id"]),
                    markdown_text(model["catalog_verified_at"]),
                ),
                "",
            ]
        )
        for claim in review["claims"]:
            lines.append(
                "- `{0}` ({1}, {2}, proposed `{3}`): {4} Caveat: {5}".format(
                    claim["claim_id"],
                    markdown_text(claim["support_level"]),
                    markdown_text(claim["disposition"]),
                    markdown_text(claim["proposed_hrd_state"]),
                    markdown_text(claim["claim"]),
                    markdown_text(claim["caveat"]),
                )
            )
    lines.extend(
        [
            "",
            "## Deterministic, statistical, and AI agreement",
            "",
            "| Evidence | Method | Source state | Reviewer state agreement | Structured differences |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in agreement_rows:
        lines.append(
            "| {0} | `{1}` | `{2}` | `{3}` | {4} |".format(
                row["evidence_id"],
                markdown_text(row["method_id"]),
                row["source_evidence_status"],
                row["agreement_status"],
                markdown_text(row["structured_disagreement_types"]),
            )
        )
    lines.extend(["", "The complete machine-readable comparison is in `agreement_disagreement.csv`."])
    lines.extend(["", "## Structured disagreements", ""])
    disagreements = [row for row in agreement_rows if row["structured_disagreement_types"] != "none"]
    if disagreements:
        for row in disagreements:
            lines.append(
                "- `{0}` / `{1}`: {2}. Resolution needed: {3}".format(
                    row["evidence_id"],
                    markdown_text(row["method_id"]),
                    markdown_text(row["structured_disagreement_types"]),
                    markdown_text(row["resolution_needed"]),
                )
            )
    else:
        lines.append("- No structured reviewer or method disagreement was recorded; this does not remove the limitations below.")
    lines.extend(["", "## Limitations", ""])
    if limitations:
        lines.extend("- " + markdown_text(value) for value in limitations)
    else:
        lines.append("- No explicit limitation was supplied in the hash-bound summaries or claim caveats.")
    lines.extend(["", "## Unresolved observations", ""])
    if unresolved:
        lines.extend("- " + markdown_text(value) for value in unresolved)
    else:
        lines.append("- No additional observation was explicitly requested by either validated reviewer.")
    lines.extend(["", "## Authorized conclusion", ""])
    if ceiling == "no_call":
        lines.append(
            "The authorized result remains `no_call`. The deterministic evidence does not authorize a categorical HRD conclusion, and neither independent AI review can promote that ceiling. All partial, blocked, and unresolved evidence remains visible above."
        )
    else:
        lines.append(
            "The synthesis preserves the deterministic authorized state `{0}`. This state originates only from ready, explicitly authorized deterministic evidence with passed classification QC. AI agreement or disagreement does not alter its authorization or certainty.".format(
                ceiling
            )
        )
    return "\n".join(lines) + "\n"


def write_agreement(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=AGREEMENT_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    write_staged_text(path, handle.getvalue())


def read_agreement(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != AGREEMENT_FIELDS:
            raise ValueError("agreement_disagreement.csv header is missing or altered")
        rows = list(reader)
    if not rows:
        raise ValueError("agreement_disagreement.csv contains no comparisons")
    return [
        require_exact_csv_row(row, AGREEMENT_FIELDS, "agreement_disagreement.csv")
        for row in rows
    ]


def prepare_output_dir(output: Path, expected_files: Iterable[str]) -> None:
    expected = set(expected_files)
    if output.is_symlink():
        raise ValueError("synthesis output may not be a symlink")
    for parent in output.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"synthesis output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"synthesis output parent is not a directory: {parent}")
    if output.exists() and not output.is_dir():
        raise ValueError(f"synthesis output is not a directory: {output}")

    output.mkdir(parents=True, exist_ok=True)

    unexpected: List[str] = []
    invalid: List[str] = []
    for path in output.iterdir():
        if path.name not in expected:
            unexpected.append(path.name)
        elif path.is_symlink() or not path.is_file():
            invalid.append(path.name)
    if unexpected:
        raise ValueError(
            "synthesis output contains unexpected existing files: "
            + ", ".join(sorted(unexpected))
        )
    if invalid:
        raise ValueError(
            "synthesis output contains invalid existing packet paths: "
            + ", ".join(sorted(invalid))
        )

    existing = sorted(path.name for path in output.iterdir() if path.name in expected)
    if existing:
        raise ValueError(
            "synthesis output already contains packet files: " + ", ".join(existing)
        )


def require_safe_new_packet(path: Path) -> Path:
    require_no_symlinked_ancestors(path, "synthesis output packet")
    if path.is_symlink():
        raise ValueError("synthesis output packet may not be a symlink: " + path.name)
    if path.exists():
        raise ValueError("synthesis output packet already exists: " + path.name)
    return path.resolve()


def require_safe_new_staged_file(path: Path) -> Path:
    require_no_symlinked_ancestors(path, "staged synthesis packet")
    if path.is_symlink():
        raise ValueError("staged synthesis packet may not be a symlink: " + path.name)
    if path.exists():
        raise ValueError("staged synthesis packet already exists: " + path.name)
    return path.resolve()


def require_staged_bytes(path: Path, expected_sha256: str) -> None:
    path = require_real_nonempty_file(path, "staged synthesis packet")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError("staged synthesis packet mode is not 0600: " + str(path))
    if sha256(path) != expected_sha256:
        raise ValueError("staged synthesis packet changed during write: " + path.name)


def write_staged_bytes(path: Path, payload: bytes) -> None:
    expected_sha256 = sha256_bytes(payload)
    path = require_safe_new_staged_file(path)
    file_descriptor = -1
    try:
        file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        require_staged_bytes(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def write_staged_text(path: Path, text: str) -> None:
    write_staged_bytes(path, text.encode("utf-8"))


def expected_synthesis_source_hash_keys(
    required_methods: Sequence[str] | None = None,
) -> set[str]:
    method_ids = required_method_ids() if required_methods is None else required_methods
    return {
        "generator",
        "review_bundle.json",
        "bundle_manifest.json",
        "agreement_disagreement.csv",
        *(
            "E{0:03d}_report_manifest.json".format(index)
            for index in range(1, len(method_ids) + 1)
        ),
        *(
            f"reviewer_{reviewer}_{filename}"
            for reviewer in ("A", "B")
            for filename in REVIEW_FILES
        ),
    }


def require_synthesis_source_hashes(
    manifest: Dict[str, Any],
    agreement_sha256: str,
    required_methods: Sequence[str],
    expected_source_hashes: Mapping[str, str] | None = None,
) -> None:
    source_hashes = manifest.get("source_sha256")
    if (
        not isinstance(source_hashes, dict)
        or set(source_hashes) != expected_synthesis_source_hash_keys(required_methods)
    ):
        raise ValueError("comparative synthesis source hashes are not exact")
    for key, digest in source_hashes.items():
        checked_hash(digest, "comparative synthesis source " + key)
    if source_hashes["agreement_disagreement.csv"] != agreement_sha256:
        raise ValueError(
            "comparative synthesis source hash is stale for agreement_disagreement.csv"
        )
    if source_hashes["generator"] != sha256(Path(__file__).resolve()):
        raise ValueError("comparative synthesis generator hash is stale")
    if (
        expected_source_hashes is not None
        and source_hashes != dict(expected_source_hashes)
    ):
        raise ValueError("comparative synthesis source hashes are stale")


def require_string_list(value: Any, label: str) -> List[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("comparative synthesis review summary has malformed " + label)
    return value


def require_exact_summary_string(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    return value


def require_reviewer_model_summary(model: Any, reviewer: str) -> Tuple[str, str, str]:
    provider = model.get("provider") if isinstance(model, dict) else None
    model_id = model.get("model_id") if isinstance(model, dict) else None
    catalog_verified_at = (
        model.get("catalog_verified_at") if isinstance(model, dict) else None
    )
    if (
        not isinstance(model, dict)
        or set(model) != {
            "provider",
            "model_id",
            "catalog_verified_at",
            "latest_available_attested",
        }
        or not require_exact_summary_string(provider)
        or not require_exact_summary_string(model_id)
        or not require_exact_summary_string(catalog_verified_at)
        or model.get("latest_available_attested") is not True
    ):
        raise ValueError(
            f"comparative synthesis reviewer {reviewer} model summary is not exact"
        )
    try:
        verified_at = datetime.fromisoformat(
            catalog_verified_at.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ValueError(
            f"comparative synthesis reviewer {reviewer} model summary is not exact"
        ) from error
    if verified_at.tzinfo is None:
        raise ValueError(
            f"comparative synthesis reviewer {reviewer} model summary is not exact"
        )
    return (
        provider,
        model_id,
        catalog_verified_at,
    )


def require_synthesis_review_summary(
    manifest: Dict[str, Any],
    agreement_rows: Sequence[Dict[str, str]],
) -> Tuple[str, ...]:
    summary = manifest.get("review_summary")
    if not isinstance(summary, dict) or not summary:
        raise ValueError("comparative synthesis review summary is missing")

    process = summary.get("process")
    required_process_keys = set(REQUIRED_SYNTHESIS_PROCESS) | {
        "method_inventory",
        "method_inventory_sha256",
    }
    if (
        not isinstance(process, dict)
        or set(process) != required_process_keys
        or any(
            process.get(key) is not value
            for key, value in REQUIRED_SYNTHESIS_PROCESS.items()
        )
    ):
        raise ValueError("comparative synthesis process summary is not exact")
    inventory_id = require_inventory_binding(
        process.get("method_inventory"),
        process.get("method_inventory_sha256"),
        "comparative synthesis process method inventory",
        None,
    )
    required_methods = required_method_ids(inventory_id)

    readiness = summary.get("readiness")
    if readiness != {
        "evidence_status": manifest.get("evidence_status"),
        "authorized_hrd_state": manifest.get("authorized_hrd_state"),
        "classification_authorization": manifest.get("classification_authorization"),
    }:
        raise ValueError("comparative synthesis readiness summary is stale")

    expected_methods = expected_method_summary(agreement_rows, required_methods)
    methods = summary.get("methods")
    if not isinstance(methods, list) or methods != expected_methods:
        raise ValueError("comparative synthesis method summary is not exact")
    method_by_evidence: Dict[str, str] = {}
    for row in expected_methods:
        method_by_evidence[row["evidence_id"]] = row["method_id"]

    reviewers = summary.get("reviewers")
    if not isinstance(reviewers, list) or len(reviewers) != 2:
        raise ValueError("comparative synthesis reviewer summary is not exact")
    model_identities: set[Tuple[str, str]] = set()
    catalog_timestamps: set[str] = set()
    for row, reviewer in zip(reviewers, ("A", "B")):
        if not isinstance(row, dict) or row.get("reviewer_id") != reviewer:
            raise ValueError("comparative synthesis reviewer summary is not exact")
        model = row.get("model")
        claim_count = row.get("claim_count")
        disagreement_count = row.get("disagreement_claim_count")
        provider, model_id, catalog_verified_at = require_reviewer_model_summary(
            model, reviewer
        )
        model_identities.add((provider, model_id))
        catalog_timestamps.add(catalog_verified_at)
        if (
            not is_positive_exact_int(claim_count)
            or not is_nonnegative_exact_int(disagreement_count)
            or disagreement_count > claim_count
        ):
            raise ValueError("comparative synthesis reviewer summary is not exact")
    if len(model_identities) != 2 or len(catalog_timestamps) != 1:
        raise ValueError("comparative synthesis reviewer summary is not exact")

    status_counts = summary.get("agreement_status_counts")
    if (
        not isinstance(status_counts, dict)
        or not status_counts
        or set(status_counts) - ALLOWED_AGREEMENT_STATUSES
        or any(
            not is_nonnegative_exact_int(value)
            for value in status_counts.values()
        )
        or sum(status_counts.values()) != len(required_methods)
    ):
        raise ValueError("comparative synthesis agreement counts are not exact")
    if status_counts != summarize_agreement_status_counts(agreement_rows):
        raise ValueError("comparative synthesis agreement counts are stale")

    disagreements = summary.get("structured_disagreements")
    if not isinstance(disagreements, list):
        raise ValueError("comparative synthesis structured disagreements are malformed")
    for row in disagreements:
        if not isinstance(row, dict):
            raise ValueError("comparative synthesis structured disagreements are malformed")
        evidence_id = str(row.get("evidence_id", ""))
        types = row.get("types")
        if (
            evidence_id not in method_by_evidence
            or row.get("method_id") != method_by_evidence[evidence_id]
            or row.get("agreement_status") not in ALLOWED_AGREEMENT_STATUSES
            or not isinstance(types, list)
            or not types
            or any(item not in ALLOWED_STRUCTURED_DISAGREEMENT_TYPES for item in types)
            or not str(row.get("resolution_needed", "")).strip()
        ):
            raise ValueError("comparative synthesis structured disagreements are malformed")
    if disagreements != summarize_structured_disagreements(agreement_rows):
        raise ValueError("comparative synthesis structured disagreements are stale")

    require_string_list(summary.get("limitations"), "limitations")
    require_string_list(summary.get("unresolved_observations"), "unresolved observations")
    if summary.get("authorized_conclusion") != manifest.get("authorized_hrd_state"):
        raise ValueError("comparative synthesis authorized conclusion is stale")
    return required_methods


def require_synthesis_report_manifest(
    packet_dir: Path,
    *,
    expected_source_hashes: Mapping[str, str] | None = None,
) -> None:
    observed = {path.name for path in packet_dir.iterdir()}
    if observed != OUTPUT_FILES:
        missing = sorted(OUTPUT_FILES - observed)
        unexpected = sorted(observed - OUTPUT_FILES)
        details = []
        if missing:
            details.append("missing " + ",".join(missing))
        if unexpected:
            details.append("unexpected " + ",".join(unexpected))
        raise ValueError(
            "comparative synthesis inventory is not exact: " + "; ".join(details)
        )

    manifest = load_object(packet_dir / "report_manifest.json", "synthesis packet")
    if set(manifest) != REPORT_MANIFEST_KEYS:
        raise ValueError("comparative synthesis manifest envelope is not exact")
    if (
        not is_exact_int(manifest.get("schema_version"), 1)
        or manifest.get("report_kind") != "comparative_synthesis"
        or manifest.get("method_id") != "comparative_hrd_synthesis"
        or manifest.get("evidence_status") not in ALLOWED_EVIDENCE_STATES
        or manifest.get("authorized_hrd_state") not in ALLOWED_HRD_STATES
        or manifest.get("classification_authorized")
        is not (manifest.get("authorized_hrd_state") in {"positive", "negative"})
        or manifest.get("classification_authorization")
        != (
            "deterministic_ceiling_preserved"
            if manifest.get("authorized_hrd_state") in {"positive", "negative"}
            else "none"
        )
        or manifest.get("classification_qc_status")
        != (
            "passed"
            if manifest.get("authorized_hrd_state") in {"positive", "negative"}
            else "not_applicable"
        )
    ):
        raise ValueError("comparative synthesis manifest does not preserve authorization")
    expected = [
        (
            "report.md",
            checked_hash(manifest.get("report_sha256"), "comparative synthesis report.md"),
        ),
        (
            "agreement_disagreement.csv",
            checked_hash(
                manifest.get("agreement_disagreement_sha256"),
                "comparative synthesis agreement_disagreement.csv",
            ),
        ),
    ]
    support_hashes = manifest.get("support_sha256")
    if (
        not isinstance(support_hashes, dict)
        or set(support_hashes) != {"agreement_disagreement.csv"}
    ):
        raise ValueError("comparative synthesis manifest support hashes are not exact")
    expected.append(
        (
            "agreement_disagreement.csv",
            checked_hash(
                support_hashes.get("agreement_disagreement.csv"),
                "comparative synthesis support agreement_disagreement.csv",
            ),
        )
    )

    for filename, expected_sha256 in expected:
        observed_sha256 = sha256(
            require_real_nonempty_file(packet_dir / filename, "synthesis packet")
        )
        if observed_sha256 != expected_sha256:
            raise ValueError("comparative synthesis manifest is stale for " + filename)

    agreement_path = require_real_nonempty_file(
        packet_dir / "agreement_disagreement.csv",
        "synthesis packet",
    )
    agreement_sha256 = sha256(agreement_path)
    agreement_rows = read_agreement(agreement_path)
    required_methods = require_synthesis_review_summary(manifest, agreement_rows)
    require_synthesis_source_hashes(
        manifest,
        agreement_sha256,
        required_methods,
        expected_source_hashes=expected_source_hashes,
    )


def copy_create_only(source: Path, destination: Path) -> None:
    source = require_real_nonempty_file(source, "staged synthesis packet")
    expected_sha256 = sha256(source)
    destination = require_safe_new_packet(destination)
    with source.open("rb") as source_handle:
        try:
            file_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError as error:
            raise ValueError(
                "synthesis output packet already exists: " + destination.name
            ) from error

        try:
            destination_handle = os.fdopen(file_descriptor, "wb")
        except Exception:
            os.close(file_descriptor)
            destination.unlink(missing_ok=True)
            raise

        try:
            with destination_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            fsync_directory(destination.parent)
            require_real_nonempty_file(destination, "synthesis output packet")
            if (
                sha256(source) != expected_sha256
                or sha256(destination) != expected_sha256
            ):
                raise ValueError("staged synthesis packet changed during copy: " + source.name)
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_packet_create_only(staged_paths: Sequence[Path], output: Path) -> None:
    installed: List[Path] = []
    expected_hashes: Dict[Path, str] = {}
    try:
        for path in staged_paths:
            destination = output / path.name
            expected_hashes[destination] = sha256(
                require_real_nonempty_file(path, "staged synthesis packet")
            )
            destination_preexisted = destination.exists() or destination.is_symlink()
            try:
                copy_create_only(path, destination)
            except Exception:
                if not destination_preexisted:
                    installed.append(destination)
                raise
            installed.append(destination)
        fsync_directory(output)
        for destination, expected_sha256 in expected_hashes.items():
            installed_path = require_real_nonempty_file(
                destination,
                "synthesis output packet",
            )
            if sha256(installed_path) != expected_sha256:
                raise ValueError(
                    "synthesis output packet changed during install: "
                    + destination.name
                )
        require_synthesis_report_manifest(output)
    except Exception:
        for path in reversed(installed):
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", action="append", required=True, type=Path)
    parser.add_argument("--require-method", action="append", required=True)
    parser.add_argument("--review-bundle", required=True, type=Path)
    parser.add_argument("--bundle-manifest", required=True, type=Path)
    parser.add_argument("--reviewer-a-dir", required=True, type=Path)
    parser.add_argument("--reviewer-b-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    try:
        output = args.output_dir
        prepare_output_dir(output, OUTPUT_FILES)
    except ValueError as error:
        raise SystemExit("Fail-closed: " + str(error)) from error
    output = output.resolve()
    required_methods = [str(value).strip() for value in args.require_method]
    if (
        not required_methods
        or any(not METHOD_ID.fullmatch(value) for value in required_methods)
        or len(set(required_methods)) != len(required_methods)
    ):
        raise SystemExit("Fail-closed: required method inventory is empty, malformed, or duplicated")
    try:
        bundle, bundle_manifest, bundle_hash, inventory_id = verify_bundle(
            args.review_bundle, args.bundle_manifest, required_methods
        )
        evidence_rows = verify_sources(
            args.source_manifest,
            required_methods,
            bundle,
            bundle_manifest,
        )
        review_a = verify_review(
            args.reviewer_a_dir,
            "A",
            bundle,
            bundle_manifest,
            bundle_hash,
            inventory_id,
        )
        review_b = verify_review(
            args.reviewer_b_dir,
            "B",
            bundle,
            bundle_manifest,
            bundle_hash,
            inventory_id,
        )
        verify_pair(review_a, review_b)
        ceiling = derive_authorized_state(evidence_rows)
        evidence_state = aggregate_evidence_state(evidence_rows)
        agreement_rows = build_agreement_rows(evidence_rows, review_a, review_b)
        limitations = collect_limitations(evidence_rows, [review_a, review_b])
        unresolved = collect_unresolved([review_a, review_b])
        report = render_report(
            str(bundle["subject_alias"]),
            ceiling,
            evidence_rows,
            review_a,
            review_b,
            agreement_rows,
            limitations,
            unresolved,
        )
    except (ValueError, OSError, UnicodeError, csv.Error) as error:
        raise SystemExit("Fail-closed: " + str(error)) from error

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hrd-synthesis-", dir=output.parent) as temporary:
        staging = Path(temporary)
        report_path = staging / "report.md"
        agreement_path = staging / "agreement_disagreement.csv"
        write_staged_text(report_path, report)
        write_agreement(agreement_path, agreement_rows)
        status_counts = summarize_agreement_status_counts(agreement_rows)
        disagreements = summarize_structured_disagreements(agreement_rows)
        source_hashes = {
            "generator": sha256(Path(__file__).resolve()),
            "review_bundle.json": bundle_hash,
            "bundle_manifest.json": sha256(args.bundle_manifest.resolve()),
            "agreement_disagreement.csv": sha256(agreement_path),
        }
        for index, source_path in enumerate(args.source_manifest, 1):
            source_hashes["E{0:03d}_report_manifest.json".format(index)] = sha256(source_path.resolve())
        for review in (review_a, review_b):
            reviewer = review["reviewer_id"]
            for filename, digest in review["hashes"].items():
                source_hashes["reviewer_{0}_{1}".format(reviewer, filename)] = digest
        manifest = {
            "schema_version": 1,
            "report_kind": "comparative_synthesis",
            "method_id": "comparative_hrd_synthesis",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "subject_alias": str(bundle["subject_alias"]),
            "evidence_status": evidence_state,
            "interpretation_status": ceiling,
            "authorized_hrd_state": ceiling,
            "classification_authorized": ceiling in {"positive", "negative"},
            "classification_authorization": (
                "deterministic_ceiling_preserved" if ceiling in {"positive", "negative"} else "none"
            ),
            "classification_qc_status": "passed" if ceiling in {"positive", "negative"} else "not_applicable",
            "report_sha256": sha256(report_path),
            "agreement_disagreement_sha256": sha256(agreement_path),
            "support_sha256": {
                "agreement_disagreement.csv": sha256(agreement_path),
            },
            "source_sha256": source_hashes,
            "review_summary": {
                "evidence_scope": "offline comparative synthesis of deterministic, statistical, and independently validated AI evidence",
                "process": {
                    "ordered_source_manifests_verified": True,
                    "source_reports_verified": True,
                    "ai_bundle_and_manifest_verified": True,
                    "reviewer_outputs_unchanged_after_validation": True,
                    "distinct_models_verified": True,
                    "distinct_invocations_verified": True,
                    "same_ai_bundle_verified": True,
                    "raw_inputs_used": False,
                    "external_research_used": False,
                    "method_inventory": inventory_payload(inventory_id),
                    "method_inventory_sha256": inventory_sha256(inventory_id),
                },
                "readiness": {
                    "evidence_status": evidence_state,
                    "authorized_hrd_state": ceiling,
                    "classification_authorization": (
                        "deterministic_ceiling_preserved" if ceiling in {"positive", "negative"} else "none"
                    ),
                },
                "methods": [
                    {
                        "evidence_id": row["evidence_id"],
                        "method_id": row["method_id"],
                        "report_kind": row["report_kind"],
                        "evidence_status": row["evidence_status"],
                        "authorized_hrd_state": row["authorized_hrd_state"],
                    }
                    for row in evidence_rows
                ],
                "reviewers": [
                    {
                        "reviewer_id": review["reviewer_id"],
                        "model": review["manifest"]["model"],
                        "claim_count": len(review["claims"]),
                        "disagreement_claim_count": sum(
                            row["disagreement_status"] != "none" for row in review["claims"]
                        ),
                    }
                    for review in (review_a, review_b)
                ],
                "agreement_status_counts": status_counts,
                "structured_disagreements": disagreements,
                "limitations": limitations,
                "unresolved_observations": unresolved,
                "authorized_conclusion": ceiling,
            },
        }
        manifest_path = staging / "report_manifest.json"
        write_staged_bytes(manifest_path, canonical_json_bytes(manifest))
        require_synthesis_report_manifest(
            staging,
            expected_source_hashes=source_hashes,
        )
        try:
            install_packet_create_only(
                (report_path, agreement_path, manifest_path),
                output,
            )
        except ValueError as error:
            raise SystemExit("Fail-closed: " + str(error)) from error
    print("Wrote verified comparative synthesis: " + str(output))
    print("Authorized HRD state: {0}; no model invoked".format(ceiling))


if __name__ == "__main__":
    main()
