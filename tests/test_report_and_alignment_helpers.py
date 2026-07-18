import unittest
from unittest.mock import patch

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

    def test_optional_summary_uses_not_staged_default(self):
        self.assertEqual(
            build_reviewer_packet.optional_summary("missing.json", {"sampleRows": "not_staged"}),
            {"status": "not_staged", "sampleRows": "not_staged"},
        )

    def test_parse_header_detects_sort_order_read_group_and_contigs(self):
        header = "@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr13\tLN:10\n@RG\tID:run1\tSM:sample1\n"
        parsed = alignment.parse_header(header, {"read_group_id": "run1", "read_group_sample": "sample1"})
        self.assertEqual(parsed["sortOrder"], "coordinate")
        self.assertTrue(parsed["readGroupPresent"])
        self.assertEqual(parsed["contigs"], ["chr13"])

    def test_parse_flagstat_counts(self):
        text = "\n".join(
            [
                "100 + 0 in total (QC-passed reads + QC-failed reads)",
                "90 + 0 mapped (90.00% : N/A)",
                "80 + 0 properly paired (80.00% : N/A)",
            ]
        )
        self.assertEqual(alignment.parse_flagstat_counts(text), {"total": 100, "mapped": 90, "properly_paired": 80})

    def test_parse_vcf_stats(self):
        stats = "SN\t0\tnumber of records:\t3\nSN\t0\tnumber of SNPs:\t2\nSN\t0\tnumber of indels:\t1\n"
        self.assertEqual(run_full_reference_smoke.parse_vcf_stats(stats), {"records": 3, "snps": 2, "indels": 1})

    def test_tool_version_replaces_invalid_utf8(self):
        with patch.object(alignment.subprocess, "run") as run:
            run.return_value.stdout = b"samtools 1.16\n"
            run.return_value.stderr = b"\xab noisy plugin banner"

            self.assertEqual(alignment.tool_version("samtools"), "samtools 1.16\n� noisy plugin banner")


if __name__ == "__main__":
    unittest.main()
