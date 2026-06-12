from __future__ import annotations

import os
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/hrd_interpretation_adapters.csv"
PHASE3_HRD_TOOL_SUMMARY_PATH = os.environ.get(
    "HRD_INTERPRETATION_PHASE3_TOOL_SUMMARY", "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json"
)
CNV_LOH_READINESS_PATH = os.environ.get("HRD_INTERPRETATION_CNV_LOH_READINESS", "results/clinicalization/cnv_loh_readiness_summary.json")
SV_CALLER_READINESS_PATH = os.environ.get("HRD_INTERPRETATION_SV_CALLER_READINESS", "results/clinicalization/sv_caller_readiness_summary.json")
SUMMARY_CSV_PATH = "results/clinicalization/hrd_interpretation_readiness_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/hrd_interpretation_readiness_summary.json"
REQUIRED_COLUMNS = {
    "adapter_id",
    "tool_name",
    "priority",
    "required_inputs",
    "locked_threshold_status",
    "no_call_condition",
    "output_contract",
    "current_status",
    "caveat",
    "source_url",
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
    for row in rows:
        adapter_id = row.get("adapter_id", "")
        if not adapter_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank adapter_id.")
        if adapter_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate adapter_id {adapter_id}.")
        ids.add(adapter_id)
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {adapter_id or '(blank)'} is missing {column}.")
        if row.get("locked_threshold_status") == "locked":
            errors.append(f"{MANIFEST_PATH} row {adapter_id} cannot lock thresholds before known-answer validation.")
        if row.get("current_status") != "scaffold_no_call":
            errors.append(f"{MANIFEST_PATH} row {adapter_id} must remain scaffold_no_call until validated inputs exist.")
        if "No " not in row.get("no_call_condition", ""):
            errors.append(f"{MANIFEST_PATH} row {adapter_id} must state an explicit no-call condition.")
    for required_id in ["sigprofiler_sbs3", "scarhrd", "chord", "hrdetect"]:
        if required_id not in ids:
            errors.append(f"{MANIFEST_PATH} must include {required_id}.")
    return errors


def _read_json_or_missing(relative_path: str) -> Any:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"status": "missing", "rows": []}
    return read_json(path)


def _tool_status(rows: list[dict[str, Any]], tool: str) -> str:
    for row in rows:
        if row.get("tool") == tool:
            return str(row.get("interpretability_status", ""))
    return "missing"


def _summary_row(summary: dict[str, Any]) -> dict[str, Any]:
    rows = summary.get("rows", [])
    if not rows:
        return {}
    return rows[0]


def current_interpretation_state() -> dict[str, Any]:
    hrd_tool_summary = _read_json_or_missing(PHASE3_HRD_TOOL_SUMMARY_PATH)
    cnv_readiness = _summary_row(_read_json_or_missing(CNV_LOH_READINESS_PATH))
    sv_readiness = _summary_row(_read_json_or_missing(SV_CALLER_READINESS_PATH))
    tool_rows = hrd_tool_summary.get("rows", [])
    return {
        "phase3_hrd_tool_status": hrd_tool_summary.get("status", ""),
        "sigprofiler_interpretability_status": _tool_status(tool_rows, "SigProfilerAssignment"),
        "scarhrd_interpretability_status": _tool_status(tool_rows, "scarHRD"),
        "chord_interpretability_status": _tool_status(tool_rows, "CHORD"),
        "cnv_ready_for_clinical_interpretation": cnv_readiness.get("ready_for_clinical_interpretation", "missing"),
        "sv_ready_for_clinical_interpretation": sv_readiness.get("ready_for_clinical_interpretation", "missing"),
        "cnv_current_bins_are_not_allele_specific_segments": cnv_readiness.get("current_bins_are_not_allele_specific_segments", "missing"),
        "sv_current_evidence_is_not_validated_vcf": sv_readiness.get("current_evidence_is_not_validated_sv_vcf", "missing"),
    }


def adapter_readiness_rows(rows: list[dict[str, str]], state: dict[str, Any]) -> list[dict[str, Any]]:
    no_call_reasons = {
        "sigprofiler_sbs3": "SBS3 interpretation thresholds and known-answer performance are not locked.",
        "scarhrd": "Allele-specific CNV/LOH segments are not available.",
        "chord": "Validated production SV caller VCF/BEDPE input is not available.",
        "hrdetect": "Integrated HRDetect-style feature classes and model calibration are not complete.",
    }
    current_input_status = {
        "sigprofiler_sbs3": state.get("sigprofiler_interpretability_status", ""),
        "scarhrd": state.get("scarhrd_interpretability_status", ""),
        "chord": state.get("chord_interpretability_status", ""),
        "hrdetect": "not_assessable_until_component_adapters_are_validated",
    }
    return [
        {
            "adapter_id": row["adapter_id"],
            "tool_name": row["tool_name"],
            "priority": row["priority"],
            "current_input_status": current_input_status.get(row["adapter_id"], "missing"),
            "interpretation_status": "no_call",
            "clinical_actionability": "not_ready",
            "locked_threshold_status": row["locked_threshold_status"],
            "required_inputs": row["required_inputs"],
            "no_call_reason": no_call_reasons.get(row["adapter_id"], row["no_call_condition"]),
            "output_contract": row["output_contract"],
        }
        for row in rows
    ]


def summary_status(errors: list[str], state: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    all_no_call = rows and all(row.get("interpretation_status") == "no_call" and row.get("clinical_actionability") == "not_ready" for row in rows)
    required_boundaries = (
        state.get("cnv_ready_for_clinical_interpretation") == "no"
        and state.get("sv_ready_for_clinical_interpretation") == "no"
        and state.get("cnv_current_bins_are_not_allele_specific_segments") == "yes"
        and state.get("sv_current_evidence_is_not_validated_vcf") == "yes"
    )
    return "passed" if not errors and all_no_call and required_boundaries else "failed"


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    state = current_interpretation_state()
    if state.get("phase3_hrd_tool_status") != "passed":
        errors.append(f"{PHASE3_HRD_TOOL_SUMMARY_PATH} must report passed HRD tool readiness.")
    if state.get("cnv_ready_for_clinical_interpretation") != "no":
        errors.append(f"{CNV_LOH_READINESS_PATH} must keep CNV/LOH clinical interpretation disabled.")
    if state.get("sv_ready_for_clinical_interpretation") != "no":
        errors.append(f"{SV_CALLER_READINESS_PATH} must keep SV clinical interpretation disabled.")
    adapter_rows = adapter_readiness_rows(rows, state)
    status = summary_status(errors, state, adapter_rows)
    summary = {
        "status": status,
        "adapter_count": len(rows),
        "no_call_adapter_count": sum(1 for row in adapter_rows if row.get("interpretation_status") == "no_call"),
        "ready_for_clinical_interpretation": "no",
        "phase3_hrd_tool_status": state.get("phase3_hrd_tool_status", ""),
        "cnv_ready_for_clinical_interpretation": state.get("cnv_ready_for_clinical_interpretation", ""),
        "sv_ready_for_clinical_interpretation": state.get("sv_ready_for_clinical_interpretation", ""),
        "next_step": "Add HG008 and COLO829 known-answer fixtures for CNV/LOH, SV, and signature adapters before locking thresholds.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root("results/clinicalization"))
    write_csv(path_from_root(SUMMARY_CSV_PATH), adapter_rows)
    write_json(
        path_from_root(SUMMARY_JSON_PATH),
        {"generatedAt": iso_now(), "status": status, "errors": errors, "summary": summary, "rows": adapter_rows},
    )
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("HRD interpretation readiness verification passed.")


if __name__ == "__main__":
    main()
