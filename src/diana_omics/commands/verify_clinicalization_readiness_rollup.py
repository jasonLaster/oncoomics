from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, read_json, write_csv, write_json

SUMMARY_CSV_PATH = "results/clinicalization/clinicalization_readiness_rollup.csv"
SUMMARY_JSON_PATH = "results/clinicalization/clinicalization_readiness_rollup.json"

DEPENDENCIES = {
    "assay_boundaries": "results/clinicalization/clinical_assay_boundaries_summary.json",
    "qc_thresholds": "results/clinicalization/clinical_qc_threshold_lock_summary.json",
    "sample_pull_plan": "results/clinicalization/known_answer_sample_pull_plan_summary.json",
    "public_finding_confirmation": "results/clinicalization/known_answer_public_finding_confirmation.json",
    "known_answer_assets": "results/clinicalization/known_answer_asset_approval_packet_summary.json",
    "benchmark_plan": "results/clinicalization/known_answer_benchmark_plan_summary.json",
    "packet_evidence": "results/clinicalization/clinical_validation_evidence_link_summary.json",
    "change_control": "results/clinicalization/clinical_change_control_summary.json",
    "signoff": "results/clinicalization/clinical_signoff_workflow_summary.json",
}


def _read_summary(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"status": "missing", "summary": {}}
    value = read_json(path)
    return value if isinstance(value, dict) else {"status": "invalid_json", "summary": {}}


def _nested(summary: dict[str, Any], key: str, default: Any = "") -> Any:
    nested = summary.get("summary", {})
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    return summary.get(key, default)


def _status(summary: dict[str, Any]) -> str:
    return str(summary.get("status", "missing"))


def _int(summary: dict[str, Any], key: str) -> int:
    value = _nested(summary, key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_rollup_rows(summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    known_assets = summaries["known_answer_assets"]
    thresholds = summaries["qc_thresholds"]
    packet = summaries["packet_evidence"]
    change_control = summaries["change_control"]
    signoff = summaries["signoff"]
    boundaries = summaries["assay_boundaries"]
    benchmark_plan = summaries["benchmark_plan"]
    sample_pull_plan = summaries["sample_pull_plan"]
    public_finding_confirmation = summaries["public_finding_confirmation"]
    return [
        {
            "rollup_area": "known_answer_sample_pull_plan",
            "dependency_status": _status(sample_pull_plan),
            "scaffold_status": "ten_target_pull_plan_present",
            "active_blocker_count": _int(sample_pull_plan, "pending_pull_target_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(sample_pull_plan, "ready_for_clinical_interpretation", "no"),
            "next_action": "Owner review must approve source terms transfer costs and checksums before downloading the expanded known-answer sample suite.",
        },
        {
            "rollup_area": "known_answer_public_finding_confirmation",
            "dependency_status": _status(public_finding_confirmation),
            "scaffold_status": "ten_target_confirmation_report_present",
            "active_blocker_count": _int(public_finding_confirmation, "not_confirmed_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(public_finding_confirmation, "ready_for_clinical_interpretation", "no"),
            "next_action": "Run approved known-answer inputs against public findings before claiming HG008 COLO829 or Seraseq confirmation.",
        },
        {
            "rollup_area": "known_answer_assets",
            "dependency_status": _status(known_assets),
            "scaffold_status": "approval_packet_ready_for_owner_review",
            "active_blocker_count": _int(known_assets, "access_terms_review_pending_count") + _int(known_assets, "checksum_pending_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(known_assets, "ready_for_clinical_interpretation", "no"),
            "next_action": "Owner review must approve access terms and checksums before any known-answer asset acquisition or benchmark execution.",
        },
        {
            "rollup_area": "known_answer_benchmark_execution",
            "dependency_status": _status(benchmark_plan),
            "scaffold_status": "dry_run_plans_present",
            "active_blocker_count": _int(benchmark_plan, "approval_required_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(benchmark_plan, "ready_for_clinical_interpretation", "no"),
            "next_action": "Do not run HG008/COLO829 benchmarks until asset approval and checksum gates are satisfied.",
        },
        {
            "rollup_area": "qc_thresholds",
            "dependency_status": _status(thresholds),
            "scaffold_status": "draft_thresholds_defined",
            "active_blocker_count": _int(thresholds, "draft_not_locked_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(thresholds, "ready_for_clinical_interpretation", "no"),
            "next_action": "Populate and lock threshold values only after known-answer validation evidence and reviewer signoff.",
        },
        {
            "rollup_area": "validation_packet",
            "dependency_status": _status(packet),
            "scaffold_status": "sections_linked_to_readiness_evidence",
            "active_blocker_count": _int(packet, "linked_section_count") - _int(packet, "unblocked_section_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(packet, "ready_for_clinical_interpretation", "no"),
            "next_action": "Keep packet sections locked until linked readiness summaries become approved validation evidence.",
        },
        {
            "rollup_area": "change_control",
            "dependency_status": _status(change_control),
            "scaffold_status": "revalidation_triggers_defined",
            "active_blocker_count": _int(change_control, "trigger_count") - _int(change_control, "approved_trigger_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(change_control, "ready_for_clinical_interpretation", "no"),
            "next_action": "Keep every change trigger review-required until validation packet evidence and signoff are complete.",
        },
        {
            "rollup_area": "signoff",
            "dependency_status": _status(signoff),
            "scaffold_status": "required_roles_defined",
            "active_blocker_count": _int(signoff, "pending_decision_count"),
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(signoff, "ready_for_clinical_interpretation", "no"),
            "next_action": "Convert pending role scaffolds into named reviewer records only after validation evidence sections are complete.",
        },
        {
            "rollup_area": "clinical_reporting_boundaries",
            "dependency_status": _status(boundaries),
            "scaffold_status": "candidate_only_boundaries_defined",
            "active_blocker_count": 1 if _nested(boundaries, "clinical_reporting_allowed", "no") != "yes" else 0,
            "clinical_release_allowed": "no",
            "ready_for_clinical_interpretation": _nested(boundaries, "known_answer_ready_for_clinical_interpretation", "no"),
            "next_action": "Keep reporting candidate-only until reportable range, thresholds, packet evidence, and signoff are approved.",
        },
    ]


def validate_rollup(summaries: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for area, path in DEPENDENCIES.items():
        if _status(summaries[area]) != "passed":
            errors.append(f"{path} must have status passed.")
    if not rows:
        errors.append("clinicalization readiness rollup has no rows.")
    if any(row.get("clinical_release_allowed") != "no" for row in rows):
        errors.append("clinicalization readiness rollup must keep clinical_release_allowed=no for every area.")
    if any(row.get("ready_for_clinical_interpretation") != "no" for row in rows):
        errors.append("clinicalization readiness rollup must keep ready_for_clinical_interpretation=no for every area.")
    if sum(int(row.get("active_blocker_count", 0) or 0) for row in rows) <= 0:
        errors.append("clinicalization readiness rollup must retain active blockers until validation and signoff are complete.")
    if _nested(summaries["known_answer_assets"], "execution_allowed_count", 0) != 0:
        errors.append("known-answer assets must keep execution_allowed_count=0.")
    if _nested(summaries["sample_pull_plan"], "execution_allowed_count", 0) != 0:
        errors.append("known-answer sample pull plan must keep execution_allowed_count=0.")
    if _nested(summaries["sample_pull_plan"], "clinical_use_allowed_count", 0) != 0:
        errors.append("known-answer sample pull plan must keep clinical_use_allowed_count=0.")
    if _nested(summaries["public_finding_confirmation"], "confirmed_count", 0) != 0:
        errors.append("known-answer public finding confirmation must keep confirmed_count=0 until approved runs exist.")
    if _nested(summaries["public_finding_confirmation"], "clinical_use_allowed_count", 0) != 0:
        errors.append("known-answer public finding confirmation must keep clinical_use_allowed_count=0.")
    if _nested(summaries["qc_thresholds"], "locked_threshold_count", 0) != 0:
        errors.append("clinical QC thresholds must keep locked_threshold_count=0.")
    if _nested(summaries["packet_evidence"], "unblocked_section_count", 0) != 0:
        errors.append("clinical validation evidence links must keep unblocked_section_count=0.")
    if _nested(summaries["change_control"], "clinical_release_allowed_count", 0) != 0:
        errors.append("clinical change control must keep clinical_release_allowed_count=0.")
    if _nested(summaries["signoff"], "approved_decision_count", 0) != 0:
        errors.append("clinical signoff workflow must keep approved_decision_count=0.")
    return errors


def main() -> None:
    summaries = {area: _read_summary(path) for area, path in DEPENDENCIES.items()}
    rows = build_rollup_rows(summaries)
    errors = validate_rollup(summaries, rows)
    active_blocker_count = sum(int(row.get("active_blocker_count", 0) or 0) for row in rows)
    summary = {
        "status": "passed" if not errors else "failed",
        "rollup_area_count": len(rows),
        "dependency_count": len(DEPENDENCIES),
        "passing_dependency_count": sum(1 for area in DEPENDENCIES if _status(summaries[area]) == "passed"),
        "active_blocker_count": active_blocker_count,
        "clinical_release_allowed": "no",
        "ready_for_clinical_interpretation": "no",
        "ready_for_benchmark_execution": "no",
        "next_step": "Monitor this rollup; the first true approval boundary remains known-answer asset owner review and checksum capture before benchmark execution.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root(Path(SUMMARY_CSV_PATH).parent))
    write_csv(path_from_root(SUMMARY_CSV_PATH), rows)
    write_json(
        path_from_root(SUMMARY_JSON_PATH),
        {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": rows},
    )
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("Clinicalization readiness rollup verification passed.")


if __name__ == "__main__":
    main()
