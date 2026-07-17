from __future__ import annotations

import importlib.util
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import generate_blocked_hrd_crosscheck_reports as BLOCKED_GENERATOR  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "render_source_report_freeze_runbook",
    SCRIPT_DIR / "render_source_report_freeze_runbook.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_packet_dirs(paths: dict[str, Path]) -> None:
    for method_id, path in paths.items():
        path.mkdir(parents=True)
        for relative in MODULE.METHOD_CONTRACTS[method_id]["files"]:
            (path / relative).write_text("packet file\n", encoding="utf-8")


class RenderSourceReportFreezeRunbookTests(unittest.TestCase):
    def test_renderer_freezes_seven_sources_in_canonical_order(self) -> None:
        text = MODULE.render(Path("/repo"), "terminal")

        self.assertEqual(text.count("/repo/scripts/publish_private_report.py"), 7)
        self.assertEqual(text.count("--packet-dir "), 7)
        self.assertEqual(text.count("--method-id "), 7)
        self.assertEqual(text.count("--receipt-output "), 7)
        previous = -1
        for method_id in MODULE.REQUIRED_METHOD_IDS:
            index = text.find(f"--method-id {method_id}", previous + 1)
            self.assertGreater(index, previous)
            self.assertIn(
                "/repo/.codex-tmp/hrd-reports/deterministic-full/"
                f"terminal.{method_id}.private.json",
                text,
            )
            previous = index

    def test_renderer_hands_exact_receipts_to_promoted_ai_renderer(self) -> None:
        text = MODULE.render(Path("/repo"), "terminal")

        self.assertIn("/repo/scripts/render_ai_synthesis_runbook.py", text)
        self.assertIn(
            "AI_REVIEW_RUNBOOK=/repo/.codex-tmp/hrd-reports/ai-review/"
            "terminal.post-reports-runbook.$(date -u +%Y%m%dT%H%M%SZ).md",
            text,
        )
        self.assertIn('--output "$AI_REVIEW_RUNBOOK"', text)
        self.assertNotIn("terminal.post-reports-runbook.md\n", text)
        self.assertEqual(text.count("--private-publication-receipt "), 7)
        previous = -1
        for method_id in MODULE.REQUIRED_METHOD_IDS:
            receipt = MODULE.receipt_path(Path("/repo"), "terminal", method_id)
            index = text.find(
                f"--private-publication-receipt {receipt}",
                previous + 1,
            )
            self.assertGreater(index, previous)
            previous = index
        for stale in MODULE.STALE_TOKENS:
            self.assertNotIn(stale, text)

    def test_ai_runbook_command_has_exact_output_argv(self) -> None:
        output = Path("/repo/.codex-tmp/hrd-reports/ai-review/runbook.md")
        command = MODULE.ai_runbook_command(
            Path("/repo/scripts"),
            output,
            [Path("/receipts/a.json"), Path("/receipts/b.json")],
        )

        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/render_ai_synthesis_runbook.py"),
                "--output",
                output,
                "--private-publication-receipt",
                Path("/receipts/a.json"),
                "--private-publication-receipt",
                Path("/receipts/b.json"),
            ],
        )

    def test_publish_command_has_exact_apply_argv(self) -> None:
        command = MODULE.publish_command(
            Path("/repo/scripts"),
            Path("/packets/deterministic"),
            "deterministic_full_wgs",
            Path("/receipts/deterministic.json"),
        )

        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/publish_private_report.py"),
                "--packet-dir",
                Path("/packets/deterministic"),
                "--method-id",
                "deterministic_full_wgs",
                "--receipt-output",
                Path("/receipts/deterministic.json"),
                "--region",
                MODULE.REGION,
                *MODULE.forbidden_flags(),
                "--apply",
            ],
        )

    def test_source_packet_dirs_match_required_methods(self) -> None:
        paths = MODULE.source_packet_dirs(Path("/repo"))

        self.assertEqual(tuple(paths), MODULE.REQUIRED_METHOD_IDS)
        self.assertEqual(
            paths["deterministic_full_wgs"].as_posix(),
            "/repo/.codex-tmp/hrd-reports/deterministic-full/report",
        )
        self.assertEqual(
            paths["rosalind_diana_wgs"].as_posix(),
            "/repo/results/rosalind_hrd/diana_wgs/"
            "diana-wgs-hrd-20260716T033101Z",
        )

    def test_validate_packet_dirs_rejects_missing_or_reordered_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)
            MODULE.validate_packet_dirs(paths)

            reordered = dict(reversed(list(paths.items())))
            with self.assertRaisesRegex(ValueError, "pinned seven-method order"):
                MODULE.validate_packet_dirs(reordered)

            shutil.rmtree(next(iter(paths.values())))
            with self.assertRaisesRegex(ValueError, "missing"):
                MODULE.validate_packet_dirs(paths)

    def test_validate_packet_dirs_rejects_non_exact_packet_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = MODULE.source_packet_dirs(root)
            write_packet_dirs(paths)

            (paths["deterministic_full_wgs"] / "notes.md").write_text(
                "stale scratch\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "inventory is not exact"):
                MODULE.validate_packet_dirs(paths)

    def test_current_blocked_generator_satisfies_renderer_packet_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blocked_root = root / ".codex-tmp/hrd-reports/blocked-crosschecks"
            BLOCKED_GENERATOR.generate(
                blocked_root,
                generated_at="2026-07-17T00:00:00+00:00",
            )

            paths = MODULE.source_packet_dirs(root)
            source_paths = {
                method_id: path
                for method_id, path in paths.items()
                if method_id not in MODULE.BLOCKED_CROSSCHECK_REPORT_DIRS
            }
            write_packet_dirs(source_paths)

            MODULE.validate_packet_dirs(paths)
            text = MODULE.render(root, "terminal")
            for method in BLOCKED_GENERATOR.METHODS:
                self.assertIn(
                    f"/blocked-crosschecks/{method['directory']} "
                    f"--method-id {method['method_id']}",
                    text,
                )
            self.assertNotIn("/blocked-crosschecks/facets-scarhrd ", text)
            self.assertNotIn("/blocked-crosschecks/oncoanalyser-chord ", text)
            self.assertNotIn("/blocked-crosschecks/hrdetect ", text)

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {
            path.as_posix() for path in MODULE.required_existing(Path("/repo"))
        }

        self.assertEqual(
            prerequisites,
            {
                "/repo/scripts/hrd_report_inventory.py",
                "/repo/scripts/publish_private_report.py",
                "/repo/scripts/render_ai_synthesis_runbook.py",
            },
        )

    def test_write_once_is_mode_0600_and_refuses_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "runbook.md"
            MODULE.write_once(output, "one\n")

            self.assertEqual(output.read_text(), "one\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_once(output, "two\n")


if __name__ == "__main__":
    unittest.main()
