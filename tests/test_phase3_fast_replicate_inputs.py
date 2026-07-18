from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_3
from test_phase3_fast_replication_plan import Phase3FastReplicationPlanTests

from diana_omics.commands.phase3_wgs import replicate_phase3_fast_inputs as replicate
from diana_omics.utils import write_json


def destination_id(row: Mapping[str, Any]) -> tuple[str, str]:
    destination = row["copy_strategy"]["destination"]
    return str(destination["bucket"]), str(destination["key"])


def matching_head(row: Mapping[str, Any], version_id: str) -> dict[str, Any]:
    return {
        "ContentLength": row["bytes"],
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": row["destination_kms_key_arn"],
        "VersionId": version_id,
        "Metadata": {
            "diana-artifact": row["artifact"],
            "diana-source-sha256": row["sha256"],
            "diana-source-version-id": row["source_version_id"],
        },
    }


class FakeS3CopyClient:
    def __init__(self) -> None:
        self.destination_heads: dict[tuple[str, str], dict[str, Any]] = {}
        self.copied: list[Mapping[str, Any]] = []
        self.created_multipart: list[Mapping[str, Any]] = []
        self.uploaded_parts: list[Mapping[str, Any]] = []
        self.completed_multipart: list[list[Mapping[str, Any]]] = []
        self.aborted: list[str] = []
        self.fail_part_number: int | None = None
        self.mismatch_after_complete = False

    def add_matching_destination(self, row: Mapping[str, Any], *, version_id: str = "existing-version") -> None:
        self.destination_heads[destination_id(row)] = matching_head(row, version_id)

    def head_destination(self, row: Mapping[str, Any], *, version_id: str = "") -> dict[str, Any] | None:
        head = self.destination_heads.get(destination_id(row))
        if head is None:
            return None
        if version_id and head["VersionId"] != version_id:
            return None
        return head

    def copy_object(self, row: Mapping[str, Any]) -> dict[str, Any]:
        self.copied.append(row)
        version_id = f"copy-version-{len(self.copied)}"
        self.destination_heads[destination_id(row)] = matching_head(row, version_id)
        return {"VersionId": version_id}

    def create_multipart_upload(self, row: Mapping[str, Any]) -> str:
        self.created_multipart.append(row)
        return f"upload-{len(self.created_multipart)}"

    def upload_part_copy(self, row: Mapping[str, Any], part: Mapping[str, Any], *, upload_id: str) -> dict[str, Any]:
        if part["part_number"] == self.fail_part_number:
            raise RuntimeError("synthetic upload-part-copy failure")
        self.uploaded_parts.append({"row": row, "part": part, "upload_id": upload_id})
        return {"CopyPartResult": {"ETag": f"etag-{part['part_number']}"}}

    def complete_multipart_upload(
        self,
        row: Mapping[str, Any],
        *,
        upload_id: str,
        parts: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        self.completed_multipart.append(parts)
        version_id = f"multipart-version-{len(self.completed_multipart)}"
        self.destination_heads[destination_id(row)] = matching_head(row, version_id)
        if self.mismatch_after_complete:
            self.destination_heads[destination_id(row)]["Metadata"]["diana-source-sha256"] = "wrong"
        return {"VersionId": version_id}

    def abort_multipart_upload(self, row: Mapping[str, Any], *, upload_id: str) -> None:
        self.aborted.append(upload_id)


def replication_plan() -> dict:
    return Phase3FastReplicationPlanTests().build_plan()


class Phase3FastReplicateInputsTests(unittest.TestCase):
    def build_receipt(self) -> dict:
        return replicate.build_phase3_fast_replication_receipt(
            replication_plan(),
            mode="dry_run",
            replication_plan_sha256=SHA_3,
        )

    def build_apply_receipt(self, plan: dict | None = None) -> dict:
        return replicate.build_phase3_fast_replication_receipt(
            plan or replication_plan(),
            mode="apply",
            replication_plan_sha256=SHA_3,
        )

    def test_dry_run_receipt_preserves_exact_copy_plan_without_s3_writes(self) -> None:
        receipt = self.build_receipt()

        self.assertEqual(receipt["manifest_type"], "phase3_wgs_fast_replication_receipt")
        self.assertEqual(receipt["status"], "dry_run")
        self.assertEqual(receipt["mode"], "dry_run")
        self.assertEqual(receipt["object_count"], 15)
        self.assertEqual(receipt["total_bytes"], 179)
        self.assertEqual(receipt["copy_strategy"]["multipart_part_size_bytes"], 512 * 1024 * 1024)
        self.assertEqual(receipt["interpretation"]["authorized_hrd_state"], "no_call")

        rows = {row["artifact"]: row for row in receipt["copy_results"]}
        self.assertEqual("dry_run", rows["tumor.bam"]["status"])
        self.assertEqual("copy_object", rows["tumor.bam"]["copy_strategy"]["method"])
        self.assertEqual(1, rows["tumor.bam"]["copy_strategy"]["part_count"])
        self.assertEqual("subject01_tumor", rows["tumor.bam"]["sample_id"])
        self.assertEqual("tumor-bam-version", rows["tumor.bam"]["source_version_id"])
        self.assertEqual("s3://private-cache/tumor.markdup.bam", rows["tumor.bam"]["source_uri"])
        self.assertTrue(rows["tumor.bam"]["checks"]["dry_run_no_s3_write"])
        self.assertTrue(rows["tumor.bam"]["checks"]["destination_uri_content_addressed"])
        self.assertTrue(rows["tumor.bam"]["checks"]["source_copy_version_bound"])
        self.assertIn("/inputs/tumor.bam/" + "c" * 64 + "/", rows["tumor.bam"]["destination_uri"])
        self.assertEqual(
            {
                "bucket": "private-cache",
                "copy_source": "private-cache/tumor.markdup.bam?versionId=tumor-bam-version",
                "key": "tumor.markdup.bam",
                "version_id": "tumor-bam-version",
            },
            rows["tumor.bam"]["copy_strategy"]["source"],
        )
        self.assertEqual(
            {
                "bucket": "diana-omics-private-cache-us-east-2",
                "key": "wgs-v2/inputs/tumor.bam/" + ("c" * 64) + "/tumor.markdup.bam",
            },
            rows["tumor.bam"]["copy_strategy"]["destination"],
        )

    def test_apply_mode_plans_before_touching_s3(self) -> None:
        receipt = self.build_apply_receipt()

        self.assertEqual("planned", receipt["status"])
        self.assertEqual("apply", receipt["mode"])
        self.assertEqual("planned", receipt["copy_results"][0]["status"])
        self.assertFalse(receipt["copy_results"][0]["checks"]["dry_run_no_s3_write"])

    def test_apply_copy_object_uses_create_only_version_bound_copy(self) -> None:
        client = FakeS3CopyClient()
        receipt = self.build_apply_receipt()

        applied = replicate.apply_phase3_fast_replication_receipt(receipt, client)

        self.assertEqual("applied", applied["status"])
        self.assertEqual(15, applied["copied_count"])
        self.assertEqual(0, applied["already_present_count"])
        self.assertEqual(15, len(client.copied))
        first = applied["copy_results"][0]
        self.assertEqual("copied", first["status"])
        self.assertEqual("copy-version-1", first["destination_version_id"])
        self.assertTrue(first["checks"]["copy_response_version_matches"])

    def test_apply_reuses_existing_matching_cache_object_without_copying(self) -> None:
        client = FakeS3CopyClient()
        receipt = self.build_apply_receipt()
        first = receipt["copy_results"][0]
        client.add_matching_destination(first)

        applied = replicate.apply_phase3_fast_replication_receipt(receipt, client)

        self.assertEqual("already_present", applied["copy_results"][0]["status"])
        self.assertEqual("existing-version", applied["copy_results"][0]["destination_version_id"])
        self.assertEqual(14, len(client.copied))
        self.assertNotEqual(first["artifact"], client.copied[0]["artifact"])

    def test_apply_rejects_existing_cache_object_with_wrong_metadata(self) -> None:
        client = FakeS3CopyClient()
        receipt = self.build_apply_receipt()
        first = receipt["copy_results"][0]
        client.add_matching_destination(first)
        client.destination_heads[destination_id(first)]["Metadata"]["diana-source-sha256"] = "wrong"

        with self.assertRaisesRegex(replicate.ManifestError, "already exists"):
            replicate.apply_phase3_fast_replication_receipt(receipt, client)

        self.assertEqual([], client.copied)

    def test_apply_upload_part_copy_uses_planned_ranges(self) -> None:
        plan = replication_plan()
        rows = plan["copy_plan"]
        old_bytes = rows[0]["bytes"]
        rows[0]["bytes"] = 6 * 1024 * 1024 * 1024 + 1
        plan["total_bytes"] = plan["total_bytes"] - old_bytes + rows[0]["bytes"]
        receipt = self.build_apply_receipt(plan)
        client = FakeS3CopyClient()

        applied = replicate.apply_phase3_fast_replication_receipt(receipt, client)

        self.assertEqual("applied", applied["status"])
        self.assertEqual(1, len(client.created_multipart))
        self.assertEqual(13, len(client.uploaded_parts))
        self.assertEqual(
            "bytes=0-536870911",
            client.uploaded_parts[0]["part"]["copy_source_range"],
        )
        self.assertEqual(
            "bytes=6442450944-6442450944",
            client.uploaded_parts[-1]["part"]["copy_source_range"],
        )
        self.assertEqual(
            [{"ETag": f"etag-{part}", "PartNumber": part} for part in range(1, 14)],
            client.completed_multipart[0],
        )

    def test_apply_aborts_multipart_upload_after_failed_part(self) -> None:
        plan = replication_plan()
        rows = plan["copy_plan"]
        old_bytes = rows[0]["bytes"]
        rows[0]["bytes"] = 6 * 1024 * 1024 * 1024 + 1
        plan["total_bytes"] = plan["total_bytes"] - old_bytes + rows[0]["bytes"]
        client = FakeS3CopyClient()
        client.fail_part_number = 2

        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            replicate.apply_phase3_fast_replication_receipt(self.build_apply_receipt(plan), client)

        self.assertEqual(["upload-1"], client.aborted)

    def test_apply_does_not_abort_after_completed_multipart_upload(self) -> None:
        plan = replication_plan()
        rows = plan["copy_plan"]
        old_bytes = rows[0]["bytes"]
        rows[0]["bytes"] = 6 * 1024 * 1024 * 1024 + 1
        plan["total_bytes"] = plan["total_bytes"] - old_bytes + rows[0]["bytes"]
        client = FakeS3CopyClient()
        client.mismatch_after_complete = True

        with self.assertRaisesRegex(replicate.ManifestError, "did not match"):
            replicate.apply_phase3_fast_replication_receipt(self.build_apply_receipt(plan), client)

        self.assertEqual([], client.aborted)

    def test_aws_cli_copy_object_is_version_bound_and_create_only(self) -> None:
        row = self.build_apply_receipt()["copy_results"][0]

        with patch.object(replicate.subprocess, "check_output", return_value='{"VersionId": "copied-version"}') as check:
            response = replicate.AwsCliS3CopyClient(region="us-east-2").copy_object(row)

        self.assertEqual({"VersionId": "copied-version"}, response)
        command = check.call_args.args[0]
        self.assertIn("private-cache/tumor.markdup.bam?versionId=tumor-bam-version", command)
        self.assertIn("--if-none-match", command)
        self.assertIn("*", command)
        self.assertIn("--metadata-directive", command)
        self.assertIn("REPLACE", command)

    def test_aws_cli_complete_multipart_upload_is_create_only(self) -> None:
        row = self.build_apply_receipt()["copy_results"][0]
        parts = [{"ETag": '"etag-1"', "PartNumber": 1}]

        with patch.object(replicate.subprocess, "check_output", return_value='{"VersionId": "completed-version"}') as check:
            response = replicate.AwsCliS3CopyClient(region="us-east-2").complete_multipart_upload(
                row,
                upload_id="upload-id",
                parts=parts,
            )

        self.assertEqual({"VersionId": "completed-version"}, response)
        command = check.call_args.args[0]
        self.assertIn("--if-none-match", command)
        self.assertIn("*", command)
        self.assertIn("--multipart-upload", command)

    def test_large_objects_plan_deterministic_upload_part_copy(self) -> None:
        plan = replication_plan()
        rows = plan["copy_plan"]
        old_bytes = rows[0]["bytes"]
        rows[0]["bytes"] = 6 * 1024 * 1024 * 1024 + 1
        plan["total_bytes"] = plan["total_bytes"] - old_bytes + rows[0]["bytes"]

        receipt = replicate.build_phase3_fast_replication_receipt(
            plan,
            mode="dry_run",
            replication_plan_sha256=SHA_3,
        )

        first = receipt["copy_results"][0]
        self.assertEqual("upload_part_copy", first["copy_strategy"]["method"])
        self.assertEqual(512 * 1024 * 1024, first["copy_strategy"]["part_size_bytes"])
        self.assertEqual(13, first["copy_strategy"]["part_count"])
        self.assertEqual(1, first["copy_strategy"]["last_part_size_bytes"])
        self.assertEqual(
            {
                "copy_source_range": "bytes=0-536870911",
                "first_byte": 0,
                "last_byte": 536870911,
                "part_number": 1,
            },
            first["copy_strategy"]["parts"][0],
        )
        self.assertEqual(
            {
                "copy_source_range": "bytes=6442450944-6442450944",
                "first_byte": 6442450944,
                "last_byte": 6442450944,
                "part_number": 13,
            },
            first["copy_strategy"]["parts"][-1],
        )

    def test_copy_source_encodes_s3_keys_and_version_ids_for_upload_part_copy(self) -> None:
        plan = replication_plan()
        rows = plan["copy_plan"]
        old_bytes = rows[0]["bytes"]
        rows[0]["bytes"] = 6 * 1024 * 1024 * 1024 + 1
        rows[0]["source_uri"] = "s3://private-cache/path with spaces/a+b.bam"
        rows[0]["source_version_id"] = "v/1+a=="
        plan["total_bytes"] = plan["total_bytes"] - old_bytes + rows[0]["bytes"]

        receipt = replicate.build_phase3_fast_replication_receipt(
            plan,
            mode="dry_run",
            replication_plan_sha256=SHA_3,
        )

        first = receipt["copy_results"][0]
        self.assertEqual(
            "private-cache/path%20with%20spaces/a%2Bb.bam?versionId=v%2F1%2Ba%3D%3D",
            first["copy_strategy"]["source"]["copy_source"],
        )

    def test_rejects_multipart_plans_that_would_exceed_s3_part_count(self) -> None:
        plan = replication_plan()
        rows = plan["copy_plan"]
        old_bytes = rows[0]["bytes"]
        rows[0]["bytes"] = replicate.DEFAULT_MULTIPART_PART_SIZE_BYTES * (replicate.S3_MAX_MULTIPART_PARTS + 1)
        plan["total_bytes"] = plan["total_bytes"] - old_bytes + rows[0]["bytes"]

        with self.assertRaisesRegex(replicate.ManifestError, "10001 parts"):
            replicate.build_phase3_fast_replication_receipt(
                plan,
                mode="dry_run",
                replication_plan_sha256=SHA_3,
            )

    def test_rejects_multipart_part_sizes_outside_s3_limits(self) -> None:
        for bad_part_size, message in (
            (replicate.S3_MIN_MULTIPART_PART_SIZE_BYTES - 1, "at least"),
            (replicate.S3_MAX_MULTIPART_PART_SIZE_BYTES + 1, "at most"),
        ):
            with self.subTest(bad_part_size=bad_part_size):
                with self.assertRaisesRegex(replicate.ManifestError, message):
                    replicate.build_phase3_fast_replication_receipt(
                        replication_plan(),
                        mode="dry_run",
                        part_size_bytes=bad_part_size,
                        replication_plan_sha256=SHA_3,
                    )

    def test_rejects_destination_without_source_sha_in_path(self) -> None:
        plan = replication_plan()
        plan["copy_plan"][0]["destination_uri"] = "s3://diana-omics-private-cache-us-east-2/wgs-v2/inputs/tumor.bam/latest.bam"

        with self.assertRaisesRegex(replicate.ManifestError, "content-addressed"):
            replicate.build_phase3_fast_replication_receipt(
                plan,
                mode="dry_run",
                replication_plan_sha256=SHA_3,
            )

    def test_rejects_mismatched_destination_kms_key(self) -> None:
        plan = replication_plan()
        plan["copy_plan"][0]["destination_kms_key_arn"] = (
            "arn:aws:kms:us-east-2:172630973301:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )

        with self.assertRaisesRegex(replicate.ManifestError, "KMS"):
            replicate.build_phase3_fast_replication_receipt(
                plan,
                mode="dry_run",
                replication_plan_sha256=SHA_3,
            )

    def test_rejects_total_bytes_drift(self) -> None:
        plan = replication_plan()
        plan["total_bytes"] = 1

        with self.assertRaisesRegex(replicate.ManifestError, "total_bytes"):
            replicate.build_phase3_fast_replication_receipt(
                plan,
                mode="dry_run",
                replication_plan_sha256=SHA_3,
            )

    def test_environment_command_writes_replication_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "replication-plan.json"
            output_path = root / "replication-receipt.json"
            write_json(input_path, replication_plan())

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_REPLICATION_PLAN": str(input_path),
                    "PHASE3_WGS_FAST_REPLICATION_RECEIPT_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_REPLICATION_MODE": "dry_run",
                    "PHASE3_WGS_FAST_REPLICATION_PART_SIZE_BYTES": str(1024 * 1024 * 1024),
                },
                clear=False,
            ):
                receipt, receipt_path = replicate.load_receipt_from_environment()
                replicate.write_receipt(receipt_path, receipt)

            self.assertEqual(output_path, receipt_path)
            self.assertEqual("dry_run", receipt["status"])
            self.assertEqual(1024 * 1024 * 1024, receipt["copy_strategy"]["multipart_part_size_bytes"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_replication_receipt"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
