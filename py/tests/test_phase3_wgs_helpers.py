import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import analyze_hrd
from diana_omics.commands import fetch_phase3_wgs_smoke_assets as fetch_phase3
from diana_omics.commands import run_phase3_wgs_smoke as phase3


class Phase3WgsHelpersTest(unittest.TestCase):
    def test_sbs96_rows_cover_expected_matrix(self):
        rows = phase3.all_sbs96_rows()
        self.assertEqual(len(rows), 96)
        self.assertEqual(len({row["trinucleotide"] for row in rows}), 96)
        self.assertEqual({row["sample"] for row in rows}, {"HCC1395"})
        self.assertIn("A[C>A]A", {row["trinucleotide"] for row in rows})
        self.assertIn("T[T>G]T", {row["trinucleotide"] for row in rows})

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
            row = {"reference_id": "ref", "run_accession": "SRR1", "output_bam": "tumor.bam"}
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
                patch.object(phase3, "capture_command", return_value=flagstat) as capture,
            ):
                self.assertEqual(phase3.alignment_flag_counts("ref", row), {"total": 100, "mapped": 90, "properly_paired": 80})
            capture.assert_called_once_with("samtools flagstat -@ 8 'tumor.bam'")
            self.assertIn("properly paired", utils.read_text(root / "results/phase3_wgs_smoke/logs/ref.SRR1.flagstat.txt"))

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

    def test_expected_hrd_bucket_keeps_unknown_labels_separate(self):
        self.assertEqual(analyze_hrd.expected_bucket_for_label("expected_hrd_positive"), "expected_hrd_like")
        self.assertEqual(analyze_hrd.expected_bucket_for_label("expected_hrd_negative"), "expected_negative")
        self.assertEqual(analyze_hrd.expected_bucket_for_label("needs_manual_review"), "expected_unknown")


if __name__ == "__main__":
    unittest.main()
