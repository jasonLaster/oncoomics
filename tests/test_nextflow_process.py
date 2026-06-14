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

    def test_split_fetch_workspace_can_skip_public_context_setup_for_speed_experiments(self):
        steps = nf.workflow_steps(nf.ProcessConfig(stage="phase3_fetch_workspace", phase3_prereq_mode="none"))
        messages = [step.message for step in steps if step.kind == "message"]
        commands = command_names(steps)
        self.assertIn("Skipping public context setup for split Phase 3 WGS alignment-speed experiment.", messages)
        self.assertIn("Skipping production somatic prerequisites for split Phase 3 WGS minimal mode.", messages)
        self.assertNotIn("fetch:phase1", commands)
        self.assertIn("fetch:full-reference-smoke", commands)
        self.assertNotIn("fetch:production-somatic", commands)
        self.assertIn("fetch:phase3-wgs", commands)

    def test_split_fetch_workspace_minimal_skips_production_somatic_downloads(self):
        steps = nf.workflow_steps(nf.ProcessConfig(stage="phase3_fetch_workspace", phase3_prereq_mode="minimal"))
        messages = [step.message for step in steps if step.kind == "message"]
        commands = command_names(steps)
        self.assertIn("fetch:full-reference-smoke", commands)
        self.assertNotIn("fetch:production-somatic", commands)
        self.assertNotIn("smoke:production-somatic", commands)
        self.assertIn("Skipping production somatic prerequisites for split Phase 3 WGS minimal mode.", messages)

    def test_cache_stream_align_sample_skips_repeated_fastq_fetch(self):
        steps = nf.workflow_steps(nf.ProcessConfig(stage="phase3_align_sample", phase3_align_input_mode="cache_stream"))
        commands = command_names(steps)
        self.assertNotIn("fetch:phase3-wgs", commands)
        self.assertIn("validate:phase3-wgs", commands)
        self.assertEqual(steps[-2], nf.remove_path_step(nf.PHASE3_FASTQ_DIR))
        self.assertEqual(steps[-1], nf.remove_path_step(nf.PHASE3_BAM_DIR))

    def test_cache_stream_fetch_workspace_uses_cache_manifest_fastq_mode(self):
        config = nf.ProcessConfig(
            stage="phase3_fetch_workspace",
            phase3_align_input_mode="cache_stream",
            phase3_asset_cache_uri="s3://cache/phase3_wgs",
        )
        env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(env["PHASE3_WGS_FASTQ_LOCAL_MODE"], "cache_manifest")

    def test_source_reference_index_prepares_cache_stream_manifest_and_reference(self):
        config = nf.ProcessConfig(
            stage="phase3_reference_index",
            source_dir=Path("/tmp/source"),
            phase3_align_input_mode="cache_stream",
            phase3_asset_cache_uri="s3://cache/phase3_wgs",
        )
        commands = command_names(nf.workflow_steps(config))
        env = nf.process_environment(config, Path("/tmp/workspace"))

        self.assertIn("fetch:full-reference-smoke", commands)
        self.assertIn("fetch:phase3-wgs", commands)
        self.assertEqual(commands[-1], "validate:phase3-wgs")
        self.assertEqual(env["PHASE3_WGS_FASTQ_LOCAL_MODE"], "cache_manifest")
        self.assertEqual(env["PHASE3_WGS_STAGE"], "reference_index")

    def test_source_reference_index_prepares_from_source_without_previous_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            workspace = root / "workspace"
            (source / "src").mkdir(parents=True)
            (source / "src/example.txt").write_text("source\n", encoding="utf-8")

            config = nf.ProcessConfig(stage="phase3_reference_index", source_dir=source, workspace=workspace)
            prepared = nf.prepare_workspace(config)

            self.assertEqual(prepared, workspace.resolve())
            self.assertEqual((workspace / "src/example.txt").read_text(encoding="utf-8"), "source\n")

    def test_shard_manifest_gather_can_use_preseeded_minimal_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace = root / "workspace"
            sentinel = workspace / "results/phase3_wgs_smoke/asset_summary.json"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text('{"status":"ready"}\n', encoding="utf-8")

            config = nf.ProcessConfig(
                stage="phase3_gather_shards",
                workspace=workspace,
                role="tumor",
                phase3_scatter_output_mode="shard_manifest",
            )
            prepared = nf.prepare_workspace(config)

            self.assertEqual(prepared, workspace.resolve())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"status":"ready"}\n')

    def test_minimal_fetch_marks_gatk_optional_for_full_source_timing(self):
        config = nf.ProcessConfig(
            stage="phase3_fetch_workspace",
            phase3_source_mode="aws_sra",
            phase3_prereq_mode="minimal",
        )
        env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(env["PHASE3_WGS_REQUIRE_GATK"], "0")

        config = nf.ProcessConfig(
            stage="phase3_fetch_workspace",
            phase3_source_mode="public_bam",
            phase3_prereq_mode="minimal",
        )
        env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(env["PHASE3_WGS_REQUIRE_GATK"], "0")

    def test_full_prereq_fetch_keeps_gatk_required(self):
        config = nf.ProcessConfig(
            stage="phase3_fetch_workspace",
            phase3_source_mode="aws_sra",
            phase3_prereq_mode="full",
        )
        env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(env["PHASE3_WGS_REQUIRE_GATK"], "1")

        config = nf.ProcessConfig(
            stage="phase3_fetch_workspace",
            phase3_source_mode="public_bam",
            phase3_prereq_mode="full",
        )
        env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(env["PHASE3_WGS_REQUIRE_GATK"], "1")

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
            phase3_aligner="bwa-mem2",
            phase3_bwa_threads="12",
            phase3_sort_threads="4",
            phase3_align_input_mode="cache_stream",
            phase3_align_profile_mode="mem_only",
            phase3_scatter_output_mode="shard_manifest",
            phase3_shard_input_mode="sra_spot_range",
            phase3_bam_validation_mode="flagstat_only",
            phase3_coverage_cnv_mode="metadata",
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
        self.assertEqual(env["PHASE3_WGS_ALIGNER"], "bwa-mem2")
        self.assertEqual(env["PHASE3_WGS_ALIGN_INPUT_MODE"], "cache_stream")
        self.assertEqual(env["PHASE3_WGS_ALIGN_PROFILE_MODE"], "mem_only")
        self.assertEqual(env["PHASE3_WGS_SCATTER_OUTPUT_MODE"], "shard_manifest")
        self.assertEqual(env["PHASE3_WGS_SHARD_INPUT_MODE"], "sra_spot_range")
        self.assertEqual(env["PHASE3_WGS_BAM_VALIDATION_MODE"], "flagstat_only")
        self.assertEqual(env["PHASE3_WGS_COVERAGE_CNV_MODE"], "metadata")
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

    def test_phase3_shard_stages_set_role_and_shard_environment(self):
        config = nf.ProcessConfig(
            stage="phase3_align_shard",
            role="tumor",
            task_cpus="32",
            phase3_align_input_mode="cache_stream",
            phase3_aligner="minimap2",
            phase3_bwa_threads="24",
            phase3_sort_threads="8",
            phase3_shard_count="8",
            phase3_shard_index="3",
            phase3_force="true",
            phase3_force_shard_alignment="true",
            phase3_asset_cache_uri="s3://cache/phase3_wgs",
        )
        steps = nf.workflow_steps(config)
        env = nf.process_environment(config, Path("/tmp/workspace"))
        self.assertEqual(command_names(steps), ["validate:phase3-wgs"])
        self.assertEqual(steps[-2], nf.remove_path_step(nf.PHASE3_FASTQ_DIR))
        self.assertEqual(steps[-1], nf.remove_path_step(nf.PHASE3_BAM_DIR))
        self.assertEqual(env["PHASE3_WGS_STAGE"], "align_shard")
        self.assertEqual(env["PHASE3_WGS_SAMPLE_ROLE"], "tumor")
        self.assertEqual(env["PHASE3_WGS_SHARD_COUNT"], "8")
        self.assertEqual(env["PHASE3_WGS_SHARD_INDEX"], "3")
        self.assertEqual(env["PHASE3_WGS_ALIGNER"], "minimap2")
        self.assertEqual(env["PHASE3_WGS_BWA_THREADS"], "24")
        self.assertEqual(env["PHASE3_WGS_SORT_THREADS"], "8")
        self.assertEqual(env["PHASE3_WGS_FORCE"], "1")
        self.assertEqual(env["PHASE3_WGS_FORCE_SHARD_ALIGNMENT"], "1")

    def test_phase3_gather_stage_keeps_bam_outputs(self):
        steps = nf.workflow_steps(nf.ProcessConfig(stage="phase3_gather_shards", role="tumor", phase3_shard_count="8"))
        self.assertEqual(command_names(steps), ["validate:phase3-wgs"])
        self.assertNotIn(nf.remove_path_step(nf.PHASE3_BAM_DIR), steps)

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

    def test_downstream_merge_accepts_pruned_align_workspaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tumor = root / "tumor"
            normal = root / "normal"
            workspace = root / "workspace"
            (tumor / nf.PHASE3_LOG_DIR).mkdir(parents=True)
            (tumor / nf.PHASE3_STAGE_MARKER_DIR).mkdir(parents=True)
            (normal / nf.PHASE3_LOG_DIR).mkdir(parents=True)
            (normal / nf.PHASE3_STAGE_MARKER_DIR).mkdir(parents=True)
            (tumor / nf.PHASE3_LOG_DIR / "tumor.log").write_text("tumor log\n", encoding="utf-8")
            (normal / nf.PHASE3_LOG_DIR / "normal.log").write_text("normal log\n", encoding="utf-8")

            config = nf.ProcessConfig(
                stage="phase3_downstream",
                workspace=workspace,
                tumor_workspace=tumor,
                normal_workspace=normal,
                tumor_role="tumor",
                normal_role="normal",
            )
            nf.merge_downstream_workspaces(config)

            self.assertTrue((workspace / nf.PHASE3_LOG_DIR / "tumor.log").is_file())
            self.assertTrue((workspace / nf.PHASE3_LOG_DIR / "normal.log").is_file())
            self.assertTrue((workspace / nf.PHASE3_BAM_DIR).is_dir())
            self.assertEqual(list((workspace / nf.PHASE3_BAM_DIR).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
