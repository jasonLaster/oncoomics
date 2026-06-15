from __future__ import annotations

from pathlib import Path
from typing import Any

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/known_answer_sample_pull_plan.csv"
SUMMARY_CSV_PATH = "results/clinicalization/known_answer_sample_pull_plan_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_sample_pull_plan_summary.json"
MINIMUM_PULL_TARGETS = 10

REQUIRED_COLUMNS = {
    "pull_id",
    "priority",
    "dataset_id",
    "sample_or_asset_id",
    "asset_role",
    "modality",
    "source_access",
    "source_url",
    "expected_answer",
    "first_validation_gate",
    "planned_pull_mode",
    "estimated_transfer_cost_class",
    "checksum_required_before_use",
    "owner_review_required",
    "execution_allowed",
    "clinical_use_allowed",
    "no_call_if_unavailable",
    "caveat",
}

REQUIRED_DATASETS = {
    "giab_hg008",
    "colo829",
    "colo829_purity_series",
    "seraseq_ctdna_mrd",
}
REQUIRED_MODALITIES = {
    "tumor_normal_wgs",
    "tumor_rna_seq",
    "tumor_normal_wgs_dilution",
    "ctdna_mrd_reference",
}
REQUIRED_ASSET_ROLE_PREFIXES = {"tumor", "normal", "truth", "dilution", "ctdna"}
ACCEPTED_SOURCE_ACCESS = {"yes", "request_or_purchase"}
ACCEPTED_PULL_MODES = {"metadata_only_until_approval", "contact_or_purchase_required", "approved_source_download"}
ACCEPTED_COST_CLASS = {"low", "medium", "high", "request_or_purchase"}


def pull_plan_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(MANIFEST_PATH)))


def _role_prefix(role: str) -> str:
    return role.split("_", 1)[0]


def validate_pull_plan(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return [f"{MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"{MANIFEST_PATH} is missing required column {column}.")

    seen_ids: set[str] = set()
    datasets: set[str] = set()
    modalities: set[str] = set()
    role_prefixes: set[str] = set()
    for row in rows:
        pull_id = row.get("pull_id", "")
        datasets.add(row.get("dataset_id", ""))
        modalities.add(row.get("modality", ""))
        role_prefixes.add(_role_prefix(row.get("asset_role", "")))
        if not pull_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank pull_id.")
        if pull_id in seen_ids:
            errors.append(f"{MANIFEST_PATH} has duplicate pull_id {pull_id}.")
        seen_ids.add(pull_id)
        try:
            priority = int(row.get("priority", ""))
        except ValueError:
            priority = 0
        if priority < 1:
            errors.append(f"{MANIFEST_PATH} row {pull_id or '(blank)'} priority must be a positive integer.")
        if row.get("source_access") not in ACCEPTED_SOURCE_ACCESS:
            errors.append(f"{MANIFEST_PATH} row {pull_id} has invalid source_access.")
        if row.get("planned_pull_mode") not in ACCEPTED_PULL_MODES:
            errors.append(f"{MANIFEST_PATH} row {pull_id} has invalid planned_pull_mode.")
        if row.get("estimated_transfer_cost_class") not in ACCEPTED_COST_CLASS:
            errors.append(f"{MANIFEST_PATH} row {pull_id} has invalid estimated_transfer_cost_class.")
        if not row.get("source_url", "").startswith("http"):
            errors.append(f"{MANIFEST_PATH} row {pull_id} must include a public or vendor source URL.")
        if not row.get("expected_answer", "").strip():
            errors.append(f"{MANIFEST_PATH} row {pull_id} must define expected_answer.")
        if not row.get("first_validation_gate", "").strip():
            errors.append(f"{MANIFEST_PATH} row {pull_id} must define first_validation_gate.")
        if row.get("checksum_required_before_use") != "yes":
            errors.append(f"{MANIFEST_PATH} row {pull_id} must require checksum capture before use.")
        if row.get("owner_review_required") != "yes":
            errors.append(f"{MANIFEST_PATH} row {pull_id} must require owner_review_required=yes.")
        if row.get("execution_allowed") != "no":
            errors.append(f"{MANIFEST_PATH} row {pull_id} must keep execution_allowed=no until explicit approval.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{MANIFEST_PATH} row {pull_id} must keep clinical_use_allowed=no.")
        if row.get("no_call_if_unavailable") != "yes":
            errors.append(f"{MANIFEST_PATH} row {pull_id} must set no_call_if_unavailable=yes.")
        if row.get("source_access") == "request_or_purchase" and row.get("planned_pull_mode") != "contact_or_purchase_required":
            errors.append(f"{MANIFEST_PATH} row {pull_id} request_or_purchase targets must use contact_or_purchase_required.")

    if len(rows) < MINIMUM_PULL_TARGETS:
        errors.append(f"{MANIFEST_PATH} must define at least {MINIMUM_PULL_TARGETS} pull targets.")
    for dataset_id in sorted(REQUIRED_DATASETS - datasets):
        errors.append(f"{MANIFEST_PATH} is missing required dataset {dataset_id}.")
    for modality in sorted(REQUIRED_MODALITIES - modalities):
        errors.append(f"{MANIFEST_PATH} is missing required modality {modality}.")
    for prefix in sorted(REQUIRED_ASSET_ROLE_PREFIXES - role_prefixes):
        errors.append(f"{MANIFEST_PATH} is missing an asset_role beginning with {prefix}.")
    return errors


def summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "pull_id": row["pull_id"],
            "priority": row["priority"],
            "dataset_id": row["dataset_id"],
            "sample_or_asset_id": row["sample_or_asset_id"],
            "asset_role": row["asset_role"],
            "modality": row["modality"],
            "source_access": row["source_access"],
            "planned_pull_mode": row["planned_pull_mode"],
            "estimated_transfer_cost_class": row["estimated_transfer_cost_class"],
            "execution_allowed": row["execution_allowed"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "first_validation_gate": row["first_validation_gate"],
        }
        for row in rows
    ]


def main() -> None:
    rows = pull_plan_rows()
    errors = validate_pull_plan(rows)
    output_rows = summary_rows(rows)
    sample_input_count = sum(
        1 for row in rows if row.get("asset_role") in {"tumor", "normal", "tumor_rna", "dilution_series", "ctdna_reference"}
    )
    truth_asset_count = sum(1 for row in rows if row.get("asset_role", "").startswith("truth"))
    summary = {
        "status": "passed" if not errors else "failed",
        "pull_target_count": len(rows),
        "minimum_pull_target_count": MINIMUM_PULL_TARGETS,
        "dataset_count": len({row.get("dataset_id", "") for row in rows}),
        "sample_input_count": sample_input_count,
        "truth_asset_count": truth_asset_count,
        "request_or_purchase_count": sum(1 for row in rows if row.get("source_access") == "request_or_purchase"),
        "owner_review_required_count": sum(1 for row in rows if row.get("owner_review_required") == "yes"),
        "checksum_required_count": sum(1 for row in rows if row.get("checksum_required_before_use") == "yes"),
        "execution_allowed_count": sum(1 for row in rows if row.get("execution_allowed") == "yes"),
        "clinical_use_allowed_count": sum(1 for row in rows if row.get("clinical_use_allowed") == "yes"),
        "pending_pull_target_count": sum(1 for row in rows if row.get("planned_pull_mode") != "approved_source_download"),
        "ready_for_sample_acquisition": "no",
        "ready_for_benchmark_execution": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Owner review must approve source terms transfer costs and checksums before downloading or executing the expanded known-answer sample suite.",
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
    print(f"Known-answer sample pull plan verification passed: {len(rows)} pull targets.")


if __name__ == "__main__":
    main()
