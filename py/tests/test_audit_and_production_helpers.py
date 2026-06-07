import unittest
from unittest.mock import patch

from diana_omics.commands import (
    audit_raw_tools,
    fetch_full_wes_benchmark_assets,
    fetch_production_somatic_assets,
    run_full_wes_benchmark,
    run_production_somatic_smoke,
)


class AuditAndProductionHelpersTest(unittest.TestCase):
    def test_available_tools_filters_by_group(self):
        groups = [{"group": "x", "tools": [{"tool": "a", "available": True}, {"tool": "b", "available": False}]}]
        self.assertEqual(audit_raw_tools.available_tools("x", groups), ["a"])
        self.assertEqual(audit_raw_tools.available_tools("missing", groups), [])

    def test_reference_dict_path(self):
        self.assertEqual(fetch_production_somatic_assets.reference_dict_path("ref.fa"), "ref.dict")
        self.assertEqual(fetch_production_somatic_assets.reference_dict_path("ref.fasta"), "ref.dict")
        self.assertEqual(fetch_full_wes_benchmark_assets.reference_dict_path("ref.fa"), "ref.dict")
        self.assertEqual(fetch_full_wes_benchmark_assets.reference_dict_path("ref.fasta"), "ref.dict")

    def test_interval_bed_writer_format(self):
        calls = {}

        def fake_write_text(path, value):
            calls["path"] = path
            calls["value"] = value

        with (
            patch.object(run_production_somatic_smoke, "write_text", fake_write_text),
            patch.object(run_production_somatic_smoke, "ensure_dir", lambda path: None),
            patch.object(run_production_somatic_smoke, "path_from_root", lambda relative: relative),
        ):
            run_production_somatic_smoke.write_interval_bed(
                "out/active.bed",
                [{"contig": "chr13", "start": 1, "end": 5}, {"contig": "chr17", "start": 2, "end": 6}],
            )

        self.assertEqual(calls["value"], "chr13\t1\t5\tactive_1\nchr17\t2\t6\tactive_2")

    def test_full_wes_truth_variant_selection_and_intervals(self):
        calls = {}
        variants = [
            {"key": "chr17:10:A:T", "type": "snv", "contig": "chr17", "position": 10, "ref": "A", "alt": "T"},
            {"key": "chr13:20:C:G", "type": "snv", "contig": "chr13", "position": 20, "ref": "C", "alt": "G"},
        ]
        depth = "chr17\t10\t12\t11\nchr13\t20\t9\t30\n"
        covered = run_full_wes_benchmark.pick_covered_truth_variants(variants, depth)
        self.assertEqual([row["key"] for row in covered], ["chr17:10:A:T"])
        with (
            patch.object(run_full_wes_benchmark, "ensure_dir", lambda path: None),
            patch.object(run_full_wes_benchmark, "path_from_root", lambda relative: relative),
            patch.object(run_full_wes_benchmark, "write_text", lambda path, value: calls.update({"path": path, "value": value})),
        ):
            intervals = run_full_wes_benchmark.write_benchmark_intervals(covered, {"chr13": 0, "chr17": 1}, "tmp/intervals.bed")
        self.assertEqual(intervals, [{"contig": "chr17", "start": 0, "end": 110}])
        self.assertEqual(calls["value"], "chr17\t0\t110")


if __name__ == "__main__":
    unittest.main()
