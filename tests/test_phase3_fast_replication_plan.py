from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import render_phase3_fast_input_manifest as render_input
from diana_omics.commands.phase3_wgs import render_phase3_fast_replication_plan as render_plan
from diana_omics.utils import write_json
from tests.test_phase3_fast_input_manifest import SHA_3, metadata, receipts


def input_manifest() -> dict:
    private_freeze, private_sha, reference_freeze, reference_sha, validation, contigs, resources = receipts()
    return render_input.build_phase3_wgs_fast_input_manifest(
        private_freeze_receipt=private_freeze,
        private_sha256_receipt=private_sha,
        reference_freeze_receipt=reference_freeze,
        reference_sha256_receipt=reference_sha,
        bam_validation_receipt=validation,
        contig_compatibility_receipt=contigs,
        caller_resource_receipt=resources,
        metadata=metadata(),
    )


class Phase3FastReplicationPlanTests(unittest.TestCase):
    def build_plan(self) -> dict:
        return render_plan.build_phase3_fast_replication_plan(
            input_manifest(),
            cache_prefix="s3://diana-omics-private-cache-us-east-2/wgs-v2",
            cache_kms_key_arn="arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc",
            cache_region="us-east-2",
            input_manifest_sha256=SHA_3,
        )

    def test_replication_plan_maps_every_gate0_object_to_a_content_addressed_cache_key(self) -> None:
        plan = self.build_plan()

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["manifest_type"], "phase3_wgs_fast_replication_plan")
        self.assertEqual(plan["workflow"]["name"], "phase3_wgs_fast")
        self.assertEqual(plan["object_count"], 15)
        self.assertEqual(plan["cache"]["region"], "us-east-2")
        self.assertEqual(
            plan["cache"]["kms_key_arn"],
            "arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc",
        )
        self.assertEqual(plan["interpretation"]["authorized_hrd_state"], "no_call")

        rows = {row["artifact"]: row for row in plan["copy_plan"]}
        self.assertIn("/inputs/tumor.bam/", rows["tumor.bam"]["destination_uri"])
        self.assertEqual("subject01_tumor", rows["tumor.bam"]["sample_id"])
        self.assertEqual("tumor", rows["tumor.bam"]["role"])
        self.assertIn("/references/reference.fa/", rows["reference.fa"]["destination_uri"])
        self.assertIn("/resources/panel_of_normals_vcf/", rows["panel_of_normals_vcf"]["destination_uri"])
        self.assertEqual("s3://private-cache/tumor.markdup.bam", rows["tumor.bam"]["source_uri"])
        self.assertEqual("tumor-bam-version", rows["tumor.bam"]["source_version_id"])
        self.assertEqual(
            "arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc",
            rows["tumor.bam"]["destination_kms_key_arn"],
        )

    def test_input_manifest_must_be_ready(self) -> None:
        manifest = input_manifest()
        manifest["status"] = "partial"

        with self.assertRaisesRegex(render_plan.ManifestError, "status"):
            render_plan.build_phase3_fast_replication_plan(
                manifest,
                cache_prefix="s3://diana-omics-private-cache-us-east-2/wgs-v2",
                cache_kms_key_arn="arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc",
                cache_region="us-east-2",
                input_manifest_sha256=SHA_3,
            )

    def test_input_manifest_must_preserve_no_call_boundary(self) -> None:
        manifest = input_manifest()
        manifest["interpretation"]["authorized_hrd_state"] = "called"

        with self.assertRaisesRegex(render_plan.ManifestError, "no_call"):
            render_plan.build_phase3_fast_replication_plan(
                manifest,
                cache_prefix="s3://diana-omics-private-cache-us-east-2/wgs-v2",
                cache_kms_key_arn="arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc",
                cache_region="us-east-2",
                input_manifest_sha256=SHA_3,
            )

    def test_copy_plan_bytes_must_be_exact_positive_integers(self) -> None:
        manifest = input_manifest()
        manifest["bam_pair"]["tumor"]["bam"]["bytes"] = True

        with self.assertRaisesRegex(render_plan.ManifestError, "positive integer"):
            render_plan.build_phase3_fast_replication_plan(
                manifest,
                cache_prefix="s3://diana-omics-private-cache-us-east-2/wgs-v2",
                cache_kms_key_arn="arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc",
                cache_region="us-east-2",
                input_manifest_sha256=SHA_3,
            )

    def test_cache_kms_key_must_match_cache_region(self) -> None:
        with self.assertRaisesRegex(render_plan.ManifestError, "KMS"):
            render_plan.build_phase3_fast_replication_plan(
                input_manifest(),
                cache_prefix="s3://diana-omics-private-cache-us-east-2/wgs-v2",
                cache_kms_key_arn="arn:aws:kms:us-east-1:172630973301:key/12345678-abcd-1234-abcd-123456789abc",
                cache_region="us-east-2",
                input_manifest_sha256=SHA_3,
            )

    def test_environment_command_writes_replication_plan(self) -> None:
        manifest = input_manifest()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input-manifest.json"
            output_path = root / "replication-plan.json"
            write_json(input_path, manifest)

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_INPUT_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_REPLICATION_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_CACHE_PREFIX": "s3://diana-omics-private-cache-us-east-2/wgs-v2",
                    "PHASE3_WGS_FAST_CACHE_KMS_KEY_ARN": (
                        "arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc"
                    ),
                    "PHASE3_WGS_FAST_CACHE_REGION": "us-east-2",
                },
                clear=False,
            ):
                plan, plan_path = render_plan.load_plan_from_environment()
                render_plan.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual("planned", plan["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_replication_plan"', output_path.read_text(encoding="utf-8"))

    def test_environment_command_rejects_redirected_input_manifest(self) -> None:
        for bad_kind in ("missing", "directory", "symlink"):
            with self.subTest(bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_manifest = root / "real-input-manifest.json"
                bad_manifest = root / f"input-manifest-{bad_kind}.json"
                write_json(real_manifest, input_manifest())
                if bad_kind == "directory":
                    bad_manifest.mkdir()
                elif bad_kind == "symlink":
                    bad_manifest.symlink_to(real_manifest)

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_INPUT_MANIFEST": str(bad_manifest),
                        "PHASE3_WGS_FAST_REPLICATION_OUTPUT": str(root / "replication-plan.json"),
                        "PHASE3_WGS_FAST_CACHE_PREFIX": "s3://diana-omics-private-cache-us-east-2/wgs-v2",
                        "PHASE3_WGS_FAST_CACHE_KMS_KEY_ARN": (
                            "arn:aws:kms:us-east-2:172630973301:key/12345678-abcd-1234-abcd-123456789abc"
                        ),
                        "PHASE3_WGS_FAST_CACHE_REGION": "us-east-2",
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(render_plan.ManifestError, "input_manifest"):
                        render_plan.load_plan_from_environment()


if __name__ == "__main__":
    unittest.main()
