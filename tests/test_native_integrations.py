import unittest
from unittest.mock import patch

from diana_omics import native


class NativeIntegrationsTest(unittest.TestCase):
    def test_optional_integration_rows_include_staged_hrd_foundation(self):
        rows = native.optional_integration_rows()
        self.assertIn("pysam", {row["name"] for row in rows})
        self.assertIn("pyfaidx", {row["name"] for row in rows})
        self.assertIn("polars", {row["name"] for row in rows})
        self.assertIn("truvari", {row["name"] for row in rows})

    def test_reference_context_falls_back_to_samtools_when_pyfaidx_missing(self):
        with (
            patch.object(native, "optional_module_available", return_value=False),
            patch.object(native, "capture_allow_empty", return_value="acg") as capture,
        ):
            self.assertEqual(native.reference_context("ref.fa", "chr1", 10), "ACG")
        capture.assert_called_once_with("samtools faidx 'ref.fa' 'chr1:9-11' | awk 'NR>1 {printf \"%s\", $0}'")

    def test_vcf_sample_names_returns_none_when_pysam_missing(self):
        with patch.object(native, "optional_module_available", return_value=False):
            self.assertIsNone(native.vcf_sample_names("calls.vcf.gz"))


if __name__ == "__main__":
    unittest.main()
