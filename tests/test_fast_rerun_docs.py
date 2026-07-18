from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEXT_GEN = ROOT / "docs/operations/next-generation-fast-rerun.md"
SUMMARY = ROOT / "docs/operations/fast-rerun-performance-cost-summary.md"
AWS_README = ROOT / "infra/aws/README.md"


class FastRerunDocsTests(unittest.TestCase):
    def test_next_generation_doc_records_operator_stopped_v4(self) -> None:
        text = NEXT_GEN.read_text(encoding="utf-8")

        self.assertIn("observed through 2026-07-18 04:49 UTC", text)
        self.assertIn("single-node CPU evidence retry was intentionally stopped during v4", text)
        self.assertIn("Do not restart that S3-only\nworker", text)
        self.assertIn("GetPileupSummaries", text)
        self.assertIn("Track the 384 On-Demand P vCPU request", text)

    def test_fast_rerun_summary_does_not_revive_the_cpu_retry(self) -> None:
        text = SUMMARY.read_text(encoding="utf-8")

        self.assertIn("operator-stopped v4 retry", text)
        self.assertIn("Do not restart\nthat same monolithic single-node CPU topology", text)
        self.assertIn("checked-in resumable DAG", text)
        self.assertNotIn("keep the CPU job alive", text)

    def test_legacy_full_wgs_launcher_is_not_current_diana_rerun_path(self) -> None:
        text = AWS_README.read_text(encoding="utf-8")

        self.assertIn("Do not use this legacy full-source CPU launcher", text)
        self.assertIn("phase3_wgs_fast", text)
        self.assertIn("P5en/Parabricks", text)


if __name__ == "__main__":
    unittest.main()
