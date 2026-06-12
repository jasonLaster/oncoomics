from __future__ import annotations

import argparse
from collections.abc import Callable

from .workflow_tasks import TASKS, run_task


def _load_commands() -> dict[str, Callable[[], None]]:
    from .commands.analyze_hrd import main as analyze_hrd
    from .commands.audit_raw_tools import main as audit_raw_tools
    from .commands.build_alignment_smoke_assets import main as build_alignment_smoke_assets
    from .commands.build_diana_raw_template import main as build_diana_raw_template
    from .commands.build_raw_samplesheets import main as build_raw_samplesheets
    from .commands.build_reference_panel import main as build_reference_panel
    from .commands.build_reviewer_packet import main as build_reviewer_packet
    from .commands.build_rna_context import main as build_rna_context
    from .commands.diagnose_pipeline import main as diagnose_pipeline
    from .commands.fetch_full_reference_smoke_assets import main as fetch_full_reference_smoke_assets
    from .commands.fetch_full_wes_benchmark_assets import main as fetch_full_wes_benchmark_assets
    from .commands.fetch_human_reference_smoke_assets import main as fetch_human_reference_smoke_assets
    from .commands.fetch_phase1 import main as fetch_phase1
    from .commands.fetch_phase3_wgs_smoke_assets import main as fetch_phase3_wgs_smoke_assets
    from .commands.fetch_production_somatic_assets import main as fetch_production_somatic_assets
    from .commands.fetch_raw_candidate_metadata import main as fetch_raw_candidate_metadata
    from .commands.run_alignment_smoke import main as run_alignment_smoke
    from .commands.run_full_reference_smoke import main as run_full_reference_smoke
    from .commands.run_full_wes_benchmark import main as run_full_wes_benchmark
    from .commands.run_human_reference_smoke import main as run_human_reference_smoke
    from .commands.run_phase3_wgs_smoke import main as run_phase3_wgs_smoke
    from .commands.run_production_somatic_smoke import main as run_production_somatic_smoke
    from .commands.run_raw_smoke import main as run_raw_smoke
    from .commands.run_sra_benchmark import main as run_sra_benchmark
    from .commands.stage_diana_raw_analysis import main as stage_diana_raw_analysis
    from .commands.verify_diana_raw import main as verify_diana_raw
    from .commands.verify_orthogonal_validation import main as verify_orthogonal_validation
    from .commands.verify_outputs import main as verify_outputs
    from .commands.verify_outputs import verify_phase3_outputs
    from .commands.verify_plan import main as verify_plan

    return {
        "analyze:hrd": analyze_hrd,
        "analyze:rna": build_rna_context,
        "audit:raw-tools": audit_raw_tools,
        "build:alignment-smoke": build_alignment_smoke_assets,
        "build:diana-template": build_diana_raw_template,
        "build:packet": build_reviewer_packet,
        "build:panel": build_reference_panel,
        "build:raw-samplesheets": build_raw_samplesheets,
        "benchmark:sra-range": run_sra_benchmark,
        "diagnose:pipeline": diagnose_pipeline,
        "fetch:full-reference-smoke": fetch_full_reference_smoke_assets,
        "fetch:full-wes": fetch_full_wes_benchmark_assets,
        "fetch:human-reference-smoke": fetch_human_reference_smoke_assets,
        "fetch:phase1": fetch_phase1,
        "fetch:phase3-wgs": fetch_phase3_wgs_smoke_assets,
        "fetch:production-somatic": fetch_production_somatic_assets,
        "fetch:raw-candidates": fetch_raw_candidate_metadata,
        "smoke:alignment": run_alignment_smoke,
        "smoke:full-reference": run_full_reference_smoke,
        "benchmark:full-wes": run_full_wes_benchmark,
        "smoke:human-reference": run_human_reference_smoke,
        "validate:phase3-wgs": run_phase3_wgs_smoke,
        "smoke:production-somatic": run_production_somatic_smoke,
        "smoke:raw": run_raw_smoke,
        "stage:diana-raw": stage_diana_raw_analysis,
        "verify:diana-raw": verify_diana_raw,
        "verify:orthogonal": verify_orthogonal_validation,
        "verify:outputs": verify_outputs,
        "verify:phase3-outputs": verify_phase3_outputs,
        "verify:plan": verify_plan,
    }


def main() -> None:
    commands = _load_commands()
    parser = argparse.ArgumentParser(description="Run Python Diana omics workflow commands.")
    command_names = sorted(set(commands) | set(TASKS))
    parser.add_argument("command", nargs="?", choices=command_names)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    if args.command in commands:
        if args.args:
            parser.error(f"{args.command} does not accept extra arguments")
        commands[args.command]()
    else:
        run_task(args.command, args.args)


if __name__ == "__main__":
    main()
