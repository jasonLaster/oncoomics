#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import capture_materializer_terminal as MODULE  # noqa: E402


class CaptureMaterializerTerminalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kms = "arn:aws:kms:us-east-1:172630973301:key/unit"
        self.prefix = (
            "s3://diana-omics-private-results-172630973301-us-east-1/"
            "runs/subject01/unit/deterministic/provenance/"
            "crosscheck-materialization-receipts"
        )
        self.parameters = {
            "source_vcf_version_id": "vcf-version",
            "source_vcf_index_version_id": "index-version",
            "source_matrix_version_id": "matrix-version",
            "source_vcf_sha256": "a" * 64,
            "source_vcf_index_sha256": "b" * 64,
            "source_matrix_sha256": "c" * 64,
            "reference_fasta_version_id": "fasta-version",
            "reference_fai_version_id": "fai-version",
        }
        self.receipt_bytes = (
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "passed",
                    "script_sha256": MODULE.EXPECTED_MATERIALIZER_SHA256,
                    "checks": {
                        "all_sources_exact_version_and_sha256": True,
                        "destination_exact_single_version_history": True,
                    },
                    "classification_authorization": "none",
                    "authorized_hrd_state": "no_call",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        self.receipt_sha = hashlib.sha256(self.receipt_bytes).hexdigest()
        self.checksum = base64.b64encode(bytes.fromhex(self.receipt_sha)).decode()
        self.version_id = "exact-receipt-version"
        self.receipt_uri = f"{self.prefix}/{self.receipt_sha}.json"
        self.key = self.receipt_uri.split("/", 3)[3]
        self.metadata = {
            "VersionId": self.version_id,
            "ContentLength": len(self.receipt_bytes),
            "ChecksumSHA256": self.checksum,
            "ChecksumType": "FULL_OBJECT",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self.kms,
            "Metadata": {"sha256": self.receipt_sha},
        }
        self.terminal = {
            "status": "passed",
            "receipt": {
                "uri": self.receipt_uri,
                "version_id": self.version_id,
                "bytes": len(self.receipt_bytes),
                "checksums": {"ChecksumSHA256": self.checksum},
                "sha256": self.receipt_sha,
                "kms_key_arn": self.kms,
                "checks": {
                    "create_only_put": True,
                    "version_exact": True,
                    "bytes_exact": True,
                    "metadata_sha256_exact": True,
                    "exact_kms": True,
                    "single_version_history": True,
                },
            },
            "receipt_anchor": {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": self.receipt_sha,
                "receipt_bytes": len(self.receipt_bytes),
                "receipt_uri": self.receipt_uri,
                "receipt_version_id": self.version_id,
                "checks": {name: True for name in MODULE.ANCHOR_CHECKS},
            },
            "outputs": {"somatic.pass.vcf.gz": {"version_id": "output-version"}},
        }
        self.log_stream = "diana-wgs-hrd-materialize/default/exact-task"
        self.job = {
            "jobId": "job-1",
            "jobName": "materialize-unit",
            "status": "SUCCEEDED",
            "startedAt": 100,
            "stoppedAt": 200,
            "jobDefinition": MODULE.EXPECTED_JOB_DEFINITION,
            "jobQueue": MODULE.EXPECTED_QUEUE_ARN,
            "parameters": dict(self.parameters),
            "retryStrategy": {"attempts": 1},
            "container": {"exitCode": 0, "logStreamName": self.log_stream},
            "attempts": [
                {
                    "container": {
                        "exitCode": 0,
                        "logStreamName": self.log_stream,
                    }
                }
            ],
        }
        self.definition = {
            "jobDefinitionArn": MODULE.EXPECTED_JOB_DEFINITION,
            "jobDefinitionName": MODULE.EXPECTED_JOB_DEFINITION_NAME,
            "revision": 4,
            "status": "ACTIVE",
            "retryStrategy": {"attempts": 1},
            "timeout": {"attemptDurationSeconds": 21600},
            "containerProperties": {
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": MODULE.LOG_GROUP,
                        "awslogs-region": MODULE.REGION,
                        "awslogs-stream-prefix": MODULE.LOG_STREAM_PREFIX.rstrip("/"),
                    },
                }
            },
        }
        self.queue = {
            "jobQueueArn": MODULE.EXPECTED_QUEUE_ARN,
            "jobQueueName": MODULE.EXPECTED_QUEUE_NAME,
            "state": "ENABLED",
            "status": "VALID",
            "computeEnvironmentOrder": [
                {
                    "order": 1,
                    "computeEnvironment": MODULE.EXPECTED_COMPUTE_ENVIRONMENT,
                }
            ],
        }
        self.compute = {
            "computeEnvironmentArn": MODULE.EXPECTED_COMPUTE_ENVIRONMENT,
            "computeEnvironmentName": MODULE.EXPECTED_QUEUE_NAME,
            "state": "ENABLED",
            "status": "VALID",
            "computeResources": {"instanceTypes": list(MODULE.EXPECTED_ARM_INSTANCE_TYPES)},
        }
        self.history = {
            "Versions": [
                {
                    "Key": self.key,
                    "VersionId": self.version_id,
                    "IsLatest": True,
                }
            ],
            "DeleteMarkers": [],
            "IsTruncated": False,
        }

    def args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(
            job_id="job-1",
            expected_parameter=[f"{name}={self.parameters[name]}" for name in MODULE.PARAMETER_NAMES],
            expected_receipt_prefix=self.prefix,
            expected_kms_key_arn=self.kms,
            capture_output=root / "terminal-capture.json",
            anchor_output=root / "materialization-anchor.json",
            receipt_output=root / "materialization-receipt.json",
            region=MODULE.REGION,
        )

    def events(self, terminal=None, trailing: str | None = None):
        payload = self.terminal if terminal is None else terminal
        lines = ["materializer startup"] + json.dumps(payload, indent=2, sort_keys=True).splitlines()
        if trailing is not None:
            lines.append(trailing)
        return [{"timestamp": 1000 + index, "ingestionTime": 2000 + index, "message": line} for index, line in enumerate(lines)]

    def aws_side_effect(
        self,
        *,
        job=None,
        definition=None,
        queue=None,
        compute=None,
        events=None,
        metadata=None,
        history=None,
    ):
        values = {
            "job": self.job if job is None else job,
            "definition": self.definition if definition is None else definition,
            "queue": self.queue if queue is None else queue,
            "compute": self.compute if compute is None else compute,
            "events": self.events() if events is None else events,
            "metadata": self.metadata if metadata is None else metadata,
            "history": self.history if history is None else history,
        }

        def invoke(region, *arguments):
            self.assertEqual(region, MODULE.REGION)
            operation = tuple(arguments[:2])
            if operation == ("batch", "describe-jobs"):
                return {"jobs": [copy.deepcopy(values["job"])]}
            if operation == ("batch", "describe-job-definitions"):
                return {"jobDefinitions": [copy.deepcopy(values["definition"])]}
            if operation == ("batch", "describe-job-queues"):
                return {"jobQueues": [copy.deepcopy(values["queue"])]}
            if operation == ("batch", "describe-compute-environments"):
                return {"computeEnvironments": [copy.deepcopy(values["compute"])]}
            if operation == ("logs", "get-log-events"):
                self.assertIn("--log-stream-name", arguments)
                stream_index = arguments.index("--log-stream-name") + 1
                self.assertEqual(arguments[stream_index], self.log_stream)
                if "--next-token" in arguments:
                    return {"events": [], "nextForwardToken": "terminal-token"}
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
                        self.key,
                        "--version-id",
                        self.version_id,
                        "--checksum-mode",
                        "ENABLED",
                    ),
                )
                return copy.deepcopy(values["metadata"])
            if operation == ("s3api", "list-object-versions"):
                return copy.deepcopy(values["history"])
            raise AssertionError(f"unexpected mocked AWS CLI call: {arguments}")

        return invoke

    def get_side_effect(self, *, receipt_bytes=None, metadata=None):
        content = self.receipt_bytes if receipt_bytes is None else receipt_bytes
        response = self.metadata if metadata is None else metadata

        def invoke(region, bucket, key, version_id, destination):
            self.assertEqual(region, MODULE.REGION)
            self.assertEqual(key, self.key)
            self.assertEqual(version_id, self.version_id)
            destination.write_bytes(content)
            return copy.deepcopy(response)

        return invoke

    def run_capture(self, args, *, aws=None, get=None):
        aws = self.aws_side_effect() if aws is None else aws
        get = self.get_side_effect() if get is None else get
        with mock.patch.object(MODULE, "aws_json", side_effect=aws), mock.patch.object(MODULE, "get_exact_object", side_effect=get):
            return MODULE.capture(args)

    def test_success_uses_logged_exact_version_and_emits_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary))
            result = self.run_capture(args)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["receipt"]["version_id"], self.version_id)
            self.assertEqual(args.receipt_output.read_bytes(), self.receipt_bytes)
            self.assertEqual(
                json.loads(args.anchor_output.read_text()),
                self.terminal["receipt_anchor"],
            )
            for path in (args.capture_output, args.anchor_output, args.receipt_output):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            persisted = json.loads(args.capture_output.read_text())
            self.assertTrue(all(persisted["checks"].values()))
            self.assertTrue(all(persisted["batch"]["checks"].values()))
            self.assertEqual(
                persisted["local_anchor"]["sha256"],
                hashlib.sha256(args.anchor_output.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                persisted["local_anchor"]["bytes"],
                args.anchor_output.stat().st_size,
            )

    def test_refuses_existing_output_before_any_aws_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("capture_output", "anchor_output", "receipt_output"):
                with self.subTest(name=name):
                    args = self.args(Path(temporary) / name)
                    path = getattr(args, name)
                    path.parent.mkdir(parents=True)
                    path.write_text("do not replace")
                    with mock.patch.object(MODULE, "aws_json") as mocked:
                        with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                            MODULE.capture(args)
                    mocked.assert_not_called()
                    self.assertEqual(path.read_text(), "do not replace")

    def test_requires_three_distinct_outputs_before_any_aws_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary))
            args.anchor_output = args.capture_output
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(ValueError, "must be distinct"):
                    MODULE.capture(args)
            mocked.assert_not_called()

    def test_requires_all_eight_exact_well_formed_parameters(self) -> None:
        values = [f"{name}={self.parameters[name]}" for name in MODULE.PARAMETER_NAMES]
        self.assertEqual(MODULE.parse_parameters(values), self.parameters)
        for malformed in (
            values[:-1],
            values + ["extra=value"],
            values + [values[0]],
            [value if not value.startswith("source_vcf_sha256=") else "source_vcf_sha256=BAD" for value in values],
        ):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                MODULE.parse_parameters(malformed)

    def test_rejects_nonterminal_or_wrong_batch_identity(self) -> None:
        mutations = {
            "status": ("status", "RUNNING"),
            "definition": ("jobDefinition", MODULE.EXPECTED_JOB_DEFINITION[:-1] + "3"),
            "queue": ("jobQueue", MODULE.EXPECTED_QUEUE_ARN + "-other"),
            "retry": ("retryStrategy", {"attempts": 2}),
            "parameters": ("parameters", {**self.parameters, "extra": "forged"}),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for label, (key, value) in mutations.items():
                with self.subTest(label=label):
                    job = copy.deepcopy(self.job)
                    job[key] = value
                    args = self.args(Path(temporary) / label)
                    with self.assertRaisesRegex(ValueError, "Batch identity failed"):
                        self.run_capture(args, aws=self.aws_side_effect(job=job))

    def test_rejects_multiple_attempts_nonzero_exit_and_log_mismatch(self) -> None:
        jobs = []
        extra_attempt = copy.deepcopy(self.job)
        extra_attempt["attempts"].append(copy.deepcopy(extra_attempt["attempts"][0]))
        jobs.append(extra_attempt)
        job_exit = copy.deepcopy(self.job)
        job_exit["container"]["exitCode"] = 1
        jobs.append(job_exit)
        attempt_exit = copy.deepcopy(self.job)
        attempt_exit["attempts"][0]["container"]["exitCode"] = 1
        jobs.append(attempt_exit)
        wrong_log = copy.deepcopy(self.job)
        wrong_log["attempts"][0]["container"]["logStreamName"] += "-forged"
        jobs.append(wrong_log)
        with tempfile.TemporaryDirectory() as temporary:
            for index, job in enumerate(jobs):
                with self.subTest(index=index):
                    args = self.args(Path(temporary) / str(index))
                    with self.assertRaises(ValueError):
                        self.run_capture(args, aws=self.aws_side_effect(job=job))

    def test_rejects_queue_that_is_not_live_exact_graviton_route(self) -> None:
        queue = copy.deepcopy(self.queue)
        queue["computeEnvironmentOrder"][0]["computeEnvironment"] += "-x86"
        compute = copy.deepcopy(self.compute)
        compute["computeResources"]["instanceTypes"] = ["m7i"]
        with tempfile.TemporaryDirectory() as temporary:
            for label, kwargs in (
                ("queue", {"queue": queue}),
                ("compute", {"compute": compute}),
            ):
                with self.subTest(label=label), self.assertRaises(ValueError):
                    self.run_capture(
                        self.args(Path(temporary) / label),
                        aws=self.aws_side_effect(**kwargs),
                    )

    def test_terminal_parser_rejects_duplicate_forgery_or_trailing_output(self) -> None:
        valid = self.events()
        duplicate = valid + self.events()
        trailing = self.events(trailing="unexpected output after receipt")
        for label, events in (("duplicate", duplicate), ("trailing", trailing)):
            with self.subTest(label=label), self.assertRaises(ValueError):
                MODULE.parse_terminal_payload(events)

    def test_logged_anchor_cannot_redirect_to_current_or_unexpected_key(self) -> None:
        terminal = copy.deepcopy(self.terminal)
        terminal["receipt_anchor"]["receipt_uri"] = self.prefix + "/latest.json"
        terminal["receipt"]["uri"] = self.prefix + "/latest.json"
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "anchor failed"):
                self.run_capture(
                    self.args(Path(temporary)),
                    aws=self.aws_side_effect(events=self.events(terminal)),
                )

    def test_rejects_download_sha_bytes_checksum_kms_or_history_tampering(self) -> None:
        bad_checksum = copy.deepcopy(self.metadata)
        bad_checksum["ChecksumSHA256"] = base64.b64encode(b"x" * 32).decode()
        bad_kms = copy.deepcopy(self.metadata)
        bad_kms["SSEKMSKeyId"] += "-wrong"
        deleted = copy.deepcopy(self.history)
        deleted["DeleteMarkers"] = [{"Key": self.key, "VersionId": "deleted", "IsLatest": False}]
        cases = (
            ("bytes", self.aws_side_effect(), self.get_side_effect(receipt_bytes=b"{}\n")),
            ("head-checksum", self.aws_side_effect(metadata=bad_checksum), self.get_side_effect()),
            ("get-kms", self.aws_side_effect(), self.get_side_effect(metadata=bad_kms)),
            ("delete-history", self.aws_side_effect(history=deleted), self.get_side_effect()),
        )
        with tempfile.TemporaryDirectory() as temporary:
            for label, aws, get in cases:
                with self.subTest(label=label), self.assertRaises(ValueError):
                    self.run_capture(self.args(Path(temporary) / label), aws=aws, get=get)

    def test_exact_get_cli_includes_logged_version_and_checksum_mode(self) -> None:
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
                        self.version_id,
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
                return json.dumps(self.metadata)

            with mock.patch.object(subprocess, "check_output", side_effect=command):
                response = MODULE.get_exact_object(
                    MODULE.REGION,
                    "diana-omics-private-results-unit",
                    "receipt.json",
                    self.version_id,
                    destination,
                )
            self.assertEqual(response["VersionId"], self.version_id)

    def test_private_create_is_exclusive_and_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            MODULE.create_private(path, b"first")
            self.assertEqual(path.read_bytes(), b"first")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.create_private(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"first")

    def test_private_group_rolls_back_only_its_partial_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.json"
            second = root / "second.json"
            third = root / "third.json"
            original = MODULE.create_private

            def fail_second(path, content):
                if path == second:
                    raise OSError("synthetic second-output failure")
                original(path, content)

            with mock.patch.object(MODULE, "create_private", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "synthetic second-output failure"):
                    MODULE.create_private_group(((first, b"first"), (second, b"second"), (third, b"third")))
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertFalse(third.exists())


if __name__ == "__main__":
    unittest.main()
