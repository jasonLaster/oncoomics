from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/clinical_change_control_triggers.csv"
SUMMARY_CSV_PATH = "results/clinicalization/clinical_change_control_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/clinical_change_control_summary.json"

REQUIRED_COLUMNS = {
    "trigger_id",
    "trigger_domain",
    "change_type",
    "watched_artifact",
    "revalidation_scope",
    "impact_assessment_required",
    "owner_review_required",
    "clinical_release_allowed",
    "approval_status",
    "rollback_or_no_call_policy",
    "evidence_dependency",
    "next_action",
}
REQUIRED_TRIGGER_IDS = {
    "workflow_version_change",
    "reference_asset_change",
    "input_policy_change",
    "small_variant_caller_change",
    "cnv_loh_tool_change",
    "sv_caller_change",
    "hrd_adapter_change",
    "threshold_lock_change",
    "report_language_change",
    "benchmark_asset_change",
    "validation_packet_change",
    "clinical_signoff_change",
}
REQUIRED_DOMAINS = {
    "workflow",
    "reference",
    "preanalytic_qc",
    "accuracy",
    "model",
    "qc_thresholds",
    "reporting",
    "known_answer",
    "validation_packet",
    "signoff",
}


def manifest_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(MANIFEST_PATH)))


def _read_json_or_missing(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"status": "missing"}
    value = read_json(path)
    return value if isinstance(value, dict) else {"status": "invalid_json"}


def _dependency_paths(row: dict[str, str]) -> list[str]:
    return [value.strip() for value in row.get("evidence_dependency", "").split(";") if value.strip()]


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
        trigger_id = row.get("trigger_id", "")
        if not trigger_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank trigger_id.")
        if trigger_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate trigger_id {trigger_id}.")
        ids.add(trigger_id)
        domains.add(row.get("trigger_domain", ""))
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {trigger_id or '(blank)'} is missing {column}.")
        if row.get("impact_assessment_required") != "yes":
            errors.append(f"{MANIFEST_PATH} row {trigger_id} must require impact_assessment_required=yes.")
        if row.get("owner_review_required") != "yes":
            errors.append(f"{MANIFEST_PATH} row {trigger_id} must require owner_review_required=yes.")
        if row.get("clinical_release_allowed") != "no":
            errors.append(f"{MANIFEST_PATH} row {trigger_id} must keep clinical_release_allowed=no.")
        if row.get("approval_status") == "approved":
            errors.append(f"{MANIFEST_PATH} row {trigger_id} cannot be approved before validation signoff.")
        if "No " not in row.get("rollback_or_no_call_policy", ""):
            errors.append(f"{MANIFEST_PATH} row {trigger_id} must define a no-release/no-call policy.")
        dependencies = _dependency_paths(row)
        if not dependencies:
            errors.append(f"{MANIFEST_PATH} row {trigger_id} must reference at least one evidence dependency.")
        for dependency in dependencies:
            summary = _read_json_or_missing(dependency)
            if summary.get("status") != "passed":
                errors.append(f"{MANIFEST_PATH} row {trigger_id} dependency {dependency} must have status passed.")

    for trigger_id in sorted(REQUIRED_TRIGGER_IDS - ids):
        errors.append(f"{MANIFEST_PATH} is missing required trigger {trigger_id}.")
    for domain in sorted(REQUIRED_DOMAINS - domains):
        errors.append(f"{MANIFEST_PATH} is missing trigger_domain {domain}.")
    return errors


def summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "trigger_id": row["trigger_id"],
            "trigger_domain": row["trigger_domain"],
            "change_type": row["change_type"],
            "watched_artifact": row["watched_artifact"],
            "revalidation_scope": row["revalidation_scope"],
            "evidence_dependency_count": len(_dependency_paths(row)),
            "impact_assessment_required": row["impact_assessment_required"],
            "owner_review_required": row["owner_review_required"],
            "clinical_release_allowed": row["clinical_release_allowed"],
            "approval_status": row["approval_status"],
            "next_action": row["next_action"],
        }
        for row in rows
    ]


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    output_rows = summary_rows(rows)
    summary = {
        "status": "passed" if not errors else "failed",
        "trigger_count": len(rows),
        "domain_count": len({row.get("trigger_domain", "") for row in rows}),
        "impact_assessment_required_count": sum(1 for row in rows if row.get("impact_assessment_required") == "yes"),
        "owner_review_required_count": sum(1 for row in rows if row.get("owner_review_required") == "yes"),
        "clinical_release_allowed_count": sum(1 for row in rows if row.get("clinical_release_allowed") == "yes"),
        "approved_trigger_count": sum(1 for row in rows if row.get("approval_status") == "approved"),
        "evidence_dependency_reference_count": sum(row["evidence_dependency_count"] for row in output_rows),
        "change_control_ready_for_clinical_release": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Add explicit signoff workflow roles and release decision records after validation evidence sections are complete.",
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
    print("Clinical change-control verification passed.")


if __name__ == "__main__":
    main()
