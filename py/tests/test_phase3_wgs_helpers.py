import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
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


if __name__ == "__main__":
    unittest.main()
