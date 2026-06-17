import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands.hrd_context import build_rosalind_hrd_packet as packet


class RosalindHrdPacketTest(unittest.TestCase):
    def test_hcc1395_wes_packet_writes_no_call_adapter_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/full_wes_benchmark/full_wes_benchmark_summary.json",
                {
                    "status": "passed",
                    "bamValidationStatus": "passed",
                    "exactPassTruthMatches": 1122,
                    "exactPassRecall": 0.8585,
                    "exactPassPrecision": 0.9842,
                    "contaminationStatus": "passed",
                    "contaminationEstimate": "0.0",
                },
            )
            utils.write_json(root / "results/full_wes_benchmark/truth_overlap_benchmark_summary.json", {"status": "passed"})
            utils.write_csv(
                root / "results/full_wes_benchmark/full_wes_fastq_validation.csv",
                [{"status": "passed"}, {"status": "passed"}, {"status": "passed"}, {"status": "passed"}],
            )
            utils.write_csv(
                root / "results/full_wes_benchmark/full_wes_bam_validation.csv",
                [{"status": "passed"}, {"status": "passed"}],
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wes_summary.json",
                {"status": "expanded_non_dry_passed"},
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wes"], "unit")

            self.assertEqual(summary["sampleSet"], "hcc1395_wes")
            reviewer = utils.read_text(root / "results/rosalind_hrd/hcc1395_wes/unit/reviewer_packet.md")
            adapter_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/hcc1395_wes/unit/hrd_adapter_status.csv"))
            self.assertIn("does not support a genome-wide HRD scar", reviewer)
            self.assertIn("no_call", {row["state"] for row in adapter_rows})

    def test_hcc1395_wgs_packet_blocks_metadata_only_sv_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/phase3_wgs_smoke/phase3_wgs_summary.json",
                {
                    "status": "passed",
                    "fullSourceFastqs": True,
                    "readPairsPerEnd": 942559447,
                    "bamValidationStatus": "passed",
                    "mutect2Status": "skipped_public_bam_timing",
                    "truthVariantsDepthEligible": 0,
                    "exactPassTruthMatches": 0,
                    "coverageCnvStatus": "passed",
                    "coverageCnvBins": 631,
                    "sbs96MatrixStatus": "skipped_public_bam_timing",
                    "sbs96UsableSnvRecords": 0,
                },
            )
            for relative in [
                "results/phase3_wgs_smoke/bam_validation_summary.csv",
                "results/phase3_wgs_smoke/coverage_cnv_summary.json",
                "results/phase3_wgs_smoke/signature_assignment_summary.json",
                "results/clinicalization/hrd_interpretation_readiness_summary.json",
                "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json",
            ]:
                if relative.endswith(".csv"):
                    utils.write_csv(root / relative, [{"status": "passed"}])
                else:
                    utils.write_json(root / relative, {"status": "passed", "rows": []})
            utils.write_json(
                root / "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "tool": "CHORD",
                            "interpretability_status": "not_assessable_requires_validated_sv_caller_vcf",
                            "caveat": "needs validated SV caller",
                        }
                    ],
                },
            )
            utils.write_json(
                root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "status": "passed",
                            "tool": "metadata_only",
                            "discordant_mapped_pairs": "",
                            "chord_input_status": "not_assessable_metadata_only",
                        }
                    ],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wgs"], "unit")

            self.assertTrue(any("no discordant mapped-pair counts" in blocker for blocker in summary["blockers"]))
            next_actions = utils.read_text(root / "results/rosalind_hrd/hcc1395_wgs/unit/next_actions.md")
            self.assertIn("regenerate full SV evidence", next_actions)


if __name__ == "__main__":
    unittest.main()
