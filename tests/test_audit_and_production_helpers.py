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

    def test_native_readiness_is_recorded_in_tooling_audit(self):
        written = {}

        def fake_write_json(path, value):
            written[str(path)] = value

        with (
            patch.object(audit_raw_tools, "ensure_dir", lambda path: None),
            patch.object(audit_raw_tools, "path_from_root", lambda relative: relative),
            patch.object(audit_raw_tools, "write_json", fake_write_json),
            patch.object(audit_raw_tools, "write_text", lambda path, value: written.update({str(path): value})),
            patch.object(audit_raw_tools, "tool_path", lambda tool: f"/usr/bin/{tool}"),
            patch.object(
                audit_raw_tools,
                "optional_integration_rows",
                return_value=[
                    {"name": "pysam", "available": "yes", "version": "1", "purpose": "vcf", "package": "pysam"},
                    {"name": "pyfaidx", "available": "yes", "version": "2", "purpose": "ref", "package": "pyfaidx"},
                    {"name": "polars", "available": "yes", "version": "3", "purpose": "joins", "package": "polars"},
                    {"name": "truvari", "available": "no", "version": "", "purpose": "sv", "package": "truvari"},
                    {
                        "name": "SigProfilerAssignment",
                        "available": "no",
                        "version": "",
                        "purpose": "signatures",
                        "package": "SigProfilerAssignment",
                    },
                ],
            ),
        ):
            audit_raw_tools.main()

        audit = written["results/raw_smoke/tooling_audit.json"]
        self.assertTrue(audit["nativeFoundationReady"])
        self.assertFalse(audit["svBenchmarkReady"])
        self.assertFalse(audit["sigProfilerReady"])
        self.assertEqual(len(audit["nativeIntegrations"]), 5)
        self.assertIn("Native Python HRD foundation ready: **yes**", written["results/raw_smoke/tooling_audit.md"])

    def test_java17_path_uses_path_java_before_homebrew(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args[0])
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": 'openjdk version "17.0.15"\n'})()

        with (
            patch.object(audit_raw_tools, "command_path", lambda tool: "/usr/bin/java" if tool == "java" else ""),
            patch.object(audit_raw_tools.os.path, "exists", lambda path: path == "/usr/bin/java"),
            patch.object(audit_raw_tools.subprocess, "run", fake_run),
            patch.dict(audit_raw_tools.os.environ, {}, clear=True),
        ):
            self.assertEqual(audit_raw_tools.java17_path(), "/usr/bin/java")

        self.assertEqual(calls, ["/usr/bin/java"])

    def test_java17_path_skips_missing_candidates(self):
        with (
            patch.object(audit_raw_tools, "command_path", lambda tool: ""),
            patch.object(audit_raw_tools.os.path, "exists", lambda path: False),
            patch.object(audit_raw_tools.subprocess, "run") as run,
            patch.dict(audit_raw_tools.os.environ, {"GATK_JAVA": "/missing/java"}, clear=True),
        ):
            self.assertEqual(audit_raw_tools.java17_path(), "")

        run.assert_not_called()

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

    def test_full_wes_flagstat_parser_uses_single_scan_counts(self):
        flagstat = "\n".join(
            [
                "123 + 0 in total (QC-passed reads + QC-failed reads)",
                "120 + 0 mapped (97.56% : N/A)",
                "110 + 0 properly paired (89.43% : N/A)",
                "7 + 0 duplicates",
            ]
        )
        self.assertEqual(
            run_full_wes_benchmark.parse_flagstat_counts(flagstat),
            {"total": 123, "mapped": 120, "properly_paired": 110, "duplicates": 7},
        )


if __name__ == "__main__":
    unittest.main()
