from __future__ import annotations

import argparse
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json
from .plan_known_answer_benchmarks import PLAN_MANIFEST_PATH

DRY_RUN_ROOT = "results/clinicalization/known_answer_benchmarks"
DRY_RUN_SUMMARY_CSV_PATH = "results/clinicalization/known_answer_benchmark_dry_run_summary.csv"
DRY_RUN_SUMMARY_JSON_PATH = "results/clinicalization/known_answer_benchmark_dry_run_summary.json"


def benchmark_plan_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(PLAN_MANIFEST_PATH)))


def required_outputs(row: dict[str, str]) -> list[str]:
    return [value.strip() for value in row.get("required_outputs", "").split(";") if value.strip()]


def select_plan(rows: list[dict[str, str]], fixture_id: str) -> dict[str, str]:
    matches = [row for row in rows if row.get("fixture_id") == fixture_id]
    if not matches:
        raise SystemExit(f"No known-answer benchmark plan found for fixture {fixture_id!r}.")
    if len(matches) > 1:
        raise SystemExit(f"Multiple known-answer benchmark plans found for fixture {fixture_id!r}.")
    return matches[0]


def dry_run_output_rows(plan: dict[str, str]) -> list[dict[str, Any]]:
    benchmark_id = plan["benchmark_id"]
    return [
        {
            "benchmark_id": benchmark_id,
            "fixture_id": plan["fixture_id"],
            "output_name": output_name,
            "planned_path": f"{DRY_RUN_ROOT}/{benchmark_id}/expected/{output_name}",
            "materialized": "no",
            "clinical_use_allowed": "no",
        }
        for output_name in required_outputs(plan)
    ]


def dry_run_summary_row(plan: dict[str, str]) -> dict[str, Any]:
    return {
        "benchmark_id": plan["benchmark_id"],
        "fixture_id": plan["fixture_id"],
        "dataset_id": plan["dataset_id"],
        "runner_mode": plan["runner_mode"],
        "dry_run_status": "passed",
        "required_output_count": len(required_outputs(plan)),
        "cache_namespace": plan["cache_namespace"],
        "input_manifest_path": plan["input_manifest_path"],
        "truth_asset_manifest": plan["truth_asset_manifest"],
        "approval_required": plan["approval_required"],
        "clinical_use_allowed": "no",
        "next_action": "Add checksum and reference-build compatibility checks before approved benchmark execution.",
    }


def existing_dry_run_rows() -> list[dict[str, Any]]:
    root = path_from_root(DRY_RUN_ROOT)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for plan_path in sorted(root.glob("*/dry_run_plan.json")):
        payload = read_json(plan_path)
        row = payload.get("summary_row", {}) if isinstance(payload, dict) else {}
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_aggregate_summary(rows: list[dict[str, Any]]) -> None:
    sorted_rows = sorted(rows, key=lambda row: str(row.get("benchmark_id", "")))
    summary = {
        "status": "passed",
        "dry_run_count": len(sorted_rows),
        "clinical_use_allowed_count": sum(1 for row in sorted_rows if row.get("clinical_use_allowed") == "yes"),
        "ready_for_benchmark_execution": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Add checksum and reference-build compatibility checks before any approved benchmark execution.",
        "error_count": 0,
    }
    write_csv(path_from_root(DRY_RUN_SUMMARY_CSV_PATH), sorted_rows)
    write_json(
        path_from_root(DRY_RUN_SUMMARY_JSON_PATH),
        {"generatedAt": iso_now(), "status": "passed", "errors": [], "summary": summary, "rows": sorted_rows},
    )


def write_dry_run(plan: dict[str, str]) -> None:
    benchmark_id = plan["benchmark_id"]
    output_dir = path_from_root(DRY_RUN_ROOT) / benchmark_id
    ensure_dir(output_dir / "expected")
    output_rows = dry_run_output_rows(plan)
    summary_row = dry_run_summary_row(plan)
    write_csv(output_dir / "expected_outputs_manifest.csv", output_rows)
    write_json(
        output_dir / "dry_run_plan.json",
        {
            "generatedAt": iso_now(),
            "status": "passed",
            "mode": "dry_run_only",
            "plan": plan,
            "summary_row": summary_row,
            "expectedOutputs": output_rows,
            "clinicalUseAllowed": "no",
            "executionAllowed": "no",
            "approvalRequired": plan["approval_required"],
            "noCallPolicy": plan["no_call_policy"],
        },
    )
    rows_by_id = {str(row.get("benchmark_id")): row for row in existing_dry_run_rows()}
    rows_by_id[benchmark_id] = summary_row
    write_aggregate_summary(list(rows_by_id.values()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare known-answer benchmark dry-run artifacts.")
    parser.add_argument("--fixture", required=True, help="Fixture id from manifests/known_answer_benchmark_plan.csv.")
    parser.add_argument("--dry-run", action="store_true", help="Required. Materialize dry-run artifacts only.")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("known-answer benchmark execution is not implemented; pass --dry-run")
    return args


def main() -> None:
    args = parse_args()
    plan = select_plan(benchmark_plan_rows(), args.fixture)
    if plan.get("execution_status") != "dry_run_only":
        raise SystemExit(f"Benchmark plan {plan['benchmark_id']} is not marked dry_run_only.")
    if plan.get("approval_required") != "yes":
        raise SystemExit(f"Benchmark plan {plan['benchmark_id']} must require approval.")
    if plan.get("clinical_use_allowed") != "no":
        raise SystemExit(f"Benchmark plan {plan['benchmark_id']} must keep clinical_use_allowed=no.")
    write_dry_run(plan)
    print(f"Known-answer benchmark dry run passed for {plan['benchmark_id']}.")


if __name__ == "__main__":
    main()
