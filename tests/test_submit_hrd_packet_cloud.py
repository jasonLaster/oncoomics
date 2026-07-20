from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBMITTER = ROOT / "infra/aws/submit-hrd-packet-cloud.sh"


def write_executable(path: Path, text: str) -> Path:
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class SubmitHrdPacketCloudTests(unittest.TestCase):
    def test_submitter_reads_daily_cost_guard_before_submit_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            aws_log = root / "aws.log"
            config = root / "nextflow.aws.json"
            config.write_text(
                json.dumps(
                    {
                        "aws_ondemand_queue": "diana-omics-prod-use1-ondemand",
                        "aws_region": "us-east-1",
                        "aws_results_dir": "s3://diana-omics-results-172630973301-us-east-1/runs",
                        "container": "container:tag",
                        "daily_cost_guard_ledger": "diana-omics-prod-use1-daily-cost-guard-ledger",
                        "daily_cost_guard_limit_usd": "200",
                        "daily_cost_guard_live_stop_usd": "160",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            write_executable(
                bin_dir / "aws",
                """\
                #!/usr/bin/env bash
                set -euo pipefail
                printf '%s\\n' "$*" >> "$FAKE_AWS_LOG"
                if [[ "$1 $2" == "batch describe-job-definitions" ]]; then
                  cat <<'JSON'
                {"jobDefinitions":[{"jobDefinitionName":"unit","jobDefinitionArn":"arn:aws:batch:us-east-1:172630973301:job-definition/unit:1","revision":1,"containerProperties":{"image":"container:tag"}}]}
                JSON
                  exit 0
                fi
                if [[ "$1 $2" == "dynamodb get-item" ]]; then
                  cat <<'JSON'
                {"Item":{"estimated_daily_ec2_usd":{"N":"160"}}}
                JSON
                  exit 0
                fi
                if [[ "$1 $2" == "batch submit-job" ]]; then
                  echo '{"jobId":"unexpected"}'
                  exit 0
                fi
                echo "unexpected aws command: $*" >&2
                exit 1
                """,
            )

            result = subprocess.run(
                [
                    "bash",
                    str(SUBMITTER),
                    "--run-id",
                    "cost-guard-unit",
                    "--source-commit",
                    "f" * 40,
                ],
                env={
                    **os.environ,
                    "DIANA_AWS_CONFIG": str(config),
                    "FAKE_AWS_LOG": str(aws_log),
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                },
                text=True,
                capture_output=True,
                check=False,
            )
            aws_calls = aws_log.read_text(encoding="utf-8")

        self.assertEqual(64, result.returncode)
        self.assertIn("refusing AWS Batch submission", result.stderr)
        self.assertIn("dynamodb get-item", aws_calls)
        self.assertNotIn("batch submit-job", aws_calls)


if __name__ == "__main__":
    unittest.main()
