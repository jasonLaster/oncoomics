from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_1
from test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest

from diana_omics.commands.phase3_wgs import render_phase3_fast_filter_mutect_plan as filter_mutect
from diana_omics.commands.phase3_wgs import render_phase3_fast_parabricks_mutect_plan as parabricks
from diana_omics.utils import write_json

SHA_2 = "b" * 64


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parabricks_plan(root: Path) -> tuple[dict, dict]:
    staged = staged_inputs_manifest(root)
    plan = parabricks.build_phase3_fast_parabricks_mutect_plan(
        staged,
        staged_inputs_manifest_sha256=SHA_1,
        output_root="/scratch/diana/phase3_wgs_fast/parabricks",
        num_gpus=8,
    )
    return staged, plan


class Phase3FastFilterMutectPlanTests(unittest.TestCase):
    def test_plan_renders_post_mutect_filtering_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            staged, mutect = parabricks_plan(Path(tmp))

            plan = filter_mutect.build_phase3_fast_filter_mutect_plan(
                staged,
                mutect,
                staged_inputs_manifest_sha256=SHA_1,
                mutect_plan_sha256=SHA_2,
                output_root="/scratch/diana/phase3_wgs_fast/filter_mutect",
            )

        self.assertEqual("phase3_wgs_fast_filter_mutect_plan", plan["manifest_type"])
        self.assertEqual("planned", plan["status"])
        self.assertEqual("no_call", plan["interpretation"]["authorized_hrd_state"])
        self.assertTrue(plan["inputs"]["gatk_jar"]["local_path"].endswith("/caller_resources/gatk/gatk_jar"))
        self.assertTrue(plan["inputs"]["common_sites_vcf"]["local_path"].endswith("/caller_resources/common_sites/common_sites_vcf"))
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/parabricks/variants/diana.wgs.mutect2.parabricks.pon.vcf.gz",
            plan["inputs"]["pon_annotated_vcf"]["local_path"],
        )
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/parabricks/variants/diana.wgs.mutect2.parabricks.raw.vcf.gz.stats",
            plan["inputs"]["raw_vcf_stats"]["local_path"],
        )
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/filter_mutect/variants/diana.wgs.mutect2.parabricks.filtered.vcf.gz",
            plan["outputs"]["filtered_vcf"],
        )

        tumor = plan["commands"]["get_tumor_pileups"]["argv"]
        self.assertEqual(["java", "-Xmx12g", "-jar"], tumor[:3])
        self.assertIn("GetPileupSummaries", tumor)
        self.assertIn(plan["inputs"]["tumor_bam"]["local_path"], tumor)
        self.assertIn(plan["inputs"]["common_sites_vcf"]["local_path"], tumor)

        contamination = plan["commands"]["calculate_contamination"]["argv"]
        self.assertIn("CalculateContamination", contamination)
        self.assertIn("--tumor-segmentation", contamination)
        self.assertIn(plan["outputs"]["tumor_segments"], contamination)

        filter_command = plan["commands"]["filter_mutect_calls"]["argv"]
        self.assertIn("FilterMutectCalls", filter_command)
        self.assertIn("--orientation-bias-artifact-priors", filter_command)
        self.assertIn(plan["outputs"]["read_orientation_model"], filter_command)
        self.assertIn(plan["inputs"]["pon_annotated_vcf"]["local_path"], filter_command)
        self.assertIn(plan["inputs"]["raw_vcf_stats"]["local_path"], filter_command)

        self.assertEqual(
            ["bcftools", "index", "-t", "-f", plan["outputs"]["filtered_vcf"]],
            plan["commands"]["index_filtered_vcf"]["argv"],
        )

    def test_rejects_mutect_plan_from_different_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            staged, mutect = parabricks_plan(Path(tmp))
            mutect["source"]["staged_inputs_manifest_sha256"] = SHA_2

        with self.assertRaisesRegex(filter_mutect.ManifestError, "derived"):
            filter_mutect.build_phase3_fast_filter_mutect_plan(
                staged,
                mutect,
                staged_inputs_manifest_sha256=SHA_1,
                mutect_plan_sha256=SHA_2,
            )

    def test_rejects_non_no_call_mutect_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            staged, mutect = parabricks_plan(Path(tmp))
            mutect["interpretation"]["authorized_hrd_state"] = "partial_evidence"

        with self.assertRaisesRegex(filter_mutect.ManifestError, "no_call"):
            filter_mutect.build_phase3_fast_filter_mutect_plan(
                staged,
                mutect,
                staged_inputs_manifest_sha256=SHA_1,
                mutect_plan_sha256=SHA_2,
            )

    def test_rejects_non_parabricks_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            staged, mutect = parabricks_plan(Path(tmp))
            staged["runtime"]["caller"] = "gatk_mutect2"

        with self.assertRaisesRegex(filter_mutect.ManifestError, "runtime caller"):
            filter_mutect.build_phase3_fast_filter_mutect_plan(
                staged,
                mutect,
                staged_inputs_manifest_sha256=SHA_1,
                mutect_plan_sha256=SHA_2,
            )

    def test_rejects_unpaired_common_sites_index(self) -> None:
        with TemporaryDirectory() as tmp:
            staged, mutect = parabricks_plan(Path(tmp))
            staged["caller_resources"]["common_sites_index"]["local_path"] = "/scratch/diana/elsewhere/common_sites.idx"

        with self.assertRaisesRegex(filter_mutect.ManifestError, "common_sites"):
            filter_mutect.build_phase3_fast_filter_mutect_plan(
                staged,
                mutect,
                staged_inputs_manifest_sha256=SHA_1,
                mutect_plan_sha256=SHA_2,
            )

    def test_rejects_relative_output_root(self) -> None:
        with TemporaryDirectory() as tmp:
            staged, mutect = parabricks_plan(Path(tmp))

        with self.assertRaisesRegex(filter_mutect.ManifestError, "output_root"):
            filter_mutect.build_phase3_fast_filter_mutect_plan(
                staged,
                mutect,
                staged_inputs_manifest_sha256=SHA_1,
                mutect_plan_sha256=SHA_2,
                output_root="scratch/diana/filter_mutect",
            )

    def test_environment_command_writes_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged_path = root / "staged-inputs.json"
            mutect_path = root / "mutect-plan.json"
            output_path = root / "filter-plan.json"
            staged, mutect = parabricks_plan(root)
            write_json(staged_path, staged)
            mutect["source"]["staged_inputs_manifest_sha256"] = _sha256_json(staged_path)
            write_json(mutect_path, mutect)

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST": str(staged_path),
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN": str(mutect_path),
                    "PHASE3_WGS_FAST_FILTER_MUTECT_PLAN_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_FILTER_MUTECT_OUTPUT_ROOT": "/scratch/diana/test/filter_mutect",
                },
                clear=False,
            ):
                plan, plan_path = filter_mutect.load_plan_from_environment()
                filter_mutect.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual("planned", plan["status"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_filter_mutect_plan"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
