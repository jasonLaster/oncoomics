from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_NF = ROOT / "main.nf"
NEXTFLOW_CONFIG = ROOT / "nextflow.config"
NEXT_GEN_DOC = ROOT / "docs/operations/next-generation-fast-rerun.md"


class Phase3FastNextflowTests(unittest.TestCase):
    def test_phase3_fast_workflow_starts_with_input_manifest_process(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        self.assertIn("process FAST_INPUT_MANIFEST", text)
        self.assertIn("workflow PHASE3_WGS_FAST", text)
        self.assertIn("'phase3_wgs_fast'", text)
        self.assertIn("PHASE3_WGS_FAST()", text)
        self.assertIn("build:phase3-fast-input-manifest", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/input_manifest.json", text)

    def test_fast_input_manifest_receipts_are_nextflow_path_inputs(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        for name in (
            "phase3_fast_private_freeze_receipt",
            "phase3_fast_private_sha256_receipt",
            "phase3_fast_reference_freeze_receipt",
            "phase3_fast_reference_sha256_receipt",
            "phase3_fast_bam_validation_receipt",
            "phase3_fast_contig_compatibility_receipt",
            "phase3_fast_caller_resource_receipt",
        ):
            self.assertIn(f"file(params.{name}.toString(), checkIfExists: true)", text)

    def test_fast_input_manifest_params_are_configured(self) -> None:
        config = NEXTFLOW_CONFIG.read_text(encoding="utf-8")
        main = MAIN_NF.read_text(encoding="utf-8")

        for name in (
            "phase3_fast_parameter_sha256",
            "phase3_fast_parabricks_container_digest",
            "phase3_fast_parabricks_version",
            "phase3_fast_gatk_version",
            "phase3_fast_source_commit",
            "phase3_fast_run_id",
            "phase3_fast_subject_alias",
            "phase3_fast_pair_id",
            "phase3_fast_tumor_sample_id",
            "phase3_fast_normal_sample_id",
            "phase3_fast_reference_id",
        ):
            self.assertIn(name, config)
            self.assertIn(name, main)

    def test_fast_rerun_docs_bind_gate0_to_nextflow_dag(self) -> None:
        text = NEXT_GEN_DOC.read_text(encoding="utf-8")

        self.assertIn("`phase3_wgs_fast` Nextflow DAG starts with the same renderer", text)
        self.assertIn("`FAST_INPUT_MANIFEST`", text)


if __name__ == "__main__":
    unittest.main()
