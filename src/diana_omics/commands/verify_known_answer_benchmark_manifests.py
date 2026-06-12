from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json
from .plan_known_answer_benchmarks import PLAN_MANIFEST_PATH

SUMMARY_CSV_PATH = "results/clinicalization/known_answer_benchmark_manifest_schema_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_benchmark_manifest_schema_summary.json"

INPUT_REQUIRED_COLUMNS = {
    "input_id",
    "dataset_id",
    "sample_id",
    "sample_role",
    "sample_pair",
    "reference_build",
    "source_status",
    "local_path_required",
    "source_url",
    "expected_file_type",
    "clinical_use_allowed",
    "caveat",
}
TRUTH_REQUIRED_COLUMNS = {
    "truth_asset_id",
    "dataset_id",
    "fixture_id",
    "truth_scope",
    "reference_build",
    "asset_status",
    "source_url",
    "expected_file_type",
    "required_for_execution",
    "clinical_use_allowed",
    "no_call_if_missing",
    "caveat",
}


def plan_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(PLAN_MANIFEST_PATH)))


def _read_manifest(relative_path: str) -> list[dict[str, str]]:
    path = path_from_root(relative_path)
    if not path.exists():
        return []
    return parse_csv(read_text(path))


def _validate_columns(relative_path: str, rows: list[dict[str, str]], required: set[str]) -> list[str]:
    if not rows:
        return [f"{relative_path} is missing or has no rows."]
    missing = required - set(rows[0])
    return [f"{relative_path} is missing required column {column}." for column in sorted(missing)]


def validate_input_manifest(relative_path: str, dataset_id: str) -> list[str]:
    rows = _read_manifest(relative_path)
    errors = _validate_columns(relative_path, rows, INPUT_REQUIRED_COLUMNS)
    roles = {row.get("sample_role", "") for row in rows}
    for row in rows:
        input_id = row.get("input_id", "(blank)")
        if row.get("dataset_id") != dataset_id:
            errors.append(f"{relative_path} row {input_id} dataset_id must be {dataset_id}.")
        if row.get("source_status") != "planned_not_downloaded":
            errors.append(f"{relative_path} row {input_id} must remain planned_not_downloaded before approval.")
        if row.get("local_path_required") != "no":
            errors.append(f"{relative_path} row {input_id} must keep local_path_required=no before approval.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{relative_path} row {input_id} must keep clinical_use_allowed=no.")
        if not row.get("source_url", "").startswith("http"):
            errors.append(f"{relative_path} row {input_id} must include a public source URL.")
        if row.get("reference_build") not in {"GRCh38", "GRCh37"}:
            errors.append(f"{relative_path} row {input_id} must declare GRCh38 or GRCh37.")
    if "normal" not in roles and not any(role.startswith("normal") for role in roles):
        errors.append(f"{relative_path} must include a normal/control input row.")
    if not any(role.startswith("tumor") for role in roles):
        errors.append(f"{relative_path} must include a tumor input row.")
    return errors


def validate_truth_manifest(relative_path: str, dataset_id: str, fixture_id: str) -> list[str]:
    rows = _read_manifest(relative_path)
    errors = _validate_columns(relative_path, rows, TRUTH_REQUIRED_COLUMNS)
    for row in rows:
        asset_id = row.get("truth_asset_id", "(blank)")
        if row.get("dataset_id") != dataset_id:
            errors.append(f"{relative_path} row {asset_id} dataset_id must be {dataset_id}.")
        if row.get("fixture_id") != fixture_id:
            errors.append(f"{relative_path} row {asset_id} fixture_id must be {fixture_id}.")
        if row.get("asset_status") != "planned_not_downloaded":
            errors.append(f"{relative_path} row {asset_id} must remain planned_not_downloaded before approval.")
        if row.get("required_for_execution") != "yes":
            errors.append(f"{relative_path} row {asset_id} must set required_for_execution=yes.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{relative_path} row {asset_id} must keep clinical_use_allowed=no.")
        if row.get("no_call_if_missing") != "yes":
            errors.append(f"{relative_path} row {asset_id} must set no_call_if_missing=yes.")
        if not row.get("source_url", "").startswith("http"):
            errors.append(f"{relative_path} row {asset_id} must include a public source URL.")
        if row.get("reference_build") not in {"GRCh38", "GRCh37"}:
            errors.append(f"{relative_path} row {asset_id} must declare GRCh38 or GRCh37.")
    return errors


def schema_rows(plans: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    output_rows: list[dict[str, Any]] = []
    for plan in plans:
        benchmark_id = plan["benchmark_id"]
        dataset_id = plan["dataset_id"]
        fixture_id = plan["fixture_id"]
        input_path = plan["input_manifest_path"]
        truth_path = plan["truth_asset_manifest"]
        input_errors = validate_input_manifest(input_path, dataset_id)
        truth_errors = validate_truth_manifest(truth_path, dataset_id, fixture_id)
        errors.extend(input_errors)
        errors.extend(truth_errors)
        output_rows.append(
            {
                "benchmark_id": benchmark_id,
                "fixture_id": fixture_id,
                "dataset_id": dataset_id,
                "input_manifest_path": input_path,
                "truth_asset_manifest": truth_path,
                "input_manifest_status": "passed" if not input_errors else "failed",
                "truth_manifest_status": "passed" if not truth_errors else "failed",
                "benchmark_execution_ready": "no",
                "clinical_use_allowed": "no",
                "next_action": "Add checksum and reference-build compatibility checks before approved benchmark execution.",
            }
        )
    return output_rows, errors


def main() -> None:
    plans = plan_rows()
    rows, errors = schema_rows(plans)
    unique_input_manifests = {row["input_manifest_path"] for row in rows}
    unique_truth_manifests = {row["truth_asset_manifest"] for row in rows}
    summary = {
        "status": "passed" if not errors else "failed",
        "benchmark_count": len(plans),
        "input_manifest_count": len(unique_input_manifests),
        "truth_manifest_count": len(unique_truth_manifests),
        "benchmark_execution_ready": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Add checksum and reference-build compatibility checks before any approved benchmark execution.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root(Path(SUMMARY_CSV_PATH).parent))
    write_csv(path_from_root(SUMMARY_CSV_PATH), rows)
    write_json(path_from_root(SUMMARY_JSON_PATH), {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": rows})
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("Known-answer benchmark manifest schema verification passed.")


if __name__ == "__main__":
    main()
