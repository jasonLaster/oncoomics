from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json, write_text
from .build_rosalind_hrd_packet import DEFAULT_SAMPLE_SETS, RESULT_ROOT, markdown_table

TRIAGE_ROOT = f"{RESULT_ROOT}/readiness_triage"


def triage_id() -> str:
    value = os.environ.get("ROSALIND_HRD_TRIAGE_ID")
    if value:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "manual"
    return iso_now().replace(":", "").replace(".", "-")


def read_json_if_exists(relative_path: str | Path) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {}
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {"payload": payload}


def read_csv_if_exists(relative_path: str | Path) -> list[dict[str, str]]:
    path = path_from_root(relative_path)
    if not path.exists():
        return []
    return parse_csv(read_text(path))


def run_manifest_paths() -> list[Path]:
    root = path_from_root(RESULT_ROOT)
    if not root.exists():
        return []
    return sorted(root.glob("*/run_manifest.json"))


def load_manifest(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {}
    payload.setdefault("runId", path.parent.name)
    return payload


def all_manifests() -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for path in run_manifest_paths():
        manifest = load_manifest(path)
        if manifest:
            manifests.append(manifest)
    return manifests


def choose_packet_run(manifests: Sequence[Mapping[str, Any]]) -> str:
    explicit = os.environ.get("ROSALIND_HRD_TRIAGE_PACKET_RUN")
    if explicit:
        return explicit
    default_sets = set(DEFAULT_SAMPLE_SETS)
    full_runs = [
        manifest
        for manifest in manifests
        if default_sets.issubset({str(sample) for sample in manifest.get("sampleSets", []) if sample})
    ]
    candidates = full_runs or list(manifests)
    if not candidates:
        raise SystemExit(f"No Rosalind HRD packet run manifests found under {RESULT_ROOT}.")
    return str(max(candidates, key=lambda manifest: str(manifest.get("generatedAt", ""))).get("runId"))


def manifest_by_run_id(manifests: Sequence[Mapping[str, Any]], run_id: str) -> dict[str, Any]:
    for manifest in manifests:
        if manifest.get("runId") == run_id:
            return dict(manifest)
    raise SystemExit(f"Could not find Rosalind HRD packet run manifest for {run_id}.")


def packet_by_sample(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    packets = manifest.get("packets", [])
    if not isinstance(packets, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for packet in packets:
        if isinstance(packet, dict) and packet.get("sampleSet"):
            result[str(packet["sampleSet"])] = packet
    return result


def zero_blocker_runs(manifests: Sequence[Mapping[str, Any]], sample_set: str, *, excluding: str) -> list[str]:
    runs: list[str] = []
    for manifest in manifests:
        run_id = str(manifest.get("runId", ""))
        if not run_id or run_id == excluding:
            continue
        packet = packet_by_sample(manifest).get(sample_set)
        if not packet:
            continue
        blockers = packet.get("blockers", [])
        if isinstance(blockers, list) and not blockers:
            runs.append(run_id)
    return sorted(runs)


def adapter_state_counts(sample_set: str, packet_run_id: str) -> dict[str, int]:
    rows = read_csv_if_exists(f"{RESULT_ROOT}/{sample_set}/{packet_run_id}/hrd_adapter_status.csv")
    counts: dict[str, int] = {}
    for row in rows:
        state = row.get("state", "missing")
        counts[state] = counts.get(state, 0) + 1
    return counts


def contains_any(blockers: Sequence[str], tokens: Sequence[str]) -> bool:
    text = " ".join(blockers).lower()
    return any(token.lower() in text for token in tokens)


def classify_sample(sample_set: str, blockers: Sequence[str], closed_by_runs: Sequence[str]) -> tuple[str, str, str]:
    if sample_set == "hcc1395_wgs" and closed_by_runs and contains_any(blockers, ("no discordant mapped-pair counts", "metadata-only")):
        return (
            "closed_by_materialized_packet",
            "Use the zero-blocker selective/materialized HCC1395 WGS packet as the current WGS HRD evidence-surface demo.",
            "yes",
        )
    if not blockers:
        return (
            "packet_has_no_blockers",
            "Preserve the packet as a public-sample evidence boundary; do not promote no-call HRD adapters without required inputs.",
            "no",
        )
    if sample_set == "diana_raw_intake" or contains_any(blockers, ("actual diana", "diana bam", "diana raw")):
        return (
            "waiting_for_dinah_files",
            "Fill and validate manifests/diana_raw_inputs.csv when Dinah's actual BAM/FASTQ/CRAM paths arrive.",
            "external",
        )
    if contains_any(blockers, ("purity", "remote index", "local indexing")):
        return (
            "requires_transfer_or_indexing",
            "Transfer or index the selected public purity assets before trying to close this blocker.",
            "no",
        )
    if contains_any(blockers, ("sv/cnv callset", "sv/cna callset", "diana-generated sv", "reciprocal-overlap", "build reconciliation")):
        return (
            "requires_caller_or_truth_overlap_recompute",
            "Run or containerize the relevant caller/overlap lane before changing the packet state.",
            "no",
        )
    return ("blocked_or_needs_review", "Inspect the packet-specific blocker before rerunning a lane.", "review")


def triage_rows(packet_run_id: str, manifests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    manifest = manifest_by_run_id(manifests, packet_run_id)
    packets = packet_by_sample(manifest)
    rows: list[dict[str, Any]] = []
    for sample_set in sorted(packets):
        packet = packets[sample_set]
        raw_blockers = packet.get("blockers", [])
        blockers = [str(item) for item in raw_blockers] if isinstance(raw_blockers, list) else []
        closed_by = zero_blocker_runs(manifests, sample_set, excluding=packet_run_id)
        decision, next_action, actionable_now = classify_sample(sample_set, blockers, closed_by)
        rows.append(
            {
                "sample_set": sample_set,
                "packet_run_id": packet_run_id,
                "decision": decision,
                "actionable_now": actionable_now,
                "blocker_count": len(blockers),
                "adapter_state_counts": adapter_state_counts(sample_set, packet_run_id),
                "closed_by_runs": closed_by,
                "next_action": next_action,
                "blockers": blockers,
                "output_dir": packet.get("outputDir", ""),
            }
        )
    return rows


def csv_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "sample_set": str(row.get("sample_set", "")),
            "decision": str(row.get("decision", "")),
            "actionable_now": str(row.get("actionable_now", "")),
            "blocker_count": str(row.get("blocker_count", "")),
            "closed_by_runs": ";".join(str(item) for item in row.get("closed_by_runs", [])),
            "next_action": str(row.get("next_action", "")),
        }
        for row in rows
    ]


def markdown_for_triage(summary: Mapping[str, Any]) -> str:
    rows = summary.get("rows", [])
    table_rows = csv_rows(rows if isinstance(rows, list) else [])
    lines = [
        "# Rosalind HRD Readiness Triage",
        "",
        f"Triage ID: `{summary.get('triageId')}`",
        f"Packet run: `{summary.get('packetRunId')}`",
        "",
        "## Decision Board",
        markdown_table(table_rows),
        "",
        "## Interpretation Boundary",
        "This board identifies packet blockers and existing materialized packet closures. It does not promote SBS3, scarHRD, CHORD, or HRDetect-style interpretation unless the required production inputs and validation are present.",
        "",
        "## Blocker Detail",
    ]
    for row in rows if isinstance(rows, list) else []:
        blockers = row.get("blockers", [])
        lines.extend(
            [
                "",
                f"### {row.get('sample_set')}",
                f"- Decision: `{row.get('decision')}`",
                f"- Actionable now: `{row.get('actionable_now')}`",
                f"- Closed by runs: `{'; '.join(row.get('closed_by_runs', [])) or 'none'}`",
                f"- Next action: {row.get('next_action')}",
                "- Blockers:",
            ]
        )
        if blockers:
            lines.extend(f"  - {blocker}" for blocker in blockers)
        else:
            lines.append("  - None beyond adapter no-call boundaries.")
    return "\n".join(lines)


def write_triage(output_id: str, packet_run_id: str | None = None) -> dict[str, Any]:
    manifests = all_manifests()
    selected_run = packet_run_id or choose_packet_run(manifests)
    rows = triage_rows(selected_run, manifests)
    output_dir = f"{TRIAGE_ROOT}/{output_id}"
    ensure_dir(path_from_root(output_dir))
    summary = {
        "generatedAt": iso_now(),
        "triageId": output_id,
        "packetRunId": selected_run,
        "rows": rows,
        "remainingExternalBlockers": [
            row["sample_set"]
            for row in rows
            if row.get("decision") in {"waiting_for_dinah_files", "requires_transfer_or_indexing"}
        ],
        "materializedClosures": [
            row["sample_set"]
            for row in rows
            if row.get("decision") == "closed_by_materialized_packet"
        ],
    }
    write_json(path_from_root(f"{output_dir}/blocker_triage.json"), summary)
    write_csv(path_from_root(f"{output_dir}/blocker_triage.csv"), csv_rows(rows))
    write_text(path_from_root(f"{output_dir}/blocker_triage.md"), markdown_for_triage(summary))
    return summary


def main() -> None:
    output_id = triage_id()
    packet_run_id = os.environ.get("ROSALIND_HRD_TRIAGE_PACKET_RUN")
    summary = write_triage(output_id, packet_run_id)
    print(f"Rosalind HRD readiness triage written: {TRIAGE_ROOT}/{summary['triageId']}")


if __name__ == "__main__":
    main()
