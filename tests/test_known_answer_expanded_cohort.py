import unittest

from diana_omics.commands import run_known_answer_expanded_cohort as expanded
from diana_omics.paths import path_from_root
from diana_omics.utils import parse_csv, read_text


class KnownAnswerExpandedCohortTest(unittest.TestCase):
    def test_manifest_is_large_and_representative(self):
        rows = parse_csv(read_text(path_from_root(expanded.PLAN_PATH)))
        self.assertGreaterEqual(len(rows), 25)
        self.assertEqual(len({row["target_id"] for row in rows}), len(rows))
        self.assertGreaterEqual(len({row["cohort_group"] for row in rows}), 5)
        modalities = {row["modality"] for row in rows}
        self.assertIn("tumor_normal_wes", modalities)
        self.assertIn("tumor_normal_wgs", modalities)
        self.assertIn("tumor_rna_seq", modalities)
        self.assertIn("ctdna_mrd_reference", modalities)

    def test_all_manifest_probe_keys_are_registered(self):
        rows = parse_csv(read_text(path_from_root(expanded.PLAN_PATH)))
        registered = set(expanded._probe_functions())
        self.assertTrue({row["probe_key"] for row in rows}.issubset(registered))

    def test_summary_counts_confirmations_gaps_and_blocks(self):
        rows = [
            {"cohort_group": "a", "target_status": "expanded_non_dry_passed"},
            {"cohort_group": "a", "target_status": "expanded_non_dry_partial"},
            {"cohort_group": "b", "target_status": "expanded_non_dry_gap_identified"},
            {"cohort_group": "c", "target_status": "expanded_non_dry_blocked_request_or_purchase"},
        ]
        summary = expanded._summary(rows)
        self.assertEqual(summary["target_count"], 4)
        self.assertEqual(summary["cohort_group_count"], 3)
        self.assertEqual(summary["passed_count"], 1)
        self.assertEqual(summary["partial_count"], 1)
        self.assertEqual(summary["gap_identified_count"], 1)
        self.assertEqual(summary["blocked_count"], 1)
        self.assertEqual(summary["ready_for_clinical_interpretation"], "no")


if __name__ == "__main__":
    unittest.main()
