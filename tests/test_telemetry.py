import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import paths
from diana_omics.telemetry import RunTelemetry, run_traced_command


class TelemetryTest(unittest.TestCase):
    def test_run_telemetry_writes_spans_heartbeats_and_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload_root = root / "uploaded"
            with patch.object(paths, "ROOT", root):
                telemetry = RunTelemetry("test_workflow", "results/test", {"case": "unit"}, upload_uri=str(upload_root))
                with telemetry.span("outer"):
                    telemetry.heartbeat("outer", {"records": 1})
                    output = run_traced_command(
                        "printf ok",
                        "results/test/logs/command.log",
                        telemetry,
                        "command.printf",
                        {"records": 1},
                    )
                telemetry.finalize("passed", {"output": output})

            self.assertEqual(output, "ok")
            latest = json.loads((root / "results/test/logs/telemetry/latest_run.json").read_text(encoding="utf-8"))
            run_dir = Path(latest["runDir"])
            self.assertTrue((run_dir / "events.jsonl").exists())
            self.assertTrue((run_dir / "otel_spans.jsonl").exists())
            self.assertTrue((run_dir / "resource_samples.jsonl").exists())
            self.assertEqual(json.loads((run_dir / "heartbeat.json").read_text(encoding="utf-8"))["stage"], "outer")
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "passed")
            self.assertGreater(manifest["durationSeconds"], 0)
            self.assertEqual(manifest["uploadStatus"], "uploaded")
            self.assertEqual(manifest["upload"]["mode"], "local")
            spans = [json.loads(line) for line in (run_dir / "otel_spans.jsonl").read_text(encoding="utf-8").splitlines()]
            span_by_name = {span["name"]: span for span in spans}
            self.assertIn("outer", span_by_name)
            self.assertIn("command.printf", span_by_name)
            self.assertEqual(span_by_name["command.printf"]["parentSpanId"], span_by_name["outer"]["spanId"])
            self.assertIn("## telemetry", (root / "results/test/logs/command.log").read_text(encoding="utf-8"))
            uploaded_manifest = json.loads(
                (upload_root / "test_workflow" / latest["runId"] / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(uploaded_manifest["uploadStatus"], "uploaded")


if __name__ == "__main__":
    unittest.main()
