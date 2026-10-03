import csv
import hashlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics.commands.adc_atlas.build_pan_cancer_adc_atlas import (
    _render_html,
    build_expression_summaries,
    build_orthogonal_followup,
    build_target_and_candidate_summaries,
    load_patient_bridge,
    summarize_values,
    xena_log_tpm_to_tpm,
)


class PanCancerAdcAtlasTest(unittest.TestCase):
    def test_followup_queue_orders_rna_without_promoting_evidence(self):
        rows = [
            {
                "target_id": "trop2",
                "gene_symbol": "TACSTD2",
                "display_name": "TROP-2",
                "patient_tpm": 108.4,
                "patient_within_sample_protein_coding_percentile": 95.2,
                "tcga_brca_quantile_band": "q1_to_median",
                "descriptive_patient_to_tcga_brca_median_ratio": 0.68,
                "patient_comparison_status": "directionally_comparable",
                "protein_gate": "membrane IHC",
                "caveat": "RNA is not membrane protein.",
            },
            {
                "target_id": "her3",
                "gene_symbol": "ERBB3",
                "display_name": "HER3",
                "patient_tpm": 710.8,
                "patient_within_sample_protein_coding_percentile": 99.6,
                "tcga_brca_quantile_band": "at_or_above_p95",
                "descriptive_patient_to_tcga_brca_median_ratio": 6.19,
                "patient_comparison_status": "directionally_comparable",
                "protein_gate": "membrane IHC with heterogeneity review",
                "caveat": "Surface localization is unmeasured.",
            },
        ]
        queue = build_orthogonal_followup(rows, limit=1)
        self.assertEqual("her3", queue[0]["target_id"])
        self.assertEqual("partial_evidence", queue[0]["evidence_status"])
        self.assertIn("not a therapeutic ranking", queue[0]["interpretation_boundary"])

        second_queue = build_orthogonal_followup(rows, start=1, limit=1)
        self.assertEqual("trop2", second_queue[0]["target_id"])
        self.assertEqual(2, second_queue[0]["review_order"])
        self.assertIn("rank 2", second_queue[0]["prioritization_basis"])

    def test_visualization_links_the_selected_patient_bridge_run(self):
        html = _render_html({"patient_bridge": {"run_id": "adc-atlas-patient-bridge-new-run"}})
        self.assertIn("results/workbench/adc-atlas-patient-bridge-new-run", html)
        self.assertNotIn("__PATIENT_RUN_URL__", html)

    def test_xena_inverse_transform(self):
        self.assertAlmostEqual(0.0, xena_log_tpm_to_tpm(-9.965784284662087), places=8)
        self.assertAlmostEqual(1.0, xena_log_tpm_to_tpm(0.0014419741739063218), places=8)
        self.assertIsNone(xena_log_tpm_to_tpm("NaN"))
        self.assertIsNone(xena_log_tpm_to_tpm(None))

    def test_summary_reports_distribution_and_prevalence(self):
        summary = summarize_values([0, 1, 10, 20])
        self.assertEqual(4, summary["sample_count"])
        self.assertEqual(5.5, summary["median_tpm"])
        self.assertEqual(0.75, summary["fraction_ge_1_tpm"])
        self.assertEqual(0.5, summary["fraction_ge_10_tpm"])

    def test_cohort_filter_excludes_target_and_non_primary_tcga(self):
        targets = [{"target_id": "trop2", "gene_symbol": "TACSTD2", "query_gene": "TACSTD2", "display_name": "TROP-2"}]
        samples = ["tumor", "normal", "metastatic", "pediatric"]
        phenotypes = [
            {"sample": "tumor", "_study": "TCGA", "_sample_type": "Primary Tumor", "detailed_category": "Breast Cancer"},
            {"sample": "normal", "_study": "GTEX", "_sample_type": "Normal Tissue", "_primary_site": "Breast"},
            {"sample": "metastatic", "_study": "TCGA", "_sample_type": "Metastatic", "detailed_category": "Breast Cancer"},
            {"sample": "pediatric", "_study": "TARGET", "_sample_type": "Primary Tumor", "detailed_category": "Wilms"},
        ]

        def score(tpm):
            return math.log2(tpm + 0.001)

        cancer, normal, counts = build_expression_summaries(
            targets, samples, phenotypes, {"TACSTD2": [score(5), score(1), score(99), score(99)]}
        )
        self.assertEqual(5.0, cancer[0]["median_tpm"])
        self.assertEqual(1.0, normal[0]["median_tpm"])
        self.assertEqual(1, counts["target_samples_excluded"])
        self.assertEqual(1, counts["other_samples_excluded"])

    def test_candidate_evidence_is_ceilinged_below_ready(self):
        targets = [
            {
                "target_id": "trop2",
                "gene_symbol": "TACSTD2",
                "display_name": "TROP-2",
                "query_gene": "TACSTD2",
                "tier": "anchor",
                "target_scope": "epithelial",
                "epitope_or_isoform": "whole-gene proxy",
                "payload_context": "TOP1",
                "protein_gate": "membrane IHC",
                "caveat": "RNA is not protein",
            }
        ]
        cancer = [{"target_id": "trop2", "cancer": "Breast Cancer", "median_tpm": 10}]
        normal = [{"target_id": "trop2", "normal_tissue": "Breast", "median_tpm": 2}]
        target_rows, candidates = build_target_and_candidate_summaries(targets, cancer, normal, [], [], [])
        self.assertEqual("blocked_not_harmonized", target_rows[0]["patient_comparison_status"])
        self.assertEqual("partial_evidence", candidates[0]["overall_status"])
        self.assertEqual("no_call", candidates[0]["surface_localization_status"])

    def test_directional_patient_bridge_does_not_raise_evidence_ceiling(self):
        targets = [
            {
                "target_id": "trop2",
                "gene_symbol": "TACSTD2",
                "display_name": "TROP-2",
                "query_gene": "TACSTD2",
                "tier": "anchor",
                "target_scope": "epithelial",
                "epitope_or_isoform": "whole-gene proxy",
                "payload_context": "TOP1",
                "protein_gate": "membrane IHC",
                "caveat": "RNA is not protein",
            }
        ]
        patient = [
            {
                "target_id": "trop2",
                "patient_tpm": "230.5",
                "patient_protein_coding_percentile": "98.2",
                "tcga_brca_median_tpm": "159.3",
                "descriptive_patient_to_cohort_median_ratio": "1.447",
                "cohort_quantile_band": "median_to_q3",
                "comparison_status": "directionally_comparable",
            }
        ]
        target_rows, candidates = build_target_and_candidate_summaries(
            targets,
            [{"target_id": "trop2", "cancer": "Breast Cancer", "median_tpm": 10}],
            [{"target_id": "trop2", "normal_tissue": "Breast", "median_tpm": 2}],
            [],
            [],
            [],
            patient,
        )
        self.assertEqual("directionally_comparable", target_rows[0]["patient_comparison_status"])
        self.assertEqual(230.5, target_rows[0]["patient_tpm"])
        self.assertEqual("median_to_q3", target_rows[0]["tcga_brca_quantile_band"])
        self.assertEqual("partial_evidence", candidates[0]["overall_status"])
        self.assertEqual("no_call", candidates[0]["surface_localization_status"])

    def test_patient_bridge_requires_hash_bound_passed_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comparison = root / "comparison.csv"
            with comparison.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "target_id",
                        "patient_tpm",
                        "patient_protein_coding_percentile",
                        "tcga_brca_median_tpm",
                        "descriptive_patient_to_cohort_median_ratio",
                        "cohort_quantile_band",
                        "comparison_status",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "target_id": "trop2",
                        "patient_tpm": "109.2",
                        "patient_protein_coding_percentile": "98.4",
                        "tcga_brca_median_tpm": "159.3",
                        "descriptive_patient_to_cohort_median_ratio": "0.6855",
                        "cohort_quantile_band": "q1_to_median",
                        "comparison_status": "directionally_comparable",
                    }
                )
            qa = root / "qa.json"
            qa.write_text(
                json.dumps(
                    {
                        "status": "passed_for_directional_comparison_with_cross_pipeline_caveat",
                        "comparisonStatus": "directionally_comparable",
                    }
                ),
                encoding="utf-8",
            )
            run_manifest = root / "run.json"
            run_manifest.write_text(json.dumps({"status": "completed_research_analysis"}), encoding="utf-8")

            def artifact(path: Path) -> dict[str, str]:
                return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

            pointer = root / "pointer.json"
            pointer.write_text(
                json.dumps(
                    {
                        "sample_label": "Diana E019",
                        "comparison_table": artifact(comparison),
                        "qa_summary": artifact(qa),
                        "run_manifest": artifact(run_manifest),
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ADC_ATLAS_PATIENT_BRIDGE": str(pointer)}):
                bridge = load_patient_bridge()
            self.assertIsNotNone(bridge)
            self.assertEqual("trop2", bridge["comparisons"][0]["target_id"])

            comparison.write_text(comparison.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with patch.dict(os.environ, {"ADC_ATLAS_PATIENT_BRIDGE": str(pointer)}):
                with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                    load_patient_bridge()


if __name__ == "__main__":
    unittest.main()
