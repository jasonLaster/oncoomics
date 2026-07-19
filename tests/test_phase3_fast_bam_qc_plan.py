from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest

from diana_omics.commands.phase3_wgs import render_phase3_fast_bam_qc_plan as bam_qc
from diana_omics.utils import write_json


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase3FastBamQcPlanTests(unittest.TestCase):
    def test_plan_renders_tumor_and_normal_samtools_qc_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = bam_qc.build_phase3_fast_bam_qc_plan(
                staged_inputs_manifest(Path(tmp)),
                staged_inputs_manifest_sha256=SHA_1,
                output_root="/scratch/diana/phase3_wgs_fast/bam_qc",
                threads=8,
            )

        self.assertEqual("phase3_wgs_fast_bam_qc_plan", plan["manifest_type"])
        self.assertEqual("planned", plan["status"])
        self.assertEqual("no_call", plan["interpretation"]["authorized_hrd_state"])
        self.assertEqual("qc_only_not_hrd_evidence", plan["interpretation"]["hrd_use"])
        self.assertEqual(8, plan["runtime"]["samtools_threads"])
        self.assertEqual({"tumor", "normal"}, set(plan["inputs"]))
        self.assertEqual("subject01_tumor", plan["inputs"]["tumor"]["bam"]["sample_id"])
        self.assertEqual("subject01_normal", plan["inputs"]["normal"]["bam"]["sample_id"])
        self.assertEqual(
            Path(plan["inputs"]["tumor"]["bam"]["local_path"]).parent,
            Path(plan["inputs"]["tumor"]["bai"]["local_path"]).parent,
        )

        tumor_bam = plan["inputs"]["tumor"]["bam"]["local_path"]
        tumor_commands = plan["commands"]["tumor"]
        self.assertEqual(
            ["samtools", "quickcheck", "-v", tumor_bam],
            tumor_commands["quickcheck"]["argv"],
        )
        self.assertEqual(
            ["samtools", "flagstat", "-@", "8", tumor_bam],
            tumor_commands["flagstat"]["argv"],
        )
        self.assertEqual(
            ["samtools", "idxstats", tumor_bam],
            tumor_commands["idxstats"]["argv"],
        )
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/bam_qc/tumor/flagstat.txt",
            plan["outputs"]["tumor"]["flagstat"],
        )

    def test_rejects_non_ready_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["status"] = "planned"

        with self.assertRaisesRegex(bam_qc.ManifestError, "ready"):
            bam_qc.build_phase3_fast_bam_qc_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_non_no_call_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["interpretation"]["authorized_hrd_state"] = "partial_evidence"

        with self.assertRaisesRegex(bam_qc.ManifestError, "no_call"):
            bam_qc.build_phase3_fast_bam_qc_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_unpaired_bam_index_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["tumor"]["bai"]["local_path"] = "/scratch/diana/elsewhere/tumor.bai"

        with self.assertRaisesRegex(bam_qc.ManifestError, "tumor.bam"):
            bam_qc.build_phase3_fast_bam_qc_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_matching_tumor_normal_sample_names(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["normal"]["bam"]["sample_id"] = "subject01_tumor"
        manifest["bam_pair"]["normal"]["bai"]["sample_id"] = "subject01_tumor"

        with self.assertRaisesRegex(bam_qc.ManifestError, "must differ"):
            bam_qc.build_phase3_fast_bam_qc_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_relative_output_root(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))

        with self.assertRaisesRegex(bam_qc.ManifestError, "output_root"):
            bam_qc.build_phase3_fast_bam_qc_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                output_root="scratch/diana/phase3_wgs_fast/bam_qc",
            )

    def test_rejects_non_exact_threads(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))

        with self.assertRaisesRegex(bam_qc.ManifestError, "threads"):
            bam_qc.build_phase3_fast_bam_qc_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                threads=True,
            )

    def test_environment_command_writes_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "staged-inputs.json"
            output_path = root / "bam-qc-plan.json"
            write_json(input_path, staged_inputs_manifest(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_BAM_QC_PLAN_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_BAM_QC_OUTPUT_ROOT": "/scratch/diana/test/bam_qc",
                    "PHASE3_WGS_FAST_BAM_QC_THREADS": "12",
                },
                clear=False,
            ):
                plan, plan_path = bam_qc.load_plan_from_environment()
                bam_qc.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual(12, plan["runtime"]["samtools_threads"])
            self.assertEqual(_sha256_json(input_path), plan["source"]["staged_inputs_manifest_sha256"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_bam_qc_plan"', output_path.read_text(encoding="utf-8"))

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_manifest = root / "staged-inputs.json"
            linked_manifest = root / "staged-inputs-link.json"
            write_json(real_manifest, staged_inputs_manifest(root))
            linked_manifest.symlink_to(real_manifest)

            with self.assertRaisesRegex(
                bam_qc.ManifestError,
                "staged-inputs-link\\.json SHA-256 input is missing or a symlink",
            ):
                bam_qc._sha256_path(linked_manifest)

            real_parent = root / "real-inputs"
            linked_parent = root / "linked-inputs"
            real_parent.mkdir()
            parent_manifest = real_parent / "staged-inputs.json"
            write_json(parent_manifest, staged_inputs_manifest(root))
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                bam_qc.ManifestError,
                "staged-inputs\\.json SHA-256 input parent may not be a symlink",
            ):
                bam_qc._sha256_path(linked_parent / "staged-inputs.json")


if __name__ == "__main__":
    unittest.main()
