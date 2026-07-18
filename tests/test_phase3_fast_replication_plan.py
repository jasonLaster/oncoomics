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
            input_manifest_sha256=SHA_3,
        )

    def test_replication_plan_maps_every_gate0_object_to_a_content_addressed_cache_key(self) -> None:
        plan = self.build_plan()

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["manifest_type"], "phase3_wgs_fast_replication_plan")
        self.assertEqual(plan["workflow"]["name"], "phase3_wgs_fast")
        self.assertEqual(plan["object_count"], 15)
        self.assertEqual(plan["interpretation"]["authorized_hrd_state"], "no_call")

        rows = {row["artifact"]: row for row in plan["copy_plan"]}
        self.assertIn("/inputs/tumor.bam/", rows["tumor.bam"]["destination_uri"])
        self.assertIn("/references/reference.fa/", rows["reference.fa"]["destination_uri"])
        self.assertIn("/resources/panel_of_normals_vcf/", rows["panel_of_normals_vcf"]["destination_uri"])
        self.assertEqual("s3://private-cache/tumor.markdup.bam", rows["tumor.bam"]["source_uri"])
        self.assertEqual("tumor-bam-version", rows["tumor.bam"]["source_version_id"])

    def test_input_manifest_must_be_ready(self) -> None:
        manifest = input_manifest()
        manifest["status"] = "partial"

        with self.assertRaisesRegex(render_plan.ManifestError, "status"):
            render_plan.build_phase3_fast_replication_plan(
                manifest,
                cache_prefix="s3://diana-omics-private-cache-us-east-2/wgs-v2",
                input_manifest_sha256=SHA_3,
            )

    def test_input_manifest_must_preserve_no_call_boundary(self) -> None:
        manifest = input_manifest()
        manifest["interpretation"]["authorized_hrd_state"] = "called"

        with self.assertRaisesRegex(render_plan.ManifestError, "no_call"):
            render_plan.build_phase3_fast_replication_plan(
                manifest,
                cache_prefix="s3://diana-omics-private-cache-us-east-2/wgs-v2",
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
                },
                clear=False,
            ):
                plan, plan_path = render_plan.load_plan_from_environment()
                render_plan.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual("planned", plan["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_replication_plan"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
