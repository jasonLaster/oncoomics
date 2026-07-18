#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "freeze_final_artifacts", SCRIPT_DIR / "freeze_final_artifacts.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FreezeFinalArtifactsTests(unittest.TestCase):
    def test_parse_s3_rejects_bucket_only(self) -> None:
        self.assertEqual(MODULE.parse_s3("s3://private-bucket/path/to/tree"), ("private-bucket", "path/to/tree"))
        with self.assertRaises(ValueError):
            MODULE.parse_s3("s3://private-bucket")

    def test_common_checksum_requires_shared_equal_algorithm(self) -> None:
        self.assertTrue(
            MODULE.common_checksum_matches(
                {
                    "ChecksumCRC64NVME": "same",
                    "ChecksumSHA256": "left",
                    "ChecksumType": "FULL_OBJECT",
                },
                {"ChecksumCRC64NVME": "same", "ChecksumType": "FULL_OBJECT"},
            )
        )
        self.assertFalse(
            MODULE.common_checksum_matches(
                {"ChecksumCRC64NVME": "left", "ChecksumType": "FULL_OBJECT"},
                {"ChecksumCRC64NVME": "right", "ChecksumType": "FULL_OBJECT"},
            )
        )
        self.assertFalse(
            MODULE.common_checksum_matches(
                {"ChecksumSHA256": "left", "ChecksumType": "FULL_OBJECT"},
                {"ChecksumCRC64NVME": "left", "ChecksumType": "FULL_OBJECT"},
            )
        )
        self.assertFalse(
            MODULE.common_checksum_matches(
                {"ChecksumCRC64NVME": "same", "ChecksumType": "COMPOSITE"},
                {"ChecksumCRC64NVME": "same", "ChecksumType": "FULL_OBJECT"},
            )
        )

    def test_relative_key_rejects_traversal_and_backslash(self) -> None:
        self.assertEqual(MODULE.safe_relative_key("variants/final.vcf.gz"), "variants/final.vcf.gz")
        for value in ("", "/absolute", "../escape", "variants/../../escape", "variants\\escape"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.safe_relative_key(value)

    def test_checksum_algorithm_prefers_crc64_then_sha256(self) -> None:
        self.assertEqual(
            MODULE.preferred_checksum_algorithm(
                {"ChecksumSHA256": "sha", "ChecksumCRC64NVME": "crc"}
            ),
            "CRC64NVME",
        )
        self.assertEqual(
            MODULE.preferred_checksum_algorithm({"ChecksumSHA256": "sha"}),
            "SHA256",
        )
        with self.assertRaisesRegex(ValueError, "no supported checksum"):
            MODULE.preferred_checksum_algorithm({})

    def test_copy_uses_exact_source_version_etag_checksum_and_kms(self) -> None:
        with patch.object(
            MODULE,
            "aws_json",
            return_value={"VersionId": "destination-version"},
        ) as mocked:
            result = MODULE.copy_object(
                "source-bucket",
                "path with space/final.vcf.gz",
                "source/version+id",
                '"etag"',
                "destination-bucket",
                "frozen/final.vcf.gz",
                "arn:aws:kms:us-east-1:1:key/test",
                "CRC64NVME",
                "us-east-1",
            )
        self.assertEqual(result["VersionId"], "destination-version")
        arguments, region = mocked.call_args.args
        self.assertEqual(region, "us-east-1")
        self.assertEqual(
            arguments,
            [
                "s3api",
                "copy-object",
                "--copy-source",
                (
                    "source-bucket/path%20with%20space/final.vcf.gz"
                    "?versionId=source%2Fversion%2Bid"
                ),
                "--copy-source-if-match",
                '"etag"',
                "--bucket",
                "destination-bucket",
                "--key",
                "frozen/final.vcf.gz",
                "--if-none-match",
                "*",
                "--server-side-encryption",
                "aws:kms",
                "--sse-kms-key-id",
                "arn:aws:kms:us-east-1:1:key/test",
                "--checksum-algorithm",
                "CRC64NVME",
            ],
        )

    def test_copy_omits_version_id_for_unversioned_work_bucket_source(self) -> None:
        with patch.object(
            MODULE,
            "aws_json",
            return_value={"VersionId": "destination-version"},
        ) as mocked:
            result = MODULE.copy_object(
                "source-bucket",
                "private-results/final/artifacts/README.md",
                "null",
                '"etag"',
                "destination-bucket",
                "deterministic/final/README.md",
                "arn:aws:kms:us-east-1:1:key/test",
                "SHA256",
                "us-east-1",
            )
        self.assertEqual(result["VersionId"], "destination-version")
        arguments, _region = mocked.call_args.args
        self.assertIn(
            "source-bucket/private-results/final/artifacts/README.md",
            arguments,
        )
        self.assertNotIn(
            "source-bucket/private-results/final/artifacts/README.md?versionId=null",
            arguments,
        )

    def test_list_objects_consumes_every_page(self) -> None:
        pages = [
            {
                "IsTruncated": True,
                "NextContinuationToken": "next-page",
                "Contents": [{"Key": "prefix/one"}],
            },
            {
                "IsTruncated": False,
                "Contents": [{"Key": "prefix/two"}],
            },
        ]
        with patch.object(MODULE, "aws_json", side_effect=pages) as mocked:
            self.assertEqual(
                MODULE.list_objects("bucket", "prefix/", "us-east-1"),
                [{"Key": "prefix/one"}, {"Key": "prefix/two"}],
            )
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(
            mocked.call_args_list[0].args,
            (
                [
                    "s3api",
                    "list-objects-v2",
                    "--bucket",
                    "bucket",
                    "--prefix",
                    "prefix/",
                ],
                "us-east-1",
            ),
        )
        self.assertEqual(
            mocked.call_args_list[1].args,
            (
                [
                    "s3api",
                    "list-objects-v2",
                    "--bucket",
                    "bucket",
                    "--prefix",
                    "prefix/",
                    "--continuation-token",
                    "next-page",
                ],
                "us-east-1",
            ),
        )

    def test_list_objects_rejects_missing_continuation_token(self) -> None:
        with patch.object(
            MODULE,
            "aws_json",
            return_value={"IsTruncated": True, "Contents": []},
        ):
            with self.assertRaisesRegex(RuntimeError, "NextContinuationToken"):
                MODULE.list_objects("bucket", "prefix/", "us-east-1")

    def test_list_objects_rejects_stalled_pagination(self) -> None:
        stalled = {
            "IsTruncated": True,
            "NextContinuationToken": "same-page",
            "Contents": [{"Key": "prefix/one"}],
        }
        with patch.object(MODULE, "aws_json", side_effect=[stalled, stalled]):
            with self.assertRaisesRegex(RuntimeError, "did not advance"):
                MODULE.list_objects("bucket", "prefix/", "us-east-1")

    def test_version_history_consumes_versions_and_delete_markers_across_pages(self) -> None:
        pages = [
            {
                "Versions": [{"Key": "prefix/a", "VersionId": "v1"}],
                "IsTruncated": True,
                "NextKeyMarker": "prefix/a",
                "NextVersionIdMarker": "v1",
            },
            {
                "DeleteMarkers": [{"Key": "prefix/b", "VersionId": "d1"}],
                "IsTruncated": False,
            },
        ]
        with patch.object(MODULE, "aws_json", side_effect=pages) as mocked:
            rows = MODULE.version_history("bucket", "prefix/", "us-east-1")
        self.assertEqual(
            [(row["VersionId"], row["history_kind"]) for row in rows],
            [("v1", "version"), ("d1", "delete_marker")],
        )
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(
            mocked.call_args_list[0].args,
            (
                [
                    "s3api",
                    "list-object-versions",
                    "--bucket",
                    "bucket",
                    "--prefix",
                    "prefix/",
                ],
                "us-east-1",
            ),
        )
        self.assertEqual(
            mocked.call_args_list[1].args,
            (
                [
                    "s3api",
                    "list-object-versions",
                    "--bucket",
                    "bucket",
                    "--prefix",
                    "prefix/",
                    "--key-marker",
                    "prefix/a",
                    "--version-id-marker",
                    "v1",
                ],
                "us-east-1",
            ),
        )

    def test_version_history_rejects_missing_version_marker(self) -> None:
        with patch.object(
            MODULE,
            "aws_json",
            return_value={
                "Versions": [{"Key": "prefix/a", "VersionId": "v1"}],
                "IsTruncated": True,
                "NextKeyMarker": "prefix/a",
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "next key/version markers"):
                MODULE.version_history("bucket", "prefix/", "us-east-1")

    def test_version_history_rejects_stalled_pagination(self) -> None:
        stalled = {
            "IsTruncated": True,
            "NextKeyMarker": "prefix/a",
            "NextVersionIdMarker": "v1",
        }
        with patch.object(MODULE, "aws_json", side_effect=[stalled, stalled]):
            with self.assertRaisesRegex(RuntimeError, "did not advance"):
                MODULE.version_history("bucket", "prefix/", "us-east-1")

    def test_bucket_versioning_must_be_enabled(self) -> None:
        with patch.object(MODULE, "aws_json", return_value={"Status": "Enabled"}):
            MODULE.require_bucket_versioning("bucket", "us-east-1")
        with patch.object(MODULE, "aws_json", return_value={"Status": "Suspended"}):
            with self.assertRaisesRegex(ValueError, "not Enabled"):
                MODULE.require_bucket_versioning("bucket", "us-east-1")

    def test_snapshot_destination_rejects_hidden_or_duplicate_history(self) -> None:
        with patch.object(
            MODULE,
            "version_history",
            return_value=[
                {
                    "history_kind": "delete_marker",
                    "Key": "prefix/a",
                    "VersionId": "d1",
                }
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "delete marker"):
                MODULE.snapshot_destination("bucket", "prefix/", "kms", "us-east-1")
        duplicate = [
            {
                "history_kind": "version",
                "Key": "prefix/a",
                "VersionId": value,
                "IsLatest": value == "v2",
            }
            for value in ("v1", "v2")
        ]
        with patch.object(MODULE, "version_history", return_value=duplicate):
            with self.assertRaisesRegex(RuntimeError, "multiple versions"):
                MODULE.snapshot_destination("bucket", "prefix/", "kms", "us-east-1")

    def test_destination_snapshot_matches_receipt_exactly(self) -> None:
        history = [
            {
                "history_kind": "version",
                "Key": "prefix/a",
                "VersionId": "v1",
                "IsLatest": True,
            }
        ]
        current = {
            "VersionId": "v1",
            "ContentLength": 10,
            "ETag": '"etag"',
            "ChecksumType": "FULL_OBJECT",
            "ChecksumSHA256": "sha",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "kms",
        }
        with patch.object(MODULE, "version_history", return_value=history), patch.object(
            MODULE,
            "list_objects",
            return_value=[{"Key": "prefix/a", "Size": 10, "ETag": '"etag"'}],
        ), patch.object(MODULE, "head", return_value=current):
            destination = MODULE.snapshot_destination(
                "bucket", "prefix/", "kms", "us-east-1"
            )
        source = [{"relative_key": "a", "bytes": 10}]
        receipt = [
            {
                "relative_key": "a",
                "status": "passed",
                "destination": {"key": "prefix/a", "version_id": "v1"},
            }
        ]
        self.assertTrue(
            MODULE.destination_matches_receipt(source, destination, receipt)
        )
        receipt[0]["destination"]["version_id"] = "changed"
        self.assertFalse(
            MODULE.destination_matches_receipt(source, destination, receipt)
        )

    def test_existing_receipt_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "receipt.json"
            path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "never overwritten"):
                MODULE.require_new_output(path, "receipt")

    def test_new_output_rejects_output_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            path = linked_parent / "missing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent must not be a symlink"):
                MODULE.require_new_output(path, "receipt")

            self.assertFalse((real_parent / "missing" / "receipt.json").exists())

    def test_atomic_writer_rejects_output_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            path = linked_parent / "missing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent must not be a symlink"):
                MODULE.write_json_atomic(path, {"status": "redirected"}, create=True)

            self.assertFalse((real_parent / "missing" / "receipt.json").exists())

    def test_rejects_output_below_existing_dir_under_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            path = linked_parent / "existing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent must not be a symlink"):
                MODULE.write_json_atomic(path, {"status": "redirected"}, create=True)

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

    def test_create_only_receipt_write_preserves_late_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "receipt.json"
            MODULE.write_json_atomic(path, {"status": "initial"}, create=True)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "initial"},
            )

            with self.assertRaises(FileExistsError):
                MODULE.write_json_atomic(path, {"status": "replacement"}, create=True)

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "initial"},
            )

    def test_create_only_receipt_is_born_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "receipt.json"
            original_open = MODULE.os.open
            opened: list[tuple[int, int]] = []

            def spy_open(path_value, flags, mode=0o777, *args, **kwargs):
                if Path(path_value).name.startswith(".receipt.json.tmp-"):
                    opened.append((flags, mode))
                return original_open(path_value, flags, mode, *args, **kwargs)

            with patch.object(MODULE.os, "open", side_effect=spy_open):
                MODULE.write_json_atomic(path, {"status": "initial"}, create=True)

            self.assertEqual(
                opened,
                [(MODULE.os.O_WRONLY | MODULE.os.O_CREAT | MODULE.os.O_EXCL, 0o600)],
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "initial"},
            )

    def test_receipt_put_is_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            receipt = Path(value) / "receipt.json"
            receipt.write_text("{}")
            receipt_checksum = MODULE.checksum_sha256(MODULE.sha256(receipt))
            with patch.object(
                MODULE, "aws_json", return_value={"VersionId": "v1"}
            ) as mocked:
                MODULE.put_receipt(receipt, "bucket", "key", "kms", "us-east-1")
        arguments, region = mocked.call_args.args
        self.assertEqual(region, "us-east-1")
        self.assertEqual(
            arguments,
            [
                "s3api",
                "put-object",
                "--bucket",
                "bucket",
                "--key",
                "key",
                "--body",
                str(receipt),
                "--if-none-match",
                "*",
                "--server-side-encryption",
                "aws:kms",
                "--sse-kms-key-id",
                "kms",
                "--checksum-algorithm",
                "SHA256",
                "--checksum-sha256",
                receipt_checksum,
                "--content-type",
                "application/json",
            ],
        )

    def test_get_exact_object_rejects_symlinked_receipt_download(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            destination = Path(value) / "receipt.json"

            def command(arguments, text):
                real_receipt = destination.with_name("real-receipt.json")
                real_receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
                destination.symlink_to(real_receipt)
                return "{}"

            with (
                patch.object(MODULE.subprocess, "check_output", side_effect=command),
                self.assertRaisesRegex(
                    ValueError,
                    "downloaded final-freeze receipt must not be a symlink",
                ),
            ):
                MODULE.get_exact_object(
                    "bucket",
                    "receipt.json",
                    "receipt-version",
                    destination,
                    "us-east-1",
                )

    def test_main_persists_copy_version_and_history_when_post_copy_head_fails(self) -> None:
        run_id = "run-id"
        job_id = "job-id"
        command = ["worker", "--run-id", run_id]
        job = {
            "jobArn": f"arn:aws:batch:us-east-1:172630973301:job/{job_id}",
            "jobId": job_id,
            "jobName": "wgs",
            "jobDefinition": "arn:aws:batch:us-east-1:172630973301:job-definition/wgs:1",
            "status": "SUCCEEDED",
            "retryStrategy": {"attempts": 1, "evaluateOnExit": []},
            "timeout": {"attemptDurationSeconds": 129600},
            "container": {
                "command": command,
                "taskArn": "arn:aws:ecs:us-east-1:172630973301:task/cluster/task-id",
                "logStreamName": "wgs/default/stream",
            },
        }
        normalized_attempt = {
            "started_at_epoch_ms": 1,
            "stopped_at_epoch_ms": 2,
            "status_reason": "",
            "container_instance_arn": "arn:aws:ecs:us-east-1:172630973301:container-instance/cluster/instance-id",
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
        source_row = {
            "relative_key": "variants/final.vcf.gz",
            "key": (
                f"runs/diana-hrd/{run_id}/private-results/final/artifacts/"
                "variants/final.vcf.gz"
            ),
            "bytes": 10,
            "etag": '"etag"',
            "version_id": "source-version",
            "checksums": {"ChecksumSHA256": "source-checksum"},
            "checksum_type": "FULL_OBJECT",
        }
        source_head = {
            "ContentLength": 10,
            "ETag": '"etag"',
            "VersionId": "source-version",
            "ChecksumType": "FULL_OBJECT",
            "ChecksumSHA256": "source-checksum",
        }
        observed = [
            {
                "history_kind": "version",
                "Key": (
                    f"runs/subject01/{run_id}/deterministic/final/"
                    "variants/final.vcf.gz"
                ),
                "VersionId": "destination-version",
                "IsLatest": True,
            }
        ]
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            execution = root / "execution.json"
            output = root / "freeze.json"
            anchor = root / "anchor.json"
            execution.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "region": "us-east-1",
                        "run_id": run_id,
                        "batch": {
                            "job_id": job_id,
                            "job_name": "wgs",
                            "job_definition_arn": job["jobDefinition"],
                            "status": "SUCCEEDED",
                            "command": command,
                            "log_stream": job["container"]["logStreamName"],
                            "attempt_count": 1,
                            "attempts": [normalized_attempt],
                            "retry_strategy": job["retryStrategy"],
                            "timeout": job["timeout"],
                        },
                        "container": {"task_arn": job["container"]["taskArn"]},
                        "worker": {
                            "kms_key_id": "arn:aws:kms:us-east-1:172630973301:key/test",
                            "checks": {"task_identity": True},
                        },
                    }
                ),
                encoding="utf-8",
            )
            argv = [
                "freeze_final_artifacts.py",
                "--job-id",
                job_id,
                "--run-id",
                run_id,
                "--execution-receipt",
                str(execution),
                "--source-prefix",
                f"s3://diana-omics-work-172630973301-us-east-1/runs/diana-hrd/{run_id}/private-results/final/artifacts/",
                "--destination-prefix",
                f"s3://diana-omics-private-results-172630973301-us-east-1/runs/subject01/{run_id}/deterministic/final/",
                "--kms-key-arn",
                "arn:aws:kms:us-east-1:172630973301:key/test",
                "--output",
                str(output),
                "--anchor-output",
                str(anchor),
                "--apply",
            ]
            with patch.object(sys, "argv", argv), patch.object(
                MODULE,
                "aws_json",
                return_value={"jobs": [job]},
            ), patch.object(MODULE, "require_bucket_versioning"), patch.object(
                MODULE, "snapshot_inventory", return_value=[source_row]
            ), patch.object(
                MODULE, "version_history", side_effect=[[], observed]
            ), patch.object(
                MODULE,
                "copy_object",
                return_value={"VersionId": "destination-version"},
            ), patch.object(
                MODULE,
                "head",
                side_effect=[source_head, source_head, RuntimeError("head failed")],
            ):
                with self.assertRaisesRegex(RuntimeError, "head failed"):
                    MODULE.main()
            failed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(
                failed["objects"][0]["copy_result"]["version_id"],
                "destination-version",
            )
            self.assertEqual(
                failed["created_or_observed_versions"][0]["VersionId"],
                "destination-version",
            )
            self.assertFalse(anchor.exists())

    def test_snapshot_inventory_captures_exact_version_and_sorts(self) -> None:
        listed = [
            {"Key": "prefix/z", "Size": 2, "ETag": '"z"'},
            {"Key": "prefix/a", "Size": 1, "ETag": '"a"'},
            {"Key": "prefix/unversioned", "Size": 3, "ETag": '"u"'},
        ]
        heads = {
            "prefix/z": {
                "ContentLength": 2,
                "ETag": '"z"',
                "VersionId": "vz",
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": "sz",
            },
            "prefix/a": {
                "ContentLength": 1,
                "ETag": '"a"',
                "VersionId": "va",
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": "sa",
            },
            "prefix/unversioned": {
                "ContentLength": 3,
                "ETag": '"u"',
                "VersionId": "null",
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": "su",
            },
        }
        with patch.object(MODULE, "list_objects", return_value=listed), patch.object(
            MODULE, "head", side_effect=lambda _bucket, key, _region: heads[key]
        ):
            snapshot = MODULE.snapshot_inventory("bucket", "prefix/", "us-east-1")
        self.assertEqual(
            [row["relative_key"] for row in snapshot],
            ["a", "unversioned", "z"],
        )
        self.assertEqual(snapshot[0]["version_id"], "va")
        self.assertEqual(snapshot[1]["version_id"], "null")

    def test_inventory_identity_detects_added_or_replaced_object(self) -> None:
        original = [
            {
                "relative_key": "a",
                "key": "prefix/a",
                "bytes": 1,
                "etag": '"a"',
                "version_id": "v1",
            }
        ]
        replaced = [{**original[0], "version_id": "v2"}]
        added = [*original, {**original[0], "relative_key": "b", "key": "prefix/b"}]
        self.assertNotEqual(MODULE.inventory_identity(original), MODULE.inventory_identity(replaced))
        self.assertNotEqual(MODULE.inventory_identity(original), MODULE.inventory_identity(added))

    def test_validate_execution_binding_requires_exact_job_and_source_tree(self) -> None:
        job = {
            "jobArn": "arn:aws:batch:us-east-1:172630973301:job/job-id",
            "jobId": "job-id",
            "jobName": "wgs-run",
            "jobDefinition": "arn:aws:batch:us-east-1:172630973301:job-definition/wgs:1",
            "status": "SUCCEEDED",
            "retryStrategy": {"attempts": 1, "evaluateOnExit": []},
            "timeout": {"attemptDurationSeconds": 129600},
            "container": {
                "command": ["worker", "--run-id", "run-id"],
                "taskArn": "arn:aws:ecs:us-east-1:172630973301:task/cluster/task-id",
                "logStreamName": "wgs/default/stream",
            },
        }
        normalized_attempt = {
            "started_at_epoch_ms": 1,
            "stopped_at_epoch_ms": 2,
            "status_reason": "",
            "container_instance_arn": "arn:aws:ecs:us-east-1:172630973301:container-instance/cluster/instance-id",
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
            "region": "us-east-1",
            "run_id": "run-id",
            "batch": {
                "job_id": "job-id",
                "job_name": "wgs-run",
                "job_definition_arn": job["jobDefinition"],
                "status": "SUCCEEDED",
                "command": job["container"]["command"],
                "log_stream": job["container"]["logStreamName"],
                "attempt_count": 1,
                "attempts": [normalized_attempt],
                "retry_strategy": job["retryStrategy"],
                "timeout": job["timeout"],
            },
            "container": {"task_arn": job["container"]["taskArn"]},
            "worker": {
                "kms_key_id": "arn:aws:kms:us-east-1:172630973301:key/test",
                "checks": {"task_identity": True, "sha256": True},
            },
        }
        kwargs = {
            "job": job,
            "job_id": "job-id",
            "run_id": "run-id",
            "source_bucket": "diana-omics-work-172630973301-us-east-1",
            "source_prefix": (
                "runs/diana-hrd/run-id/private-results/final/artifacts/"
            ),
            "region": "us-east-1",
        }
        self.assertEqual(
            MODULE.validate_execution_binding(receipt, **kwargs),
            (
                "172630973301",
                "arn:aws:kms:us-east-1:172630973301:key/test",
            ),
        )
        with self.assertRaisesRegex(ValueError, "guarded artifact tree"):
            MODULE.validate_execution_binding(
                receipt,
                **{
                    **kwargs,
                    "source_prefix": (
                        "runs/diana-hrd/other/private-results/final/artifacts/"
                    ),
                },
            )
        with self.assertRaisesRegex(ValueError, "exact successful Batch job"):
            MODULE.validate_execution_binding(
                {**receipt, "batch": {**receipt["batch"], "status": "RUNNING"}},
                **kwargs,
            )
        with self.assertRaisesRegex(ValueError, "exact successful Batch job"):
            MODULE.validate_execution_binding(
                {
                    **receipt,
                    "batch": {
                        **receipt["batch"],
                        "timeout": {"attemptDurationSeconds": 64800},
                    },
                },
                **kwargs,
            )


if __name__ == "__main__":
    unittest.main()
