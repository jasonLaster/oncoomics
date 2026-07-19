from __future__ import annotations

import importlib.util
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import runbook_io as RUNBOOK_IO  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "render_post_success_runbook", SCRIPT_DIR / "render_post_success_runbook.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

TERMINAL_JOB_ID = "12345678-1234-1234-1234-123456789abc"


def render() -> str:
    return MODULE.render(Path("/repo"), TERMINAL_JOB_ID)


class RenderPostSuccessRunbookTests(unittest.TestCase):
    def test_renderer_uses_checked_in_terminal_handoff_scripts(self) -> None:
        text = render()

        for script in (
            "/repo/scripts/capture_batch_provenance.py",
            "/repo/scripts/freeze_stage_provenance.py",
            "/repo/scripts/freeze_final_artifacts.py",
            "/repo/scripts/materialize_frozen_artifacts.py",
            "/repo/scripts/submit_materializer_v4.py",
            "/repo/scripts/render_materializer_capture_command.py",
            "/repo/scripts/download_materializer_staged_validation.py",
            "/repo/scripts/finalize_input_contract.py",
            "/repo/scripts/check_contract.py",
            "/repo/scripts/publish_input_contract.py",
            "/repo/scripts/stage_deterministic_wgs_report.py",
            "/repo/aws/submit_route.py",
            "/repo/scripts/capture_route_terminal.py",
            "/repo/scripts/download_exact_report_tree.py",
            "/repo/scripts/stage_hrd_crosscheck_report.py",
            "/repo/scripts/generate_blocked_hrd_crosscheck_reports.py",
            "/repo/scripts/render_source_report_freeze_runbook.py",
        ):
            self.assertIn(script, text)

        for stale in MODULE.STALE_TOKENS:
            self.assertNotIn(stale, text)

    def test_renderer_keeps_fail_closed_guards_and_report_builders(self) -> None:
        text = render()

        self.assertIn("--expected-status SUCCEEDED", text)
        self.assertIn(f"--job-id {TERMINAL_JOB_ID}", text)
        self.assertNotIn("--job-id 0c1e11bc-5fab-4dc0-b072-69d8e9759f52", text)
        self.assertNotIn("--job-id 6f827d44-d19b-4a6c-9126-d65189aa66cf", text)
        self.assertIn(
            "s3://diana-omics-work-172630973301-us-east-1/runs/diana-hrd/"
            "diana-wgs-hrd-20260716T033101Z/private-results/final/artifacts/",
            text,
        )
        self.assertIn(
            "s3://diana-omics-private-results-172630973301-us-east-1/runs/"
            "subject01/diana-wgs-hrd-20260716T033101Z/deterministic/final/",
            text,
        )
        self.assertNotIn(
            "s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/"
            "diana-wgs-hrd-20260716T033101Z/artifacts/",
            text,
        )
        self.assertIn("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES", text)
        self.assertIn("HRD_CROSSCHECK_LICENSE_REVIEWED=YES", text)
        self.assertIn("terminal.materializer.request.dry.json", text)
        self.assertIn("terminal.materializer.capture-command.sh", text)
        self.assertIn("--crosscheck-materialization-capture", text)
        self.assertIn("--crosscheck-materialization-anchor", text)
        self.assertIn("--input-contract", text)
        self.assertIn("--staged-input-validation-download-receipt", text)
        self.assertIn(
            "Wait for the submitted materializer job in "
            "`terminal.materializer.response.json` to reach `SUCCEEDED`",
            text,
        )
        self.assertIn(
            "Wait for this route's submitted Batch job to reach `SUCCEEDED`",
            text,
        )
        self.assertIn(".codex-tmp/hrd-crosschecks/input-contract.pending.json", text)
        self.assertIn(
            "--early-look-root "
            "/repo/results/diana_wgs_hrd/early-look-intersected-20260716T150517Z/"
            "artifacts",
            text,
        )
        self.assertNotIn(
            "--early-look-root /repo/.codex-tmp/hrd-reports/deterministic-early-look",
            text,
        )
        self.assertIn("--expected-crosscheck-materializer-sha256", text)
        self.assertIn("ROSALIND_HRD_SAMPLE_SET=diana_wgs", text)
        self.assertIn(
            'ROSALIND_HRD_FORBIDDEN_TOKENS_JSON="$(cat '
            "/repo/.codex-tmp/hrd-reports/deterministic-full/materialized-final/"
            "phase3_wgs_fast/forbidden_tokens/workspace/manifests/"
            'phase3_wgs_fast/forbidden_tokens.json)"',
            text,
        )
        self.assertIn(
            "--forbidden-tokens-file "
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "materialized-final/phase3_wgs_fast/forbidden_tokens/workspace/"
            "manifests/phase3_wgs_fast/forbidden_tokens.json",
            text[
                text.index("stage_deterministic_wgs_report.py") : text.index(
                    "build:rosalind-hrd-packet"
                )
            ],
        )
        self.assertNotIn("ROSALIND_HRD_FORBIDDEN_TOKENS_JSON=[", text)
        self.assertIn("build:rosalind-hrd-packet", text)
        self.assertNotIn(f"{MODULE.REGION} {MODULE.REGION}", text)
        self.assertNotIn(
            f"{MODULE.PRIVATE_KMS_KEY_ARN} {MODULE.PRIVATE_KMS_KEY_ARN}",
            text,
        )

        materializer_submit = text.index("terminal.materializer.request.json")
        materializer_wait = text.index("Wait for the submitted materializer job")
        materializer_waiter = text.index(
            "MATERIALIZER_JOB_ID=$(jq -er .response.jobId",
            materializer_wait,
        )
        materializer_capture = text.index("render_materializer_capture_command.py")
        self.assertLess(materializer_submit, materializer_wait)
        self.assertLess(materializer_wait, materializer_waiter)
        self.assertLess(materializer_waiter, materializer_capture)
        self.assertIn(
            'aws batch describe-jobs --jobs "$MATERIALIZER_JOB_ID" '
            "--region us-east-1 --output json",
            text,
        )
        self.assertIn(
            "SUBMITTED|PENDING|RUNNABLE|STARTING|RUNNING) sleep 30 ;;",
            text,
        )

    def test_routes_render_in_canonical_executable_order(self) -> None:
        text = render()

        previous = -1
        for route in MODULE.EXECUTABLE_CROSSCHECK_METHOD_IDS:
            index = text.find(f"--route {route}", previous + 1)
            self.assertGreater(index, previous)
            previous = index

        self.assertIn(
            "SEQUENZA_SCARHRD_SUBMISSION_ID=$(date -u +%Y%m%dT%H%M%SZ)-"
            "seq$(python3 -c",
            text,
        )
        self.assertIn(
            "SIGPROFILER_SBS3_SUBMISSION_ID=$(date -u +%Y%m%dT%H%M%SZ)-"
            "sig$(python3 -c",
            text,
        )
        self.assertNotIn("sequenza01", text)
        self.assertNotIn("sigprof01", text)
        self.assertNotIn("'$CONTRACT_URI'", text)

        for route in MODULE.EXECUTABLE_CROSSCHECK_METHOD_IDS:
            dry = text.index(f"terminal.{route}.request.dry.json")
            review = text.index(
                f"Review `/repo/.codex-tmp/hrd-reports/deterministic-full/"
                f"terminal.{route}.request.dry.json`",
                dry,
            )
            submit = text.index(
                f"terminal.{route}.request.json --dry-run-receipt"
            )
            wait = text.index(
                "Wait for this route's submitted Batch job to reach `SUCCEEDED`",
                submit,
            )
            waiter = text.index(
                f"{MODULE.route_var(route, 'JOB_ID')}=$(jq -er .job_id",
                wait,
            )
            capture = text.index(f"capture_route_terminal.py --route {route}", wait)
            self.assertLess(dry, review)
            self.assertLess(review, submit)
            self.assertLess(submit, wait)
            self.assertLess(wait, waiter)
            self.assertLess(waiter, capture)

    def test_route_submit_command_has_exact_response_output_argv(self) -> None:
        response = Path("/run/terminal.sequenza_scarhrd.response.json")
        dry_receipt = Path("/run/terminal.sequenza_scarhrd.request.dry.json")

        dry_run = MODULE.submit_route_command(
            Path("/repo/aws"),
            Path("/run"),
            "sequenza_scarhrd",
        )
        apply = MODULE.submit_route_command(
            Path("/repo/aws"),
            Path("/run"),
            "sequenza_scarhrd",
            dry_run_receipt=dry_receipt,
            response_output=response,
        )

        self.assertNotIn("--response-output", dry_run)
        self.assertEqual(dry_run.count("--region"), 1)
        self.assertEqual(dry_run[dry_run.index("--region") + 1], MODULE.REGION)
        self.assertEqual(dry_run[-1], MODULE.REGION)
        self.assertEqual(
            apply[apply.index("--dry-run-receipt") + 1],
            dry_receipt,
        )
        self.assertEqual(apply.count("--response-output"), 1)
        self.assertEqual(apply.count("--region"), 1)
        self.assertEqual(apply[apply.index("--response-output") + 1], response)
        self.assertIn("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES", apply)
        self.assertIn("HRD_CROSSCHECK_LICENSE_REVIEWED=YES", apply)
        self.assertEqual(apply[-1], "--submit")

        with self.assertRaisesRegex(ValueError, "requires a dry-run receipt"):
            MODULE.submit_route_command(
                Path("/repo/aws"),
                Path("/run"),
                "sequenza_scarhrd",
                response_output=response,
            )
        with self.assertRaisesRegex(ValueError, "only valid with route submit"):
            MODULE.submit_route_command(
                Path("/repo/aws"),
                Path("/run"),
                "sequenza_scarhrd",
                dry_run_receipt=dry_receipt,
            )

    def test_materializer_submit_command_is_bound_to_dry_request(self) -> None:
        response = Path("/run/terminal.materializer.response.json")
        dry_receipt = Path("/run/terminal.materializer.request.dry.json")

        dry_run = MODULE.materializer_command(
            Path("/repo/scripts"),
            Path("/run"),
            request_output=Path("/run/terminal.materializer.request.dry.json"),
        )
        apply = MODULE.materializer_command(
            Path("/repo/scripts"),
            Path("/run"),
            request_output=Path("/run/terminal.materializer.request.json"),
            dry_run_receipt=dry_receipt,
            response_output=response,
        )

        self.assertNotIn("--response-output", dry_run)
        self.assertEqual(
            apply[apply.index("--dry-run-receipt") + 1],
            dry_receipt,
        )
        self.assertEqual(apply[apply.index("--response-output") + 1], response)
        self.assertIn("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES", apply)
        self.assertNotIn("HRD_CROSSCHECK_LICENSE_REVIEWED=YES", apply)
        self.assertEqual(apply[-1], "--submit")

        with self.assertRaisesRegex(ValueError, "requires a dry-run receipt"):
            MODULE.materializer_command(
                Path("/repo/scripts"),
                Path("/run"),
                request_output=Path("/run/terminal.materializer.request.json"),
                response_output=response,
            )
        with self.assertRaisesRegex(ValueError, "only valid with materializer submit"):
            MODULE.materializer_command(
                Path("/repo/scripts"),
                Path("/run"),
                request_output=Path("/run/terminal.materializer.request.dry.json"),
                dry_run_receipt=dry_receipt,
            )

    def test_input_contract_apply_is_bound_to_dry_run_receipt(self) -> None:
        text = render()

        apply = text[text.index("terminal.input-contract.publication.json") :]

        self.assertIn(
            "--dry-run-receipt "
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.input-contract.publication.dry.json",
            apply,
        )
        self.assertLess(
            text.index("terminal.input-contract.publication.dry.json"),
            apply.index("--dry-run-receipt") + text.index(apply),
        )

    def test_final_freeze_apply_is_bound_to_dry_run_receipt(self) -> None:
        text = render()

        apply = text[text.index("terminal.final-freeze.json") :]

        self.assertIn(
            "--dry-run-receipt "
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.final-freeze.dry.json",
            apply,
        )
        self.assertLess(
            text.index("terminal.final-freeze.dry.json"),
            apply.index("--dry-run-receipt") + text.index(apply),
        )

    def test_stage_freeze_apply_is_bound_to_dry_run_receipt(self) -> None:
        text = render()

        apply = text[text.index("terminal.stage-freeze.json") :]

        self.assertIn(
            "--dry-run-receipt "
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.stage-freeze.dry.json",
            apply,
        )
        self.assertLess(
            text.index("terminal.stage-freeze.dry.json"),
            apply.index("--dry-run-receipt") + text.index(apply),
        )

    def test_render_source_handoff_follows_all_packet_staging(self) -> None:
        text = render()

        self.assertLess(
            text.index("stage_deterministic_wgs_report.py"),
            text.index("build:rosalind-hrd-packet"),
        )
        self.assertLess(
            text.index("stage_hrd_crosscheck_report.py"),
            text.index("generate_blocked_hrd_crosscheck_reports.py"),
        )
        self.assertLess(
            text.index("generate_blocked_hrd_crosscheck_reports.py"),
            text.rindex("render_source_report_freeze_runbook.py"),
        )
        self.assertIn("--generated-at 2026-07-16T03:31:01+00:00", text)
        self.assertIn(
            "--forbidden-tokens-file "
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "materialized-final/phase3_wgs_fast/forbidden_tokens/workspace/"
            "manifests/phase3_wgs_fast/forbidden_tokens.json",
            text,
        )
        self.assertNotIn("validate_phase3_fast_report_packets.py", text)
        self.assertNotIn("terminal.report-packet-validation.json", text)
        self.assertIn(
            "SOURCE_FREEZE_RUNBOOK=/repo/.codex-tmp/hrd-reports/"
            "deterministic-full/source-freeze-runbook."
            "$(date -u +%Y%m%dT%H%M%SZ).md",
            text,
        )
        self.assertIn('--output "$SOURCE_FREEZE_RUNBOOK" --root /repo', text)
        self.assertNotIn("source-freeze-runbook.md\n", text)

    def test_blocked_reports_bind_canonical_upstream_report_manifests(self) -> None:
        text = render()
        command_start = text.index("generate_blocked_hrd_crosscheck_reports.py")
        command_end = text.index("## 7. Render", command_start)
        command = text[command_start:command_end]

        self.assertIn(
            "--run-id diana-wgs-hrd-20260716T033101Z",
            command,
        )
        self.assertEqual(command.count("--source-report-manifest"), 4)

        previous = -1
        for method_id, path in [
            (
                "deterministic_full_wgs",
                "/repo/.codex-tmp/hrd-reports/deterministic-full/report/"
                "report_manifest.json",
            ),
            (
                "rosalind_diana_wgs",
                "/repo/results/rosalind_hrd/diana_wgs/"
                "diana-wgs-hrd-20260716T033101Z/report_manifest.json",
            ),
            (
                "sequenza_scarhrd",
                "/repo/.codex-tmp/hrd-reports/crosschecks/sequenza_scarhrd/"
                "report_manifest.json",
            ),
            (
                "sigprofiler_sbs3",
                "/repo/.codex-tmp/hrd-reports/crosschecks/sigprofiler_sbs3/"
                "report_manifest.json",
            ),
        ]:
            index = command.find(
                f"--source-report-manifest {method_id}={path}",
                previous + 1,
            )
            self.assertGreater(index, previous)
            previous = index

        self.assertNotIn("facets_scarhrd_blocked=", command)
        self.assertNotIn("oncoanalyser_chord_blocked=", command)
        self.assertNotIn("hrdetect_blocked=", command)

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {
            path.as_posix() for path in MODULE.required_existing(Path("/repo"))
        }

        self.assertIn("/repo/aws/submit_route.py", prerequisites)
        self.assertIn("/repo/scripts/capture_materializer_terminal.py", prerequisites)
        self.assertIn("/repo/scripts/stage_hrd_crosscheck_report.py", prerequisites)
        self.assertIn(
            "/repo/scripts/render_source_report_freeze_runbook.py",
            prerequisites,
        )
        self.assertIn("/repo/scripts/publish_private_report.py", prerequisites)
        self.assertIn("/repo/scripts/ai_model_catalog.py", prerequisites)
        self.assertIn("/repo/scripts/forbidden_text.py", prerequisites)
        self.assertIn("/repo/scripts/prepare_ai_review_run.py", prerequisites)
        self.assertIn("/repo/scripts/build_ai_review_bundle.py", prerequisites)
        self.assertIn("/repo/scripts/render_reviewed_publication_runbook.py", prerequisites)
        self.assertIn("/repo/scripts/build_public_results_index.py", prerequisites)
        self.assertIn("/repo/scripts/publish_public_results_index.py", prerequisites)
        self.assertIn("/repo/src/diana_omics/__main__.py", prerequisites)
        self.assertIn("/repo/src/diana_omics/cli.py", prerequisites)
        self.assertIn("/repo/src/diana_omics/commands/registry.py", prerequisites)
        self.assertIn(
            "/repo/src/diana_omics/commands/hrd_context/"
            "build_rosalind_hrd_packet.py",
            prerequisites,
        )
        for stale in (
            "/repo/.codex-tmp/hrd-reports/stage_crosscheck_report.py",
            "/repo/.codex-tmp/hrd-crosschecks/aws/submit_route.py",
        ):
            self.assertNotIn(stale, prerequisites)

    def test_required_existing_includes_precomputed_local_inputs(self) -> None:
        prerequisites = {
            path.as_posix() for path in MODULE.required_existing(Path("/repo"))
        }

        for path in (
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "executed-worker-freeze-receipt.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "reference-freeze-receipt.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "materializer-registration-receipt.v4.json",
            "/repo/.codex-tmp/hrd-crosschecks/input-contract.pending.json",
            "/repo/results/diana_wgs_hrd/early-look-intersected-20260716T150517Z/"
            "artifacts/early_look_summary.json",
            "/repo/results/diana_wgs_hrd/early-look-intersected-20260716T150517Z/"
            "artifacts/variants/core_hrr_pass_variants.csv",
            "/repo/results/diana_wgs_hrd/early-look-intersected-20260716T150517Z/"
            "artifacts/coverage_cnv/coverage_cnv_bins.csv",
        ):
            self.assertIn(path, prerequisites)

    def test_required_absent_includes_fixed_create_only_outputs(self) -> None:
        outputs = {path.as_posix() for path in MODULE.required_absent(Path("/repo"))}

        for path in (
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.execution.succeeded.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.stage-freeze.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.materializer.capture-command.sh",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.materializer.receipt.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "input-contract.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.sequenza_scarhrd.request.dry.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.sigprofiler_sbs3.exact-report.json",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "materialized-final",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/report",
            "/repo/results/rosalind_hrd/diana_wgs/"
            f"{MODULE.RUN_ID}",
            "/repo/results/rosalind_hrd/"
            f"{MODULE.RUN_ID}/run_manifest.json",
            "/repo/results/rosalind_hrd/"
            f"{MODULE.RUN_ID}/packet_index.md",
            "/repo/results/rosalind_hrd/"
            f"{MODULE.RUN_ID}/cloud_materialization_plan.md",
            "/repo/.codex-tmp/hrd-reports/route-replays/"
            "sequenza_scarhrd",
            "/repo/.codex-tmp/hrd-reports/crosschecks/"
            "sigprofiler_sbs3",
            "/repo/.codex-tmp/hrd-reports/blocked-crosschecks/"
            "hrdetect_blocked",
            "/repo/.codex-tmp/hrd-reports/deterministic-full/"
            "terminal.deterministic_full_wgs.private.json",
            "/repo/.codex-tmp/hrd-reports/ai-review/model-catalog-receipts/"
            f"{MODULE.RUN_ID}/model-catalog-receipt.20260717T115311Z.json",
            "/repo/.codex-tmp/public-index/public-index.terminal.json",
        ):
            self.assertIn(path, outputs)

        self.assertNotIn(
            "/repo/.codex-tmp/hrd-reports/blocked-crosschecks",
            outputs,
        )

    def test_preexisting_outputs_include_broken_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = (
                root
                / ".codex-tmp/hrd-reports/deterministic-full/"
                "terminal.execution.succeeded.json"
            )
            stale.parent.mkdir(parents=True)
            stale.symlink_to(root / "missing")

            preexisting = RUNBOOK_IO.preexisting_create_only_paths(
                MODULE.required_absent(root)
            )

            self.assertEqual(preexisting, (stale,))

    def test_main_rejects_preexisting_create_only_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in MODULE.required_existing(root):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            stale = (
                root
                / ".codex-tmp/hrd-reports/deterministic-full/"
                "terminal.materializer.receipt.json"
            )
            stale.write_text("{}\n", encoding="utf-8")
            output = root / "post-success.md"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "render_post_success_runbook.py",
                        "--output",
                        str(output),
                        "--root",
                        str(root),
                        "--terminal-job-id",
                        TERMINAL_JOB_ID,
                    ],
                ),
                self.assertRaisesRegex(SystemExit, "create-only outputs"),
            ):
                MODULE.main()

            self.assertFalse(output.exists())

    def test_write_once_is_mode_0600_and_refuses_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"
            MODULE.write_once(output, "one\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "one\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_once(output, "two\n")


if __name__ == "__main__":
    unittest.main()
