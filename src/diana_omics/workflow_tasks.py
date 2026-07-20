from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .paths import ROOT

NEXTFLOW_LOG_PATH = Path("logs") / "nextflow.log"
AWS_USE1_NEXTFLOW_PARAMS = "infra/aws/nextflow.aws.json"
AWS_USE2_NEXTFLOW_PARAMS = "infra/aws/nextflow.aws.use2.json"
AWS_USE1_TERRAFORM_WORKSPACE = "sra-use1"
AWS_USE2_TERRAFORM_WORKSPACE = "phase3-fast-use2"
AWS_USE1_TERRAFORM_ENV = {
    "TF_VAR_region": "us-east-1",
    "TF_VAR_environment": "prod-use1",
    "TF_VAR_nextflow_params_filename": "nextflow.aws.json",
}
AWS_USE2_TERRAFORM_ENV = {
    "TF_VAR_region": "us-east-2",
    "TF_VAR_environment": "prod-use2",
    "TF_VAR_enable_gpu_p5en_batch": "true",
    "TF_VAR_enable_parabricks_mirror": "true",
    "TF_VAR_manage_service_linked_roles": "false",
    "TF_VAR_nextflow_params_filename": "nextflow.aws.use2.json",
}
AWS_USE1_ECR_PUSH_ENV = {
    "AWS_REGION": "us-east-1",
    "DIANA_AWS_TERRAFORM_WORKSPACE": AWS_USE1_TERRAFORM_WORKSPACE,
}
AWS_USE2_ECR_PUSH_ENV = {
    "AWS_REGION": "us-east-2",
    "DIANA_AWS_TERRAFORM_WORKSPACE": AWS_USE2_TERRAFORM_WORKSPACE,
}
SRA_BENCH_RANGE_MATRIX = ",".join(
    (
        "aws_s3api_range:4:268435456:4:aws-range-c4",
        "aws_s3api_range:8:268435456:4:aws-range-c8",
        "aws_s3api_range:16:134217728:4:aws-range-c16",
        "s5cmd_cat:4:268435456:4:s5cat-c4",
        "s5cmd_cat:8:268435456:4:s5cat-c8",
    )
)
LEGACY_PHASE3_AWS_FULL_ENV = {"ALLOW_LEGACY_PHASE3_AWS_FULL": "YES"}
LEGACY_PHASE3_CPU_FULL_NEXTFLOW_ARGS = ("--allow_legacy_phase3_cpu_full", "true")
LEGACY_PHASE3_AWS_FULL_DESCRIPTION = (
    "Legacy full-source AWS Phase 3 WGS CPU runs are disabled for Diana reruns. "
    "Use the P5 Hopper/Parabricks phase3_wgs_fast path after quota and GPU smoke pass. "
    "Set ALLOW_LEGACY_PHASE3_AWS_FULL=YES only for an explicitly approved legacy public WGS run."
)
PHASE3_FAST_AWS_EXECUTE_ENV = {"ALLOW_PHASE3_FAST_AWS_EXECUTE": "YES"}
PHASE3_FAST_PARABRICKS_NUM_GPUS = "8"
PHASE3_FAST_AWS_EXECUTE_DESCRIPTION = (
    "Phase 3 fast AWS execute mode runs the full Diana BAM-to-evidence P5 Hopper/Parabricks path. "
    "Set ALLOW_PHASE3_FAST_AWS_EXECUTE=YES only after Gate 0 receipts, P-family quota, a pinned mirrored "
    "Parabricks image, the PARABRICKS_MIRROR_RECEIPT receipt, the PHASE3_FAST_GPU_SMOKE_RESULT "
    "gpu_smoke.json, and the forbidden-token scan inventory have been reviewed."
)
PHASE3_FAST_AWS_EXECUTE_ALLOWED_EXTRA_ARGS = frozenset(
    {
        "--phase3_fast_bam_validation_receipt",
        "--phase3_fast_caller_resource_receipt",
        "--phase3_fast_contig_compatibility_receipt",
        "--phase3_fast_forbidden_tokens_json",
        "--phase3_fast_generated_at",
        "--phase3_fast_parameter_sha256",
        "--phase3_fast_parabricks_version",
        "--phase3_fast_private_freeze_receipt",
        "--phase3_fast_private_sha256_receipt",
        "--phase3_fast_reference_freeze_receipt",
        "--phase3_fast_reference_sha256_receipt",
        "--phase3_fast_sequenza_female",
        "--phase3_fast_source_commit",
    }
)


@dataclass(frozen=True)
class TaskStep:
    argv: tuple[str, ...]
    env: Optional[Mapping[str, str]] = None
    cwd: Path = ROOT
    append_args: bool = False


@dataclass(frozen=True)
class Task:
    steps: tuple[TaskStep, ...]
    accepts_args: bool = False
    allowed_extra_args: Optional[frozenset[str]] = None
    description: str = ""
    required_env: Optional[Mapping[str, str]] = None


def _python_bin() -> str:
    return os.environ.get("PYTHON_BIN", sys.executable or "/usr/bin/python3")


def _python_env(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    path_entries = [str(ROOT / "src")]
    current = os.environ.get("PYTHONPATH")
    if current:
        path_entries.append(current)
    env = {"PYTHONPATH": os.pathsep.join(path_entries)}
    if extra:
        env.update(extra)
    return env


def _git_short_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "local"


def _image_tag() -> str:
    return os.environ.get("AWS_IMAGE_TAG", _git_short_sha())


def _py(command: str, env: Optional[Mapping[str, str]] = None) -> TaskStep:
    return TaskStep((_python_bin(), "-m", "diana_omics", command), env=_python_env(env))


def _tool(*argv: str, env: Optional[Mapping[str, str]] = None, append_args: bool = False) -> TaskStep:
    return TaskStep(tuple(argv), env=env, append_args=append_args)


def _nextflow(*args: str, append_args: bool = False) -> TaskStep:
    return _tool("nextflow", "-log", str(NEXTFLOW_LOG_PATH), "run", "main.nf", *args, append_args=append_args)


def _aws_daily_cost_guard(params_file: str) -> TaskStep:
    return _tool("bash", "infra/aws/check-daily-cost-guard.sh", params_file)


def _aws_nextflow_params_file(step: TaskStep) -> str | None:
    if not step.argv or step.argv[0] != "nextflow":
        return None
    try:
        profile = step.argv[step.argv.index("-profile") + 1]
    except (ValueError, IndexError):
        return None
    if not profile.startswith("awsbatch"):
        return None
    try:
        return step.argv[step.argv.index("-params-file") + 1]
    except (ValueError, IndexError) as error:
        raise ValueError("AWS Nextflow tasks must pass -params-file before the daily cost guard") from error


def _with_aws_daily_cost_guards(steps: Sequence[TaskStep]) -> tuple[TaskStep, ...]:
    guarded: list[TaskStep] = []
    for step in steps:
        params_file = _aws_nextflow_params_file(step)
        if params_file is not None:
            guarded.append(_aws_daily_cost_guard(params_file))
        guarded.append(step)
    return tuple(guarded)


def _terraform(*args: str, env: Optional[Mapping[str, str]] = None) -> TaskStep:
    return _tool("terraform", "-chdir=infra/aws", *args, env=env)


def _tf_image_env(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    env = {"TF_VAR_image_tag": _image_tag()}
    if extra:
        env.update(extra)
    return env


def _task(
    *steps: TaskStep,
    accepts_args: bool = False,
    allowed_extra_args: Optional[frozenset[str]] = None,
    description: str = "",
    required_env: Optional[Mapping[str, str]] = None,
) -> Task:
    return Task(
        _with_aws_daily_cost_guards(steps),
        accepts_args=accepts_args,
        allowed_extra_args=allowed_extra_args,
        description=description,
        required_env=required_env,
    )


def _legacy_phase3_aws_full_task(*steps: TaskStep) -> Task:
    return _task(
        *(_allow_legacy_phase3_cpu_full(step) for step in steps),
        description=LEGACY_PHASE3_AWS_FULL_DESCRIPTION,
        required_env=LEGACY_PHASE3_AWS_FULL_ENV,
    )


def _allow_legacy_phase3_cpu_full(step: TaskStep) -> TaskStep:
    if not step.argv or step.argv[0] != "nextflow":
        return step
    return TaskStep(
        (*step.argv, *LEGACY_PHASE3_CPU_FULL_NEXTFLOW_ARGS),
        env=step.env,
        cwd=step.cwd,
        append_args=step.append_args,
    )


def _phase3_fast_aws_execute_task(*steps: TaskStep) -> Task:
    return _task(
        *steps,
        accepts_args=True,
        allowed_extra_args=PHASE3_FAST_AWS_EXECUTE_ALLOWED_EXTRA_ARGS,
        description=PHASE3_FAST_AWS_EXECUTE_DESCRIPTION,
        required_env=PHASE3_FAST_AWS_EXECUTE_ENV,
    )


TASKS: dict[str, Task] = {
    "verify:plan:online": _task(_py("verify:plan", {"CHECK_URLS": "1"})),
    "py:lint": _task(_tool(_python_bin(), "-m", "ruff", "check", "src", "tests")),
    "py:format": _task(_tool(_python_bin(), "-m", "ruff", "format", "src", "tests")),
    "py:format:check": _task(_tool(_python_bin(), "-m", "ruff", "format", "--check", "src", "tests")),
    "py:typecheck": _task(
        _tool(
            _python_bin(),
            "-m",
            "mypy",
            "--config-file",
            "pyproject.toml",
            "src",
            "tests",
            env={"MYPYPATH": "src"},
        )
    ),
    "py:test": _task(_tool(_python_bin(), "-m", "pytest", "tests", env=_python_env(), append_args=True), accepts_args=True),
    "typecheck": _task(_tool(_python_bin(), "-m", "mypy", "--config-file", "pyproject.toml", "src", "tests", env={"MYPYPATH": "src"})),
    "test": _task(_tool(_python_bin(), "-m", "pytest", "tests", env=_python_env(), append_args=True), accepts_args=True),
    "benchmark:known-answer": _task(
        _tool(_python_bin(), "-m", "diana_omics.commands.known_answer.run_known_answer_benchmark", env=_python_env(), append_args=True),
        accepts_args=True,
    ),
    "run:all": _task(
        _py("verify:plan"),
        _py("fetch:phase1"),
        _py("fetch:raw-candidates"),
        _py("audit:raw-tools"),
        _py("build:diana-template"),
        _py("verify:diana-raw"),
        _py("build:raw-samplesheets"),
        _py("smoke:raw"),
        _py("build:alignment-smoke"),
        _py("smoke:alignment"),
        _py("fetch:human-reference-smoke"),
        _py("smoke:human-reference"),
        _py("fetch:full-reference-smoke"),
        _py("smoke:full-reference"),
        _py("fetch:production-somatic"),
        _py("smoke:production-somatic"),
        _py("fetch:full-wes"),
        _py("benchmark:full-wes"),
        _py("fetch:phase3-wgs"),
        _py("validate:phase3-wgs"),
        _py("verify:orthogonal"),
        _py("build:panel"),
        _py("analyze:hrd"),
        _py("analyze:rna"),
        _py("analyze:lehmann"),
        _py("build:packet"),
        _py("verify:outputs"),
    ),
    "phase3:stage:fetch:tumor": _task(_py("fetch:phase3-wgs", {"PHASE3_WGS_FETCH_ONLY_ROLE": "tumor"})),
    "phase3:stage:fetch:normal": _task(_py("fetch:phase3-wgs", {"PHASE3_WGS_FETCH_ONLY_ROLE": "normal"})),
    "phase3:stage:ref": _task(_py("validate:phase3-wgs", {"PHASE3_WGS_STAGE": "reference_index"})),
    "phase3:stage:align:tumor": _task(
        _py(
            "validate:phase3-wgs",
            {
                "PHASE3_WGS_STAGE": "align_sample",
                "PHASE3_WGS_SAMPLE_ROLE": "tumor",
                "PHASE3_WGS_PARALLEL_ALIGN": "0",
            },
        )
    ),
    "phase3:stage:align:normal": _task(
        _py(
            "validate:phase3-wgs",
            {
                "PHASE3_WGS_STAGE": "align_sample",
                "PHASE3_WGS_SAMPLE_ROLE": "normal",
                "PHASE3_WGS_PARALLEL_ALIGN": "0",
            },
        )
    ),
    "phase3:stage:downstream": _task(_py("validate:phase3-wgs", {"PHASE3_WGS_STAGE": "downstream", "PHASE3_WGS_PARALLEL_ALIGN": "0"})),
    "nf:quick": _task(_nextflow("-profile", "local", "--workflow", "quick")),
    "nf:full-wes": _task(_nextflow("-profile", "local", "--workflow", "full_wes")),
    "nf:phase3-wgs:stub": _task(_nextflow("-profile", "local", "--workflow", "phase3_wgs", "--phase3_reads", "10000", "-stub-run")),
    "nf:docker:phase3-wgs:stub": _task(_nextflow("-profile", "docker", "--workflow", "phase3_wgs", "--phase3_reads", "10000", "-stub-run")),
    "nf:phase3-fetch:dev": _task(_nextflow("-profile", "local", "--workflow", "phase3_fetch", "--phase3_reads", "500000")),
    "nf:phase3-fetch:full": _task(
        _nextflow(
            "-profile",
            "local",
            "--workflow",
            "phase3_fetch",
            "--phase3_reads",
            "full",
            "--phase3_fetch_concurrency",
            "4",
            "--phase3_aria2_split",
            "1",
        )
    ),
    "nf:phase3-sra-benchmark": _task(_nextflow("-profile", "local", "--workflow", "phase3_sra_benchmark")),
    "nf:phase3-wgs-fast:stub": _task(_tool("bash", "scripts/run_phase3_wgs_fast_stub.sh")),
    "nf:known-answer-public-findings": _task(_nextflow("-profile", "local", "--workflow", "known_answer_public_findings")),
    "nf:known-answer-bounded-non-dry": _task(_nextflow("-profile", "local", "--workflow", "known_answer_bounded_non_dry")),
    "nf:known-answer-expanded-cohort": _task(_nextflow("-profile", "local", "--workflow", "known_answer_expanded_cohort")),
    "nf:phase3-wgs:dev": _task(_nextflow("-profile", "local", "--workflow", "phase3_wgs", "--phase3_reads", "500000")),
    "nf:phase3-wgs:full": _legacy_phase3_aws_full_task(
        _nextflow("-profile", "local", "--workflow", "phase3_wgs", "--phase3_reads", "full")
    ),
    "nf:phase3-wgs:monolith:full": _legacy_phase3_aws_full_task(
        _nextflow("-profile", "local", "--workflow", "phase3_wgs_monolith", "--phase3_reads", "full")
    ),
    "nf:all-public": _task(_nextflow("-profile", "local", "--workflow", "all_public", "--phase3_reads", "500000")),
    "infra:aws:init": _task(_terraform("init")),
    "infra:aws:fmt": _task(_terraform("fmt")),
    "infra:aws:fmt:check": _task(_terraform("fmt", "-check")),
    "infra:aws:validate": _task(_terraform("validate")),
    "infra:aws:use1": _task(_terraform("workspace", "select", AWS_USE1_TERRAFORM_WORKSPACE)),
    "infra:aws:use2": _task(_terraform("workspace", "select", "-or-create", AWS_USE2_TERRAFORM_WORKSPACE)),
    "infra:aws:plan": _task(_terraform("plan", env=_tf_image_env())),
    "infra:aws:apply": _task(_terraform("apply", env=_tf_image_env())),
    "infra:aws:plan:use1": _task(
        _terraform("workspace", "select", AWS_USE1_TERRAFORM_WORKSPACE),
        _terraform("plan", env=_tf_image_env(AWS_USE1_TERRAFORM_ENV)),
    ),
    "infra:aws:apply:use1": _task(
        _terraform("workspace", "select", AWS_USE1_TERRAFORM_WORKSPACE),
        _terraform("apply", env=_tf_image_env(AWS_USE1_TERRAFORM_ENV)),
    ),
    "infra:aws:plan:use2": _task(
        _terraform("workspace", "select", "-or-create", AWS_USE2_TERRAFORM_WORKSPACE),
        _terraform("plan", env=_tf_image_env(AWS_USE2_TERRAFORM_ENV)),
    ),
    "infra:aws:apply:use2": _task(
        _terraform("workspace", "select", "-or-create", AWS_USE2_TERRAFORM_WORKSPACE),
        _terraform("apply", env=_tf_image_env(AWS_USE2_TERRAFORM_ENV)),
    ),
    "aws:ecr:push": _task(_tool("bash", "infra/aws/push-image.sh")),
    "aws:ecr:push:use1": _task(_tool("bash", "infra/aws/push-image.sh", env=AWS_USE1_ECR_PUSH_ENV)),
    "aws:ecr:push:use2": _task(_tool("bash", "infra/aws/push-image.sh", env=AWS_USE2_ECR_PUSH_ENV)),
    "aws:ecr:mirror-parabricks:use2": _task(
        _tool("bash", "infra/aws/mirror-parabricks.sh", env=AWS_USE2_ECR_PUSH_ENV, append_args=True),
        accepts_args=True,
    ),
    "aws:hrd-packet:cloud-submit": _task(
        _tool("bash", "infra/aws/submit-hrd-packet-cloud.sh", append_args=True),
        accepts_args=True,
    ),
    "deploy:aws": _task(
        _tool("bash", "infra/aws/push-image.sh", env=AWS_USE1_ECR_PUSH_ENV),
        _terraform("workspace", "select", AWS_USE1_TERRAFORM_WORKSPACE),
        _terraform("apply", "-auto-approve", env=_tf_image_env(AWS_USE1_TERRAFORM_ENV)),
    ),
    "nf:aws:monitor": _task(_tool("bash", "infra/aws/monitor-batch-job.sh", append_args=True), accepts_args=True),
    "nf:aws:quick:stub": _task(
        _nextflow("-profile", "awsbatch_spot", "-params-file", "infra/aws/nextflow.aws.json", "--workflow", "quick", "-stub-run")
    ),
    "nf:aws:phase3-fetch:stub": _task(
        _nextflow(
            "-profile",
            "awsbatch_spot",
            "-params-file",
            AWS_USE1_NEXTFLOW_PARAMS,
            "--workflow",
            "phase3_fetch",
            "--phase3_reads",
            "10000",
            "-stub-run",
        )
    ),
    "nf:aws:phase3-wgs:stub": _task(
        _nextflow(
            "-profile",
            "awsbatch_spot",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_wgs",
            "--phase3_reads",
            "10000",
            "-stub-run",
        )
    ),
    "nf:aws:sra-bench:tiny": _task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_sra_benchmark",
            "--phase3_fetch_cpus",
            "2",
            "--phase3_fetch_memory",
            "8 GB",
            "--phase3_fetch_concurrency",
            "2",
            "--sra_benchmark_bytes",
            "16777216",
            "--sra_benchmark_parts",
            "1",
        )
    ),
    "nf:aws:phase3-fetch:tiny": _task(
        _nextflow(
            "-profile",
            "awsbatch_spot",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_fetch",
            "--phase3_reads",
            "10000",
            "--phase3_fetch_cpus",
            "2",
            "--phase3_fetch_memory",
            "8 GB",
            "--phase3_fetch_concurrency",
            "2",
        )
    ),
    "nf:aws:phase3-fetch:dev": _task(
        _nextflow(
            "-profile",
            "awsbatch_spot",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_fetch",
            "--phase3_reads",
            "500000",
            "--phase3_fetch_cpus",
            "4",
            "--phase3_fetch_memory",
            "16 GB",
        )
    ),
    "nf:aws:phase3-sra-benchmark": _task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_sra_benchmark",
            "--phase3_fetch_cpus",
            "4",
            "--phase3_fetch_memory",
            "16 GB",
            "--phase3_fetch_concurrency",
            "8",
            "--sra_benchmark_bytes",
            "268435456",
            "--sra_benchmark_parts",
            "4",
        )
    ),
    "nf:aws:known-answer-public-findings": _task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "known_answer_public_findings",
            "--phase3_fetch_cpus",
            "2",
            "--phase3_fetch_memory",
            "8 GB",
            "--aws_max_retries",
            "0",
        )
    ),
    "nf:aws:known-answer-bounded-non-dry": _task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "known_answer_bounded_non_dry",
            "--phase3_fetch_cpus",
            "2",
            "--phase3_fetch_memory",
            "8 GB",
            "--aws_max_retries",
            "0",
        )
    ),
    "nf:aws:known-answer-expanded-cohort": _task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "known_answer_expanded_cohort",
            "--phase3_fetch_cpus",
            "2",
            "--phase3_fetch_memory",
            "8 GB",
            "--aws_max_retries",
            "0",
        )
    ),
    "nf:aws:sra-bench:matrix:2cpu": _task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_sra_benchmark",
            "--phase3_fetch_cpus",
            "2",
            "--phase3_fetch_memory",
            "8 GB",
            "--sra_benchmark_matrix",
            SRA_BENCH_RANGE_MATRIX,
        )
    ),
    "nf:aws:sra-bench:matrix:4cpu": _task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_sra_benchmark",
            "--phase3_fetch_cpus",
            "4",
            "--phase3_fetch_memory",
            "16 GB",
            "--sra_benchmark_matrix",
            SRA_BENCH_RANGE_MATRIX,
        )
    ),
    "nf:aws:phase3-fetch:full": _task(
        _nextflow(
            "-profile",
            "awsbatch_spot",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_fetch",
            "--phase3_reads",
            "full",
            "--phase3_source_mode",
            "aws_sra",
            "--phase3_fetch_cpus",
            "8",
            "--phase3_fetch_memory",
            "28 GB",
            "--phase3_fetch_concurrency",
            "8",
            "--phase3_aria2_split",
            "8",
            "--phase3_s3_range_concurrency",
            "8",
            "--phase3_sra_run_concurrency",
            "2",
            "--phase3_cache_upload_workers",
            "4",
            "--phase3_fastq_stats_mode",
            "metadata",
        )
    ),
    "nf:aws:phase3-wgs:dev": _task(
        _nextflow(
            "-profile",
            "awsbatch_spot",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_wgs",
            "--phase3_reads",
            "500000",
        )
    ),
    "nf:aws:phase3-wgs:full": _legacy_phase3_aws_full_task(
        _nextflow(
            "-profile",
            "awsbatch_spot",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_wgs",
            "--phase3_reads",
            "full",
            "--phase3_source_mode",
            "aws_sra",
            "--phase3_fetch_cpus",
            "8",
            "--phase3_fetch_memory",
            "28 GB",
            "--phase3_ref_cpus",
            "16",
            "--phase3_ref_memory",
            "28 GB",
            "--phase3_align_cpus",
            "16",
            "--phase3_align_memory",
            "96 GB",
            "--phase3_downstream_cpus",
            "16",
            "--phase3_downstream_memory",
            "64 GB",
            "--phase3_fetch_concurrency",
            "8",
            "--phase3_s3_range_concurrency",
            "8",
            "--phase3_sra_run_concurrency",
            "2",
            "--phase3_cache_upload_workers",
            "4",
            "--phase3_alignment_cache_workers",
            "2",
            "--phase3_fastq_stats_mode",
            "metadata",
            "--phase3_bam_validation_mode",
            "flagstat_only",
            "--phase3_coverage_cnv_mode",
            "full",
            "--phase3_include_wes",
            "false",
            "--phase3_prereq_mode",
            "minimal",
        )
    ),
    "nf:aws:phase3-wgs:full:ondemand-large": _legacy_phase3_aws_full_task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_wgs",
            "--phase3_reads",
            "full",
            "--phase3_source_mode",
            "aws_sra",
            "--phase3_fetch_cpus",
            "8",
            "--phase3_fetch_memory",
            "48 GB",
            "--phase3_ref_cpus",
            "16",
            "--phase3_ref_memory",
            "32 GB",
            "--phase3_align_cpus",
            "32",
            "--phase3_align_memory",
            "96 GB",
            "--phase3_downstream_cpus",
            "16",
            "--phase3_downstream_memory",
            "64 GB",
            "--phase3_fetch_concurrency",
            "8",
            "--phase3_s3_range_concurrency",
            "8",
            "--phase3_sra_run_concurrency",
            "1",
            "--phase3_cache_upload_workers",
            "4",
            "--phase3_alignment_cache_workers",
            "2",
            "--phase3_fastq_stats_mode",
            "metadata",
            "--phase3_bam_validation_mode",
            "flagstat_only",
            "--phase3_coverage_cnv_mode",
            "full",
            "--phase3_include_wes",
            "false",
            "--phase3_prereq_mode",
            "minimal",
        )
    ),
    "nf:aws:phase3-wgs:full:ondemand-failfast": _legacy_phase3_aws_full_task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_wgs",
            "--phase3_reads",
            "full",
            "--phase3_source_mode",
            "public_bam",
            "--phase3_fetch_cpus",
            "8",
            "--phase3_fetch_memory",
            "48 GB",
            "--phase3_ref_cpus",
            "16",
            "--phase3_ref_memory",
            "32 GB",
            "--phase3_align_cpus",
            "16",
            "--phase3_align_memory",
            "96 GB",
            "--phase3_downstream_cpus",
            "16",
            "--phase3_downstream_memory",
            "64 GB",
            "--phase3_fetch_concurrency",
            "8",
            "--phase3_s3_range_concurrency",
            "8",
            "--phase3_sra_run_concurrency",
            "1",
            "--phase3_cache_upload_workers",
            "4",
            "--phase3_alignment_cache_workers",
            "2",
            "--phase3_fastq_stats_mode",
            "metadata",
            "--phase3_bam_validation_mode",
            "flagstat_only",
            "--phase3_coverage_cnv_mode",
            "full",
            "--phase3_include_wes",
            "false",
            "--phase3_prereq_mode",
            "minimal",
            "--phase3_bwa_threads",
            "12",
            "--phase3_sort_threads",
            "4",
            "--aws_max_retries",
            "0",
        )
    ),
    "nf:aws:phase3-wgs-fast:gpu-smoke": _task(
        _py("verify:phase3-fast-gpu-smoke"),
        _nextflow(
            "-profile",
            "awsbatch_gpu",
            "-params-file",
            AWS_USE2_NEXTFLOW_PARAMS,
            "--workflow",
            "phase3_wgs_fast_gpu_smoke",
            "--phase3_fast_gpu_smoke_expected_gpus",
            "8",
            "--phase3_fast_gpu_smoke_gpu_names",
            "H100,H200",
            "--phase3_fast_parabricks_num_gpus",
            PHASE3_FAST_PARABRICKS_NUM_GPUS,
            "--aws_max_retries",
            "0",
        ),
    ),
    "nf:aws:phase3-wgs-fast:execute": _phase3_fast_aws_execute_task(
        _py("verify:phase3-fast-aws-execute"),
        _nextflow(
            "-profile",
            "awsbatch_gpu",
            "-params-file",
            AWS_USE2_NEXTFLOW_PARAMS,
            "--workflow",
            "phase3_wgs_fast",
            "--phase3_fast_replication_mode",
            "apply",
            "--phase3_fast_small_variant_mode",
            "execute",
            "--phase3_fast_parabricks_num_gpus",
            PHASE3_FAST_PARABRICKS_NUM_GPUS,
            "--aws_max_retries",
            "0",
            append_args=True,
        )
    ),
    "nf:aws:phase3-wgs:monolith:full": _legacy_phase3_aws_full_task(
        _nextflow(
            "-profile",
            "awsbatch_ondemand",
            "-params-file",
            "infra/aws/nextflow.aws.json",
            "--workflow",
            "phase3_wgs_monolith",
            "--phase3_reads",
            "full",
            "--phase3_source_mode",
            "aws_sra",
            "--phase3_fetch_concurrency",
            "8",
            "--phase3_s3_range_concurrency",
            "8",
            "--phase3_sra_run_concurrency",
            "1",
            "--phase3_cache_upload_workers",
            "4",
            "--phase3_alignment_cache_workers",
            "2",
            "--phase3_fastq_stats_mode",
            "metadata",
            "--phase3_wgs_cpus",
            "16",
            "--phase3_wgs_memory",
            "28 GB",
            "--phase3_include_wes",
            "false",
            "--phase3_prereq_mode",
            "minimal",
        )
    ),
}


def run_task(name: str, extra_args: Sequence[str] = ()) -> None:
    task = TASKS[name]
    passthrough = tuple(arg for arg in extra_args if arg != "--")
    if passthrough and not task.accepts_args:
        raise SystemExit(f"{name} does not accept extra arguments: {' '.join(passthrough)}")
    if passthrough and task.allowed_extra_args is not None:
        _validate_extra_args(name, passthrough, task.allowed_extra_args)
    if task.required_env:
        missing = [
            f"{key}={expected_value}"
            for key, expected_value in sorted(task.required_env.items())
            if os.environ.get(key) != expected_value
        ]
        if missing:
            suffix = f"\n{task.description}" if task.description else ""
            raise SystemExit(f"{name} requires {' '.join(missing)} to run.{suffix}")
    for step in task.steps:
        env = os.environ.copy()
        if step.env:
            env.update(step.env)
        argv = step.argv + (passthrough if step.append_args else ())
        if len(argv) >= 3 and argv[0] == "nextflow" and argv[1] == "-log":
            log_path = Path(argv[2])
            if not log_path.is_absolute():
                log_path = step.cwd / log_path
            log_path.parent.mkdir(parents=True, exist_ok=True)
        print("+ " + " ".join(argv), flush=True)
        subprocess.run(argv, cwd=step.cwd, env=env, check=True)


def _validate_extra_args(name: str, args: Sequence[str], allowed: frozenset[str]) -> None:
    seen: set[str] = set()
    index = 0
    while index < len(args):
        flag = args[index]
        if not flag.startswith("--"):
            raise SystemExit(f"{name} only accepts --flag value extra arguments; found {flag}")
        if flag not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise SystemExit(f"{name} does not accept extra argument {flag}. Allowed extra arguments: {allowed_text}")
        if flag in seen:
            raise SystemExit(f"{name} received duplicate extra argument {flag}")
        if index + 1 >= len(args) or args[index + 1].startswith("--"):
            raise SystemExit(f"{name} requires a value after extra argument {flag}")
        seen.add(flag)
        index += 2
