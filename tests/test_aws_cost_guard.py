from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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


class FakeEc2:
    def __init__(self, *pages: dict) -> None:
        self.calls: list[dict] = []
        self.pages = list(pages)

    def describe_instances(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        if not self.pages:
            return {"Reservations": []}
        return self.pages.pop(0)


class FailingEc2:
    def describe_instances(self, **kwargs: object) -> dict:
        raise RuntimeError("live EC2 inventory unavailable")


class FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_public_access_block(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class FakeTable:
    def __init__(self, item: dict | None = None) -> None:
        self.item = item
        self.get_calls: list[dict] = []
        self.put_calls: list[dict] = []

    def get_item(self, **kwargs: object) -> dict:
        self.get_calls.append(kwargs)
        if self.item is None:
            return {}
        return {"Item": self.item}

    def put_item(self, **kwargs: dict) -> None:
        self.put_calls.append(kwargs)
        self.item = kwargs["Item"]


def terraform_block(text: str, header: str) -> str:
    start = text.index(header)
    block_start = text.index("{", start)
    depth = 0
    for index in range(block_start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        if depth == 0:
            return text[start : index + 1]
    raise AssertionError(f"unterminated Terraform block: {header}")


def assert_lifecycle_ignores(test: unittest.TestCase, block: str, *fields: str) -> None:
    lifecycle = terraform_block(block, "lifecycle")
    for field in fields:
        test.assertIn(field, lifecycle)


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

    def test_scheduled_guard_stops_batch_after_estimated_batch_ec2_limit(self) -> None:
        now = datetime(2026, 7, 19, 2, 0, tzinfo=timezone.utc)
        batch = FakeBatch()
        ec2 = FakeEc2(
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-p5",
                                "InstanceType": "p5en.48xlarge",
                                "LaunchTime": now - timedelta(hours=1),
                            },
                        ],
                    },
                ],
            },
        )
        table = FakeTable()

        result = GUARD.monitor_estimated_ec2_spend(
            batch,
            ec2,
            table,
            job_queues=["gpu"],
            compute_environments=["gpu-ce"],
            reason="estimated guard",
            tag_key="DianaBatchCostGuard",
            tag_value="diana-omics-prod-use2",
            daily_limit_usd=Decimal("100"),
            hourly_rates={"p5en.48xlarge": Decimal("140")},
            unknown_hourly_rate=Decimal("20"),
            now=now,
        )

        self.assertEqual("stopped", result["status"])
        self.assertEqual("140.000000", result["estimated_daily_ec2_usd"])
        self.assertEqual(
            table.get_calls,
            [
                {
                    "Key": {"guard_day": "2026-07-19"},
                    "ConsistentRead": True,
                },
            ],
        )
        self.assertEqual(
            table.item["instances"]["i-p5"],
            {
                "billable_seconds": 3600,
                "estimated_usd": Decimal("140.000000"),
                "hourly_rate_usd": Decimal("140.000000"),
                "instance_type": "p5en.48xlarge",
                "last_seen_epoch": int(now.timestamp()),
            },
        )
        self.assertEqual(
            ec2.calls[0]["Filters"],
            [
                {
                    "Name": "tag:DianaBatchCostGuard",
                    "Values": ["diana-omics-prod-use2"],
                },
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "shutting-down"],
                },
            ],
        )
        self.assertIn(
            (
                "update_job_queue",
                {"jobQueue": "gpu", "state": "DISABLED"},
            ),
            batch.calls,
        )
        self.assertIn(
            (
                "update_compute_environment",
                {
                    "computeEnvironment": "gpu-ce",
                    "state": "DISABLED",
                },
            ),
            batch.calls,
        )

    def test_scheduled_guard_only_adds_runtime_since_prior_poll(self) -> None:
        now = datetime(2026, 7, 19, 2, 0, tzinfo=timezone.utc)
        previous = now - timedelta(seconds=60)
        batch = FakeBatch()
        ec2 = FakeEc2(
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-p5",
                                "InstanceType": "p5.48xlarge",
                                "LaunchTime": now - timedelta(hours=1),
                            },
                        ],
                    },
                ],
            },
        )
        table = FakeTable(
            {
                "guard_day": "2026-07-19",
                "estimated_daily_ec2_usd": Decimal("10.000000"),
                "instances": {
                    "i-p5": {
                        "billable_seconds": Decimal(60),
                        "estimated_usd": Decimal("10.000000"),
                        "last_seen_epoch": Decimal(int(previous.timestamp())),
                    },
                },
            },
        )

        result = GUARD.monitor_estimated_ec2_spend(
            batch,
            ec2,
            table,
            job_queues=["gpu"],
            compute_environments=["gpu-ce"],
            reason="estimated guard",
            tag_key="DianaBatchCostGuard",
            tag_value="diana-omics-prod-use2",
            daily_limit_usd=Decimal("200"),
            hourly_rates={"p5": Decimal("60")},
            unknown_hourly_rate=Decimal("20"),
            now=now,
        )

        self.assertEqual(
            {
                "active_instance_count": 1,
                "estimated_daily_ec2_usd": "11.000000",
                "guard_day": "2026-07-19",
                "limit_usd": "200",
                "status": "monitored",
            },
            result,
        )
        self.assertEqual([], batch.calls)
        self.assertEqual(
            {
                "billable_seconds": 120,
                "estimated_usd": Decimal("11.000000"),
                "hourly_rate_usd": Decimal("60.000000"),
                "instance_type": "p5.48xlarge",
                "last_seen_epoch": int(now.timestamp()),
            },
            table.item["instances"]["i-p5"],
        )

    def test_scheduled_guard_conservatively_stops_unknown_instance_types(self) -> None:
        now = datetime(2026, 7, 19, 2, 0, tzinfo=timezone.utc)
        batch = FakeBatch()
        ec2 = FakeEc2(
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-gpu",
                                "InstanceType": "p6.48xlarge",
                                "LaunchTime": now - timedelta(hours=2),
                            },
                        ],
                    },
                ],
            },
        )
        table = FakeTable()

        result = GUARD.monitor_estimated_ec2_spend(
            batch,
            ec2,
            table,
            job_queues=["gpu"],
            compute_environments=["gpu-ce"],
            reason="unknown guard",
            tag_key="DianaBatchCostGuard",
            tag_value="diana-omics-prod-use2",
            daily_limit_usd=Decimal("200"),
            hourly_rates={},
            unknown_hourly_rate=Decimal("140"),
            now=now,
        )

        self.assertEqual("stopped", result["status"])
        self.assertEqual("280.000000", result["estimated_daily_ec2_usd"])
        self.assertIn(
            (
                "terminate_job",
                {
                    "jobId": "running",
                    "reason": "unknown guard",
                },
            ),
            batch.calls,
        )

    def test_scheduled_guard_estimates_batch_ec2_spend_across_regions(self) -> None:
        now = datetime(2026, 7, 19, 2, 0, tzinfo=timezone.utc)
        batch = FakeBatch()
        ec2_by_region = {
            "us-east-1": FakeEc2(
                {
                    "Reservations": [
                        {
                            "Instances": [
                                {
                                    "InstanceId": "i-overlap",
                                    "InstanceType": "c7i.48xlarge",
                                    "LaunchTime": now - timedelta(minutes=30),
                                },
                            ],
                        },
                    ],
                }
            ),
            "us-east-2": FakeEc2(
                {
                    "Reservations": [
                        {
                            "Instances": [
                                {
                                    "InstanceId": "i-overlap",
                                    "InstanceType": "p5en.48xlarge",
                                    "LaunchTime": now - timedelta(hours=1),
                                },
                            ],
                        },
                    ],
                }
            ),
        }
        table = FakeTable()

        result = GUARD.monitor_estimated_ec2_spend(
            batch,
            ec2_by_region,
            table,
            job_queues=["gpu"],
            compute_environments=["gpu-ce"],
            reason="cross-region guard",
            tag_key="DianaBatchCostGuard",
            tag_value="diana-omics",
            daily_limit_usd=Decimal("200"),
            hourly_rates={
                "c7i": Decimal("12"),
                "p5en.48xlarge": Decimal("140"),
            },
            unknown_hourly_rate=Decimal("140"),
            now=now,
        )

        self.assertEqual(
            {
                "active_instance_count": 2,
                "estimated_daily_ec2_usd": "146.000000",
                "guard_day": "2026-07-19",
                "limit_usd": "200",
                "status": "monitored",
            },
            result,
        )
        self.assertEqual([], batch.calls)
        self.assertEqual(
            {
                "us-east-1:i-overlap": {
                    "billable_seconds": 1800,
                    "estimated_usd": Decimal("6.000000"),
                    "hourly_rate_usd": Decimal("12.000000"),
                    "instance_type": "c7i.48xlarge",
                    "last_seen_epoch": int(now.timestamp()),
                    "region": "us-east-1",
                },
                "us-east-2:i-overlap": {
                    "billable_seconds": 3600,
                    "estimated_usd": Decimal("140.000000"),
                    "hourly_rate_usd": Decimal("140.000000"),
                    "instance_type": "p5en.48xlarge",
                    "last_seen_epoch": int(now.timestamp()),
                    "region": "us-east-2",
                },
            },
            table.item["instances"],
        )

    def test_handler_stops_batch_when_live_estimator_fails(self) -> None:
        batch = FakeBatch()

        class FakeBoto3:
            @staticmethod
            def client(service: str, **kwargs: object) -> object:
                if service == "batch":
                    return batch
                if service == "ec2":
                    return FailingEc2()
                raise AssertionError(f"unexpected client: {service}")

            @staticmethod
            def resource(service: str, **kwargs: object) -> object:
                if service != "dynamodb":
                    raise AssertionError(f"unexpected resource: {service}")

                class FakeDynamoDB:
                    @staticmethod
                    def Table(table_name: str) -> FakeTable:
                        return FakeTable()

                return FakeDynamoDB()

        with mock.patch.dict(
            sys.modules,
            {"boto3": FakeBoto3},
        ), mock.patch.dict(
            os.environ,
            {
                "BATCH_COMPUTE_ENVIRONMENTS": json.dumps(["gpu-ce"]),
                "BATCH_COST_GUARD_REGIONS": json.dumps(["us-east-2"]),
                "BATCH_COST_GUARD_TAG_KEY": "DianaBatchCostGuard",
                "BATCH_COST_GUARD_TAG_VALUE": "diana-omics",
                "BATCH_COST_LEDGER_TABLE": "daily-cost",
                "BATCH_DAILY_EC2_LIMIT_USD": "160",
                "BATCH_ESTIMATED_FAILURE_STOP_REASON": "estimator failed closed",
                "BATCH_INSTANCE_HOURLY_RATES_USD": json.dumps({"p5en.48xlarge": 140}),
                "BATCH_JOB_QUEUES": json.dumps(["gpu"]),
                "BATCH_UNKNOWN_INSTANCE_HOURLY_RATE_USD": "140",
            },
            clear=True,
        ):
            result = GUARD.handler({}, None)

        self.assertEqual("stopped", result["status"])
        self.assertEqual("RuntimeError", result["estimator_error"])
        self.assertIn(
            (
                "update_job_queue",
                {"jobQueue": "gpu", "state": "DISABLED"},
            ),
            batch.calls,
        )
        self.assertIn(
            (
                "terminate_job",
                {
                    "jobId": "running",
                    "reason": "estimator failed closed",
                },
            ),
            batch.calls,
        )

    def test_budget_event_stops_batch_and_blocks_public_s3(self) -> None:
        batch = FakeBatch()
        s3 = FakeS3()

        class FakeBoto3:
            @staticmethod
            def client(service: str, **kwargs: object) -> object:
                if service == "batch":
                    return batch
                if service == "s3":
                    return s3
                raise AssertionError(f"unexpected client: {service}")

        with mock.patch.dict(
            sys.modules,
            {"boto3": FakeBoto3},
        ), mock.patch.dict(
            os.environ,
            {
                "BATCH_COMPUTE_ENVIRONMENTS": json.dumps(["gpu-ce"]),
                "BATCH_JOB_QUEUES": json.dumps(["gpu"]),
                "BATCH_PUBLIC_S3_BUCKETS": json.dumps(["raw", "results", "raw"]),
            },
            clear=True,
        ):
            result = GUARD.handler({"Records": [{"EventSource": "aws:sns"}]}, None)

        self.assertEqual("stopped", result["status"])
        self.assertEqual(2, result["public_s3_buckets_blocked"])
        self.assertEqual(
            [
                {
                    "Bucket": "raw",
                    "PublicAccessBlockConfiguration": GUARD.BLOCK_PUBLIC_ACCESS,
                },
                {
                    "Bucket": "results",
                    "PublicAccessBlockConfiguration": GUARD.BLOCK_PUBLIC_ACCESS,
                },
            ],
            s3.calls,
        )
        self.assertIn(
            (
                "update_job_queue",
                {"jobQueue": "gpu", "state": "DISABLED"},
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
        self.assertIn(
            "var.daily_cost_guard_limit_usd > 0 && var.daily_cost_guard_limit_usd <= 200",
            variables,
        )
        self.assertIn('variable "daily_cost_guard_stop_threshold_percent"', variables)
        self.assertIn("default     = 80", variables)
        self.assertIn(
            (
                "var.daily_cost_guard_stop_threshold_percent > 0 && "
                "var.daily_cost_guard_stop_threshold_percent <= 80"
            ),
            variables,
        )
        self.assertIn(
            'variable "daily_cost_guard_live_stop_threshold_percent"',
            variables,
        )
        self.assertIn(
            (
                "var.daily_cost_guard_live_stop_threshold_percent > 0 && "
                "var.daily_cost_guard_live_stop_threshold_percent <= 80"
            ),
            variables,
        )
        self.assertIn("default     = 140", variables)
        self.assertIn(
            (
                "BATCH_DAILY_EC2_LIMIT_USD       = "
                "tostring(var.daily_cost_guard_limit_usd * "
                "var.daily_cost_guard_live_stop_threshold_percent / 100)"
            ),
            main,
        )
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
        self.assertIn("BATCH_BUDGET_STOP_REASON", main)
        self.assertIn("DianaBatchCostGuard", main)
        self.assertIn('resource "aws_dynamodb_table" "daily_cost_guard"', main)
        self.assertIn('resource "aws_cloudwatch_event_rule" "daily_cost_guard_poll"', main)
        self.assertIn("var.daily_cost_guard_schedule_expression", main)
        self.assertIn("BATCH_COST_LEDGER_TABLE", main)
        self.assertIn("daily_cost_guard_ledger", main)
        self.assertIn("BATCH_INSTANCE_HOURLY_RATES_USD", main)
        self.assertIn("BATCH_UNKNOWN_INSTANCE_HOURLY_RATE_USD", main)
        self.assertIn("daily_cost_guard_batch_compute_environments", main)
        self.assertIn("daily_cost_guard_batch_job_queues", main)
        self.assertIn(
            (
                "daily_cost_guard_live_stop_usd               = "
                "tostring(var.daily_cost_guard_limit_usd * "
                "var.daily_cost_guard_live_stop_threshold_percent / 100)"
            ),
            main,
        )
        self.assertIn("concat(", main)
        self.assertIn("var.enable_gpu_p5en_batch", main)
        self.assertIn("aws_batch_job_queue.gpu_p5en[0].name", main)
        self.assertIn("aws_batch_compute_environment.gpu_p5en_ondemand[0].name", main)
        self.assertIn('"batch:UpdateJobQueue"', main)
        self.assertIn('"batch:UpdateComputeEnvironment"', main)
        self.assertIn('"ec2:DescribeInstances"', main)
        self.assertIn("BATCH_PUBLIC_S3_BUCKETS", main)
        self.assertIn('"s3:PutBucketPublicAccessBlock"', main)
        self.assertIn('"dynamodb:GetItem"', main)
        self.assertIn('"dynamodb:PutItem"', main)
        self.assertIn('sid       = "ListDianaBatchJobs"', main)
        self.assertIn('resources = ["*"]', main)
        self.assertIn('sid    = "CancelAndTerminateDianaBatchJobs"', main)
        self.assertIn('"batch:CancelJob"', main)
        self.assertIn('"batch:TerminateJob"', main)
        self.assertIn('variable "daily_cost_guard_schedule_expression"', variables)
        self.assertIn('variable "daily_cost_guard_regions"', variables)
        self.assertIn('default     = ["us-east-1", "us-east-2", "us-west-2"]', variables)
        self.assertIn('daily_cost_guard_ec2_tag_value = var.project', main)
        self.assertIn(
            "BATCH_COST_GUARD_REGIONS   = jsonencode(sort(distinct(concat([var.region], var.daily_cost_guard_regions))))",
            main,
        )
        self.assertIn(
            "daily_cost_guard_regions                     = sort(distinct(concat([var.region], var.daily_cost_guard_regions)))",
            main,
        )
        self.assertIn('variable "daily_cost_guard_instance_hourly_rates_usd"', variables)
        self.assertIn('variable "daily_cost_guard_unknown_instance_hourly_rate_usd"', variables)
        self.assertIn('output "daily_cost_guard_budget"', outputs)
        self.assertIn('output "daily_cost_guard_topic_arn"', outputs)
        self.assertIn('output "daily_cost_guard_ledger"', outputs)
        self.assertIn("ignore_changes = [", terraform_block(main, 'resource "aws_s3_bucket_public_access_block" "this"'))
        self.assertIn("block_public_policy", terraform_block(main, 'resource "aws_s3_bucket_public_access_block" "this"'))
        self.assertIn("restrict_public_buckets", terraform_block(main, 'resource "aws_s3_bucket_public_access_block" "this"'))

    def test_terraform_preserves_tripped_batch_kill_switch_state(self) -> None:
        main = MAIN_TF.read_text(encoding="utf-8")

        for name in (
            "spot",
            "ondemand",
            "hrd_x86_ondemand",
            "gpu_p5en_ondemand",
        ):
            with self.subTest(compute_environment=name):
                assert_lifecycle_ignores(
                    self,
                    terraform_block(
                        main,
                        f'resource "aws_batch_compute_environment" "{name}"',
                    ),
                    "compute_resources[0].desired_vcpus",
                    "state",
                )

        for name in (
            "spot",
            "ondemand",
            "hrd_x86",
            "gpu_p5en",
        ):
            with self.subTest(job_queue=name):
                assert_lifecycle_ignores(
                    self,
                    terraform_block(main, f'resource "aws_batch_job_queue" "{name}"'),
                    "state",
                )


if __name__ == "__main__":
    unittest.main()
