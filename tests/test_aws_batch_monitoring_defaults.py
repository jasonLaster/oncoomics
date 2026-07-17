from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_LOG_GROUP = "/aws/batch/job"


class AwsBatchMonitoringDefaultsTest(unittest.TestCase):
    def test_monitor_scripts_default_to_nextflow_aws_log_group(self) -> None:
        nextflow_config = (ROOT / "nextflow.config").read_text(encoding="utf-8")
        self.assertIn(f"aws_logs_group = '{EXPECTED_LOG_GROUP}'", nextflow_config)

        for relative in (
            "infra/aws/monitor-batch-job.sh",
            "scripts/review_phase3_aws_run.sh",
        ):
            with self.subTest(relative=relative):
                script = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(
                    f'LOG_GROUP="${{AWS_BATCH_LOG_GROUP:-{EXPECTED_LOG_GROUP}}}"',
                    script,
                )
                self.assertNotIn("/aws/batch/diana-omics-prod-use1", script)


if __name__ == "__main__":
    unittest.main()
