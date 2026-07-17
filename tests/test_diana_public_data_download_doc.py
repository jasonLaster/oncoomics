from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/operations/diana-public-data-download.md"
RUN_ID = "diana-wgs-hrd-20260716T033101Z"


class DianaPublicDataDownloadDocTests(unittest.TestCase):
    def test_rosalind_freeze_examples_use_canonical_packet_output(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertNotIn(
            ".codex-tmp/hrd-reports/deterministic-full/rosalind",
            text,
        )
        self.assertIn(
            'ROSALIND_PACKET="results/rosalind_hrd/diana_wgs/$RUN_ID"',
            text,
        )
        self.assertEqual(text.count('--packet-dir "$ROSALIND_PACKET"'), 2)
        self.assertIn(
            "$RUN_ROOT/terminal.rosalind_diana_wgs.private.json",
            text,
        )

    def test_rosalind_publication_examples_reuse_terminal_receipt_names(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertEqual(
            text.count(
                '--private-publication-receipt '
                '"$RUN_ROOT/terminal.rosalind_diana_wgs.private.json"'
            ),
            2,
        )
        self.assertEqual(
            text.count(
                '--destination-prefix "s3://diana-omics-results-172630973301-us-east-1/'
                'runs/diana-hrd-public/subject01/$RUN_ID/rosalind/"'
            ),
            2,
        )
        self.assertEqual(
            sorted(
                set(
                    re.findall(
                        r'\$RUN_ROOT/terminal\.rosalind_diana_wgs\.public(?:\.dry)?\.json',
                        text,
                    )
                )
            ),
            [
                "$RUN_ROOT/terminal.rosalind_diana_wgs.public.dry.json",
                "$RUN_ROOT/terminal.rosalind_diana_wgs.public.json",
            ],
        )

    def test_pinned_run_id_is_documented_once_for_manual_rosalind_freeze(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertIn(f"RUN_ID={RUN_ID}", text)
        self.assertIn(
            'ROSALIND_PACKET="results/rosalind_hrd/diana_wgs/$RUN_ID"',
            text,
        )

    def test_reviewed_publication_uses_run_scoped_ai_review_receipts(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertNotIn(
            ".codex-tmp/hrd-reports/ai-review/publication-receipts/",
            text,
        )
        receipt_root = (
            f".codex-tmp/hrd-reports/ai-review/{RUN_ID}/publication-receipts/"
        )
        self.assertIn(f"{receipt_root}terminal.ai-reviewer-a.private.json", text)
        self.assertIn(f"{receipt_root}terminal.ai-reviewer-b.private.json", text)
        self.assertIn(
            f"{receipt_root}terminal.comparative-synthesis.private.json",
            text,
        )

    def test_reviewed_publication_delegates_public_index_to_final_runbook(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        final_section = text.split("## Render the AI review and synthesis handoff", 1)[1]

        self.assertIn("scripts/render_reviewed_publication_runbook.py", final_section)
        self.assertIn(
            "then rebuilds and publishes `public-index/objects.json`",
            final_section,
        )
        self.assertNotIn("scripts/build_public_results_index.py", final_section)
        self.assertNotIn("scripts/publish_public_results_index.py", final_section)

    def test_terminal_packet_docs_start_with_checked_in_freeze_commands(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        for script in (
            "scripts/capture_batch_provenance.py",
            "scripts/freeze_stage_provenance.py",
            "scripts/freeze_final_artifacts.py",
            "scripts/materialize_frozen_artifacts.py",
            "scripts/submit_materializer_v4.py",
            "scripts/render_materializer_capture_command.py",
            "scripts/download_materializer_staged_validation.py",
            "aws/submit_route.py",
            "scripts/capture_route_terminal.py",
            "scripts/stage_deterministic_wgs_report.py",
            "scripts/generate_blocked_hrd_crosscheck_reports.py",
        ):
            self.assertIn(script, text)
        self.assertIn(
            '--output "$RUN_ROOT/terminal.execution.succeeded.json"',
            text,
        )
        self.assertIn('--output "$RUN_ROOT/terminal.stage-freeze.json"', text)
        self.assertIn('--output "$RUN_ROOT/terminal.final-freeze.json"', text)
        self.assertLess(
            text.index("python3 scripts/capture_batch_provenance.py"),
            text.index("python3 scripts/materialize_frozen_artifacts.py"),
        )
        self.assertLess(
            text.index("python3 scripts/materialize_frozen_artifacts.py"),
            text.index("python3 scripts/submit_materializer_v4.py"),
        )
        self.assertLess(
            text.index("python3 scripts/download_materializer_staged_validation.py"),
            text.index("python3 scripts/stage_deterministic_wgs_report.py"),
        )
        self.assertLess(
            text.index("python3 scripts/publish_input_contract.py"),
            text.index("python3 aws/submit_route.py"),
        )
        self.assertLess(
            text.index("python3 scripts/capture_route_terminal.py"),
            text.index("python3 scripts/download_exact_report_tree.py"),
        )
        self.assertLess(
            text.index("python3 scripts/stage_hrd_crosscheck_report.py"),
            text.index("python3 scripts/generate_blocked_hrd_crosscheck_reports.py"),
        )
        self.assertLess(
            text.index("python3 scripts/generate_blocked_hrd_crosscheck_reports.py"),
            text.index("python3 scripts/render_source_report_freeze_runbook.py"),
        )


if __name__ == "__main__":
    unittest.main()
