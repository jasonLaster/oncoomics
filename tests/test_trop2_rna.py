import unittest

from diana_omics.trop2_rna import (
    build_expression_metrics,
    compare_counts,
    parse_depth,
    parse_flagstat,
    parse_idxstats,
    require_run_id,
    summarize_depth,
)


class Trop2RnaTest(unittest.TestCase):
    def test_run_id_is_strict(self):
        self.assertEqual(require_run_id("immunoid-trop2-20260903T220000Z"), "immunoid-trop2-20260903T220000Z")
        for invalid in ("", "../escape", "/absolute", "contains a space"):
            with self.subTest(run_id=invalid), self.assertRaises(ValueError):
                require_run_id(invalid)

    def test_idxstats_summary_includes_unplaced_unmapped_reads(self):
        summary = parse_idxstats("1\t249250621\t100\t3\n2\t243199373\t80\t4\n*\t0\t0\t9\n")
        self.assertEqual(summary["contigCount"], 2)
        self.assertEqual(summary["totalMappedAlignments"], 180)
        self.assertEqual(summary["totalUnmappedAlignments"], 16)
        self.assertEqual(summary["contigs"][0]["length"], 249250621)

    def test_idxstats_rejects_malformed_rows(self):
        with self.assertRaisesRegex(ValueError, "four"):
            parse_idxstats("1\t249250621\t100\n")
        with self.assertRaisesRegex(ValueError, "negative"):
            parse_idxstats("1\t249250621\t-1\t0\n")

    def test_flagstat_parser_preserves_alignment_record_semantics(self):
        summary = parse_flagstat(
            "120 + 0 in total (QC-passed reads + QC-failed reads)\n"
            "100 + 0 primary\n"
            "15 + 0 secondary\n"
            "5 + 0 supplementary\n"
            "30 + 0 duplicates\n"
            "25 + 0 primary duplicates\n"
            "120 + 0 mapped (100.00% : N/A)\n"
            "100 + 0 primary mapped (100.00% : N/A)\n"
            "100 + 0 paired in sequencing\n"
            "49 + 0 read1\n"
            "51 + 0 read2\n"
            "98 + 0 properly paired (98.00% : N/A)\n"
        )
        self.assertEqual(summary["primaryAlignments"], 100)
        self.assertEqual(summary["primaryNonduplicateAlignments"], 75)
        self.assertEqual(summary["read1Alignments"], 49)
        self.assertEqual(summary["read2Alignments"], 51)

    def test_flagstat_parser_rejects_incomplete_output(self):
        with self.assertRaisesRegex(ValueError, "primaryAlignments"):
            parse_flagstat("10 + 0 in total (QC-passed reads + QC-failed reads)\n")

    def test_depth_parser_fills_unreported_positions(self):
        values = parse_depth("1\t10\t5\n1\t12\t20\n", contig="1", start=10, end=12)
        self.assertEqual(values, [5, 0, 20])
        summary = summarize_depth(values)
        self.assertEqual(summary["bases"], 3)
        self.assertEqual(summary["medianDepth"], 5)
        self.assertAlmostEqual(summary["fractionAtLeast1x"], 2 / 3)

    def test_expression_metrics_are_explicitly_approximate(self):
        metrics = build_expression_metrics(
            primary_region_reads=50_000,
            hq_nonduplicate_region_reads=40_000,
            unique_hq_templates=25_000,
            total_index_mapped_alignments=200_000_000,
            gene_length_bp=2_000,
        )
        self.assertEqual(metrics["hqRetentionFraction"], 0.8)
        self.assertEqual(metrics["alignmentReadsPerMillion"], 250)
        self.assertEqual(metrics["approximateFragmentRpkm"], 125)
        self.assertIn("not Salmon/tximport TPM", metrics["normalizationCaveat"])

    def test_count_comparison_uses_two_percent_gate(self):
        self.assertEqual(compare_counts(1000, 990)["status"], "concordant")
        self.assertEqual(compare_counts(1000, 900)["status"], "discordant_review_required")


if __name__ == "__main__":
    unittest.main()
