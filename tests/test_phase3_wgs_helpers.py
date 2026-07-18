import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import analyze_hrd
from diana_omics.commands import fetch_phase3_wgs_smoke_assets as fetch_phase3
from diana_omics.commands import run_phase3_wgs_smoke as phase3


class Phase3WgsHelpersTest(unittest.TestCase):
    def test_alignment_thread_plan_defaults_and_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(phase3.alignment_thread_plan(64), (64, 64))
        with patch.dict(os.environ, {"PHASE3_WGS_BWA_THREADS": "48", "PHASE3_WGS_SORT_THREADS": "8"}, clear=True):
            self.assertEqual(phase3.alignment_thread_plan(64), (48, 8))
        with patch.dict(os.environ, {"PHASE3_WGS_BWA_THREADS": "0", "PHASE3_WGS_SORT_THREADS": "0"}, clear=True):
            self.assertEqual(phase3.alignment_thread_plan(64), (64, 64))
        with patch.dict(os.environ, {"PHASE3_WGS_BWA_THREADS": "-1"}, clear=True):
            with self.assertRaises(ValueError):
                phase3.alignment_thread_plan(64)

    def test_bam_validation_mode_controls_stats_and_cache_group(self):
        with patch.object(phase3, "BAM_VALIDATION_MODE", "full"):
            self.assertTrue(phase3.bam_stats_enabled())
            self.assertEqual(phase3.bam_validation_cache_group(), "bam_validation")
        with patch.object(phase3, "BAM_VALIDATION_MODE", "flagstat_only"):
            self.assertFalse(phase3.bam_stats_enabled())
            self.assertEqual(phase3.bam_validation_cache_group(), "bam_validation_flagstat_only")

    def test_coverage_cnv_mode_controls_cache_group(self):
        with patch.object(phase3, "COVERAGE_CNV_MODE", "full"):
            self.assertEqual(phase3.coverage_cnv_cache_group(), "coverage_cnv")
        with patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"):
            self.assertEqual(phase3.coverage_cnv_cache_group(), "coverage_cnv_metadata")

    def test_downstream_can_skip_bam_hydration_only_for_public_bam_timing_fast_modes(self):
        row = {"production_caller": "skipped_for_public_bam_timing"}
        with patch.object(phase3, "BAM_VALIDATION_MODE", "flagstat_only"), patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"):
            self.assertTrue(phase3.downstream_can_skip_bam_hydration(row))
        with patch.object(phase3, "BAM_VALIDATION_MODE", "full"), patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"):
            self.assertFalse(phase3.downstream_can_skip_bam_hydration(row))
        with patch.object(phase3, "BAM_VALIDATION_MODE", "flagstat_only"), patch.object(phase3, "COVERAGE_CNV_MODE", "full"):
            self.assertFalse(phase3.downstream_can_skip_bam_hydration(row))
        with patch.object(phase3, "BAM_VALIDATION_MODE", "flagstat_only"), patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"):
            self.assertFalse(phase3.downstream_can_skip_bam_hydration({"production_caller": "GATK Mutect2 + FilterMutectCalls"}))

    def test_downstream_timing_mode_does_not_materialize_alignments(self):
        row = {"production_caller": "skipped_for_public_bam_timing"}
        with patch.object(phase3, "BAM_VALIDATION_MODE", "flagstat_only"), patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"):
            self.assertFalse(phase3.alignment_materialization_required_for_stage("downstream", row))
            self.assertTrue(phase3.alignment_materialization_required_for_stage("all", row))
        with patch.object(phase3, "BAM_VALIDATION_MODE", "full"), patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"):
            self.assertTrue(phase3.alignment_materialization_required_for_stage("downstream", row))

    def test_phase3_completion_accepts_public_bam_timing_contract(self):
        row = {"production_caller": "skipped_for_public_bam_timing"}
        self.assertTrue(
            phase3.phase3_completion_status(
                row,
                bam_status="passed",
                mutect_status="skipped_public_bam_timing",
                cnv_status="passed",
                signature_status="skipped_public_bam_timing",
                sv_rows=[{"status": "passed"}],
            )
        )
        self.assertFalse(
            phase3.phase3_completion_status(
                row,
                bam_status="passed",
                mutect_status="passed",
                cnv_status="passed",
                signature_status="passed",
                sv_rows=[{"status": "passed"}],
            )
        )

    def test_phase3_completion_production_contract_requires_real_outputs(self):
        row = {"production_caller": "GATK Mutect2 + FilterMutectCalls"}
        self.assertTrue(
            phase3.phase3_completion_status(
                row,
                bam_status="passed",
                mutect_status="passed",
                cnv_status="passed",
                signature_status="passed",
                sv_rows=[{"status": "passed"}],
            )
        )
        self.assertFalse(
            phase3.phase3_completion_status(
                row,
                bam_status="passed",
                mutect_status="skipped_public_bam_timing",
                cnv_status="passed",
                signature_status="skipped_public_bam_timing",
                sv_rows=[{"status": "passed"}],
            )
        )

    def test_sbs96_rows_cover_expected_matrix(self):
        rows = phase3.all_sbs96_rows()
        self.assertEqual(len(rows), 96)
        self.assertEqual(len({row["trinucleotide"] for row in rows}), 96)
        self.assertEqual({row["sample"] for row in rows}, {"HCC1395"})
        self.assertIn("A[C>A]A", {row["trinucleotide"] for row in rows})
        self.assertIn("T[T>G]T", {row["trinucleotide"] for row in rows})

    def test_java_probe_decodes_invalid_native_version_bytes_with_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            java = Path(temporary) / "java"
            java.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch.object(
                fetch_phase3.subprocess,
                "run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=b"\xff",
                    stderr=b'openjdk version "17.0.15"\n',
                ),
            ) as run:
                self.assertTrue(fetch_phase3.java_works(str(java)))

        run.assert_called_once_with(
            [str(java), "-version"],
            stdout=fetch_phase3.subprocess.PIPE,
            stderr=fetch_phase3.subprocess.PIPE,
            check=False,
        )

    def test_normalized_context_keeps_pyrimidine_orientation(self):
        self.assertEqual(
            phase3.normalized_context("ACA", "C", "T"),
            {"mutationType": "C>T", "trinucleotide": "A[C>T]A"},
        )
        self.assertEqual(
            phase3.normalized_context("AGT", "G", "A"),
            {"mutationType": "C>T", "trinucleotide": "A[C>T]T"},
        )
        self.assertIsNone(phase3.normalized_context("NNN", "C", "A"))

    def test_parse_vcf_sample_names_uses_native_adapter_when_available(self):
        with patch.object(phase3, "vcf_sample_names", return_value=["tumor", "normal"]), patch.object(phase3, "capture_command") as capture:
            self.assertEqual(phase3.parse_vcf_sample_names("calls.vcf.gz"), ["tumor", "normal"])
        capture.assert_not_called()

    def test_alignment_thread_plan_allows_split_bwa_and_sort_threads(self):
        with patch.dict(os.environ, {"PHASE3_WGS_BWA_THREADS": "12", "PHASE3_WGS_SORT_THREADS": "4"}, clear=False):
            self.assertEqual(phase3.alignment_thread_plan(16), (12, 4))
        with patch.dict(os.environ, {"PHASE3_WGS_BWA_THREADS": "0", "PHASE3_WGS_SORT_THREADS": ""}, clear=False):
            self.assertEqual(phase3.alignment_thread_plan(16), (16, 16))

    def test_write_intervals_merges_and_sorts_by_reference_order(self):
        variants = [
            {"contig": "chr17", "position": 200},
            {"contig": "chr13", "position": 100},
            {"contig": "chr13", "position": 120},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intervals_path = "intervals/phase3.bed"
            with patch.object(phase3, "INTERVAL_PADDING", 10), patch.object(phase3, "path_from_root", lambda relative: root / relative):
                rows = phase3.write_intervals(variants, {"chr13": 0, "chr17": 1}, intervals_path)
            self.assertEqual(rows, [{"contig": "chr13", "start": 89, "end": 130}, {"contig": "chr17", "start": 189, "end": 210}])
            self.assertEqual(utils.read_text(root / intervals_path).splitlines(), ["chr13\t89\t130", "chr17\t189\t210"])

    def test_pick_covered_truth_variants_filters_by_depth(self):
        variants = [
            {"key": "a", "contig": "chr1", "position": 10, "ref": "A", "alt": "C", "type": "snv"},
            {"key": "b", "contig": "chr1", "position": 11, "ref": "G", "alt": "T", "type": "snv"},
        ]
        with patch.object(phase3, "MIN_TRUTH_DEPTH", 2), patch.object(phase3, "MAX_TRUTH_VARIANTS", 10):
            rows = phase3.pick_covered_truth_variants(variants, "chr1\t10\t2\t9\nchr1\t11\t1\t8\n")
        self.assertEqual([row["key"] for row in rows], ["a"])
        self.assertEqual(rows[0]["minDepth"], 2)

    def test_reusable_bam_validation_rows_accepts_matching_passed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tumor.bam").write_text("bam", encoding="utf-8")
            (root / "tumor.bam.bai").write_text("bai", encoding="utf-8")
            rows = [{"role": "tumor", "run_accession": "SRR1", "output_bam": "tumor.bam", "output_bai": "tumor.bam.bai"}]
            utils.write_json(
                root / phase3.bam_validation_summary_path(),
                {
                    "status": "passed",
                    "rows": [
                        {
                            "role": "tumor",
                            "run_accession": "SRR1",
                            "output_bam": "tumor.bam",
                            "bam_size_bytes": 3,
                            "status": "passed",
                        }
                    ],
                },
            )
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "REUSE_BAM_VALIDATION", True),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "quickcheck_bam", return_value=True),
            ):
                reusable = phase3.reusable_bam_validation_rows(rows)
        self.assertIsNotNone(reusable)
        assert reusable is not None
        self.assertEqual(reusable[0]["validation_cache"], "reused")

    def test_reusable_bam_validation_rows_rejects_wrong_bam(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tumor.bam").write_text("bam", encoding="utf-8")
            (root / "tumor.bam.bai").write_text("bai", encoding="utf-8")
            rows = [{"role": "tumor", "run_accession": "SRR1", "output_bam": "tumor.bam", "output_bai": "tumor.bam.bai"}]
            utils.write_json(
                root / phase3.bam_validation_summary_path(),
                {"status": "passed", "rows": [{"role": "tumor", "run_accession": "SRR1", "output_bam": "other.bam", "status": "passed"}]},
            )
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "REUSE_BAM_VALIDATION", True),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "quickcheck_bam", return_value=True),
            ):
                self.assertIsNone(phase3.reusable_bam_validation_rows(rows))

    def test_reusable_bam_validation_rows_rejects_wrong_validation_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tumor.bam").write_text("bam", encoding="utf-8")
            (root / "tumor.bam.bai").write_text("bai", encoding="utf-8")
            rows = [{"role": "tumor", "run_accession": "SRR1", "output_bam": "tumor.bam", "output_bai": "tumor.bam.bai"}]
            utils.write_json(
                root / phase3.bam_validation_summary_path(),
                {
                    "status": "passed",
                    "bamValidationMode": "flagstat_only",
                    "rows": [{"role": "tumor", "run_accession": "SRR1", "output_bam": "tumor.bam", "status": "passed"}],
                },
            )
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "REUSE_BAM_VALIDATION", True),
                patch.object(phase3, "BAM_VALIDATION_MODE", "full"),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "quickcheck_bam", return_value=True),
            ):
                self.assertIsNone(phase3.reusable_bam_validation_rows(rows))

    def test_reusable_bam_validation_rows_can_skip_bam_presence_for_timing_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [{"role": "tumor", "run_accession": "SRR1", "output_bam": "tumor.bam", "output_bai": "tumor.bam.bai"}]
            utils.write_json(
                root / phase3.bam_validation_summary_path(),
                {
                    "status": "passed",
                    "rows": [
                        {
                            "role": "tumor",
                            "run_accession": "SRR1",
                            "output_bam": "tumor.bam",
                            "bam_size_bytes": 100,
                            "status": "passed",
                        }
                    ],
                },
            )
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "REUSE_BAM_VALIDATION", True),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "quickcheck_bam") as quickcheck,
            ):
                reusable = phase3.reusable_bam_validation_rows(rows, require_bams=False)
        quickcheck.assert_not_called()
        self.assertIsNotNone(reusable)
        assert reusable is not None
        self.assertEqual(reusable[0]["validation_cache"], "reused_no_bam_hydration")

    def test_restore_cached_outputs_can_skip_mtime_currentness_for_validated_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            newer_input = root / "tumor.bam"
            newer_input.write_text("bam", encoding="utf-8")

            def restore(_aws: str, _uri: str, output: Path, _checksum: object, _label: str) -> None:
                utils.write_text(output, "cached\n")
                os.utime(output, (newer_input.stat().st_mtime - 10, newer_input.stat().st_mtime - 10))

            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
                patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
                patch.object(fetch_phase3, "s3_object_size", return_value=10),
                patch.object(fetch_phase3, "restore_cached_asset", side_effect=restore),
            ):
                self.assertTrue(
                    phase3.restore_cached_outputs(
                        ["results/phase3_wgs_smoke/bam_validation_summary.json"],
                        {"results/phase3_wgs_smoke/bam_validation_summary.json": "s3://cache/summary.json"},
                        ["tumor.bam"],
                        "pair.bam_validation",
                        require_current=False,
                    )
                )
            self.assertEqual(utils.read_text(root / "results/phase3_wgs_smoke/bam_validation_summary.json"), "cached\n")

    def test_alignment_flag_counts_reuses_flagstat_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {"reference_id": "ref", "run_accession": "SRR1", "output_bam": "tumor.bam"}
            utils.write_text(
                root / "results/phase3_wgs_smoke/logs/ref.SRR1.flagstat.txt",
                "\n".join(
                    [
                        "100 + 0 in total (QC-passed reads + QC-failed reads)",
                        "100 + 0 primary",
                        "90 + 0 mapped (90.00% : N/A)",
                        "90 + 0 primary mapped (90.00% : N/A)",
                        "80 + 0 properly paired (80.00% : N/A)",
                    ]
                ),
            )
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "count") as count,
            ):
                self.assertEqual(phase3.alignment_flag_counts("ref", row), {"total": 100, "mapped": 90, "properly_paired": 80})
            count.assert_not_called()

    def test_alignment_flag_counts_uses_threaded_flagstat_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {"reference_id": "ref", "role": "tumor", "run_accession": "SRR1", "output_bam": "tumor.bam", "output_bai": "tumor.bam.bai"}
            flagstat = "\n".join(
                [
                    "100 + 0 in total (QC-passed reads + QC-failed reads)",
                    "90 + 0 mapped (90.00% : N/A)",
                    "80 + 0 properly paired (80.00% : N/A)",
                ]
            )
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "BAM_SCAN_THREADS", 8),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "run_cached_command", return_value=flagstat) as run,
            ):
                self.assertEqual(phase3.alignment_flag_counts("ref", row), {"total": 100, "mapped": 90, "properly_paired": 80})
            run.assert_called_once_with(
                "samtools flagstat -@ 8 'tumor.bam'",
                "results/phase3_wgs_smoke/logs/ref.SRR1.flagstat.txt",
                ["tumor.bam", "tumor.bam.bai"],
                "",
                "tumor.flagstat",
                require_current=False,
            )

    def test_build_coverage_cnv_reuses_current_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["bins.bed", "tumor.bam", "tumor.bam.bai", "normal.bam", "normal.bam.bai"]:
                utils.write_text(root / path, path)
            utils.write_text(root / "results/phase3_wgs_smoke/coverage_cnv_bins.csv", "contig,start,end\nchr1,0,10\n")
            utils.write_text(root / "results/phase3_wgs_smoke/coverage_cnv_summary.csv", "status,bin_count\npassed,1\n")
            utils.write_json(
                root / "results/phase3_wgs_smoke/coverage_cnv_summary.json",
                {"status": "passed", "rows": [{"status": "passed", "bin_count": 1}]},
            )
            tumor = {"output_bam": "tumor.bam", "output_bai": "tumor.bam.bai"}
            normal = {"output_bam": "normal.bam", "output_bai": "normal.bam.bai"}
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "capture_allow_empty") as capture,
            ):
                summary = phase3.build_coverage_cnv(tumor, normal, "bins.bed")
        capture.assert_not_called()
        self.assertEqual(summary["cnv_cache"], "reused")

    def test_build_coverage_cnv_metadata_mode_skips_bedcov(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["bins.bed", "tumor.bam", "tumor.bam.bai", "normal.bam", "normal.bam.bai"]:
                utils.write_text(root / path, path)
            tumor = {"output_bam": "tumor.bam", "output_bai": "tumor.bam.bai", "pair_id": "pair1", "read_pairs_per_end": "full"}
            normal = {"output_bam": "normal.bam", "output_bai": "normal.bam.bai", "run_accession": "normal"}
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "run_cached_output_command") as run,
                patch.object(phase3, "publish_cached_outputs", return_value=3),
            ):
                summary = phase3.build_coverage_cnv(tumor, normal, "bins.bed")
                summary_json = utils.read_json(root / "results/phase3_wgs_smoke/coverage_cnv_summary.json")
        run.assert_not_called()
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["tool"], "metadata_only")
        self.assertEqual(summary["coverage_cnv_mode"], "metadata")
        self.assertEqual(summary["bin_count"], 0)
        self.assertIn("coverageCnvMode", summary_json)

    def test_downstream_can_skip_bam_hydration_for_idxstats_public_bam_timing(self):
        row = {"production_caller": "skipped_for_public_bam_timing"}
        with (
            patch.object(phase3, "BAM_VALIDATION_MODE", "flagstat_only"),
            patch.object(phase3, "COVERAGE_CNV_MODE", "idxstats"),
        ):
            self.assertFalse(phase3.alignment_materialization_required_for_stage("downstream", row))

    def test_build_coverage_cnv_idxstats_mode_skips_bedcov(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["bins.bed", "tumor.bam", "tumor.bam.bai", "normal.bam", "normal.bam.bai"]:
                utils.write_text(root / path, path)
            tumor = {
                "output_bam": "tumor.bam",
                "output_bai": "tumor.bam.bai",
                "pair_id": "pair1",
                "read_pairs_per_end": "full",
                "reference_id": "ref",
                "role": "tumor",
                "run_accession": "tumor",
            }
            normal = {
                "output_bam": "normal.bam",
                "output_bai": "normal.bam.bai",
                "pair_id": "pair1",
                "read_pairs_per_end": "full",
                "reference_id": "ref",
                "role": "normal",
                "run_accession": "normal",
            }
            utils.write_text(root / phase3.alignment_idxstats_path(tumor), "chr1\t1000\t100\t0\nchr2\t1000\t100\t0\n*\t0\t0\t0\n")
            utils.write_text(root / phase3.alignment_idxstats_path(normal), "chr1\t1000\t50\t0\nchr2\t1000\t150\t0\n*\t0\t0\t0\n")
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "COVERAGE_CNV_MODE", "idxstats"),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "run_cached_output_command") as run,
                patch.object(phase3, "publish_cached_outputs", return_value=3),
            ):
                summary = phase3.build_coverage_cnv(tumor, normal, "bins.bed")
                bins = utils.parse_csv(utils.read_text(root / "results/phase3_wgs_smoke/coverage_cnv_bins.csv"))
        run.assert_not_called()
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["tool"], "samtools idxstats")
        self.assertEqual(summary["coverage_cnv_mode"], "idxstats")
        self.assertEqual(summary["bin_count"], 2)
        self.assertEqual(bins[0]["contig"], "chr1")
        self.assertEqual(bins[0]["coverage_class"], "relative_gain")

    def test_build_coverage_cnv_idxstats_mode_accepts_cached_command_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["bins.bed", "tumor.bam", "tumor.bam.bai", "normal.bam", "normal.bam.bai"]:
                utils.write_text(root / path, path)
            tumor = {
                "output_bam": "tumor.bam",
                "output_bai": "tumor.bam.bai",
                "pair_id": "pair1",
                "read_pairs_per_end": "full",
                "reference_id": "ref",
                "role": "tumor",
                "run_accession": "tumor",
            }
            normal = {
                "output_bam": "normal.bam",
                "output_bai": "normal.bam.bai",
                "pair_id": "pair1",
                "read_pairs_per_end": "full",
                "reference_id": "ref",
                "role": "normal",
                "run_accession": "normal",
            }
            utils.write_text(
                root / phase3.alignment_idxstats_path(tumor),
                "$ samtools idxstats tumor.bam\n\n## stdout\nchr1\t1000\t100\t0\n*\t0\t0\t0\n",
            )
            utils.write_text(
                root / phase3.alignment_idxstats_path(normal),
                "$ samtools idxstats normal.bam\n\n## stdout\nchr1\t1000\t50\t0\n*\t0\t0\t0\n",
            )
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "COVERAGE_CNV_MODE", "idxstats"),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "run_cached_output_command") as run,
                patch.object(phase3, "publish_cached_outputs", return_value=3),
            ):
                summary = phase3.build_coverage_cnv(tumor, normal, "bins.bed")
        run.assert_not_called()
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["bin_count"], 1)

    def test_build_coverage_cnv_full_mode_shards_bedcov_by_contig(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["tumor.bam", "tumor.bam.bai", "normal.bam", "normal.bam.bai"]:
                utils.write_text(root / path, path)
            utils.write_text(root / "bins.bed", "chr1\t0\t10\nchr1\t10\t20\nchr2\t0\t10\n")
            tumor = {
                "output_bam": "tumor.bam",
                "output_bai": "tumor.bam.bai",
                "pair_id": "pair1",
                "read_pairs_per_end": "full",
                "reference_id": "ref",
                "role": "tumor",
            }
            normal = {
                "output_bam": "normal.bam",
                "output_bai": "normal.bam.bai",
                "pair_id": "pair1",
                "read_pairs_per_end": "full",
                "reference_id": "ref",
                "role": "normal",
            }

            def fake_parallel(commands, workers):
                self.assertEqual(workers, 2)
                self.assertEqual(len(commands), 2)
                for command, _log in commands:
                    if "chr1.bedcov.tsv" in command:
                        utils.write_text(
                            root / "results/phase3_wgs_smoke/coverage_cnv_bedcov_shards/chr1.bedcov.tsv",
                            "chr1\t0\t10\t100\t50\nchr1\t10\t20\t80\t80\n",
                        )
                    elif "chr2.bedcov.tsv" in command:
                        utils.write_text(
                            root / "results/phase3_wgs_smoke/coverage_cnv_bedcov_shards/chr2.bedcov.tsv",
                            "chr2\t0\t10\t20\t40\n",
                        )
                    else:
                        self.fail(f"unexpected bedcov command: {command}")
                return ["", ""]

            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "COVERAGE_CNV_MODE", "full"),
                patch.object(phase3, "CNV_BEDCOV_WORKERS", 2),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "restore_cached_output", return_value=False),
                patch.object(phase3, "publish_cached_output", return_value=True),
                patch.object(phase3, "publish_cached_outputs", return_value=3),
                patch.object(phase3, "run_commands_parallel", side_effect=fake_parallel) as run_parallel,
                patch.object(phase3, "run_cached_output_command") as run_single,
            ):
                summary = phase3.build_coverage_cnv(tumor, normal, "bins.bed")
                bedcov = utils.read_text(root / "results/phase3_wgs_smoke/coverage_cnv_bedcov.tsv")
        run_parallel.assert_called_once()
        run_single.assert_not_called()
        self.assertIn("chr1\t0\t10\t100\t50", bedcov)
        self.assertIn("chr2\t0\t10\t20\t40", bedcov)
        self.assertEqual(summary["tool"], "samtools bedcov")
        self.assertEqual(summary["coverage_cnv_mode"], "full")
        self.assertEqual(summary["bin_count"], 3)

    def test_build_bins_keeps_current_file_timestamp_when_content_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_text(root / "ref.fa.fai", "chr1\t10\t0\t10\t11\nchrUn\t20\t0\t20\t21\n")
            with (
                patch.object(phase3, "BIN_SIZE", 5),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
            ):
                rows = phase3.build_bins("ref.fa.fai", "bins.bed")
                os.utime(root / "bins.bed", (1000, 1000))
                phase3.build_bins("ref.fa.fai", "bins.bed")
                bins_mtime = (root / "bins.bed").stat().st_mtime
        self.assertEqual(rows, [{"contig": "chr1", "start": 0, "end": 5}, {"contig": "chr1", "start": 5, "end": 10}])
        self.assertEqual(bins_mtime, 1000)

    def test_truth_depth_text_reuses_current_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["truth.bed", "tumor.bam", "tumor.bam.bai", "normal.bam", "normal.bam.bai"]:
                utils.write_text(root / path, path)
            utils.write_text(root / phase3.truth_depth_path(), "chr1\t10\t2\t3\n")
            tumor = {"output_bam": "tumor.bam", "output_bai": "tumor.bam.bai"}
            normal = {"output_bam": "normal.bam", "output_bai": "normal.bam.bai"}
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "run_command") as run,
            ):
                depth = phase3.truth_depth_text(tumor, normal, "truth.bed", "ref")
        run.assert_not_called()
        self.assertEqual(depth, "chr1\t10\t2\t3\n")

    def test_run_mutect2_call_reuses_current_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["tumor.bam", "tumor.bam.bai", "normal.bam", "normal.bam.bai", "ref.fa", "intervals.bed"]:
                utils.write_text(root / path, path)
                os.utime(root / path, (1000, 1000))
            for path in ["unfiltered.vcf.gz", "unfiltered.vcf.gz.tbi"]:
                utils.write_text(root / path, path)
                os.utime(root / path, (2000, 2000))
            tumor = {
                "output_bam": "tumor.bam",
                "output_bai": "tumor.bam.bai",
                "reference_path": "ref.fa",
                "reference_id": "ref",
                "read_pairs_per_end": "100",
                "role": "tumor",
                "pair_id": "pair",
            }
            normal = {
                "output_bam": "normal.bam",
                "output_bai": "normal.bam.bai",
                "reference_id": "ref",
                "read_pairs_per_end": "100",
                "role": "normal",
                "pair_id": "pair",
            }
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "restore_cached_outputs") as restore,
                patch.object(phase3, "run_command") as run,
            ):
                phase3.run_mutect2_call(tumor, normal, "intervals.bed", "unfiltered.vcf.gz", "f1r2.tar.gz", "ref", "")
        restore.assert_not_called()
        run.assert_not_called()

    def test_run_filter_mutect_calls_reuses_current_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["unfiltered.vcf.gz", "unfiltered.vcf.gz.tbi", "ref.fa"]:
                utils.write_text(root / path, path)
                os.utime(root / path, (1000, 1000))
            for path in ["filtered.vcf.gz", "filtered.vcf.gz.tbi"]:
                utils.write_text(root / path, path)
                os.utime(root / path, (2000, 2000))
            tumor = {
                "java_path": "java",
                "gatk_jar_path": "gatk.jar",
                "reference_path": "ref.fa",
                "reference_id": "ref",
                "read_pairs_per_end": "100",
                "role": "tumor",
                "pair_id": "pair",
            }
            normal = {"reference_id": "ref", "read_pairs_per_end": "100", "role": "normal", "pair_id": "pair"}
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "restore_cached_outputs") as restore,
                patch.object(phase3, "run_command") as run,
            ):
                phase3.run_filter_mutect_calls(tumor, normal, "unfiltered.vcf.gz", "filtered.vcf.gz", "ref")
        restore.assert_not_called()
        run.assert_not_called()

    def test_write_filtered_vcf_stats_uses_pair_cache(self):
        tumor = {"reference_id": "ref", "read_pairs_per_end": "100", "role": "tumor", "pair_id": "pair"}
        normal = {"reference_id": "ref", "read_pairs_per_end": "100", "role": "normal", "pair_id": "pair"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["filtered.vcf.gz", "filtered.vcf.gz.tbi"]:
                utils.write_text(root / path, path)
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(phase3, "run_cached_command") as run,
            ):
                phase3.write_filtered_vcf_stats(tumor, normal, "filtered.vcf.gz", "results/phase3_wgs_smoke/logs/ref.stats.txt")
        run.assert_called_once_with(
            "bcftools stats 'filtered.vcf.gz'",
            "results/phase3_wgs_smoke/logs/ref.stats.txt",
            ["filtered.vcf.gz", "filtered.vcf.gz.tbi"],
            "s3://cache/phase3_wgs/validation/ref/100/pair/pair/filter_mutect_calls/results__phase3_wgs_smoke__logs__ref.stats.txt",
            "pair.filter_mutect_calls.stats",
        )

    def test_build_sbs96_matrix_reuses_current_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["filtered.vcf.gz", "filtered.vcf.gz.tbi", "ref.fa", "ref.fa.fai"]:
                utils.write_text(root / path, path)
                os.utime(root / path, (1000, 1000))
            utils.write_text(root / "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv", "sample,mutation_type,trinucleotide,count\n")
            utils.write_text(root / "results/phase3_wgs_smoke/signature_assignment_summary.csv", "status,usable_snv_records\npassed,0\n")
            utils.write_json(
                root / "results/phase3_wgs_smoke/signature_assignment_summary.json",
                {"status": "passed", "rows": [{"status": "passed", "usable_snv_records": 0, "sigprofiler_assignment_status": "cached"}]},
            )
            for path in [
                "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
                "results/phase3_wgs_smoke/signature_assignment_summary.csv",
                "results/phase3_wgs_smoke/signature_assignment_summary.json",
            ]:
                os.utime(root / path, (2000, 2000))
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "reference_context") as context,
            ):
                summary = phase3.build_sbs96_matrix("filtered.vcf.gz", "ref.fa")
        context.assert_not_called()
        self.assertEqual(summary["sbs96_cache"], "reused")
        self.assertEqual(summary["sigprofiler_assignment_status"], "cached")

    def test_build_sv_evidence_scans_each_bam_once(self):
        class FakeProcess:
            def __init__(self, output: str):
                self.stdout = StringIO(output)
                self.stderr = StringIO("")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def wait(self):
                return 0

        sam_lines = "\n".join(
            [
                "read1\t2048\tchr1\t10\t60\t50M\t=\t20\t10\tACGT\tFFFF",
                "read2\t1\tchr1\t20\t60\t50M\tchr2\t30\t0\tACGT\tFFFF",
                "read3\t1\tchr1\t30\t60\t50M\t=\t40\t100001\tACGT\tFFFF",
                "read4\t15\tchr1\t40\t60\t50M\t=\t50\t10\tACGT\tFFFF",
            ]
        )
        row = {"sample": "sample", "role": "tumor", "run_accession": "SRR1", "output_bam": "tumor.bam"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "indexed_alignment_count", return_value=4),
                patch.object(phase3.subprocess, "Popen", return_value=FakeProcess(sam_lines)) as popen,
            ):
                summary = phase3.build_sv_evidence([row])
        popen.assert_called_once()
        self.assertEqual(summary[0]["total_alignments"], 4)
        self.assertEqual(summary[0]["supplementary_alignments"], 1)
        self.assertEqual(summary[0]["discordant_mapped_pairs"], 2)
        self.assertEqual(summary[0]["interchromosomal_pairs"], 1)
        self.assertEqual(summary[0]["large_insert_pairs"], 1)
        self.assertEqual(summary[0]["sv_candidate_rows_written"], 2)

    def test_build_sv_evidence_reuses_current_outputs(self):
        row = {
            "sample": "sample",
            "role": "tumor",
            "run_accession": "SRR1",
            "output_bam": "tumor.bam",
            "output_bai": "tumor.bam.bai",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ["tumor.bam", "tumor.bam.bai"]:
                utils.write_text(root / path, path)
                os.utime(root / path, (1000, 1000))
            utils.write_text(root / "results/phase3_wgs_smoke/sv_evidence_candidates.csv", "sample,role\n")
            utils.write_text(root / "results/phase3_wgs_smoke/sv_evidence_summary.csv", "status,role\npassed,tumor\n")
            utils.write_json(
                root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
                {
                    "status": "passed",
                    "rows": [
                        {
                            "status": "passed",
                            "sample": "sample",
                            "role": "tumor",
                            "run_accession": "SRR1",
                            "input_bam": "tumor.bam",
                        }
                    ],
                },
            )
            for path in [
                "results/phase3_wgs_smoke/sv_evidence_candidates.csv",
                "results/phase3_wgs_smoke/sv_evidence_summary.csv",
                "results/phase3_wgs_smoke/sv_evidence_summary.json",
            ]:
                os.utime(root / path, (2000, 2000))
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "indexed_alignment_count") as indexed,
                patch.object(phase3.subprocess, "Popen") as popen,
            ):
                summary = phase3.build_sv_evidence([row])
        indexed.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(summary[0]["sv_cache"], "reused")

    def test_build_sv_evidence_metadata_mode_skips_bam_scan(self):
        rows = [
            {
                "sample": "tumor",
                "role": "tumor",
                "run_accession": "SRR1",
                "output_bam": "tumor.bam",
                "output_bai": "tumor.bam.bai",
                "production_caller": "skipped_for_public_bam_timing",
                "fastq_1": "data/raw/phase3/fastq/SRR1_R1.full.fastq.gz",
                "reference_id": "ref",
                "pair_id": "pair",
                "read_pairs_per_end": "full",
            },
            {
                "sample": "normal",
                "role": "normal",
                "run_accession": "SRR2",
                "output_bam": "normal.bam",
                "output_bai": "normal.bam.bai",
                "production_caller": "skipped_for_public_bam_timing",
                "fastq_1": "data/raw/phase3/fastq/SRR2_R1.full.fastq.gz",
                "reference_id": "ref",
                "pair_id": "pair",
                "read_pairs_per_end": "full",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(phase3, "BAM_VALIDATION_MODE", "flagstat_only"),
                patch.object(phase3, "COVERAGE_CNV_MODE", "metadata"),
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "indexed_alignment_count") as indexed,
                patch.object(phase3.subprocess, "Popen") as popen,
            ):
                summary = phase3.build_sv_evidence(rows)
        indexed.assert_not_called()
        popen.assert_not_called()
        self.assertEqual([row["tool"] for row in summary], ["metadata_only", "metadata_only"])
        self.assertEqual(summary[0]["sv_cache"], "metadata_only_no_bam_hydration")

    def test_phase3_fetch_full_mode_uses_source_spots(self):
        with patch.object(fetch_phase3, "READ_PAIRS_LIMIT", None):
            self.assertEqual(fetch_phase3.expected_read_pairs({"spots": "12345"}), 12345)
            self.assertEqual(fetch_phase3.read_count_label(12345), "full")
        with patch.object(fetch_phase3, "READ_PAIRS_LIMIT", 500000):
            self.assertEqual(fetch_phase3.expected_read_pairs({"spots": "12345"}), 500000)
            self.assertEqual(fetch_phase3.read_count_label(500000), "500000reads")

    def test_sra_aws_uri_uses_configured_open_data_bucket(self):
        with patch.object(fetch_phase3, "SRA_AWS_BUCKET", "sra-pub-run-odp"):
            self.assertEqual(fetch_phase3.sra_aws_uri("SRR7890824"), "s3://sra-pub-run-odp/sra/SRR7890824/SRR7890824")

    def test_seqkit_n_fraction_tolerates_missing_sum_n(self):
        self.assertEqual(fetch_phase3.seqkit_n_fraction({"num_seqs": "2", "sum_len": "300"}, 300), 0)
        self.assertEqual(fetch_phase3.seqkit_n_fraction({"sum_n": "3"}, 300), 0.01)

    def test_aws_sra_full_scan_validation_method_does_not_claim_provider_md5(self):
        with patch.object(fetch_phase3, "SOURCE_MODE", "aws_sra"):
            self.assertEqual(fetch_phase3.full_scan_validation_method(), "seqkit_stats_full_scan_sra_spot_count_check")
        with patch.object(fetch_phase3, "SOURCE_MODE", "ena_fastq"):
            self.assertEqual(fetch_phase3.full_scan_validation_method(), "seqkit_stats_full_scan_with_exact_provider_md5")

    def test_public_bam_fetch_can_make_gatk_optional_for_timing_runs(self):
        with patch.object(fetch_phase3, "SOURCE_MODE", "public_bam"), patch.object(fetch_phase3, "REQUIRE_GATK_MODE", "auto"):
            self.assertFalse(fetch_phase3.require_gatk_assets())
        with patch.object(fetch_phase3, "SOURCE_MODE", "public_bam"), patch.object(fetch_phase3, "REQUIRE_GATK_MODE", "1"):
            self.assertTrue(fetch_phase3.require_gatk_assets())
        with patch.object(fetch_phase3, "SOURCE_MODE", "aws_sra"), patch.object(fetch_phase3, "REQUIRE_GATK_MODE", "auto"):
            self.assertTrue(fetch_phase3.require_gatk_assets())

    def test_phase3_asset_cache_uri_joins_paths(self):
        with patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://diana-omics-raw/cache/phase3_wgs"):
            self.assertEqual(
                fetch_phase3.cache_uri("/fastq/", "SRR7890824_R1.full.fastq.gz"),
                "s3://diana-omics-raw/cache/phase3_wgs/fastq/SRR7890824_R1.full.fastq.gz",
            )

    def test_alignment_cache_uri_uses_reference_read_label_and_role(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "output_bam": "data/raw/phase3/ref/full/bam/SRR7890824.tumor.bam",
            "output_bai": "data/raw/phase3/ref/full/bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }
        with patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://diana-omics-raw/cache/phase3_wgs"):
            self.assertEqual(
                phase3.alignment_cache_uris(row),
                (
                    "s3://diana-omics-raw/cache/phase3_wgs/bam/ucsc_hg38_analysis_set_full/full/tumor/SRR7890824.tumor.bam",
                    "s3://diana-omics-raw/cache/phase3_wgs/bam/ucsc_hg38_analysis_set_full/full/tumor/SRR7890824.tumor.bam.bai",
                ),
            )

    def test_cache_stream_alignment_uses_cached_fastq_fifos(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }
        with (
            patch.object(phase3, "ALIGN_INPUT_MODE", "cache_stream"),
            patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
            patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
            patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
            patch.object(fetch_phase3, "s3_object_size", side_effect=[10, 20]),
        ):
            command = phase3.align_command(row, 48, 8)
        self.assertIn("mkfifo", command)
        self.assertIn("'/usr/bin/aws' s3 cp --only-show-errors 's3://cache/phase3_wgs/fastq/SRR7890824_R1.full.fastq.gz' \"$r1\"", command)
        self.assertIn("'/usr/bin/aws' s3 cp --only-show-errors 's3://cache/phase3_wgs/fastq/SRR7890824_R2.full.fastq.gz' \"$r2\"", command)
        self.assertIn("bwa mem -t 48", command)
        self.assertIn("\"$r1\" \"$r2\" | samtools sort -@ 8", command)
        self.assertIn("cache_stream alignment failed", command)

    def test_cache_stream_alignment_can_use_bwa_mem2(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }
        with (
            patch.object(phase3, "ALIGNER", "bwa-mem2"),
            patch.object(phase3, "ALIGN_INPUT_MODE", "cache_stream"),
            patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
            patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
            patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
            patch.object(fetch_phase3, "s3_object_size", side_effect=[10, 20]),
        ):
            command = phase3.align_command(row, 48, 8)
        self.assertIn("bwa-mem2 mem -t 48", command)

    def test_cache_stream_alignment_can_use_minimap2_index(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }
        with (
            patch.object(phase3, "ALIGNER", "minimap2"),
            patch.object(phase3, "ALIGN_INPUT_MODE", "cache_stream"),
            patch.object(phase3, "path_from_root", side_effect=lambda value: Path("/tmp") / value),
            patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
            patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
            patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
            patch.object(fetch_phase3, "s3_object_size", side_effect=[10, 20]),
            patch.object(Path, "exists", return_value=True),
        ):
            command = phase3.align_command(row, 48, 8)
        self.assertIn("minimap2 -ax sr -t 48", command)
        self.assertIn("'refs/hg38.fa.mmi' \"$r1\" \"$r2\"", command)

    def test_fastq_shard_rows_distribute_expected_read_pairs_and_cache_uris(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "sample": "HCC1395",
            "read_pairs_per_end": "10",
        }
        with patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"):
            shards = phase3.fastq_shard_rows(row, 8)
        self.assertEqual([int(shard["expected_read_pairs"]) for shard in shards], [2, 2, 1, 1, 1, 1, 1, 1])
        self.assertEqual([(int(shard["spot_start"]), int(shard["spot_end"])) for shard in shards[:3]], [(1, 2), (3, 4), (5, 5)])
        self.assertEqual(shards[0]["shard_label"], "shard00of08")
        self.assertEqual(
            shards[0]["fastq_1_uri"],
            "s3://cache/phase3_wgs/fastq_shards/full/SRR7890824/8way/SRR7890824.shard00of08_R1.fastq.gz",
        )

    def test_prepare_fastq_shards_spot_range_mode_writes_manifest_without_splitting(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "sample": "HCC1395",
            "read_pairs_per_end": "10",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch.object(phase3, "ALIGN_INPUT_MODE", "cache_stream"),
                patch.object(phase3, "SHARD_INPUT_MODE", "sra_spot_range"),
                patch.object(phase3, "path_from_root", side_effect=lambda value: root / value),
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
                patch.object(fetch_phase3, "cache_writes_enabled", return_value=True),
                patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
                patch.object(phase3, "run_command", side_effect=AssertionError("spot-range prep should not split FASTQs")),
            ):
                phase3.prepare_fastq_shards(row, 8)

            manifest = root / phase3.fastq_shard_manifest_path(row, 8)
            marker = root / "results/phase3_wgs_smoke/stage_markers/shard_fastq_tumor.json"
            self.assertTrue(manifest.is_file())
            self.assertIn("spot_start,spot_end", manifest.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(phase3.read_json(marker)["status"], "spot_range_manifest")
            self.assertEqual(phase3.read_json(marker)["shardInputMode"], "sra_spot_range")

    def test_force_shard_alignment_bypasses_cached_bam_without_forcing_fastq_split(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "sample": "HCC1395",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/HCC1395.tumor.bam",
            "output_bai": "bam/HCC1395.tumor.bam.bai",
            "read_pairs_per_end": "8",
        }
        commands: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            def fake_run(command: str, _log_path: str) -> None:
                commands.append(command)
                bam_path = root / phase3.shard_bam_path(row, 0, 4)
                bam_path.parent.mkdir(parents=True, exist_ok=True)
                bam_path.write_bytes(b"bam")

            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "FORCE_SHARD_ALIGNMENT", True),
                patch.object(phase3, "ALIGN_INPUT_MODE", "cache_stream"),
                patch.object(phase3, "SHARD_INPUT_MODE", "fastq_cache"),
                patch.object(phase3, "ALIGNER", "minimap2"),
                patch.object(phase3, "path_from_root", side_effect=lambda value: root / value),
                patch.object(phase3, "require_cache_for_shards", return_value="/usr/bin/aws"),
                patch.object(phase3, "ensure_bwa_index"),
                patch.object(phase3, "run_command", side_effect=fake_run),
                patch.object(phase3, "quickcheck_bam", return_value=True),
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(fetch_phase3, "s3_object_size", side_effect=AssertionError("cached BAM should not be queried")),
                patch.object(fetch_phase3, "publish_cached_asset", return_value=True),
            ):
                phase3.align_and_publish_shard("ucsc_hg38_analysis_set_full", row, 0, 4)

            marker = root / "results/phase3_wgs_smoke/stage_markers/align_tumor_shard00of04.json"
            self.assertEqual(len(commands), 1)
            self.assertIn("minimap2 -ax sr", commands[0])
            self.assertTrue(phase3.read_json(marker)["forceShardAlignment"])

    def test_seqkit_split_shards_command_uses_fast_native_paired_split(self):
        command = phase3.seqkit_split_shards_command(
            Path("/tmp/input R1.fastq.gz"),
            Path("/tmp/input R2.fastq.gz"),
            Path("/tmp/shards"),
            "SRR7890824",
            8,
            8,
        )

        self.assertIn("seqkit split2 -j 8 -p 8", command)
        self.assertIn("-1 '/tmp/input R1.fastq.gz'", command)
        self.assertIn("-2 '/tmp/input R2.fastq.gz'", command)
        self.assertIn("-O '/tmp/shards'", command)
        self.assertNotIn("-P", command)
        self.assertIn("-e .gz -f", command)

    def test_seqkit_split_output_path_matches_split2_read_part_names(self):
        self.assertEqual(
            phase3.seqkit_split_output_path(Path("/tmp/shards"), "SRR7890824", 1, 0),
            Path("/tmp/shards/SRR7890824_R1.full.part_001.fastq.gz"),
        )
        self.assertEqual(
            phase3.seqkit_split_output_path(Path("/tmp/shards"), "SRR7890824", 2, 7),
            Path("/tmp/shards/SRR7890824_R2.full.part_008.fastq.gz"),
        )

    def test_align_shard_command_streams_shard_fastqs_and_bounds_sort_memory(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "10",
        }
        shard = {
            "shard_index": 0,
            "shard_count": 8,
            "fastq_1_uri": "s3://cache/phase3_wgs/fastq_shards/full/SRR7890824/8way/SRR7890824.shard00of08_R1.fastq.gz",
            "fastq_2_uri": "s3://cache/phase3_wgs/fastq_shards/full/SRR7890824/8way/SRR7890824.shard00of08_R2.fastq.gz",
        }
        with (
            patch.object(phase3, "ALIGNER", "minimap2"),
            patch.object(phase3, "ALIGN_INPUT_MODE", "cache_stream"),
            patch.object(phase3, "SORT_MEMORY", "1500M"),
            patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
            patch.object(fetch_phase3, "cache_writes_enabled", return_value=True),
            patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
        ):
            command = phase3.align_shard_command(row, shard, 24, 8)
        self.assertIn("minimap2 -ax sr -t 24", command)
        self.assertIn("SRR7890824.shard00of08_R1.fastq.gz", command)
        self.assertIn("samtools sort -@ 8 -m '1500M' -o 'bam/shards/SRR7890824.tumor.shard00of08.coord.bam' -", command)
        self.assertIn("cache_stream shard alignment failed", command)

    def test_align_shard_command_can_extract_sra_spot_ranges_without_fastq_shards(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "10",
        }
        shard = {
            "shard_index": 2,
            "shard_count": 8,
            "spot_start": 5,
            "spot_end": 5,
        }
        with (
            patch.object(phase3, "ALIGNER", "minimap2"),
            patch.object(phase3, "ALIGN_INPUT_MODE", "cache_stream"),
            patch.object(phase3, "SHARD_INPUT_MODE", "sra_spot_range"),
            patch.object(phase3, "SORT_MEMORY", "1500M"),
            patch.object(phase3, "path_from_root", side_effect=lambda value: Path("/tmp") / value),
            patch.object(fetch_phase3, "aws_sra_run_paths", return_value=("SRR7890824", Path("r1"), Path("r2"), Path("data/raw/phase3/sra/SRR7890824.sra"), Path("tmp"))),
            patch.object(fetch_phase3, "command_path", return_value="/usr/bin/fastq-dump"),
            patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
            patch.object(fetch_phase3, "cache_writes_enabled", return_value=True),
            patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
        ):
            command = phase3.align_shard_command(row, shard, 24, 8)
        self.assertIn("fastq-dump' --split-files --skip-technical -N 5 -X 5", command)
        self.assertIn("/tmp/data/raw/phase3/sra/SRR7890824.sra", command)
        self.assertIn("minimap2 -ax sr -t 24", command)
        self.assertIn("\"$r1\" \"$r2\"", command)
        self.assertIn("spot-range shard alignment failed", command)
        self.assertNotIn("fastq_shards", command)

    def test_ensure_sra_for_spot_range_uses_unsigned_open_data_fallback(self):
        row = {"run_accession": "SRR7890824"}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            commands: list[str] = []

            def capture_run(command: str, _log_path: str) -> str:
                commands.append(command)
                return ""

            with (
                patch.object(phase3, "path_from_root", side_effect=lambda value: root / value),
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
                patch.object(fetch_phase3, "cache_writes_enabled", return_value=True),
                patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
                patch.object(fetch_phase3, "aws_sra_run_paths", return_value=("SRR7890824", Path("r1"), Path("r2"), Path("data/raw/phase3/sra/SRR7890824.sra"), Path("tmp"))),
                patch.object(fetch_phase3, "s3_object_size", return_value=None),
                patch.object(phase3, "run_command", side_effect=capture_run),
            ):
                phase3.ensure_sra_for_spot_range(row)

        self.assertEqual(len(commands), 1)
        self.assertIn("s3 cp --no-sign-request --only-show-errors", commands[0])
        self.assertIn("s3://sra-pub-run-odp/sra/SRR7890824/SRR7890824", commands[0])

    def test_restore_cached_shard_bams_uses_alignment_cache_workers(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
        }
        restored: list[str] = []

        def fake_restore(_aws: str, _uri: str, target: Path, _expected: object, _label: str) -> bool:
            restored.append(target.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("bam", encoding="utf-8")
            return True

        with (
            patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
            patch.object(fetch_phase3, "cache_writes_enabled", return_value=True),
            patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
            patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
            patch.object(fetch_phase3, "restore_cached_asset", side_effect=fake_restore),
            patch.object(phase3, "ALIGNMENT_CACHE_WORKERS", 4),
            patch.object(phase3, "quickcheck_bam", return_value=True),
        ):
            paths = phase3.restore_cached_shard_bams(row, 4)

        self.assertEqual(len(paths), 4)
        self.assertEqual(len(restored), 4)

    def test_gather_shards_manifest_mode_skips_merge_and_writes_manifest(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "sample": "HCC1395",
            "run_accession": "SRR7890824",
            "output_bam": "bam/HCC1395.tumor.bam",
            "read_pairs_per_end": "8",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch.object(phase3, "SCATTER_OUTPUT_MODE", "shard_manifest"),
                patch.object(phase3, "path_from_root", side_effect=lambda value: root / value),
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(phase3, "require_cache_for_shards", return_value="/usr/bin/aws"),
                patch.object(fetch_phase3, "s3_object_size", return_value=123),
                patch.object(phase3, "run_command", side_effect=AssertionError("merge should not run")),
            ):
                phase3.gather_shards("ucsc_hg38_analysis_set_full", row, 4)

            manifest = root / phase3.shard_bam_manifest_path(row, 4)
            marker = root / "results/phase3_wgs_smoke/stage_markers/gather_tumor_4way.json"
            self.assertTrue(manifest.is_file())
            self.assertTrue(marker.is_file())
            self.assertIn("s3://cache/phase3_wgs/bam_shards", manifest.read_text(encoding="utf-8"))
            self.assertEqual(phase3.read_json(marker)["scatterOutputMode"], "shard_manifest")

    def test_cache_manifest_fastq_summary_uses_s3_sizes(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "source_fastq_1": "https://example.test/R1.fastq.gz",
            "source_fastq_2": "https://example.test/R2.fastq.gz",
            "run_accession": "SRR7890824",
            "read_pairs_per_end": "568040077",
            "source_bases": "171548103254",
        }
        with (
            patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
            patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
            patch.object(fetch_phase3, "s3_object_size", side_effect=[101, 202]),
        ):
            r1, r2, paired = fetch_phase3.summarize_paired_fastqs_from_cache_manifest(row)
        self.assertEqual(r1["source"], "cache_manifest")
        self.assertEqual(r1["bytes"], 101)
        self.assertEqual(r2["bytes"], 202)
        self.assertEqual(r1["firstReadId"], "not_collected_cache_manifest")
        self.assertEqual(paired["pairedIdCheck"], "not_checked_cache_manifest")

    def test_public_bam_panel_rows_preserve_bam_sample_and_source_counts(self):
        rows = fetch_phase3.public_bam_panel_rows()
        tumor = next(row for row in rows if row["role"] == "tumor")
        normal = next(row for row in rows if row["role"] == "normal")
        self.assertEqual(tumor["run"], "SRR7890833")
        self.assertEqual(tumor["bam_sample_name"], "WGS_EA_T_1")
        self.assertEqual(tumor["spots"], "942559447")
        self.assertTrue(tumor["source_bam_url"].endswith("/WGS_EA_T_1.bwa.dedup.bam"))
        self.assertEqual(normal["run"], "SRR7890832")
        self.assertEqual(normal["bam_sample_name"], "WGS_EA_N_1")
        self.assertEqual(normal["spots"], "870155991")

    def test_public_bam_fastq_summary_records_manifest_source(self):
        row = {
            "run_accession": "SRR7890833",
            "read_pairs_per_end": "942559447",
            "source_bases": "284652952994",
            "fastq_1": "data/raw/phase3/fastq/SRR7890833_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890833_R2.full.fastq.gz",
            "source_fastq_1": "s3://sra-pub-run-odp/sra/SRR7890833/SRR7890833#R1",
            "source_fastq_2": "s3://sra-pub-run-odp/sra/SRR7890833/SRR7890833#R2",
        }
        with patch.object(fetch_phase3, "SOURCE_MODE", "public_bam"):
            r1, r2, paired = fetch_phase3.summarize_paired_fastqs_from_public_bam(row)
        self.assertEqual(r1["source"], "public_bwa_mem_bam")
        self.assertEqual(r1["records"], 942559447)
        self.assertEqual(r2["validationMethod"], "public_bwa_mem_bam_manifest_sra_spot_count_check")
        self.assertEqual(paired["pairedIdCheck"], "not_checked_public_bam")

    def test_public_alignment_manifest_check_uses_md5_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = root / "tiny.bam"
            payload.write_bytes(b"public bam fixture")
            expected_md5 = "94e4cf2868db369e458c03db28d8288f"
            self.assertTrue(phase3.file_satisfies_public_manifest(payload, str(payload.stat().st_size), expected_md5))
            self.assertTrue((root / f"tiny.bam.{expected_md5}.md5ok").exists())
            payload.write_bytes(b"changed")
            self.assertFalse(phase3.file_satisfies_public_manifest(payload, "18", expected_md5))

    def test_public_bam_aria2_path_accepts_env_override(self):
        with (
            patch.dict(os.environ, {"PHASE3_WGS_ARIA2C": "/opt/bin/aria2c"}, clear=False),
            patch.object(fetch_phase3, "command_path", return_value=""),
            patch.object(Path, "is_file", return_value=True),
        ):
            self.assertEqual(phase3.public_bam_aria2_path(), "/opt/bin/aria2c")

    def test_public_bam_download_uses_split_aria2_when_available(self):
        row = {
            "role": "tumor",
            "reference_id": "ref",
            "run_accession": "SRR1",
            "source_bam_url": "https://example.test/sample.bam",
            "output_bam": "bam/sample.bam",
            "source_bam_md5": "abc",
            "source_bam_bytes": "123",
        }
        commands: list[str] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch.object(phase3, "PUBLIC_BAM_ARIA2_SPLIT", 8),
                patch.object(phase3, "path_from_root", side_effect=lambda value: root / value),
                patch.object(phase3, "public_bam_aria2_path", return_value="/usr/bin/aria2c"),
                patch.object(phase3, "file_satisfies_public_manifest", side_effect=[False, True]),
                patch.object(phase3, "run_command", side_effect=lambda command, log: commands.append(command)),
            ):
                phase3.download_public_alignment_file(
                    row, "bam", "source_bam_url", "output_bam", "source_bam_md5", "source_bam_bytes"
                )
        self.assertEqual(len(commands), 1)
        self.assertIn("/usr/bin/aria2c", commands[0])
        self.assertIn("--split=8", commands[0])
        self.assertNotIn("curl -L", commands[0])

    def test_public_bam_download_refuses_silent_curl_fallback_for_split_restore(self):
        row = {
            "role": "tumor",
            "reference_id": "ref",
            "run_accession": "SRR1",
            "source_bam_url": "https://example.test/sample.bam",
            "output_bam": "bam/sample.bam",
            "source_bam_md5": "abc",
            "source_bam_bytes": "123",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch.object(phase3, "PUBLIC_BAM_ARIA2_SPLIT", 8),
                patch.object(phase3, "path_from_root", side_effect=lambda value: root / value),
                patch.object(phase3, "public_bam_aria2_path", return_value=""),
                patch.object(phase3, "file_satisfies_public_manifest", return_value=False),
            ):
                with self.assertRaisesRegex(RuntimeError, "aria2c is unavailable"):
                    phase3.download_public_alignment_file(
                        row, "bam", "source_bam_url", "output_bam", "source_bam_md5", "source_bam_bytes"
                    )

    def test_alignment_profile_mem_only_skips_sort(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }
        with patch.object(phase3, "ALIGN_PROFILE_MODE", "mem_only"):
            command = phase3.align_command(row, 48, 8)
        self.assertIn("bwa mem -t 48", command)
        self.assertIn("> /dev/null", command)
        self.assertNotIn("samtools sort", command)

    def test_alignment_profile_unsorted_bam_uses_view_not_sort(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "data/raw/phase3/fastq/SRR7890824_R2.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": "refs/hg38.fa",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "read_group_id": "SRR7890824",
            "read_group_sample": "HCC1395",
            "read_group_library": "HCC1395",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }
        with patch.object(phase3, "ALIGN_PROFILE_MODE", "unsorted_bam"):
            command = phase3.align_command(row, 48, 8)
        self.assertIn("samtools view -@ 8 -b -o 'bam/SRR7890824.tumor.unsorted.bam' -", command)
        self.assertNotIn("samtools sort", command)

    def test_validation_cache_uris_scope_sample_and_pair_outputs(self):
        tumor = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "pair_id": "hcc1395",
            "run_accession": "SRR7890824",
        }
        normal = {**tumor, "role": "normal", "run_accession": "SRR7890827"}
        with patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"):
            self.assertEqual(
                phase3.sample_validation_cache_uri(tumor, "results/phase3_wgs_smoke/logs/ref.SRR7890824.stats.txt"),
                "s3://cache/phase3_wgs/validation/ucsc_hg38_analysis_set_full/full/tumor/results__phase3_wgs_smoke__logs__ref.SRR7890824.stats.txt",
            )
            self.assertEqual(
                phase3.pair_validation_cache_uri(tumor, normal, "coverage_cnv", "results/phase3_wgs_smoke/coverage_cnv_bedcov.tsv"),
                "s3://cache/phase3_wgs/validation/ucsc_hg38_analysis_set_full/full/pair/hcc1395/coverage_cnv/results__phase3_wgs_smoke__coverage_cnv_bedcov.tsv",
            )

    def test_restore_cached_alignment_requires_bam_and_bai(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
                patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
                patch.object(fetch_phase3, "s3_object_size", side_effect=[10, None]),
                patch.object(fetch_phase3, "restore_cached_asset") as restore,
            ):
                self.assertFalse(phase3.restore_cached_alignment(row))
            restore.assert_not_called()

    def test_restore_cached_alignment_writes_stage_marker(self):
        row = {
            "fastq_1": "data/raw/phase3/fastq/SRR7890824_R1.full.fastq.gz",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
            "read_pairs_per_end": "568040077",
        }

        def restore(_aws, _uri, target_path, _expected_bytes, _label):
            utils.write_text(target_path, "restored")
            return True

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(phase3, "FORCE", False),
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "bam_satisfies_read_scope", return_value=True),
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(fetch_phase3, "cache_reads_enabled", return_value=True),
                patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
                patch.object(fetch_phase3, "s3_object_size", return_value=10),
                patch.object(fetch_phase3, "restore_cached_asset", side_effect=restore),
            ):
                self.assertTrue(phase3.restore_cached_alignment(row))
            marker = utils.read_json(root / "results/phase3_wgs_smoke/stage_markers/align_tumor.json")
        self.assertEqual(marker["status"], "restored_cache")
        self.assertEqual(marker["runAccession"], "SRR7890824")

    def test_align_sample_prefers_cached_alignment_before_public_bam(self):
        row = {
            "reference_id": "ucsc_hg38_analysis_set_full",
            "role": "tumor",
            "run_accession": "SRR7890824",
            "output_bam": "bam/SRR7890824.tumor.bam",
            "output_bai": "bam/SRR7890824.tumor.bam.bai",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(phase3, "path_from_root", lambda relative: root / relative),
                patch.object(phase3, "bam_satisfies_read_scope", return_value=False),
                patch.object(phase3, "restore_cached_alignment", return_value=True) as restore_cached,
                patch.object(phase3, "restore_public_alignment", return_value=True) as restore_public,
                patch.object(phase3, "ensure_alignment_idxstats") as idxstats,
            ):
                phase3.align_and_index_sample("ucsc_hg38_analysis_set_full", row)
        restore_cached.assert_called_once_with(row)
        restore_public.assert_not_called()
        idxstats.assert_called_once_with(row)

    def test_parse_s3_uri_requires_bucket_and_key(self):
        self.assertEqual(fetch_phase3.parse_s3_uri("s3://bucket/path/to/object"), ("bucket", "path/to/object"))
        with self.assertRaises(ValueError):
            fetch_phase3.parse_s3_uri("https://example.com/object")

    def test_restore_fastq_cache_requires_both_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r1 = root / "SRR7890824_R1.full.fastq.gz"
            r2 = root / "SRR7890824_R2.full.fastq.gz"
            with (
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(fetch_phase3, "ASSET_CACHE_MODE", "readwrite"),
                patch.object(fetch_phase3, "CACHE_FASTQS", True),
                patch.object(fetch_phase3, "s3_object_size", side_effect=[10, None]),
                patch.object(fetch_phase3, "restore_cached_asset") as restore,
            ):
                self.assertFalse(fetch_phase3.restore_aws_sra_fastq_cache("/usr/bin/aws", "SRR7890824", r1, r2))
            restore.assert_not_called()

    def test_publish_validated_aws_sra_cache_parallelizes_then_deletes_sra(self):
        row = {
            "run_accession": "SRR7890824",
            "fastq_1": "fastq/SRR7890824_R1.full.fastq.gz",
            "fastq_2": "fastq/SRR7890824_R2.full.fastq.gz",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in [row["fastq_1"], row["fastq_2"]]:
                utils.write_text(root / path, "fastq")
            sra_path = root / fetch_phase3.SMOKE_ROOT / "sra" / "SRR7890824.sra"
            utils.write_text(sra_path, "sra")
            published: list[str] = []

            def publish(_aws, source_path, _uri, label, _expected_bytes=None):
                self.assertTrue(source_path.exists())
                published.append(label)
                return True

            with (
                patch.object(fetch_phase3, "ASSET_CACHE_URI", "s3://cache/phase3_wgs"),
                patch.object(fetch_phase3, "ASSET_CACHE_MODE", "readwrite"),
                patch.object(fetch_phase3, "CACHE_FASTQS", True),
                patch.object(fetch_phase3, "CACHE_SRA_OBJECTS", True),
                patch.object(fetch_phase3, "DELETE_SRA_AFTER_CONVERSION", True),
                patch.object(fetch_phase3, "CACHE_UPLOAD_WORKERS", 3),
                patch.object(fetch_phase3, "path_from_root", lambda relative: root / relative),
                patch.object(fetch_phase3, "aws_cli_path", return_value="/usr/bin/aws"),
                patch.object(fetch_phase3, "publish_cached_asset", side_effect=publish),
            ):
                summary = fetch_phase3.publish_validated_aws_sra_cache([row])
            sra_exists_after = sra_path.exists()
        self.assertEqual(set(published), {"SRR7890824.R1.fastq.gz", "SRR7890824.R2.fastq.gz", "SRR7890824.sra"})
        self.assertFalse(sra_exists_after)
        self.assertEqual(summary["cacheUploadWorkers"], 3)
        self.assertEqual(summary["deletedLocalSra"], [str(sra_path)])

    def test_expected_hrd_bucket_keeps_unknown_labels_separate(self):
        self.assertEqual(analyze_hrd.expected_bucket_for_label("expected_hrd_positive"), "expected_hrd_like")
        self.assertEqual(analyze_hrd.expected_bucket_for_label("expected_hrd_negative"), "expected_negative")
        self.assertEqual(analyze_hrd.expected_bucket_for_label("needs_manual_review"), "expected_unknown")


if __name__ == "__main__":
    unittest.main()
