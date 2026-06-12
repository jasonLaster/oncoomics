import unittest

from diana_omics.commands import run_sra_benchmark


class SraBenchmarkTest(unittest.TestCase):
    def test_parse_matrix_defaults_to_single_config(self):
        configs = run_sra_benchmark.parse_matrix("", "aws_s3api_range", 8, 1024, 4)
        self.assertEqual(
            configs,
            [{"label": "single", "strategy": "aws_s3api_range", "bytes": 1024, "parts": 4, "concurrency": 8}],
        )

    def test_parse_matrix_accepts_labels(self):
        configs = run_sra_benchmark.parse_matrix("aws_s3api_range:4:1024:2:c4,s5cmd_cat:8:2048:1", "aws_s3api_range", 1, 1, 1)
        self.assertEqual(configs[0]["label"], "c4")
        self.assertEqual(configs[1]["label"], "s5cmd_cat-c8-p1-b2048")
        self.assertEqual(configs[1]["concurrency"], 8)

    def test_range_for_part_is_byte_exact(self):
        self.assertEqual(run_sra_benchmark.range_for_part(0, 10), (0, 9, "bytes=0-9"))
        self.assertEqual(run_sra_benchmark.range_for_part(2, 10), (20, 29, "bytes=20-29"))

    def test_summarize_rows_reports_aggregate_throughput(self):
        summary = run_sra_benchmark.summarize_rows(
            {"label": "c4", "strategy": "aws_s3api_range", "bytes": 100, "parts": 2, "concurrency": 4},
            [{"bytes": 100}, {"bytes": 300}],
            2.0,
        )
        self.assertEqual(summary["totalBytes"], 400)
        self.assertEqual(summary["aggregateMbPerSecond"], 0.0)


if __name__ == "__main__":
    unittest.main()
