import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
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


if __name__ == "__main__":
    unittest.main()
