from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_cache_manifest import applied_receipt
from test_phase3_fast_input_manifest import SHA_1, SHA_3

from diana_omics.commands.phase3_wgs import render_phase3_fast_cache_manifest as cache
from diana_omics.commands.phase3_wgs import render_phase3_fast_staging_plan as staging
from diana_omics.utils import write_json


def ready_cache_manifest() -> dict:
    return cache.build_phase3_fast_cache_manifest(
        applied_receipt(),
        replication_receipt_sha256=SHA_3,
    )


class Phase3FastStagingPlanTests(unittest.TestCase):
    def test_staging_plan_maps_verified_cache_to_versioned_local_downloads(self) -> None:
        plan = staging.build_phase3_fast_staging_plan(
            ready_cache_manifest(),
            cache_manifest_sha256=SHA_1,
            staging_root="/scratch/diana/phase3_wgs_fast",
        )

        self.assertEqual("phase3_wgs_fast_staging_plan", plan["manifest_type"])
        self.assertEqual("planned", plan["status"])
        self.assertEqual("phase3_wgs_fast", plan["workflow"]["name"])
        self.assertEqual("no_call", plan["interpretation"]["authorized_hrd_state"])
        self.assertEqual("us-east-2", plan["cache"]["region"])
        self.assertEqual(15, plan["object_count"])
        self.assertEqual(179, plan["total_bytes"])

        tumor = plan["bam_pair"]["tumor"]["bam"]
        self.assertEqual("/scratch/diana/phase3_wgs_fast/inputs/tumor/tumor.markdup.bam", tumor["local_path"])
        self.assertEqual("copy-version-1", tumor["source"]["version_id"])
        self.assertEqual("subject01_tumor", tumor["sample_id"])
        self.assertEqual(
            [
                "aws",
                "s3api",
                "get-object",
                "--region",
                "us-east-2",
                "--bucket",
                "diana-omics-private-cache-us-east-2",
                "--key",
                "wgs-v2/inputs/tumor.bam/" + ("c" * 64) + "/tumor.markdup.bam",
                "--version-id",
                "copy-version-1",
                "/scratch/diana/phase3_wgs_fast/inputs/tumor/tumor.markdup.bam",
            ],
            tumor["get_object_command"],
        )

        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/reference/reference.fa",
            plan["reference"]["fasta"]["local_path"],
        )
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/caller_resources/panel_of_normals_vcf/panel_of_normals_vcf",
            plan["caller_resources"]["panel_of_normals_vcf"]["local_path"],
        )

    def test_rejects_non_ready_cache_manifest(self) -> None:
        manifest = ready_cache_manifest()
        manifest["status"] = "stubbed"

        with self.assertRaisesRegex(staging.ManifestError, "ready"):
            staging.build_phase3_fast_staging_plan(
                manifest,
                cache_manifest_sha256=SHA_1,
            )

    def test_rejects_relative_staging_root(self) -> None:
        with self.assertRaisesRegex(staging.ManifestError, "absolute"):
            staging.build_phase3_fast_staging_plan(
                ready_cache_manifest(),
                cache_manifest_sha256=SHA_1,
                staging_root="scratch/diana",
            )

    def test_rejects_cache_entries_without_durable_destination_version(self) -> None:
        manifest = ready_cache_manifest()
        manifest["bam_pair"]["tumor"]["bam"]["version_id"] = "null"

        with self.assertRaisesRegex(staging.ManifestError, "durable"):
            staging.build_phase3_fast_staging_plan(
                manifest,
                cache_manifest_sha256=SHA_1,
            )

    def test_rejects_duplicate_local_paths(self) -> None:
        manifest = ready_cache_manifest()
        manifest["bam_pair"]["tumor"]["bai"]["uri"] = manifest["bam_pair"]["tumor"]["bam"]["uri"]

        with self.assertRaisesRegex(staging.ManifestError, "duplicate local paths"):
            staging.build_phase3_fast_staging_plan(
                manifest,
                cache_manifest_sha256=SHA_1,
            )

    def test_environment_command_writes_staging_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "cache-manifest.json"
            output_path = root / "staging-plan.json"
            write_json(input_path, ready_cache_manifest())

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_CACHE_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_STAGING_PLAN_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_STAGING_ROOT": "/scratch/diana/test",
                },
                clear=False,
            ):
                plan, plan_path = staging.load_plan_from_environment()
                staging.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual("planned", plan["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_staging_plan"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
