from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_1
from test_phase3_fast_staged_inputs import materialized_staging_plan

from diana_omics.commands.phase3_wgs import render_phase3_fast_parabricks_mutect_plan as parabricks
from diana_omics.commands.phase3_wgs import verify_phase3_fast_staged_inputs as staged
from diana_omics.utils import write_json


def staged_inputs_manifest(root: Path) -> dict:
    return staged.build_phase3_fast_staged_inputs_manifest(
        materialized_staging_plan(root),
        staging_plan_sha256=SHA_1,
    )


class Phase3FastParabricksMutectPlanTests(unittest.TestCase):
    def test_plan_renders_prepon_mutectcaller_and_postpon_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks.build_phase3_fast_parabricks_mutect_plan(
                staged_inputs_manifest(Path(tmp)),
                staged_inputs_manifest_sha256=SHA_1,
                output_root="/scratch/diana/phase3_wgs_fast/parabricks",
                num_gpus=8,
            )

        self.assertEqual("phase3_wgs_fast_parabricks_mutect_plan", plan["manifest_type"])
        self.assertEqual("planned", plan["status"])
        self.assertEqual("no_call", plan["interpretation"]["authorized_hrd_state"])
        self.assertEqual(8, plan["runtime"]["num_gpus"])
        self.assertEqual("subject01_tumor", plan["inputs"]["tumor_bam"]["sample_id"])
        self.assertEqual("subject01_normal", plan["inputs"]["normal_bam"]["sample_id"])

        self.assertEqual(
            [
                "pbrun",
                "prepon",
                "--in-pon-file",
                plan["inputs"]["panel_of_normals_vcf"]["local_path"],
                "--tmp-dir",
                "/scratch/diana/phase3_wgs_fast/parabricks/tmp/prepon",
                "--logfile",
                "/scratch/diana/phase3_wgs_fast/parabricks/logs/prepon.log",
                "--num-gpus",
                "8",
            ],
            plan["commands"]["prepon"]["argv"],
        )

        mutect = plan["commands"]["mutectcaller"]["argv"]
        self.assertEqual("pbrun", mutect[0])
        self.assertEqual("mutectcaller", mutect[1])
        self.assertIn("--ref", mutect)
        self.assertIn("--tumor-name", mutect)
        self.assertIn("subject01_tumor", mutect)
        self.assertIn("--normal-name", mutect)
        self.assertIn("subject01_normal", mutect)
        self.assertIn("--pon", mutect)
        self.assertIn("--mutect-germline-resource", mutect)
        self.assertIn("--interval-file", mutect)
        self.assertIn("--mutect-f1r2-tar-gz", mutect)

        self.assertEqual(
            [
                "pbrun",
                "postpon",
                "--in-vcf",
                plan["outputs"]["raw_vcf"],
                "--in-pon-file",
                plan["inputs"]["panel_of_normals_vcf"]["local_path"],
                "--out-vcf",
                plan["outputs"]["pon_annotated_vcf"],
                "--tmp-dir",
                "/scratch/diana/phase3_wgs_fast/parabricks/tmp/postpon",
                "--logfile",
                "/scratch/diana/phase3_wgs_fast/parabricks/logs/postpon.log",
                "--num-gpus",
                "8",
            ],
            plan["commands"]["postpon"]["argv"],
        )

    def test_rejects_non_ready_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["status"] = "planned"

        with self.assertRaisesRegex(parabricks.ManifestError, "ready"):
            parabricks.build_phase3_fast_parabricks_mutect_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_missing_sample_names(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["tumor"]["bam"].pop("sample_id")

        with self.assertRaisesRegex(parabricks.ManifestError, "sample_id"):
            parabricks.build_phase3_fast_parabricks_mutect_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_matching_tumor_normal_sample_names(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["normal"]["bam"]["sample_id"] = "subject01_tumor"

        with self.assertRaisesRegex(parabricks.ManifestError, "must differ"):
            parabricks.build_phase3_fast_parabricks_mutect_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_unpaired_pon_index_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["caller_resources"]["panel_of_normals_index"]["local_path"] = (
            "/scratch/diana/phase3_wgs_fast/caller_resources/elsewhere/panel.tbi"
        )

        with self.assertRaisesRegex(parabricks.ManifestError, "panel_of_normals"):
            parabricks.build_phase3_fast_parabricks_mutect_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_unpaired_germline_index_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["caller_resources"]["germline_resource_index"]["local_path"] = (
            "/scratch/diana/phase3_wgs_fast/caller_resources/elsewhere/germline.tbi"
        )

        with self.assertRaisesRegex(parabricks.ManifestError, "germline_resource"):
            parabricks.build_phase3_fast_parabricks_mutect_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_relative_output_root(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))

        with self.assertRaisesRegex(parabricks.ManifestError, "output_root"):
            parabricks.build_phase3_fast_parabricks_mutect_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                output_root="scratch/diana/phase3_wgs_fast/parabricks",
            )

    def test_rejects_non_positive_gpu_count(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))

        with self.assertRaisesRegex(parabricks.ManifestError, "num_gpus"):
            parabricks.build_phase3_fast_parabricks_mutect_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                num_gpus=0,
            )

    def test_environment_command_writes_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "staged-inputs.json"
            output_path = root / "parabricks-plan.json"
            write_json(input_path, staged_inputs_manifest(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_PARABRICKS_OUTPUT_ROOT": "/scratch/diana/test/parabricks",
                    "PHASE3_WGS_FAST_PARABRICKS_NUM_GPUS": "4",
                },
                clear=False,
            ):
                plan, plan_path = parabricks.load_plan_from_environment()
                parabricks.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual("planned", plan["status"])
            self.assertEqual(4, plan["runtime"]["num_gpus"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_parabricks_mutect_plan"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
