from __future__ import annotations

import os
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/clinical_known_answer_fixtures.csv"
PHASE3_SUMMARY_PATH = os.environ.get("KNOWN_ANSWER_PHASE3_SUMMARY", "results/phase3_wgs_smoke/phase3_wgs_summary.json")
HRD_INTERPRETATION_READINESS_PATH = os.environ.get(
    "KNOWN_ANSWER_HRD_INTERPRETATION_READINESS", "results/clinicalization/hrd_interpretation_readiness_summary.json"
)
BENCHMARK_PLAN_SUMMARY_PATH = os.environ.get(
    "KNOWN_ANSWER_BENCHMARK_PLAN_SUMMARY", "results/clinicalization/known_answer_benchmark_plan_summary.json"
)
BENCHMARK_MANIFEST_SCHEMA_SUMMARY_PATH = os.environ.get(
    "KNOWN_ANSWER_BENCHMARK_MANIFEST_SCHEMA_SUMMARY",
    "results/clinicalization/known_answer_benchmark_manifest_schema_summary.json",
)
SUMMARY_CSV_PATH = "results/clinicalization/known_answer_fixture_readiness_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_fixture_readiness_summary.json"
REQUIRED_COLUMNS = {
    "fixture_id",
    "priority",
    "dataset_id",
    "sample_pair",
    "modality",
    "truth_scope",
    "required_truth_or_expected_answer",
    "required_output",
    "clinicalization_gate",
    "current_status",
    "threshold_status",
    "source_url",
    "caveat",
}
REQUIRED_DATASETS = {"giab_hg008", "colo829", "colo829_purity_series"}
REQUIRED_TRUTH_SCOPES = {
    "small_variant_snv_indel",
    "sv_cnv",
    "signature_qc",
    "driver_signature_guardrail",
    "sv_cna",
    "dilution_sensitivity",
}
REQUIRED_GATES = {
    "small_variant_feature_validation",
    "sv_cnv_feature_validation",
    "signature_adapter_validation",
    "negative_guardrail_validation",
    "limit_of_detection_stress_validation",
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
    datasets: set[str] = set()
    truth_scopes: set[str] = set()
    gates: set[str] = set()
    for row in rows:
        fixture_id = row.get("fixture_id", "")
        if not fixture_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank fixture_id.")
        if fixture_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate fixture_id {fixture_id}.")
        ids.add(fixture_id)
        datasets.add(row.get("dataset_id", ""))
        truth_scopes.add(row.get("truth_scope", ""))
        gates.add(row.get("clinicalization_gate", ""))
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {fixture_id or '(blank)'} is missing {column}.")
        if row.get("current_status") != "planned_not_run":
            errors.append(f"{MANIFEST_PATH} row {fixture_id} must remain planned_not_run until an approved benchmark run exists.")
        if row.get("threshold_status") == "locked":
            errors.append(f"{MANIFEST_PATH} row {fixture_id} cannot lock thresholds before fixture execution.")
    for dataset_id in sorted(REQUIRED_DATASETS - datasets):
        errors.append(f"{MANIFEST_PATH} is missing required dataset {dataset_id}.")
    for truth_scope in sorted(REQUIRED_TRUTH_SCOPES - truth_scopes):
        errors.append(f"{MANIFEST_PATH} is missing required truth_scope {truth_scope}.")
    for gate in sorted(REQUIRED_GATES - gates):
        errors.append(f"{MANIFEST_PATH} is missing required clinicalization_gate {gate}.")
    return errors


def _read_json_or_missing(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"status": "missing"}
    value = read_json(path)
    return value if isinstance(value, dict) else {"status": "invalid_json"}


def _hrd_ready_status(summary: dict[str, Any]) -> str:
    nested = summary.get("summary", {})
    if isinstance(nested, dict):
        return str(nested.get("ready_for_clinical_interpretation", ""))
    return str(summary.get("ready_for_clinical_interpretation", ""))


def _benchmark_plan_status(summary: dict[str, Any]) -> str:
    nested = summary.get("summary", {})
    if isinstance(nested, dict):
        return str(nested.get("ready_for_benchmark_execution", ""))
    return str(summary.get("ready_for_benchmark_execution", ""))


def readiness_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": row["fixture_id"],
            "dataset_id": row["dataset_id"],
            "sample_pair": row["sample_pair"],
            "truth_scope": row["truth_scope"],
            "clinicalization_gate": row["clinicalization_gate"],
            "fixture_status": "planned_not_run",
            "threshold_status": row["threshold_status"],
            "required_output": row["required_output"],
            "clinical_interpretation_allowed": "no",
            "next_action": "Implement fetch and benchmark commands only after runtime/cost approval.",
        }
        for row in rows
    ]


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    phase3_summary = _read_json_or_missing(PHASE3_SUMMARY_PATH)
    hrd_summary = _read_json_or_missing(HRD_INTERPRETATION_READINESS_PATH)
    benchmark_plan_summary = _read_json_or_missing(BENCHMARK_PLAN_SUMMARY_PATH)
    benchmark_manifest_schema_summary = _read_json_or_missing(BENCHMARK_MANIFEST_SCHEMA_SUMMARY_PATH)
    if phase3_summary.get("status") != "passed":
        errors.append(f"{PHASE3_SUMMARY_PATH} must report a passed Phase 3 WGS baseline.")
    if phase3_summary.get("phase3Complete") is not True:
        errors.append(f"{PHASE3_SUMMARY_PATH} must report phase3Complete=true.")
    if _hrd_ready_status(hrd_summary) != "no":
        errors.append(f"{HRD_INTERPRETATION_READINESS_PATH} must keep clinical interpretation disabled before known-answer benchmarks.")
    if benchmark_plan_summary.get("status") not in {"passed", "missing"}:
        errors.append(f"{BENCHMARK_PLAN_SUMMARY_PATH} must pass when present.")
    if _benchmark_plan_status(benchmark_plan_summary) not in {"", "no"}:
        errors.append(f"{BENCHMARK_PLAN_SUMMARY_PATH} must keep benchmark execution disabled before approval.")
    if benchmark_manifest_schema_summary.get("status") not in {"passed", "missing"}:
        errors.append(f"{BENCHMARK_MANIFEST_SCHEMA_SUMMARY_PATH} must pass when present.")
    if _benchmark_plan_status(benchmark_manifest_schema_summary) not in {"", "no"}:
        errors.append(f"{BENCHMARK_MANIFEST_SCHEMA_SUMMARY_PATH} must keep benchmark execution disabled before approval.")
    output_rows = readiness_rows(rows)
    summary = {
        "status": "passed" if not errors else "failed",
        "fixture_count": len(rows),
        "dataset_count": len({row.get("dataset_id", "") for row in rows}),
        "planned_fixture_count": sum(1 for row in rows if row.get("current_status") == "planned_not_run"),
        "locked_threshold_count": sum(1 for row in rows if row.get("threshold_status") == "locked"),
        "ready_for_clinical_interpretation": "no",
        "phase3_baseline_status": phase3_summary.get("status", ""),
        "phase3_complete": phase3_summary.get("phase3Complete", ""),
        "hrd_interpretation_ready_for_clinical_interpretation": _hrd_ready_status(hrd_summary),
        "benchmark_plan_status": benchmark_plan_summary.get("status", ""),
        "benchmark_execution_ready": _benchmark_plan_status(benchmark_plan_summary),
        "benchmark_manifest_schema_status": benchmark_manifest_schema_summary.get("status", ""),
        "benchmark_manifest_execution_ready": _benchmark_plan_status(benchmark_manifest_schema_summary),
        "next_step": "Add checksum and reference-build compatibility checks before any approved benchmark execution.",
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
    print("Known-answer fixture readiness verification passed.")


if __name__ == "__main__":
    main()
