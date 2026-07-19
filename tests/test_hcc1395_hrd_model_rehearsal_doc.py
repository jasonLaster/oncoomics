from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/validation/hcc1395-hrd-model-rehearsal.md"
DOCS_INDEX = ROOT / "docs/README.md"
ARTIFACT_ROOT = ROOT / "artifacts/phase3_wgs_selective5"
PACKET_ROOT = (
    ROOT
    / "results/rosalind_hrd/hcc1395_wgs/hcc1395-wgs-selective5-20260717"
)


class Hcc1395HrdModelRehearsalDocTests(unittest.TestCase):
    def test_report_preserves_scope_and_no_call_boundaries(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        self.assertIn("not a Diana result", text)
        self.assertIn("Overall evidence status: `partial_evidence`", text)
        self.assertIn("Authorized HRD state: `no_call`", text)
        self.assertIn(
            "No HRD-positive or HRD-negative classification is authorized",
            normalized,
        )
        for method in ("scarHRD", "SBS3", "CHORD", "HRDetect"):
            self.assertIn(method, text)
        self.assertGreaterEqual(text.count("`no_call`"), 10)

    def test_report_records_measured_known_answer_results(self) -> None:
        text = DOC.read_text(encoding="utf-8")

        for measured_result in (
            "568,040,077 read pairs",
            "300 truth-depth-eligible variants",
            "268 exact PASS truth matches",
            "631 coverage bins",
            "265 usable PASS SNVs",
            "39,983,763 discordant mapped pairs",
        ):
            self.assertIn(measured_result, text)

        self.assertIn("Coverage bins are not allele-specific CNV/LOH segments", text)
        self.assertIn("Read counters are not a production somatic SV VCF", text)

    def test_report_separates_analytical_methods_from_model_reviewers(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        normalized = " ".join(text.split())

        self.assertIn("`gpt-5.6-sol` narrative audit", text)
        self.assertIn("`gpt-5.6-terra` adversarial audit", text)
        self.assertIn(
            "they did not run, reproduce, or replace any of those analytical methods",
            normalized,
        )
        self.assertIn("input matrix available; assignment not run", text)
        self.assertIn("input_matrix_ready_assignment_not_run", text)
        self.assertIn("five active interpretation gaps", normalized)
        self.assertIn("All 41 focused packet tests passed", text)
        self.assertIn("This is not multi-method biological concordance", text)

    def test_report_links_to_existing_frozen_evidence(self) -> None:
        self.assertTrue((ARTIFACT_ROOT / "README.md").is_file())
        for packet_file in (
            "report.md",
            "sample_validation_summary.csv",
            "hrd_adapter_status.csv",
            "input_evidence_index.json",
            "report_manifest.json",
        ):
            self.assertTrue((PACKET_ROOT / packet_file).is_file())

        text = DOC.read_text(encoding="utf-8")
        for digest in (
            "81b8cf1e02918898a6b3420df06e8171c7d1df75d492ddc01041b1f4ca30e123",
            "e86109a6219f503988b04c9503c8c8857bd2998ba5f0ec9148a546c5df7a25c0",
            "ffbe4f4e01dcdfb36c80e7bef26d77ea300e014f90f728bec4026a7a618803b4",
            "36ce5450e9decf5f0c80d6ec13c535c171892214fd84dedd5aedd9b3ccdc7151",
        ):
            self.assertIn(digest, text)

    def test_documentation_index_links_the_rehearsal(self) -> None:
        text = DOCS_INDEX.read_text(encoding="utf-8")
        self.assertIn(
            "validation/hcc1395-hrd-model-rehearsal.md",
            text,
        )


if __name__ == "__main__":
    unittest.main()
