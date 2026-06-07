import unittest

from diana_omics import domain


class DomainTest(unittest.TestCase):
    def test_mutation_classes_and_prediction(self):
        brca = {"mutationType": "Frame_Shift_Del", "gene": {"hugoGeneSymbol": "BRCA1"}}
        self.assertEqual(domain.mutation_class(brca), "likely_damaging")
        self.assertEqual(domain.score_mutation(brca), 3)
        self.assertEqual(
            domain.prediction_class({"expected_hrd_label": "expected_hrd_like"}, brca, -1, 0.4, 5),
            "strong_hrd_like_candidate",
        )

    def test_cna_and_scar_helpers(self):
        self.assertEqual(domain.cna_state(-2), "deep_deletion")
        self.assertEqual(domain.cna_state(0), "neutral")
        self.assertEqual(domain.scar_proxy_class(0.36, None), "copy_number_scar_proxy_high")
        self.assertEqual(domain.confusion_bucket("low_evidence_negative_candidate"), "predicted_negative")


if __name__ == "__main__":
    unittest.main()
