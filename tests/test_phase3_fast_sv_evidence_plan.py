from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest

from diana_omics.commands.phase3_wgs import render_phase3_fast_sv_evidence_plan as sv_evidence
from diana_omics.utils import write_json


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase3FastSvEvidencePlanTests(unittest.TestCase):
    def test_plan_renders_tumor_and_normal_mechanical_sv_evidence_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = sv_evidence.build_phase3_fast_sv_evidence_plan(
                staged_inputs_manifest(Path(tmp)),
                staged_inputs_manifest_sha256=SHA_1,
                output_root="/scratch/diana/phase3_wgs_fast/sv_evidence",
                threads=8,
            )

        self.assertEqual("phase3_wgs_fast_sv_evidence_plan", plan["manifest_type"])
        self.assertEqual("planned", plan["status"])
        self.assertEqual("no_call", plan["interpretation"]["authorized_hrd_state"])
        self.assertEqual("mechanical_sv_evidence_not_validated_sv_callset", plan["interpretation"]["hrd_use"])
        self.assertEqual("no_call_requires_validated_production_sv_caller_vcf", plan["interpretation"]["chord_use"])
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
            ["samtools", "idxstats", tumor_bam],
            tumor_commands["idxstats"]["argv"],
        )
        self.assertEqual(
            ["samtools", "view", "-@", "8", "-c", "-f", "2048", tumor_bam],
            tumor_commands["supplementary_alignments"]["argv"],
        )
        self.assertEqual(
            ["samtools", "view", "-@", "8", "-f", "1", "-F", "14", tumor_bam],
            tumor_commands["discordant_mapped_pairs"]["argv"],
        )
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/sv_evidence/tumor/discordant_mapped_pairs.sam",
            plan["outputs"]["tumor"]["discordant_mapped_pairs"],
        )

    def test_rejects_non_ready_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["status"] = "planned"

        with self.assertRaisesRegex(sv_evidence.ManifestError, "ready"):
            sv_evidence.build_phase3_fast_sv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_non_no_call_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["interpretation"]["authorized_hrd_state"] = "partial_evidence"

        with self.assertRaisesRegex(sv_evidence.ManifestError, "no_call"):
            sv_evidence.build_phase3_fast_sv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_unpaired_bam_index_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["tumor"]["bai"]["local_path"] = "/scratch/diana/elsewhere/tumor.bai"

        with self.assertRaisesRegex(sv_evidence.ManifestError, "tumor.bam"):
            sv_evidence.build_phase3_fast_sv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_matching_tumor_normal_sample_names(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["normal"]["bam"]["sample_id"] = "subject01_tumor"
        manifest["bam_pair"]["normal"]["bai"]["sample_id"] = "subject01_tumor"

        with self.assertRaisesRegex(sv_evidence.ManifestError, "must differ"):
            sv_evidence.build_phase3_fast_sv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_relative_output_root(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))

        with self.assertRaisesRegex(sv_evidence.ManifestError, "output_root"):
            sv_evidence.build_phase3_fast_sv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                output_root="scratch/diana/phase3_wgs_fast/sv_evidence",
            )

    def test_rejects_non_exact_threads(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))

        with self.assertRaisesRegex(sv_evidence.ManifestError, "threads"):
            sv_evidence.build_phase3_fast_sv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                threads=True,
            )

    def test_environment_command_writes_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "staged-inputs.json"
            output_path = root / "sv-evidence-plan.json"
            write_json(input_path, staged_inputs_manifest(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_PLAN_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_OUTPUT_ROOT": "/scratch/diana/test/sv_evidence",
                    "PHASE3_WGS_FAST_SV_EVIDENCE_THREADS": "12",
                },
                clear=False,
            ):
                plan, plan_path = sv_evidence.load_plan_from_environment()
                sv_evidence.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual(12, plan["runtime"]["samtools_threads"])
            self.assertEqual(_sha256_json(input_path), plan["source"]["staged_inputs_manifest_sha256"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_sv_evidence_plan"', output_path.read_text(encoding="utf-8"))

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_manifest = root / "staged-inputs.json"
            linked_manifest = root / "staged-inputs-link.json"
            write_json(real_manifest, staged_inputs_manifest(root))
            linked_manifest.symlink_to(real_manifest)

            with self.assertRaisesRegex(
                sv_evidence.ManifestError,
                "staged-inputs-link\\.json SHA-256 input is missing or a symlink",
            ):
                sv_evidence._sha256_path(linked_manifest)

            real_parent = root / "real-inputs"
            linked_parent = root / "linked-inputs"
            real_parent.mkdir()
            parent_manifest = real_parent / "staged-inputs.json"
            write_json(parent_manifest, staged_inputs_manifest(root))
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                sv_evidence.ManifestError,
                "staged-inputs\\.json SHA-256 input parent may not be a symlink",
            ):
                sv_evidence._sha256_path(linked_parent / "staged-inputs.json")


if __name__ == "__main__":
    unittest.main()
