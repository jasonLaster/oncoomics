from __future__ import annotations

import os
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/clinical_validation_packet_sections.csv"
TEMPLATE_DOC_PATH = "docs/clinical/validation-packet-template.md"
CLINICAL_BOUNDARIES_PATH = os.environ.get("CLINICAL_PACKET_BOUNDARIES", "results/clinicalization/clinical_assay_boundaries_summary.json")
KNOWN_ANSWER_READINESS_PATH = os.environ.get(
    "CLINICAL_PACKET_KNOWN_ANSWER_READINESS", "results/clinicalization/known_answer_fixture_readiness_summary.json"
)
SUMMARY_CSV_PATH = "results/clinicalization/clinical_validation_packet_readiness_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/clinical_validation_packet_readiness_summary.json"
REQUIRED_COLUMNS = {
    "section_id",
    "section_title",
    "validation_domain",
    "required_evidence",
    "current_evidence_status",
    "blocking_dependency",
    "packet_status",
    "signoff_status",
    "caveat",
}
REQUIRED_DOMAINS = {
    "scope",
    "workflow",
    "preanalytic_qc",
    "accuracy",
    "precision",
    "reproducibility",
    "lod",
    "reportable_range",
    "limitations",
    "qc",
    "reporting",
    "change_control",
    "signoff",
}
REQUIRED_SECTIONS = {
    "intended_use",
    "workflow_overview",
    "input_acceptance",
    "accuracy_small_variants",
    "accuracy_cnv_loh",
    "accuracy_sv",
    "signature_model_accuracy",
    "precision_repeatability",
    "reproducibility",
    "lod",
    "reportable_range",
    "interferences_limitations",
    "qc_gates",
    "report_template",
    "change_control",
    "approval_signoff",
}


def manifest_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(MANIFEST_PATH)))


def validate_manifest(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return [f"{MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"{MANIFEST_PATH} is missing required column {column}.")
    ids: set[str] = set()
    domains: set[str] = set()
    for row in rows:
        section_id = row.get("section_id", "")
        if not section_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank section_id.")
        if section_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate section_id {section_id}.")
        ids.add(section_id)
        domains.add(row.get("validation_domain", ""))
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {section_id or '(blank)'} is missing {column}.")
        if row.get("packet_status") != "template_only":
            errors.append(f"{MANIFEST_PATH} row {section_id} must remain template_only until validation evidence is complete.")
        if row.get("signoff_status") == "approved":
            errors.append(f"{MANIFEST_PATH} row {section_id} cannot be approved before completed validation signoff.")
    for section_id in sorted(REQUIRED_SECTIONS - ids):
        errors.append(f"{MANIFEST_PATH} is missing required section {section_id}.")
    for domain in sorted(REQUIRED_DOMAINS - domains):
        errors.append(f"{MANIFEST_PATH} is missing required validation_domain {domain}.")
    return errors


def _read_json_or_missing(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"status": "missing"}
    value = read_json(path)
    return value if isinstance(value, dict) else {"status": "invalid_json"}


def _nested_summary_value(summary: dict[str, Any], key: str) -> Any:
    nested = summary.get("summary", {})
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    return summary.get(key, "")


def validate_template_doc() -> list[str]:
    path = path_from_root(TEMPLATE_DOC_PATH)
    if not path.exists():
        return [f"{TEMPLATE_DOC_PATH} is missing."]
    text = read_text(path)
    errors: list[str] = []
    for phrase in [
        "template only",
        "Clinical reporting allowed: no",
        "Reportable range locked: no",
        "not approved",
        "no-call",
        "Change control",
    ]:
        if phrase not in text:
            errors.append(f"{TEMPLATE_DOC_PATH} must include phrase {phrase!r}.")
    return errors


def packet_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "section_id": row["section_id"],
            "section_title": row["section_title"],
            "validation_domain": row["validation_domain"],
            "current_evidence_status": row["current_evidence_status"],
            "packet_status": row["packet_status"],
            "signoff_status": row["signoff_status"],
            "ready_for_clinical_packet": "no",
            "blocking_dependency": row["blocking_dependency"],
        }
        for row in rows
    ]


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    errors.extend(validate_template_doc())
    boundaries = _read_json_or_missing(CLINICAL_BOUNDARIES_PATH)
    known_answer = _read_json_or_missing(KNOWN_ANSWER_READINESS_PATH)
    if boundaries.get("status") != "passed":
        errors.append(f"{CLINICAL_BOUNDARIES_PATH} must report passed clinical assay boundaries.")
    if _nested_summary_value(boundaries, "clinical_reporting_allowed") != "no":
        errors.append(f"{CLINICAL_BOUNDARIES_PATH} must keep clinical reporting disabled.")
    if _nested_summary_value(boundaries, "reportable_range_locked") != "no":
        errors.append(f"{CLINICAL_BOUNDARIES_PATH} must keep reportable range unlocked.")
    if known_answer.get("status") != "passed":
        errors.append(f"{KNOWN_ANSWER_READINESS_PATH} must report passed known-answer readiness.")
    if _nested_summary_value(known_answer, "locked_threshold_count") != 0:
        errors.append(f"{KNOWN_ANSWER_READINESS_PATH} must report locked_threshold_count=0.")
    output_rows = packet_rows(rows)
    summary = {
        "status": "passed" if not errors else "failed",
        "section_count": len(rows),
        "domain_count": len({row.get("validation_domain", "") for row in rows}),
        "template_only_section_count": sum(1 for row in rows if row.get("packet_status") == "template_only"),
        "approved_section_count": sum(1 for row in rows if row.get("signoff_status") == "approved"),
        "clinical_reporting_allowed": "no",
        "reportable_range_locked": "no",
        "packet_status": "template_only",
        "ready_for_clinical_packet": "no",
        "next_step": "Pause for operator review/commit, then decide whether to implement HG008/COLO829 benchmark runners or continue local governance scaffolding.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root("results/clinicalization"))
    write_csv(path_from_root(SUMMARY_CSV_PATH), output_rows)
    write_json(
        path_from_root(SUMMARY_JSON_PATH),
        {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": output_rows},
    )
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("Clinical validation packet verification passed.")


if __name__ == "__main__":
    main()
