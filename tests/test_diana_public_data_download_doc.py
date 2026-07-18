from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/operations/diana-public-data-download.md"
RUN_ID = "diana-wgs-hrd-20260716T033101Z"


class DianaPublicDataDownloadDocTests(unittest.TestCase):
    def test_public_browser_documents_static_results_and_live_raw_inbox(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertIn("data.diana-tnbc.com", text)
        self.assertIn("public-index/objects.json", text)
        self.assertIn(
            "s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/",
            text,
        )
        self.assertIn("anonymous list and read", text)
        self.assertIn("republishing `public-index/objects.json`", text)

    def test_terminal_handoff_delegates_to_post_success_renderer(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertIn(
            'POST_SUCCESS_RUNBOOK="$RUN_ROOT/post-success-runbook.$(date -u +%Y%m%dT%H%M%SZ).md"',
            text,
        )
        self.assertEqual(
            text.count("python3 scripts/render_post_success_runbook.py"),
            1,
        )
        self.assertIn('--output "$POST_SUCCESS_RUNBOOK"', text)

        for generated_command in (
            "python3 scripts/capture_batch_provenance.py",
            "python3 scripts/freeze_stage_provenance.py",
            "python3 scripts/freeze_final_artifacts.py",
            "python3 scripts/materialize_frozen_artifacts.py",
            "python3 scripts/submit_materializer_v4.py",
            "python3 scripts/finalize_input_contract.py",
            "python3 scripts/stage_deterministic_wgs_report.py",
            "python3 aws/submit_route.py",
            "python3 scripts/capture_route_terminal.py",
            "python3 scripts/stage_hrd_crosscheck_report.py",
            "python3 scripts/generate_blocked_hrd_crosscheck_reports.py",
        ):
            self.assertNotIn(generated_command, text)

    def test_post_success_sequence_is_documented_without_stale_manual_args(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        previous = -1
        for script in (
            "scripts/capture_batch_provenance.py",
            "scripts/submit_materializer_v4.py",
            "scripts/finalize_input_contract.py",
            "scripts/stage_deterministic_wgs_report.py",
            "aws/submit_route.py",
            "scripts/stage_hrd_crosscheck_report.py",
            "scripts/render_source_report_freeze_runbook.py",
        ):
            index = text.find(script, previous + 1)
            self.assertGreater(index, previous)
            previous = index

        self.assertNotRegex(
            text,
            re.compile(
                r"--crosscheck-materialization-receipt.*"
                r"--crosscheck-materialization-receipt",
                re.DOTALL,
            ),
        )
        self.assertNotIn("SUBMISSION_ID=20260717T200000Z-sequenza1", text)
        self.assertNotIn("ROUTE=sequenza_scarhrd", text)
        self.assertNotIn(
            '--source-dir ".codex-tmp/hrd-reports/route-replays/$ROUTE"',
            text,
        )

    def test_deterministic_report_inventory_includes_crosscheck_input_plans(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertIn("six `deterministic_full_wgs` packet\nfiles", text)
        self.assertIn("crosscheck_input_plans.json", text)
        self.assertNotIn("five `deterministic_full_wgs` packet\nfiles", text)

    def test_source_freeze_and_ai_flow_are_renderer_owned(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        freeze_section = text.split("## Freeze reviewed reports", 1)[1]

        self.assertLess(
            freeze_section.index("scripts/render_source_report_freeze_runbook.py"),
            freeze_section.index("scripts/render_ai_synthesis_runbook.py"),
        )
        self.assertLess(
            freeze_section.index("scripts/render_ai_synthesis_runbook.py"),
            freeze_section.index("scripts/render_reviewed_publication_runbook.py"),
        )
        for method_id in (
            "deterministic_full_wgs",
            "rosalind_diana_wgs",
            "sequenza_scarhrd",
            "sigprofiler_sbs3",
            "facets_scarhrd_blocked",
            "oncoanalyser_chord_blocked",
            "hrdetect_blocked",
        ):
            self.assertIn(method_id, freeze_section)
        self.assertIn("ten\nprivate receipts", freeze_section)
        self.assertIn("`comparative_hrd_synthesis`", freeze_section)

    def test_reviewed_publication_delegates_public_index_to_final_runbook(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        freeze_section = text.split("## Freeze reviewed reports", 1)[1]

        self.assertIn("scripts/render_reviewed_publication_runbook.py", freeze_section)
        self.assertIn("rebuilds\n`public-index/objects.json`", freeze_section)
        self.assertNotIn("python3 scripts/build_public_results_index.py", text)
        self.assertNotIn("python3 scripts/publish_public_results_index.py", text)

    def test_no_stale_inline_private_receipt_handoffs_remain(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        stale_snippets = (
            "--receipt-upload-output",
            "--private-publication-upload-receipt",
            "terminal.rosalind_diana_wgs.public.dry.json",
            "terminal.rosalind_diana_wgs.public.json",
            "--private-publication-receipt .codex-tmp/hrd-reports/",
            "--output .codex-tmp/hrd-reports/deterministic-full/source-freeze-runbook.md",
            ".codex-tmp/hrd-reports/ai-review/publication-receipts/",
        )
        for stale in stale_snippets:
            self.assertNotIn(stale, text)

    def test_download_examples_stay_on_public_alias_paths(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        self.assertIn(f"runs/diana-hrd-public/subject01/{RUN_ID}/early-look/", text)
        self.assertIn("https://${BUCKET}.s3.us-east-1.amazonaws.com/${KEY}", text)
        self.assertIn("curl -C -", text)
        self.assertIn("Do not publish private version-history receipts", text)


if __name__ == "__main__":
    unittest.main()
