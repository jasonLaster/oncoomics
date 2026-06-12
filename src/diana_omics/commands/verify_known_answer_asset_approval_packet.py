from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json
from .verify_known_answer_asset_acquisition import ACQUISITION_MANIFEST_PATH
from .verify_known_answer_checksum_policy import POLICY_MANIFEST_PATH

APPROVAL_PACKET_PATH = "manifests/known_answer_asset_approval_packet.csv"
SUMMARY_CSV_PATH = "results/clinicalization/known_answer_asset_approval_packet_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/known_answer_asset_approval_packet_summary.json"

REQUIRED_COLUMNS = {
    "packet_id",
    "manifest_path",
    "asset_kind",
    "dataset_id",
    "source_urls",
    "source_url_count",
    "access_terms_status",
    "checksum_evidence_status",
    "estimated_transfer_cost_class",
    "estimated_compute_cost_class",
    "raw_data_upload_allowed",
    "execution_allowed",
    "clinical_use_allowed",
    "owner_review_required",
    "approval_recommendation",
    "next_action",
}
ACCEPTED_ACCESS_TERMS_STATUS = {"needs_owner_review", "approved", "rejected", "blocked"}
ACCEPTED_CHECKSUM_STATUS = {"checksum_not_captured", "source_published_checksum", "verified_local_checksum"}
ACCEPTED_COST_CLASS = {"low", "medium", "high"}
BLOCKING_RECOMMENDATION = "defer_until_terms_and_checksums_captured"


def _read_csv(relative_path: str) -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(relative_path)))


def acquisition_rows() -> list[dict[str, str]]:
    return _read_csv(ACQUISITION_MANIFEST_PATH)


def checksum_rows() -> list[dict[str, str]]:
    return _read_csv(POLICY_MANIFEST_PATH)


def packet_rows() -> list[dict[str, str]]:
    return _read_csv(APPROVAL_PACKET_PATH)


def _source_urls_for_manifest(relative_path: str) -> list[str]:
    rows = _read_csv(relative_path)
    return sorted({row.get("source_url", "").strip() for row in rows if row.get("source_url", "").strip()})


def validate_packet(
    acquisition_plan: list[dict[str, str]], checksum_policy: list[dict[str, str]], packets: list[dict[str, str]]
) -> list[str]:
    errors: list[str] = []
    if not packets:
        return [f"{APPROVAL_PACKET_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(packets[0])
    for column in sorted(missing_columns):
        errors.append(f"{APPROVAL_PACKET_PATH} is missing required column {column}.")

    acquisition_by_path = {row.get("manifest_path", ""): row for row in acquisition_plan}
    checksum_by_path = {row.get("manifest_path", ""): row for row in checksum_policy}
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for row in packets:
        packet_id = row.get("packet_id", "")
        manifest_path = row.get("manifest_path", "")
        if packet_id in seen_ids:
            errors.append(f"{APPROVAL_PACKET_PATH} has duplicate packet_id {packet_id}.")
        seen_ids.add(packet_id)
        if manifest_path in seen_paths:
            errors.append(f"{APPROVAL_PACKET_PATH} has duplicate manifest_path {manifest_path}.")
        seen_paths.add(manifest_path)

        acquisition = acquisition_by_path.get(manifest_path)
        checksum = checksum_by_path.get(manifest_path)
        if acquisition is None:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} references manifest_path without acquisition plan: {manifest_path}.")
        else:
            for column in ("asset_kind", "dataset_id", "raw_data_upload_allowed", "execution_allowed", "clinical_use_allowed", "owner_review_required"):
                if row.get(column) != acquisition.get(column):
                    errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} {column} must match acquisition plan.")
        if checksum is None:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} references manifest_path without checksum policy: {manifest_path}.")
        else:
            if row.get("checksum_evidence_status") != checksum.get("checksum_source_status"):
                errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} checksum_evidence_status must match checksum policy.")

        expected_urls = _source_urls_for_manifest(manifest_path)
        packet_urls = [value.strip() for value in row.get("source_urls", "").split(";") if value.strip()]
        if packet_urls != expected_urls:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} source_urls must match source URLs in {manifest_path}.")
        if row.get("source_url_count") != str(len(expected_urls)):
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} source_url_count must be {len(expected_urls)}.")
        if row.get("access_terms_status") not in ACCEPTED_ACCESS_TERMS_STATUS:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} has invalid access_terms_status.")
        if row.get("checksum_evidence_status") not in ACCEPTED_CHECKSUM_STATUS:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} has invalid checksum_evidence_status.")
        if row.get("estimated_transfer_cost_class") not in ACCEPTED_COST_CLASS:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} has invalid estimated_transfer_cost_class.")
        if row.get("estimated_compute_cost_class") not in ACCEPTED_COST_CLASS:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} has invalid estimated_compute_cost_class.")
        if row.get("raw_data_upload_allowed") != "no":
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} must keep raw_data_upload_allowed=no.")
        if row.get("execution_allowed") != "no":
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} must keep execution_allowed=no.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} must keep clinical_use_allowed=no.")
        if row.get("owner_review_required") != "yes":
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} must require owner_review_required=yes.")
        if row.get("approval_recommendation") != BLOCKING_RECOMMENDATION:
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} must defer approval until terms and checksums are captured.")
        if not row.get("next_action", "").strip():
            errors.append(f"{APPROVAL_PACKET_PATH} row {packet_id} must define next_action.")

    for manifest_path in sorted(set(acquisition_by_path) - seen_paths):
        errors.append(f"{APPROVAL_PACKET_PATH} is missing approval packet row for {manifest_path}.")
    return errors


def summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "packet_id": row["packet_id"],
            "manifest_path": row["manifest_path"],
            "asset_kind": row["asset_kind"],
            "dataset_id": row["dataset_id"],
            "source_url_count": row["source_url_count"],
            "access_terms_status": row["access_terms_status"],
            "checksum_evidence_status": row["checksum_evidence_status"],
            "estimated_transfer_cost_class": row["estimated_transfer_cost_class"],
            "estimated_compute_cost_class": row["estimated_compute_cost_class"],
            "raw_data_upload_allowed": row["raw_data_upload_allowed"],
            "execution_allowed": row["execution_allowed"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "owner_review_required": row["owner_review_required"],
            "approval_recommendation": row["approval_recommendation"],
            "next_action": row["next_action"],
        }
        for row in rows
    ]


def main() -> None:
    acquisition_plan = acquisition_rows()
    checksum_policy = checksum_rows()
    packets = packet_rows()
    errors = validate_packet(acquisition_plan, checksum_policy, packets)
    output_rows = summary_rows(packets)
    summary = {
        "status": "passed" if not errors else "failed",
        "packet_row_count": len(packets),
        "source_url_count": sum(int(row.get("source_url_count", "0") or "0") for row in packets),
        "access_terms_review_pending_count": sum(1 for row in packets if row.get("access_terms_status") == "needs_owner_review"),
        "checksum_pending_count": sum(1 for row in packets if row.get("checksum_evidence_status") == "checksum_not_captured"),
        "execution_allowed_count": sum(1 for row in packets if row.get("execution_allowed") == "yes"),
        "raw_data_upload_allowed_count": sum(1 for row in packets if row.get("raw_data_upload_allowed") == "yes"),
        "approval_packet_ready_for_owner_review": "yes" if not errors else "no",
        "benchmark_execution_ready": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Owner review is required before any asset acquisition; capture access terms and checksums before enabling benchmark execution.",
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
    print("Known-answer asset approval packet verification passed.")


if __name__ == "__main__":
    main()
