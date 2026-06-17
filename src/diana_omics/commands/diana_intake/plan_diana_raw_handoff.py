from __future__ import annotations

from typing import Any

from ...diana_raw import DIANA_RAW_RESULTS, DIANA_RAW_TEMPLATE, diana_raw_contract
from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json, write_text
from .verify_diana_raw import selected_samplesheet, validate_rows

PY_COMMAND = "PYTHONPATH=src /usr/bin/python3 -m diana_omics"


def analysis_id() -> str:
    from os import environ

    return environ.get("DIANA_RAW_ANALYSIS_ID", "diana_raw_initial")


def sample_state(samplesheet: str) -> dict[str, Any]:
    path = path_from_root(samplesheet)
    if not path.exists():
        return {
            "status": "waiting_for_dinah_files",
            "samplesheet": samplesheet,
            "rowCount": 0,
            "dnaRowCount": 0,
            "rnaRows": 0,
            "matchedPairIds": [],
            "structuralErrors": [f"{samplesheet} is not present yet."],
            "warnings": ["Copy the template and replace placeholder paths when Dinah's files arrive."],
        }
    rows = parse_csv(read_text(path))
    errors, warnings, summary = validate_rows(rows, require_files=False)
    return {
        "status": "samplesheet_present" if not errors else "samplesheet_needs_metadata_fix",
        "samplesheet": samplesheet,
        **summary,
        "structuralErrors": errors,
        "warnings": warnings,
    }


def handoff_rows(samplesheet: str, analysis: str) -> list[dict[str, str]]:
    strict_validate = f"DIANA_RAW_SAMPLESHEET={samplesheet} DIANA_RAW_REQUIRE_DATA=1 {PY_COMMAND} verify:diana-raw"
    stage = f"DIANA_RAW_SAMPLESHEET={samplesheet} DIANA_RAW_REQUIRE_DATA=1 DIANA_RAW_ANALYSIS_ID={analysis} {PY_COMMAND} stage:diana-raw"
    packet = f"ROSALIND_HRD_SAMPLE_SET=diana_raw_intake ROSALIND_HRD_RUN_ID=diana-raw-{analysis} {PY_COMMAND} build:rosalind-hrd-packet"
    triage = (
        "ROSALIND_HRD_TRIAGE_PACKET_RUN=public-evidence-hg008-depth-20260617 "
        f"ROSALIND_HRD_TRIAGE_ID=diana-raw-{analysis}-triage {PY_COMMAND} triage:rosalind-hrd-readiness"
    )
    return [
        {
            "step": "1",
            "name": "refresh_template_and_contract",
            "command_or_action": f"{PY_COMMAND} build:diana-template",
            "success_evidence": f"{DIANA_RAW_TEMPLATE}; {DIANA_RAW_RESULTS}/input_contract.json",
            "boundary": "Template readiness only; no Diana files are validated.",
        },
        {
            "step": "2",
            "name": "copy_and_fill_samplesheet",
            "command_or_action": f"cp {DIANA_RAW_TEMPLATE} {samplesheet}",
            "success_evidence": "Tumor and matched normal DNA rows contain real local paths, reference metadata, and shared pair_id.",
            "boundary": "Do not leave template placeholder paths or pending metadata in strict mode.",
        },
        {
            "step": "3",
            "name": "cloud_upload_permission_gate",
            "command_or_action": "Record whether human-data cloud upload is allowed before S3, Batch, or external transfer.",
            "success_evidence": "Reviewer-visible approval note in samplesheet notes/caveat or analysis packet.",
            "boundary": "No AWS Batch or S3 upload for human data until permission is explicit.",
        },
        {
            "step": "4",
            "name": "strict_validate_diana_inputs",
            "command_or_action": strict_validate,
            "success_evidence": f"{DIANA_RAW_RESULTS}/input_validation_summary.json status passed",
            "boundary": "Passing validation proves files and pairing are staged; it is not an HRD result.",
        },
        {
            "step": "5",
            "name": "stage_diana_raw_analysis_packet",
            "command_or_action": stage,
            "success_evidence": f"results/diana_raw_analysis/{analysis}/analysis_packet.json",
            "boundary": "Staging records inputs and planned commands; compute lanes still require review.",
        },
        {
            "step": "6",
            "name": "refresh_rosalind_raw_intake_packet",
            "command_or_action": packet,
            "success_evidence": f"results/rosalind_hrd/diana_raw_intake/diana-raw-{analysis}/reviewer_packet.md",
            "boundary": "The packet should remain no-call until downstream feature lanes pass.",
        },
        {
            "step": "7",
            "name": "refresh_readiness_triage",
            "command_or_action": triage,
            "success_evidence": f"results/rosalind_hrd/readiness_triage/diana-raw-{analysis}-triage/blocker_triage.md",
            "boundary": "Triage should show file-arrival blockers closed only after strict validation passes.",
        },
        {
            "step": "8",
            "name": "route_first_compute_lane",
            "command_or_action": "Use WGS rows for WGS feature lanes; use WES rows for small-variant mechanics; keep RNA as context.",
            "success_evidence": "A reviewed lane-specific command plan in results/diana_raw_analysis/<analysis_id>/recompute_command_plan.csv.",
            "boundary": "Do not compute scarHRD, CHORD, SBS3, or HRDetect-style results until their adapters and policies are locked.",
        },
    ]


def markdown_plan(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Dinah Raw File Handoff Plan",
        "",
        f"Status: `{summary['status']}`",
        f"Samplesheet: `{summary['samplesheet']}`",
        f"Analysis ID: `{analysis_id()}`",
        "",
        "## Current State",
        "",
        f"- DNA rows: `{summary.get('dnaRowCount', 0)}`",
        f"- RNA rows: `{summary.get('rnaRows', 0)}`",
        f"- Matched pair IDs: `{';'.join(summary.get('matchedPairIds', [])) or 'none'}`",
        f"- Structural errors: `{len(summary.get('structuralErrors', []))}`",
        f"- Warnings: `{len(summary.get('warnings', []))}`",
        "",
        "## Handoff Steps",
        "",
        "| step | name | command_or_action | success_evidence | boundary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {step} | {name} | `{command}` | {evidence} | {boundary} |".format(
                step=row["step"],
                name=row["name"],
                command=row["command_or_action"].replace("|", "\\|"),
                evidence=row["success_evidence"].replace("|", "\\|"),
                boundary=row["boundary"].replace("|", "\\|"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "This plan prepares intake and routing only. It does not validate Dinah's actual files, run HRD feature lanes, or support a clinical HRD interpretation until strict validation, downstream evidence generation, public sidecar checks, and reviewer sign-off are complete.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    samplesheet = selected_samplesheet()
    analysis = analysis_id()
    state = sample_state(samplesheet)
    rows = handoff_rows(samplesheet, analysis)
    ensure_dir(path_from_root(DIANA_RAW_RESULTS))
    summary = {
        "generatedAt": iso_now(),
        "status": state["status"],
        "samplesheet": samplesheet,
        "analysisId": analysis,
        "contract": diana_raw_contract(),
        "currentState": state,
        "handoffSteps": rows,
        "interpretationBoundary": (
            "Handoff planning does not validate actual files or produce HRD evidence; strict validation and downstream "
            "feature lanes must pass before interpretation."
        ),
    }
    write_csv(path_from_root(f"{DIANA_RAW_RESULTS}/dinah_handoff_plan.csv"), rows)
    write_json(path_from_root(f"{DIANA_RAW_RESULTS}/dinah_handoff_plan.json"), summary)
    write_text(path_from_root(f"{DIANA_RAW_RESULTS}/dinah_handoff_plan.md"), markdown_plan(state, rows))
    print(f"Dinah raw file handoff plan written: {DIANA_RAW_RESULTS}/dinah_handoff_plan.md")


if __name__ == "__main__":
    main()
