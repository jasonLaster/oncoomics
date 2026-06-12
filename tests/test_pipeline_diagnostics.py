import tempfile
import unittest
from pathlib import Path

from diana_omics import pipeline_diagnostics as diagnostics
from diana_omics.commands import diagnose_pipeline


class PipelineDiagnosticsTest(unittest.TestCase):
    def test_parse_duration_seconds_handles_nextflow_units(self):
        self.assertEqual(diagnostics.parse_duration_seconds("2h 34m 54s"), 9294)
        self.assertEqual(diagnostics.parse_duration_seconds("12m 8s"), 728)
        self.assertEqual(diagnostics.parse_duration_seconds("498ms"), 0.498)
        self.assertIsNone(diagnostics.parse_duration_seconds("-"))

    def test_read_trace_summarizes_best_completed_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.tsv"
            path.write_text(
                "\t".join(["task_id", "hash", "native_id", "name", "status", "exit", "submit", "duration", "realtime"]) + "\n"
                "1\taa/id\tjob-1\tPHASE3_WGS_SPLIT:PHASE3_FETCH_WORKSPACE (phase3_fetch_workspace_full_aws_sra_c8_s1)\tCOMPLETED\t0\t-\t12m 8s\t9m 48s\n"
                "2\tbb/id\tjob-2\tPHASE3_WGS_SPLIT:PHASE3_REFERENCE_INDEX (phase3_reference_index_full)\tCOMPLETED\t0\t-\t2m 8s\t10.7s\n",
                encoding="utf-8",
            )
            rows = diagnostics.read_trace(path)
        best = diagnostics.best_completed_by_stage(rows)
        self.assertEqual(best["phase3_fetch"]["durationSeconds"], 728)
        self.assertEqual(best["reference_index"]["realtimeSeconds"], 10.7)

    def test_failure_signals_and_speedup_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace = root / "trace.tsv"
            trace.write_text(
                "\t".join(["task_id", "hash", "native_id", "name", "status", "exit", "submit", "duration", "realtime"]) + "\n"
                "1\taa/id\tjob-1\tPHASE3_WGS_SPLIT:PHASE3_FETCH_WORKSPACE (phase3_fetch_workspace_full_aws_sra_c8_s1)\tCOMPLETED\t0\t-\t12m 8s\t9m 48s\n"
                "2\tbb/id\tjob-2\tPHASE3_WGS_SPLIT:PHASE3_REFERENCE_INDEX (phase3_reference_index_full)\tCOMPLETED\t0\t-\t2m 8s\t10.7s\n",
                encoding="utf-8",
            )
            log = root / "nextflow.log"
            log.write_text(
                "Caused by:\n  Host EC2 (instance i-123) terminated.\n"
                "WorkflowStats[succeededCount=0; failedCount=1; failedDuration=2h 34m 54s; cachedDuration=0ms;]\n",
                encoding="utf-8",
            )
            summary = diagnostics.build_diagnostics([trace], [log])
        self.assertEqual(summary["speedupEstimate"]["speedup"], 10.86)
        self.assertIn("spot_or_host_interruption", {signal["label"] for item in summary["logSummaries"] for signal in item["signals"]})

    def test_collectors_include_nested_run_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "logs" / "phase3opt_align64_20260612T200806Z"
            run_dir.mkdir(parents=True)
            trace = run_dir / "trace.tsv"
            review = run_dir / "review.log"
            trace.write_text("task_id\n", encoding="utf-8")
            review.write_text("Host EC2 (instance i-123) terminated.\n", encoding="utf-8")

            self.assertEqual([trace], diagnose_pipeline.collect_trace_paths(root))
            self.assertEqual([review], diagnose_pipeline.collect_log_paths(root))


if __name__ == "__main__":
    unittest.main()
