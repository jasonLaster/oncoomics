from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_3
from test_phase3_fast_replication_plan import Phase3FastReplicationPlanTests

from diana_omics.commands.phase3_wgs import replicate_phase3_fast_inputs as replicate
from diana_omics.utils import write_json


def replication_plan() -> dict:
    return Phase3FastReplicationPlanTests().build_plan()


class Phase3FastReplicateInputsTests(unittest.TestCase):
    def build_receipt(self) -> dict:
        return replicate.build_phase3_fast_replication_receipt(
            replication_plan(),
            mode="dry_run",
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

    def test_apply_mode_fails_closed_until_multipart_copy_is_implemented(self) -> None:
        with self.assertRaisesRegex(replicate.ManifestError, "dry_run"):
            replicate.build_phase3_fast_replication_receipt(
                replication_plan(),
                mode="apply",
                replication_plan_sha256=SHA_3,
            )

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
