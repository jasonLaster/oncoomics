from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class TraceRow:
    source: str
    task_id: str
    name: str
    status: str
    exit: str
    duration_seconds: Optional[float]
    realtime_seconds: Optional[float]
    native_id: str

    @property
    def stage(self) -> str:
        return stage_name(self.name)


def parse_duration_seconds(value: str) -> Optional[float]:
    raw = value.strip()
    if not raw or raw == "-":
        return None
    total = 0.0
    matched = False
    for match in re.finditer(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)\b", raw):
        matched = True
        amount = float(match.group(1))
        unit = match.group(2)
        if unit == "ms":
            total += amount / 1000
        elif unit == "s":
            total += amount
        elif unit == "m":
            total += amount * 60
        elif unit == "h":
            total += amount * 60 * 60
        elif unit == "d":
            total += amount * 60 * 60 * 24
    return total if matched else None


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    rounded = int(round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def stage_name(name: str) -> str:
    if "PHASE3_FETCH_WORKSPACE" in name or "PHASE3_FETCH " in name:
        return "phase3_fetch"
    if "PHASE3_REFERENCE_INDEX" in name:
        return "reference_index"
    if "PHASE3_ALIGN_SAMPLE" in name:
        if "align_tumor" in name:
            return "align_tumor"
        if "align_normal" in name:
            return "align_normal"
        return "align_sample"
    if "PHASE3_DOWNSTREAM" in name:
        return "downstream"
    if "PHASE3_SRA_BENCHMARK" in name:
        return "sra_benchmark"
    if "PHASE3_WGS (" in name:
        return "phase3_monolith"
    return "other"


def read_trace(path: Path) -> list[TraceRow]:
    if not path.exists():
        return []
    rows: list[TraceRow] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for record in reader:
            if record.get("task_id") == "task_id" or not record.get("name"):
                continue
            rows.append(
                TraceRow(
                    source=str(path),
                    task_id=record.get("task_id", ""),
                    name=record.get("name", ""),
                    status=record.get("status", ""),
                    exit=record.get("exit", ""),
                    duration_seconds=parse_duration_seconds(record.get("duration", "")),
                    realtime_seconds=parse_duration_seconds(record.get("realtime", "")),
                    native_id=record.get("native_id", ""),
                )
            )
    return rows


def read_traces(paths: Iterable[Path]) -> list[TraceRow]:
    rows: list[TraceRow] = []
    for path in paths:
        rows.extend(read_trace(path))
    return rows


def best_completed_by_stage(rows: Iterable[TraceRow]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.status not in {"COMPLETED", "CACHED"}:
            continue
        seconds = row.duration_seconds
        if seconds is None:
            continue
        current = best.get(row.stage)
        if current is None or seconds < float(current["durationSeconds"]):
            best[row.stage] = {
                "stage": row.stage,
                "status": row.status,
                "durationSeconds": seconds,
                "realtimeSeconds": row.realtime_seconds,
                "duration": format_duration(seconds),
                "realtime": format_duration(row.realtime_seconds),
                "source": row.source,
                "name": row.name,
                "nativeId": row.native_id,
            }
    return best


FAILURE_PATTERNS: list[tuple[str, str]] = [
    ("spot_or_host_interruption", r"Host EC2 .* terminated"),
    ("aws_credentials_metadata", r"Error when retrieving credentials from container-role"),
    ("duplicate_alignment_resume", r"Terminate duplicate .* alignment"),
    ("manual_or_superseded_termination", r"\bsuperseded\b|Killing running tasks"),
    ("report_overwrite", r"(Report|Timeline) file already exists"),
    ("missing_cloudwatch_stream", r"Unable to find CloudWatch log stream"),
]


def extract_failure_signals(text: str) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    lines = text.splitlines()
    for label, pattern in FAILURE_PATTERNS:
        regex = re.compile(pattern)
        for index, line in enumerate(lines):
            if regex.search(line):
                signals.append({"label": label, "line": line.strip(), "lineNumber": str(index + 1)})
                break
    return signals


def workflow_failed_duration_seconds(text: str) -> Optional[float]:
    matches = re.findall(r"failedDuration=([^;]+);", text)
    durations = [parse_duration_seconds(match) for match in matches]
    clean = [duration for duration in durations if duration is not None]
    return max(clean) if clean else None


def summarize_logs(paths: Iterable[Path]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        signals = extract_failure_signals(text)
        failed_duration = workflow_failed_duration_seconds(text)
        if signals or failed_duration is not None:
            summaries.append(
                {
                    "source": str(path),
                    "failedDurationSeconds": failed_duration,
                    "failedDuration": format_duration(failed_duration),
                    "signals": signals,
                }
            )
    return summaries


def trace_status_counts(rows: Iterable[TraceRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def estimate_split_checkpoint_speedup(best: dict[str, dict[str, Any]], log_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    monolith_failures = [
        float(summary["failedDurationSeconds"])
        for summary in log_summaries
        if summary.get("failedDurationSeconds") is not None
        and any(signal.get("label") in {"spot_or_host_interruption", "aws_credentials_metadata"} for signal in summary.get("signals", []))
    ]
    fetch = best.get("phase3_fetch")
    reference = best.get("reference_index")
    if not monolith_failures or not fetch or not reference:
        return {"available": False}
    split_seconds = float(fetch["durationSeconds"]) + float(reference["durationSeconds"])
    baseline_seconds = max(monolith_failures)
    return {
        "available": True,
        "baselineSeconds": baseline_seconds,
        "baseline": format_duration(baseline_seconds),
        "splitCheckpointSeconds": split_seconds,
        "splitCheckpoint": format_duration(split_seconds),
        "speedup": round(baseline_seconds / split_seconds, 2) if split_seconds else "",
        "scope": "through fetch plus reference-index checkpoints",
    }


def build_diagnostics(trace_paths: Iterable[Path], log_paths: Iterable[Path]) -> dict[str, Any]:
    rows = read_traces(trace_paths)
    best = best_completed_by_stage(rows)
    log_summaries = summarize_logs(log_paths)
    return {
        "traceRowCount": len(rows),
        "statusCounts": trace_status_counts(rows),
        "bestCompletedByStage": best,
        "logSummaries": log_summaries,
        "speedupEstimate": estimate_split_checkpoint_speedup(best, log_summaries),
        "recommendations": recommendations(best, log_summaries),
    }


def recommendations(best: dict[str, dict[str, Any]], log_summaries: list[dict[str, Any]]) -> list[str]:
    labels = {signal["label"] for summary in log_summaries for signal in summary.get("signals", [])}
    notes: list[str] = []
    if "duplicate_alignment_resume" in labels:
        notes.append(
            "Persist cloud-generated alignment BAM/BAI outputs in the asset cache so launcher interruptions do not force alignment rework."
        )
    if "aws_credentials_metadata" in labels:
        notes.append(
            "Keep AWS smoke tests split and short; credential or host failures should burn minutes, not multi-hour monolithic runs."
        )
    if "report_overwrite" in labels:
        notes.append("Enable Nextflow report/timeline overwrite or use unique report names for resume loops.")
    if "phase3_fetch" in best and "reference_index" in best and ("align_tumor" not in best or "align_normal" not in best):
        notes.append("The next optimization target is alignment checkpoint durability; fetch and reference-index already complete quickly.")
    return notes


def render_markdown(diagnostics: dict[str, Any]) -> str:
    lines = [
        "# Pipeline Diagnostics",
        "",
        "## Summary",
        "",
        f"- Trace rows reviewed: {diagnostics['traceRowCount']}",
        f"- Trace statuses: {diagnostics['statusCounts']}",
    ]
    speedup = diagnostics.get("speedupEstimate", {})
    if speedup.get("available"):
        lines.append(
            f"- Split checkpoint acceleration: {speedup['baseline']} baseline failure window to {speedup['splitCheckpoint']} "
            f"through fetch/reference, about {speedup['speedup']}x faster ({speedup['scope']})."
        )
    else:
        lines.append("- Split checkpoint acceleration: not enough trace/log evidence yet.")
    lines.extend(["", "## Best Completed Stages", ""])
    best = diagnostics.get("bestCompletedByStage", {})
    if best:
        lines.append("| Stage | Status | Duration | Realtime | Source |")
        lines.append("| --- | --- | --- | --- | --- |")
        for stage in ["sra_benchmark", "phase3_fetch", "reference_index", "align_tumor", "align_normal", "downstream"]:
            row = best.get(stage)
            if not row:
                continue
            source = Path(str(row["source"])).name
            lines.append(f"| {stage} | {row['status']} | {row['duration']} | {row['realtime']} | {source} |")
    else:
        lines.append("No completed stages found in trace artifacts.")
    lines.extend(["", "## Failure Signals", ""])
    any_signal = False
    for summary in diagnostics.get("logSummaries", []):
        signals = summary.get("signals", [])
        if not signals:
            continue
        any_signal = True
        lines.append(f"- `{summary['source']}`: {', '.join(signal['label'] for signal in signals)}")
    if not any_signal:
        lines.append("No known failure signatures found.")
    lines.extend(["", "## Recommendations", ""])
    for note in diagnostics.get("recommendations", []):
        lines.append(f"- {note}")
    if not diagnostics.get("recommendations"):
        lines.append("- No immediate diagnostic recommendation.")
    return "\n".join(lines) + "\n"
