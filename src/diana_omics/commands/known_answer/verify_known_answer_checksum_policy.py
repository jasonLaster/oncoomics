from __future__ import annotations

from pathlib import Path
from typing import Any

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json
from .plan_known_answer_benchmarks import PLAN_MANIFEST_PATH

POLICY_MANIFEST_PATH = "manifests/known_answer_checksum_policy.csv"
SUMMARY_CSV_PATH = "results/clinicalization/known_answer_checksum_policy_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_checksum_policy_summary.json"

REQUIRED_COLUMNS = {
    "policy_id",
    "manifest_path",
    "asset_kind",
    "checksum_source_status",
    "accepted_checksum_types",
    "capture_required_before_execution",
    "execution_allowed",
    "clinical_use_allowed",
    "no_call_if_unverified",
    "next_action",
}
ACCEPTED_STATUS = {"checksum_not_captured", "source_published_checksum", "verified_local_checksum"}
ACCEPTED_TYPES = {"sha256", "md5"}


def _read_csv(relative_path: str) -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(relative_path)))


def planned_manifest_paths() -> dict[str, str]:
    paths: dict[str, str] = {}
    for row in _read_csv(PLAN_MANIFEST_PATH):
        paths[row["input_manifest_path"]] = "input"
        paths[row["truth_asset_manifest"]] = "truth"
    return paths


def policy_rows() -> list[dict[str, str]]:
    return _read_csv(POLICY_MANIFEST_PATH)


def validate_policy(planned_paths: dict[str, str], rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return [f"{POLICY_MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"{POLICY_MANIFEST_PATH} is missing required column {column}.")

    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    for row in rows:
        policy_id = row.get("policy_id", "")
        manifest_path = row.get("manifest_path", "")
        if policy_id in seen_ids:
            errors.append(f"{POLICY_MANIFEST_PATH} has duplicate policy_id {policy_id}.")
        seen_ids.add(policy_id)
        if manifest_path in seen_paths:
            errors.append(f"{POLICY_MANIFEST_PATH} has duplicate manifest_path {manifest_path}.")
        seen_paths.add(manifest_path)
        if manifest_path not in planned_paths:
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} references unplanned manifest_path {manifest_path}.")
        elif row.get("asset_kind") != planned_paths[manifest_path]:
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} asset_kind must be {planned_paths[manifest_path]}.")
        if row.get("checksum_source_status") not in ACCEPTED_STATUS:
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} has invalid checksum_source_status.")
        checksum_types = {value.strip() for value in row.get("accepted_checksum_types", "").split(";") if value.strip()}
        if not checksum_types or not checksum_types <= ACCEPTED_TYPES:
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} must use accepted checksum types sha256/md5.")
        if row.get("capture_required_before_execution") != "yes":
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} must require checksum capture before execution.")
        if row.get("execution_allowed") != "no":
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} must keep execution_allowed=no.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} must keep clinical_use_allowed=no.")
        if row.get("no_call_if_unverified") != "yes":
            errors.append(f"{POLICY_MANIFEST_PATH} row {policy_id} must set no_call_if_unverified=yes.")

    for manifest_path in sorted(set(planned_paths) - seen_paths):
        errors.append(f"{POLICY_MANIFEST_PATH} is missing checksum policy for {manifest_path}.")
    return errors


def summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "policy_id": row["policy_id"],
            "manifest_path": row["manifest_path"],
            "asset_kind": row["asset_kind"],
            "checksum_source_status": row["checksum_source_status"],
            "capture_required_before_execution": row["capture_required_before_execution"],
            "execution_allowed": row["execution_allowed"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "no_call_if_unverified": row["no_call_if_unverified"],
            "next_action": row["next_action"],
        }
        for row in rows
    ]


def main() -> None:
    planned_paths = planned_manifest_paths()
    rows = policy_rows()
    errors = validate_policy(planned_paths, rows)
    output_rows = summary_rows(rows)
    captured_count = sum(1 for row in rows if row.get("checksum_source_status") != "checksum_not_captured")
    summary = {
        "status": "passed" if not errors else "failed",
        "policy_count": len(rows),
        "planned_manifest_count": len(planned_paths),
        "checksum_captured_count": captured_count,
        "checksum_pending_count": len(rows) - captured_count,
        "benchmark_execution_ready": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Populate source-published checksums or verified local checksums only after approved asset acquisition.",
        "error_count": len(errors),
    }
    ensure_dir(path_from_root(Path(SUMMARY_CSV_PATH).parent))
    write_csv(path_from_root(SUMMARY_CSV_PATH), output_rows)
    write_json(path_from_root(SUMMARY_JSON_PATH), {"generatedAt": iso_now(), "status": summary["status"], "errors": errors, "summary": summary, "rows": output_rows})
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)
    print("Known-answer checksum policy verification passed.")


if __name__ == "__main__":
    main()
