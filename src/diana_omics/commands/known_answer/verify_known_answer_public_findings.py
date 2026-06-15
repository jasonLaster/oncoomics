from __future__ import annotations

from pathlib import Path
from typing import Any

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json, write_text
from .run_known_answer_benchmark import DRY_RUN_SUMMARY_JSON_PATH
from .verify_known_answer_sample_pull_plan import MANIFEST_PATH as PULL_PLAN_PATH

CHECK_MANIFEST_PATH = "manifests/known_answer_public_finding_checks.csv"
SUMMARY_CSV_PATH = "results/clinicalization/known_answer_public_finding_confirmation.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_public_finding_confirmation.json"
SUMMARY_MD_PATH = "results/clinicalization/known_answer_public_finding_confirmation.md"

REQUIRED_COLUMNS = {
    "check_id",
    "pull_id",
    "dataset_id",
    "fixture_id",
    "public_finding",
    "source_url",
    "analysis_command",
    "analysis_artifact_path",
    "pass_gate",
    "no_call_policy",
}


def _read_csv(relative_path: str) -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(relative_path)))


def pull_plan_rows() -> list[dict[str, str]]:
    return _read_csv(PULL_PLAN_PATH)


def check_rows() -> list[dict[str, str]]:
    return _read_csv(CHECK_MANIFEST_PATH)


def dry_run_rows() -> list[dict[str, Any]]:
    path = path_from_root(DRY_RUN_SUMMARY_JSON_PATH)
    if not path.exists():
        return []
    payload = read_json(path)
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def validate_checks(pull_rows: list[dict[str, str]], checks: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not checks:
        return [f"{CHECK_MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(checks[0])
    for column in sorted(missing_columns):
        errors.append(f"{CHECK_MANIFEST_PATH} is missing required column {column}.")

    pulls_by_id = {row.get("pull_id", ""): row for row in pull_rows}
    seen_ids: set[str] = set()
    seen_pull_ids: set[str] = set()
    for row in checks:
        check_id = row.get("check_id", "")
        pull_id = row.get("pull_id", "")
        if not check_id:
            errors.append(f"{CHECK_MANIFEST_PATH} has a row with blank check_id.")
        if check_id in seen_ids:
            errors.append(f"{CHECK_MANIFEST_PATH} has duplicate check_id {check_id}.")
        seen_ids.add(check_id)
        if pull_id in seen_pull_ids:
            errors.append(f"{CHECK_MANIFEST_PATH} has multiple checks for pull_id {pull_id}.")
        seen_pull_ids.add(pull_id)
        pull = pulls_by_id.get(pull_id)
        if pull is None:
            errors.append(f"{CHECK_MANIFEST_PATH} row {check_id} references unknown pull_id {pull_id}.")
        elif row.get("dataset_id") != pull.get("dataset_id"):
            errors.append(f"{CHECK_MANIFEST_PATH} row {check_id} dataset_id must match {pull_id}.")
        for column in ("public_finding", "analysis_command", "analysis_artifact_path", "pass_gate", "no_call_policy"):
            if not row.get(column, "").strip():
                errors.append(f"{CHECK_MANIFEST_PATH} row {check_id} must define {column}.")
        if not row.get("source_url", "").startswith("http"):
            errors.append(f"{CHECK_MANIFEST_PATH} row {check_id} must include a source_url.")
    for pull_id in sorted(set(pulls_by_id) - seen_pull_ids):
        errors.append(f"{CHECK_MANIFEST_PATH} is missing a public finding check for {pull_id}.")
    return errors


def _analysis_artifact_status(relative_path: str) -> tuple[str, str]:
    path = path_from_root(relative_path)
    if not path.exists():
        return "missing", ""
    try:
        payload = read_json(path)
    except Exception as error:  # pragma: no cover - defensive error surfaced in summary
        return "invalid_json", str(error)
    if not isinstance(payload, dict):
        return "invalid_json", "analysis artifact is not a JSON object"
    return str(payload.get("status", "unknown")), ""


GAP_IDENTIFIED_ARTIFACT_STATUSES = {
    "not_confirmed_input_metadata_only",
    "not_confirmed_truth_assets_verified",
    "bounded_non_dry_gap_identified",
    "bounded_non_dry_blocked_remote_index_missing",
    "blocked_source_download_failed",
}

BOUNDED_CONFIRMED_ARTIFACT_STATUSES = {"bounded_non_dry_passed"}
BOUNDED_PARTIAL_ARTIFACT_STATUSES = {"bounded_non_dry_partial"}


def _confirmation_status(pull: dict[str, str], artifact_status: str) -> str:
    if artifact_status == "blocked_request_or_purchase":
        return "blocked_request_or_purchase"
    if artifact_status in BOUNDED_CONFIRMED_ARTIFACT_STATUSES:
        return "bounded_non_dry_confirmed"
    if artifact_status in BOUNDED_PARTIAL_ARTIFACT_STATUSES:
        return "bounded_non_dry_partial"
    if artifact_status in GAP_IDENTIFIED_ARTIFACT_STATUSES:
        return "not_confirmed_gap_identified"
    if pull.get("source_access") == "request_or_purchase":
        return "blocked_request_or_purchase"
    if pull.get("execution_allowed") != "yes":
        return "not_run_pending_approval"
    if artifact_status == "missing":
        return "no_call_missing_analysis_output"
    if artifact_status == "passed":
        return "confirmed"
    if artifact_status == "failed":
        return "discordant_or_failed"
    return "no_call_invalid_analysis_output"


def build_confirmation_rows(
    pull_rows: list[dict[str, str]], checks: list[dict[str, str]], dry_runs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    pulls_by_id = {row["pull_id"]: row for row in pull_rows}
    dry_run_by_fixture = {str(row.get("fixture_id", "")): row for row in dry_runs}
    rows: list[dict[str, Any]] = []
    for check in checks:
        pull = pulls_by_id[check["pull_id"]]
        artifact_status, artifact_error = _analysis_artifact_status(check["analysis_artifact_path"])
        dry_run = dry_run_by_fixture.get(check.get("fixture_id", ""))
        dry_run_status = str(dry_run.get("dry_run_status", "not_applicable")) if dry_run else "not_applicable"
        if check.get("fixture_id") and not dry_run:
            dry_run_status = "missing"
        confirmation_status = _confirmation_status(pull, artifact_status)
        rows.append(
            {
                "check_id": check["check_id"],
                "pull_id": check["pull_id"],
                "dataset_id": check["dataset_id"],
                "fixture_id": check["fixture_id"],
                "sample_or_asset_id": pull["sample_or_asset_id"],
                "asset_role": pull["asset_role"],
                "public_finding": check["public_finding"],
                "source_url": check["source_url"],
                "analysis_command": check["analysis_command"],
                "analysis_artifact_path": check["analysis_artifact_path"],
                "analysis_artifact_status": artifact_status,
                "analysis_artifact_error": artifact_error,
                "dry_run_status": dry_run_status,
                "confirmation_status": confirmation_status,
                "pass_gate": check["pass_gate"],
                "no_call_policy": check["no_call_policy"],
                "clinical_use_allowed": pull["clinical_use_allowed"],
            }
        )
    return rows


def validate_confirmation_rows(rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        errors.append("known-answer public finding confirmation has no rows.")
    if any(row.get("clinical_use_allowed") != "no" for row in rows):
        errors.append("known-answer public finding confirmation must keep clinical_use_allowed=no for every target.")
    for row in rows:
        status = row.get("confirmation_status")
        if status == "confirmed" and row.get("analysis_artifact_status") != "passed":
            errors.append(f"{row.get('check_id')} cannot be confirmed without a passed analysis artifact.")
        if status == "confirmed" and row.get("clinical_use_allowed") != "no":
            errors.append(f"{row.get('check_id')} cannot allow clinical use.")
        if status in {"bounded_non_dry_confirmed", "bounded_non_dry_partial"} and row.get("clinical_use_allowed") != "no":
            errors.append(f"{row.get('check_id')} cannot allow clinical use from bounded non-dry evidence.")
    return errors


def write_markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Known-Answer Public Finding Confirmation",
        "",
        "This generated status answers whether the current Diana Omics analysis confirms each expanded known-answer pull target.",
        "",
        f"- Status: `{summary['status']}`",
        f"- Confirmed targets: `{summary['confirmed_count']}`",
        f"- Bounded non-dry confirmations: `{summary['bounded_non_dry_confirmed_count']}`",
        f"- Partial bounded non-dry results: `{summary['bounded_non_dry_partial_count']}`",
        f"- Not-run or blocked targets: `{summary['not_confirmed_count']}`",
        f"- Ready for clinical interpretation: `{summary['ready_for_clinical_interpretation']}`",
        "",
        "| Pull target | Public finding check | Current confirmation | Analysis artifact | Next gate |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["pull_id"]),
                    str(row["public_finding"]),
                    str(row["confirmation_status"]),
                    str(row["analysis_artifact_path"]),
                    str(row["no_call_policy"]),
                ]
            )
            + " |"
        )
    write_text(path_from_root(SUMMARY_MD_PATH), "\n".join(lines))


def main() -> None:
    pulls = pull_plan_rows()
    checks = check_rows()
    errors = validate_checks(pulls, checks)
    rows = build_confirmation_rows(pulls, checks, dry_run_rows()) if not errors else []
    errors.extend(validate_confirmation_rows(rows))
    confirmed_count = sum(1 for row in rows if row.get("confirmation_status") == "confirmed")
    summary = {
        "status": "passed" if not errors else "failed",
        "target_count": len(rows),
        "confirmed_count": confirmed_count,
        "not_confirmed_count": len(rows) - confirmed_count,
        "bounded_non_dry_confirmed_count": sum(1 for row in rows if row.get("confirmation_status") == "bounded_non_dry_confirmed"),
        "bounded_non_dry_partial_count": sum(1 for row in rows if row.get("confirmation_status") == "bounded_non_dry_partial"),
        "blocked_request_or_purchase_count": sum(1 for row in rows if row.get("confirmation_status") == "blocked_request_or_purchase"),
        "gap_identified_count": sum(1 for row in rows if row.get("confirmation_status") == "not_confirmed_gap_identified"),
        "not_run_pending_approval_count": sum(1 for row in rows if row.get("confirmation_status") == "not_run_pending_approval"),
        "missing_analysis_output_count": sum(1 for row in rows if row.get("confirmation_status") == "no_call_missing_analysis_output"),
        "dry_run_ready_count": sum(1 for row in rows if row.get("dry_run_status") == "passed"),
        "clinical_use_allowed_count": sum(1 for row in rows if row.get("clinical_use_allowed") == "yes"),
        "ready_for_benchmark_execution": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Acquire approved inputs and truth assets with checksums, then run the mapped analysis command for each target before claiming public-finding confirmation.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root(Path(SUMMARY_CSV_PATH).parent))
    write_csv(path_from_root(SUMMARY_CSV_PATH), rows)
    write_json(
        path_from_root(SUMMARY_JSON_PATH),
        {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": rows},
    )
    write_markdown(rows, summary)
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print(f"Known-answer public finding confirmation verified: {confirmed_count}/{len(rows)} confirmed.")


if __name__ == "__main__":
    main()
