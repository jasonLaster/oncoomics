from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/daily_cost_guard.py"

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
        MODULE.validate_daily_cost_guard_estimated_spend(
            Decimal("159.999999"),
            live_stop_usd="160",
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


if __name__ == "__main__":
    unittest.main()
