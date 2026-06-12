from __future__ import annotations

import os
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/allele_specific_cnv_tool_candidates.csv"
PHASE3_CNV_SUMMARY_PATH = os.environ.get("CNV_LOH_PHASE3_CNV_SUMMARY", "results/phase3_wgs_smoke/coverage_cnv_summary.json")
SUMMARY_CSV_PATH = "results/clinicalization/cnv_loh_readiness_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/cnv_loh_readiness_summary.json"
REQUIRED_COLUMNS = {
    "tool_id",
    "tool_name",
    "priority",
    "input_contract",
    "primary_outputs",
    "scarhrd_segment_ready",
    "loh_support",
    "purity_ploidy_support",
    "container_required",
    "validation_target",
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
        tool_id = row.get("tool_id", "")
        if not tool_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank tool_id.")
        if tool_id in ids:
            errors.append(f"{MANIFEST_PATH} has duplicate tool_id {tool_id}.")
        ids.add(tool_id)
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {tool_id or '(blank)'} is missing {column}.")
        if row.get("scarhrd_segment_ready") != "yes":
            errors.append(f"{MANIFEST_PATH} row {tool_id} must produce scarHRD-ready allele-specific segments.")
        if row.get("loh_support") != "yes" or row.get("purity_ploidy_support") != "yes":
            errors.append(f"{MANIFEST_PATH} row {tool_id} must support LOH plus purity/ploidy.")
        if row.get("current_status") == "production_ready":
            errors.append(f"{MANIFEST_PATH} row {tool_id} cannot be production_ready before known-answer validation.")
    if not any(row.get("priority") == "primary_candidate" for row in rows):
        errors.append(f"{MANIFEST_PATH} must include one primary_candidate.")
    return errors


def current_phase3_cnv_state() -> dict[str, Any]:
    path = path_from_root(PHASE3_CNV_SUMMARY_PATH)
    if not path.exists():
        return {"status": "missing", "bin_count": 0, "scarhrd_input_status": "missing_phase3_cnv_summary"}
    summary = read_json(path)
    rows = summary.get("rows", [])
    row = rows[0] if rows else {}
    return {
        "status": summary.get("status", "unknown"),
        "bin_count": int(row.get("bin_count") or 0),
        "scarhrd_input_status": row.get("scarhrd_input_status", ""),
        "tool": row.get("tool", ""),
    }


def readiness_row(rows: list[dict[str, str]], errors: list[str], cnv_state: dict[str, Any]) -> dict[str, Any]:
    scarhrd_status = str(cnv_state.get("scarhrd_input_status", ""))
    current_bins_are_not_segments = "not_assessable" in scarhrd_status and int(cnv_state.get("bin_count") or 0) > 0
    return {
        "status": "passed" if not errors and current_bins_are_not_segments else "failed",
        "candidate_count": len(rows),
        "primary_candidate_count": sum(1 for row in rows if row.get("priority") == "primary_candidate"),
        "phase3_cnv_status": cnv_state.get("status", ""),
        "phase3_cnv_bins": cnv_state.get("bin_count", 0),
        "phase3_cnv_tool": cnv_state.get("tool", ""),
        "phase3_scarhrd_input_status": scarhrd_status,
        "current_bins_are_not_allele_specific_segments": "yes" if current_bins_are_not_segments else "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Containerize the primary candidate and run HG008/COLO829 CNV/LOH truth-overlap fixtures before enabling scarHRD interpretation.",
        "error_count": len(errors),
    }


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    cnv_state = current_phase3_cnv_state()
    if int(cnv_state.get("bin_count") or 0) <= 0:
        errors.append(f"{PHASE3_CNV_SUMMARY_PATH} does not report positive coverage CNV bins.")
    if "not_assessable" not in str(cnv_state.get("scarhrd_input_status", "")):
        errors.append(f"{PHASE3_CNV_SUMMARY_PATH} must keep scarHRD not assessable until allele-specific segments exist.")
    summary = readiness_row(rows, errors, cnv_state)
    ensure_dir(path_from_root("results/clinicalization"))
    write_csv(path_from_root(SUMMARY_CSV_PATH), [summary])
    write_json(path_from_root(SUMMARY_JSON_PATH), {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "rows": [summary]})
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("CNV/LOH readiness verification passed.")


if __name__ == "__main__":
    main()
