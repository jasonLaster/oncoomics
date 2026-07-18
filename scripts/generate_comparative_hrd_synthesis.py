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
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from forbidden_text import has_unauthorized_hrd_classification
from hrd_report_inventory import (
    inventory_payload,
    inventory_sha256,
    require_inventory_binding,
    require_pinned_methods,
)


HEX64 = re.compile(r"^[0-9a-f]{64}$")
METHOD_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")
EVIDENCE_ID = re.compile(r"^E[0-9]{3,}$")
CLAIM_ID = re.compile(r"^C[0-9]{3,}$")
SUBJECT_ALIAS = re.compile(r"^subject[0-9]{2,4}$")
ALLOWED_EVIDENCE_STATES = {"ready", "partial_evidence", "no_call", "blocked"}
ALLOWED_HRD_STATES = {"no_call", "positive", "negative"}
ALLOWED_QC_STATES = {"passed", "failed", "not_applicable", "blocked", "not_run"}
ALLOWED_DISAGREEMENTS = {
    "none",
    "method_conflict",
    "insufficient_comparability",
    "missing_evidence",
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> Dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError("missing or unsafe " + label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON in " + label) from error
    if not isinstance(value, dict):
        raise ValueError(label + " must be a JSON object")
    return value


def checked_hash(value: Any, label: str) -> str:
    text = str(value).lower()
    if not HEX64.fullmatch(text):
        raise ValueError("malformed SHA-256 for " + label)
    return text


def split_semicolon(value: str) -> Tuple[str, ...]:
    return tuple(item.strip() for item in value.split(";") if item.strip())


def join_values(values: Iterable[str]) -> str:
    unique = sorted(set(str(value) for value in values if str(value)))
    return ";".join(unique) if unique else "none"


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
        elif row["classification_authorized"] is not False:
            raise ValueError(
                "no_call deterministic evidence cannot authorize classification"
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
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    bundle = load_object(bundle_path, "review_bundle.json")
    manifest = load_object(bundle_manifest_path, "bundle_manifest.json")
    if bundle.get("schema_version") != 2 or manifest.get("schema_version") != 2:
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
    if bundle.get("required_method_ids") != list(required_methods):
        raise ValueError("AI bundle method inventory does not match the ordered required inventory")
    if manifest.get("required_method_ids") != list(required_methods):
        raise ValueError("bundle manifest method inventory does not match the ordered required inventory")
    require_pinned_methods(required_methods, "synthesis required method inventory")
    require_inventory_binding(
        bundle.get("method_inventory"),
        bundle.get("method_inventory_sha256"),
        "review bundle method inventory binding",
    )
    require_inventory_binding(
        manifest.get("method_inventory"),
        manifest.get("method_inventory_sha256"),
        "bundle manifest method inventory binding",
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
    identities = []
    for reviewer in ("A", "B"):
        model = models[reviewer]
        if not isinstance(model, dict) or model.get("latest_available_attested") is not True:
            raise ValueError("latest-model attestation is missing for reviewer " + reviewer)
        provider = str(model.get("provider", "")).strip()
        model_id = str(model.get("model_id", "")).strip()
        if not provider or not model_id:
            raise ValueError("model identity is missing for reviewer " + reviewer)
        identities.append((provider, model_id))
    if identities[0] == identities[1]:
        raise ValueError("reviewers must use distinct models")
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
    return bundle, manifest, bundle_hash


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
        if source.get("schema_version") != 1:
            raise ValueError("unsupported source report schema for " + evidence_id)
        method = str(source.get("method_id") or source.get("route") or "")
        if method != required_method or not METHOD_ID.fullmatch(method):
            raise ValueError("source method does not match ordered required inventory at " + evidence_id)
        if sha256(source_path) != checked_hash(input_hashes[evidence_id], evidence_id + " source manifest"):
            raise ValueError("source manifest changed after AI bundle construction at " + evidence_id)
        report_hash = checked_hash(source.get("report_sha256"), method + " report")
        report_path = source_path.parent / "report.md"
        if not report_path.is_file() or report_path.is_symlink() or sha256(report_path) != report_hash:
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
        normalized_hashes = sorted(checked_hash(value, method + " source artifact") for value in source_hashes.values())
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
    for row in rows:
        if None in row or any(not isinstance(row.get(field), str) for field in CLAIMS_FIELDS):
            raise ValueError("claims.csv contains a malformed row")
        claim_id = row["claim_id"].strip()
        if not CLAIM_ID.fullmatch(claim_id) or claim_id in seen:
            raise ValueError("claims.csv contains a malformed or duplicate claim ID")
        seen.add(claim_id)
        evidence_ids = split_semicolon(row["evidence_ids"])
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("claim " + claim_id + " has missing or duplicate evidence IDs")
        if any(item not in evidence_by_id for item in evidence_ids):
            raise ValueError("claim " + claim_id + " cites unknown evidence")
        expected_methods = tuple(str(evidence_by_id[item]["method_id"]) for item in evidence_ids)
        expected_states = tuple(str(evidence_by_id[item]["evidence_status"]) for item in evidence_ids)
        if split_semicolon(row["source_methods"]) != expected_methods:
            raise ValueError("claim " + claim_id + " method binding changed")
        if split_semicolon(row["evidence_states"]) != expected_states:
            raise ValueError("claim " + claim_id + " evidence-state binding changed")
        proposed = row["proposed_hrd_state"].strip()
        if proposed not in ALLOWED_HRD_STATES or proposed not in {"no_call", ceiling}:
            raise ValueError("claim " + claim_id + " exceeds deterministic authorization")
        if ceiling == "no_call" and proposed != "no_call":
            raise ValueError("claim " + claim_id + " promotes a no_call synthesis")
        disagreement = row["disagreement_status"].strip()
        if disagreement not in ALLOWED_DISAGREEMENTS:
            raise ValueError("claim " + claim_id + " has an invalid disagreement state")
        if disagreement == "none" and row["resolution_needed"].strip() != "not_applicable":
            raise ValueError("claim " + claim_id + " has inconsistent disagreement metadata")
        if disagreement != "none" and row["resolution_needed"].strip() in {"", "not_applicable"}:
            raise ValueError("claim " + claim_id + " omits a disagreement resolution")
        covered.update(evidence_ids)
    if covered != set(evidence_by_id):
        raise ValueError("claims.csv does not preserve every source method and state")
    return rows


def verify_review(
    directory: Path,
    reviewer: str,
    bundle: Dict[str, Any],
    bundle_manifest: Dict[str, Any],
    bundle_hash: str,
) -> Dict[str, Any]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("reviewer " + reviewer + " directory is missing or unsafe")
    observed = {path.name for path in directory.iterdir()}
    if observed != REVIEW_FILES or any(path.is_symlink() or not path.is_file() for path in directory.iterdir()):
        raise ValueError("reviewer " + reviewer + " directory must contain exactly the four validated artifacts")
    validation_path = directory / "validation.json"
    manifest_path = directory / "review_manifest.json"
    report_path = directory / "report.md"
    claims_path = directory / "claims.csv"
    validation = load_object(validation_path, "reviewer " + reviewer + " validation")
    manifest = load_object(manifest_path, "reviewer " + reviewer + " manifest")
    if validation.get("schema_version") != 2 or validation.get("status") != "passed":
        raise ValueError("reviewer " + reviewer + " is not validated")
    if validation.get("reviewer_id") != reviewer or manifest.get("reviewer_id") != reviewer:
        raise ValueError("reviewer identity is altered for reviewer " + reviewer)
    if manifest.get("schema_version") != 2:
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
    if (
        validation.get("method_inventory_sha256") != inventory_sha256()
        or manifest.get("method_inventory_sha256") != inventory_sha256()
    ):
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
    invocation = manifest.get("invocation")
    if not isinstance(invocation, dict) or any(
        not str(invocation.get(key, "")).strip()
        for key in ("invocation_id", "interface", "started_at", "completed_at")
    ):
        raise ValueError("reviewer " + reviewer + " invocation metadata is incomplete")
    evidence_by_id = {str(row["evidence_id"]): row for row in bundle["evidence_sources"]}
    claims = read_claims(claims_path, evidence_by_id, str(bundle["authorized_hrd_state"]))
    if validation.get("claim_count") != len(claims):
        raise ValueError("reviewer " + reviewer + " claim count changed")
    disagreement_count = sum(row["disagreement_status"].strip() != "none" for row in claims)
    if validation.get("disagreement_claim_count") != disagreement_count:
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
    invocation_a = str(review_a["manifest"]["invocation"]["invocation_id"])
    invocation_b = str(review_b["manifest"]["invocation"]["invocation_id"])
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
        states_a = {row["proposed_hrd_state"].strip() for row in claims_a}
        states_b = {row["proposed_hrd_state"].strip() for row in claims_b}
        dispositions_a = {row["disposition"].strip() for row in claims_a}
        dispositions_b = {row["disposition"].strip() for row in claims_b}
        disagreements_a = {row["disagreement_status"].strip() for row in claims_a}
        disagreements_b = {row["disagreement_status"].strip() for row in claims_b}
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
            row["resolution_needed"].strip()
            for row in claims_a + claims_b
            if row["resolution_needed"].strip() not in {"", "not_applicable"}
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
        values.update(row["caveat"].strip() for row in review["claims"] if row["caveat"].strip())
    return sorted(values)


def collect_unresolved(reviews: Sequence[Dict[str, Any]]) -> List[str]:
    return sorted(
        {
            row["resolution_needed"].strip()
            for review in reviews
            for row in review["claims"]
            if row["resolution_needed"].strip() not in {"", "not_applicable"}
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
                "Pinned latest-model contract: `{0}/{1}`. The output remained bound to the same AI bundle and an independent invocation.".format(
                    markdown_text(model["provider"]), markdown_text(model["model_id"])
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
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AGREEMENT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare_output_dir(output: Path, expected_files: Iterable[str]) -> None:
    expected = set(expected_files)
    if output.is_symlink():
        raise ValueError("synthesis output may not be a symlink")
    parent = output.parent
    while not parent.exists() and not parent.is_symlink():
        if parent == parent.parent:
            break
        parent = parent.parent
    if parent.is_symlink():
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


def copy_create_only(source: Path, destination: Path) -> None:
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
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def install_packet_create_only(staged_paths: Sequence[Path], output: Path) -> None:
    installed: List[Path] = []
    try:
        for path in staged_paths:
            destination = output / path.name
            copy_create_only(path, destination)
            installed.append(destination)
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
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
        require_pinned_methods(required_methods, "synthesis method arguments")
    except ValueError as error:
        raise SystemExit("Fail-closed: " + str(error)) from error
    try:
        bundle, bundle_manifest, bundle_hash = verify_bundle(
            args.review_bundle, args.bundle_manifest, required_methods
        )
        evidence_rows = verify_sources(
            args.source_manifest,
            required_methods,
            bundle,
            bundle_manifest,
        )
        review_a = verify_review(
            args.reviewer_a_dir, "A", bundle, bundle_manifest, bundle_hash
        )
        review_b = verify_review(
            args.reviewer_b_dir, "B", bundle, bundle_manifest, bundle_hash
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
        report_path.write_text(report, encoding="utf-8")
        write_agreement(agreement_path, agreement_rows)
        status_counts: Dict[str, int] = {}
        for row in agreement_rows:
            status_counts[row["agreement_status"]] = status_counts.get(row["agreement_status"], 0) + 1
        disagreements = [
            {
                "evidence_id": row["evidence_id"],
                "method_id": row["method_id"],
                "agreement_status": row["agreement_status"],
                "types": split_semicolon(row["structured_disagreement_types"])
                if row["structured_disagreement_types"] != "none"
                else [],
                "resolution_needed": row["resolution_needed"],
            }
            for row in agreement_rows
            if row["structured_disagreement_types"] != "none"
        ]
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
                    "method_inventory": inventory_payload(),
                    "method_inventory_sha256": inventory_sha256(),
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
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
