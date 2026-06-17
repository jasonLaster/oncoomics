from __future__ import annotations

import os
from typing import Any

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json

MANIFEST_PATH = "manifests/sv_caller_tool_candidates.csv"
PHASE3_SV_SUMMARY_PATH = os.environ.get("SV_CALLER_PHASE3_SV_SUMMARY", "results/phase3_wgs_smoke/sv_evidence_summary.json")
SUMMARY_CSV_PATH = "results/clinicalization/sv_caller_readiness_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/sv_caller_readiness_summary.json"
REQUIRED_COLUMNS = {
    "tool_id",
    "tool_name",
    "priority",
    "input_contract",
    "primary_outputs",
    "chord_ready",
    "bedpe_support",
    "vcf_support",
    "somatic_filter_support",
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
        if row.get("chord_ready") != "yes":
            errors.append(f"{MANIFEST_PATH} row {tool_id} must produce CHORD/HRDetect-ready SV features.")
        if row.get("vcf_support") != "yes" or row.get("somatic_filter_support") != "yes":
            errors.append(f"{MANIFEST_PATH} row {tool_id} must support VCF output plus somatic filtering.")
        if row.get("bedpe_support") not in {"yes", "convertible"}:
            errors.append(f"{MANIFEST_PATH} row {tool_id} must produce or convert to BEDPE-like event records.")
        if row.get("current_status") == "production_ready":
            errors.append(f"{MANIFEST_PATH} row {tool_id} cannot be production_ready before known-answer validation.")
    if not any(row.get("priority") == "primary_candidate" for row in rows):
        errors.append(f"{MANIFEST_PATH} must include one primary_candidate.")
    return errors


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def current_phase3_sv_state() -> dict[str, Any]:
    path = path_from_root(PHASE3_SV_SUMMARY_PATH)
    if not path.exists():
        return {
            "status": "missing",
            "row_count": 0,
            "chord_input_status": "missing_phase3_sv_summary",
            "all_rows_passed": "no",
        }
    summary = read_json(path)
    rows = summary.get("rows", [])
    chord_statuses = sorted({str(row.get("chord_input_status", "")) for row in rows if row.get("chord_input_status")})
    return {
        "status": summary.get("status", "unknown"),
        "row_count": len(rows),
        "all_rows_passed": "yes" if rows and all(row.get("status") == "passed" for row in rows) else "no",
        "tool": ";".join(sorted({str(row.get("tool", "")) for row in rows if row.get("tool")})),
        "supplementary_alignments": sum(_int(row.get("supplementary_alignments")) for row in rows),
        "discordant_mapped_pairs": sum(_int(row.get("discordant_mapped_pairs")) for row in rows),
        "interchromosomal_pairs": sum(_int(row.get("interchromosomal_pairs")) for row in rows),
        "large_insert_pairs": sum(_int(row.get("large_insert_pairs")) for row in rows),
        "candidate_rows_written": sum(_int(row.get("sv_candidate_rows_written")) for row in rows),
        "chord_input_status": ";".join(chord_statuses),
    }


def chord_status_requires_validated_sv_vcf(chord_status: str) -> bool:
    return "not_assessable" in chord_status and "sv_caller_vcf" in chord_status


def chord_status_is_not_assessable(chord_status: str) -> bool:
    return "not_assessable" in chord_status


def readiness_row(rows: list[dict[str, str]], errors: list[str], sv_state: dict[str, Any]) -> dict[str, Any]:
    chord_status = str(sv_state.get("chord_input_status", ""))
    current_evidence_not_validated_vcf = chord_status_is_not_assessable(chord_status)
    positive_sv_counts = _int(sv_state.get("discordant_mapped_pairs")) > 0
    evidence_state = "bam_sv_counts_present" if positive_sv_counts else "metadata_only_or_no_discordant_pair_counts"
    next_step = (
        "Containerize the primary SV caller and run HG008/COLO829 reciprocal-overlap fixtures before enabling CHORD or HRDetect interpretation."
        if positive_sv_counts
        else "Regenerate full SV evidence with discordant-pair counts, then run the primary SV caller and HG008/COLO829 reciprocal-overlap fixtures."
    )
    return {
        "status": "passed" if not errors and current_evidence_not_validated_vcf else "failed",
        "candidate_count": len(rows),
        "primary_candidate_count": sum(1 for row in rows if row.get("priority") == "primary_candidate"),
        "phase3_sv_status": sv_state.get("status", ""),
        "phase3_sv_rows": sv_state.get("row_count", 0),
        "phase3_sv_all_rows_passed": sv_state.get("all_rows_passed", ""),
        "phase3_sv_tool": sv_state.get("tool", ""),
        "phase3_supplementary_alignments": sv_state.get("supplementary_alignments", 0),
        "phase3_discordant_mapped_pairs": sv_state.get("discordant_mapped_pairs", 0),
        "phase3_interchromosomal_pairs": sv_state.get("interchromosomal_pairs", 0),
        "phase3_large_insert_pairs": sv_state.get("large_insert_pairs", 0),
        "phase3_sv_candidate_rows_written": sv_state.get("candidate_rows_written", 0),
        "phase3_chord_input_status": chord_status,
        "phase3_sv_evidence_state": evidence_state,
        "current_evidence_is_not_validated_sv_vcf": "yes" if current_evidence_not_validated_vcf else "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": next_step,
        "error_count": len(errors),
    }


def main() -> None:
    rows = manifest_rows()
    errors = validate_manifest(rows)
    sv_state = current_phase3_sv_state()
    if sv_state.get("status") != "passed" or sv_state.get("all_rows_passed") != "yes":
        errors.append(f"{PHASE3_SV_SUMMARY_PATH} must report passed SV evidence rows.")
    if not chord_status_is_not_assessable(str(sv_state.get("chord_input_status", ""))):
        errors.append(f"{PHASE3_SV_SUMMARY_PATH} must keep CHORD not assessable until validated SV caller VCF exists.")
    summary = readiness_row(rows, errors, sv_state)
    ensure_dir(path_from_root("results/clinicalization"))
    write_csv(path_from_root(SUMMARY_CSV_PATH), [summary])
    write_json(path_from_root(SUMMARY_JSON_PATH), {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "rows": [summary]})
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("SV caller readiness verification passed.")


if __name__ == "__main__":
    main()
