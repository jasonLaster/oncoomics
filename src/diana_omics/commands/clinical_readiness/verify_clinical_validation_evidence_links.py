from __future__ import annotations

from pathlib import Path
from typing import Any

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json
from .verify_clinical_validation_packet import MANIFEST_PATH as PACKET_SECTIONS_PATH

MANIFEST_PATH = "manifests/clinical_validation_evidence_links.csv"
SUMMARY_CSV_PATH = "results/clinicalization/clinical_validation_evidence_link_summary.csv"
SUMMARY_JSON_PATH = "results/clinicalization/clinical_validation_evidence_link_summary.json"

REQUIRED_COLUMNS = {
    "link_id",
    "section_id",
    "validation_domain",
    "readiness_summary_paths",
    "required_status",
    "blocking_signal",
    "packet_section_unblocked",
    "clinical_use_allowed",
    "signoff_status",
    "next_action",
}


def _read_csv(relative_path: str) -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(relative_path)))


def _read_json_or_missing(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {"status": "missing"}
    value = read_json(path)
    return value if isinstance(value, dict) else {"status": "invalid_json"}


def packet_section_rows() -> list[dict[str, str]]:
    return _read_csv(PACKET_SECTIONS_PATH)


def evidence_link_rows() -> list[dict[str, str]]:
    return _read_csv(MANIFEST_PATH)


def _summary_paths(row: dict[str, str]) -> list[str]:
    return [value.strip() for value in row.get("readiness_summary_paths", "").split(";") if value.strip()]


def validate_links(packet_sections: list[dict[str, str]], links: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not links:
        return [f"{MANIFEST_PATH} has no rows."]
    missing_columns = REQUIRED_COLUMNS - set(links[0])
    for column in sorted(missing_columns):
        errors.append(f"{MANIFEST_PATH} is missing required column {column}.")

    packet_by_id = {row.get("section_id", ""): row for row in packet_sections}
    seen_ids: set[str] = set()
    seen_sections: set[str] = set()
    for row in links:
        link_id = row.get("link_id", "")
        section_id = row.get("section_id", "")
        if not link_id:
            errors.append(f"{MANIFEST_PATH} has a row with blank link_id.")
        if link_id in seen_ids:
            errors.append(f"{MANIFEST_PATH} has duplicate link_id {link_id}.")
        seen_ids.add(link_id)
        if section_id in seen_sections:
            errors.append(f"{MANIFEST_PATH} has duplicate section_id {section_id}.")
        seen_sections.add(section_id)
        packet = packet_by_id.get(section_id)
        if packet is None:
            errors.append(f"{MANIFEST_PATH} row {link_id} references unknown section_id {section_id}.")
        elif row.get("validation_domain") != packet.get("validation_domain"):
            errors.append(f"{MANIFEST_PATH} row {link_id} validation_domain must match packet section {section_id}.")
        for column in REQUIRED_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{MANIFEST_PATH} row {link_id or '(blank)'} is missing {column}.")
        if row.get("required_status") != "passed":
            errors.append(f"{MANIFEST_PATH} row {link_id} must require passed readiness summaries.")
        if row.get("packet_section_unblocked") != "no":
            errors.append(f"{MANIFEST_PATH} row {link_id} must keep packet_section_unblocked=no.")
        if row.get("clinical_use_allowed") != "no":
            errors.append(f"{MANIFEST_PATH} row {link_id} must keep clinical_use_allowed=no.")
        if row.get("signoff_status") == "approved":
            errors.append(f"{MANIFEST_PATH} row {link_id} cannot be approved before validation signoff.")
        paths = _summary_paths(row)
        if not paths:
            errors.append(f"{MANIFEST_PATH} row {link_id} must reference at least one readiness summary.")
        for summary_path in paths:
            summary = _read_json_or_missing(summary_path)
            if summary.get("status") != row.get("required_status"):
                errors.append(f"{MANIFEST_PATH} row {link_id} summary {summary_path} must have status {row.get('required_status')}.")

    for section_id in sorted(set(packet_by_id) - seen_sections):
        errors.append(f"{MANIFEST_PATH} is missing evidence link for packet section {section_id}.")
    return errors


def summary_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "link_id": row["link_id"],
            "section_id": row["section_id"],
            "validation_domain": row["validation_domain"],
            "readiness_summary_count": len(_summary_paths(row)),
            "required_status": row["required_status"],
            "blocking_signal": row["blocking_signal"],
            "packet_section_unblocked": row["packet_section_unblocked"],
            "clinical_use_allowed": row["clinical_use_allowed"],
            "signoff_status": row["signoff_status"],
            "next_action": row["next_action"],
        }
        for row in rows
    ]


def main() -> None:
    packet_sections = packet_section_rows()
    links = evidence_link_rows()
    errors = validate_links(packet_sections, links)
    output_rows = summary_rows(links)
    summary = {
        "status": "passed" if not errors else "failed",
        "linked_section_count": len(links),
        "packet_section_count": len(packet_sections),
        "readiness_summary_reference_count": sum(row["readiness_summary_count"] for row in output_rows),
        "unblocked_section_count": sum(1 for row in links if row.get("packet_section_unblocked") == "yes"),
        "clinical_use_allowed_count": sum(1 for row in links if row.get("clinical_use_allowed") == "yes"),
        "approved_link_count": sum(1 for row in links if row.get("signoff_status") == "approved"),
        "ready_for_clinical_packet": "no",
        "ready_for_clinical_interpretation": "no",
        "next_step": "Use this evidence-link map to fill validation-packet sections only after underlying readiness summaries become approved validation evidence.",
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
    print("Clinical validation evidence-link verification passed.")


if __name__ == "__main__":
    main()
