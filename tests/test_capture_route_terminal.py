#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPT_DIR = HERE.parents[0] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SCRIPT = SCRIPT_DIR / "capture_route_terminal.py"
SPEC = importlib.util.spec_from_file_location("capture_route_terminal", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

DOWNLOAD_SCRIPT = HERE.parents[0] / "scripts" / "download_exact_report_tree.py"
DOWNLOAD_SPEC = importlib.util.spec_from_file_location("download_exact_report_tree", DOWNLOAD_SCRIPT)
assert DOWNLOAD_SPEC and DOWNLOAD_SPEC.loader
DOWNLOAD_MODULE = importlib.util.module_from_spec(DOWNLOAD_SPEC)
DOWNLOAD_SPEC.loader.exec_module(DOWNLOAD_MODULE)


def write_duplicate_json_field(payload: bytes, key: str, stale_value: object) -> bytes:
    text = payload.decode("utf-8")
    current = f'  "{key}": '
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one top-level JSON field {key}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    return text.replace(current, duplicate, 1).encode("utf-8")


class CaptureRouteTerminalTests(unittest.TestCase):
    def test_collect_log_events_rejects_malformed_next_token(self) -> None:
        for value in (None, True):
            with self.subTest(nextForwardToken=value):
                calls: list[tuple[str, ...]] = []

                def invoke(region, *arguments):
                    self.assertEqual(region, MODULE.REGION)
                    calls.append(arguments)
                    return {"events": [], "nextForwardToken": value}

                with (
                    mock.patch.object(MODULE, "aws_json", side_effect=invoke),
                    self.assertRaisesRegex(
                        ValueError,
                        "CloudWatch nextForwardToken is malformed",
                    ),
                ):
                    MODULE.collect_log_events(MODULE.REGION, "unit-stream")

                self.assertEqual(len(calls), 1)

    def fixture(self, route: str = "sigprofiler_sbs3") -> dict:
        config = MODULE.ROUTES[route]
        kms = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
        output_uri = "s3://diana-omics-private-results-172630973301-us-east-1/runs/subject01/unit/"
        contract_uri = output_uri + "preparation/input-contract/deadbeef.json"
        contract_version = "exact-contract-version"
        contract_sha = "a" * 64
        submission_id = "20260717T200000Z-a1b2c3d4"
        root = output_uri.rstrip("/")
        route_output = f"{root}/crosschecks/{contract_sha}/{route}/{submission_id}/"
        receipt_prefix = f"{root}/crosscheck-publication-receipts/{contract_sha}/{route}/{submission_id}/"
        submission_environment = {
            "HRD_CROSSCHECK_INPUT_CONTRACT_URI": contract_uri,
            "HRD_CROSSCHECK_INPUT_CONTRACT_VERSION_ID": contract_version,
            "HRD_CROSSCHECK_INPUT_CONTRACT_SHA256": contract_sha,
            "HRD_CROSSCHECK_OUTPUT_URI": output_uri,
            "HRD_CROSSCHECK_ROUTE_OUTPUT_URI": route_output,
            "HRD_CROSSCHECK_PUBLICATION_RECEIPT_PREFIX": receipt_prefix,
            "HRD_CROSSCHECK_SUBMISSION_ID": submission_id,
        }
        object_rows = []
        history_audit = []
        for index, relative_path in enumerate(
            (
                "report.md",
                "report_manifest.json",
                "upload_receipt.json",
                "report_upload_receipt.json",
            ),
            start=1,
        ):
            sha = f"{index:x}" * 64
            checksum = base64.b64encode(bytes.fromhex(sha)).decode()
            key = MODULE.s3_location(route_output + relative_path)[1]
            version_id = f"output-version-{index}"
            object_rows.append(
                {
                    "relative_path": relative_path,
                    "uri": route_output + relative_path,
                    "key": key,
                    "sha256": sha,
                    "etag": f"etag-{index}",
                    "version_id": version_id,
                    "content_length": 100 + index,
                    "server_side_encryption": "aws:kms",
                    "ssekms_key_id": kms,
                    "checksum_sha256": checksum,
                    "checks": dict(MODULE.EXPECTED_OBJECT_CHECKS),
                }
            )
            history_audit.append(
                {
                    "key": key,
                    "version_id": version_id,
                    "sha256": sha,
                    "checks": dict(MODULE.EXPECTED_HISTORY_AUDIT_CHECKS),
                }
            )
        receipt = {
            "schema_version": 1,
            "status": "passed",
            "route": route,
            "submission_id": submission_id,
            "contract": {
                "uri": contract_uri,
                "version_id": contract_version,
                "sha256": contract_sha,
            },
            "route_output_uri": route_output,
            "route_output_initial_version_history_count": 0,
            "route_output_bucket_versioning": "Enabled",
            "publication_strategy": ("one_shot_create_only_exact_version_history"),
            "objects": object_rows,
            "history_audit": history_audit,
            "checks": dict(MODULE.EXPECTED_RECEIPT_CHECKS),
        }
        receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
        receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
        checksum = base64.b64encode(bytes.fromhex(receipt_sha)).decode()
        receipt_uri = receipt_prefix + receipt_sha + ".json"
        receipt_key = MODULE.s3_location(receipt_uri)[1]
        receipt_version = "exact-publication-receipt-version"
        metadata = {
            "VersionId": receipt_version,
            "ContentLength": len(receipt_bytes),
            "ChecksumSHA256": checksum,
            "ChecksumType": "FULL_OBJECT",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": kms,
            "Metadata": {"sha256": receipt_sha},
        }
        terminal = {
            "publication_anchor": {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": receipt_sha,
                "receipt_bytes": len(receipt_bytes),
                "receipt_uri": receipt_uri,
                "receipt_version_id": receipt_version,
                "route_output_uri": route_output,
                "checks": dict(MODULE.EXPECTED_PUBLICATION_ANCHOR_CHECKS),
            }
        }
        log_stream = "hrd-crosscheck/default/exact-route-task"
        definition_environment = [{"name": name, "value": value} for name, value in config["definition_environment"].items()]
        effective_environment = submission_environment
        job = {
            "jobId": "job-1",
            "jobName": f"subject01-{route}-unit",
            "status": "SUCCEEDED",
            "startedAt": 100,
            "stoppedAt": 200,
            "jobDefinition": config["job_definition_arn"],
            "jobQueue": MODULE.EXPECTED_QUEUE_ARN,
            "retryStrategy": {"attempts": 1, "evaluateOnExit": []},
            "container": {
                "exitCode": 0,
                "logStreamName": log_stream,
                "environment": [{"name": name, "value": value} for name, value in effective_environment.items()],
            },
            "attempts": [
                {
                    "container": {
                        "exitCode": 0,
                        "logStreamName": log_stream,
                    }
                }
            ],
        }
        definition = {
            "jobDefinitionArn": config["job_definition_arn"],
            "jobDefinitionName": config["job_definition_name"],
            "revision": 3,
            "status": "ACTIVE",
            "type": "container",
            "platformCapabilities": ["EC2"],
            "retryStrategy": {"attempts": 1, "evaluateOnExit": []},
            "timeout": {"attemptDurationSeconds": config["timeout_seconds"]},
            "containerProperties": {
                "command": config["command"],
                "image": config["image"],
                "jobRoleArn": MODULE.EXPECTED_JOB_ROLE,
                "vcpus": config["vcpus"],
                "memory": config["memory"],
                "environment": definition_environment,
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": MODULE.LOG_GROUP,
                        "awslogs-region": MODULE.REGION,
                        "awslogs-stream-prefix": MODULE.LOG_STREAM_PREFIX,
                    },
                    "secretOptions": [],
                },
            },
        }
        queue = {
            "jobQueueArn": MODULE.EXPECTED_QUEUE_ARN,
            "jobQueueName": MODULE.EXPECTED_QUEUE_NAME,
            "state": "ENABLED",
            "status": "VALID",
            "priority": 30,
            "computeEnvironmentOrder": [
                {
                    "order": 1,
                    "computeEnvironment": MODULE.EXPECTED_COMPUTE_ENVIRONMENT,
                }
            ],
        }
        compute = {
            "computeEnvironmentArn": MODULE.EXPECTED_COMPUTE_ENVIRONMENT,
            "computeEnvironmentName": MODULE.EXPECTED_COMPUTE_ENVIRONMENT_NAME,
            "state": "ENABLED",
            "status": "VALID",
            "type": "MANAGED",
            "containerOrchestrationType": "ECS",
            "computeResources": {
                "type": "EC2",
                "allocationStrategy": "BEST_FIT_PROGRESSIVE",
                "minvCpus": 0,
                "maxvCpus": 128,
                "instanceTypes": ["r7i", "m7i", "c7i"],
                "launchTemplate": {
                    "launchTemplateId": "lt-0b2375486d24af74a",
                    "version": "3",
                    "overrides": [],
                },
                "ec2Configuration": [{"imageType": "ECS_AL2023"}],
            },
        }
        history = {
            "Versions": [
                {
                    "Key": receipt_key,
                    "VersionId": receipt_version,
                    "IsLatest": True,
                }
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
        }
        return {
            "route": route,
            "kms": kms,
            "output_uri": output_uri,
            "contract_uri": contract_uri,
            "contract_version": contract_version,
            "contract_sha": contract_sha,
            "submission_id": submission_id,
            "submission_environment": submission_environment,
            "route_output": route_output,
            "receipt_prefix": receipt_prefix,
            "receipt": receipt,
            "receipt_bytes": receipt_bytes,
            "receipt_sha": receipt_sha,
            "receipt_uri": receipt_uri,
            "receipt_key": receipt_key,
            "receipt_version": receipt_version,
            "metadata": metadata,
            "terminal": terminal,
            "log_stream": log_stream,
            "job": job,
            "definition": definition,
            "queue": queue,
            "compute": compute,
            "history": history,
        }

    def args(self, root: Path, fixture: dict) -> argparse.Namespace:
        return argparse.Namespace(
            route=fixture["route"],
            job_id="job-1",
            expected_contract_uri=fixture["contract_uri"],
            expected_contract_version_id=fixture["contract_version"],
            expected_contract_sha256=fixture["contract_sha"],
            expected_output_uri=fixture["output_uri"],
            submission_id=fixture["submission_id"],
            expected_kms_key_arn=fixture["kms"],
            capture_output=root / "terminal-capture.json",
            receipt_output=root / "publication-receipt.json",
            anchor_output=root / "publication-anchor.json",
            region=MODULE.REGION,
        )

    def receipt_location(self, fixture: dict) -> dict[str, object]:
        return {
            "key": fixture["receipt_key"],
            "version_id": fixture["receipt_version"],
            "sha256": fixture["receipt_sha"],
            "bytes": len(fixture["receipt_bytes"]),
            "kms_key_arn": fixture["kms"],
        }

    def receipt_history_rows(self, fixture: dict) -> list[dict[str, object]]:
        return [
            {
                "history_kind": "version",
                "Key": fixture["receipt_key"],
                "VersionId": fixture["receipt_version"],
                "IsLatest": True,
            }
        ]

    def events(self, fixture: dict, terminal=None, trailing=None):
        payload = fixture["terminal"] if terminal is None else terminal
        lines = ["route startup"] + json.dumps(payload, indent=2, sort_keys=True).splitlines()
        if trailing is not None:
            lines.append(trailing)
        return [
            {
                "timestamp": 1000 + index,
                "ingestionTime": 2000 + index,
                "message": line,
            }
            for index, line in enumerate(lines)
        ]

    def test_terminal_capture_expects_current_guarded_x86_queue(self) -> None:
        params = json.loads((HERE.parents[0] / "infra/aws/nextflow.aws.json").read_text(encoding="utf-8"))

        self.assertEqual("diana-omics-prod-use1-hrd-x86", MODULE.EXPECTED_QUEUE_NAME)
        self.assertNotEqual(
            MODULE.EXPECTED_COMPUTE_ENVIRONMENT_NAME,
            MODULE.EXPECTED_QUEUE_NAME,
        )
        self.assertIn(MODULE.EXPECTED_QUEUE_NAME, params["daily_cost_guard_batch_job_queues"])
        self.assertIn(
            MODULE.EXPECTED_COMPUTE_ENVIRONMENT_NAME,
            params["daily_cost_guard_batch_compute_environments"],
        )

    def aws_side_effect(self, fixture: dict, **overrides):
        values = {
            "job": fixture["job"],
            "definition": fixture["definition"],
            "queue": fixture["queue"],
            "compute": fixture["compute"],
            "events": self.events(fixture),
            "metadata": fixture["metadata"],
            "history": fixture["history"],
            **overrides,
        }

        def invoke(region, *arguments):
            self.assertEqual(region, MODULE.REGION)
            operation = tuple(arguments[:2])
            if operation == ("batch", "describe-jobs"):
                return {"jobs": [copy.deepcopy(values["job"])]}
            if operation == ("batch", "describe-job-definitions"):
                self.assertIn(
                    MODULE.ROUTES[fixture["route"]]["job_definition_arn"],
                    arguments,
                )
                return {"jobDefinitions": [copy.deepcopy(values["definition"])]}
            if operation == ("batch", "describe-job-queues"):
                return {"jobQueues": [copy.deepcopy(values["queue"])]}
            if operation == ("batch", "describe-compute-environments"):
                return {"computeEnvironments": [copy.deepcopy(values["compute"])]}
            if operation == ("logs", "get-log-events"):
                expected_log_arguments = (
                    "logs",
                    "get-log-events",
                    "--log-group-name",
                    MODULE.LOG_GROUP,
                    "--log-stream-name",
                    fixture["log_stream"],
                    "--start-from-head",
                )
                if "--next-token" in arguments:
                    self.assertEqual(
                        arguments,
                        (*expected_log_arguments, "--next-token", "terminal-token"),
                    )
                    return {"events": [], "nextForwardToken": "terminal-token"}
                self.assertEqual(arguments, expected_log_arguments)
                return {
                    "events": copy.deepcopy(values["events"]),
                    "nextForwardToken": "terminal-token",
                }
            if operation == ("s3api", "get-bucket-versioning"):
                return {"Status": "Enabled"}
            if operation == ("s3api", "head-object"):
                self.assertEqual(
                    arguments,
                    (
                        "s3api",
                        "head-object",
                        "--bucket",
                        "diana-omics-private-results-172630973301-us-east-1",
                        "--key",
                        fixture["receipt_key"],
                        "--version-id",
                        fixture["receipt_version"],
                        "--checksum-mode",
                        "ENABLED",
                    ),
                )
                return copy.deepcopy(values["metadata"])
            if operation == ("s3api", "list-object-versions"):
                return copy.deepcopy(values["history"])
            raise AssertionError(f"unexpected mocked AWS CLI call: {arguments}")

        return invoke

    def get_side_effect(self, fixture: dict, content=None, metadata=None):
        downloaded = fixture["receipt_bytes"] if content is None else content
        response = fixture["metadata"] if metadata is None else metadata

        def invoke(region, bucket, key, version_id, destination):
            self.assertEqual(region, MODULE.REGION)
            self.assertEqual(key, fixture["receipt_key"])
            self.assertEqual(version_id, fixture["receipt_version"])
            destination.write_bytes(downloaded)
            return copy.deepcopy(response)

        return invoke

    def run_capture(self, args, fixture: dict, aws=None, get=None):
        aws = self.aws_side_effect(fixture) if aws is None else aws
        get = self.get_side_effect(fixture) if get is None else get
        with mock.patch.object(MODULE, "aws_json", side_effect=aws), mock.patch.object(MODULE, "get_exact_object", side_effect=get):
            return MODULE.capture(args)

    def test_receipt_history_consumes_key_and_version_markers(self):
        fixture = self.fixture()
        pages = [
            {
                "IsTruncated": True,
                "Versions": [{"Key": fixture["receipt_key"], "VersionId": "v1"}],
                "DeleteMarkers": [],
                "NextKeyMarker": fixture["receipt_key"],
                "NextVersionIdMarker": "v1",
            },
            {
                "IsTruncated": False,
                "Versions": [],
                "DeleteMarkers": [
                    {"Key": fixture["receipt_key"], "VersionId": "d1"}
                ],
            },
        ]

        with mock.patch.object(MODULE, "aws_json", side_effect=pages) as aws_json:
            self.assertEqual(
                MODULE.version_history(MODULE.REGION, "bucket", fixture["receipt_key"]),
                [
                    {
                        "Key": fixture["receipt_key"],
                        "VersionId": "v1",
                        "history_kind": "version",
                    },
                    {
                        "Key": fixture["receipt_key"],
                        "VersionId": "d1",
                        "history_kind": "delete_marker",
                    },
                ],
            )

        self.assertEqual(
            aws_json.call_args_list[1].args,
            (
                MODULE.REGION,
                "s3api",
                "list-object-versions",
                "--bucket",
                "bucket",
                "--prefix",
                fixture["receipt_key"],
                "--key-marker",
                fixture["receipt_key"],
                "--version-id-marker",
                "v1",
            ),
        )

    def test_receipt_history_rejects_missing_or_stalled_markers(self):
        fixture = self.fixture()
        cases = (
            {"NextKeyMarker": fixture["receipt_key"]},
            {"NextKeyMarker": True, "NextVersionIdMarker": "v1"},
            {
                "NextKeyMarker": fixture["receipt_key"],
                "NextVersionIdMarker": True,
            },
        )
        for case in cases:
            with self.subTest(case=case):
                missing_or_malformed = {
                    "IsTruncated": True,
                    "Versions": [],
                    "DeleteMarkers": [],
                    **case,
                }
                with mock.patch.object(
                    MODULE,
                    "aws_json",
                    return_value=missing_or_malformed,
                ):
                    with self.assertRaisesRegex(ValueError, "key/version markers"):
                        MODULE.version_history(
                            MODULE.REGION,
                            "bucket",
                            fixture["receipt_key"],
                        )

        stalled = {
            "IsTruncated": True,
            "Versions": [],
            "DeleteMarkers": [],
            "NextKeyMarker": fixture["receipt_key"],
            "NextVersionIdMarker": "v1",
        }
        with mock.patch.object(MODULE, "aws_json", side_effect=[stalled, stalled]):
            with self.assertRaisesRegex(ValueError, "did not advance"):
                MODULE.version_history(MODULE.REGION, "bucket", fixture["receipt_key"])

    def test_both_routes_succeed_and_emit_exclusive_mode_0600_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            for route in MODULE.ROUTES:
                with self.subTest(route=route):
                    fixture = self.fixture(route)
                    args = self.args(Path(temporary) / route, fixture)
                    result = self.run_capture(args, fixture)
                    self.assertEqual(result["status"], "passed")
                    self.assertEqual(result["batch"]["route"], route)
                    self.assertEqual(
                        result["receipt"]["version_id"],
                        fixture["receipt_version"],
                    )
                    self.assertEqual(args.receipt_output.read_bytes(), fixture["receipt_bytes"])
                    expected_anchor = (
                        json.dumps(
                            fixture["terminal"]["publication_anchor"],
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode()
                    self.assertEqual(args.anchor_output.read_bytes(), expected_anchor)
                    for path in (
                        args.capture_output,
                        args.receipt_output,
                        args.anchor_output,
                    ):
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    persisted = json.loads(args.capture_output.read_text())
                    self.assertTrue(all(persisted["checks"].values()))
                    self.assertTrue(all(persisted["batch"]["checks"].values()))
                    anchor_binding = persisted["cloudwatch"]["publication_anchor_local"]
                    self.assertEqual(anchor_binding["output"], str(args.anchor_output.resolve()))
                    self.assertEqual(
                        anchor_binding["sha256"],
                        hashlib.sha256(expected_anchor).hexdigest(),
                    )
                    self.assertEqual(anchor_binding["bytes"], len(expected_anchor))
                    receipt, rows, *_ = DOWNLOAD_MODULE.validate_publication(
                        args.receipt_output,
                        args.anchor_output,
                        fixture["kms"],
                    )
                    self.assertEqual(receipt["route"], route)
                    self.assertEqual(len(rows), 4)

    def test_refuses_existing_output_before_any_aws_call(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary), fixture)
            args.receipt_output.write_text("do not replace")
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                    MODULE.capture(args)
            mocked.assert_not_called()
            self.assertEqual(args.receipt_output.read_text(), "do not replace")

    def test_rejects_three_output_aliases_and_each_existing_output_preflight(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            aliases = self.args(base / "aliases", fixture)
            aliases.anchor_output = aliases.capture_output
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(ValueError, "must be distinct"):
                    MODULE.capture(aliases)
            mocked.assert_not_called()

            for name in ("capture_output", "receipt_output", "anchor_output"):
                with self.subTest(name=name):
                    args = self.args(base / name, fixture)
                    path = getattr(args, name)
                    path.parent.mkdir(parents=True)
                    path.write_text("preserve")
                    with mock.patch.object(MODULE, "aws_json") as mocked:
                        with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                            MODULE.capture(args)
                    mocked.assert_not_called()
                    self.assertEqual(path.read_text(), "preserve")

            symlink_args = self.args(base / "symlink", fixture)
            symlink_args.anchor_output.parent.mkdir(parents=True)
            symlink_args.anchor_output.symlink_to(base / "absent-target.json")
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(FileExistsError, "may not be a symlink"):
                    MODULE.capture(symlink_args)
            mocked.assert_not_called()
            self.assertTrue(symlink_args.anchor_output.is_symlink())

            symlink_parent = base / "real-parent"
            symlink_parent.mkdir()
            symlink_parent_args = self.args(base / "linked-parent", fixture)
            symlink_parent_args.capture_output.parent.symlink_to(
                symlink_parent,
                target_is_directory=True,
            )
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(
                    FileExistsError,
                    "parent may not be a symlink",
                ):
                    MODULE.capture(symlink_parent_args)
            mocked.assert_not_called()
            self.assertFalse((symlink_parent / "capture.json").exists())

    def test_three_output_atomic_reservation_rolls_back_on_racing_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.json"
            collision = root / "collision.json"
            third = root / "third.json"
            real_open = MODULE.os.open

            def racing_open(path, flags, mode):
                if Path(path) == collision:
                    collision.write_bytes(b"racer-owned")
                    raise FileExistsError("simulated concurrent creator")
                return real_open(path, flags, mode)

            with mock.patch.object(MODULE.os, "open", side_effect=racing_open):
                with self.assertRaises(FileExistsError):
                    MODULE.create_private_outputs(
                        [
                            (first, b"first"),
                            (collision, b"ours"),
                            (third, b"third"),
                        ]
                    )
            self.assertFalse(first.exists())
            self.assertEqual(collision.read_bytes(), b"racer-owned")
            self.assertFalse(third.exists())

    def test_three_output_create_rejects_symlinked_parents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.create_private_outputs(
                    [(linked_parent / "capture.json", b"capture")]
                )

            self.assertFalse((real_parent / "capture.json").exists())

    def test_three_output_create_rejects_nested_symlinked_parents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.create_private_outputs(
                    [(linked_parent / "missing" / "capture.json", b"capture")]
                )

            self.assertFalse((real_parent / "missing" / "capture.json").exists())

    def test_three_output_create_rejects_existing_dir_below_symlinked_parent(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-parent"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.create_private_outputs(
                    [(linked_parent / "existing" / "capture.json", b"capture")]
                )

            self.assertFalse((real_parent / "existing" / "capture.json").exists())

    def test_three_output_atomic_write_failure_removes_all_reserved_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]
            with mock.patch.object(MODULE.os, "fsync", side_effect=OSError("simulated fsync failure")):
                with self.assertRaises(OSError):
                    MODULE.create_private_outputs([(path, f"content-{index}".encode()) for index, path in enumerate(paths)])
            self.assertTrue(all(not path.exists() for path in paths))

    def test_three_output_atomic_fsyncs_unique_parent_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_parent = root / "first"
            second_parent = root / "second"
            rows = [
                (first_parent / "capture.json", b"capture"),
                (first_parent / "anchor.json", b"anchor"),
                (second_parent / "receipt.json", b"receipt"),
            ]

            with mock.patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                MODULE.create_private_outputs(rows)

            self.assertEqual(
                fsync_directory.mock_calls,
                [mock.call(first_parent), mock.call(second_parent)],
            )

    def test_three_output_parent_fsync_failure_removes_all_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=OSError("simulated parent fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "simulated parent fsync failure"),
            ):
                MODULE.create_private_outputs([(path, f"content-{index}".encode()) for index, path in enumerate(paths)])

            self.assertTrue(all(not path.exists() for path in paths))

    def test_three_output_rehashes_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                real_fsync_directory(parent)
                paths[1].write_bytes(b"tampered")

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.create_private_outputs(
                    [(path, f"content-{index}".encode()) for index, path in enumerate(paths)]
                )

            self.assertTrue(all(not path.exists() for path in paths))

    def test_three_output_rejects_same_byte_leaf_replacement_between_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]
            replacement = root / "replacement.json"
            replacement.write_bytes(b"content-1")
            replacement.chmod(0o600)
            real_read = MODULE.read_private_output_once
            swapped = False

            def replace_leaf_after_first_read(path: Path):
                nonlocal swapped
                result = real_read(path)
                if path == paths[1] and not swapped:
                    replacement.replace(path)
                    swapped = True
                return result

            with (
                mock.patch.object(
                    MODULE,
                    "read_private_output_once",
                    side_effect=replace_leaf_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.create_private_outputs(
                    [
                        (path, f"content-{index}".encode())
                        for index, path in enumerate(paths)
                    ]
                )

            self.assertTrue(swapped)
            self.assertTrue(all(not path.exists() for path in paths))

    def test_three_output_rechecks_mode_after_parent_fsync(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]
            real_fsync_directory = MODULE.fsync_directory

            def chmod_after_parent_fsync(parent: Path) -> None:
                real_fsync_directory(parent)
                paths[1].chmod(0o644)

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=chmod_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output mode changed during write",
                ),
            ):
                MODULE.create_private_outputs(
                    [(path, f"content-{index}".encode()) for index, path in enumerate(paths)]
                )

            self.assertTrue(all(not path.exists() for path in paths))

    def test_three_output_rejects_symlink_swap_before_final_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]
            relocated = root / "relocated.json"
            real_is_file = Path.is_file
            swapped = False

            def swap_after_first_private_output_file_check(path: Path) -> bool:
                nonlocal swapped
                result = real_is_file(path)
                if path == paths[1] and result and not swapped:
                    path.unlink()
                    relocated.write_bytes(b"content-1")
                    relocated.chmod(0o600)
                    path.symlink_to(relocated)
                    swapped = True
                return result

            with (
                mock.patch.object(
                    Path,
                    "is_file",
                    autospec=True,
                    side_effect=swap_after_first_private_output_file_check,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.create_private_outputs(
                    [
                        (path, f"content-{index}".encode())
                        for index, path in enumerate(paths)
                    ]
                )

            self.assertTrue(swapped)
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertEqual(relocated.read_bytes(), b"content-1")

    def test_three_output_rejects_symlink_swap_before_final_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]
            relocated = root / "relocated.json"
            real_open = MODULE.os.open
            swapped = False

            def swap_before_verify_open(
                path_arg: Path,
                flags: int,
                *args: int,
            ) -> int:
                nonlocal swapped
                if path_arg == paths[1] and not args and not swapped:
                    path_arg.unlink()
                    relocated.write_bytes(b"content-1")
                    relocated.chmod(0o600)
                    path_arg.symlink_to(relocated)
                    swapped = True
                return real_open(path_arg, flags, *args)

            with (
                mock.patch.object(MODULE.os, "open", side_effect=swap_before_verify_open),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.create_private_outputs(
                    [
                        (path, f"content-{index}".encode())
                        for index, path in enumerate(paths)
                    ]
                )

            self.assertTrue(swapped)
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertEqual(relocated.read_bytes(), b"content-1")

    def test_three_output_rejects_mode_change_before_final_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / f"{index}.json" for index in range(3)]
            real_open = MODULE.os.open
            chmodded = False

            def chmod_before_verify_open(
                path_arg: Path,
                flags: int,
                *args: int,
            ) -> int:
                nonlocal chmodded
                if path_arg == paths[1] and not args and not chmodded:
                    path_arg.chmod(0o644)
                    chmodded = True
                return real_open(path_arg, flags, *args)

            with (
                mock.patch.object(MODULE.os, "open", side_effect=chmod_before_verify_open),
                self.assertRaisesRegex(
                    ValueError,
                    "private output mode changed during write",
                ),
            ):
                MODULE.create_private_outputs(
                    [
                        (path, f"content-{index}".encode())
                        for index, path in enumerate(paths)
                    ]
                )

            self.assertTrue(chmodded)
            self.assertTrue(all(not path.exists() for path in paths))

    def test_rejects_wrong_revision_queue_or_non_x86_compute_environment(self):
        fixture = self.fixture()
        wrong_definition = copy.deepcopy(fixture["job"])
        wrong_definition["jobDefinition"] = MODULE.ROUTES[fixture["route"]]["job_definition_arn"][:-1] + "2"
        wrong_queue = copy.deepcopy(fixture["queue"])
        wrong_queue["computeEnvironmentOrder"][0]["computeEnvironment"] += "-other"
        wrong_compute = copy.deepcopy(fixture["compute"])
        wrong_compute["computeResources"]["instanceTypes"] = ["c7g", "m7g", "r7g"]
        cases = (
            ("revision", {"job": wrong_definition}),
            ("queue", {"queue": wrong_queue}),
            ("compute", {"compute": wrong_compute}),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for label, overrides in cases:
                with self.subTest(label=label), self.assertRaisesRegex(ValueError, "Batch identity failed"):
                    self.run_capture(
                        self.args(Path(temporary) / label, fixture),
                        fixture,
                        aws=self.aws_side_effect(fixture, **overrides),
                    )

    def test_rejects_forged_contract_submission_or_static_definition_override(self):
        fixture = self.fixture()
        cases = []
        static_name, static_value = next(iter(MODULE.ROUTES[fixture["route"]]["definition_environment"].items()))
        for name, value in (
            ("HRD_CROSSCHECK_INPUT_CONTRACT_VERSION_ID", "forged-version"),
            ("HRD_CROSSCHECK_SUBMISSION_ID", "20260717T200000Z-forged999"),
            ("EXTRA_UNREVIEWED", "forged"),
            (static_name, static_value),
        ):
            job = copy.deepcopy(fixture["job"])
            job["container"]["environment"] = [row for row in job["container"]["environment"] if row["name"] != name]
            job["container"]["environment"].append({"name": name, "value": value})
            cases.append((name, job))
        with tempfile.TemporaryDirectory() as temporary:
            for label, job in cases:
                with self.subTest(label=label), self.assertRaisesRegex(ValueError, "Batch identity failed"):
                    self.run_capture(
                        self.args(Path(temporary) / label, fixture),
                        fixture,
                        aws=self.aws_side_effect(fixture, job=job),
                    )

    def test_rejects_retry_multiple_attempts_nonzero_exit_and_log_mismatch(self):
        fixture = self.fixture()
        jobs = []
        retry = copy.deepcopy(fixture["job"])
        retry["retryStrategy"] = {"attempts": 2}
        jobs.append(retry)
        attempts = copy.deepcopy(fixture["job"])
        attempts["attempts"].append(copy.deepcopy(attempts["attempts"][0]))
        jobs.append(attempts)
        exit_one = copy.deepcopy(fixture["job"])
        exit_one["attempts"][0]["container"]["exitCode"] = 1
        jobs.append(exit_one)
        wrong_log = copy.deepcopy(fixture["job"])
        wrong_log["attempts"][0]["container"]["logStreamName"] += "-forged"
        jobs.append(wrong_log)
        with tempfile.TemporaryDirectory() as temporary:
            for index, job in enumerate(jobs):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    self.run_capture(
                        self.args(Path(temporary) / str(index), fixture),
                        fixture,
                        aws=self.aws_side_effect(fixture, job=job),
                    )

    def test_rejects_coerced_exit_codes(self):
        mutations = (
            (
                "job bool",
                lambda job: job["container"].__setitem__("exitCode", False),
            ),
            (
                "job float",
                lambda job: job["container"].__setitem__("exitCode", 0.0),
            ),
            (
                "attempt bool",
                lambda job: job["attempts"][0]["container"].__setitem__(
                    "exitCode",
                    False,
                ),
            ),
            (
                "attempt float",
                lambda job: job["attempts"][0]["container"].__setitem__(
                    "exitCode",
                    0.0,
                ),
            ),
        )
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            for label, mutate in mutations:
                with self.subTest(label=label), self.assertRaises(ValueError):
                    job = copy.deepcopy(fixture["job"])
                    mutate(job)
                    self.run_capture(
                        self.args(Path(temporary) / label, fixture),
                        fixture,
                        aws=self.aws_side_effect(fixture, job=job),
                    )

    def test_batch_identity_requires_exact_job_name_and_log_stream_text(self):
        fixture = self.fixture()
        cases = (
            (
                "job_name",
                lambda job, compute: job.__setitem__("jobName", 123),
                "failed job_name_text",
            ),
            (
                "job_log_stream",
                lambda job, compute: job["container"].__setitem__(
                    "logStreamName",
                    123,
                ),
                "failed log_stream_exact",
            ),
            (
                "attempt_log_stream",
                lambda job, compute: job["attempts"][0]["container"].__setitem__(
                    "logStreamName",
                    123,
                ),
                "failed log_stream_exact",
            ),
            (
                "x86_instance_type",
                lambda job, compute: compute["computeResources"].__setitem__(
                    "instanceTypes",
                    ["r7i", "m7i", 7],
                ),
                "failed x86_compute_environment_live_exact",
            ),
        )

        for label, mutate, error in cases:
            with self.subTest(label=label):
                job = copy.deepcopy(fixture["job"])
                compute = copy.deepcopy(fixture["compute"])
                mutate(job, compute)

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_job(
                        job,
                        fixture["definition"],
                        fixture["queue"],
                        compute,
                        self.args(Path("unused"), fixture),
                        fixture["submission_environment"],
                    )

    def test_batch_identity_check_map_must_be_exact(self):
        fixture = self.fixture()
        cases = (
            (
                {
                    **MODULE.EXPECTED_BATCH_IDENTITY_CHECKS,
                    "future_route_batch_identity_check": True,
                },
                "missing future_route_batch_identity_check",
            ),
            (
                {
                    name: value
                    for name, value in MODULE.EXPECTED_BATCH_IDENTITY_CHECKS.items()
                    if name != "definition_log_exact"
                },
                "unexpected definition_log_exact",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(MODULE, "EXPECTED_BATCH_IDENTITY_CHECKS", expected),
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.validate_job(
                    fixture["job"],
                    fixture["definition"],
                    fixture["queue"],
                    fixture["compute"],
                    self.args(Path("unused"), fixture),
                    fixture["submission_environment"],
                )

    def test_failed_batch_identity_check_reports_exact_key(self):
        fixture = self.fixture()
        job = copy.deepcopy(fixture["job"])
        job["stoppedAt"] = 99

        with self.assertRaisesRegex(ValueError, "failed terminal_timestamps"):
            MODULE.validate_job(
                job,
                fixture["definition"],
                fixture["queue"],
                fixture["compute"],
                self.args(Path("unused"), fixture),
                fixture["submission_environment"],
            )

    def test_batch_runtime_numbers_must_be_exact_integers(self):
        cases = (
            ("job_retry", {"job_retry": 1.0}, "failed one_retry_attempt"),
            ("definition_revision", {"definition_revision": 3.0}, "failed definition_identity_exact"),
            ("definition_retry", {"definition_retry": True}, "failed definition_identity_exact"),
            ("definition_timeout", {"definition_timeout": 21600.0}, "failed definition_identity_exact"),
            ("vcpus", {"vcpus": 4.0}, "failed definition_container_exact"),
            ("memory", {"memory": 16384.0}, "failed definition_container_exact"),
            ("min_vcpus", {"min_vcpus": 0.0}, "failed x86_compute_environment_live_exact"),
            ("max_vcpus", {"max_vcpus": 128.0}, "failed x86_compute_environment_live_exact"),
        )

        for label, values, error in cases:
            with self.subTest(label=label):
                fixture = self.fixture()
                if "job_retry" in values:
                    fixture["job"]["retryStrategy"]["attempts"] = values["job_retry"]
                if "definition_revision" in values:
                    fixture["definition"]["revision"] = values["definition_revision"]
                if "definition_retry" in values:
                    fixture["definition"]["retryStrategy"]["attempts"] = values[
                        "definition_retry"
                    ]
                if "definition_timeout" in values:
                    fixture["definition"]["timeout"]["attemptDurationSeconds"] = values[
                        "definition_timeout"
                    ]
                if "vcpus" in values:
                    fixture["definition"]["containerProperties"]["vcpus"] = values[
                        "vcpus"
                    ]
                if "memory" in values:
                    fixture["definition"]["containerProperties"]["memory"] = values[
                        "memory"
                    ]
                if "min_vcpus" in values:
                    fixture["compute"]["computeResources"]["minvCpus"] = values[
                        "min_vcpus"
                    ]
                if "max_vcpus" in values:
                    fixture["compute"]["computeResources"]["maxvCpus"] = values[
                        "max_vcpus"
                    ]

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_job(
                        fixture["job"],
                        fixture["definition"],
                        fixture["queue"],
                        fixture["compute"],
                        self.args(Path("unused"), fixture),
                        fixture["submission_environment"],
                    )

    def test_batch_terminal_timestamps_must_be_exact_integers(self):
        cases = (
            ("startedAt", 100.0),
            ("startedAt", True),
            ("startedAt", "100"),
            ("stoppedAt", 200.0),
            ("stoppedAt", True),
            ("stoppedAt", "200"),
        )

        for field, value in cases:
            with self.subTest(field=field, value=value):
                fixture = self.fixture()
                fixture["job"][field] = value

                with self.assertRaisesRegex(ValueError, "failed terminal_timestamps"):
                    MODULE.validate_job(
                        fixture["job"],
                        fixture["definition"],
                        fixture["queue"],
                        fixture["compute"],
                        self.args(Path("unused"), fixture),
                        fixture["submission_environment"],
                    )

    def test_batch_identity_checks_avoid_raw_string_coercion(self):
        module = ast.parse(
            (SCRIPT_DIR / "capture_route_terminal.py").read_text(encoding="utf-8")
        )
        raw_batch_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in ("logStreamName", "jobName", "instanceTypes")
            )
        ]

        self.assertEqual(raw_batch_coercions, [])

    def test_cloudwatch_event_timestamps_must_be_exact_integers(self):
        cases = (
            ("float", 1000.0, "not an exact positive integer"),
            ("bool", True, "not an exact positive integer"),
            ("string", "1000", "not an exact positive integer"),
            ("unordered", 999, "not ordered"),
        )

        for label, value, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = self.fixture()
                events = self.events(fixture)
                events[-1]["timestamp"] = value

                with self.assertRaisesRegex(ValueError, error):
                    self.run_capture(
                        self.args(Path(temporary), fixture),
                        fixture,
                        aws=self.aws_side_effect(fixture, events=events),
                    )

    def test_terminal_parser_rejects_duplicate_anchor_and_trailing_output(self):
        fixture = self.fixture()
        valid = self.events(fixture)
        duplicate = valid + valid
        trailing = self.events(fixture, trailing="unexpected output")
        for label, events in (("duplicate", duplicate), ("trailing", trailing)):
            with self.subTest(label=label), self.assertRaises(ValueError):
                MODULE.parse_terminal_payload(events)

    def test_terminal_parser_rejects_duplicate_object_names(self):
        fixture = self.fixture()
        text = json.dumps(fixture["terminal"], indent=2, sort_keys=True)
        current = '    "schema_version": '
        if text.count(current) != 1:
            raise AssertionError(
                "expected exactly one terminal publication schema field"
            )
        duplicate = text.replace(
            current,
            f'{current}0,\n{current}',
            1,
        )
        events = [
            {
                "timestamp": 1000 + index,
                "ingestionTime": 2000 + index,
                "message": line,
            }
            for index, line in enumerate(duplicate.splitlines())
        ]

        with self.assertRaisesRegex(
            ValueError,
            "duplicate JSON object name in terminal route payload: schema_version",
        ):
            MODULE.parse_terminal_payload(events)

    def test_logged_anchor_cannot_redirect_receipt_or_route_output(self):
        fixture = self.fixture()
        redirects = []
        receipt = copy.deepcopy(fixture["terminal"])
        receipt["publication_anchor"]["receipt_uri"] = fixture["receipt_prefix"] + "latest.json"
        redirects.append(receipt)
        output = copy.deepcopy(fixture["terminal"])
        output["publication_anchor"]["route_output_uri"] += "forged/"
        redirects.append(output)
        with tempfile.TemporaryDirectory() as temporary:
            for index, terminal in enumerate(redirects):
                with self.subTest(index=index), self.assertRaisesRegex(ValueError, "anchor failed"):
                    self.run_capture(
                        self.args(Path(temporary) / str(index), fixture),
                        fixture,
                        aws=self.aws_side_effect(fixture, events=self.events(fixture, terminal)),
                    )

    def test_rejects_logged_anchor_with_missing_unexpected_or_failed_check(self):
        fixture = self.fixture()
        cases = {}
        for label, mutate in (
            ("missing", lambda checks: checks.pop("sha256_exact")),
            ("unexpected", lambda checks: checks.__setitem__("forged_extra", True)),
            ("failed", lambda checks: checks.__setitem__("exact_kms", False)),
            ("truthy-integer", lambda checks: checks.__setitem__("sha256_exact", 1)),
        ):
            terminal = copy.deepcopy(fixture["terminal"])
            mutate(terminal["publication_anchor"]["checks"])
            cases[label] = terminal

        with tempfile.TemporaryDirectory() as temporary:
            for label, terminal in cases.items():
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError,
                    "anchor failed",
                ):
                    self.run_capture(
                        self.args(Path(temporary) / label, fixture),
                        fixture,
                        aws=self.aws_side_effect(
                            fixture,
                            events=self.events(fixture, terminal),
                        ),
                    )

    def test_logged_anchor_outer_check_map_must_be_exact(self):
        fixture = self.fixture()
        cases = (
            (
                {
                    **MODULE.EXPECTED_LOGGED_PUBLICATION_ANCHOR_CHECKS,
                    "future_logged_anchor_check": True,
                },
                "missing future_logged_anchor_check",
            ),
            (
                {
                    name: value
                    for name, value in MODULE.EXPECTED_LOGGED_PUBLICATION_ANCHOR_CHECKS.items()
                    if name != "receipt_uri_content_addressed"
                },
                "unexpected receipt_uri_content_addressed",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(
                    MODULE,
                    "EXPECTED_LOGGED_PUBLICATION_ANCHOR_CHECKS",
                    expected,
                ),
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.validate_logged_anchor(
                    fixture["terminal"],
                    self.args(Path("unused"), fixture),
                    fixture["submission_environment"],
                )

    def test_failed_logged_anchor_outer_check_reports_exact_key(self):
        fixture = self.fixture()
        terminal = copy.deepcopy(fixture["terminal"])
        terminal["publication_anchor"]["route_output_uri"] += "forged/"

        with self.assertRaisesRegex(ValueError, "failed route_output_uri_exact"):
            MODULE.validate_logged_anchor(
                terminal,
                self.args(Path("unused"), fixture),
                fixture["submission_environment"],
            )

    def test_logged_anchor_requires_exact_schema_version(self):
        fixture = self.fixture()
        terminal = copy.deepcopy(fixture["terminal"])
        terminal["publication_anchor"]["schema_version"] = 1.0

        with self.assertRaisesRegex(ValueError, "failed anchor_schema_status"):
            MODULE.validate_logged_anchor(
                terminal,
                self.args(Path("unused"), fixture),
                fixture["submission_environment"],
            )

    def test_logged_anchor_receipt_bytes_must_be_exact_int(self):
        fixture = self.fixture()
        terminal = copy.deepcopy(fixture["terminal"])
        terminal["publication_anchor"]["receipt_bytes"] = float(
            terminal["publication_anchor"]["receipt_bytes"]
        )

        with self.assertRaisesRegex(ValueError, "failed receipt_bytes_positive"):
            MODULE.validate_logged_anchor(
                terminal,
                self.args(Path("unused"), fixture),
                fixture["submission_environment"],
            )

    def test_logged_anchor_rejects_coerced_sha256_and_version_id(self):
        fixture = self.fixture()
        cases = (
            (
                "numeric_sha256",
                "receipt_sha256",
                int("1" * 64),
                "failed receipt_sha256_well_formed",
            ),
            (
                "numeric_version",
                "receipt_version_id",
                1234567890,
                "failed receipt_version_nonempty",
            ),
        )

        for label, field, value, error in cases:
            with self.subTest(label=label):
                terminal = copy.deepcopy(fixture["terminal"])
                terminal["publication_anchor"][field] = value

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_logged_anchor(
                        terminal,
                        self.args(Path("unused"), fixture),
                        fixture["submission_environment"],
                    )

    def test_receipt_rejects_contract_route_submission_and_inventory_tampering(self):
        fixture = self.fixture()
        receipts = []
        contract = copy.deepcopy(fixture["receipt"])
        contract["contract"]["version_id"] = "forged"
        receipts.append(contract)
        route = copy.deepcopy(fixture["receipt"])
        route["route"] = "sequenza_scarhrd"
        receipts.append(route)
        submission = copy.deepcopy(fixture["receipt"])
        submission["submission_id"] = "20260717T200000Z-forged999"
        receipts.append(submission)
        output = copy.deepcopy(fixture["receipt"])
        output["objects"][0]["key"] += "-other"
        receipts.append(output)
        audit = copy.deepcopy(fixture["receipt"])
        audit["history_audit"][0]["version_id"] = "forged"
        receipts.append(audit)
        location = {
            "key": fixture["receipt_key"],
            "version_id": fixture["receipt_version"],
            "sha256": fixture["receipt_sha"],
            "bytes": len(fixture["receipt_bytes"]),
        }
        args = self.args(Path("unused"), fixture)
        history = [
            {
                "history_kind": "version",
                "Key": fixture["receipt_key"],
                "VersionId": fixture["receipt_version"],
                "IsLatest": True,
            }
        ]
        for index, receipt_value in enumerate(receipts):
            content = (json.dumps(receipt_value, indent=2, sort_keys=True) + "\n").encode()
            local_sha = hashlib.sha256(content).hexdigest()
            checksum = base64.b64encode(bytes.fromhex(local_sha)).decode()
            metadata = {
                **fixture["metadata"],
                "ContentLength": len(content),
                "ChecksumSHA256": checksum,
                "Metadata": {"sha256": local_sha},
            }
            local_location = {
                **location,
                "sha256": local_sha,
                "bytes": len(content),
            }
            with self.subTest(index=index), self.assertRaises(ValueError):
                MODULE.validate_exact_receipt(
                    content,
                    metadata,
                    metadata,
                    history,
                    local_location,
                    args,
                    fixture["submission_environment"],
                )

    def test_receipt_rejects_missing_unexpected_or_failed_check_maps(self):
        fixture = self.fixture()
        cases = {}
        for location, label, mutate in (
            (
                "receipt",
                "missing",
                lambda receipt: receipt["checks"].pop("all_outputs_create_only"),
            ),
            (
                "receipt",
                "unexpected",
                lambda receipt: receipt["checks"].__setitem__("forged_extra", True),
            ),
            (
                "receipt",
                "failed",
                lambda receipt: receipt["checks"].__setitem__(
                    "all_output_versions_exact",
                    False,
                ),
            ),
            (
                "receipt",
                "truthy-integer",
                lambda receipt: receipt["checks"].__setitem__(
                    "all_outputs_create_only",
                    1,
                ),
            ),
            (
                "object",
                "missing",
                lambda receipt: receipt["objects"][0]["checks"].pop("create_only_put"),
            ),
            (
                "object",
                "unexpected",
                lambda receipt: receipt["objects"][0]["checks"].__setitem__(
                    "forged_extra",
                    True,
                ),
            ),
            (
                "object",
                "failed",
                lambda receipt: receipt["objects"][0]["checks"].__setitem__(
                    "version_exact",
                    False,
                ),
            ),
            (
                "object",
                "truthy-integer",
                lambda receipt: receipt["objects"][0]["checks"].__setitem__(
                    "version_exact",
                    1,
                ),
            ),
            (
                "history",
                "missing",
                lambda receipt: receipt["history_audit"][0]["checks"].pop(
                    "checksum_sha256_exact"
                ),
            ),
            (
                "history",
                "unexpected",
                lambda receipt: receipt["history_audit"][0]["checks"].__setitem__(
                    "forged_extra",
                    True,
                ),
            ),
            (
                "history",
                "failed",
                lambda receipt: receipt["history_audit"][0]["checks"].__setitem__(
                    "exact_kms",
                    False,
                ),
            ),
            (
                "history",
                "truthy-integer",
                lambda receipt: receipt["history_audit"][0]["checks"].__setitem__(
                    "exact_kms",
                    1,
                ),
            ),
        ):
            receipt = copy.deepcopy(fixture["receipt"])
            mutate(receipt)
            cases[f"{location}-{label}"] = receipt

        location = {
            "key": fixture["receipt_key"],
            "version_id": fixture["receipt_version"],
            "bytes": len(fixture["receipt_bytes"]),
        }
        args = self.args(Path("unused"), fixture)
        history = [
            {
                "history_kind": "version",
                "Key": fixture["receipt_key"],
                "VersionId": fixture["receipt_version"],
                "IsLatest": True,
            }
        ]
        for label, receipt_value in cases.items():
            content = (json.dumps(receipt_value, indent=2, sort_keys=True) + "\n").encode()
            local_sha = hashlib.sha256(content).hexdigest()
            checksum = base64.b64encode(bytes.fromhex(local_sha)).decode()
            metadata = {
                **fixture["metadata"],
                "ContentLength": len(content),
                "ChecksumSHA256": checksum,
                "Metadata": {"sha256": local_sha},
            }
            with self.subTest(label=label), self.assertRaises(ValueError):
                MODULE.validate_exact_receipt(
                    content,
                    metadata,
                    metadata,
                    history,
                    {**location, "sha256": local_sha},
                    args,
                    fixture["submission_environment"],
                )

    def test_output_inventory_check_map_must_be_exact(self):
        fixture = self.fixture()
        cases = (
            (
                {
                    **MODULE.EXPECTED_OUTPUT_INVENTORY_CHECKS,
                    "future_inventory_check": True,
                },
                "missing future_inventory_check",
            ),
            (
                {
                    name: value
                    for name, value in MODULE.EXPECTED_OUTPUT_INVENTORY_CHECKS.items()
                    if name != "history_audit_binds_every_output"
                },
                "unexpected history_audit_binds_every_output",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(MODULE, "EXPECTED_OUTPUT_INVENTORY_CHECKS", expected),
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.validate_output_rows(
                    fixture["receipt"],
                    fixture["route_output"],
                    fixture["kms"],
                )

    def test_route_output_content_length_must_be_exact_int(self):
        for value in (True, 101.0, "101"):
            with self.subTest(value=value):
                fixture = self.fixture()
                fixture["receipt"]["objects"][0]["content_length"] = value

                with self.assertRaisesRegex(
                    ValueError,
                    "route receipt output row failed",
                ):
                    MODULE.validate_output_rows(
                        fixture["receipt"],
                        fixture["route_output"],
                        fixture["kms"],
                    )

    def test_output_rows_reject_coerced_sha256_and_version_id(self):
        cases = (
            (
                "numeric_object_sha256",
                lambda receipt: (
                    receipt["objects"][0].__setitem__("sha256", int("1" * 64)),
                    receipt["history_audit"][0].__setitem__("sha256", int("1" * 64)),
                ),
                "output row",
            ),
            (
                "numeric_object_version",
                lambda receipt: (
                    receipt["objects"][0].__setitem__("version_id", 1234567890),
                    receipt["history_audit"][0].__setitem__(
                        "version_id",
                        1234567890,
                    ),
                ),
                "output row",
            ),
            (
                "numeric_history_sha256",
                lambda receipt: receipt["history_audit"][0].__setitem__(
                    "sha256",
                    int("1" * 64),
                ),
                "history audit",
            ),
            (
                "numeric_history_version",
                lambda receipt: receipt["history_audit"][0].__setitem__(
                    "version_id",
                    1234567890,
                ),
                "history audit",
            ),
        )

        for label, mutate, error in cases:
            with self.subTest(label=label):
                fixture = self.fixture()
                mutate(fixture["receipt"])

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_output_rows(
                        fixture["receipt"],
                        fixture["route_output"],
                        fixture["kms"],
                    )

    def test_failed_output_inventory_check_reports_exact_key(self):
        fixture = self.fixture()
        receipt = copy.deepcopy(fixture["receipt"])
        receipt["objects"] = receipt["objects"][:-1]
        receipt["history_audit"] = receipt["history_audit"][:-1]

        with self.assertRaisesRegex(
            ValueError,
            "failed successful_report_products_present",
        ):
            MODULE.validate_output_rows(
                receipt,
                fixture["route_output"],
                fixture["kms"],
            )

    def test_exact_receipt_download_check_map_must_be_exact(self):
        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)
        cases = (
            (
                {
                    **MODULE.EXPECTED_EXACT_RECEIPT_DOWNLOAD_CHECKS,
                    "future_exact_receipt_check": True,
                },
                "missing future_exact_receipt_check",
            ),
            (
                {
                    name: value
                    for name, value in MODULE.EXPECTED_EXACT_RECEIPT_DOWNLOAD_CHECKS.items()
                    if name != "head_metadata_sha256_exact"
                },
                "unexpected head_metadata_sha256_exact",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(
                    MODULE,
                    "EXPECTED_EXACT_RECEIPT_DOWNLOAD_CHECKS",
                    expected,
                ),
                self.assertRaisesRegex(ValueError, error),
            ):
                MODULE.validate_exact_receipt(
                    fixture["receipt_bytes"],
                    fixture["metadata"],
                    fixture["metadata"],
                    self.receipt_history_rows(fixture),
                    self.receipt_location(fixture),
                    args,
                    fixture["submission_environment"],
                )

    def test_failed_exact_receipt_download_check_reports_exact_key(self):
        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)
        get_response = {**fixture["metadata"], "VersionId": "wrong-version"}

        with self.assertRaisesRegex(ValueError, "failed get_version_exact"):
            MODULE.validate_exact_receipt(
                fixture["receipt_bytes"],
                get_response,
                fixture["metadata"],
                self.receipt_history_rows(fixture),
                self.receipt_location(fixture),
                args,
                fixture["submission_environment"],
            )

    def test_exact_receipt_rejects_duplicate_object_names(self):
        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)
        content = write_duplicate_json_field(
            fixture["receipt_bytes"],
            "schema_version",
            0,
        )
        local_sha = hashlib.sha256(content).hexdigest()
        checksum = base64.b64encode(bytes.fromhex(local_sha)).decode()
        metadata = {
            **fixture["metadata"],
            "ContentLength": len(content),
            "ChecksumSHA256": checksum,
            "Metadata": {"sha256": local_sha},
        }

        with self.assertRaisesRegex(
            ValueError,
            "duplicate JSON object name in downloaded route receipt: schema_version",
        ):
            MODULE.validate_exact_receipt(
                content,
                metadata,
                metadata,
                self.receipt_history_rows(fixture),
                {
                    **self.receipt_location(fixture),
                    "sha256": local_sha,
                    "bytes": len(content),
                },
                args,
                fixture["submission_environment"],
            )

    def test_exact_receipt_content_lengths_must_be_exact_ints(self):
        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)
        for response_name in ("GET", "HEAD"):
            with self.subTest(response_name=response_name):
                get_response = dict(fixture["metadata"])
                head_response = dict(fixture["metadata"])
                if response_name == "GET":
                    get_response["ContentLength"] = float(len(fixture["receipt_bytes"]))
                    expected_check = "get_bytes_exact"
                else:
                    head_response["ContentLength"] = float(len(fixture["receipt_bytes"]))
                    expected_check = "head_bytes_exact"

                with self.assertRaisesRegex(ValueError, f"failed {expected_check}"):
                    MODULE.validate_exact_receipt(
                        fixture["receipt_bytes"],
                        get_response,
                        head_response,
                        self.receipt_history_rows(fixture),
                        self.receipt_location(fixture),
                        args,
                        fixture["submission_environment"],
                    )

    def test_exact_receipt_checksums_must_be_exact_strings(self):
        class CoercibleChecksum:
            def __str__(self) -> str:
                return fixture["metadata"]["ChecksumSHA256"]

        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)
        for response_name in ("GET", "HEAD"):
            with self.subTest(response_name=response_name):
                get_response = dict(fixture["metadata"])
                head_response = dict(fixture["metadata"])
                checksum = CoercibleChecksum()
                if response_name == "GET":
                    get_response["ChecksumSHA256"] = checksum
                    expected_check = "get_sha256_checksum_exact"
                else:
                    head_response["ChecksumSHA256"] = checksum
                    expected_check = "head_sha256_checksum_exact"

                with self.assertRaisesRegex(
                    ValueError,
                    f"{response_name} ChecksumSHA256 "
                    "is not an exact SHA-256 checksum string",
                ):
                    MODULE.validate_exact_receipt(
                        fixture["receipt_bytes"],
                        get_response,
                        head_response,
                        self.receipt_history_rows(fixture),
                        self.receipt_location(fixture),
                        args,
                        fixture["submission_environment"],
                    )

    def test_logged_receipt_bytes_must_be_exact_int(self):
        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)

        with self.assertRaisesRegex(ValueError, "logged_local_bytes_exact"):
            MODULE.validate_exact_receipt(
                fixture["receipt_bytes"],
                fixture["metadata"],
                fixture["metadata"],
                self.receipt_history_rows(fixture),
                {
                    **self.receipt_location(fixture),
                    "bytes": float(len(fixture["receipt_bytes"])),
                },
                args,
                fixture["submission_environment"],
            )

    def test_route_receipt_requires_exact_schema_version(self):
        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)
        receipt = copy.deepcopy(fixture["receipt"])
        receipt["schema_version"] = 1.0
        content = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
        local_sha = hashlib.sha256(content).hexdigest()
        checksum = base64.b64encode(bytes.fromhex(local_sha)).decode()
        metadata = {
            **fixture["metadata"],
            "ContentLength": len(content),
            "ChecksumSHA256": checksum,
            "Metadata": {"sha256": local_sha},
        }

        with self.assertRaisesRegex(ValueError, "failed receipt_schema_status"):
            MODULE.validate_exact_receipt(
                content,
                metadata,
                metadata,
                self.receipt_history_rows(fixture),
                {
                    **self.receipt_location(fixture),
                    "sha256": local_sha,
                    "bytes": len(content),
                },
                args,
                fixture["submission_environment"],
            )

    def test_route_receipt_initial_version_count_must_be_exact_int(self):
        fixture = self.fixture()
        args = self.args(Path("unused"), fixture)
        receipt = copy.deepcopy(fixture["receipt"])
        receipt["route_output_initial_version_history_count"] = 0.0
        content = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
        local_sha = hashlib.sha256(content).hexdigest()
        checksum = base64.b64encode(bytes.fromhex(local_sha)).decode()
        metadata = {
            **fixture["metadata"],
            "ContentLength": len(content),
            "ChecksumSHA256": checksum,
            "Metadata": {"sha256": local_sha},
        }

        with self.assertRaisesRegex(ValueError, "failed receipt_output_exact"):
            MODULE.validate_exact_receipt(
                content,
                metadata,
                metadata,
                self.receipt_history_rows(fixture),
                {
                    **self.receipt_location(fixture),
                    "sha256": local_sha,
                    "bytes": len(content),
                },
                args,
                fixture["submission_environment"],
            )

    def test_exact_int_rejects_coercible_values(self):
        self.assertTrue(MODULE.exact_int(7, 7))
        self.assertTrue(MODULE.is_positive_exact_int(7))
        for value in (True, 7.0, "7", 0, None):
            with self.subTest(helper="exact_int", value=value):
                self.assertFalse(MODULE.exact_int(value, 7))
        for value in (True, 7.0, "7", 0, -1, None):
            with self.subTest(helper="is_positive_exact_int", value=value):
                self.assertFalse(MODULE.is_positive_exact_int(value))

    def test_schema_version_checks_use_exact_integer_helper(self):
        cases = (
            (1, 1, True),
            (1.0, 1, False),
            ("1", 1, False),
            (2, 1, False),
            (None, 1, False),
            (True, 1, False),
            (False, 0, False),
        )
        for value, expected, accepted in cases:
            with self.subTest(value=value, expected=expected):
                self.assertIs(
                    MODULE.exact_schema_version(
                        {"schema_version": value},
                        expected,
                    ),
                    accepted,
                )

    def test_schema_version_checks_avoid_raw_comparisons(self):
        module = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        parent_by_child = {
            child: parent
            for parent in ast.walk(module)
            for child in ast.iter_child_nodes(parent)
        }

        def in_exact_schema_helper(node: ast.AST) -> bool:
            parent = parent_by_child.get(node)
            while parent is not None:
                if isinstance(parent, ast.FunctionDef):
                    return parent.name == "exact_schema_version"
                parent = parent_by_child.get(parent)
            return False

        raw_schema_version_comparisons = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
            and not in_exact_schema_helper(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_sha256_checksum_guards_avoid_raw_string_coercion(self):
        module = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        raw_checksum_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and node.args
            and "ChecksumSHA256" in ast.unparse(node.args[0])
        ]

        self.assertEqual(raw_checksum_coercions, [])

    def test_rejects_download_sha_checksum_kms_or_receipt_history_tampering(self):
        fixture = self.fixture()
        bad_checksum = copy.deepcopy(fixture["metadata"])
        bad_checksum["ChecksumSHA256"] = base64.b64encode(b"x" * 32).decode()
        bad_kms = copy.deepcopy(fixture["metadata"])
        bad_kms["SSEKMSKeyId"] += "-wrong"
        deleted = copy.deepcopy(fixture["history"])
        deleted["DeleteMarkers"] = [{"Key": fixture["receipt_key"], "VersionId": "deleted"}]
        cases = (
            (
                "download-bytes",
                self.aws_side_effect(fixture),
                self.get_side_effect(fixture, content=b"{}\n"),
            ),
            (
                "head-checksum",
                self.aws_side_effect(fixture, metadata=bad_checksum),
                self.get_side_effect(fixture),
            ),
            (
                "get-kms",
                self.aws_side_effect(fixture),
                self.get_side_effect(fixture, metadata=bad_kms),
            ),
            (
                "delete-history",
                self.aws_side_effect(fixture, history=deleted),
                self.get_side_effect(fixture),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for label, aws, get in cases:
                with self.subTest(label=label), self.assertRaises(ValueError):
                    self.run_capture(
                        self.args(Path(temporary) / label, fixture),
                        fixture,
                        aws=aws,
                        get=get,
                    )

    def test_rejects_symlinked_exact_receipt_download_before_capture(self):
        fixture = self.fixture()

        def get(region, bucket, key, version_id, destination):
            real_receipt = destination.with_name("real-publication-receipt.json")
            real_receipt.write_bytes(fixture["receipt_bytes"])
            destination.symlink_to(real_receipt)
            return copy.deepcopy(fixture["metadata"])

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "downloaded route receipt must be a real file"):
                self.run_capture(
                    self.args(Path(temporary), fixture),
                    fixture,
                    get=get,
                )

    def test_downloaded_exact_receipt_rejects_same_byte_leaf_replacement(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "publication-receipt.json"
            replacement = root / "replacement-publication-receipt.json"
            receipt.write_bytes(fixture["receipt_bytes"])
            replacement.write_bytes(fixture["receipt_bytes"])
            real_read = MODULE.read_real_hash_input_once
            swapped = False

            def replace_leaf_after_first_read(path, label, preflight):
                nonlocal swapped
                result = real_read(path, label, preflight)
                if path == receipt and not swapped:
                    replacement.replace(receipt)
                    swapped = True
                return result

            with (
                mock.patch.object(
                    MODULE,
                    "read_real_hash_input_once",
                    side_effect=replace_leaf_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "downloaded route receipt changed during read",
                ),
            ):
                MODULE.read_stable_downloaded_file(
                    receipt,
                    "downloaded route receipt",
                )

            self.assertTrue(swapped)

    def test_exact_get_cli_includes_logged_version_and_checksum_mode(self):
        fixture = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "receipt.json"

            def command(command, **kwargs):
                self.assertEqual(
                    command,
                    [
                        "aws",
                        "s3api",
                        "get-object",
                        "--bucket",
                        "diana-omics-private-results-unit",
                        "--key",
                        "receipt.json",
                        "--version-id",
                        fixture["receipt_version"],
                        "--checksum-mode",
                        "ENABLED",
                        "--region",
                        MODULE.REGION,
                        "--output",
                        "json",
                        str(destination),
                    ],
                )
                self.assertEqual(
                    kwargs,
                    {"text": True, "stderr": subprocess.STDOUT},
                )
                destination.write_bytes(fixture["receipt_bytes"])
                return json.dumps(fixture["metadata"])

            with mock.patch.object(subprocess, "check_output", side_effect=command):
                response = MODULE.get_exact_object(
                    MODULE.REGION,
                    "diana-omics-private-results-unit",
                    "receipt.json",
                    fixture["receipt_version"],
                    destination,
                )
            self.assertEqual(response["VersionId"], fixture["receipt_version"])

    def test_private_create_is_exclusive_and_mode_0600(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            MODULE.create_private(path, b"first")
            self.assertEqual(path.read_bytes(), b"first")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.create_private(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"first")


if __name__ == "__main__":
    unittest.main()
