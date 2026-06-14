from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

SOURCE_COPY_EXCLUDES = (".git/", ".nextflow/", "work/", "nextflow-out/")
PHASE3_FASTQ_DIR = "data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/fastq"
PHASE3_BAM_DIR = "data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/ucsc_hg38_analysis_set_full/full/bam"
PHASE3_LOG_DIR = "results/phase3_wgs_smoke/logs"
PHASE3_STAGE_MARKER_DIR = "results/phase3_wgs_smoke/stage_markers"
DOWNSTREAM_REUSABLE_ARTIFACTS = (
    "results/phase3_wgs_smoke/bam_validation_summary.csv",
    "results/phase3_wgs_smoke/bam_validation_summary.json",
    "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.json",
    "results/phase3_wgs_smoke/seqc2_truth_depth.tsv",
    "results/phase3_wgs_smoke/sv_evidence_candidates.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.json",
)
POST_VALIDATION_CONTEXT_ARTIFACTS = (
    "data/raw/cbioportal/sample_ids_by_list.json",
    "data/raw/cbioportal/mutations_hrr.json",
    "data/raw/cbioportal/cna_hrr_gistic.json",
    "data/raw/cbioportal/expression_marker_genes.json",
    "data/raw/cbioportal/clinical_sample_selected.json",
    "data/raw/cbioportal/clinical_patient_selected.json",
    "data/raw/xena/brca_clinical_matrix.tsv",
    "data/processed/catalog/cbioportal_tcga_brca_summary.json",
    "data/processed/catalog/gdc_tcga_brca_open_summary.json",
    "data/processed/catalog/xena_tcga_brca_clinical_summary.json",
)
SOURCE_WORKSPACE_STAGES = {
    "quick",
    "full_wes",
    "phase3_fetch",
    "phase3_fetch_workspace",
    "phase3_sra_benchmark",
    "phase3_wgs",
    "all_public",
}
PREVIOUS_WORKSPACE_STAGES = {
    "phase3_reference_index",
    "phase3_align_sample",
    "phase3_prepare_fastq_shards",
    "phase3_align_shard",
    "phase3_gather_shards",
    "phase3_post_validation",
}
STAGES = tuple(sorted(SOURCE_WORKSPACE_STAGES | PREVIOUS_WORKSPACE_STAGES | {"phase3_downstream"}))


@dataclass(frozen=True)
class WorkflowStep:
    kind: str
    command: str = ""
    message: str = ""
    path: str = ""
    success_message: str = ""
    failure_message: str = ""


@dataclass(frozen=True)
class ProcessConfig:
    stage: str
    workspace: Path = Path("workspace")
    python_bin: str = sys.executable or "/usr/bin/python3"
    source_dir: Optional[Path] = None
    previous_workspace: Optional[Path] = None
    tumor_workspace: Optional[Path] = None
    normal_workspace: Optional[Path] = None
    role: str = ""
    tumor_role: str = ""
    normal_role: str = ""
    skip_wiki_checks: str = "false"
    task_cpus: str = ""
    phase3_reads: str = "500000"
    phase3_fetch_concurrency: str = "2"
    phase3_aria2_split: str = "1"
    phase3_source_mode: str = "ena_fastq"
    phase3_sra_aws_bucket: str = "sra-pub-run-odp"
    phase3_s3_range_concurrency: str = "8"
    phase3_s3_range_bytes: str = "268435456"
    phase3_s3_range_retries: str = "4"
    phase3_sra_run_concurrency: str = "1"
    phase3_sra_command_retries: str = "2"
    phase3_fastq_stats_mode: str = "seqkit"
    phase3_cache_upload_workers: str = "4"
    phase3_alignment_cache_workers: str = "2"
    phase3_aligner: str = "bwa"
    phase3_bwa_threads: str = "0"
    phase3_sort_threads: str = "0"
    phase3_align_input_mode: str = "local_fastq"
    phase3_align_profile_mode: str = "pipe"
    phase3_scatter_output_mode: str = "merged_bam"
    phase3_shard_input_mode: str = "fastq_cache"
    phase3_force: str = "false"
    phase3_force_shard_alignment: str = "false"
    phase3_shard_count: str = "1"
    phase3_shard_index: str = "0"
    phase3_bam_validation_mode: str = "full"
    phase3_coverage_cnv_mode: str = "full"
    phase3_asset_cache_uri: str = ""
    phase3_asset_cache_mode: str = "readwrite"
    phase3_delete_sra_after_conversion: str = "false"
    phase3_include_wes: bool = False
    phase3_prereq_mode: str = "minimal"
    sra_benchmark_runs: str = "SRR7890824,SRR7890827"
    sra_benchmark_bytes: str = "1073741824"
    sra_benchmark_parts: str = "1"
    sra_benchmark_strategy: str = "aws_s3api_range"
    sra_benchmark_matrix: str = ""


def python_step(command: str) -> WorkflowStep:
    return WorkflowStep(kind="python", command=command)


def optional_python_step(command: str, success_message: str = "", failure_message: str = "") -> WorkflowStep:
    return WorkflowStep(kind="optional_python", command=command, success_message=success_message, failure_message=failure_message)


def message_step(message: str) -> WorkflowStep:
    return WorkflowStep(kind="message", message=message)


def remove_path_step(path: str) -> WorkflowStep:
    return WorkflowStep(kind="remove_path", path=path)


def python_steps(commands: Sequence[str]) -> tuple[WorkflowStep, ...]:
    return tuple(python_step(command) for command in commands)


CORE_SETUP = (
    "verify:plan",
    "fetch:phase1",
    "fetch:raw-candidates",
    "audit:raw-tools",
    "build:diana-template",
    "verify:diana-raw",
    "build:raw-samplesheets",
)
SMOKE_PREREQUISITES = (
    "smoke:raw",
    "build:alignment-smoke",
    "smoke:alignment",
    "fetch:human-reference-smoke",
    "smoke:human-reference",
)
FULL_REFERENCE = ("fetch:full-reference-smoke", "smoke:full-reference")
PRODUCTION_SOMATIC = ("fetch:production-somatic", "smoke:production-somatic")
FULL_WES = ("fetch:full-wes", "benchmark:full-wes")
FINAL_ANALYSIS = ("build:panel", "analyze:hrd", "analyze:rna", "build:packet")


def quick_steps() -> tuple[WorkflowStep, ...]:
    return (
        python_steps(CORE_SETUP)
        + python_steps(SMOKE_PREREQUISITES)
        + python_steps(FULL_REFERENCE)
        + python_steps(PRODUCTION_SOMATIC)
        + python_steps(FINAL_ANALYSIS)
        + (
            optional_python_step(
                "verify:outputs",
                success_message="Full output verification passed.",
                failure_message="Full output verification did not pass; quick does not recompute full-source WGS acceptance artifacts.",
            ),
        )
    )


def full_wes_steps() -> tuple[WorkflowStep, ...]:
    return (
        python_steps(CORE_SETUP)
        + python_steps(SMOKE_PREREQUISITES)
        + python_steps(FULL_REFERENCE)
        + python_steps(PRODUCTION_SOMATIC)
        + python_steps(FULL_WES)
        + (python_step("verify:orthogonal"),)
        + python_steps(FINAL_ANALYSIS)
        + (
            optional_python_step(
                "verify:outputs",
                success_message="Full output verification passed.",
                failure_message="Full output verification did not pass; full_wes does not recompute full-source WGS acceptance artifacts.",
            ),
        )
    )


def phase3_fetch_steps() -> tuple[WorkflowStep, ...]:
    return python_steps(CORE_SETUP + ("fetch:full-reference-smoke", "fetch:production-somatic", "fetch:phase3-wgs"))


def phase3_wes_prerequisite_steps(config: ProcessConfig, split_workflow: bool) -> tuple[WorkflowStep, ...]:
    if config.phase3_include_wes:
        return python_steps(FULL_WES)
    workflow_name = "split Phase 3 WGS" if split_workflow else "Phase 3 WGS"
    return (message_step(f"Skipping full WES prerequisite for {workflow_name}; use --phase3_include_wes true for orthogonal WES ladder."),)


def phase3_fetch_workspace_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    setup_steps: tuple[WorkflowStep, ...]
    if config.phase3_prereq_mode == "none":
        setup_steps = (message_step("Skipping public context setup for split Phase 3 WGS alignment-speed experiment."),)
    else:
        setup_steps = python_steps(CORE_SETUP)
    production_somatic_steps: tuple[WorkflowStep, ...]
    if config.phase3_prereq_mode == "full":
        production_somatic_steps = python_steps(PRODUCTION_SOMATIC)
    else:
        production_somatic_steps = (
            message_step("Skipping production somatic prerequisites for split Phase 3 WGS minimal mode."),
        )
    return (
        setup_steps
        + python_steps(("fetch:full-reference-smoke",))
        + production_somatic_steps
        + phase3_wes_prerequisite_steps(config, split_workflow=True)
        + (python_step("fetch:phase3-wgs"), remove_path_step(PHASE3_FASTQ_DIR))
    )


def reference_index_from_source(config: ProcessConfig) -> bool:
    return config.stage == "phase3_reference_index" and config.previous_workspace is None


def phase3_reference_index_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    if reference_index_from_source(config):
        return phase3_fetch_workspace_steps(config) + (python_step("validate:phase3-wgs"),)
    return (python_step("validate:phase3-wgs"),)


def phase3_align_sample_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    if config.phase3_align_input_mode == "cache_stream":
        return (python_step("validate:phase3-wgs"), remove_path_step(PHASE3_FASTQ_DIR), remove_path_step(PHASE3_BAM_DIR))
    return (
        python_step("fetch:phase3-wgs"),
        python_step("validate:phase3-wgs"),
        remove_path_step(PHASE3_FASTQ_DIR),
        remove_path_step(PHASE3_BAM_DIR),
    )


def phase3_prepare_fastq_shards_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    return (python_step("validate:phase3-wgs"), remove_path_step(PHASE3_FASTQ_DIR))


def phase3_align_shard_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    return (python_step("validate:phase3-wgs"), remove_path_step(PHASE3_FASTQ_DIR), remove_path_step(PHASE3_BAM_DIR))


def phase3_gather_shards_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    return (python_step("validate:phase3-wgs"),)


def phase3_prerequisite_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    steps = python_steps(CORE_SETUP)
    if config.phase3_prereq_mode == "full":
        steps += python_steps(SMOKE_PREREQUISITES)
    else:
        steps += (message_step("Skipping raw/alignment/human-reference smoke prerequisites for Phase 3 WGS minimal mode."),)
    steps += (python_step("fetch:full-reference-smoke"),)
    if config.phase3_prereq_mode == "full":
        steps += (python_step("smoke:full-reference"),)
    else:
        steps += (message_step("Skipping full-reference smoke alignment for Phase 3 WGS minimal mode."),)
    if config.phase3_prereq_mode == "full":
        steps += python_steps(PRODUCTION_SOMATIC)
    else:
        steps += (message_step("Skipping production somatic prerequisites for Phase 3 WGS minimal mode."),)
    return steps


def orthogonal_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    if config.phase3_include_wes:
        return (python_step("verify:orthogonal"),)
    return (message_step("Skipping orthogonal WES verification because --phase3_include_wes is false."),)


def phase3_output_gate_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    if config.phase3_reads == "full":
        if config.phase3_include_wes:
            return (python_step("verify:outputs"),)
        return (python_step("verify:phase3-outputs"),)
    return (
        message_step("Skipping fatal full output verification for bounded Phase 3 developer run."),
        optional_python_step("verify:outputs"),
    )


def phase3_downstream_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    return (
        (python_step("validate:phase3-wgs"),) + orthogonal_steps(config) + python_steps(FINAL_ANALYSIS) + phase3_output_gate_steps(config)
    )


def phase3_post_validation_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    return (python_step("verify:phase3-outputs"),) + orthogonal_steps(config) + python_steps(FINAL_ANALYSIS) + phase3_output_gate_steps(config)


def phase3_wgs_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    return (
        phase3_prerequisite_steps(config)
        + phase3_wes_prerequisite_steps(config, split_workflow=False)
        + (python_step("fetch:phase3-wgs"), python_step("validate:phase3-wgs"))
        + orthogonal_steps(config)
        + python_steps(FINAL_ANALYSIS)
        + phase3_output_gate_steps(config)
    )


def all_public_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    verification_steps: tuple[WorkflowStep, ...]
    if config.phase3_reads == "full":
        verification_steps = (python_step("verify:outputs"),)
    else:
        verification_steps = (
            message_step("Skipping fatal full output verification for bounded Phase 3 developer run."),
            optional_python_step("verify:outputs"),
        )
    return (
        python_steps(CORE_SETUP)
        + python_steps(SMOKE_PREREQUISITES)
        + python_steps(FULL_REFERENCE)
        + python_steps(PRODUCTION_SOMATIC)
        + python_steps(FULL_WES)
        + (python_step("fetch:phase3-wgs"), python_step("validate:phase3-wgs"), python_step("verify:orthogonal"))
        + python_steps(FINAL_ANALYSIS)
        + verification_steps
    )


def workflow_steps(config: ProcessConfig) -> tuple[WorkflowStep, ...]:
    if config.stage == "quick":
        return quick_steps()
    if config.stage == "full_wes":
        return full_wes_steps()
    if config.stage == "phase3_fetch":
        return phase3_fetch_steps()
    if config.stage == "phase3_fetch_workspace":
        return phase3_fetch_workspace_steps(config)
    if config.stage == "phase3_reference_index":
        return phase3_reference_index_steps(config)
    if config.stage == "phase3_align_sample":
        return phase3_align_sample_steps(config)
    if config.stage == "phase3_prepare_fastq_shards":
        return phase3_prepare_fastq_shards_steps(config)
    if config.stage == "phase3_align_shard":
        return phase3_align_shard_steps(config)
    if config.stage == "phase3_gather_shards":
        return phase3_gather_shards_steps(config)
    if config.stage == "phase3_downstream":
        return phase3_downstream_steps(config)
    if config.stage == "phase3_post_validation":
        return phase3_post_validation_steps(config)
    if config.stage == "phase3_sra_benchmark":
        return (python_step("benchmark:sra-range"),)
    if config.stage == "phase3_wgs":
        return phase3_wgs_steps(config)
    if config.stage == "all_public":
        return all_public_steps(config)
    raise ValueError(f"Unknown Nextflow process stage: {config.stage}")


def as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def inherited_or_default(env: dict[str, str], name: str, default: str) -> str:
    return env.get(name) or default


def process_environment(config: ProcessConfig, workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DIANA_OMICS_ROOT": str(workspace),
            "DIANA_OMICS_SKIP_WIKI_CHECKS": config.skip_wiki_checks,
            "PYTHONPATH": str(workspace / "src"),
            "PYTHON_BIN": config.python_bin,
        }
    )
    if config.stage == "full_wes":
        env["PHASE2F_THREADS"] = inherited_or_default(env, "PHASE2F_THREADS", config.task_cpus or "8")
    if config.stage == "all_public":
        env["PHASE2F_THREADS"] = inherited_or_default(env, "PHASE2F_THREADS", "8")
    if config.stage in {
        "phase3_fetch",
        "phase3_fetch_workspace",
        "phase3_align_sample",
        "phase3_prepare_fastq_shards",
        "phase3_align_shard",
        "phase3_gather_shards",
        "phase3_wgs",
        "all_public",
    } or reference_index_from_source(config):
        env.update(phase3_fetch_environment(config, env))
    if config.stage in {
        "phase3_reference_index",
        "phase3_align_sample",
        "phase3_prepare_fastq_shards",
        "phase3_align_shard",
        "phase3_gather_shards",
        "phase3_downstream",
        "phase3_wgs",
        "all_public",
    }:
        env.update(phase3_stage_environment(config, env))
    if config.stage in {"phase3_align_sample", "phase3_prepare_fastq_shards", "phase3_align_shard", "phase3_gather_shards"}:
        env["PHASE3_WGS_FETCH_ONLY_ROLE"] = config.role
        env["PHASE3_WGS_SAMPLE_ROLE"] = config.role
    if config.stage == "phase3_sra_benchmark":
        env.update(sra_benchmark_environment(config, env))
    return env


def phase3_fetch_environment(config: ProcessConfig, env: dict[str, str]) -> dict[str, str]:
    manifest_only_stage = config.stage == "phase3_fetch_workspace" or reference_index_from_source(config)
    fastq_local_mode = "cache_manifest" if manifest_only_stage and config.phase3_align_input_mode == "cache_stream" else "hydrate"
    require_gatk = "1" if config.phase3_prereq_mode == "full" else "0"
    return {
        "PHASE3_WGS_READS": config.phase3_reads,
        "PHASE3_WGS_FETCH_CONCURRENCY": config.phase3_fetch_concurrency,
        "PHASE3_WGS_ARIA2_SPLIT": config.phase3_aria2_split,
        "PHASE3_WGS_SOURCE_MODE": config.phase3_source_mode,
        "PHASE3_WGS_SRA_AWS_BUCKET": config.phase3_sra_aws_bucket,
        "PHASE3_WGS_SRA_THREADS": inherited_or_default(env, "PHASE3_WGS_SRA_THREADS", config.task_cpus or "1"),
        "PHASE3_WGS_S3_RANGE_CONCURRENCY": config.phase3_s3_range_concurrency,
        "PHASE3_WGS_S3_RANGE_BYTES": config.phase3_s3_range_bytes,
        "PHASE3_WGS_S3_RANGE_RETRIES": config.phase3_s3_range_retries,
        "PHASE3_WGS_SRA_RUN_CONCURRENCY": config.phase3_sra_run_concurrency,
        "PHASE3_WGS_SRA_COMMAND_RETRIES": config.phase3_sra_command_retries,
        "PHASE3_WGS_FASTQ_STATS_MODE": config.phase3_fastq_stats_mode,
        "PHASE3_WGS_FASTQ_LOCAL_MODE": inherited_or_default(env, "PHASE3_WGS_FASTQ_LOCAL_MODE", fastq_local_mode),
        "PHASE3_WGS_CACHE_UPLOAD_WORKERS": config.phase3_cache_upload_workers,
        "PHASE3_WGS_ASSET_CACHE_URI": config.phase3_asset_cache_uri,
        "PHASE3_WGS_ASSET_CACHE_MODE": config.phase3_asset_cache_mode,
        "PHASE3_WGS_DELETE_SRA_AFTER_CONVERSION": config.phase3_delete_sra_after_conversion,
        "PHASE3_WGS_REQUIRE_GATK": inherited_or_default(env, "PHASE3_WGS_REQUIRE_GATK", require_gatk),
    }


def phase3_stage_environment(config: ProcessConfig, env: dict[str, str]) -> dict[str, str]:
    stage_by_process = {
        "phase3_reference_index": "reference_index",
        "phase3_align_sample": "align_sample",
        "phase3_prepare_fastq_shards": "prepare_fastq_shards",
        "phase3_align_shard": "align_shard",
        "phase3_gather_shards": "gather_shards",
        "phase3_downstream": "downstream",
    }
    values = {
        "PHASE3_WGS_READS": config.phase3_reads,
        "PHASE3_WGS_THREADS": inherited_or_default(env, "PHASE3_WGS_THREADS", config.task_cpus or "1"),
        "PHASE3_WGS_ALIGNER": inherited_or_default(env, "PHASE3_WGS_ALIGNER", config.phase3_aligner),
        "PHASE3_WGS_BWA_THREADS": inherited_or_default(env, "PHASE3_WGS_BWA_THREADS", config.phase3_bwa_threads),
        "PHASE3_WGS_SORT_THREADS": inherited_or_default(env, "PHASE3_WGS_SORT_THREADS", config.phase3_sort_threads),
        "PHASE3_WGS_ALIGN_INPUT_MODE": inherited_or_default(
            env, "PHASE3_WGS_ALIGN_INPUT_MODE", config.phase3_align_input_mode
        ),
        "PHASE3_WGS_ALIGN_PROFILE_MODE": inherited_or_default(
            env, "PHASE3_WGS_ALIGN_PROFILE_MODE", config.phase3_align_profile_mode
        ),
        "PHASE3_WGS_SCATTER_OUTPUT_MODE": inherited_or_default(
            env, "PHASE3_WGS_SCATTER_OUTPUT_MODE", config.phase3_scatter_output_mode
        ),
        "PHASE3_WGS_SHARD_INPUT_MODE": inherited_or_default(env, "PHASE3_WGS_SHARD_INPUT_MODE", config.phase3_shard_input_mode),
        "PHASE3_WGS_FORCE": "1" if as_bool(config.phase3_force) else inherited_or_default(env, "PHASE3_WGS_FORCE", "0"),
        "PHASE3_WGS_FORCE_SHARD_ALIGNMENT": (
            "1"
            if as_bool(config.phase3_force_shard_alignment)
            else inherited_or_default(env, "PHASE3_WGS_FORCE_SHARD_ALIGNMENT", "0")
        ),
        "PHASE3_WGS_SHARD_COUNT": inherited_or_default(env, "PHASE3_WGS_SHARD_COUNT", config.phase3_shard_count),
        "PHASE3_WGS_SHARD_INDEX": inherited_or_default(env, "PHASE3_WGS_SHARD_INDEX", config.phase3_shard_index),
        "PHASE3_WGS_BAM_VALIDATION_MODE": inherited_or_default(
            env, "PHASE3_WGS_BAM_VALIDATION_MODE", config.phase3_bam_validation_mode
        ),
        "PHASE3_WGS_COVERAGE_CNV_MODE": inherited_or_default(
            env, "PHASE3_WGS_COVERAGE_CNV_MODE", config.phase3_coverage_cnv_mode
        ),
        "PHASE3_WGS_ALIGNMENT_CACHE_WORKERS": config.phase3_alignment_cache_workers,
        "PHASE3_WGS_ASSET_CACHE_URI": config.phase3_asset_cache_uri,
        "PHASE3_WGS_ASSET_CACHE_MODE": config.phase3_asset_cache_mode,
    }
    if config.stage in stage_by_process:
        values["PHASE3_WGS_STAGE"] = stage_by_process[config.stage]
    if config.stage in {"phase3_align_sample", "phase3_prepare_fastq_shards", "phase3_align_shard", "phase3_gather_shards", "phase3_downstream"}:
        values["PHASE3_WGS_PARALLEL_ALIGN"] = "0"
    return values


def sra_benchmark_environment(config: ProcessConfig, env: dict[str, str]) -> dict[str, str]:
    aws_cli = shutil.which("aws") or ""
    fallback_aws = Path("/opt/diana-aws/bin/aws")
    if not aws_cli and fallback_aws.is_file() and os.access(fallback_aws, os.X_OK):
        aws_cli = str(fallback_aws)
    if not aws_cli:
        raise RuntimeError("AWS CLI is required for phase3_sra_benchmark.")
    return {
        "AWS_CA_BUNDLE": env.get("AWS_CA_BUNDLE") or "/etc/ssl/certs/ca-certificates.crt",
        "AWS_CLI": aws_cli,
        "S5CMD": shutil.which("s5cmd") or "",
        "BYTES": config.sra_benchmark_bytes,
        "PARTS": config.sra_benchmark_parts,
        "RUNS": config.sra_benchmark_runs,
        "BUCKET": config.phase3_sra_aws_bucket,
        "CONCURRENCY": config.phase3_fetch_concurrency,
        "STRATEGY": config.sra_benchmark_strategy,
        "MATRIX": config.sra_benchmark_matrix,
    }


class ProcessRunner:
    def __init__(self, workspace: Path, python_bin: str, env: dict[str, str]) -> None:
        self.workspace = workspace
        self.python_bin = python_bin
        self.env = env

    def run_python(self, command: str, check: bool = True) -> bool:
        argv = [self.python_bin, "-m", "diana_omics", command]
        print(f"==> {shlex.join(argv)}", flush=True)
        completed = subprocess.run(argv, cwd=self.workspace, env=self.env, check=False)
        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, argv)
        return completed.returncode == 0

    def run_step(self, step: WorkflowStep) -> None:
        if step.kind == "python":
            self.run_python(step.command)
            return
        if step.kind == "optional_python":
            passed = self.run_python(step.command, check=False)
            message = step.success_message if passed else step.failure_message
            if message:
                print(f"==> {message}", flush=True)
            return
        if step.kind == "message":
            print(f"==> {step.message}", flush=True)
            return
        if step.kind == "remove_path":
            remove_path(self.workspace / step.path)
            return
        raise ValueError(f"Unknown workflow step kind: {step.kind}")


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def copy_optional_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    run_rsync(["-a", f"{source.resolve()}/", f"{destination.resolve()}/"])


def run_rsync(args: Sequence[str]) -> None:
    subprocess.run(["rsync", *args], check=True)


def prepare_source_workspace(source_dir: Path, workspace: Path) -> None:
    remove_path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    args = ["-a", "--delete"]
    for pattern in SOURCE_COPY_EXCLUDES:
        args.extend(["--exclude", pattern])
    args.extend([f"{source_dir.resolve()}/", f"{workspace.resolve()}/"])
    run_rsync(args)


def prepare_previous_workspace(previous_workspace: Path, workspace: Path) -> None:
    remove_path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    run_rsync(["-a", f"{previous_workspace.resolve()}/", f"{workspace.resolve()}/"])


def merge_downstream_workspaces(config: ProcessConfig) -> None:
    if config.tumor_role != "tumor" or config.normal_role != "normal":
        raise RuntimeError(f"Expected tumor then normal workspaces, got {config.tumor_role} and {config.normal_role}.")
    tumor_workspace = require_path(config.tumor_workspace, "--tumor-workspace")
    normal_workspace = require_path(config.normal_workspace, "--normal-workspace")
    workspace = config.workspace
    prepare_previous_workspace(tumor_workspace, workspace)
    for relative_path in (PHASE3_BAM_DIR, PHASE3_LOG_DIR, PHASE3_STAGE_MARKER_DIR):
        (workspace / relative_path).mkdir(parents=True, exist_ok=True)
    copy_optional_tree(normal_workspace.resolve() / PHASE3_BAM_DIR, workspace.resolve() / PHASE3_BAM_DIR)
    copy_optional_tree(normal_workspace.resolve() / PHASE3_LOG_DIR, workspace.resolve() / PHASE3_LOG_DIR)
    copy_optional_tree(normal_workspace.resolve() / PHASE3_STAGE_MARKER_DIR, workspace.resolve() / PHASE3_STAGE_MARKER_DIR)
    for reusable_source in (tumor_workspace, normal_workspace):
        for artifact in DOWNSTREAM_REUSABLE_ARTIFACTS:
            source = reusable_source / artifact
            if source.is_file():
                destination = workspace / artifact
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)


def stage_post_validation_context(source_dir: Path, workspace: Path) -> None:
    missing: list[str] = []
    for artifact in POST_VALIDATION_CONTEXT_ARTIFACTS:
        source = source_dir / artifact
        if not source.is_file():
            missing.append(artifact)
            continue
        destination = workspace / artifact
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    if missing:
        raise RuntimeError(
            "phase3_post_validation source workspace is missing required public context artifacts: " + ", ".join(missing)
        )


def require_post_validation_context(workspace: Path) -> None:
    missing = [artifact for artifact in POST_VALIDATION_CONTEXT_ARTIFACTS if not (workspace / artifact).is_file()]
    if missing:
        raise RuntimeError(
            "phase3_post_validation requires staged cBioPortal/Xena/GDC context artifacts. "
            "Pass --source-dir from a repo workspace with fetch:phase1 outputs, or include these files in --previous-workspace: "
            + ", ".join(missing)
        )


def require_path(path: Optional[Path], flag_name: str) -> Path:
    if path is None:
        raise RuntimeError(f"{flag_name} is required for this Nextflow process stage.")
    return path


def prepare_workspace(config: ProcessConfig) -> Path:
    workspace = config.workspace.resolve()
    if reference_index_from_source(config):
        prepare_source_workspace(require_path(config.source_dir, "--source-dir"), workspace)
    elif config.stage in SOURCE_WORKSPACE_STAGES:
        prepare_source_workspace(require_path(config.source_dir, "--source-dir"), workspace)
    elif (
        config.stage == "phase3_gather_shards"
        and config.previous_workspace is None
        and config.phase3_scatter_output_mode == "shard_manifest"
    ):
        workspace.mkdir(parents=True, exist_ok=True)
    elif config.stage in PREVIOUS_WORKSPACE_STAGES:
        prepare_previous_workspace(require_path(config.previous_workspace, "--previous-workspace"), workspace)
        if config.stage == "phase3_post_validation":
            if config.source_dir is not None:
                stage_post_validation_context(config.source_dir.resolve(), workspace)
            require_post_validation_context(workspace)
    elif config.stage == "phase3_downstream":
        merge_downstream_workspaces(config)
        workspace = config.workspace.resolve()
    else:
        raise ValueError(f"Unknown Nextflow process stage: {config.stage}")
    return workspace


def run_process(config: ProcessConfig) -> None:
    workspace = prepare_workspace(config)
    env = process_environment(config, workspace)
    runner = ProcessRunner(workspace, config.python_bin, env)
    for step in workflow_steps(config):
        runner.run_step(step)


def write_stub_outputs(config: ProcessConfig) -> None:
    workspace = config.workspace
    if config.stage == "phase3_reference_index":
        write_json_stub(workspace / PHASE3_STAGE_MARKER_DIR / "reference_index.json", {"stub": True, "stage": "reference_index"})
        return
    if config.stage == "phase3_align_sample":
        role = config.role or "unknown"
        write_json_stub(workspace / PHASE3_STAGE_MARKER_DIR / f"align_{role}.json", {"stub": True, "stage": "align_sample", "role": role})
        return
    if config.stage == "phase3_prepare_fastq_shards":
        role = config.role or "unknown"
        (workspace / "src").mkdir(parents=True, exist_ok=True)
        (workspace / "manifests").mkdir(parents=True, exist_ok=True)
        (workspace / "manifests/phase3_wgs_smoke_samplesheet.csv").write_text("role,run_accession,sample,read_pairs_per_end\n", encoding="utf-8")
        (workspace / "results/phase3_wgs_smoke/shards").mkdir(parents=True, exist_ok=True)
        write_json_stub(workspace / "results/phase3_wgs_smoke/asset_summary.json", {"status": "ready", "stub": True})
        write_json_stub(
            workspace / PHASE3_STAGE_MARKER_DIR / f"shard_fastq_{role}.json",
            {"stub": True, "stage": "prepare_fastq_shards", "role": role, "shards": config.phase3_shard_count},
        )
        return
    if config.stage == "phase3_align_shard":
        role = config.role or "unknown"
        write_json_stub(
            workspace / PHASE3_STAGE_MARKER_DIR / f"align_{role}_shard{int(config.phase3_shard_index):02d}of{int(config.phase3_shard_count):02d}.json",
            {
                "stub": True,
                "stage": "align_shard",
                "role": role,
                "shardIndex": config.phase3_shard_index,
                "shardCount": config.phase3_shard_count,
            },
        )
        return
    if config.stage == "phase3_gather_shards":
        role = config.role or "unknown"
        write_json_stub(
            workspace / PHASE3_STAGE_MARKER_DIR / f"gather_{role}_{config.phase3_shard_count}way.json",
            {"stub": True, "stage": "gather_shards", "role": role, "shards": config.phase3_shard_count},
        )
        return
    if config.stage == "phase3_sra_benchmark":
        result_dir = workspace / "results/phase3_wgs_smoke"
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "sra_benchmark.json").write_text(json.dumps({"sourceMode": "aws_sra", "stub": True}) + "\n", encoding="utf-8")
        (result_dir / "sra_benchmark.tsv").touch()
        return
    (workspace / "manifests").mkdir(parents=True, exist_ok=True)
    (workspace / "results").mkdir(parents=True, exist_ok=True)
    if config.stage == "phase3_downstream":
        (workspace / "results/phase3_wgs_smoke").mkdir(parents=True, exist_ok=True)
    (workspace / "results/nextflow_stub_help.txt").write_text(f"stub for {config.stage}\n", encoding="utf-8")


def write_json_stub(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Diana Omics Nextflow process stage.")
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--stub", action="store_true")
    parser.add_argument("--workspace", default="workspace")
    parser.add_argument("--python-bin", default=sys.executable or "/usr/bin/python3")
    parser.add_argument("--source-dir")
    parser.add_argument("--previous-workspace")
    parser.add_argument("--tumor-workspace")
    parser.add_argument("--normal-workspace")
    parser.add_argument("--role", default="")
    parser.add_argument("--tumor-role", default="")
    parser.add_argument("--normal-role", default="")
    parser.add_argument("--skip-wiki-checks", default="false")
    parser.add_argument("--task-cpus", default="")
    parser.add_argument("--phase3-reads", default="500000")
    parser.add_argument("--phase3-fetch-concurrency", default="2")
    parser.add_argument("--phase3-aria2-split", default="1")
    parser.add_argument("--phase3-source-mode", default="ena_fastq")
    parser.add_argument("--phase3-sra-aws-bucket", default="sra-pub-run-odp")
    parser.add_argument("--phase3-s3-range-concurrency", default="8")
    parser.add_argument("--phase3-s3-range-bytes", default="268435456")
    parser.add_argument("--phase3-s3-range-retries", default="4")
    parser.add_argument("--phase3-sra-run-concurrency", default="1")
    parser.add_argument("--phase3-sra-command-retries", default="2")
    parser.add_argument("--phase3-fastq-stats-mode", default="seqkit")
    parser.add_argument("--phase3-cache-upload-workers", default="4")
    parser.add_argument("--phase3-alignment-cache-workers", default="2")
    parser.add_argument("--phase3-aligner", default="bwa")
    parser.add_argument("--phase3-bwa-threads", default="0")
    parser.add_argument("--phase3-sort-threads", default="0")
    parser.add_argument("--phase3-align-input-mode", default="local_fastq")
    parser.add_argument("--phase3-align-profile-mode", default="pipe")
    parser.add_argument("--phase3-scatter-output-mode", default="merged_bam")
    parser.add_argument("--phase3-shard-input-mode", default="fastq_cache")
    parser.add_argument("--phase3-force", default="false")
    parser.add_argument("--phase3-force-shard-alignment", default="false")
    parser.add_argument("--phase3-shard-count", default="1")
    parser.add_argument("--phase3-shard-index", default="0")
    parser.add_argument("--phase3-bam-validation-mode", default="full")
    parser.add_argument("--phase3-coverage-cnv-mode", default="full")
    parser.add_argument("--phase3-asset-cache-uri", default="")
    parser.add_argument("--phase3-asset-cache-mode", default="readwrite")
    parser.add_argument("--phase3-delete-sra-after-conversion", default="false")
    parser.add_argument("--phase3-include-wes", default="false")
    parser.add_argument("--phase3-prereq-mode", default="minimal")
    parser.add_argument("--sra-benchmark-runs", default="SRR7890824,SRR7890827")
    parser.add_argument("--sra-benchmark-bytes", default="1073741824")
    parser.add_argument("--sra-benchmark-parts", default="1")
    parser.add_argument("--sra-benchmark-strategy", default="aws_s3api_range")
    parser.add_argument("--sra-benchmark-matrix", default="")
    return parser.parse_args(argv)


def optional_path(value: Optional[str]) -> Optional[Path]:
    return Path(value) if value else None


def config_from_args(args: argparse.Namespace) -> ProcessConfig:
    return ProcessConfig(
        stage=args.stage,
        workspace=Path(args.workspace),
        python_bin=args.python_bin,
        source_dir=optional_path(args.source_dir),
        previous_workspace=optional_path(args.previous_workspace),
        tumor_workspace=optional_path(args.tumor_workspace),
        normal_workspace=optional_path(args.normal_workspace),
        role=args.role,
        tumor_role=args.tumor_role,
        normal_role=args.normal_role,
        skip_wiki_checks=args.skip_wiki_checks,
        task_cpus=args.task_cpus,
        phase3_reads=args.phase3_reads,
        phase3_fetch_concurrency=args.phase3_fetch_concurrency,
        phase3_aria2_split=args.phase3_aria2_split,
        phase3_source_mode=args.phase3_source_mode,
        phase3_sra_aws_bucket=args.phase3_sra_aws_bucket,
        phase3_s3_range_concurrency=args.phase3_s3_range_concurrency,
        phase3_s3_range_bytes=args.phase3_s3_range_bytes,
        phase3_s3_range_retries=args.phase3_s3_range_retries,
        phase3_sra_run_concurrency=args.phase3_sra_run_concurrency,
        phase3_sra_command_retries=args.phase3_sra_command_retries,
        phase3_fastq_stats_mode=args.phase3_fastq_stats_mode,
        phase3_cache_upload_workers=args.phase3_cache_upload_workers,
        phase3_alignment_cache_workers=args.phase3_alignment_cache_workers,
        phase3_aligner=args.phase3_aligner,
        phase3_bwa_threads=args.phase3_bwa_threads,
        phase3_sort_threads=args.phase3_sort_threads,
        phase3_align_input_mode=args.phase3_align_input_mode,
        phase3_align_profile_mode=args.phase3_align_profile_mode,
        phase3_scatter_output_mode=args.phase3_scatter_output_mode,
        phase3_shard_input_mode=args.phase3_shard_input_mode,
        phase3_force=args.phase3_force,
        phase3_force_shard_alignment=args.phase3_force_shard_alignment,
        phase3_shard_count=args.phase3_shard_count,
        phase3_shard_index=args.phase3_shard_index,
        phase3_bam_validation_mode=args.phase3_bam_validation_mode,
        phase3_coverage_cnv_mode=args.phase3_coverage_cnv_mode,
        phase3_asset_cache_uri=args.phase3_asset_cache_uri,
        phase3_asset_cache_mode=args.phase3_asset_cache_mode,
        phase3_delete_sra_after_conversion=args.phase3_delete_sra_after_conversion,
        phase3_include_wes=as_bool(args.phase3_include_wes),
        phase3_prereq_mode=args.phase3_prereq_mode,
        sra_benchmark_runs=args.sra_benchmark_runs,
        sra_benchmark_bytes=args.sra_benchmark_bytes,
        sra_benchmark_parts=args.sra_benchmark_parts,
        sra_benchmark_strategy=args.sra_benchmark_strategy,
        sra_benchmark_matrix=args.sra_benchmark_matrix,
    )


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    config = config_from_args(args)
    if args.stub:
        write_stub_outputs(config)
        return
    run_process(config)


if __name__ == "__main__":
    main()
