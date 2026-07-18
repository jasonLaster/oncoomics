from __future__ import annotations

import importlib.util
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                f"/repo/.codex-tmp/hrd-reports/deterministic-full/terminal.{method_id}.private.json",
                text,
            )
            previous = index

    def test_renderer_hands_exact_receipts_to_promoted_ai_renderer(self) -> None:
        text = MODULE.render(Path("/repo"), "rerun")

        self.assertIn("/repo/scripts/render_ai_synthesis_runbook.py", text)
        self.assertIn(
            "AI_REVIEW_RUNBOOK=/repo/.codex-tmp/hrd-reports/ai-review/rerun.post-reports-runbook.$(date -u +%Y%m%dT%H%M%SZ).md",
            text,
        )
        self.assertIn('--output "$AI_REVIEW_RUNBOOK" --root /repo', text)
        self.assertIn("--receipt-stem rerun", text)
        self.assertNotIn("rerun.post-reports-runbook.md\n", text)
        self.assertEqual(text.count("--private-publication-receipt "), 7)
        previous = -1
        for method_id in MODULE.REQUIRED_METHOD_IDS:
            receipt = MODULE.receipt_path(Path("/repo"), "rerun", method_id)
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
            Path("/repo"),
            output,
            [Path("/receipts/a.json"), Path("/receipts/b.json")],
            "rerun",
        )

        self.assertEqual(
            command,
            [
                "python3",
                Path("/repo/scripts/render_ai_synthesis_runbook.py"),
                "--output",
                output,
                "--root",
                Path("/repo"),
                "--receipt-stem",
                "rerun",
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
            "/repo/results/rosalind_hrd/diana_wgs/diana-wgs-hrd-20260716T033101Z",
        )

    def test_renderer_accepts_phase3_fast_packet_overrides(self) -> None:
        paths = MODULE.source_packet_dirs(
            Path("/repo"),
            sigprofiler_report_dir=Path("/fast/sigprofiler"),
            sequenza_report_dir=Path("/fast/sequenza"),
            deterministic_report_dir=Path("/fast/deterministic_report"),
            rosalind_report_dir=Path("/fast/rosalind_hrd/diana_wgs"),
            blocked_crosscheck_root=Path("/fast/blocked_crosschecks"),
        )
        text = MODULE.render(
            Path("/repo"),
            "terminal",
            sigprofiler_report_dir=Path("/fast/sigprofiler"),
            sequenza_report_dir=Path("/fast/sequenza"),
            deterministic_report_dir=Path("/fast/deterministic_report"),
            rosalind_report_dir=Path("/fast/rosalind_hrd/diana_wgs"),
            blocked_crosscheck_root=Path("/fast/blocked_crosschecks"),
        )

        self.assertEqual(tuple(paths), MODULE.REQUIRED_METHOD_IDS)
        for packet_dir in paths.values():
            self.assertIn(f"--packet-dir {packet_dir}", text)
        self.assertIn("/fast/blocked_crosschecks/facets_scarhrd_blocked", text)

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
            blocked_method_ids = {method["method_id"] for method in BLOCKED_GENERATOR.METHODS}
            source_paths = {method_id: path for method_id, path in paths.items() if method_id not in blocked_method_ids}
            write_packet_dirs(source_paths)

            MODULE.validate_packet_dirs(paths)
            text = MODULE.render(root, "terminal")
            for method in BLOCKED_GENERATOR.METHODS:
                self.assertIn(
                    f"/blocked-crosschecks/{method['directory']} --method-id {method['method_id']}",
                    text,
                )
            self.assertNotIn("/blocked-crosschecks/facets-scarhrd ", text)
            self.assertNotIn("/blocked-crosschecks/oncoanalyser-chord ", text)
            self.assertNotIn("/blocked-crosschecks/hrdetect ", text)

    def test_required_existing_points_at_checked_in_scripts(self) -> None:
        prerequisites = {path.as_posix() for path in MODULE.required_existing(Path("/repo"))}

        self.assertEqual(
            {
                "/repo/scripts/hrd_report_inventory.py",
                "/repo/scripts/ai_model_catalog.py",
                "/repo/scripts/forbidden_text.py",
                "/repo/scripts/publish_private_report.py",
                "/repo/scripts/render_ai_synthesis_runbook.py",
                "/repo/scripts/prepare_ai_review_run.py",
                "/repo/scripts/build_ai_review_bundle.py",
                "/repo/scripts/stage_ai_review_inputs.py",
                "/repo/scripts/validate_ai_review.py",
                "/repo/scripts/finalize_ai_review.py",
                "/repo/scripts/generate_comparative_hrd_synthesis.py",
                "/repo/scripts/render_reviewed_publication_runbook.py",
                "/repo/scripts/runbook_io.py",
                "/repo/scripts/publish_reviewed_public_report.py",
                "/repo/scripts/build_public_results_index.py",
                "/repo/scripts/publish_public_results_index.py",
                "/repo/scripts/write_ai_model_catalog_receipt.py",
            },
            prerequisites,
        )

    def test_required_absent_includes_source_private_receipts(self) -> None:
        outputs = {path.as_posix() for path in MODULE.required_absent(Path("/repo"), "unit")}

        for path in (
            *(f"/repo/.codex-tmp/hrd-reports/deterministic-full/unit.{method_id}.private.json" for method_id in MODULE.REQUIRED_METHOD_IDS),
            f"/repo/.codex-tmp/hrd-reports/ai-review/model-catalog-receipts/{MODULE.RUN_ID}/model-catalog-receipt.20260717T115311Z.json",
            f"/repo/.codex-tmp/hrd-reports/ai-review/{MODULE.RUN_ID}",
            "/repo/.codex-tmp/public-index/public-index.unit.dry.json",
        ):
            self.assertIn(path, outputs)

    def test_main_rejects_preexisting_source_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in MODULE.required_existing(root):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            write_packet_dirs(MODULE.source_packet_dirs(root))

            stale = MODULE.receipt_path(
                root,
                "terminal",
                "sigprofiler_sbs3",
            )
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.symlink_to(root / "missing")
            output = root / "source-freeze.md"

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "render_source_report_freeze_runbook.py",
                        "--output",
                        str(output),
                        "--root",
                        str(root),
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

            self.assertEqual(output.read_text(), "one\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_once(output, "two\n")


if __name__ == "__main__":
    unittest.main()
