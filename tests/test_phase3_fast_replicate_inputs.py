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
        self.assertEqual(receipt["interpretation"]["authorized_hrd_state"], "no_call")

        rows = {row["artifact"]: row for row in receipt["copy_results"]}
        self.assertEqual("dry_run", rows["tumor.bam"]["status"])
        self.assertEqual("tumor-bam-version", rows["tumor.bam"]["source_version_id"])
        self.assertEqual("s3://private-cache/tumor.markdup.bam", rows["tumor.bam"]["source_uri"])
        self.assertTrue(rows["tumor.bam"]["checks"]["dry_run_no_s3_write"])
        self.assertTrue(rows["tumor.bam"]["checks"]["destination_uri_content_addressed"])
        self.assertIn("/inputs/tumor.bam/" + "c" * 64 + "/", rows["tumor.bam"]["destination_uri"])

    def test_apply_mode_fails_closed_until_multipart_copy_is_implemented(self) -> None:
        with self.assertRaisesRegex(replicate.ManifestError, "dry_run"):
            replicate.build_phase3_fast_replication_receipt(
                replication_plan(),
                mode="apply",
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
                },
                clear=False,
            ):
                receipt, receipt_path = replicate.load_receipt_from_environment()
                replicate.write_receipt(receipt_path, receipt)

            self.assertEqual(output_path, receipt_path)
            self.assertEqual("dry_run", receipt["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_replication_receipt"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
