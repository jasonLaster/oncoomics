from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/clinical_signoff_workflow.csv"
SUMMARY_CSV_PATH = "results/clinicalization/clinical_signoff_workflow_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/clinical_signoff_workflow_summary.json"

REQUIRED_COLUMNS = {
    "signoff_id",
    "review_role",
    "review_domain",
    "required_evidence_paths",
    "decision_status",
    "release_allowed",
    "clinical_use_allowed",
    "signoff_required",
    "blocking_condition",
    "next_action",
}
REQUIRED_ROLES = {
    "assay_owner",
    "bioinformatics_owner",
    "clinical_scientist",
    "quality_reviewer",
    "laboratory_director",
}
ACCEPTED_DECISION_STATUS = {"pending", "approved", "rejected", "blocked"}


def manifest_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(MANIFEST_PATH)))


def _read_json_or_missing(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"status": "missing"}
    value = read_json(path)
    return value if isinstance(value, dict) else {"status": "invalid_json"}


def _evidence_paths(row: dict[str, str]) -> list[str]:
    return [value.strip() for value in row.get("required_evidence_paths", "").split(";") if value.strip()]


def validate_manifest(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return [f"{MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"{MANIFEST_PATH} is missing required column {column}.")

    ids: set[str] = set()
    roles: set[str] = set()
    for row in rows:
        signoff_id = row.get("signoff_id", "")
        role = row.get("review_role", "")
        if not signoff_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank signoff_id.")
        if signoff_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate signoff_id {signoff_id}.")
        ids.add(signoff_id)
        roles.add(role)
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {signoff_id or '(blank)'} is missing {column}.")
        if row.get("decision_status") not in ACCEPTED_DECISION_STATUS:
            errors.append(f"{MANIFEST_PATH} row {signoff_id} has invalid decision_status.")
        if row.get("decision_status") == "approved":
            errors.append(f"{MANIFEST_PATH} row {signoff_id} cannot be approved before completed validation evidence.")
        if row.get("release_allowed") != "no":
            errors.append(f"{MANIFEST_PATH} row {signoff_id} must keep release_allowed=no.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{MANIFEST_PATH} row {signoff_id} must keep clinical_use_allowed=no.")
        if row.get("signoff_required") != "yes":
            errors.append(f"{MANIFEST_PATH} row {signoff_id} must require signoff_required=yes.")
        evidence_paths = _evidence_paths(row)
        if not evidence_paths:
            errors.append(f"{MANIFEST_PATH} row {signoff_id} must reference required evidence.")
        for evidence_path in evidence_paths:
            summary = _read_json_or_missing(evidence_path)
            if summary.get("status") != "passed":
                errors.append(f"{MANIFEST_PATH} row {signoff_id} evidence {evidence_path} must have status passed.")
    for role in sorted(REQUIRED_ROLES - roles):
        errors.append(f"{MANIFEST_PATH} is missing required review_role {role}.")
    return errors


def summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "signoff_id": row["signoff_id"],
            "review_role": row["review_role"],
            "review_domain": row["review_domain"],
            "required_evidence_count": len(_evidence_paths(row)),
            "decision_status": row["decision_status"],
            "release_allowed": row["release_allowed"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "signoff_required": row["signoff_required"],
            "blocking_condition": row["blocking_condition"],
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
        "signoff_step_count": len(rows),
        "required_role_count": len({row.get("review_role", "") for row in rows}),
        "required_evidence_reference_count": sum(row["required_evidence_count"] for row in output_rows),
        "pending_decision_count": sum(1 for row in rows if row.get("decision_status") == "pending"),
        "approved_decision_count": sum(1 for row in rows if row.get("decision_status") == "approved"),
        "release_allowed_count": sum(1 for row in rows if row.get("release_allowed") == "yes"),
        "clinical_use_allowed_count": sum(1 for row in rows if row.get("clinical_use_allowed") == "yes"),
        "ready_for_clinical_release": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Convert pending signoff steps into named reviewer records only after validation evidence sections are complete.",
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
    print("Clinical signoff workflow verification passed.")


if __name__ == "__main__":
    main()
