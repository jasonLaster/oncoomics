#!/usr/bin/env python3
from __future__ import annotations

import ast
import base64
import hashlib
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
LEGACY_BATCH_WORKER_CHECKS = {
    "receipt_status": True,
    "receipt_checks": True,
    "receipt_upload": True,
    "task_identity": True,
    "task_host_mapping": True,
    "hash_command_definition": True,
    "freeze_command_definition": True,
    "live_hash_command": True,
    "live_freeze_command": True,
    "exact_version": True,
    "bytes": True,
    "sha256": True,
    "full_object_checksum": True,
    "kms": True,
}


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
            "checks": dict(MODULE.EXPECTED_BATCH_WORKER_CHECKS),
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


def stage_payload_bytes() -> dict[str, bytes]:
    return {
        "preflight.json": (
            json.dumps(preflight_payload(), sort_keys=True) + "\n"
        ).encode(),
        "gather.json": (json.dumps(gather_payload(), sort_keys=True) + "\n").encode(),
    }


def stage_dry_run_receipt(execution: Path, payloads: dict[str, bytes]) -> dict:
    source_prefix = f"runs/diana-hrd/{RUN_ID}/private-results/"
    destination_prefix = f"runs/subject01/{RUN_ID}/deterministic/provenance/wgs-stage/"
    objects = []
    for name in MODULE.SOURCE_NAMES:
        payload = payloads[name]
        head = object_head(payload)
        objects.append(
            {
                "name": name,
                "source": {
                    "bucket": SOURCE_BUCKET,
                    "key": source_prefix + name,
                    "version_id": "null",
                    "bytes": len(payload),
                    "etag": str(head["ETag"]),
                    "checksums": MODULE.checksums(head),
                    "checksum_type": "FULL_OBJECT",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": KMS,
                    "get_response": head,
                },
                "destination": {
                    "bucket": DESTINATION_BUCKET,
                    "key": destination_prefix + name,
                },
                "checks": dict(MODULE.EXPECTED_DRY_RUN_CHECKS),
                "status": "dry_run",
            }
        )
    return {
        "schema_version": 1,
        "status": "dry_run",
        "generated_at": "2026-07-19T00:00:00+00:00",
        "run_id": RUN_ID,
        "batch_job_id": JOB_ID,
        "batch_status": "SUCCEEDED",
        "execution_receipt_sha256": MODULE.sha256(execution),
        "source_prefix": f"s3://{SOURCE_BUCKET}/{source_prefix}",
        "destination_prefix": f"s3://{DESTINATION_BUCKET}/{destination_prefix}",
        "kms_key_arn": KMS,
        "source_bucket_versioning": "Suspended",
        "destination_bucket_versioning": "Enabled",
        "destination_initial_version_history_count": 0,
        "script_sha256": MODULE.sha256(Path(MODULE.__file__)),
        "receipt_anchor_strategy": "sha256_content_addressed_never_overwritten",
        "objects": objects,
        "completed_at": "2026-07-19T00:01:00+00:00",
        "object_count": len(objects),
        "passed_count": 0,
    }


def write_stage_dry_run_receipt(
    path: Path, execution: Path
) -> tuple[Path, dict[str, bytes]]:
    payloads = stage_payload_bytes()
    path.write_text(
        json.dumps(
            stage_dry_run_receipt(execution, payloads),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path, payloads


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
        wrong_schema = deepcopy(receipt)
        wrong_schema["schema_version"] = 1.0
        tampered.append(wrong_schema)
        for value in (True, 42.0, "42", 0):
            non_exact_worker_bytes = deepcopy(receipt)
            non_exact_worker_bytes["worker"]["bytes"] = value
            tampered.append(non_exact_worker_bytes)
        legacy_worker_checks = deepcopy(receipt)
        legacy_worker_checks["worker"]["checks"] = dict(LEGACY_BATCH_WORKER_CHECKS)
        tampered.append(legacy_worker_checks)
        missing_worker_check = deepcopy(receipt)
        missing_worker_check["worker"]["checks"].pop("receipt_envelope")
        tampered.append(missing_worker_check)
        unexpected_worker_check = deepcopy(receipt)
        unexpected_worker_check["worker"]["checks"]["forged_extra"] = True
        tampered.append(unexpected_worker_check)
        failed_worker_check = deepcopy(receipt)
        failed_worker_check["worker"]["checks"]["live_freeze_command"] = False
        tampered.append(failed_worker_check)
        for candidate in tampered:
            with self.subTest(candidate=candidate):
                with self.assertRaisesRegex(ValueError, "exact successful"):
                    MODULE.validate_execution(
                        candidate, job, JOB_ID, RUN_ID, REGION, KMS
                    )

    def test_validate_execution_requires_exact_live_attempt_ints(self) -> None:
        receipt, job = execution_fixture()
        for label, mutate in (
            (
                "started-boolean",
                lambda candidate: candidate["attempts"][0].__setitem__(
                    "startedAt",
                    True,
                ),
            ),
            (
                "stopped-float",
                lambda candidate: candidate["attempts"][0].__setitem__(
                    "stoppedAt",
                    2.0,
                ),
            ),
            (
                "exit-string",
                lambda candidate: candidate["attempts"][0]["container"].__setitem__(
                    "exitCode",
                    "0",
                ),
            ),
        ):
            with self.subTest(label=label):
                mutated_job = deepcopy(job)
                mutate(mutated_job)
                with self.assertRaisesRegex(ValueError, "exact integer"):
                    MODULE.validate_execution(
                        receipt,
                        mutated_job,
                        JOB_ID,
                        RUN_ID,
                        REGION,
                        KMS,
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
        for value in (True, 100.0, "100"):
            with self.subTest(document="preflight", value=value):
                wrong_preflight = preflight_payload()
                wrong_preflight["wgs_bytes"] = value
                with self.assertRaisesRegex(ValueError, "WGS stage semantics"):
                    MODULE.validate_source_document(
                        "preflight.json", wrong_preflight, RUN_ID
                    )
            with self.subTest(document="gather", value=value):
                wrong_gather = gather_payload()
                wrong_gather["samples"][1]["output_bam_bytes"] = value
                with self.assertRaisesRegex(ValueError, "tumor sample"):
                    MODULE.validate_source_document(
                        "gather.json", wrong_gather, RUN_ID
                    )

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
        for value in (True, len(payload) * 1.0, str(len(payload))):
            with self.subTest(content_length=value):
                self.assertFalse(
                    MODULE.source_stable(
                        {**before, "ContentLength": value},
                        before,
                    )
                )
                self.assertFalse(
                    MODULE.source_stable(
                        before,
                        {**before, "ContentLength": value},
                    )
                )

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
            for response_name in ("GET", "HEAD"):
                for content_length in (True, len(payload) * 1.0, str(len(payload))):
                    with self.subTest(
                        response_name=response_name,
                        content_length=content_length,
                    ):
                        response = dict(head)
                        current_head = dict(head)
                        if response_name == "GET":
                            response["ContentLength"] = content_length
                        else:
                            current_head["ContentLength"] = content_length
                        self.assertFalse(
                            MODULE.response_matches_head(
                                response,
                                current_head,
                                local,
                                expected_version_id="v1",
                            )
                        )

    def test_prepare_source_row_content_length_must_be_exact_integer(self) -> None:
        for value in (True, 7.0, "7"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as raw:
                head = {**object_head(b"payload"), "ContentLength": value}
                with (
                    patch.object(MODULE, "head_object", return_value=head),
                    patch.object(
                        MODULE,
                        "download_object",
                        side_effect=AssertionError("downloaded"),
                    ),
                    self.assertRaisesRegex(RuntimeError, "invalid unversioned"),
                ):
                    MODULE.prepare_source_row(
                        name="preflight.json",
                        source_bucket=SOURCE_BUCKET,
                        source_prefix=f"runs/diana-hrd/{RUN_ID}/private-results/",
                        destination_bucket=DESTINATION_BUCKET,
                        destination_prefix=(
                            f"runs/subject01/{RUN_ID}/deterministic/"
                            "provenance/wgs-stage/"
                        ),
                        kms_key_arn=KMS,
                        run_id=RUN_ID,
                        region=REGION,
                        temp=Path(raw),
                    )

    def test_download_object_rejects_symlinked_destination(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            destination = Path(value) / "downloaded.json"

            def aws_json(arguments, region):
                real_download = destination.with_name("real-downloaded.json")
                real_download.write_text('{"status":"passed"}\n', encoding="utf-8")
                destination.symlink_to(real_download)
                return {"VersionId": "exact-version"}

            with (
                patch.object(MODULE, "aws_json", side_effect=aws_json),
                self.assertRaisesRegex(
                    ValueError,
                    "downloaded provenance object must not be a symlink",
                ),
            ):
                MODULE.download_object(
                    DESTINATION_BUCKET,
                    "receipt.json",
                    destination,
                    REGION,
                    version_id="exact-version",
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
        for value in (True, 1.0, "1"):
            with self.subTest(value=value):
                self.assertFalse(
                    MODULE.exact_history_matches(
                        [{**expected[0], "Size": value}],
                        expected,
                    )
                )
                self.assertFalse(
                    MODULE.exact_history_matches(
                        expected,
                        [{**expected[0], "Size": value}],
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

    def test_atomic_writer_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "receipt.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                real_fsync_directory(parent)
                path.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "local evidence output changed during write",
                ),
            ):
                MODULE.write_json_once(path, {"status": "passed"})

            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob(".receipt.json.*.tmp")), [])

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

    def test_apply_requires_dry_run_receipt_before_aws(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [
                    "freeze_stage_provenance.py",
                    "--job-id",
                    JOB_ID,
                    "--run-id",
                    RUN_ID,
                    "--execution-receipt",
                    "execution.json",
                    "--kms-key-arn",
                    KMS,
                    "--output",
                    "receipt.json",
                    "--anchor-output",
                    "anchor.json",
                    "--region",
                    REGION,
                    "--apply",
                ],
            ),
            patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            self.assertRaisesRegex(SystemExit, "requires --dry-run-receipt"),
        ):
            MODULE.main()

    def test_dry_run_receipt_is_only_valid_with_apply_before_aws(self) -> None:
        with (
            patch.object(
                sys,
                "argv",
                [
                    "freeze_stage_provenance.py",
                    "--job-id",
                    JOB_ID,
                    "--run-id",
                    RUN_ID,
                    "--execution-receipt",
                    "execution.json",
                    "--kms-key-arn",
                    KMS,
                    "--output",
                    "receipt.json",
                    "--anchor-output",
                    "anchor.json",
                    "--region",
                    REGION,
                    "--dry-run-receipt",
                    "receipt.dry.json",
                ],
            ),
            patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            self.assertRaisesRegex(SystemExit, "only valid with --apply"),
        ):
            MODULE.main()

    def test_validate_dry_run_receipt_rejects_stale_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            execution = root / "execution.json"
            execution.write_text("{}\n", encoding="utf-8")
            payloads = stage_payload_bytes()
            receipt = stage_dry_run_receipt(execution, payloads)
            path = root / "stage.dry.json"

            for label, mutate, message in (
                (
                    "extra-top-level",
                    lambda payload: payload.__setitem__(
                        "stale_receipt_sha256", "0" * 64
                    ),
                    "stale or missing metadata",
                ),
                (
                    "stale-run-binding",
                    lambda payload: payload.__setitem__("batch_job_id", "stale-job"),
                    "does not match this apply",
                ),
                (
                    "non-exact-schema",
                    lambda payload: payload.__setitem__("schema_version", 1.0),
                    "did not pass preflight",
                ),
                (
                    "stale-object",
                    lambda payload: payload["objects"][0]["source"].__setitem__(
                        "sha256", "0" * 64
                    ),
                    "object evidence does not match this apply",
                ),
                (
                    "failed-object-check",
                    lambda payload: payload["objects"][0]["checks"].__setitem__(
                        "source_kms_exact", False
                    ),
                    "object evidence does not match this apply",
                ),
            ):
                with self.subTest(label=label):
                    mutated = deepcopy(receipt)
                    mutate(mutated)
                    path.write_text(
                        json.dumps(mutated, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.validate_dry_run_receipt(path, receipt)

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

    def test_s3_byte_helpers_require_exact_integers(self) -> None:
        for value in (1, 7):
            with self.subTest(value=value):
                self.assertTrue(MODULE.is_positive_exact_int(value))
                self.assertTrue(MODULE.exact_int(value, value))
        for value in (True, 1.0, "1", 0, -1, None):
            with self.subTest(value=value):
                self.assertFalse(MODULE.is_positive_exact_int(value))
                self.assertFalse(MODULE.exact_int(value, 1))

    def test_s3_byte_guards_avoid_raw_int_coercion(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "freeze_stage_provenance.py").read_text(
                encoding="utf-8"
            )
        )
        raw_byte_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and node.args
            and any(
                field in ast.unparse(node.args[0])
                for field in (
                    "ContentLength",
                    "Size",
                    "bytes",
                    "wgs_bytes",
                    "output_bam_bytes",
                )
            )
        ]

        self.assertEqual(raw_byte_coercions, [])

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "freeze_stage_provenance.py").read_text(
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
        payloads = stage_payload_bytes()
        failure_history = [
            {
                "history_type": "Versions",
                "Key": (
                    f"runs/subject01/{RUN_ID}/deterministic/provenance/"
                    "wgs-stage/preflight.json"
                ),
                "VersionId": "copied-version",
                "IsLatest": True,
                "Size": len(payloads["preflight.json"]),
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
            name = _key.rsplit("/", 1)[-1]
            destination.write_bytes(payloads[name])
            return object_head(payloads[name])

        def fake_head(
            bucket: str, key: str, _region: str, version_id: str = ""
        ) -> dict:
            if bucket == DESTINATION_BUCKET:
                raise RuntimeError("destination head failed")
            return object_head(payloads[key.rsplit("/", 1)[-1]])

        with tempfile.TemporaryDirectory() as value:
            directory = Path(value)
            execution = directory / "execution.json"
            execution.write_text("{}\n")
            output = directory / "receipt.json"
            anchor = directory / "anchor.json"
            dry_run, payloads = write_stage_dry_run_receipt(
                directory / "receipt.dry.json",
                execution,
            )
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
                "--dry-run-receipt",
                str(dry_run),
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
                patch.object(MODULE, "head_object", side_effect=fake_head),
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
