#!/usr/bin/env python3
"""Render the first post-success Diana WGS HRD handoff runbook."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from hrd_report_inventory import (
    BLOCKED_CROSSCHECK_REPORT_DIRS,
    EXECUTABLE_CROSSCHECK_METHOD_IDS,
)
from publish_reviewed_public_report import (
    ACCOUNT_ID,
    PRIVATE_BUCKET,
    PRIVATE_KMS_KEY_ARN,
    REGION,
    RUN_ID,
    SUBJECT_ALIAS,
)
from render_ai_synthesis_runbook import FORBIDDEN_TOKENS
from render_source_report_freeze_runbook import (
    required_absent as source_required_absent,
    required_existing as source_required_existing,
)
from runbook_io import (
    Raw,
    bash_block,
    block,
    missing_required_files,
    preexisting_create_only_paths,
    shell_join,
    timestamped_runbook_assignment,
    unique_paths,
    write_once,
)


JOB_ID = "0c1e11bc-5fab-4dc0-b072-69d8e9759f52"
WORK_BUCKET = f"diana-omics-work-{ACCOUNT_ID}-{REGION}"
PRIVATE_RUN_ROOT = f"s3://{PRIVATE_BUCKET}/runs/{SUBJECT_ALIAS}/{RUN_ID}/"
DETERMINISTIC_PRIVATE_PREFIX = f"{PRIVATE_RUN_ROOT}deterministic/"
WORKER_URI = (
    f"s3://{WORK_BUCKET}/runs/diana-hrd/{RUN_ID}/"
    "inputs/diana_hrd_wgs_worker.py"
)
WORK_FINAL_ARTIFACT_PREFIX = (
    f"s3://{WORK_BUCKET}/runs/diana-hrd/{RUN_ID}/"
    "private-results/final/artifacts/"
)
DETERMINISTIC_FINAL_PREFIX = DETERMINISTIC_PRIVATE_PREFIX + "final/"
EARLY_LOOK_ARTIFACT_ROOT = Path(
    "results/diana_wgs_hrd/early-look-intersected-20260716T150517Z/artifacts"
)

ROUTE_SUBMISSION_PREFIX = {
    "sequenza_scarhrd": "seq",
    "sigprofiler_sbs3": "sig",
}
STALE_TOKENS = (
    ".codex-tmp/hrd-reports/deterministic-full/capture_batch_provenance.py",
    ".codex-tmp/hrd-reports/deterministic-full/freeze_final_artifacts.py",
    ".codex-tmp/hrd-reports/deterministic-full/generate_report.py",
    ".codex-tmp/hrd-reports/stage_crosscheck_report.py",
    ".codex-tmp/hrd-reports/publish_private_report.py",
    ".codex-tmp/hrd-reports/ai-review/render_ai_synthesis_runbook.py",
    ".codex-tmp/hrd-crosschecks/scripts/finalize_input_contract.py",
    ".codex-tmp/hrd-crosschecks/aws/submit_route.py",
    "--private-publication-upload-receipt",
    "--receipt-upload-output",
    "--expected-file",
    "execution.running.json",
)


def forbidden_flags() -> list[str]:
    return [
        token
        for value in FORBIDDEN_TOKENS
        for token in ("--forbidden-token", value)
    ]


def jq_assign(variable: str, field: str, path: Path) -> str:
    return f"{variable}=$(jq -er {shlex.quote(field)} {shlex.quote(str(path))})"


def sha_assign(variable: str, path: Path) -> str:
    return (
        f"{variable}=$(shasum -a 256 {shlex.quote(str(path))} "
        "| awk '{print $1}')"
    )


def submission_id_assign(variable: str, route: str) -> str:
    return (
        f"{variable}=$(date -u +%Y%m%dT%H%M%SZ)-"
        f"{ROUTE_SUBMISSION_PREFIX[route]}$(python3 -c "
        f"{shlex.quote('import secrets; print(secrets.token_hex(4))')})"
    )


def batch_wait_lines(
    job_id_variable: str,
    response: Path,
    job_id_field: str,
) -> list[str]:
    job = f'"${job_id_variable}"'
    describe = (
        f"aws batch describe-jobs --jobs {job} "
        f"--region {REGION} --output json"
    )
    job_display = f"${{{job_id_variable}}}"
    return [
        "set -euo pipefail",
        jq_assign(job_id_variable, job_id_field, response),
        "while true; do",
        f"  HRD_BATCH_STATUS=$({describe} | jq -er '.jobs[0].status')",
        '  case "$HRD_BATCH_STATUS" in',
        "    SUCCEEDED) break ;;",
        "    SUBMITTED|PENDING|RUNNABLE|STARTING|RUNNING) sleep 30 ;;",
        "    FAILED)",
        f"      {describe} >&2",
        "      exit 1",
        "      ;;",
        "    *)",
        f'      echo "Unexpected Batch status for {job_display}: $HRD_BATCH_STATUS" >&2',
        "      exit 1",
        "      ;;",
        "  esac",
        "done",
    ]


def route_var(route: str, suffix: str) -> str:
    return f"{route.upper()}_{suffix}"


def materializer_command(
    scripts: Path,
    deterministic: Path,
    *,
    request_output: Path,
    response_output: Path | None = None,
) -> list[str | Path]:
    command: list[str | Path] = [
        "python3",
        scripts / "submit_materializer_v4.py",
        "--run-id",
        RUN_ID,
        "--final-freeze-receipt",
        deterministic / "terminal.final-freeze.json",
        "--final-freeze-anchor",
        deterministic / "terminal.final-freeze.anchor.json",
        "--exact-materialization-receipt",
        deterministic / "terminal.materialize.json",
        "--reference-freeze-receipt",
        deterministic / "reference-freeze-receipt.json",
        "--reference-sha256-receipt",
        deterministic / "reference-sha256.json",
        "--materializer-script-anchor",
        deterministic / "materializer-script-freeze-anchor.json",
        "--registration-receipt",
        deterministic / "materializer-registration-receipt.v4.json",
        "--job-definition-payload",
        deterministic / "materializer-job-definition.v4.json",
        "--request-output",
        request_output,
        "--region",
        REGION,
    ]
    if response_output is not None:
        return [
            "env",
            "HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES",
            *command,
            "--response-output",
            response_output,
            "--submit",
        ]
    return command


def stage_deterministic_command(
    scripts: Path, deterministic: Path, early_look_root: Path
) -> list[str | Path]:
    return [
        "python3",
        scripts / "stage_deterministic_wgs_report.py",
        "--artifact-root",
        deterministic / "materialized-final",
        "--preflight-json",
        deterministic / "quarantine.preflight.json",
        "--gather-json",
        deterministic / "quarantine.gather.json",
        "--sha-audit",
        deterministic / "private-input-sha256.json",
        "--execution-json",
        deterministic / "terminal.execution.succeeded.json",
        "--executed-worker-freeze-receipt",
        deterministic / "executed-worker-freeze-receipt.json",
        "--executed-worker-freeze-receipt-upload",
        deterministic / "executed-worker-freeze-receipt-upload.json",
        "--final-freeze-receipt",
        deterministic / "terminal.final-freeze.json",
        "--final-freeze-anchor",
        deterministic / "terminal.final-freeze.anchor.json",
        "--exact-materialization-receipt",
        deterministic / "terminal.materialize.json",
        "--crosscheck-materialization-receipt",
        deterministic / "terminal.materializer.receipt.json",
        "--crosscheck-materialization-capture",
        deterministic / "terminal.materializer.capture.json",
        "--crosscheck-materialization-anchor",
        deterministic / "terminal.materializer.anchor.json",
        "--stage-provenance-receipt",
        deterministic / "terminal.stage-freeze.json",
        "--stage-provenance-anchor",
        deterministic / "terminal.stage-freeze.anchor.json",
        "--staged-input-validation-json",
        deterministic / "staged_input_validation.json",
        "--staged-input-validation-download-receipt",
        deterministic / "terminal.staged-input-validation.json",
        "--expected-kms-key-arn",
        PRIVATE_KMS_KEY_ARN,
        "--early-look-root",
        early_look_root,
        "--output-dir",
        deterministic / "report",
        *forbidden_flags(),
    ]


def rosalind_command(root: Path, deterministic: Path) -> list[str | Path]:
    return [
        "env",
        "ROSALIND_HRD_SAMPLE_SET=diana_wgs",
        f"ROSALIND_HRD_RUN_ID={RUN_ID}",
        f"ROSALIND_HRD_ARTIFACT_ROOT={deterministic / 'materialized-final'}",
        f"ROSALIND_HRD_DETERMINISTIC_REPORT_DIR={deterministic / 'report'}",
        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON="
        + json.dumps(list(FORBIDDEN_TOKENS), separators=(",", ":")),
        f"PYTHONPATH={root / 'src'}",
        "/usr/bin/python3",
        "-m",
        "diana_omics",
        "build:rosalind-hrd-packet",
    ]


def submit_route_command(
    aws_dir: Path,
    deterministic: Path,
    route: str,
    *,
    response_output: Path | None = None,
) -> list[str | Path]:
    submission = Raw(f'"${route_var(route, "SUBMISSION_ID")}"')
    command: list[str | Path] = [
        "python3",
        aws_dir / "submit_route.py",
        "--route",
        route,
        "--contract",
        deterministic / "input-contract.json",
        "--contract-uri",
        Raw('"$CONTRACT_URI"'),
        "--contract-version-id",
        Raw('"$CONTRACT_VERSION_ID"'),
        "--contract-publication-anchor",
        deterministic / "terminal.input-contract.publication.json",
        "--submission-id",
        submission,
        "--request-output",
        deterministic / f"terminal.{route}.request.dry.json",
        "--region",
        REGION,
    ]
    if response_output is not None:
        command = [
            "python3",
            aws_dir / "submit_route.py",
            "--route",
            route,
            "--contract",
            deterministic / "input-contract.json",
            "--contract-uri",
            Raw('"$CONTRACT_URI"'),
            "--contract-version-id",
            Raw('"$CONTRACT_VERSION_ID"'),
            "--contract-publication-anchor",
            deterministic / "terminal.input-contract.publication.json",
            "--submission-id",
            submission,
            "--request-output",
            deterministic / f"terminal.{route}.request.json",
            "--response-output",
            response_output,
            "--region",
            REGION,
            "--submit",
        ]
        return [
            "env",
            "HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES",
            "HRD_CROSSCHECK_LICENSE_REVIEWED=YES",
            *command,
        ]
    return command


def capture_route_command(
    scripts: Path,
    deterministic: Path,
    route: str,
) -> list[str | Path]:
    return [
        "python3",
        scripts / "capture_route_terminal.py",
        "--route",
        route,
        "--job-id",
        Raw(f'"${route_var(route, "JOB_ID")}"'),
        "--expected-contract-uri",
        Raw('"$CONTRACT_URI"'),
        "--expected-contract-version-id",
        Raw('"$CONTRACT_VERSION_ID"'),
        "--expected-contract-sha256",
        Raw('"$CONTRACT_SHA256"'),
        "--expected-output-uri",
        PRIVATE_RUN_ROOT,
        "--submission-id",
        Raw(f'"${route_var(route, "SUBMISSION_ID")}"'),
        "--expected-kms-key-arn",
        PRIVATE_KMS_KEY_ARN,
        "--capture-output",
        deterministic / f"terminal.{route}.capture.json",
        "--receipt-output",
        deterministic / f"terminal.{route}.publication.json",
        "--anchor-output",
        deterministic / f"terminal.{route}.publication.anchor.json",
        "--region",
        REGION,
    ]


def download_route_command(
    scripts: Path,
    deterministic: Path,
    route: str,
    report_root: Path,
) -> list[str | Path]:
    return [
        "python3",
        scripts / "download_exact_report_tree.py",
        "--publication-receipt",
        deterministic / f"terminal.{route}.publication.json",
        "--publication-anchor",
        deterministic / f"terminal.{route}.publication.anchor.json",
        "--kms-key-arn",
        PRIVATE_KMS_KEY_ARN,
        "--output-dir",
        report_root / "route-replays" / route,
        "--verification-output",
        deterministic / f"terminal.{route}.exact-report.json",
        "--region",
        REGION,
    ]


def stage_route_command(
    scripts: Path,
    deterministic: Path,
    route: str,
    report_root: Path,
) -> list[str | Path]:
    return [
        "python3",
        scripts / "stage_hrd_crosscheck_report.py",
        "--source-dir",
        report_root / "route-replays" / route,
        "--download-verification",
        deterministic / f"terminal.{route}.exact-report.json",
        "--route",
        route,
        "--output-dir",
        report_root / "crosschecks" / route,
    ]


def required_local_inputs(root: Path) -> tuple[Path, ...]:
    deterministic = root / ".codex-tmp/hrd-reports/deterministic-full"
    hrd_crosschecks = root / ".codex-tmp/hrd-crosschecks"
    early_look = root / EARLY_LOOK_ARTIFACT_ROOT
    return (
        deterministic / "executed-worker-freeze-receipt.json",
        deterministic / "executed-worker-freeze-receipt-upload.json",
        deterministic / "private-input-sha256.json",
        deterministic / "quarantine.preflight.json",
        deterministic / "quarantine.gather.json",
        deterministic / "reference-freeze-receipt.json",
        deterministic / "reference-sha256.json",
        deterministic / "materializer-script-freeze-anchor.json",
        deterministic / "materializer-registration-receipt.v4.json",
        deterministic / "materializer-job-definition.v4.json",
        hrd_crosschecks / "input-contract.pending.json",
        early_look / "early_look_summary.json",
        early_look / "variants/core_hrr_pass_variants.csv",
        early_look / "coverage_cnv/coverage_cnv_bins.csv",
    )


def required_existing(root: Path) -> tuple[Path, ...]:
    scripts = root / "scripts"
    return unique_paths(
        (
            root / "aws/submit_route.py",
            scripts / "capture_batch_provenance.py",
            scripts / "freeze_stage_provenance.py",
            scripts / "freeze_final_artifacts.py",
            scripts / "materialize_frozen_artifacts.py",
            scripts / "submit_materializer_v4.py",
            scripts / "render_materializer_capture_command.py",
            scripts / "capture_materializer_terminal.py",
            scripts / "download_materializer_staged_validation.py",
            scripts / "finalize_input_contract.py",
            scripts / "check_contract.py",
            scripts / "publish_input_contract.py",
            scripts / "stage_deterministic_wgs_report.py",
            scripts / "capture_route_terminal.py",
            scripts / "download_exact_report_tree.py",
            scripts / "stage_hrd_crosscheck_report.py",
            scripts / "generate_blocked_hrd_crosscheck_reports.py",
            scripts / "render_source_report_freeze_runbook.py",
            *source_required_existing(root),
            *required_local_inputs(root),
        )
    )


def required_absent(root: Path) -> tuple[Path, ...]:
    reports = root / ".codex-tmp/hrd-reports"
    deterministic = reports / "deterministic-full"
    rosalind = root / "results/rosalind_hrd/diana_wgs" / RUN_ID
    blocked = reports / "blocked-crosschecks"

    terminal_outputs = [
        "terminal.execution.succeeded.json",
        "terminal.stage-freeze.dry.json",
        "terminal.stage-freeze.dry.anchor.json",
        "terminal.stage-freeze.json",
        "terminal.stage-freeze.anchor.json",
        "terminal.final-freeze.dry.json",
        "terminal.final-freeze.dry.anchor.json",
        "terminal.final-freeze.json",
        "terminal.final-freeze.anchor.json",
        "terminal.materialize.json",
        "terminal.materializer.request.dry.json",
        "terminal.materializer.request.json",
        "terminal.materializer.response.json",
        "terminal.materializer.capture-command.sh",
        "terminal.materializer.capture.json",
        "terminal.materializer.anchor.json",
        "terminal.materializer.receipt.json",
        "staged_input_validation.json",
        "terminal.staged-input-validation.json",
        "input-contract.json",
        "input-contract.readiness.json",
        "terminal.input-contract.publication.dry.json",
        "terminal.input-contract.publication.json",
    ]

    route_outputs: list[Path] = []
    for route in EXECUTABLE_CROSSCHECK_METHOD_IDS:
        route_outputs.extend(
            [
                deterministic / f"terminal.{route}.request.dry.json",
                deterministic / f"terminal.{route}.request.json",
                deterministic / f"terminal.{route}.response.json",
                deterministic / f"terminal.{route}.capture.json",
                deterministic / f"terminal.{route}.publication.json",
                deterministic / f"terminal.{route}.publication.anchor.json",
                deterministic / f"terminal.{route}.exact-report.json",
                reports / "route-replays" / route,
                reports / "crosschecks" / route,
            ]
        )

    return (
        *(deterministic / name for name in terminal_outputs),
        deterministic / "materialized-final",
        deterministic / "report",
        rosalind,
        *route_outputs,
        *(
            blocked / directory
            for directory in BLOCKED_CROSSCHECK_REPORT_DIRS.values()
        ),
        *source_required_absent(root, "terminal"),
    )


def render(root: Path) -> str:
    scripts = root / "scripts"
    aws_dir = root / "aws"
    reports = root / ".codex-tmp/hrd-reports"
    deterministic = reports / "deterministic-full"
    early_look = root / EARLY_LOOK_ARTIFACT_ROOT
    pending_contract = root / ".codex-tmp/hrd-crosschecks/input-contract.pending.json"

    lines = [
        "# Post-success Diana WGS HRD handoff",
        "",
        f"- Run: `{RUN_ID}`",
        f"- Terminal Batch job: `{JOB_ID}`",
        "- Boundary: start only after that Batch job reports `SUCCEEDED`; this "
        "runbook freezes exact deterministic outputs, materializes cross-check "
        "inputs, stages deterministic/Rosalind/cross-check packets, then "
        "delegates the seven-source private-freeze and AI-review handoff to "
        "`scripts/render_source_report_freeze_runbook.py`.",
        "",
        "## 1. Capture and freeze terminal deterministic artifacts",
        "",
        block(
            [
                "python3",
                scripts / "capture_batch_provenance.py",
                "--job-id",
                JOB_ID,
                "--run-id",
                RUN_ID,
                "--worker-uri",
                WORKER_URI,
                "--executed-worker-freeze-receipt",
                deterministic / "executed-worker-freeze-receipt.json",
                "--executed-worker-freeze-receipt-upload",
                deterministic / "executed-worker-freeze-receipt-upload.json",
                "--output",
                deterministic / "terminal.execution.succeeded.json",
                "--expected-status",
                "SUCCEEDED",
                "--region",
                REGION,
            ]
        ),
        block(
            [
                "python3",
                scripts / "freeze_stage_provenance.py",
                "--job-id",
                JOB_ID,
                "--run-id",
                RUN_ID,
                "--execution-receipt",
                deterministic / "terminal.execution.succeeded.json",
                "--kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--output",
                deterministic / "terminal.stage-freeze.dry.json",
                "--anchor-output",
                deterministic / "terminal.stage-freeze.dry.anchor.json",
                "--region",
                REGION,
            ]
        ),
        block(
            [
                "python3",
                scripts / "freeze_stage_provenance.py",
                "--job-id",
                JOB_ID,
                "--run-id",
                RUN_ID,
                "--execution-receipt",
                deterministic / "terminal.execution.succeeded.json",
                "--kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--output",
                deterministic / "terminal.stage-freeze.json",
                "--anchor-output",
                deterministic / "terminal.stage-freeze.anchor.json",
                "--region",
                REGION,
                "--apply",
            ]
        ),
        block(
            [
                "python3",
                scripts / "freeze_final_artifacts.py",
                "--job-id",
                JOB_ID,
                "--run-id",
                RUN_ID,
                "--execution-receipt",
                deterministic / "terminal.execution.succeeded.json",
                "--source-prefix",
                WORK_FINAL_ARTIFACT_PREFIX,
                "--destination-prefix",
                DETERMINISTIC_FINAL_PREFIX,
                "--kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--output",
                deterministic / "terminal.final-freeze.dry.json",
                "--anchor-output",
                deterministic / "terminal.final-freeze.dry.anchor.json",
                "--region",
                REGION,
            ]
        ),
        block(
            [
                "python3",
                scripts / "freeze_final_artifacts.py",
                "--job-id",
                JOB_ID,
                "--run-id",
                RUN_ID,
                "--execution-receipt",
                deterministic / "terminal.execution.succeeded.json",
                "--source-prefix",
                WORK_FINAL_ARTIFACT_PREFIX,
                "--destination-prefix",
                DETERMINISTIC_FINAL_PREFIX,
                "--kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--output",
                deterministic / "terminal.final-freeze.json",
                "--anchor-output",
                deterministic / "terminal.final-freeze.anchor.json",
                "--region",
                REGION,
                "--apply",
            ]
        ),
        block(
            [
                "python3",
                scripts / "materialize_frozen_artifacts.py",
                "--freeze-receipt",
                deterministic / "terminal.final-freeze.json",
                "--output-dir",
                deterministic / "materialized-final",
                "--receipt-output",
                deterministic / "terminal.materialize.json",
                "--expected-kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--region",
                REGION,
            ]
        ),
        "## 2. Materialize alias-only cross-check inputs",
        "",
        block(
            materializer_command(
                scripts,
                deterministic,
                request_output=deterministic / "terminal.materializer.request.dry.json",
            )
        ),
        block(
            materializer_command(
                scripts,
                deterministic,
                request_output=deterministic / "terminal.materializer.request.json",
                response_output=deterministic / "terminal.materializer.response.json",
            )
        ),
        "Wait for the submitted materializer job in "
        "`terminal.materializer.response.json` to reach `SUCCEEDED`, then "
        "render and run the terminal capture command.",
        "",
        bash_block(
            batch_wait_lines(
                "MATERIALIZER_JOB_ID",
                deterministic / "terminal.materializer.response.json",
                ".response.jobId",
            )
        ),
        block(
            [
                "python3",
                scripts / "render_materializer_capture_command.py",
                "--request-receipt",
                deterministic / "terminal.materializer.request.json",
                "--response-receipt",
                deterministic / "terminal.materializer.response.json",
                "--output",
                deterministic / "terminal.materializer.capture-command.sh",
                "--expected-receipt-prefix",
                DETERMINISTIC_PRIVATE_PREFIX
                + "provenance/crosscheck-materialization-receipts/",
                "--expected-kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--capture-output",
                deterministic / "terminal.materializer.capture.json",
                "--anchor-output",
                deterministic / "terminal.materializer.anchor.json",
                "--receipt-output",
                deterministic / "terminal.materializer.receipt.json",
                "--region",
                REGION,
            ]
        ),
        block(["bash", deterministic / "terminal.materializer.capture-command.sh"]),
        block(
            [
                "python3",
                scripts / "download_materializer_staged_validation.py",
                "--materializer-receipt",
                deterministic / "terminal.materializer.receipt.json",
                "--output",
                deterministic / "staged_input_validation.json",
                "--verification-output",
                deterministic / "terminal.staged-input-validation.json",
                "--expected-kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--region",
                REGION,
            ]
        ),
        "## 3. Publish the cross-check input contract",
        "",
        bash_block(
            [
                jq_assign(
                    "HRD_CROSSCHECK_MATERIALIZER_SHA256",
                    ".source.sha256",
                    deterministic / "materializer-script-freeze-anchor.json",
                ),
                shell_join(
                    [
                        "python3",
                        scripts / "finalize_input_contract.py",
                        "--pending-contract",
                        pending_contract,
                        "--final-freeze-receipt",
                        deterministic / "terminal.final-freeze.json",
                        "--final-freeze-anchor",
                        deterministic / "terminal.final-freeze.anchor.json",
                        "--exact-materialization-receipt",
                        deterministic / "terminal.materialize.json",
                        "--crosscheck-materialization-receipt",
                        deterministic / "terminal.materializer.receipt.json",
                        "--crosscheck-materialization-anchor",
                        deterministic / "terminal.materializer.anchor.json",
                        "--expected-crosscheck-materializer-sha256",
                        Raw('"$HRD_CROSSCHECK_MATERIALIZER_SHA256"'),
                        "--output",
                        deterministic / "input-contract.json",
                    ]
                ),
            ]
        ),
        block(
            [
                "python3",
                scripts / "check_contract.py",
                "--contract",
                deterministic / "input-contract.json",
                "--json-out",
                deterministic / "input-contract.readiness.json",
            ]
        ),
        block(
            [
                "python3",
                scripts / "publish_input_contract.py",
                "--contract",
                deterministic / "input-contract.json",
                "--destination-prefix",
                DETERMINISTIC_PRIVATE_PREFIX + "contracts/",
                "--kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--anchor-output",
                deterministic / "terminal.input-contract.publication.dry.json",
                "--region",
                REGION,
            ]
        ),
        block(
            [
                "python3",
                scripts / "publish_input_contract.py",
                "--contract",
                deterministic / "input-contract.json",
                "--destination-prefix",
                DETERMINISTIC_PRIVATE_PREFIX + "contracts/",
                "--kms-key-arn",
                PRIVATE_KMS_KEY_ARN,
                "--anchor-output",
                deterministic / "terminal.input-contract.publication.json",
                "--region",
                REGION,
                "--apply",
            ]
        ),
        "## 4. Stage deterministic and Rosalind packets",
        "",
        block(stage_deterministic_command(scripts, deterministic, early_look)),
        block(rosalind_command(root, deterministic)),
        "## 5. Execute and stage supported cross-check routes",
        "",
        bash_block(
            [
                jq_assign(
                    "CONTRACT_URI",
                    ".receipt_uri",
                    deterministic / "terminal.input-contract.publication.json",
                ),
                jq_assign(
                    "CONTRACT_VERSION_ID",
                    ".receipt_version_id",
                    deterministic / "terminal.input-contract.publication.json",
                ),
                sha_assign("CONTRACT_SHA256", deterministic / "input-contract.json"),
            ]
        ),
    ]

    for route in EXECUTABLE_CROSSCHECK_METHOD_IDS:
        response = deterministic / f"terminal.{route}.response.json"
        submission_id = route_var(route, "SUBMISSION_ID")
        job_id = route_var(route, "JOB_ID")
        lines.extend(
            [
                f"### {route}",
                "",
                bash_block([submission_id_assign(submission_id, route)]),
                block(submit_route_command(aws_dir, deterministic, route)),
                block(
                    submit_route_command(
                        aws_dir,
                        deterministic,
                        route,
                        response_output=response,
                    )
                ),
                "Wait for this route's submitted Batch job to reach "
                "`SUCCEEDED`, then capture and stage its exact "
                "content-addressed report.",
                "",
                bash_block(
                    [
                        *batch_wait_lines(job_id, response, ".job_id"),
                        shell_join(capture_route_command(scripts, deterministic, route)),
                        shell_join(
                            download_route_command(
                                scripts, deterministic, route, reports
                            )
                        ),
                        shell_join(
                            stage_route_command(scripts, deterministic, route, reports)
                        ),
                    ]
                ),
            ]
        )

    lines.extend(
        [
            "## 6. Stage blocked cross-check packets",
            "",
            block(
                [
                    "python3",
                    scripts / "generate_blocked_hrd_crosscheck_reports.py",
                    "--output-dir",
                    reports / "blocked-crosschecks",
                ]
            ),
            "## 7. Render the seven-source private-freeze and AI-review handoff",
            "",
            bash_block(
                [
                    timestamped_runbook_assignment(
                        "SOURCE_FREEZE_RUNBOOK",
                        deterministic,
                        "source-freeze-runbook",
                    ),
                    shell_join(
                        [
                            "python3",
                            scripts / "render_source_report_freeze_runbook.py",
                            "--output",
                            Raw('"$SOURCE_FREEZE_RUNBOOK"'),
                            "--root",
                            root,
                        ]
                    ),
                ]
            ),
        ]
    )

    text = "\n".join(lines).rstrip() + "\n"
    leaked = [token for token in STALE_TOKENS if token in text]
    if leaked:
        raise AssertionError(f"post-success runbook contains stale tokens: {leaked}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", default=Path.cwd(), type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    missing = missing_required_files(required_existing(root))
    if missing:
        raise SystemExit(
            "Fail-closed: missing post-success runbook prerequisites: "
            + ", ".join(str(path) for path in missing)
        )
    preexisting = preexisting_create_only_paths(required_absent(root))
    if preexisting:
        raise SystemExit(
            "Fail-closed: post-success create-only outputs already exist: "
            + ", ".join(str(path) for path in preexisting)
        )
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {args.output}")

    write_once(args.output, render(root))
    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
