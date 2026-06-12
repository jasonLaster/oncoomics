from __future__ import annotations

import os
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/clinical_assay_claim_boundaries.csv"
KNOWN_ANSWER_READINESS_PATH = os.environ.get(
    "CLINICAL_ASSAY_KNOWN_ANSWER_READINESS", "results/clinicalization/known_answer_fixture_readiness_summary.json"
)
HRD_INTERPRETATION_READINESS_PATH = os.environ.get(
    "CLINICAL_ASSAY_HRD_INTERPRETATION_READINESS", "results/clinicalization/hrd_interpretation_readiness_summary.json"
)
SUMMARY_CSV_PATH = "results/clinicalization/clinical_assay_boundaries_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/clinical_assay_boundaries_summary.json"
REQUIRED_COLUMNS = {
    "boundary_id",
    "boundary_type",
    "requirement",
    "current_policy",
    "permitted_report_language",
    "prohibited_language",
    "evidence_dependency",
    "current_status",
    "signoff_status",
    "caveat",
}
REQUIRED_BOUNDARY_IDS = {
    "intended_use_candidate",
    "reportable_range_wgs_hrd",
    "qc_raw_fastq",
    "qc_alignment_bam",
    "qc_small_variant",
    "qc_cnv_loh",
    "qc_sv",
    "qc_signature",
    "report_no_call_language",
    "report_candidate_language",
    "prohibit_treatment_recommendation",
    "reviewer_signoff",
}
REQUIRED_TYPES = {"assay_claim", "reportable_range", "qc_gate", "report_language", "exclusion", "signoff"}
PROHIBITED_READY_STATUSES = {"clinical_ready", "approved", "locked"}


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
    types: set[str] = set()
    for row in rows:
        boundary_id = row.get("boundary_id", "")
        if not boundary_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank boundary_id.")
        if boundary_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate boundary_id {boundary_id}.")
        ids.add(boundary_id)
        boundary_type = row.get("boundary_type", "")
        types.add(boundary_type)
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {boundary_id or '(blank)'} is missing {column}.")
        if row.get("current_status") in PROHIBITED_READY_STATUSES:
            errors.append(f"{MANIFEST_PATH} row {boundary_id} cannot be marked clinically ready before validation.")
        if row.get("signoff_status") == "approved":
            errors.append(f"{MANIFEST_PATH} row {boundary_id} cannot be approved before validation packet signoff.")
        if boundary_type == "report_language" and not row.get("prohibited_language", ""):
            errors.append(f"{MANIFEST_PATH} row {boundary_id} must define prohibited report language.")
    for boundary_id in sorted(REQUIRED_BOUNDARY_IDS - ids):
        errors.append(f"{MANIFEST_PATH} is missing required boundary {boundary_id}.")
    for boundary_type in sorted(REQUIRED_TYPES - types):
        errors.append(f"{MANIFEST_PATH} is missing required boundary_type {boundary_type}.")
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


def boundary_summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "boundary_id": row["boundary_id"],
            "boundary_type": row["boundary_type"],
            "current_status": row["current_status"],
            "signoff_status": row["signoff_status"],
            "clinical_reporting_allowed": "no",
            "reportable_range_locked": "no" if row["boundary_type"] == "reportable_range" else "",
            "permitted_report_language": row["permitted_report_language"],
            "prohibited_language": row["prohibited_language"],
        }
        for row in rows
    ]


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    known_answer = _read_json_or_missing(KNOWN_ANSWER_READINESS_PATH)
    hrd_interpretation = _read_json_or_missing(HRD_INTERPRETATION_READINESS_PATH)
    if known_answer.get("status") != "passed":
        errors.append(f"{KNOWN_ANSWER_READINESS_PATH} must report passed known-answer readiness.")
    if _nested_summary_value(known_answer, "ready_for_clinical_interpretation") != "no":
        errors.append(f"{KNOWN_ANSWER_READINESS_PATH} must keep clinical interpretation disabled.")
    if _nested_summary_value(known_answer, "locked_threshold_count") != 0:
        errors.append(f"{KNOWN_ANSWER_READINESS_PATH} must report locked_threshold_count=0.")
    if hrd_interpretation.get("status") != "passed":
        errors.append(f"{HRD_INTERPRETATION_READINESS_PATH} must report passed HRD interpretation readiness.")
    if _nested_summary_value(hrd_interpretation, "ready_for_clinical_interpretation") != "no":
        errors.append(f"{HRD_INTERPRETATION_READINESS_PATH} must keep clinical interpretation disabled.")
    summary_rows = boundary_summary_rows(rows)
    summary = {
        "status": "passed" if not errors else "failed",
        "boundary_count": len(rows),
        "qc_gate_count": sum(1 for row in rows if row.get("boundary_type") == "qc_gate"),
        "report_language_count": sum(1 for row in rows if row.get("boundary_type") == "report_language"),
        "clinical_reporting_allowed": "no",
        "assay_claim_status": "candidate_definition_only",
        "reportable_range_locked": "no",
        "clinical_signoff_status": "not_approved",
        "known_answer_ready_for_clinical_interpretation": _nested_summary_value(known_answer, "ready_for_clinical_interpretation"),
        "locked_threshold_count": _nested_summary_value(known_answer, "locked_threshold_count"),
        "next_step": "Prepare the CLIA/CAP validation packet template for accuracy, precision, LoD, reproducibility, reportable range, failure modes, and change control.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root("results/clinicalization"))
    write_csv(path_from_root(SUMMARY_CSV_PATH), summary_rows)
    write_json(
        path_from_root(SUMMARY_JSON_PATH),
        {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": summary_rows},
    )
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("Clinical assay boundary verification passed.")


if __name__ == "__main__":
    main()
