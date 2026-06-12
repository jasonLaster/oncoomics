from __future__ import annotations

from pathlib import Path

from ..paths import ROOT, path_from_root
from ..pipeline_diagnostics import build_diagnostics, render_markdown
from ..utils import ensure_dir, read_json, write_json, write_text


def collect_trace_paths(root: Path) -> list[Path]:
    return sorted((root / "logs").glob("*.trace.tsv"))


def collect_log_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    paths.extend(sorted((root / "logs").glob("*.log")))
    paths.extend(sorted((root / "logs").glob("nextflow.log*")))
    paths.extend(sorted((root / "nextflow-out/aws").glob("**/nextflow.log")))
    paths.extend(sorted((root / "nextflow-out/aws").glob("**/launcher.out")))
    return sorted({path for path in paths if path.is_file()})


def current_result_statuses() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for relative_path in [
        "results/phase3_wgs_smoke/fastq_summary.json",
        "results/phase3_wgs_smoke/phase3_wgs_summary.json",
        "results/full_wes_benchmark/full_wes_benchmark_summary.json",
        "results/orthogonal_validation/public_examples_summary.json",
    ]:
        path = path_from_root(relative_path)
        if not path.exists():
            statuses[relative_path] = "missing"
            continue
        try:
            statuses[relative_path] = str(read_json(path).get("status", "unknown"))
        except Exception as error:
            statuses[relative_path] = f"unreadable: {error}"
    return statuses


def main() -> None:
    ensure_dir(path_from_root("results"))
    diagnostics = build_diagnostics(collect_trace_paths(ROOT), collect_log_paths(ROOT))
    diagnostics["currentResultStatuses"] = current_result_statuses()
    write_json(path_from_root("results/pipeline_diagnostics.json"), diagnostics)
    report = render_markdown(diagnostics)
    report += "\n## Current Result Statuses\n\n"
    for path, status in diagnostics["currentResultStatuses"].items():
        report += f"- `{path}`: {status}\n"
    write_text(path_from_root("results/pipeline_diagnostics.md"), report)
    print("Pipeline diagnostics written to results/pipeline_diagnostics.md and results/pipeline_diagnostics.json.")
