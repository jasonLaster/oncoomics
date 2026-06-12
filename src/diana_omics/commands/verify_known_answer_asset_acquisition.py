from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json
from .plan_known_answer_benchmarks import PLAN_MANIFEST_PATH

ACQUISITION_MANIFEST_PATH = "manifests/known_answer_asset_acquisition_plan.csv"
SUMMARY_CSV_PATH = "results/clinicalization/known_answer_asset_acquisition_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_asset_acquisition_summary.json"

REQUIRED_COLUMNS = {
    "acquisition_id",
    "manifest_path",
    "asset_kind",
    "dataset_id",
    "approval_status",
    "acquisition_mode",
    "estimated_cost_class",
    "raw_data_upload_allowed",
    "execution_allowed",
    "checksum_required_before_use",
    "clinical_use_allowed",
    "owner_review_required",
    "next_action",
}
ACCEPTED_APPROVAL_STATUS = {"not_requested", "requested", "approved", "rejected", "blocked"}
ACCEPTED_ACQUISITION_MODE = {"metadata_only_until_approval", "approved_source_download", "verified_local_pointer"}
ACCEPTED_COST_CLASS = {"low", "medium", "high"}


def _read_csv(relative_path: str) -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(relative_path)))


def planned_manifest_paths() -> dict[str, dict[str, str]]:
    paths: dict[str, dict[str, str]] = {}
    for row in _read_csv(PLAN_MANIFEST_PATH):
        paths[row["input_manifest_path"]] = {"asset_kind": "input", "dataset_id": row["dataset_id"]}
        paths[row["truth_asset_manifest"]] = {"asset_kind": "truth", "dataset_id": row["dataset_id"]}
    return paths


def acquisition_rows() -> list[dict[str, str]]:
    return _read_csv(ACQUISITION_MANIFEST_PATH)


def validate_acquisition_plan(planned_paths: dict[str, dict[str, str]], rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return [f"{ACQUISITION_MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"{ACQUISITION_MANIFEST_PATH} is missing required column {column}.")

    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for row in rows:
        acquisition_id = row.get("acquisition_id", "")
        manifest_path = row.get("manifest_path", "")
        if not acquisition_id:
            errors.append(f"{ACQUISITION_MANIFEST_PATH} has a row with blank acquisition_id.")
        if acquisition_id in seen_ids:
            errors.append(f"{ACQUISITION_MANIFEST_PATH} has duplicate acquisition_id {acquisition_id}.")
        seen_ids.add(acquisition_id)
        if manifest_path in seen_paths:
            errors.append(f"{ACQUISITION_MANIFEST_PATH} has duplicate manifest_path {manifest_path}.")
        seen_paths.add(manifest_path)
        if manifest_path not in planned_paths:
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} references unplanned manifest_path {manifest_path}.")
        else:
            planned = planned_paths[manifest_path]
            if row.get("asset_kind") != planned["asset_kind"]:
                errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} asset_kind must be {planned['asset_kind']}.")
            if row.get("dataset_id") != planned["dataset_id"]:
                errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} dataset_id must be {planned['dataset_id']}.")
        if row.get("approval_status") not in ACCEPTED_APPROVAL_STATUS:
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} has invalid approval_status.")
        if row.get("acquisition_mode") not in ACCEPTED_ACQUISITION_MODE:
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} has invalid acquisition_mode.")
        if row.get("estimated_cost_class") not in ACCEPTED_COST_CLASS:
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} has invalid estimated_cost_class.")
        if row.get("raw_data_upload_allowed") != "no":
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} must keep raw_data_upload_allowed=no.")
        if row.get("execution_allowed") != "no":
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} must keep execution_allowed=no until explicit approval and checksum capture.")
        if row.get("checksum_required_before_use") != "yes":
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} must require checksum capture before use.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} must keep clinical_use_allowed=no.")
        if row.get("owner_review_required") != "yes":
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} must require owner_review_required=yes.")
        if not row.get("next_action", "").strip():
            errors.append(f"{ACQUISITION_MANIFEST_PATH} row {acquisition_id} must define next_action.")

    for manifest_path in sorted(set(planned_paths) - seen_paths):
        errors.append(f"{ACQUISITION_MANIFEST_PATH} is missing acquisition planning for {manifest_path}.")
    return errors


def summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "acquisition_id": row["acquisition_id"],
            "manifest_path": row["manifest_path"],
            "asset_kind": row["asset_kind"],
            "dataset_id": row["dataset_id"],
            "approval_status": row["approval_status"],
            "acquisition_mode": row["acquisition_mode"],
            "estimated_cost_class": row["estimated_cost_class"],
            "raw_data_upload_allowed": row["raw_data_upload_allowed"],
            "execution_allowed": row["execution_allowed"],
            "checksum_required_before_use": row["checksum_required_before_use"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "owner_review_required": row["owner_review_required"],
            "next_action": row["next_action"],
        }
        for row in rows
    ]


def main() -> None:
    planned_paths = planned_manifest_paths()
    rows = acquisition_rows()
    errors = validate_acquisition_plan(planned_paths, rows)
    output_rows = summary_rows(rows)
    approved_count = sum(1 for row in rows if row.get("approval_status") == "approved")
    summary = {
        "status": "passed" if not errors else "failed",
        "asset_group_count": len(rows),
        "planned_manifest_count": len(planned_paths),
        "approved_count": approved_count,
        "execution_allowed_count": sum(1 for row in rows if row.get("execution_allowed") == "yes"),
        "raw_data_upload_allowed_count": sum(1 for row in rows if row.get("raw_data_upload_allowed") == "yes"),
        "checksum_required_count": sum(1 for row in rows if row.get("checksum_required_before_use") == "yes"),
        "benchmark_execution_ready": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Prepare exact asset URLs access terms checksum sources and cost notes for owner approval before acquisition or benchmark execution.",
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
    print("Known-answer asset acquisition planning verification passed.")


if __name__ == "__main__":
    main()
