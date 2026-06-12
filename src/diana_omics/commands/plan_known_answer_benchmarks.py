from __future__ import annotations

from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json
from .verify_known_answer_readiness import MANIFEST_PATH as FIXTURE_MANIFEST_PATH

PLAN_MANIFEST_PATH = "manifests/known_answer_benchmark_plan.csv"
SUMMARY_CSV_PATH = "results/clinicalization/known_answer_benchmark_plan_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_benchmark_plan_summary.json"

REQUIRED_COLUMNS = {
    "benchmark_id",
    "fixture_id",
    "dataset_id",
    "runner_mode",
    "input_manifest_path",
    "truth_asset_manifest",
    "planned_command",
    "required_outputs",
    "cache_namespace",
    "execution_status",
    "approval_required",
    "cost_class",
    "clinical_use_allowed",
    "no_call_policy",
}


def fixture_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(FIXTURE_MANIFEST_PATH)))


def plan_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(PLAN_MANIFEST_PATH)))


def validate_plan(fixtures: list[dict[str, str]], plans: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not plans:
        return [f"{PLAN_MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(plans[0])
    for column in sorted(missing_columns):
        errors.append(f"{PLAN_MANIFEST_PATH} is missing required column {column}.")

    fixture_by_id = {row.get("fixture_id", ""): row for row in fixtures}
    planned_fixture_ids: set[str] = set()
    benchmark_ids: set[str] = set()
    cache_namespaces: set[str] = set()
    for row in plans:
        benchmark_id = row.get("benchmark_id", "")
        fixture_id = row.get("fixture_id", "")
        if not benchmark_id:
            errors.append(f"{PLAN_MANIFEST_PATH} has a row with blank benchmark_id.")
        if benchmark_id in benchmark_ids:
            errors.append(f"{PLAN_MANIFEST_PATH} has duplicate benchmark_id {benchmark_id}.")
        benchmark_ids.add(benchmark_id)
        if fixture_id not in fixture_by_id:
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id or '(blank)'} references unknown fixture_id {fixture_id}.")
            continue
        planned_fixture_ids.add(fixture_id)
        fixture = fixture_by_id[fixture_id]
        if row.get("dataset_id") != fixture.get("dataset_id"):
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id} dataset_id must match fixture {fixture_id}.")
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id or '(blank)'} is missing {column}.")
        if row.get("execution_status") != "dry_run_only":
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id} must remain dry_run_only until benchmark execution is approved.")
        if row.get("approval_required") != "yes":
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id} must require approval before costly benchmark execution.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id} must keep clinical_use_allowed=no.")
        if "--dry-run" not in row.get("planned_command", ""):
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id} planned_command must include --dry-run.")
        outputs = [value for value in row.get("required_outputs", "").split(";") if value.strip()]
        if len(outputs) < 2:
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id} must define at least two required outputs.")
        cache_namespace = row.get("cache_namespace", "")
        if cache_namespace in cache_namespaces:
            errors.append(f"{PLAN_MANIFEST_PATH} has duplicate cache_namespace {cache_namespace}.")
        cache_namespaces.add(cache_namespace)
        no_call_policy = row.get("no_call_policy", "")
        if "No-call" not in no_call_policy:
            errors.append(f"{PLAN_MANIFEST_PATH} row {benchmark_id} must define explicit no-call behavior.")

    missing_plans = set(fixture_by_id) - planned_fixture_ids
    for fixture_id in sorted(missing_plans):
        errors.append(f"{PLAN_MANIFEST_PATH} is missing a dry-run benchmark plan for fixture {fixture_id}.")
    return errors


def summary_rows(plans: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "benchmark_id": row["benchmark_id"],
            "fixture_id": row["fixture_id"],
            "dataset_id": row["dataset_id"],
            "runner_mode": row["runner_mode"],
            "execution_status": row["execution_status"],
            "approval_required": row["approval_required"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "required_output_count": len([value for value in row["required_outputs"].split(";") if value.strip()]),
            "cache_namespace": row["cache_namespace"],
            "next_action": "Run benchmark:known-answer --fixture <fixture_id> --dry-run before adding local input/truth manifest validation.",
        }
        for row in plans
    ]


def main() -> None:
    fixtures = fixture_rows()
    plans = plan_rows()
    errors = validate_plan(fixtures, plans)
    output_rows = summary_rows(plans)
    summary = {
        "status": "passed" if not errors else "failed",
        "benchmark_count": len(plans),
        "fixture_count": len(fixtures),
        "dry_run_only_count": sum(1 for row in plans if row.get("execution_status") == "dry_run_only"),
        "approval_required_count": sum(1 for row in plans if row.get("approval_required") == "yes"),
        "clinical_use_allowed_count": sum(1 for row in plans if row.get("clinical_use_allowed") == "yes"),
        "ready_for_benchmark_execution": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Run benchmark:known-answer --fixture <fixture_id> --dry-run for each known-answer fixture, then add input/truth manifest schema validation.",
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
    print("Known-answer benchmark plan verification passed.")


if __name__ == "__main__":
    main()
