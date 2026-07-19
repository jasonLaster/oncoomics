#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
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
        self.destination_prefix = (
            "s3://diana-omics-private-results-172630973301-us-east-1/"
            "runs/subject01/unit/deterministic/final/"
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
        self.source_sha256 = {
            "vcf": self.parameters["source_vcf_sha256"],
            "vcf_index": self.parameters["source_vcf_index_sha256"],
            "matrix": self.parameters["source_matrix_sha256"],
            "fasta": "d" * 64,
            "fai": "e" * 64,
        }

        self.outputs = {}
        for index, filename in enumerate(MODULE.EXPECTED_MATERIALIZER_OUTPUTS):
            sha256 = f"{index + 1}" * 64
            self.outputs[filename] = {
                "uri": f"{self.destination_prefix}{filename}",
                "version_id": f"output-version-{index}",
                "bytes": 100 + index,
                "etag": f'"etag-{index}"',
                "checksums": {
                    "ChecksumSHA256": base64.b64encode(
                        bytes.fromhex(sha256)
                    ).decode(),
                    "ChecksumType": "FULL_OBJECT",
                },
                "sha256": sha256,
                "kms_key_arn": self.kms,
                "checks": dict(MODULE.EXPECTED_RECEIPT_UPLOAD_CHECKS),
            }
        source_custody = {}
        for source_name, version_parameter in MODULE.EXPECTED_SOURCE_VERSION_PARAMETERS.items():
            expected_sha256 = self.source_sha256[source_name]
            source_custody[source_name] = {
                "uri": (
                    "s3://diana-omics-private-results-172630973301-us-east-1/"
                    f"runs/subject01/unit/source/{source_name}"
                ),
                "version_id": self.parameters[version_parameter],
                "bytes": 200 + len(source_custody),
                "etag": f'"source-etag-{source_name}"',
                "checksums": {},
                "sha256": expected_sha256,
                "expected_sha256": (
                    expected_sha256
                    if source_name not in {"fasta", "fai"}
                    else None
                ),
                "kms_key_arn": self.kms,
            }
        self.receipt_bytes = (
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "passed",
                    "generated_at_utc": "2026-07-19T00:00:00Z",
                    "run_alias": "subject01",
                    "script_sha256": MODULE.EXPECTED_MATERIALIZER_SHA256,
                    "destination_prefix": self.destination_prefix,
                    "destination_bucket_versioning": "Enabled",
                    "destination_initial_version_history_count": 0,
                    "receipt_anchor_strategy": "sha256_content_addressed_create_only",
                    "source_custody": source_custody,
                    "validation": {"status": "passed"},
                    "input_sha256": {
                        "filtered_vcf": self.source_sha256["vcf"],
                        "filtered_vcf_index": self.source_sha256["vcf_index"],
                        "source_sbs96_matrix": self.source_sha256["matrix"],
                        "reference_fasta": self.source_sha256["fasta"],
                        "reference_fai": self.source_sha256["fai"],
                    },
                    "outputs": self.outputs,
                    "destination_inventory": [
                        {
                            "filename": filename,
                            "key": output["uri"].split("/", 3)[3],
                            "version_id": output["version_id"],
                            "bytes": output["bytes"],
                            "sha256": output["sha256"],
                            "checksums": output["checksums"],
                        }
                        for filename, output in sorted(self.outputs.items())
                    ],
                    "checks": dict(MODULE.EXPECTED_MATERIALIZER_RECEIPT_CHECKS),
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
                "checks": dict(MODULE.EXPECTED_RECEIPT_UPLOAD_CHECKS),
            },
            "receipt_anchor": {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": self.receipt_sha,
                "receipt_bytes": len(self.receipt_bytes),
                "receipt_uri": self.receipt_uri,
                "receipt_version_id": self.version_id,
                "checks": dict(MODULE.EXPECTED_RECEIPT_ANCHOR_CHECKS),
            },
            "outputs": copy.deepcopy(self.outputs),
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
                    MODULE.collect_log_events(MODULE.REGION, self.log_stream)

                self.assertEqual(len(calls), 1)

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
        key=None,
    ):
        expected_key = self.key if key is None else key
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
                expected_log_arguments = (
                    "logs",
                    "get-log-events",
                    "--log-group-name",
                    MODULE.LOG_GROUP,
                    "--log-stream-name",
                    self.log_stream,
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
                        expected_key,
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

    def get_side_effect(self, *, receipt_bytes=None, metadata=None, key=None):
        content = self.receipt_bytes if receipt_bytes is None else receipt_bytes
        response = self.metadata if metadata is None else metadata
        expected_key = self.key if key is None else key

        def invoke(region, bucket, key, version_id, destination):
            self.assertEqual(region, MODULE.REGION)
            self.assertEqual(key, expected_key)
            self.assertEqual(version_id, self.version_id)
            destination.write_bytes(content)
            return copy.deepcopy(response)

        return invoke

    def encode_receipt(self, receipt: dict) -> bytes:
        return (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )

    def run_capture_with_receipt(self, root: Path, receipt: dict):
        receipt_bytes = self.encode_receipt(receipt)
        receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
        checksum = base64.b64encode(bytes.fromhex(receipt_sha)).decode()
        metadata = {
            **self.metadata,
            "ContentLength": len(receipt_bytes),
            "ChecksumSHA256": checksum,
            "Metadata": {"sha256": receipt_sha},
        }
        terminal = copy.deepcopy(self.terminal)
        terminal["receipt"]["bytes"] = len(receipt_bytes)
        terminal["receipt"]["checksums"]["ChecksumSHA256"] = checksum
        terminal["receipt"]["sha256"] = receipt_sha
        terminal["receipt"]["uri"] = f"{self.prefix}/{receipt_sha}.json"
        terminal["receipt_anchor"]["receipt_bytes"] = len(receipt_bytes)
        terminal["receipt_anchor"]["receipt_sha256"] = receipt_sha
        terminal["receipt_anchor"]["receipt_uri"] = terminal["receipt"]["uri"]

        receipt_key = terminal["receipt_anchor"]["receipt_uri"].split("/", 3)[3]
        history = copy.deepcopy(self.history)
        history["Versions"][0]["Key"] = receipt_key
        return self.run_capture(
            self.args(root),
            aws=self.aws_side_effect(
                events=self.events(terminal),
                metadata=metadata,
                history=history,
                key=receipt_key,
            ),
            get=self.get_side_effect(
                receipt_bytes=receipt_bytes,
                metadata=metadata,
                key=receipt_key,
            ),
        )

    def run_capture(self, args, *, aws=None, get=None):
        aws = self.aws_side_effect() if aws is None else aws
        get = self.get_side_effect() if get is None else get
        with mock.patch.object(MODULE, "aws_json", side_effect=aws), mock.patch.object(MODULE, "get_exact_object", side_effect=get):
            return MODULE.capture(args)

    def receipt_location(self) -> dict:
        return MODULE.validate_logged_anchor(
            self.terminal,
            self.prefix,
            self.kms,
        )

    def receipt_history_rows(self) -> list[dict]:
        return [
            {
                "Key": self.key,
                "VersionId": self.version_id,
                "IsLatest": True,
                "history_kind": "version",
            }
        ]

    def test_receipt_history_consumes_key_and_version_markers(self) -> None:
        pages = [
            {
                "IsTruncated": True,
                "Versions": [{"Key": self.key, "VersionId": "v1"}],
                "DeleteMarkers": [],
                "NextKeyMarker": self.key,
                "NextVersionIdMarker": "v1",
            },
            {
                "IsTruncated": False,
                "Versions": [],
                "DeleteMarkers": [{"Key": self.key, "VersionId": "d1"}],
            },
        ]

        with mock.patch.object(MODULE, "aws_json", side_effect=pages) as aws_json:
            self.assertEqual(
                MODULE.version_history(MODULE.REGION, "bucket", self.key),
                [
                    {"Key": self.key, "VersionId": "v1", "history_kind": "version"},
                    {
                        "Key": self.key,
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
                self.key,
                "--key-marker",
                self.key,
                "--version-id-marker",
                "v1",
            ),
        )

    def test_receipt_history_rejects_missing_or_stalled_markers(self) -> None:
        cases = (
            {"NextKeyMarker": self.key},
            {"NextKeyMarker": True, "NextVersionIdMarker": "v1"},
            {"NextKeyMarker": self.key, "NextVersionIdMarker": True},
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
                        MODULE.version_history(MODULE.REGION, "bucket", self.key)

        stalled = {
            "IsTruncated": True,
            "Versions": [],
            "DeleteMarkers": [],
            "NextKeyMarker": self.key,
            "NextVersionIdMarker": "v1",
        }
        with mock.patch.object(MODULE, "aws_json", side_effect=[stalled, stalled]):
            with self.assertRaisesRegex(ValueError, "did not advance"):
                MODULE.version_history(MODULE.REGION, "bucket", self.key)

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

            real_parent = Path(temporary) / "real-parent"
            real_parent.mkdir()
            symlinked_output = self.args(Path(temporary) / "symlinked-output")
            symlinked_output.anchor_output.parent.mkdir()
            symlinked_output.anchor_output.symlink_to(
                real_parent / "anchor.json"
            )
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(FileExistsError, "may not be a symlink"):
                    MODULE.capture(symlinked_output)
            mocked.assert_not_called()
            self.assertFalse((real_parent / "anchor.json").exists())

            symlinked_parent = self.args(Path(temporary) / "symlinked-parent")
            symlinked_parent.capture_output.parent.symlink_to(
                real_parent,
                target_is_directory=True,
            )
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(
                    FileExistsError, "parent may not be a symlink"
                ):
                    MODULE.capture(symlinked_parent)
            mocked.assert_not_called()
            self.assertFalse((real_parent / "terminal-capture.json").exists())

    def test_requires_three_distinct_outputs_before_any_aws_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary))
            args.anchor_output = args.capture_output
            with mock.patch.object(MODULE, "aws_json") as mocked:
                with self.assertRaisesRegex(ValueError, "must be distinct"):
                    MODULE.capture(args)
            mocked.assert_not_called()

    def test_create_private_group_rejects_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.create_private_group(
                    ((linked_parent / "capture.json", b"capture"),)
                )

            self.assertFalse((real_parent / "capture.json").exists())

    def test_create_private_group_rejects_nested_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.create_private_group(
                    [(linked_parent / "missing" / "capture.json", b"capture")]
                )

            self.assertFalse((real_parent / "missing" / "capture.json").exists())

    def test_create_private_group_rejects_existing_dir_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-parent"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(FileExistsError, "parent may not be a symlink"):
                MODULE.create_private_group(
                    [(linked_parent / "existing" / "capture.json", b"capture")]
                )

            self.assertFalse((real_parent / "existing" / "capture.json").exists())

    def test_requires_all_eight_exact_well_formed_parameters(self) -> None:
        values = [f"{name}={self.parameters[name]}" for name in MODULE.PARAMETER_NAMES]
        self.assertEqual(MODULE.parse_parameters(values), self.parameters)
        for malformed in (
            values[:-1],
            values + ["extra=value"],
            values + [values[0]],
            [value if not value.startswith("source_vcf_sha256=") else "source_vcf_sha256=BAD" for value in values],
            [value if not value.startswith("source_vcf_version_id=") else "source_vcf_version_id=null" for value in values],
        ):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                MODULE.parse_parameters(malformed)

    def test_valid_version_id_rejects_coerced_empty_null_and_whitespace_values(
        self,
    ) -> None:
        cases = (
            (True, False),
            (1, False),
            (1.0, False),
            ("", False),
            ("null", False),
            ("None", False),
            ("has space", False),
            ("exact-version", True),
        )

        for value, accepted in cases:
            with self.subTest(value=value):
                self.assertIs(MODULE.valid_version_id(value), accepted)

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

    def test_rejects_logged_anchor_with_missing_unexpected_or_failed_anchor_check(self) -> None:
        cases = {}
        for label, mutate in (
            (
                "missing",
                lambda checks: checks.pop("sha256_exact"),
            ),
            (
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
            ),
            (
                "failed",
                lambda checks: checks.__setitem__("exact_kms", False),
            ),
        ):
            terminal = copy.deepcopy(self.terminal)
            mutate(terminal["receipt_anchor"]["checks"])
            cases[label] = terminal

        with tempfile.TemporaryDirectory() as temporary:
            for label, terminal in cases.items():
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError,
                    "anchor failed",
                ):
                    self.run_capture(
                        self.args(Path(temporary) / label),
                        aws=self.aws_side_effect(events=self.events(terminal)),
                    )

    def test_batch_identity_check_map_must_be_exact(self) -> None:
        cases = (
            (
                {
                    **MODULE.EXPECTED_BATCH_IDENTITY_CHECKS,
                    "future_batch_identity_check": True,
                },
                "missing future_batch_identity_check",
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
                    self.job,
                    self.definition,
                    self.queue,
                    self.compute,
                    "job-1",
                    self.parameters,
                )

    def test_failed_batch_identity_check_reports_exact_key(self) -> None:
        job = copy.deepcopy(self.job)
        job["stoppedAt"] = 99

        with self.assertRaisesRegex(ValueError, "failed terminal_timestamps"):
            MODULE.validate_job(
                job,
                self.definition,
                self.queue,
                self.compute,
                "job-1",
                self.parameters,
            )

    def test_batch_runtime_numbers_must_be_exact_integers(self) -> None:
        cases = (
            ("job_retry", {"job_retry": 1.0}, "failed one_retry_attempt"),
            ("definition_revision", {"definition_revision": 4.0}, "failed definition_exact"),
            ("definition_retry", {"definition_retry": True}, "failed definition_exact"),
            ("definition_timeout", {"definition_timeout": 21600.0}, "failed definition_exact"),
        )

        for label, values, error in cases:
            with self.subTest(label=label):
                job = copy.deepcopy(self.job)
                definition = copy.deepcopy(self.definition)
                if "job_retry" in values:
                    job["retryStrategy"]["attempts"] = values["job_retry"]
                if "definition_revision" in values:
                    definition["revision"] = values["definition_revision"]
                if "definition_retry" in values:
                    definition["retryStrategy"]["attempts"] = values["definition_retry"]
                if "definition_timeout" in values:
                    definition["timeout"]["attemptDurationSeconds"] = values[
                        "definition_timeout"
                    ]

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_job(
                        job,
                        definition,
                        self.queue,
                        self.compute,
                        "job-1",
                        self.parameters,
                    )

    def test_batch_terminal_timestamps_must_be_exact_integers(self) -> None:
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
                job = copy.deepcopy(self.job)
                job[field] = value

                with self.assertRaisesRegex(ValueError, "failed terminal_timestamps"):
                    MODULE.validate_job(
                        job,
                        self.definition,
                        self.queue,
                        self.compute,
                        "job-1",
                        self.parameters,
                    )

    def test_cloudwatch_event_timestamps_must_be_exact_integers(self) -> None:
        cases = (
            ("float", 1000.0, "not an exact positive integer"),
            ("bool", True, "not an exact positive integer"),
            ("string", "1000", "not an exact positive integer"),
            ("unordered", 999, "not ordered"),
        )

        for label, value, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                events = self.events()
                events[-1]["timestamp"] = value

                with self.assertRaisesRegex(ValueError, error):
                    self.run_capture(
                        self.args(Path(temporary)),
                        aws=self.aws_side_effect(events=events),
                    )

    def test_logged_anchor_outer_check_map_must_be_exact(self) -> None:
        cases = (
            (
                {
                    **MODULE.EXPECTED_LOGGED_RECEIPT_ANCHOR_CHECKS,
                    "future_logged_anchor_check": True,
                },
                "missing future_logged_anchor_check",
            ),
            (
                {
                    name: value
                    for name, value in MODULE.EXPECTED_LOGGED_RECEIPT_ANCHOR_CHECKS.items()
                    if name != "upload_checks_exact"
                },
                "unexpected upload_checks_exact",
            ),
        )

        for expected, error in cases:
            with (
                self.subTest(error=error),
                mock.patch.object(
                    MODULE,
                    "EXPECTED_LOGGED_RECEIPT_ANCHOR_CHECKS",
                    expected,
                ),
                self.assertRaisesRegex(ValueError, error),
            ):
                self.receipt_location()

    def test_failed_logged_anchor_outer_check_reports_exact_key(self) -> None:
        terminal = copy.deepcopy(self.terminal)
        terminal["receipt"]["sha256"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "failed upload_binding"):
            MODULE.validate_logged_anchor(terminal, self.prefix, self.kms)

    def test_logged_anchor_requires_exact_schema_version(self) -> None:
        terminal = copy.deepcopy(self.terminal)
        terminal["receipt_anchor"]["schema_version"] = 1.0

        with self.assertRaisesRegex(ValueError, "failed anchor_schema_status"):
            MODULE.validate_logged_anchor(terminal, self.prefix, self.kms)

    def test_logged_anchor_receipt_bytes_must_be_exact_int(self) -> None:
        terminal = copy.deepcopy(self.terminal)
        terminal["receipt"]["bytes"] = float(self.terminal["receipt"]["bytes"])

        with self.assertRaisesRegex(ValueError, "failed upload_binding"):
            MODULE.validate_logged_anchor(terminal, self.prefix, self.kms)

    def test_logged_anchor_rejects_coerced_sha256_and_version_id(self) -> None:
        cases = (
            (
                "numeric_sha256",
                "receipt_sha256",
                int("1" * 64),
                "receipt_sha256_well_formed",
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
                terminal = copy.deepcopy(self.terminal)
                terminal["receipt_anchor"][field] = value

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_logged_anchor(terminal, self.prefix, self.kms)

    def test_rejects_logged_anchor_with_missing_unexpected_or_failed_upload_check(self) -> None:
        cases = {}
        for label, mutate in (
            (
                "missing",
                lambda checks: checks.pop("sha256_checksum_exact"),
            ),
            (
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
            ),
            (
                "failed",
                lambda checks: checks.__setitem__("single_version_history", False),
            ),
        ):
            terminal = copy.deepcopy(self.terminal)
            mutate(terminal["receipt"]["checks"])
            cases[label] = terminal

        with tempfile.TemporaryDirectory() as temporary:
            for label, terminal in cases.items():
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError,
                    "anchor failed",
                ):
                    self.run_capture(
                        self.args(Path(temporary) / label),
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

    def test_rejects_materializer_receipt_with_missing_unexpected_or_failed_check(self) -> None:
        cases = {}
        for label, mutate in (
            (
                "missing",
                lambda checks: checks.pop("alias_only_pass_snv_vcf"),
            ),
            (
                "unexpected",
                lambda checks: checks.__setitem__("forged_extra", True),
            ),
            (
                "failed",
                lambda checks: checks.__setitem__(
                    "sbs96_matches_independent_pass_vcf_derivation",
                    False,
                ),
            ),
        ):
            receipt = json.loads(self.receipt_bytes)
            mutate(receipt["checks"])
            cases[label] = (
                json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")

        with tempfile.TemporaryDirectory() as temporary:
            for label, receipt_bytes in cases.items():
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError,
                    "receipt verification failed",
                ):
                    self.run_capture_with_receipt(
                        Path(temporary) / label,
                        json.loads(receipt_bytes),
                    )

    def test_rejects_materializer_receipt_with_missing_source_or_output_custody(
        self,
    ) -> None:
        cases = {
            "missing-output": lambda receipt: receipt["outputs"].pop("sbs96.csv"),
            "wrong-source-sha": lambda receipt: receipt["source_custody"][
                "matrix"
            ].__setitem__("sha256", "f" * 64),
            "stale-inventory-row": lambda receipt: receipt[
                "destination_inventory"
            ].append(
                {
                    "filename": "stale.tmp",
                    "key": "runs/subject01/unit/deterministic/final/stale.tmp",
                    "version_id": "stale-version",
                    "bytes": 1,
                    "sha256": "f" * 64,
                    "checksums": {
                        "ChecksumSHA256": base64.b64encode(
                            bytes.fromhex("f" * 64)
                        ).decode(),
                        "ChecksumType": "FULL_OBJECT",
                    },
                }
            ),
        }

        with tempfile.TemporaryDirectory() as temporary:
            for label, mutate in cases.items():
                receipt = json.loads(self.receipt_bytes)
                mutate(receipt)
                with self.subTest(label=label), self.assertRaisesRegex(
                    ValueError,
                    "receipt verification failed",
                ):
                    self.run_capture_with_receipt(
                        Path(temporary) / label,
                        receipt,
                    )

    def test_rejects_nullish_materializer_output_version_ids(self) -> None:
        cases = ("null", "None")

        with tempfile.TemporaryDirectory() as temporary:
            for version_id in cases:
                receipt = json.loads(self.receipt_bytes)
                for output in receipt["outputs"].values():
                    output["version_id"] = version_id
                for row in receipt["destination_inventory"]:
                    row["version_id"] = version_id

                with self.subTest(version_id=version_id), self.assertRaisesRegex(
                    ValueError,
                    "failed receipt_outputs_exact",
                ):
                    self.run_capture_with_receipt(
                        Path(temporary) / version_id.lower(),
                        receipt,
                    )

    def test_exact_receipt_download_check_map_must_be_exact(self) -> None:
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
                    self.receipt_bytes,
                    self.metadata,
                    self.metadata,
                    self.receipt_history_rows(),
                    self.receipt_location(),
                    self.parameters,
                    self.destination_prefix,
                    self.kms,
                )

    def test_failed_exact_receipt_download_check_reports_exact_key(self) -> None:
        get_response = {**self.metadata, "VersionId": "wrong-version"}

        with self.assertRaisesRegex(ValueError, "failed get_version_exact"):
            MODULE.validate_exact_receipt(
                self.receipt_bytes,
                get_response,
                self.metadata,
                self.receipt_history_rows(),
                self.receipt_location(),
                self.parameters,
                self.destination_prefix,
                self.kms,
            )

    def test_exact_receipt_content_lengths_must_be_exact_ints(self) -> None:
        for response_name in ("GET", "HEAD"):
            with self.subTest(response_name=response_name):
                get_response = dict(self.metadata)
                head_response = dict(self.metadata)
                if response_name == "GET":
                    get_response["ContentLength"] = float(len(self.receipt_bytes))
                    expected_check = "get_bytes_exact"
                else:
                    head_response["ContentLength"] = float(len(self.receipt_bytes))
                    expected_check = "head_bytes_exact"

                with self.assertRaisesRegex(ValueError, f"failed {expected_check}"):
                    MODULE.validate_exact_receipt(
                        self.receipt_bytes,
                        get_response,
                        head_response,
                        self.receipt_history_rows(),
                        self.receipt_location(),
                        self.parameters,
                        self.destination_prefix,
                        self.kms,
                    )

    def test_exact_receipt_checksums_must_be_exact_strings(self) -> None:
        class CoercibleChecksum:
            def __str__(self) -> str:
                return self.metadata["ChecksumSHA256"]

        for response_name in ("GET", "HEAD"):
            with self.subTest(response_name=response_name):
                get_response = dict(self.metadata)
                head_response = dict(self.metadata)
                checksum = CoercibleChecksum()
                checksum.metadata = self.metadata
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
                        self.receipt_bytes,
                        get_response,
                        head_response,
                        self.receipt_history_rows(),
                        self.receipt_location(),
                        self.parameters,
                        self.destination_prefix,
                        self.kms,
                    )

    def test_logged_receipt_bytes_must_be_exact_int(self) -> None:
        with self.assertRaisesRegex(ValueError, "logged_local_bytes_exact"):
            MODULE.validate_exact_receipt(
                self.receipt_bytes,
                self.metadata,
                self.metadata,
                self.receipt_history_rows(),
                {**self.receipt_location(), "bytes": float(len(self.receipt_bytes))},
                self.parameters,
                self.destination_prefix,
                self.kms,
            )

    def test_materializer_receipt_destination_count_must_be_exact_int(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = json.loads(self.receipt_bytes)
            receipt["destination_initial_version_history_count"] = 0.0

            with self.assertRaisesRegex(
                ValueError,
                "failed receipt_destination_exact",
            ):
                self.run_capture_with_receipt(Path(temporary), receipt)

    def test_materializer_receipt_destination_inventory_bytes_must_be_exact_int(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = json.loads(self.receipt_bytes)
            row = receipt["destination_inventory"][0]
            row["bytes"] = float(row["bytes"])

            with self.assertRaisesRegex(
                ValueError,
                "failed receipt_destination_inventory_exact",
            ):
                self.run_capture_with_receipt(Path(temporary), receipt)

    def test_materializer_receipt_requires_exact_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = json.loads(self.receipt_bytes)
            receipt["schema_version"] = 2.0

            with self.assertRaisesRegex(
                ValueError,
                "failed receipt_schema_status",
            ):
                self.run_capture_with_receipt(Path(temporary), receipt)

    def test_integer_helpers_reject_coercible_values(self) -> None:
        self.assertTrue(MODULE.is_positive_int(1))
        self.assertTrue(MODULE.exact_int(7, 7))

        for value in (True, 1.0, "1", 0, -1, None):
            with self.subTest(helper="is_positive_int", value=value):
                self.assertFalse(MODULE.is_positive_int(value))
        for value in (True, 7.0, "7", 0, None):
            with self.subTest(helper="exact_int", value=value):
                self.assertFalse(MODULE.exact_int(value, 7))

    def test_schema_version_checks_use_exact_integer_helper(self) -> None:
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

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "capture_materializer_terminal.py").read_text(
                encoding="utf-8"
            )
        )
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

    def test_sha256_checksum_guards_avoid_raw_string_coercion(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "capture_materializer_terminal.py").read_text(
                encoding="utf-8"
            )
        )
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

    def test_rejects_symlinked_exact_receipt_download_before_capture(self) -> None:
        def get(region, bucket, key, version_id, destination):
            real_receipt = destination.with_name("real-materialization-receipt.json")
            real_receipt.write_bytes(self.receipt_bytes)
            destination.symlink_to(real_receipt)
            return copy.deepcopy(self.metadata)

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                ValueError,
                "downloaded materialization receipt must be a real file",
            ):
                self.run_capture(self.args(Path(temporary)), get=get)

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
                destination.write_bytes(self.receipt_bytes)
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

    def test_private_create_fsyncs_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"

            with mock.patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                MODULE.create_private(path, b"first")

            fsync_directory.assert_called_once_with(path.parent)

    def test_private_create_removes_partial_output_after_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=OSError("synthetic fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic fsync failure"),
            ):
                MODULE.create_private(path, b"partial")

            self.assertFalse(path.exists())

    def test_private_create_removes_output_after_parent_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=OSError("synthetic parent fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic parent fsync failure"),
            ):
                MODULE.create_private(path, b"partial")

            self.assertFalse(path.exists())

    def test_private_create_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                real_fsync_directory(parent)
                path.write_bytes(b"tampered")

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
                MODULE.create_private(path, b"complete")

            self.assertFalse(path.exists())

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
