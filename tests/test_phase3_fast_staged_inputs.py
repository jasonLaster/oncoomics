from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_1
from test_phase3_fast_staging_plan import ready_cache_manifest

from diana_omics.commands.phase3_wgs import render_phase3_fast_staging_plan as staging
from diana_omics.commands.phase3_wgs import verify_phase3_fast_staged_inputs as staged
from diana_omics.utils import write_json


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def materialized_staging_plan(root: Path) -> dict:
    plan = staging.build_phase3_fast_staging_plan(
        ready_cache_manifest(),
        cache_manifest_sha256=SHA_1,
        staging_root=root / "scratch",
    )
    total_bytes = 0
    for row in plan["staged_objects"]:
        path = Path(row["local_path"])
        data = f"materialized {row['artifact']}\n".encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        row["bytes"] = len(data)
        row["sha256"] = _sha256(data)
        total_bytes += len(data)
    plan["total_bytes"] = total_bytes
    return plan


class Phase3FastStagedInputsTests(unittest.TestCase):
    def test_staged_manifest_groups_sha_verified_local_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = materialized_staging_plan(Path(tmp))

            manifest = staged.build_phase3_fast_staged_inputs_manifest(
                plan,
                staging_plan_sha256=SHA_1,
            )

        self.assertEqual("phase3_wgs_fast_staged_inputs_manifest", manifest["manifest_type"])
        self.assertEqual("ready", manifest["status"])
        self.assertEqual("phase3_wgs_fast", manifest["workflow"]["name"])
        self.assertEqual("no_call", manifest["interpretation"]["authorized_hrd_state"])
        self.assertEqual(15, manifest["object_count"])

        tumor = manifest["bam_pair"]["tumor"]["bam"]
        self.assertEqual("tumor.bam", tumor["artifact"])
        self.assertTrue(tumor["local_path"].endswith("/scratch/inputs/tumor/tumor.markdup.bam"))
        self.assertTrue(tumor["checks"]["local_sha256_matches"])
        self.assertEqual("copy-version-1", tumor["source"]["version_id"])

        panel = manifest["caller_resources"]["panel_of_normals_vcf"]
        self.assertTrue(panel["local_path"].endswith("/scratch/caller_resources/panel_of_normals_vcf/panel_of_normals_vcf"))

    def test_rejects_missing_local_file(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = materialized_staging_plan(Path(tmp))
            Path(plan["staged_objects"][0]["local_path"]).unlink()

            with self.assertRaisesRegex(staged.ManifestError, "does not exist"):
                staged.build_phase3_fast_staged_inputs_manifest(
                    plan,
                    staging_plan_sha256=SHA_1,
                )

    def test_rejects_size_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = materialized_staging_plan(Path(tmp))
            plan["staged_objects"][0]["bytes"] += 1
            plan["total_bytes"] += 1

            with self.assertRaisesRegex(staged.ManifestError, "local size"):
                staged.build_phase3_fast_staged_inputs_manifest(
                    plan,
                    staging_plan_sha256=SHA_1,
                )

    def test_rejects_sha_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = materialized_staging_plan(Path(tmp))
            plan["staged_objects"][0]["sha256"] = "0" * 64

            with self.assertRaisesRegex(staged.ManifestError, "local sha256"):
                staged.build_phase3_fast_staged_inputs_manifest(
                    plan,
                    staging_plan_sha256=SHA_1,
                )

    def test_rejects_duplicate_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = materialized_staging_plan(Path(tmp))
            plan["staged_objects"][1]["artifact"] = plan["staged_objects"][0]["artifact"]

            with self.assertRaisesRegex(staged.ManifestError, "duplicate artifact"):
                staged.build_phase3_fast_staged_inputs_manifest(
                    plan,
                    staging_plan_sha256=SHA_1,
                )

    def test_environment_command_writes_staged_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "staging-plan.json"
            output_path = root / "staged-inputs.json"
            write_json(input_path, materialized_staging_plan(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_STAGING_PLAN": str(input_path),
                    "PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT": str(output_path),
                },
                clear=False,
            ):
                manifest, manifest_path = staged.load_manifest_from_environment()
                staged.write_manifest(manifest_path, manifest)

            self.assertEqual(output_path, manifest_path)
            self.assertEqual("ready", manifest["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_staged_inputs_manifest"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
