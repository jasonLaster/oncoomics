from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/daily_cost_guard.py"
SHELL_GUARD = ROOT / "infra/aws/check-daily-cost-guard.sh"

SPEC = importlib.util.spec_from_file_location("daily_cost_guard_exact", GUARD)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DailyCostGuardTests(unittest.TestCase):
    @mock.patch.object(MODULE.subprocess, "run")
    def test_loads_estimated_spend_from_dynamodb_ledger(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Item":{"estimated_daily_ec2_usd":{"N":"159.999999"}}}',
        )

        spend = MODULE.load_daily_cost_guard_estimated_spend(
            ledger="diana-omics-prod-use1-daily-cost-guard-ledger",
            region="us-east-1",
            guard_day="2026-07-20",
        )

        self.assertEqual(Decimal("159.999999"), spend)
        self.assertEqual(
            [
                "aws",
                "dynamodb",
                "get-item",
                "--region",
                "us-east-1",
                "--table-name",
                "diana-omics-prod-use1-daily-cost-guard-ledger",
                "--key",
                '{"guard_day": {"S": "2026-07-20"}}',
                "--consistent-read",
                "--output",
                "json",
            ],
            run.call_args.args[0],
        )

    def test_cost_guard_blocks_at_the_live_stop(self) -> None:
        result = MODULE.validate_daily_cost_guard_estimated_spend(
            Decimal("159.999999"),
            live_stop_usd="160",
            daily_limit_usd="200",
            reservation_usd="40",
        )

        self.assertEqual(
            {
                "daily_limit_usd": "200",
                "reservation_usd": "40",
                "reserved_daily_ec2_usd": "199.999999",
            },
            result,
        )

        for spend in (Decimal("160"), Decimal("200")):
            with self.subTest(spend=spend):
                with self.assertRaisesRegex(
                    MODULE.DailyCostGuardError,
                    "refusing AWS Batch submission",
                ):
                    MODULE.validate_daily_cost_guard_estimated_spend(
                        spend,
                        live_stop_usd="160",
                    )

    def test_cost_guard_reserves_the_next_submission_before_daily_limit(self) -> None:
        with self.assertRaisesRegex(
            MODULE.DailyCostGuardError,
            "reservation would exceed the \\$200.000000 daily limit",
        ):
            MODULE.validate_daily_cost_guard_estimated_spend(
                Decimal("51"),
                live_stop_usd="160",
                daily_limit_usd="200",
                reservation_usd="150",
            )

    @mock.patch.object(MODULE, "check_daily_cost_guard")
    def test_cli_fails_closed_when_guard_is_spent(self, check) -> None:
        check.side_effect = MODULE.DailyCostGuardError("already spent")

        with mock.patch.object(MODULE.sys, "stderr") as stderr:
            result = MODULE.main(
                [
                    "--ledger",
                    "diana-omics-prod-use1-daily-cost-guard-ledger",
                    "--region",
                    "us-east-1",
                    "--live-stop-usd",
                    "160",
                ]
            )

        self.assertEqual(64, result)
        stderr.write.assert_any_call("Fail-closed: already spent")

    def test_shell_guard_reads_nextflow_config_before_checking_dynamodb(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "nextflow.aws.json"
            config.write_text(
                json.dumps(
                    {
                        "aws_region": "us-east-2",
                        "daily_cost_guard_ledger": "diana-omics-prod-use2-daily-cost-guard-ledger",
                        "daily_cost_guard_limit_usd": "200",
                        "daily_cost_guard_live_stop_usd": "160",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake_aws = root / "aws"
            fake_aws.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s\\n' \"$@\" > \"$FAKE_AWS_ARGV\"\n"
                "printf '{\"Item\":{\"estimated_daily_ec2_usd\":{\"N\":\"159.999999\"}}}\\n'\n",
                encoding="utf-8",
            )
            fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR)
            argv = root / "aws.argv"

            result = subprocess.run(
                ["bash", str(SHELL_GUARD), str(config)],
                env={
                    **os.environ,
                    "FAKE_AWS_ARGV": str(argv),
                    "PATH": f"{root}{os.pathsep}{os.environ.get('PATH', '')}",
                },
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertEqual(
                [
                    "dynamodb",
                    "get-item",
                    "--region",
                    "us-east-2",
                    "--table-name",
                    "diana-omics-prod-use2-daily-cost-guard-ledger",
                    "--key",
                    '{"guard_day": {"S": "' + MODULE.today_utc() + '"}}',
                    "--consistent-read",
                    "--output",
                    "json",
                ],
                argv.read_text(encoding="utf-8").splitlines(),
            )

    def test_shell_guard_passes_task_reservation_from_nextflow_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "nextflow.aws.use2.json"
            config.write_text(
                json.dumps(
                    {
                        "aws_region": "us-east-2",
                        "daily_cost_guard_ledger": "diana-omics-prod-use2-daily-cost-guard-ledger",
                        "daily_cost_guard_limit_usd": "200",
                        "daily_cost_guard_live_stop_usd": "160",
                        "daily_cost_guard_phase3_fast_execute_reservation_usd": "150",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            fake_python = root / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "if [[ \"$1\" == *daily_cost_guard.py ]]; then\n"
                "  printf '%s\\n' \"$@\" > \"$FAKE_PYTHON_ARGV\"\n"
                "  exit 0\n"
                "fi\n"
                "exec /usr/bin/python3 \"$@\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
            argv = root / "python.argv"

            result = subprocess.run(
                [
                    "bash",
                    str(SHELL_GUARD),
                    str(config),
                    "daily_cost_guard_phase3_fast_execute_reservation_usd",
                ],
                env={
                    **os.environ,
                    "FAKE_PYTHON_ARGV": str(argv),
                    "PATH": f"{root}{os.pathsep}{os.environ.get('PATH', '')}",
                },
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertIn("--limit-usd\n200\n", argv.read_text(encoding="utf-8"))
            self.assertIn("--reservation-usd\n150\n", argv.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
