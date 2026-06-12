from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/clinical_qc_threshold_locks.csv"
CLINICAL_BOUNDARIES_PATH = os.environ.get(
    "CLINICAL_QC_THRESHOLDS_BOUNDARIES", "results/clinicalization/clinical_assay_boundaries_summary.json"
)
SUMMARY_CSV_PATH = "results/clinicalization/clinical_qc_threshold_lock_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/clinical_qc_threshold_lock_summary.json"

REQUIRED_COLUMNS = {
    "threshold_id",
    "threshold_domain",
    "feature_class",
    "metric_name",
    "threshold_kind",
    "proposed_threshold",
    "lock_status",
    "evidence_dependency",
    "no_call_if_unmet",
    "reportable_range_impact",
    "clinical_use_allowed",
    "signoff_status",
    "next_action",
}
REQUIRED_THRESHOLD_IDS = {
    "raw_input_identity",
    "sample_pairing_qc",
    "bam_reference_compatibility",
    "bam_coverage_acceptance",
    "small_variant_concordance",
    "allele_specific_cnv_loh_overlap",
    "sv_caller_overlap",
    "signature_mutation_count",
    "integrated_hrd_model_inputs",
    "report_generation_gate",
}
REQUIRED_DOMAINS = {"preanalytic_qc", "alignment_qc", "accuracy_qc", "signature_qc", "model_qc", "reporting_qc"}
REQUIRED_FEATURE_CLASSES = {"input", "alignment", "small_variant", "cnv_loh", "sv", "signature", "integrated_hrd", "reporting"}
ACCEPTED_THRESHOLD_KINDS = {"qualitative", "quantitative"}
ACCEPTED_LOCK_STATUSES = {"draft_not_locked", "locked"}


def manifest_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(MANIFEST_PATH)))


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


def validate_manifest(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return [f"{MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"{MANIFEST_PATH} is missing required column {column}.")

    ids: set[str] = set()
    domains: set[str] = set()
    feature_classes: set[str] = set()
    for row in rows:
        threshold_id = row.get("threshold_id", "")
        if not threshold_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank threshold_id.")
        if threshold_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate threshold_id {threshold_id}.")
        ids.add(threshold_id)
        domains.add(row.get("threshold_domain", ""))
        feature_classes.add(row.get("feature_class", ""))
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {threshold_id or '(blank)'} is missing {column}.")
        if row.get("threshold_kind") not in ACCEPTED_THRESHOLD_KINDS:
            errors.append(f"{MANIFEST_PATH} row {threshold_id} has invalid threshold_kind.")
        if row.get("lock_status") not in ACCEPTED_LOCK_STATUSES:
            errors.append(f"{MANIFEST_PATH} row {threshold_id} has invalid lock_status.")
        if row.get("lock_status") == "locked":
            errors.append(f"{MANIFEST_PATH} row {threshold_id} cannot lock thresholds before validation evidence and signoff.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{MANIFEST_PATH} row {threshold_id} must keep clinical_use_allowed=no.")
        if row.get("signoff_status") == "approved":
            errors.append(f"{MANIFEST_PATH} row {threshold_id} cannot be approved before validation packet signoff.")
        if row.get("no_call_if_unmet") != "yes":
            errors.append(f"{MANIFEST_PATH} row {threshold_id} must set no_call_if_unmet=yes.")
        if "No " not in row.get("reportable_range_impact", ""):
            errors.append(f"{MANIFEST_PATH} row {threshold_id} must define explicit no-call reportable-range impact.")

    for threshold_id in sorted(REQUIRED_THRESHOLD_IDS - ids):
        errors.append(f"{MANIFEST_PATH} is missing required threshold {threshold_id}.")
    for domain in sorted(REQUIRED_DOMAINS - domains):
        errors.append(f"{MANIFEST_PATH} is missing threshold_domain {domain}.")
    for feature_class in sorted(REQUIRED_FEATURE_CLASSES - feature_classes):
        errors.append(f"{MANIFEST_PATH} is missing feature_class {feature_class}.")
    return errors


def threshold_summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "threshold_id": row["threshold_id"],
            "threshold_domain": row["threshold_domain"],
            "feature_class": row["feature_class"],
            "threshold_kind": row["threshold_kind"],
            "proposed_threshold": row["proposed_threshold"],
            "lock_status": row["lock_status"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "signoff_status": row["signoff_status"],
            "no_call_if_unmet": row["no_call_if_unmet"],
            "ready_for_clinical_interpretation": "no",
            "next_action": row["next_action"],
        }
        for row in rows
    ]


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    boundaries = _read_json_or_missing(CLINICAL_BOUNDARIES_PATH)
    if boundaries.get("status") != "passed":
        errors.append(f"{CLINICAL_BOUNDARIES_PATH} must report passed clinical assay boundaries.")
    if _nested_summary_value(boundaries, "clinical_reporting_allowed") != "no":
        errors.append(f"{CLINICAL_BOUNDARIES_PATH} must keep clinical reporting disabled.")
    if _nested_summary_value(boundaries, "reportable_range_locked") != "no":
        errors.append(f"{CLINICAL_BOUNDARIES_PATH} must keep reportable range unlocked.")

    output_rows = threshold_summary_rows(rows)
    locked_count = sum(1 for row in rows if row.get("lock_status") == "locked")
    summary = {
        "status": "passed" if not errors else "failed",
        "threshold_count": len(rows),
        "domain_count": len({row.get("threshold_domain", "") for row in rows}),
        "feature_class_count": len({row.get("feature_class", "") for row in rows}),
        "locked_threshold_count": locked_count,
        "draft_not_locked_count": sum(1 for row in rows if row.get("lock_status") == "draft_not_locked"),
        "clinical_use_allowed_count": sum(1 for row in rows if row.get("clinical_use_allowed") == "yes"),
        "reportable_range_locked": "no",
        "clinical_reporting_allowed": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Populate threshold values from known-answer validation evidence and reviewer signoff before any lock_status=locked change.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root(Path(SUMMARY_CSV_PATH).parent))
    write_csv(path_from_root(SUMMARY_CSV_PATH), output_rows)
    write_json(
        path_from_root(SUMMARY_JSON_PATH),
        {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": output_rows},
    )
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("Clinical QC threshold lock verification passed.")


if __name__ == "__main__":
    main()
