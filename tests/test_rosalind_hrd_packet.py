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

    def test_hcc1395_wgs_packet_flags_stale_sv_readiness_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(root / "results/phase3_wgs_smoke/phase3_wgs_summary.json", {"status": "passed"})
            utils.write_json(root / "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/cnv_loh_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/hrd_interpretation_readiness_summary.json", {"status": "passed", "rows": []})
            utils.write_json(root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json", {"status": "passed"})
            utils.write_csv(root / "results/phase3_wgs_smoke/bam_validation_summary.csv", [{"status": "passed"}])
            utils.write_json(root / "results/phase3_wgs_smoke/coverage_cnv_summary.json", {"status": "passed"})
            utils.write_json(root / "results/phase3_wgs_smoke/signature_assignment_summary.json", {"status": "passed"})
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
            utils.write_json(
                root / "results/clinicalization/sv_caller_readiness_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "candidate_count": 4,
                            "phase3_discordant_mapped_pairs": 20,
                            "ready_for_clinical_interpretation": "no",
                        }
                    ],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wgs"], "unit")

            self.assertTrue(any("SV readiness sidecar is stale" in blocker for blocker in summary["blockers"]))
            evidence_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/hcc1395_wgs/unit/sample_validation_summary.csv"))
            self.assertIn("sv_caller_readiness", {row["evidence_id"] for row in evidence_rows})

    def test_artifact_root_override_reads_materialized_inputs(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            utils.write_json(
                artifact_root / "results/full_wes_benchmark/full_wes_benchmark_summary.json",
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
            utils.write_json(artifact_root / "results/full_wes_benchmark/truth_overlap_benchmark_summary.json", {"status": "passed"})
            utils.write_csv(
                artifact_root / "results/full_wes_benchmark/full_wes_fastq_validation.csv",
                [{"status": "passed"}, {"status": "passed"}, {"status": "passed"}, {"status": "passed"}],
            )
            utils.write_csv(
                artifact_root / "results/full_wes_benchmark/full_wes_bam_validation.csv",
                [{"status": "passed"}, {"status": "passed"}],
            )
            utils.write_json(
                artifact_root / "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wes_summary.json",
                {"status": "expanded_non_dry_passed"},
            )

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict("os.environ", {"ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root)}),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wes"], "unit")

            self.assertEqual(summary["missingArtifacts"], [])
            evidence_rows = utils.parse_csv(utils.read_text(output_root / "results/rosalind_hrd/hcc1395_wes/unit/sample_validation_summary.csv"))
            self.assertIn("4/4 FASTQ rows passed", evidence_rows[0]["detail"])
            artifact_index = utils.read_json(output_root / "results/rosalind_hrd/hcc1395_wes/unit/input_evidence_index.json")
            self.assertTrue(str(artifact_root) in artifact_index["artifacts"][0]["resolved_path"])

    def test_diana_raw_intake_packet_marks_waiting_input_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(
                root / "manifests/diana_raw_inputs.template.csv",
                [{"patient_id": "DIANA", "sample_id": "DIANA-TUMOR-DNA"}],
            )
            utils.write_text(root / "docs/operations/diana-raw-inputs.md", "# Diana Raw Inputs")
            utils.write_json(
                root / "results/diana_raw_intake/input_contract.json",
                {
                    "requiredColumns": ["patient_id", "pair_id", "sample_id"],
                    "dnaAssays": ["WGS", "WES"],
                    "dataTypes": ["FASTQ", "BAM", "CRAM"],
                    "validationCommand": "DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw",
                    "recomputeCommand": "DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw",
                },
            )
            utils.write_json(
                root / "results/diana_raw_intake/intake_readiness_summary.json",
                {
                    "status": "template_ready",
                    "template": "manifests/diana_raw_inputs.template.csv",
                    "actualSamplesheet": "manifests/diana_raw_inputs.csv",
                    "readyForDianaRawData": True,
                },
            )
            utils.write_json(
                root / "results/diana_raw_intake/input_validation_summary.json",
                {
                    "status": "waiting_for_diana_raw_data",
                    "summary": {"rowCount": 0, "dnaRowCount": 0, "tumorDnaRows": 0, "normalDnaRows": 0, "matchedPairIds": []},
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_raw_intake"], "unit")

            self.assertTrue(any("Actual Diana BAM/FASTQ/CRAM paths" in blocker for blocker in summary["blockers"]))
            adapter_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/diana_raw_intake/unit/hrd_adapter_status.csv"))
            self.assertIn("blocked_until_files", {row["state"] for row in adapter_rows})
            reviewer = utils.read_text(root / "results/rosalind_hrd/diana_raw_intake/unit/reviewer_packet.md")
            self.assertIn("verify:diana-raw", reviewer)


if __name__ == "__main__":
    unittest.main()
