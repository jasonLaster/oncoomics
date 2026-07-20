from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra/aws"
MAIN_TF = INFRA / "main.tf"
VARIABLES_TF = INFRA / "variables.tf"
OUTPUTS_TF = INFRA / "outputs.tf"
VERSIONS_TF = INFRA / "versions.tf"
COST_GUARD = INFRA / "batch_cost_guard.py"

SPEC = importlib.util.spec_from_file_location("batch_cost_guard", COST_GUARD)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GUARD
SPEC.loader.exec_module(GUARD)


class FakeBatch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.pages = {
            ("gpu", "SUBMITTED", None): {
                "jobSummaryList": [{"jobId": "queued"}],
                "nextToken": "page-2",
            },
            ("gpu", "SUBMITTED", "page-2"): {
                "jobSummaryList": [{"jobId": "queued-2"}],
            },
            ("gpu", "RUNNING", None): {
                "jobSummaryList": [{"jobId": "running"}],
            },
        }

    def update_job_queue(self, **kwargs: str) -> None:
        self.calls.append(("update_job_queue", kwargs))

    def update_compute_environment(self, **kwargs: str) -> None:
        self.calls.append(("update_compute_environment", kwargs))

    def list_jobs(self, **kwargs: str) -> dict:
        self.calls.append(("list_jobs", kwargs))
        return self.pages.get(
            (
                kwargs["jobQueue"],
                kwargs["jobStatus"],
                kwargs.get("nextToken"),
            ),
            {"jobSummaryList": []},
        )

    def cancel_job(self, **kwargs: str) -> None:
        self.calls.append(("cancel_job", kwargs))

    def terminate_job(self, **kwargs: str) -> None:
        self.calls.append(("terminate_job", kwargs))


class AwsCostGuardTests(unittest.TestCase):
    def test_lambda_disables_batch_and_stops_visible_jobs(self) -> None:
        batch = FakeBatch()

        result = GUARD.stop_batch(
            batch,
            job_queues=["gpu", "gpu"],
            compute_environments=["ce", "ce"],
            reason="daily guard",
        )

        self.assertEqual(
            result,
            {
                "compute_environments_disabled": 1,
                "job_queues_disabled": 1,
                "jobs": {
                    "already_terminal": 0,
                    "cancelled": 2,
                    "terminated": 1,
                },
                "status": "stopped",
            },
        )
        self.assertEqual(
            batch.calls[:2],
            [
                ("update_job_queue", {"jobQueue": "gpu", "state": "DISABLED"}),
                (
                    "update_compute_environment",
                    {
                        "computeEnvironment": "ce",
                        "state": "DISABLED",
                    },
                ),
            ],
        )
        self.assertIn(
            (
                "cancel_job",
                {
                    "jobId": "queued-2",
                    "reason": "daily guard",
                },
            ),
            batch.calls,
        )
        self.assertIn(
            (
                "terminate_job",
                {
                    "jobId": "running",
                    "reason": "daily guard",
                },
            ),
            batch.calls,
        )

    def test_handler_requires_exact_nonempty_environment_lists(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "BATCH_COMPUTE_ENVIRONMENTS": "[]",
                "BATCH_JOB_QUEUES": json.dumps(["gpu"]),
            },
            clear=True,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "BATCH_COMPUTE_ENVIRONMENTS",
            ):
                GUARD.handler({}, None)

    def test_terraform_wires_daily_budget_to_batch_kill_switch(self) -> None:
        main = MAIN_TF.read_text(encoding="utf-8")
        variables = VARIABLES_TF.read_text(encoding="utf-8")
        outputs = OUTPUTS_TF.read_text(encoding="utf-8")
        versions = VERSIONS_TF.read_text(encoding="utf-8")

        self.assertIn('source  = "hashicorp/archive"', versions)
        self.assertIn('variable "daily_cost_guard_limit_usd"', variables)
        self.assertIn("default     = 200", variables)
        self.assertIn('variable "daily_cost_guard_stop_threshold_percent"', variables)
        self.assertIn("default     = 80", variables)
        self.assertIn('resource "aws_budgets_budget" "daily_cost_guard"', main)
        self.assertIn('time_unit    = "DAILY"', main)
        self.assertIn(
            "threshold                  = var.daily_cost_guard_stop_threshold_percent",
            main,
        )
        self.assertIn('threshold                  = 100', main)
        self.assertIn('resource "aws_sns_topic" "daily_cost_guard"', main)
        self.assertIn('resource "aws_lambda_function" "batch_cost_guard"', main)
        self.assertIn('handler          = "batch_cost_guard.handler"', main)
        self.assertIn(
            'BATCH_STOP_REASON = "Diana daily AWS Budget cost guard tripped"',
            main,
        )
        self.assertIn("aws_batch_job_queue.gpu_p5en.name", main)
        self.assertIn("aws_batch_compute_environment.gpu_p5en_ondemand.name", main)
        self.assertIn('"batch:UpdateJobQueue"', main)
        self.assertIn('"batch:UpdateComputeEnvironment"', main)
        self.assertIn('sid       = "ListDianaBatchJobs"', main)
        self.assertIn('resources = ["*"]', main)
        self.assertIn('sid    = "CancelAndTerminateDianaBatchJobs"', main)
        self.assertIn('"batch:CancelJob"', main)
        self.assertIn('"batch:TerminateJob"', main)
        self.assertIn('output "daily_cost_guard_budget"', outputs)
        self.assertIn('output "daily_cost_guard_topic_arn"', outputs)


if __name__ == "__main__":
    unittest.main()
