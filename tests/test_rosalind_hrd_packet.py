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

    def test_hcc1395_wgs_packet_flags_zero_sidecar_against_positive_sv_counts(self):
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
                            "tool": "samtools view flag/evidence counters",
                            "discordant_mapped_pairs": 20,
                            "chord_input_status": "not_assessable_requires_validated_sv_caller_vcf",
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
                            "phase3_discordant_mapped_pairs": 0,
                            "ready_for_clinical_interpretation": "no",
                        }
                    ],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hcc1395_wgs"], "unit")

            self.assertTrue(any("sv_evidence_summary reports 20" in blocker for blocker in summary["blockers"]))

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

    def test_hg008_packet_surfaces_sv_truth_asset_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json",
                {"status": "expanded_non_dry_passed", "publicFindingResult": "40/40 SNVs passed.", "blockers": []},
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json",
                {
                    "status": "expanded_non_dry_passed",
                    "publicFindingResult": "4/4 CNVs passed.",
                    "blockers": ["No Diana-generated CNV callset exists for HG008."],
                    "evidence": {"cnvProbes": [{"passed": True}, {"passed": True}, {"passed": True}, {"passed": True}]},
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_sv_truth_asset.json",
                {
                    "status": "expanded_non_dry_gap_identified",
                    "publicFindingResult": "HG008 SV truth asset is present.",
                    "blockers": ["No Diana-generated SV callset exists for HG008."],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json",
                {
                    "status": "bounded_non_dry_partial",
                    "publicFindingResult": "SV overlap remains unrun.",
                    "blockers": ["No Diana-generated SV/CNV callset exists for HG008 in this bounded run."],
                    "evidence": {
                        "cnvDepthProbe": {
                            "passedCnvDepthSignal": True,
                            "normalizedLossTumorNormalRatio": 0.438786,
                            "remainingSvGap": "SV reciprocal-overlap remains unrun.",
                        }
                    },
                },
            )
            utils.write_json(root / "results/clinicalization/known_answer_runs/expanded_cohort/hg008_rna_stats.json", {"status": "passed"})

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["hg008"], "unit")

            self.assertEqual(
                summary["blockers"],
                [
                    "No Diana-generated CNV segment callset exists for HG008; current HG008 CNV evidence is bounded depth-direction validation, not segment-level reciprocal overlap.",
                    "No Diana-generated SV callset exists for HG008; SV reciprocal-overlap against v0.5 truth remains unrun.",
                ],
            )
            evidence_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/hg008/unit/sample_validation_summary.csv"))
            self.assertIn("sv_truth_asset", {row["evidence_id"] for row in evidence_rows})
            cnv_row = next(row for row in evidence_rows if row["evidence_id"] == "cnv_depth_sweep")
            self.assertIn("Bounded reciprocal depth signal present: yes", cnv_row["detail"])
            reviewer = utils.read_text(root / "results/rosalind_hrd/hg008/unit/reviewer_packet.md")
            self.assertIn("HG008 SV truth asset is present", reviewer)
            self.assertIn("normalized loss tumor-normal ratio: 0.438786", reviewer)

    def test_colo829_packet_surfaces_purity_series_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                "colo829_platform_illumina_hiseqx",
                "colo829_platform_pacbio_sequel",
                "colo829_platform_ont_minion",
                "colo829_platform_illumina_novaseq_phased",
            ):
                utils.write_json(
                    root / f"results/clinicalization/known_answer_runs/expanded_cohort/{name}.json",
                    {"status": "expanded_non_dry_passed", "publicFindingResult": f"{name} recovered BRAF V600E."},
                )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json",
                {
                    "status": "expanded_non_dry_gap_identified",
                    "publicFindingResult": "SV/CNA truth assets are present.",
                    "blockers": ["No Diana SV/CNA callset exists."],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json",
                {"status": "bounded_non_dry_gap_identified", "publicFindingResult": "SV/CNA overlap was not generated.", "blockers": []},
            )
            purity_blocker = "Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested."
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_illumina.json",
                {
                    "status": "expanded_non_dry_blocked_remote_index_missing",
                    "publicFindingResult": "COLO829 purity illumina metadata exposes selected levels.",
                    "blockers": [purity_blocker],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_long_read.json",
                {
                    "status": "expanded_non_dry_blocked_remote_index_missing",
                    "publicFindingResult": "COLO829 purity long_read metadata exposes selected levels.",
                    "blockers": [purity_blocker],
                },
            )
            utils.write_json(
                root / "results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json",
                {
                    "status": "bounded_non_dry_blocked_remote_index_missing",
                    "publicFindingResult": "COLO829 dilution BAMs cannot be remotely region-sliced.",
                    "blockers": [purity_blocker],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["colo829"], "unit")

            self.assertIn(purity_blocker, summary["blockers"])
            evidence_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/colo829/unit/sample_validation_summary.csv"))
            evidence_ids = {row["evidence_id"] for row in evidence_rows}
            self.assertIn("purity_illumina_metadata", evidence_ids)
            self.assertIn("purity_long_read_metadata", evidence_ids)
            self.assertIn("purity_recall_table", evidence_ids)
            adapter_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/colo829/unit/hrd_adapter_status.csv"))
            self.assertIn("Purity sensitivity benchmark", {row["adapter"] for row in adapter_rows})

    def test_cloud_materialization_plan_preserves_selected_sample_sets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                packet.write_cloud_materialization_plan(
                    "results/rosalind_hrd/unit",
                    "unit",
                    [{"sampleSet": "hcc1395_wgs", "missingArtifacts": []}],
                )
            plan = utils.read_text(root / "results/rosalind_hrd/unit/cloud_materialization_plan.md")
        self.assertIn("export ROSALIND_HRD_SAMPLE_SET=hcc1395_wgs", plan)

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
