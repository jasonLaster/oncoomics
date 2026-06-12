import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import nextflow_process as nf


def command_names(steps):
    return [step.command for step in steps if step.kind in {"python", "optional_python"}]


def write_post_validation_context(root: Path) -> None:
    for artifact in nf.POST_VALIDATION_CONTEXT_ARTIFACTS:
        path = root / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if artifact.endswith(".json") else "header\n", encoding="utf-8")


class NextflowProcessTest(unittest.TestCase):
    def test_quick_plan_keeps_nonfatal_full_output_verifier(self):
        steps = nf.workflow_steps(nf.ProcessConfig(stage="quick"))
        self.assertEqual(command_names(steps)[:3], ["verify:plan", "fetch:phase1", "fetch:raw-candidates"])
        self.assertEqual(steps[-1].kind, "optional_python")
        self.assertEqual(steps[-1].command, "verify:outputs")
        self.assertIn("quick does not recompute", steps[-1].failure_message)

    def test_split_fetch_workspace_skips_wes_by_default_and_removes_fastq_scratch(self):
        steps = nf.workflow_steps(nf.ProcessConfig(stage="phase3_fetch_workspace"))
        messages = [step.message for step in steps if step.kind == "message"]
        self.assertIn(
            "Skipping full WES prerequisite for split Phase 3 WGS; use --phase3_include_wes true for orthogonal WES ladder.", messages
        )
        self.assertNotIn("benchmark:full-wes", command_names(steps))
        self.assertEqual(steps[-1], nf.remove_path_step(nf.PHASE3_FASTQ_DIR))

    def test_phase3_full_wgs_without_wes_uses_phase3_output_gate(self):
        config = nf.ProcessConfig(stage="phase3_wgs", phase3_reads="full", phase3_include_wes=False)
        steps = nf.workflow_steps(config)
        self.assertIn("verify:phase3-outputs", command_names(steps))
        self.assertNotIn("verify:outputs", command_names(steps))

    def test_phase3_full_wgs_with_wes_uses_whole_pipeline_gate(self):
        config = nf.ProcessConfig(stage="phase3_wgs", phase3_reads="full", phase3_include_wes=True)
        steps = nf.workflow_steps(config)
        self.assertIn("benchmark:full-wes", command_names(steps))
        self.assertIn("verify:outputs", command_names(steps))
        self.assertNotIn("verify:phase3-outputs", command_names(steps))

    def test_phase3_post_validation_continues_without_rerunning_validation(self):
        config = nf.ProcessConfig(stage="phase3_post_validation", phase3_reads="full", phase3_include_wes=False)
        steps = nf.workflow_steps(config)
        commands = command_names(steps)
        self.assertEqual(commands[0], "verify:phase3-outputs")
        self.assertNotIn("validate:phase3-wgs", commands)
        self.assertEqual(commands[-1], "verify:phase3-outputs")
        self.assertIn("build:packet", commands)

    def test_phase3_post_validation_uses_previous_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            previous = root / "previous"
            source = root / "source"
            workspace = root / "workspace"
            (previous / "results/phase3_wgs_smoke").mkdir(parents=True)
            (previous / "results/phase3_wgs_smoke/phase3_wgs_summary.json").write_text('{"status":"passed"}\n', encoding="utf-8")
            write_post_validation_context(source)

            config = nf.ProcessConfig(stage="phase3_post_validation", workspace=workspace, previous_workspace=previous, source_dir=source)
            prepared = nf.prepare_workspace(config)

            self.assertEqual(prepared, workspace.resolve())
            self.assertEqual(
                (workspace / "results/phase3_wgs_smoke/phase3_wgs_summary.json").read_text(encoding="utf-8"),
                '{"status":"passed"}\n',
            )
            self.assertTrue((workspace / "data/processed/catalog/cbioportal_tcga_brca_summary.json").is_file())

    def test_phase3_post_validation_fails_when_context_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            previous = root / "previous"
            workspace = root / "workspace"
            (previous / "results/phase3_wgs_smoke").mkdir(parents=True)
            config = nf.ProcessConfig(stage="phase3_post_validation", workspace=workspace, previous_workspace=previous)

            with self.assertRaisesRegex(RuntimeError, "requires staged cBioPortal/Xena/GDC context artifacts"):
                nf.prepare_workspace(config)

    def test_phase3_env_preserves_inherited_thread_overrides(self):
        config = nf.ProcessConfig(
            stage="phase3_align_sample",
            role="tumor",
            task_cpus="16",
            phase3_reads="full",
            phase3_source_mode="aws_sra",
            phase3_bwa_threads="12",
            phase3_sort_threads="4",
            phase3_asset_cache_uri="s3://cache/phase3_wgs",
        )
        with patch.dict(os.environ, {"PHASE3_WGS_THREADS": "24"}, clear=False):
            env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(env["DIANA_OMICS_ROOT"], "/tmp/workspace")
        self.assertEqual(env["PHASE3_WGS_THREADS"], "24")
        self.assertEqual(env["PHASE3_WGS_BWA_THREADS"], "12")
        self.assertEqual(env["PHASE3_WGS_SORT_THREADS"], "4")
        self.assertEqual(env["PHASE3_WGS_SRA_THREADS"], "16")
        self.assertEqual(env["PHASE3_WGS_STAGE"], "align_sample")
        self.assertEqual(env["PHASE3_WGS_FETCH_ONLY_ROLE"], "tumor")
        self.assertEqual(env["PHASE3_WGS_SOURCE_MODE"], "aws_sra")
        self.assertEqual(env["PHASE3_WGS_ASSET_CACHE_URI"], "s3://cache/phase3_wgs")

    def test_phase3_env_sets_alignment_thread_overrides(self):
        config = nf.ProcessConfig(
            stage="phase3_align_sample",
            role="tumor",
            task_cpus="64",
            phase3_bwa_threads="48",
            phase3_sort_threads="8",
        )
        env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(env["PHASE3_WGS_THREADS"], "64")
        self.assertEqual(env["PHASE3_WGS_BWA_THREADS"], "48")
        self.assertEqual(env["PHASE3_WGS_SORT_THREADS"], "8")

    def test_downstream_merge_copies_normal_bam_side_and_reusable_summaries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tumor = root / "tumor"
            normal = root / "normal"
            workspace = root / "workspace"
            (tumor / nf.PHASE3_BAM_DIR).mkdir(parents=True)
            (tumor / nf.PHASE3_LOG_DIR).mkdir(parents=True)
            (tumor / nf.PHASE3_STAGE_MARKER_DIR).mkdir(parents=True)
            (normal / nf.PHASE3_BAM_DIR).mkdir(parents=True)
            (normal / nf.PHASE3_LOG_DIR).mkdir(parents=True)
            (normal / nf.PHASE3_STAGE_MARKER_DIR).mkdir(parents=True)
            (tumor / nf.PHASE3_BAM_DIR / "tumor.bam").write_text("tumor\n", encoding="utf-8")
            (normal / nf.PHASE3_BAM_DIR / "normal.bam").write_text("normal\n", encoding="utf-8")
            (normal / nf.PHASE3_LOG_DIR / "normal.log").write_text("log\n", encoding="utf-8")
            artifact = "results/phase3_wgs_smoke/bam_validation_summary.csv"
            (normal / artifact).parent.mkdir(parents=True, exist_ok=True)
            (normal / artifact).write_text("status\npassed\n", encoding="utf-8")

            config = nf.ProcessConfig(
                stage="phase3_downstream",
                workspace=workspace,
                tumor_workspace=tumor,
                normal_workspace=normal,
                tumor_role="tumor",
                normal_role="normal",
            )
            nf.merge_downstream_workspaces(config)

            self.assertTrue((workspace / nf.PHASE3_BAM_DIR / "tumor.bam").is_file())
            self.assertTrue((workspace / nf.PHASE3_BAM_DIR / "normal.bam").is_file())
            self.assertTrue((workspace / nf.PHASE3_LOG_DIR / "normal.log").is_file())
            self.assertEqual((workspace / artifact).read_text(encoding="utf-8"), "status\npassed\n")


if __name__ == "__main__":
    unittest.main()
