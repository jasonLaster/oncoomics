import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import patch

from test_phase3_fast_deterministic_report import _crosscheck_materialization_plan, _write_final_manifest

from diana_omics import utils
from diana_omics.commands.hrd_context import build_rosalind_hrd_packet as packet
from diana_omics.commands.phase3_wgs import stage_phase3_fast_deterministic_report as stage_phase3_fast_report


def write_diana_wgs_worker_artifacts(root: Path, readiness_overrides: Optional[Dict[str, str]] = None) -> None:
    readiness_overrides = readiness_overrides or {}
    readiness = [
        {
            "evidence_surface": surface,
            "status": readiness_overrides.get(surface, status),
            "detail": detail,
        }
        for surface, status, detail in (
            ("source_sha256", "ready", "Payload checksums passed."),
            ("wgs_alignment", "ready", "Tumor and normal alignment passed."),
            ("matched_normal_somatic_variants", "ready", "Matched-normal calling passed."),
            ("coverage_cnv", "partial_evidence", "Coverage bins are not allele-specific."),
            ("sbs96", "partial_evidence", "SBS96 input exists without SBS3 assignment."),
            ("sv", "partial_evidence", "BAM-derived counts are not an SV callset."),
            ("scarHRD", "no_call", "Allele-specific segments and purity/ploidy are absent."),
            ("CHORD", "no_call", "A validated production SV callset is absent."),
            ("HRDetect", "no_call", "The calibrated integrated feature model is absent."),
            ("overall_hrd", "no_call", "No defensible scalar HRD classification is available."),
        )
    ]
    utils.write_json(
        root / "diana_hrd_summary.json",
        {
            "status": "no_call",
            "evidence_status": "partial_evidence",
            "run_id": "unit-worker-run",
            "input": {
                "dataset": "SENSITIVE-DATASET-LABEL",
                "pair": "SENSITIVE-PAIR-ID",
                "lanes": 2,
                "reference": "hg38 analysis reference",
                "source_integrity": "passed",
            },
            "hrd_readiness": readiness,
            "boundary": "Research-use output with no clinical or scalar HRD conclusion authorized.",
        },
    )
    utils.write_csv(root / "hrd_readiness.csv", readiness)
    alignment_rows = [
        {"status": "passed", "role": "tumor", "total_reads": 100, "mapped_reads": 98},
        {"status": "passed", "role": "normal", "total_reads": 100, "mapped_reads": 99},
    ]
    utils.write_json(root / "alignment/bam_validation_summary.json", {"status": "passed", "rows": alignment_rows})
    utils.write_json(
        root / "variants/mutect2_summary.json",
        {
            "status": "passed",
            "total_filtered_records": 321,
            "pass_records": 123,
            "pass_snvs": 100,
            "pass_indels": 23,
            "brca1_brca2_pass_region_records": 1,
        },
    )
    utils.write_csv(
        root / "variants/brca1_brca2_pass_variants.csv",
        [{"contig": "chr17", "position": "100", "annotation_status": "region_only_requires_variant_annotation_review"}],
    )
    utils.write_json(
        root / "cnv/coverage_cnv_summary.json",
        {"status": "partial_evidence", "bin_count": 600, "relative_gain_bins": 4, "relative_loss_bins": 5},
    )
    cnv_rows = []
    for index in range(600):
        coverage_class = (
            "relative_gain" if index < 4 else "relative_loss" if index < 9 else "neutral_or_low_signal"
        )
        cnv_rows.append(
            {"contig": "chr1", "start": index * 5_000_000, "end": (index + 1) * 5_000_000, "coverage_class": coverage_class}
        )
    utils.write_csv(root / "cnv/coverage_cnv_bins.csv", cnv_rows)
    utils.write_json(
        root / "signatures/signature_assignment_summary.json",
        {
            "status": "partial_evidence",
            "usable_snv_records": 100,
            "sbs96_rows": 96,
            "sigprofiler_assignment_status": "input_ready_threshold_met",
            "sbs3_status": "no_call_signature_assignment_and_threshold_policy_not_locked",
        },
    )
    substitutions = ("C>A", "C>G", "C>T", "T>A", "T>C", "T>G")
    bases = ("A", "C", "G", "T")
    sbs_rows = []
    for substitution in substitutions:
        for left in bases:
            for right in bases:
                sbs_rows.append(
                    {
                        "mutation_type": substitution,
                        "trinucleotide": f"{left}[{substitution}]{right}",
                        "count": 2 if len(sbs_rows) < 4 else 1,
                    }
                )
    utils.write_csv(root / "signatures/wgs_sbs96_matrix.csv", sbs_rows)
    sv_rows = [
        {
            "status": "partial_evidence", "role": "tumor", "total_alignments": 100,
            "discordant_mapped_pairs": 20, "supplementary_alignments": 10,
            "interchromosomal_pairs": 4, "large_insert_pairs": 16,
        },
        {
            "status": "partial_evidence", "role": "normal", "total_alignments": 100,
            "discordant_mapped_pairs": 8, "supplementary_alignments": 3,
            "interchromosomal_pairs": 2, "large_insert_pairs": 6,
        },
    ]
    utils.write_json(
        root / "sv/sv_evidence_summary.json",
        {"status": "partial_evidence", "rows": sv_rows, "production_sv_callset_status": "no_call"},
    )
    utils.write_csv(root / "sv/sv_evidence_summary.csv", sv_rows)
    utils.write_json(
        root / "tool_versions.json",
        {"bwa": "bwa 0.7.17", "samtools": "samtools 1.20", "bcftools": "bcftools 1.20", "gatk": "gatk 4.6.1.0"},
    )


def write_deterministic_report(root: Path, artifact_root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    input_rows = []
    source_sha256 = {}
    for relative, input_id in packet.DIANA_WGS_DETERMINISTIC_INPUTS.items():
        path = artifact_root / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source_sha256[input_id] = digest
        input_rows.append(
            {
                "input_id": input_id,
                "path": f"artifact-root/{relative}",
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
    utils.write_csv(root / "input_sha256.csv", input_rows)
    utils.write_csv(root / "readiness.csv", [{"evidence_surface": "overall_hrd", "state": "no_call", "reason": "unit"}])
    utils.write_json(
        root / "evidence_checks.json",
        {
            "status": "passed",
            "report_status": "partial_evidence",
            "overall_hrd_status": "no_call",
            "checks": [{"check_id": "unit_contract", "status": "passed", "detail": "synthetic"}],
            "input_sha256": input_rows,
        },
    )
    utils.write_json(
        root / "crosscheck_input_plans.json",
        {
            "schema_version": 1,
            "plan_type": "terminal_crosscheck_input_materialization_plan",
            "status": "materialized",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "routes": {
                "sequenza_scarhrd": {
                    "status": "inputs_materialized",
                    "execution_status": "not_run",
                    "interpretation_status": "no_call",
                },
                "sigprofiler_sbs3": {
                    "status": "inputs_materialized",
                    "execution_status": "not_run",
                    "interpretation_status": "no_call",
                },
            },
        },
    )
    (root / "report.md").write_text("# Deterministic full-WGS unit report\n", encoding="utf-8")
    support_sha256 = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in packet.DETERMINISTIC_SUPPORT_FILES
    }
    utils.write_json(
        root / "report_manifest.json",
        {
            "schema_version": 1,
            "method_id": "deterministic_full_wgs",
            "report_kind": "deterministic_baseline",
            "evidence_status": "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "support_sha256": support_sha256,
            "source_sha256": source_sha256,
            "report_sha256": hashlib.sha256((root / "report.md").read_bytes()).hexdigest(),
            "review_summary": {
                "overall": {"evidence_status": "partial_evidence", "authorized_hrd_state": "no_call"},
                "custody": {
                    "private_freeze_status": "passed",
                    "exact_kms_match": True,
                    "freeze_receipt_version_id": "freeze-version-unit",
                    "stage_provenance_receipt_version_id": "stage-version-unit",
                    "freeze_receipt_sha256": "a" * 64,
                    "stage_provenance_receipt_sha256": "b" * 64,
                },
            },
        },
    )
    return root


def write_phase3_fast_deterministic_report(root: Path) -> tuple[Path, Path]:
    final_manifest_path, final_root, final_manifest = _write_final_manifest(root)
    deterministic_root = root / "deterministic"
    stage_phase3_fast_report.stage_phase3_fast_deterministic_report(
        final_manifest,
        _crosscheck_materialization_plan(final_manifest, final_manifest_path),
        final_manifest_sha256=hashlib.sha256(final_manifest_path.read_bytes()).hexdigest(),
        final_manifest_bytes=final_manifest_path.stat().st_size,
        final_root=final_root,
        output_dir=deterministic_root,
    )
    return deterministic_root, final_root


class RosalindHrdPacketTest(unittest.TestCase):
    def test_packet_file_writes_are_create_only_and_fsynced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "results/rosalind_hrd/unit/report.md"

            with patch.object(
                packet.os,
                "fsync",
                wraps=packet.os.fsync,
            ) as fsync:
                packet.write_text_create_only(destination, "one")

            self.assertEqual(destination.read_text(encoding="utf-8"), "one\n")
            self.assertEqual(fsync.call_count, 1)

            with self.assertRaises(FileExistsError):
                packet.write_text_create_only(destination, "two")

            self.assertEqual(destination.read_text(encoding="utf-8"), "one\n")

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

    def test_diana_wgs_packet_consumes_worker_artifact_root_without_exposing_input_labels(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(summary["missingArtifacts"], [])
            self.assertEqual(summary["blockers"], [])
            evidence_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/sample_validation_summary.csv")
            )
            self.assertEqual(
                {row["evidence_id"] for row in evidence_rows},
                {
                    "wgs_run_boundary",
                    "wgs_alignment",
                    "matched_normal_somatic_variants",
                    "hrr_region_small_variants",
                    "coverage_cnv",
                    "sbs96_input",
                    "bam_derived_sv_evidence",
                },
            )
            adapter_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/hrd_adapter_status.csv")
            )
            self.assertEqual({row["state"] for row in adapter_rows}, {"ready", "partial_evidence", "no_call"})
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "scarHRD")["state"], "no_call")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "SBS3")["state"], "no_call")
            reviewer = utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/reviewer_packet.md")
            self.assertIn("does not support a scalar or categorical HRD conclusion", reviewer)
            self.assertNotIn("SENSITIVE-PAIR-ID", reviewer)
            self.assertNotIn("SENSITIVE-DATASET-LABEL", reviewer)

            evidence_index = utils.read_json(
                output_root / "results/rosalind_hrd/diana_wgs/unit/input_evidence_index.json"
            )
            self.assertEqual(len(evidence_index["artifacts"]), len(packet.PACKET_SPECS["diana_wgs"].artifacts))
            for artifact in evidence_index["artifacts"]:
                source = artifact_root / artifact["path"]
                self.assertEqual(artifact["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

            report = output_root / "results/rosalind_hrd/diana_wgs/unit/report.md"
            manifest = utils.read_json(
                output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            self.assertEqual(report.read_text(encoding="utf-8"), reviewer)
            self.assertEqual(manifest["method_id"], "rosalind_diana_wgs")
            self.assertEqual(manifest["evidence_status"], "partial_evidence")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(manifest["report_sha256"], hashlib.sha256(report.read_bytes()).hexdigest())
            self.assertEqual(len(manifest["source_sha256"]), len(evidence_index["artifacts"]))
            self.assertEqual(
                set(manifest["support_sha256"]),
                {
                    "input_evidence_index.json", "sample_validation_summary.csv",
                    "hrd_adapter_status.csv", "research_context_sources.json",
                    "next_actions.md", "reviewer_packet.md",
                },
            )
            self.assertEqual(manifest["review_summary"]["provenance"]["artifact_count"], 12)
            self.assertTrue(manifest["review_summary"]["provenance"]["custody"]["exact_kms_match"])
            self.assertTrue(all(row["next_action"] for row in manifest["review_summary"]["adapters"]))
            self.assertIn("## Deterministic custody and process", reviewer)
            self.assertIn("samtools 1.20", reviewer)
            serialized_manifest = utils.read_text(
                output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json"
            )
            self.assertNotIn("SENSITIVE-PAIR-ID", serialized_manifest)
            self.assertNotIn("SENSITIVE-DATASET-LABEL", serialized_manifest)

    def test_diana_wgs_packet_consumes_phase3_fast_deterministic_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

            self.assertEqual(summary["missingArtifacts"], [])
            self.assertEqual(summary["blockers"], [])

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/phase3-fast"
            evidence_rows = utils.parse_csv(utils.read_text(output_dir / "sample_validation_summary.csv"))
            self.assertEqual(
                {row["evidence_id"] for row in evidence_rows},
                {
                    "phase3_fast_run_boundary",
                    "source_sha256",
                    "matched_normal_somatic_variants",
                    "wgs_bam_qc",
                    "coverage_cnv",
                    "sbs96_input",
                    "sigprofiler_sbs3_input_plan",
                    "sequenza_scarhrd_input_plan",
                    "bam_derived_sv_evidence",
                },
            )
            self.assertEqual(
                next(row for row in evidence_rows if row["evidence_id"] == "sbs96_input")["status"],
                "partial_evidence",
            )

            adapter_rows = utils.parse_csv(utils.read_text(output_dir / "hrd_adapter_status.csv"))
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "scarHRD")["state"], "no_call")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "CHORD")["state"], "no_call")
            self.assertEqual(
                next(row for row in adapter_rows if row["adapter"] == "SBS96 input matrix")["state"],
                "partial_evidence",
            )
            self.assertEqual(
                next(row for row in adapter_rows if row["adapter"] == "SigProfiler/SBS3 input materializer")["state"],
                "blocked",
            )
            self.assertEqual(
                next(row for row in adapter_rows if row["adapter"] == "Sequenza/scarHRD input materializer")["state"],
                "blocked",
            )

            reviewer = utils.read_text(output_dir / "reviewer_packet.md")
            self.assertIn("Phase 3 fast final evidence", reviewer)
            self.assertIn("SigProfiler/SBS3 input materialization: `awaiting_private_results_freeze`", reviewer)
            self.assertIn("Sequenza/scarHRD input materialization: `blocked`", reviewer)
            self.assertIn(
                "Sequenza/scarHRD alias contract: `blocked` with `sequenza.female=true`.",
                reviewer,
            )
            self.assertIn(
                "Sequenza/scarHRD attestations: final BAM contract published `false`; "
                "validated runtime `false`.",
                reviewer,
            )
            self.assertIn("SBS96", reviewer)
            manifest = utils.read_json(output_dir / "report_manifest.json")
            self.assertEqual(manifest["method_id"], "rosalind_diana_wgs")
            self.assertEqual(manifest["evidence_status"], "partial_evidence")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(
                manifest["review_summary"]["provenance"]["binding_kind"],
                "phase3_fast_final",
            )
            self.assertEqual(
                "awaiting_private_results_freeze",
                manifest["review_summary"]["provenance"]["phase3_fast"]["crosscheck_input_plans"][
                    "sigprofiler_sbs3"
                ],
            )
            self.assertEqual(
                "blocked",
                manifest["review_summary"]["provenance"]["phase3_fast"]["crosscheck_input_plans"][
                    "sequenza_scarhrd"
                ],
            )
            sequenza_contract = manifest["review_summary"]["provenance"]["phase3_fast"][
                "sequenza_scarhrd_alias_input_contract"
            ]
            self.assertEqual(
                {"sequenza": {"female": True}},
                sequenza_contract["method_parameters"],
            )
            self.assertEqual(
                {
                    "tumor": "subject01_tumor",
                    "normal": "subject01_normal",
                },
                sequenza_contract["planned_aliases"],
            )
            self.assertNotIn("tumor_sample", json.dumps(sequenza_contract))
            self.assertNotIn("normal_sample", json.dumps(sequenza_contract))
            self.assertEqual(
                [
                    "normal_bai",
                    "normal_bam",
                    "staged_validation",
                    "tumor_bai",
                    "tumor_bam",
                ],
                sequenza_contract["planned_alias_output_roles"],
            )
            self.assertNotIn(".bam", json.dumps(sequenza_contract))
            self.assertFalse(
                sequenza_contract["attestations"]["final_bam_contract_published"]
            )
            self.assertFalse(
                sequenza_contract["attestations"]["validated_sequenza_scarhrd_runtime"]
            )
            self.assertEqual("GRCh38", sequenza_contract["reference"]["build"])
            self.assertIn("tumor_bam", sequenza_contract["artifacts"])
            self.assertEqual(
                {"bytes", "sha256", "version_id"},
                set(sequenza_contract["artifacts"]["tumor_bam"]),
            )
            self.assertIn("small_variants.filter_mutect.filtered_vcf", manifest["source_sha256"])
            evidence_index = utils.read_json(output_dir / "input_evidence_index.json")
            self.assertEqual(
                len(evidence_index["artifacts"]),
                manifest["review_summary"]["provenance"]["artifact_count"] + 1,
            )

    def test_diana_wgs_phase3_fast_packet_requires_sequenza_alias_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")
            plans_path = deterministic_root / "crosscheck_input_plans.json"
            plans = utils.read_json(plans_path)
            plans["routes"]["sequenza_scarhrd"].pop("alias_input_contract")
            utils.write_json(plans_path, plans)
            report_manifest_path = deterministic_root / "report_manifest.json"
            report_manifest = utils.read_json(report_manifest_path)
            report_manifest["support_sha256"]["crosscheck_input_plans.json"] = hashlib.sha256(
                plans_path.read_bytes()
            ).hexdigest()
            utils.write_json(report_manifest_path, report_manifest)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                self.assertRaisesRegex(ValueError, "lacks an alias input contract"),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

    def test_diana_wgs_phase3_fast_packet_rejects_final_artifact_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(output_root / "phase3_fast")
            (final_root / "artifacts/cnv_evidence/coverage_bins/coverage_cnv_bins.csv").write_text(
                "changed\n",
                encoding="utf-8",
            )

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "final artifact hash differs"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "phase3-fast")

    def test_diana_wgs_packet_clamps_unsupported_adapter_promotions(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(
                artifact_root,
                readiness_overrides={"coverage_cnv": "ready", "scarHRD": "ready", "overall_hrd": "ready"},
            )
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(any("coverage_cnv attempted promotion to ready" in blocker for blocker in summary["blockers"]))
            self.assertTrue(any("scarHRD attempted promotion to ready" in blocker for blocker in summary["blockers"]))
            self.assertTrue(any("overall_hrd attempted promotion to ready" in blocker for blocker in summary["blockers"]))
            adapter_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/hrd_adapter_status.csv")
            )
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "Coverage CNV proxy")["state"], "partial_evidence")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "scarHRD")["state"], "no_call")
            self.assertEqual(next(row for row in adapter_rows if row["adapter"] == "Overall HRD classification")["state"], "no_call")

    def test_diana_wgs_packet_does_not_turn_missing_sidecars_into_zero_count_findings(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            for relative in (
                "alignment/bam_validation_summary.json",
                "variants/mutect2_summary.json",
                "cnv/coverage_cnv_summary.json",
                "signatures/signature_assignment_summary.json",
                "sv/sv_evidence_summary.json",
            ):
                (artifact_root / relative).unlink()

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "Diana WGS"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")
            self.assertFalse(
                (output_root / "results/rosalind_hrd/diana_wgs/unit/report_manifest.json").exists()
            )

    def test_diana_wgs_packet_flags_disagreement_between_readiness_csv_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            worker_summary = utils.read_json(artifact_root / "diana_hrd_summary.json")
            next(row for row in worker_summary["hrd_readiness"] if row["evidence_surface"] == "wgs_alignment")["status"] = "no_call"
            utils.write_json(artifact_root / "diana_hrd_summary.json", worker_summary)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertTrue(any("readiness CSV disagrees" in blocker for blocker in summary["blockers"]))
            adapter_rows = utils.parse_csv(
                utils.read_text(output_root / "results/rosalind_hrd/diana_wgs/unit/hrd_adapter_status.csv")
            )
            alignment = next(row for row in adapter_rows if row["adapter"] == "WGS alignment")
            self.assertEqual(alignment["state"], "no_call")
            self.assertIn("no state promotion", alignment["blocker"])

    def test_diana_wgs_packet_rejects_deterministic_or_worker_tampering(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            (deterministic_root / "evidence_checks.json").write_text("{}\n", encoding="utf-8")
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "support hash differs"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")
            self.assertEqual(list(output_dir.glob("*")), [])

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            alignment_path = artifact_root / "alignment/bam_validation_summary.json"
            alignment = utils.read_json(alignment_path)
            alignment["rows"][1]["role"] = "tumor"
            utils.write_json(alignment_path, alignment)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "one passed tumor and one passed normal"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

    def test_diana_wgs_packet_rejects_stale_artifact_index(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            original_artifact_index = packet.artifact_index

            def stale_artifact_index(*args, **kwargs):
                rows = original_artifact_index(*args, **kwargs)
                return [
                    {
                        **row,
                        "sha256": "0" * 64
                        if row["path"] == "diana_hrd_summary.json"
                        else row["sha256"],
                    }
                    for row in rows
                ]

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.object(packet, "artifact_index", side_effect=stale_artifact_index),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "artifact index differs from deterministic input summary",
                ):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(list(output_dir.glob("*")), [])

    def test_diana_wgs_packet_rejects_existing_packet_files_create_only(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

                output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
                original_bytes = {
                    path.name: path.read_bytes() for path in output_dir.iterdir()
                }
                (deterministic_root / "evidence_checks.json").write_text(
                    "{}\n", encoding="utf-8"
                )

                with self.assertRaisesRegex(ValueError, "already contains packet files"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(
                {path.name: path.read_bytes() for path in output_dir.iterdir()},
                original_bytes,
            )

    def test_diana_wgs_packet_cleans_current_attempt_after_install_failure(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            copied: list[str] = []
            original_copy = packet.copy_diana_wgs_packet_file

            def fail_after_first_copy(source: Path, destination: Path) -> None:
                if copied:
                    raise ValueError("synthetic install failure")
                original_copy(source, destination)
                copied.append(destination.name)

            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
                patch.object(
                    packet,
                    "copy_diana_wgs_packet_file",
                    side_effect=fail_after_first_copy,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "synthetic install failure"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(copied, ["input_evidence_index.json"])
            self.assertEqual(list(output_dir.glob("*")), [])

    def test_diana_wgs_packet_rejects_stale_extra_output(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            deterministic_root = write_deterministic_report(
                output_root / "deterministic",
                artifact_root,
            )
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            output_dir.mkdir(parents=True)
            utils.write_text(output_dir / "unexpected.txt", "stale")

            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "unexpected existing files"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")

            self.assertEqual(
                sorted(path.name for path in output_dir.iterdir()),
                ["unexpected.txt"],
            )

    def test_diana_wgs_packet_rejects_output_below_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            real_parent = output_root / "real-rosalind"
            real_parent.mkdir()
            linked_parent = output_root / "results/rosalind_hrd"
            linked_parent.parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "Diana WGS packet output parent may not be a symlink",
            ):
                packet.prepare_diana_wgs_output_dir(
                    linked_parent / "diana_wgs" / "unit",
                    packet.PACKET_REPORT_FILES,
                )

            self.assertFalse((real_parent / "diana_wgs").exists())

    def test_diana_wgs_packet_identifier_scan_removes_generated_outputs(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as artifacts:
            output_root = Path(tmp)
            artifact_root = Path(artifacts)
            write_diana_wgs_worker_artifacts(artifact_root)
            summary_path = artifact_root / "diana_hrd_summary.json"
            summary = utils.read_json(summary_path)
            summary["input"]["reference"] = summary["input"]["pair"]
            utils.write_json(summary_path, summary)
            deterministic_root = write_deterministic_report(output_root / "deterministic", artifact_root)
            output_dir = output_root / "results/rosalind_hrd/diana_wgs/unit"
            with (
                patch.object(packet, "path_from_root", lambda relative: output_root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                    },
                ),
            ):
                with self.assertRaisesRegex(ValueError, "identifier scan failed"):
                    packet.write_packet(packet.PACKET_SPECS["diana_wgs"], "unit")
            self.assertFalse((output_dir / "report.md").exists())
            self.assertFalse((output_dir / "report_manifest.json").exists())
            self.assertEqual(list(output_dir.glob("*")), [])

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

    def test_cloud_materialization_plan_identifies_diana_wgs_artifact_directory_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                packet.write_cloud_materialization_plan(
                    "results/rosalind_hrd/unit",
                    "unit",
                    [{"sampleSet": "diana_wgs", "missingArtifacts": ["diana_hrd_summary.json"]}],
                )
            plan = utils.read_text(root / "results/rosalind_hrd/unit/cloud_materialization_plan.md")
        self.assertIn("artifact directory that directly contains `diana_hrd_summary.json`", plan)
        self.assertIn("Do not point it at the parent run directory", plan)

    def test_cloud_materialization_plan_rejects_symlinked_parent_without_writing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real_output = root / "real-rosalind"
            real_output.mkdir()
            linked_output = root / "results" / "rosalind_hrd"
            linked_output.parent.mkdir()
            linked_output.symlink_to(real_output, target_is_directory=True)

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                with self.assertRaisesRegex(
                    ValueError,
                    "HRD packet output parent may not be a symlink",
                ):
                    packet.write_cloud_materialization_plan(
                        "results/rosalind_hrd/unit",
                        "unit",
                        [{"sampleSet": "diana_wgs", "missingArtifacts": []}],
                    )

            self.assertFalse((real_output / "unit").exists())

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
                    "handoffPlanCommand": "PYTHONPATH=src /usr/bin/python3 -m diana_omics plan:diana-raw-handoff",
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
            utils.write_json(
                root / "results/diana_raw_intake/dinah_handoff_plan.json",
                {
                    "status": "waiting_for_dinah_files",
                    "samplesheet": "manifests/diana_raw_inputs.csv",
                    "analysisId": "unit",
                    "currentState": {"status": "waiting_for_dinah_files"},
                    "handoffSteps": [{"name": "strict_validate_diana_inputs"}, {"name": "stage_diana_raw_analysis_packet"}],
                },
            )

            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                summary = packet.write_packet(packet.PACKET_SPECS["diana_raw_intake"], "unit")

            self.assertTrue(any("Actual Diana BAM/FASTQ/CRAM paths" in blocker for blocker in summary["blockers"]))
            adapter_rows = utils.parse_csv(utils.read_text(root / "results/rosalind_hrd/diana_raw_intake/unit/hrd_adapter_status.csv"))
            self.assertIn("blocked_until_files", {row["state"] for row in adapter_rows})
            reviewer = utils.read_text(root / "results/rosalind_hrd/diana_raw_intake/unit/reviewer_packet.md")
            self.assertIn("verify:diana-raw", reviewer)
            self.assertIn("dinah_handoff_plan", reviewer)
            self.assertIn("plan:diana-raw-handoff", reviewer)


if __name__ == "__main__":
    unittest.main()
