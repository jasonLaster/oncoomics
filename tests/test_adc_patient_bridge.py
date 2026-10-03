import math
import unittest

from diana_omics.adc_patient_bridge import (
    aggregate_salmon_to_genes,
    build_target_comparison,
    cohort_band,
    percentile_rank,
    transcript_gene_map,
)


class AdcPatientBridgeTest(unittest.TestCase):
    def test_transcript_gene_map_reads_gencode_attributes(self):
        lines = [
            'chr1\tHAVANA\ttranscript\t1\t10\t.\t+\t.\tgene_id "ENSG1.1"; transcript_id "ENST1.2"; gene_type "protein_coding"; gene_name "TACSTD2";\n'
        ]
        self.assertEqual(
            {"gene_id": "ENSG1.1", "gene_symbol": "TACSTD2", "gene_type": "protein_coding"},
            transcript_gene_map(lines)["ENST1.2"],
        )

    def test_aggregate_salmon_preserves_tpm_and_estimated_reads(self):
        quant = [
            {"Name": "ENST1", "TPM": "2.5", "NumReads": "3.25"},
            {"Name": "ENST2", "TPM": "7.5", "NumReads": "8.75"},
        ]
        mapping = {
            "ENST1": {"gene_id": "ENSG1", "gene_symbol": "TACSTD2", "gene_type": "protein_coding"},
            "ENST2": {"gene_id": "ENSG1", "gene_symbol": "TACSTD2", "gene_type": "protein_coding"},
        }
        rows, qa = aggregate_salmon_to_genes(quant, mapping)
        self.assertEqual(10.0, rows[0]["tpm"])
        self.assertEqual(12.0, rows[0]["estimated_reads"])
        self.assertEqual(1.0, qa["transcript_mapping_fraction"])

    def test_percentile_and_bands_are_deterministic(self):
        self.assertEqual(62.5, percentile_rank(2, [0, 1, 2, 3]))
        cohort = {"q1_tpm": 1, "median_tpm": 2, "q3_tpm": 3, "p90_tpm": 4, "p95_tpm": 5}
        self.assertEqual("below_q1", cohort_band(0.5, cohort))
        self.assertEqual("median_to_q3", cohort_band(2, cohort))
        self.assertEqual("at_or_above_p95", cohort_band(5, cohort))

    def test_comparison_is_directional_not_exact_percentile(self):
        targets = [{"target_id": "trop2", "gene_symbol": "TACSTD2", "query_gene": "TACSTD2", "display_name": "TROP-2"}]
        genes = [
            {"gene_symbol": "TACSTD2", "gene_type": "protein_coding", "tpm": 10},
            {"gene_symbol": "OTHER", "gene_type": "protein_coding", "tpm": 1},
        ]
        reference = [
            {
                "target_id": "trop2",
                "sample_count": 100,
                "q1_tpm": 2,
                "median_tpm": 5,
                "q3_tpm": 8,
                "p90_tpm": 9,
                "p95_tpm": 10,
            }
        ]
        row = build_target_comparison(targets, genes, reference)[0]
        self.assertEqual("directionally_comparable", row["comparison_status"])
        self.assertEqual("at_or_above_p95", row["cohort_quantile_band"])
        self.assertTrue(math.isclose(2.0, row["descriptive_patient_to_cohort_median_ratio"]))
        self.assertIn("not an exact percentile", row["comparison_caveat"])


if __name__ == "__main__":
    unittest.main()
