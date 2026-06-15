import unittest

from diana_omics.commands import analyze_lehmann_subtypes


class LehmannSubtypeFeasibilityTest(unittest.TestCase):
    def test_column_index_handles_multi_letter_columns(self):
        self.assertEqual(analyze_lehmann_subtypes.column_index("A1"), 0)
        self.assertEqual(analyze_lehmann_subtypes.column_index("L20"), 11)
        self.assertEqual(analyze_lehmann_subtypes.column_index("AA2"), 26)

    def test_receptor_status_requires_all_three_negative(self):
        self.assertEqual(
            analyze_lehmann_subtypes.receptor_status(
                {
                    "er_status_nature2012": "Negative",
                    "pr_status_nature2012": "Negative",
                    "her2_status_nature2012": "Negative",
                }
            ),
            "xena_triple_negative",
        )
        self.assertEqual(
            analyze_lehmann_subtypes.receptor_status(
                {
                    "er_status_nature2012": "Negative",
                    "pr_status_nature2012": "Positive",
                    "her2_status_nature2012": "Negative",
                }
            ),
            "not_tnbc_from_xena_receptor_fields",
        )
        self.assertEqual(
            analyze_lehmann_subtypes.receptor_status(
                {
                    "er_status_nature2012": "Negative",
                    "pr_status_nature2012": "Negative",
                    "her2_status_nature2012": "",
                }
            ),
            "incomplete_receptor_fields",
        )


if __name__ == "__main__":
    unittest.main()
