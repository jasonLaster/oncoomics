from __future__ import annotations

import importlib.util
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "render_post_success_runbook", SCRIPT_DIR / "render_post_success_runbook.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RenderPostSuccessRunbookTests(unittest.TestCase):
    def test_renderer_uses_checked_in_terminal_handoff_scripts(self) -> None:
        text = MODULE.render(Path("/repo"))

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
        text = MODULE.render(Path("/repo"))

        self.assertIn("--expected-status SUCCEEDED", text)
        self.assertIn("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES", text)
        self.assertIn("HRD_CROSSCHECK_LICENSE_REVIEWED=YES", text)
        self.assertIn("terminal.materializer.request.dry.json", text)
        self.assertIn("terminal.materializer.capture-command.sh", text)
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
        self.assertIn("--expected-crosscheck-materializer-sha256", text)
        self.assertIn("ROSALIND_HRD_SAMPLE_SET=diana_wgs", text)
        self.assertIn("ROSALIND_HRD_FORBIDDEN_TOKENS_JSON=", text)
        self.assertIn("build:rosalind-hrd-packet", text)

        materializer_submit = text.index("terminal.materializer.request.json")
        materializer_wait = text.index("Wait for the submitted materializer job")
        materializer_capture = text.index("render_materializer_capture_command.py")
        self.assertLess(materializer_submit, materializer_wait)
        self.assertLess(materializer_wait, materializer_capture)

    def test_routes_render_in_canonical_executable_order(self) -> None:
        text = MODULE.render(Path("/repo"))

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
            submit = text.index(f"terminal.{route}.request.json --response-output")
            wait = text.index(
                "Wait for this route's submitted Batch job to reach `SUCCEEDED`",
                submit,
            )
            capture = text.index(f"capture_route_terminal.py --route {route}", wait)
            self.assertLess(submit, wait)
            self.assertLess(wait, capture)

    def test_route_submit_command_has_exact_response_output_argv(self) -> None:
        response = Path("/run/terminal.sequenza_scarhrd.response.json")

        dry_run = MODULE.submit_route_command(
            Path("/repo/aws"),
            Path("/run"),
            "sequenza_scarhrd",
        )
        apply = MODULE.submit_route_command(
            Path("/repo/aws"),
            Path("/run"),
            "sequenza_scarhrd",
            response_output=response,
        )

        self.assertNotIn("--response-output", dry_run)
        self.assertEqual(apply.count("--response-output"), 1)
        self.assertEqual(apply[apply.index("--response-output") + 1], response)
        self.assertIn("HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES", apply)
        self.assertIn("HRD_CROSSCHECK_LICENSE_REVIEWED=YES", apply)
        self.assertEqual(apply[-1], "--submit")

    def test_render_source_handoff_follows_all_packet_staging(self) -> None:
        text = MODULE.render(Path("/repo"))

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

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {
            path.as_posix() for path in MODULE.required_existing(Path("/repo"))
        }

        self.assertIn("/repo/aws/submit_route.py", prerequisites)
        self.assertIn("/repo/scripts/stage_hrd_crosscheck_report.py", prerequisites)
        self.assertIn(
            "/repo/scripts/render_source_report_freeze_runbook.py",
            prerequisites,
        )
        for stale in (
            "/repo/.codex-tmp/hrd-reports/stage_crosscheck_report.py",
            "/repo/.codex-tmp/hrd-crosschecks/aws/submit_route.py",
        ):
            self.assertNotIn(stale, prerequisites)

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
