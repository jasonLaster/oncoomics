import unittest

from diana_omics.commands import run_known_answer_bounded_non_dry as bounded


class KnownAnswerBoundedNonDryTest(unittest.TestCase):
    def test_pileup_parser_counts_ref_alt_and_other_bases(self):
        parsed = bounded._parse_pileup_bases("TTtTAaaCg", "A", "T")
        self.assertEqual(parsed["altCount"], 4)
        self.assertEqual(parsed["refCount"], 3)
        self.assertEqual(parsed["otherCount"], 2)
        self.assertEqual(parsed["depthInformative"], 9)
        self.assertAlmostEqual(parsed["altFraction"], 4 / 9, places=6)

    def test_pileup_parser_skips_indel_annotations_and_read_markers(self):
        parsed = bounded._parse_pileup_bases("^]Tt$A+3ACGa-2tt.,*", "A", "T")
        self.assertEqual(parsed["altCount"], 2)
        self.assertEqual(parsed["refCount"], 4)
        self.assertEqual(parsed["deletionCount"], 1)
        self.assertEqual(parsed["depthInformative"], 6)

    def test_hg008_selector_skips_complex_source_variants(self):
        self.assertTrue(bounded._hg008_source_variant_is_simple_snv("AC=1;HG008Nv63SOMATICVARIANT=chr1_hap1:783362-G-A"))
        self.assertFalse(bounded._hg008_source_variant_is_simple_snv("AC=1;HG008Nv63SOMATICVARIANT=chr1_hap1:1195496-C-CA"))

    def test_cnv_probe_uses_interior_window(self):
        self.assertEqual(bounded._interior_window_start(["chr2", "0", "39789308", "2", "1", "1", "noCNV"], 1000), 1_000_001)


if __name__ == "__main__":
    unittest.main()
