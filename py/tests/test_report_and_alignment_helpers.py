import unittest

from diana_omics import alignment
from diana_omics.commands import build_reviewer_packet, run_full_reference_smoke


class ReportAndAlignmentHelpersTest(unittest.TestCase):
    def test_markdown_table_escapes_pipes(self):
        self.assertEqual(
            build_reviewer_packet.table([{"name": "A|B", "count": 2}]),
            "| name | count |\n| --- | --- |\n| A/B | 2 |",
        )

    def test_count_by_uses_blank_bucket(self):
        self.assertEqual(
            build_reviewer_packet.count_by([{"status": ""}, {"status": "passed"}, {}], "status"),
            [{"key": "(blank)", "count": 2}, {"key": "passed", "count": 1}],
        )

    def test_parse_header_detects_sort_order_read_group_and_contigs(self):
        header = "@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr13\tLN:10\n@RG\tID:run1\tSM:sample1\n"
        parsed = alignment.parse_header(header, {"read_group_id": "run1", "read_group_sample": "sample1"})
        self.assertEqual(parsed["sortOrder"], "coordinate")
        self.assertTrue(parsed["readGroupPresent"])
        self.assertEqual(parsed["contigs"], ["chr13"])

    def test_parse_vcf_stats(self):
        stats = "SN\t0\tnumber of records:\t3\nSN\t0\tnumber of SNPs:\t2\nSN\t0\tnumber of indels:\t1\n"
        self.assertEqual(run_full_reference_smoke.parse_vcf_stats(stats), {"records": 3, "snps": 2, "indels": 1})


if __name__ == "__main__":
    unittest.main()
