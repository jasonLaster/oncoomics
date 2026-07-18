#!/usr/bin/env python3
from __future__ import annotations

import base64
import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "freeze_stage_provenance", SCRIPT_DIR / "freeze_stage_provenance.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ACCOUNT = "172630973301"
REGION = "us-east-1"
RUN_ID = "diana-wgs-hrd-test"
JOB_ID = "job-id"
KMS = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
SOURCE_BUCKET = f"diana-omics-work-{ACCOUNT}-{REGION}"
DESTINATION_BUCKET = f"diana-omics-private-results-{ACCOUNT}-{REGION}"


def execution_fixture() -> tuple[dict, dict]:
    worker_sha = "a" * 64
    command = MODULE.expected_execution_command(SOURCE_BUCKET, RUN_ID, REGION)
    job = {
        "jobArn": f"arn:aws:batch:{REGION}:{ACCOUNT}:job/{JOB_ID}",
        "jobId": JOB_ID,
        "jobName": "wgs",
        "jobDefinition": f"arn:aws:batch:{REGION}:{ACCOUNT}:job-definition/wgs:1",
        "jobQueue": f"arn:aws:batch:{REGION}:{ACCOUNT}:job-queue/wgs",
        "status": "SUCCEEDED",
        "retryStrategy": {"attempts": 1, "evaluateOnExit": []},
        "timeout": {"attemptDurationSeconds": 129600},
        "container": {
            "command": command,
            "image": f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/diana-omics:image",
            "jobRoleArn": f"arn:aws:iam::{ACCOUNT}:role/batch",
            "logStreamName": "wgs/default/stream",
            "taskArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/cluster/task-id",
        },
    }
    normalized_attempt = {
        "started_at_epoch_ms": 1,
        "stopped_at_epoch_ms": 2,
        "status_reason": "",
        "container_instance_arn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:container-instance/cluster/instance-id",
        "task_arn": job["container"]["taskArn"],
        "log_stream": job["container"]["logStreamName"],
        "exit_code": 0,
        "reason": "",
    }
    job["attempts"] = [
        {
            "startedAt": 1,
            "stoppedAt": 2,
            "statusReason": "",
            "container": {
                "containerInstanceArn": normalized_attempt["container_instance_arn"],
                "taskArn": normalized_attempt["task_arn"],
                "logStreamName": normalized_attempt["log_stream"],
                "exitCode": 0,
                "reason": "",
            },
        }
    ]
    receipt = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "region": REGION,
        "batch": {
            "job_id": JOB_ID,
            "job_name": "wgs",
            "job_definition_arn": job["jobDefinition"],
            "job_queue_arn": job["jobQueue"],
            "job_role_arn": job["container"]["jobRoleArn"],
            "log_stream": job["container"]["logStreamName"],
            "command": command,
            "status": "SUCCEEDED",
            "attempt_count": 1,
            "attempts": [normalized_attempt],
            "retry_strategy": job["retryStrategy"],
            "timeout": job["timeout"],
        },
        "container": {
            "image_reference": job["container"]["image"],
            "task_arn": job["container"]["taskArn"],
        },
        "worker": {
            "launch_uri": (
                f"s3://{SOURCE_BUCKET}/runs/diana-hrd/{RUN_ID}/inputs/"
                "diana_hrd_wgs_worker.py"
            ),
            "executed_uri": (
                f"s3://{DESTINATION_BUCKET}/runs/subject01/{RUN_ID}/deterministic/"
                f"provenance/executed-workers/{worker_sha}.py"
            ),
            "executed_version_id": "worker-version",
            "freeze_receipt_version_id": "freeze-version",
            "bytes": 42,
            "sha256": worker_sha,
            "server_side_encryption": "aws:kms",
            "kms_key_id": KMS,
            "checksums": {
                "ChecksumSHA256": base64.b64encode(bytes.fromhex(worker_sha)).decode(
                    "ascii"
                )
            },
            "checks": {"task_identity": True, "sha256": True},
        },
    }
    return receipt, job


def object_head(payload: bytes, *, version_id: str = "null") -> dict:
    return {
        "ContentLength": len(payload),
        "ETag": '"etag"',
        "ChecksumType": "FULL_OBJECT",
        "ChecksumSHA256": "checksum",
        "VersionId": version_id,
        "ContentType": "application/json",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": KMS,
    }


def preflight_payload(run_id: str = RUN_ID) -> dict:
    return {
        "status": "passed",
        "run_id": run_id,
        "reference": "UCSC hg38 analysis set full",
        "wgs_lanes": 8,
        "wgs_bytes": 100,
        "boundary": "Preflight only; no sample interpretation.",
        "tools": {
            "aws": "/opt/aws",
            "bcftools": "/usr/bin/bcftools",
            "bwa": "/usr/bin/bwa",
            "java": "/usr/bin/java",
            "samtools": "/usr/bin/samtools",
        },
    }


def gather_payload(run_id: str = RUN_ID) -> dict:
    return {
        "status": "passed",
        "run_id": run_id,
        "reference": "ucsc_hg38_analysis_set_full",
        "duplicate_marking": (
            "samtools fixmate -m per lane followed by merged samtools markdup"
        ),
        "samples": [
            {
                "status": "passed",
                "role": role,
                "lane_count": 4,
                "output_bam": f"{role}.markdup.bam",
                "output_bam_bytes": 100,
            }
            for role in ("normal", "tumor")
        ],
    }


class FreezeStageProvenanceTests(unittest.TestCase):
    def test_validate_execution_requires_exact_job_command_worker_and_kms(self) -> None:
        receipt, job = execution_fixture()
        self.assertEqual(
            MODULE.validate_execution(
                receipt, job, JOB_ID, RUN_ID, REGION, KMS
            ),
            ACCOUNT,
        )
        tampered = []
        wrong_command = deepcopy(receipt)
        wrong_command["batch"]["command"][-1] += " --wrong"
        tampered.append(wrong_command)
        wrong_launch = deepcopy(receipt)
        wrong_launch["worker"]["launch_uri"] = "s3://wrong/worker.py"
        tampered.append(wrong_launch)
        null_version = deepcopy(receipt)
        null_version["worker"]["executed_version_id"] = "null"
        tampered.append(null_version)
        wrong_kms = deepcopy(receipt)
        wrong_kms["worker"]["kms_key_id"] = "wrong"
        tampered.append(wrong_kms)
        wrong_effective_timeout = deepcopy(receipt)
        wrong_effective_timeout["batch"]["timeout"]["attemptDurationSeconds"] = 64800
        tampered.append(wrong_effective_timeout)
        for candidate in tampered:
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(ValueError, "exact successful"):
                    MODULE.validate_execution(
                        candidate, job, JOB_ID, RUN_ID, REGION, KMS
                    )

    def test_validate_source_documents_bind_run_roles_lanes_and_reference(self) -> None:
        MODULE.validate_source_document("preflight.json", preflight_payload(), RUN_ID)
        MODULE.validate_source_document("gather.json", gather_payload(), RUN_ID)
        with self.assertRaisesRegex(ValueError, "exact passed run"):
            MODULE.validate_source_document(
                "preflight.json", preflight_payload("wrong-run"), RUN_ID
            )
        wrong_gather = gather_payload()
        wrong_gather["samples"][1]["lane_count"] = 3
        with self.assertRaisesRegex(ValueError, "tumor sample"):
            MODULE.validate_source_document("gather.json", wrong_gather, RUN_ID)

    def test_source_stable_compares_full_identity(self) -> None:
        payload = json.dumps(preflight_payload()).encode()
        before = object_head(payload)
        self.assertTrue(MODULE.source_stable(before, dict(before)))
        for field, value in (
            ("ChecksumSHA256", "changed"),
            ("SSEKMSKeyId", "wrong"),
            ("VersionId", "old-version"),
            ("ContentType", "text/plain"),
        ):
            with self.subTest(field=field):
                self.assertFalse(MODULE.source_stable(before, {**before, field: value}))

    def test_get_response_must_match_head_and_local_bytes(self) -> None:
        payload = b"payload"
        head = object_head(payload, version_id="v1")
        with tempfile.TemporaryDirectory() as value:
            local = Path(value) / "object"
            local.write_bytes(payload)
            self.assertTrue(
                MODULE.response_matches_head(
                    dict(head), head, local, expected_version_id="v1"
                )
            )
            self.assertFalse(
                MODULE.response_matches_head(
                    {**head, "ChecksumSHA256": "wrong"},
                    head,
                    local,
                    expected_version_id="v1",
                )
            )

    def test_copy_and_receipt_put_are_conditional_and_kms_bound(self) -> None:
        with patch.object(
            MODULE, "aws_json", return_value={"VersionId": "destination-version"}
        ) as mocked:
            MODULE.copy_object(
                "work-bucket",
                "path with space/preflight.json",
                '"etag"',
                "private-bucket",
                "frozen/preflight.json",
                KMS,
                "CRC64NVME",
                REGION,
        )
        arguments, region = mocked.call_args.args
        self.assertEqual(region, REGION)
        self.assertEqual(
            arguments,
            [
                "s3api",
                "copy-object",
                "--copy-source",
                "work-bucket/path%20with%20space/preflight.json",
                "--copy-source-if-match",
                '"etag"',
                "--bucket",
                "private-bucket",
                "--key",
                "frozen/preflight.json",
                "--if-none-match",
                "*",
                "--server-side-encryption",
                "aws:kms",
                "--sse-kms-key-id",
                KMS,
                "--checksum-algorithm",
                "CRC64NVME",
            ],
        )
        with tempfile.TemporaryDirectory() as value:
            receipt = Path(value) / "receipt.json"
            receipt.write_text("{}")
            receipt_checksum = MODULE.checksum_sha256(MODULE.sha256(receipt))
            with patch.object(MODULE, "aws_json", return_value={}) as mocked_put:
                MODULE.put_receipt(
                    receipt, "private-bucket", "receipt-key", KMS, REGION
                )
        put_arguments, put_region = mocked_put.call_args.args
        self.assertEqual(put_region, REGION)
        self.assertEqual(
            put_arguments,
            [
                "s3api",
                "put-object",
                "--bucket",
                "private-bucket",
                "--key",
                "receipt-key",
                "--body",
                str(receipt),
                "--if-none-match",
                "*",
                "--server-side-encryption",
                "aws:kms",
                "--sse-kms-key-id",
                KMS,
                "--checksum-algorithm",
                "SHA256",
                "--checksum-sha256",
                receipt_checksum,
                "--content-type",
                "application/json",
            ],
        )

    def test_version_history_consumes_pages_and_labels_delete_markers(self) -> None:
        pages = [
            {
                "Versions": [{"VersionId": "v1"}],
                "IsTruncated": True,
                "NextKeyMarker": "next-key",
                "NextVersionIdMarker": "next-version",
            },
            {
                "DeleteMarkers": [{"VersionId": "d1"}],
                "IsTruncated": False,
            },
        ]
        with patch.object(MODULE, "aws_json", side_effect=pages) as mocked:
            rows = MODULE.version_history("bucket", "prefix", REGION)
        self.assertEqual(
            [(row["history_type"], row["VersionId"]) for row in rows],
            [("Versions", "v1"), ("DeleteMarkers", "d1")],
        )
        self.assertIn("--key-marker", mocked.call_args_list[1].args[0])
        self.assertIn("--version-id-marker", mocked.call_args_list[1].args[0])

    def test_version_history_rejects_malformed_and_stalled_pagination(self) -> None:
        with patch.object(MODULE, "aws_json", return_value={"Versions": {}}):
            with self.assertRaisesRegex(RuntimeError, "malformed"):
                MODULE.version_history("bucket", "prefix", REGION)
        stalled = {
            "IsTruncated": True,
            "NextKeyMarker": "same",
            "NextVersionIdMarker": "same",
        }
        with patch.object(MODULE, "aws_json", side_effect=[stalled, stalled]):
            with self.assertRaisesRegex(RuntimeError, "did not advance"):
                MODULE.version_history("bucket", "prefix", REGION)

    def test_exact_history_rejects_extra_versions_and_delete_markers(self) -> None:
        expected = [
            {
                "history_type": "Versions",
                "Key": "key",
                "VersionId": "v1",
                "IsLatest": True,
                "Size": 1,
                "ETag": '"etag"',
            }
        ]
        self.assertTrue(MODULE.exact_history_matches(expected, deepcopy(expected)))
        self.assertFalse(
            MODULE.exact_history_matches(
                [
                    *expected,
                    {
                        "history_type": "DeleteMarkers",
                        "Key": "key",
                        "VersionId": "d1",
                        "IsLatest": True,
                    },
                ],
                expected,
            )
        )

    def test_null_versions_and_cross_account_kms_are_rejected(self) -> None:
        for value in ("", None, "null", "None", " NULL "):
            self.assertFalse(MODULE.valid_version_id(value))
        self.assertTrue(MODULE.valid_version_id("version-1"))
        MODULE.validate_kms_arn(KMS, ACCOUNT, REGION)
        with self.assertRaisesRegex(ValueError, "account and region"):
            MODULE.validate_kms_arn(
                KMS.replace(ACCOUNT, "999999999999"), ACCOUNT, REGION
            )

    def test_atomic_writer_preserves_existing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "receipt.json"
            MODULE.write_json_once(path, {"status": "passed"})
            first = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "refusing to replace"):
                MODULE.write_json_once(path, {"status": "failed"})
            self.assertEqual(path.read_bytes(), first)

    def test_atomic_writer_fsyncs_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "receipt.json"

            with patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                MODULE.write_json_once(path, {"status": "passed"})

            fsync_directory.assert_called_once_with(path.parent)

    def test_atomic_writer_removes_receipt_after_parent_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            path = root / "receipt.json"

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=OSError("synthetic parent fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic parent fsync failure"),
            ):
                MODULE.write_json_once(path, {"status": "passed"})

            self.assertFalse(path.exists())
            self.assertEqual(list(root.glob(".receipt.json.*.tmp")), [])

    def test_atomic_writer_rejects_output_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "missing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent must not be a symlink"):
                MODULE.write_json_once(output, {"status": "redirected"})

            self.assertFalse((real_parent / "missing" / "receipt.json").exists())

    def test_atomic_writer_rejects_existing_dir_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "existing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent must not be a symlink"):
                MODULE.write_json_once(output, {"status": "redirected"})

            self.assertFalse((real_parent / "existing" / "receipt.json").exists())

    def test_load_json_rejects_symlinked_input(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            target = root / "execution.json"
            target.write_text('{"status":"passed"}\n', encoding="utf-8")
            linked = root / "linked-execution.json"
            linked.symlink_to(target)

            with self.assertRaisesRegex(ValueError, "must be a real file"):
                MODULE.load_json(linked)

    def test_load_json_rejects_input_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-inputs"
            real_parent.mkdir()
            (real_parent / "input.json").write_text('{"status":"passed"}\n')
            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent must not be a symlink"):
                MODULE.load_json(linked_parent / "input.json")

    def test_main_rejects_symlink_output_before_aws_observation(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            output = root / "receipt.json"
            output.symlink_to(root / "target.json")
            anchor = root / "anchor.json"
            execution = root / "execution.json"
            argv = [
                "freeze_stage_provenance.py",
                "--job-id",
                JOB_ID,
                "--run-id",
                RUN_ID,
                "--execution-receipt",
                str(execution),
                "--kms-key-arn",
                KMS,
                "--output",
                str(output),
                "--anchor-output",
                str(anchor),
                "--region",
                REGION,
            ]

            with (
                patch.object(sys, "argv", argv),
                patch.object(MODULE, "aws_json") as mocked_aws,
                self.assertRaisesRegex(SystemExit, "must not be a symlink"),
            ):
                MODULE.main()

            mocked_aws.assert_not_called()

    def test_copy_success_then_validation_failure_records_version_and_history(self) -> None:
        preflight = (json.dumps(preflight_payload(), sort_keys=True) + "\n").encode()
        source_head = object_head(preflight)
        failure_history = [
            {
                "history_type": "Versions",
                "Key": (
                    f"runs/subject01/{RUN_ID}/deterministic/provenance/"
                    "wgs-stage/preflight.json"
                ),
                "VersionId": "copied-version",
                "IsLatest": True,
                "Size": len(preflight),
                "ETag": '"etag"',
            }
        ]

        def fake_download(
            _bucket: str,
            _key: str,
            destination: Path,
            _region: str,
            **_kwargs: object,
        ) -> dict:
            destination.write_bytes(preflight)
            return dict(source_head)

        with tempfile.TemporaryDirectory() as value:
            directory = Path(value)
            execution = directory / "execution.json"
            execution.write_text("{}\n")
            output = directory / "receipt.json"
            anchor = directory / "anchor.json"
            argv = [
                "freeze_stage_provenance.py",
                "--job-id",
                JOB_ID,
                "--run-id",
                RUN_ID,
                "--execution-receipt",
                str(execution),
                "--kms-key-arn",
                KMS,
                "--output",
                str(output),
                "--anchor-output",
                str(anchor),
                "--region",
                REGION,
                "--apply",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    MODULE,
                    "aws_json",
                    return_value={"jobs": [{"jobId": JOB_ID}]},
                ),
                patch.object(MODULE, "validate_execution", return_value=ACCOUNT),
                patch.object(
                    MODULE, "bucket_versioning", side_effect=["Suspended", "Enabled"]
                ),
                patch.object(
                    MODULE, "version_history", side_effect=[[], failure_history]
                ),
                patch.object(
                    MODULE,
                    "head_object",
                    side_effect=[
                        source_head,
                        source_head,
                        RuntimeError("destination head failed"),
                    ],
                ),
                patch.object(MODULE, "download_object", side_effect=fake_download),
                patch.object(
                    MODULE,
                    "copy_object",
                    return_value={"VersionId": "copied-version"},
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "destination head failed"):
                    MODULE.main()
            failure = json.loads(output.read_text())
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(
                failure["objects"][0]["destination"]["version_id"],
                "copied-version",
            )
            self.assertEqual(failure["objects"][0]["status"], "copy_returned")
            self.assertEqual(failure["destination_history_at_failure"], failure_history)
            self.assertEqual(json.loads(anchor.read_text())["status"], "failed_before_receipt_anchor")


if __name__ == "__main__":
    unittest.main()
