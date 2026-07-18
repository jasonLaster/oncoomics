from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_NF = ROOT / "main.nf"
NEXTFLOW_CONFIG = ROOT / "nextflow.config"
NEXT_GEN_DOC = ROOT / "docs/operations/next-generation-fast-rerun.md"
FAST_STUB_SCRIPT = ROOT / "scripts/run_phase3_wgs_fast_stub.sh"


class Phase3FastNextflowTests(unittest.TestCase):
    def test_phase3_fast_workflow_starts_with_input_manifest_process(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        self.assertIn("process FAST_INPUT_MANIFEST", text)
        self.assertIn("process FAST_REPLICATION_PLAN", text)
        self.assertIn("process FAST_REPLICATE_INPUTS", text)
        self.assertIn("process FAST_CACHE_MANIFEST", text)
        self.assertIn("process FAST_STAGING_PLAN", text)
        self.assertIn("process FAST_PARABRICKS_MUTECT_PLAN", text)
        self.assertIn("process FAST_BAM_QC_PLAN", text)
        self.assertIn("process FAST_CNV_EVIDENCE_PLAN", text)
        self.assertIn("process FAST_SV_EVIDENCE_PLAN", text)
        self.assertIn("process FAST_FILTER_MUTECT_PLAN", text)
        self.assertIn("process FAST_BAM_CNV_SV_EVIDENCE", text)
        self.assertIn("process FAST_EVIDENCE_JOIN", text)
        self.assertIn("process FAST_VERIFY_AND_PUBLISH", text)
        self.assertIn("process FAST_CROSSCHECK_MATERIALIZATION_PLAN", text)
        self.assertIn("process FAST_STAGE_DETERMINISTIC_REPORT", text)
        self.assertIn("process FAST_STAGE_ROSALIND_PACKET", text)
        self.assertIn("process FAST_STAGE_BLOCKED_CROSSCHECKS", text)
        self.assertNotIn("process FAST_STAGE_INPUTS", text)
        self.assertIn("workflow PHASE3_WGS_FAST", text)
        self.assertIn("'phase3_wgs_fast'", text)
        self.assertIn("PHASE3_WGS_FAST()", text)
        self.assertIn("build:phase3-fast-input-manifest", text)
        self.assertIn("build:phase3-fast-replication-plan", text)
        self.assertIn("build:phase3-fast-staging-plan", text)
        self.assertIn("replicate:phase3-fast-inputs", text)
        self.assertIn("build:phase3-fast-cache-manifest", text)
        self.assertIn("stage:phase3-fast-inputs", text)
        self.assertIn("build:phase3-fast-parabricks-mutect-plan", text)
        self.assertIn("build:phase3-fast-bam-qc-plan", text)
        self.assertIn("build:phase3-fast-cnv-evidence-plan", text)
        self.assertIn("build:phase3-fast-sv-evidence-plan", text)
        self.assertIn("build:phase3-fast-filter-mutect-plan", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/input_manifest.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/replication_plan.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/replication_receipt.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/cache_manifest.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/staging_plan.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/bam_qc_plan.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json", text)
        self.assertIn("workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json", text)
        self.assertIn("phase3_wgs_fast_staged_inputs_manifest", text)
        self.assertIn("phase3_wgs_fast_parabricks_mutect_plan", text)
        self.assertIn("phase3_wgs_fast_bam_qc_plan", text)
        self.assertIn("phase3_wgs_fast_cnv_evidence_plan", text)
        self.assertIn("phase3_wgs_fast_sv_evidence_plan", text)
        self.assertIn("phase3_wgs_fast_bam_qc_receipt", text)
        self.assertIn("phase3_wgs_fast_cnv_evidence_receipt", text)
        self.assertIn("phase3_wgs_fast_sv_evidence_receipt", text)
        self.assertIn("phase3_wgs_fast_evidence_join_manifest", text)
        self.assertIn("phase3_wgs_fast_final_evidence_manifest", text)
        self.assertIn("phase3_wgs_fast_crosscheck_materialization_plan", text)
        self.assertIn("phase3_fast_deterministic_evidence", text)
        self.assertIn("rosalind_hrd_reviewer_packet", text)
        self.assertIn("blocked_method", text)
        self.assertIn("facets_scarhrd_blocked", text)
        self.assertIn("oncoanalyser_chord_blocked", text)
        self.assertIn("hrdetect_blocked", text)
        self.assertIn("phase3_wgs_fast_filter_mutect_plan", text)

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
            "phase3_fast_sequenza_female",
            "phase3_fast_cache_prefix",
            "phase3_fast_cache_kms_key_arn",
            "phase3_fast_cache_region",
            "phase3_fast_replication_mode",
            "phase3_fast_replication_part_size_bytes",
            "phase3_fast_staging_root",
            "phase3_fast_parabricks_cpus",
            "phase3_fast_parabricks_memory",
            "phase3_fast_parabricks_num_gpus",
            "phase3_fast_parabricks_output_root",
            "phase3_fast_bam_qc_output_root",
            "phase3_fast_bam_qc_threads",
            "phase3_fast_cnv_evidence_output_root",
            "phase3_fast_cnv_evidence_bin_size",
            "phase3_fast_cnv_evidence_bedcov_workers",
            "phase3_fast_sv_evidence_output_root",
            "phase3_fast_sv_evidence_threads",
            "phase3_fast_filter_mutect_output_root",
            "phase3_fast_small_variant_mode",
            "phase3_fast_gatk_version",
            "phase3_fast_source_commit",
            "phase3_fast_run_id",
            "phase3_fast_generated_at",
            "phase3_fast_subject_alias",
            "phase3_fast_pair_id",
            "phase3_fast_tumor_sample_id",
            "phase3_fast_normal_sample_id",
            "phase3_fast_reference_id",
            "phase3_fast_forbidden_tokens_json",
        ):
            self.assertIn(name, config)
            self.assertIn(name, main)

    def test_fast_rerun_docs_bind_gate0_to_nextflow_dag(self) -> None:
        text = NEXT_GEN_DOC.read_text(encoding="utf-8")

        self.assertIn("`phase3_wgs_fast` Nextflow DAG starts with the same renderer", text)
        self.assertIn("`FAST_INPUT_MANIFEST`", text)
        self.assertIn("`FAST_REPLICATION_PLAN`", text)
        self.assertIn("`FAST_REPLICATE_INPUTS`", text)
        self.assertIn("FAST_GPU_SMOKE                     bounded P5en/Parabricks placement gate", text)
        self.assertIn("FAST_MUTECT_PARABRICKS_FILTER      worker-local Parabricks", text)
        self.assertIn("FAST_BAM_CNV_SV_EVIDENCE           worker-local BAM QC", text)
        self.assertIn("FAST_STAGE_DETERMINISTIC_REPORT     six-file deterministic method report", text)
        self.assertIn("`crosscheck_input_plans.json`", text)
        self.assertIn("`run:phase3-fast-parabricks-mutect` must consume that plan", text)
        self.assertIn("`run:phase3-fast-filter-mutect` must require", text)
        self.assertNotIn("five-file deterministic method report", text)
        self.assertNotIn("FAST_FQ2BAM_TUMOR", text)
        self.assertNotIn("FAST_MUTECT_PARABRICKS             selected GPU caller", text)
        self.assertNotIn("`FAST_MUTECT_PARABRICKS` must consume", text)
        self.assertNotIn("`FAST_FILTER_MUTECT` must require", text)

    def test_local_fast_stub_exercises_full_execute_branch_without_large_resources(self) -> None:
        script = FAST_STUB_SCRIPT.read_text(encoding="utf-8")

        for receipt in (
            "private_freeze",
            "private_sha256",
            "reference_freeze",
            "reference_sha256",
            "bam_validation",
            "contig_compatibility",
            "caller_resource",
        ):
            self.assertIn(f"--phase3_fast_{receipt}_receipt", script)

        self.assertIn("--workflow phase3_wgs_fast", script)
        self.assertIn("--phase3_fast_replication_mode apply", script)
        self.assertIn("--phase3_fast_small_variant_mode execute", script)
        self.assertIn("--phase3_fast_parabricks_cpus 1", script)
        self.assertIn("--phase3_fast_parabricks_memory '1 GB'", script)
        self.assertIn("--phase3_fast_generated_at 2026-07-16T03:31:01+00:00", script)
        self.assertIn("--phase3_fast_forbidden_tokens_json", script)
        self.assertIn("-stub-run", script)
        self.assertLess(script.index("mkdir -p logs"), script.index("nextflow -log logs/nextflow.log"))
        self.assertIn("--parabricks_container", script)

    def test_input_manifest_derives_parabricks_digest_from_runtime_container(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        self.assertIn("params.parabricks_container?.toString()?.contains('@')", text)
        self.assertIn("params.parabricks_container.toString().split('@', 2)[1]", text)
        self.assertIn('export PHASE3_WGS_FAST_PARABRICKS_CONTAINER="${params.parabricks_container}"', text)

    def test_replication_plan_consumes_input_manifest_output(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        self.assertIn("FAST_REPLICATION_PLAN(FAST_INPUT_MANIFEST.out)", text)
        self.assertIn("FAST_REPLICATE_INPUTS(FAST_REPLICATION_PLAN.out)", text)
        self.assertIn("FAST_CACHE_MANIFEST(FAST_REPLICATE_INPUTS.out)", text)
        self.assertIn("FAST_STAGING_PLAN(FAST_CACHE_MANIFEST.out)", text)
        self.assertIn("FAST_PARABRICKS_MUTECT_PLAN(FAST_STAGING_PLAN.out)", text)
        self.assertIn("FAST_BAM_QC_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)", text)
        self.assertIn("FAST_CNV_EVIDENCE_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)", text)
        self.assertIn("FAST_SV_EVIDENCE_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)", text)
        self.assertIn("FAST_FILTER_MUTECT_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)", text)
        self.assertIn("FAST_STAGE_BLOCKED_CROSSCHECKS(FAST_STAGE_ROSALIND_PACKET.out)", text)
        self.assertIn("phase3_fast_replication_mode.toString().replace('-', '_') == 'apply'", text)
        self.assertIn('export PHASE3_WGS_FAST_INPUT_MANIFEST="\\$PWD/${input_manifest}"', text)
        self.assertIn('export PHASE3_WGS_FAST_CACHE_PREFIX="${params.phase3_fast_cache_prefix}"', text)
        self.assertIn('export PHASE3_WGS_FAST_CACHE_KMS_KEY_ARN="${params.phase3_fast_cache_kms_key_arn}"', text)
        self.assertIn('export PHASE3_WGS_FAST_REPLICATION_MODE="${params.phase3_fast_replication_mode}"', text)
        self.assertIn(
            'export PHASE3_WGS_FAST_REPLICATION_PART_SIZE_BYTES="${params.phase3_fast_replication_part_size_bytes}"',
            text,
        )
        self.assertIn('export PHASE3_WGS_FAST_REPLICATION_RECEIPT="\\$PWD/${replication_receipt}"', text)
        self.assertIn('export PHASE3_WGS_FAST_CACHE_MANIFEST="\\$PWD/${cache_manifest}"', text)

    def test_parabricks_plan_materializes_scratch_inputs_worker_locally(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        self.assertLess(
            text.index("stage:phase3-fast-inputs"),
            text.index("build:phase3-fast-parabricks-mutect-plan"),
        )
        self.assertIn('export PHASE3_WGS_FAST_STAGING_PLAN="\\$PWD/${staging_plan}"', text)
        self.assertIn(
            'export PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"',
            text,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"',
            text,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json"',
            text,
        )
        self.assertIn('export PHASE3_WGS_FAST_PARABRICKS_OUTPUT_ROOT="${params.phase3_fast_parabricks_output_root}"', text)
        self.assertIn('export PHASE3_WGS_FAST_PARABRICKS_NUM_GPUS="${params.phase3_fast_parabricks_num_gpus}"', text)

    def test_filter_mutect_plan_consumes_parabricks_handoff_tuple(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        self.assertIn(
            "tuple path('workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json'), "
            "path('workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json')",
            text,
        )
        self.assertIn("tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)", text)
        self.assertIn('export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\\$PWD/${staged_inputs_manifest}"', text)
        self.assertIn('export PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN="\\$PWD/${parabricks_mutect_plan}"', text)
        self.assertIn(
            'export PHASE3_WGS_FAST_FILTER_MUTECT_PLAN_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json"',
            text,
        )
        self.assertIn('export PHASE3_WGS_FAST_FILTER_MUTECT_OUTPUT_ROOT="${params.phase3_fast_filter_mutect_output_root}"', text)

    def test_bam_qc_plan_consumes_staged_bam_handoff_tuple(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_BAM_QC_PLAN") :]
        process = process[: process.index("process FAST_MUTECT_PARABRICKS_FILTER")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)", process)
        self.assertIn("workspace/manifests/phase3_wgs_fast/bam_qc_plan.json", process)
        self.assertIn('export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\\$PWD/${staged_inputs_manifest}"', process)
        self.assertIn(
            'export PHASE3_WGS_FAST_BAM_QC_PLAN_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/bam_qc_plan.json"',
            process,
        )
        self.assertIn('export PHASE3_WGS_FAST_BAM_QC_OUTPUT_ROOT="${params.phase3_fast_bam_qc_output_root}"', process)
        self.assertIn('export PHASE3_WGS_FAST_BAM_QC_THREADS="${params.phase3_fast_bam_qc_threads}"', process)
        self.assertIn("build:phase3-fast-bam-qc-plan", process)

    def test_sv_evidence_plan_consumes_staged_bam_handoff_tuple(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_SV_EVIDENCE_PLAN") :]
        process = process[: process.index("process FAST_MUTECT_PARABRICKS_FILTER")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)", process)
        self.assertIn("workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json", process)
        self.assertIn('export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\\$PWD/${staged_inputs_manifest}"', process)
        self.assertIn(
            'export PHASE3_WGS_FAST_SV_EVIDENCE_PLAN_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json"',
            process,
        )
        self.assertIn('export PHASE3_WGS_FAST_SV_EVIDENCE_OUTPUT_ROOT="${params.phase3_fast_sv_evidence_output_root}"', process)
        self.assertIn('export PHASE3_WGS_FAST_SV_EVIDENCE_THREADS="${params.phase3_fast_sv_evidence_threads}"', process)
        self.assertIn("build:phase3-fast-sv-evidence-plan", process)

    def test_cnv_evidence_plan_consumes_staged_bam_handoff_tuple(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_CNV_EVIDENCE_PLAN") :]
        process = process[: process.index("process FAST_SV_EVIDENCE_PLAN")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)", process)
        self.assertIn("workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json", process)
        self.assertIn('export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\\$PWD/${staged_inputs_manifest}"', process)
        self.assertIn(
            'export PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json"',
            process,
        )
        self.assertIn('export PHASE3_WGS_FAST_CNV_EVIDENCE_OUTPUT_ROOT="${params.phase3_fast_cnv_evidence_output_root}"', process)
        self.assertIn('export PHASE3_WGS_FAST_CNV_EVIDENCE_BIN_SIZE="${params.phase3_fast_cnv_evidence_bin_size}"', process)
        self.assertIn(
            'export PHASE3_WGS_FAST_CNV_EVIDENCE_BEDCOV_WORKERS="${params.phase3_fast_cnv_evidence_bedcov_workers}"',
            process,
        )
        self.assertIn("build:phase3-fast-cnv-evidence-plan", process)

    def test_fast_planning_and_gpu_processes_have_separate_aws_labels(self) -> None:
        main = MAIN_NF.read_text(encoding="utf-8")
        config = NEXTFLOW_CONFIG.read_text(encoding="utf-8")

        self.assertIn("label 'cpu_io'", main)
        self.assertIn("label 'gpu_parabricks'", main)
        self.assertIn("withLabel: cpu_io", config)
        self.assertIn("queue = params.aws_ondemand_queue", config)
        self.assertIn("withLabel: gpu_parabricks", config)
        self.assertIn("queue = params.aws_gpu_queue", config)
        self.assertIn("accelerator = params.phase3_fast_parabricks_num_gpus as int", config)
        self.assertIn("phase3_fast_parabricks_cpus = 192", config)
        self.assertIn("phase3_fast_parabricks_memory = '1900 GB'", config)
        self.assertIn("phase3_fast_parabricks_num_gpus = 8", config)
        self.assertIn("phase3_fast_parabricks_output_root = '/scratch/diana/phase3_wgs_fast/parabricks_mutect'", config)
        self.assertIn("phase3_fast_bam_qc_output_root = '/scratch/diana/phase3_wgs_fast/bam_qc'", config)
        self.assertIn("phase3_fast_bam_qc_threads = 8", config)
        self.assertIn("phase3_fast_cnv_evidence_output_root = '/scratch/diana/phase3_wgs_fast/cnv_evidence'", config)
        self.assertIn("phase3_fast_cnv_evidence_bin_size = 5000000", config)
        self.assertIn("phase3_fast_cnv_evidence_bedcov_workers = 4", config)
        self.assertIn("phase3_fast_sv_evidence_output_root = '/scratch/diana/phase3_wgs_fast/sv_evidence'", config)
        self.assertIn("phase3_fast_sv_evidence_threads = 8", config)
        self.assertIn("phase3_fast_filter_mutect_output_root = '/scratch/diana/phase3_wgs_fast/filter_mutect'", config)

    def test_gpu_smoke_records_parabricks_startup(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")
        process = text[text.index("process FAST_GPU_SMOKE") :]
        process = process[: process.index("process ALL_PUBLIC")]

        self.assertIn("pbrun version", process)
        self.assertIn("parabricks-version.txt", process)
        self.assertIn('"parabricksVersionCommand": "pbrun version"', process)
        self.assertIn('"parabricksVersionTxt": "parabricks-version.txt"', process)

    def test_blocked_crosschecks_are_staged_after_rosalind(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_STAGE_BLOCKED_CROSSCHECKS") :]
        process = process[: process.index("workflow PHASE3_WGS_FAST_GPU_SMOKE")]
        self.assertIn("label 'cpu_io'", process)
        for rosalind_input in (
            "rosalind_run_manifest",
            "rosalind_packet_index",
            "rosalind_cloud_materialization_plan",
            "rosalind_input_evidence_index",
            "rosalind_sample_validation_summary",
            "rosalind_hrd_adapter_status",
            "rosalind_research_context_sources",
            "rosalind_next_actions",
            "rosalind_reviewer_packet",
            "rosalind_report",
            "rosalind_report_manifest",
        ):
            self.assertIn(f"path({rosalind_input})", process)
            self.assertIn(f'test -s "${{{rosalind_input}}}"', process)
        self.assertIn("generate_blocked_hrd_crosscheck_reports.py", process)
        self.assertIn('--generated-at "${params.phase3_fast_generated_at}"', process)
        self.assertIn('--run-id "${params.phase3_fast_run_id}"', process)
        self.assertIn(
            '--source-report-manifest "rosalind_diana_wgs=${rosalind_report_manifest}"',
            process,
        )
        self.assertIn("workspace/results/phase3_wgs_fast/blocked_crosschecks", process)
        for method_id in (
            "facets_scarhrd_blocked",
            "oncoanalyser_chord_blocked",
            "hrdetect_blocked",
        ):
            self.assertIn(
                f"workspace/results/phase3_wgs_fast/blocked_crosschecks/{method_id}/method_spec.json",
                process,
            )
            self.assertIn(
                f"workspace/results/phase3_wgs_fast/blocked_crosschecks/{method_id}/report.md",
                process,
            )
            self.assertIn(
                f"workspace/results/phase3_wgs_fast/blocked_crosschecks/{method_id}/report_manifest.json",
                process,
            )

    def test_small_variant_execution_keeps_scratch_paths_worker_local(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_MUTECT_PARABRICKS_FILTER") :]
        process = process[: process.index("process FAST_BAM_CNV_SV_EVIDENCE")]
        self.assertIn("label 'gpu_parabricks'", process)
        self.assertIn("run:phase3-fast-parabricks-mutect", process)
        self.assertIn("run:phase3-fast-filter-mutect", process)
        self.assertIn("export:phase3-fast-small-variants", process)
        self.assertLess(process.index("stage:phase3-fast-inputs"), process.index("build:phase3-fast-parabricks-mutect-plan"))
        self.assertLess(
            process.index("build:phase3-fast-parabricks-mutect-plan"),
            process.index("run:phase3-fast-parabricks-mutect"),
        )
        self.assertLess(
            process.index("run:phase3-fast-parabricks-mutect"),
            process.index("build:phase3-fast-filter-mutect-plan"),
        )
        self.assertLess(process.index("build:phase3-fast-filter-mutect-plan"), process.index("run:phase3-fast-filter-mutect"))
        self.assertLess(
            process.index("run:phase3-fast-filter-mutect"),
            process.index("export:phase3-fast-small-variants"),
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_FILTER_MUTECT_PLAN="\\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT="\\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_receipt.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_ROOT="\\$PWD/workspace/results/phase3_wgs_fast/small_variant_execution/artifacts"',
            process,
        )
        self.assertIn("workspace/manifests/phase3_wgs_fast/small_variant_artifact_export.json", process)
        self.assertIn("workspace/results/phase3_wgs_fast/small_variant_execution/artifacts", process)

        self.assertIn("smallVariantMode = params.phase3_fast_small_variant_mode.toString()", text)
        self.assertIn("smallVariantMode == 'execute'", text)
        self.assertIn("FAST_MUTECT_PARABRICKS_FILTER(FAST_STAGING_PLAN.out)", text)
        self.assertIn("allowedSmallVariantModes = ['plan', 'execute']", text)
        self.assertIn("Unknown phase3_fast_small_variant_mode", text)

    def test_bam_cnv_sv_execution_keeps_scratch_paths_worker_local(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_BAM_CNV_SV_EVIDENCE") :]
        process = process[: process.index("process FAST_EVIDENCE_JOIN")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("stage:phase3-fast-inputs", process)
        self.assertIn("build:phase3-fast-bam-qc-plan", process)
        self.assertIn("run:phase3-fast-bam-qc", process)
        self.assertIn("build:phase3-fast-cnv-evidence-plan", process)
        self.assertIn("run:phase3-fast-cnv-evidence", process)
        self.assertIn("build:phase3-fast-sv-evidence-plan", process)
        self.assertIn("run:phase3-fast-sv-evidence", process)
        self.assertLess(process.index("stage:phase3-fast-inputs"), process.index("build:phase3-fast-bam-qc-plan"))
        self.assertLess(process.index("build:phase3-fast-bam-qc-plan"), process.index("run:phase3-fast-bam-qc"))
        self.assertLess(process.index("build:phase3-fast-cnv-evidence-plan"), process.index("run:phase3-fast-cnv-evidence"))
        self.assertLess(process.index("build:phase3-fast-sv-evidence-plan"), process.index("run:phase3-fast-sv-evidence"))
        self.assertIn(
            'export PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_BAM_QC_PLAN="\\$PWD/workspace/manifests/phase3_wgs_fast/bam_qc_plan.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_BAM_QC_RECEIPT_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/bam_qc_receipt.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN="\\$PWD/workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/cnv_evidence_receipt.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_SV_EVIDENCE_PLAN="\\$PWD/workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT_OUTPUT="\\$PWD/workspace/manifests/phase3_wgs_fast/sv_evidence_receipt.json"',
            process,
        )
        self.assertIn("workspace/results/phase3_wgs_fast/bam_qc", process)
        self.assertIn("workspace/results/phase3_wgs_fast/cnv_evidence", process)
        self.assertIn("workspace/results/phase3_wgs_fast/sv_evidence", process)
        self.assertIn("FAST_BAM_CNV_SV_EVIDENCE(FAST_STAGING_PLAN.out)", text)

    def test_evidence_join_consumes_terminal_execute_branch_outputs(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_EVIDENCE_JOIN") :]
        process = process[: process.index("process FAST_VERIFY_AND_PUBLISH")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("path small_variant_artifact_export", process)
        self.assertNotIn("path(small_staged_inputs_manifest)", process)
        self.assertNotIn("path(aux_staged_inputs_manifest)", process)
        self.assertIn("path(bam_qc_receipt)", process)
        self.assertIn("path(cnv_evidence_receipt)", process)
        self.assertIn("path(sv_evidence_receipt)", process)
        self.assertIn("workspace/manifests/phase3_wgs_fast/evidence_join_manifest.json", process)
        self.assertIn(
            'export PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT="\\$PWD/${small_variant_artifact_export}"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_BAM_QC_RECEIPT="\\$PWD/${bam_qc_receipt}"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT="\\$PWD/${cnv_evidence_receipt}"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT="\\$PWD/${sv_evidence_receipt}"',
            process,
        )
        self.assertIn("join:phase3-fast-evidence", process)
        self.assertIn("small_variant_export_for_join = FAST_MUTECT_PARABRICKS_FILTER.out.map", text)
        self.assertIn(
            "aux_receipts_for_join = FAST_BAM_CNV_SV_EVIDENCE.out.map",
            text,
        )
        self.assertIn("tuple(bam_qc_receipt, cnv_evidence_receipt, sv_evidence_receipt)", text)
        self.assertIn("FAST_EVIDENCE_JOIN(small_variant_export_for_join, aux_receipts_for_join)", text)

    def test_verify_and_publish_consumes_joined_evidence_artifacts(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_VERIFY_AND_PUBLISH") :]
        process = process[: process.index("process FAST_STAGE_DETERMINISTIC_REPORT")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("path evidence_join_manifest", process)
        self.assertIn("path small_variant_artifacts", process)
        self.assertIn("path(bam_qc_results)", process)
        self.assertIn("path(cnv_evidence_results)", process)
        self.assertIn("path(sv_evidence_results)", process)
        self.assertIn("workspace/manifests/phase3_wgs_fast/final_evidence_manifest.json", process)
        self.assertIn("workspace/results/phase3_wgs_fast/final", process)
        self.assertIn(
            'export PHASE3_WGS_FAST_EVIDENCE_JOIN="\\$PWD/${evidence_join_manifest}"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_SMALL_VARIANT_ARTIFACT_ROOT="\\$PWD/${small_variant_artifacts}"',
            process,
        )
        self.assertIn("publish:phase3-fast-final-evidence", process)
        self.assertIn(
            "small_variant_artifacts_for_publish = FAST_MUTECT_PARABRICKS_FILTER.out.map",
            text,
        )
        self.assertIn(
            "aux_artifacts_for_publish = FAST_BAM_CNV_SV_EVIDENCE.out.map",
            text,
        )
        self.assertIn("FAST_VERIFY_AND_PUBLISH(FAST_EVIDENCE_JOIN.out", text)

    def test_crosscheck_materialization_plan_consumes_fast_final_evidence(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_CROSSCHECK_MATERIALIZATION_PLAN") :]
        process = process[: process.index("process FAST_STAGE_ROSALIND_PACKET")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("tuple path(final_evidence_manifest)", process)
        self.assertIn("path(final_evidence_root)", process)
        self.assertIn(
            "workspace/manifests/phase3_wgs_fast/crosscheck_materialization_plan.json",
            process,
        )
        self.assertIn(
            'test -d "${final_evidence_root}"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST="\\$PWD/${final_evidence_manifest}"',
            process,
        )
        self.assertIn("build:phase3-fast-crosscheck-materialization-plan", process)
        self.assertIn(
            "FAST_CROSSCHECK_MATERIALIZATION_PLAN(FAST_VERIFY_AND_PUBLISH.out)",
            text,
        )

    def test_stage_deterministic_report_consumes_fast_final_evidence(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_STAGE_DETERMINISTIC_REPORT") :]
        process = process[: process.index("process FAST_STAGE_ROSALIND_PACKET")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("tuple path(final_evidence_manifest)", process)
        self.assertIn("path(final_evidence_root)", process)
        self.assertIn("workspace/results/phase3_wgs_fast/deterministic_report", process)
        self.assertIn("workspace/results/phase3_wgs_fast/deterministic_report/report.md", process)
        self.assertIn("workspace/results/phase3_wgs_fast/deterministic_report/report_manifest.json", process)
        self.assertIn("workspace/results/phase3_wgs_fast/deterministic_report/evidence_checks.json", process)
        self.assertIn("workspace/results/phase3_wgs_fast/deterministic_report/input_sha256.csv", process)
        self.assertIn("workspace/results/phase3_wgs_fast/deterministic_report/crosscheck_input_plans.json", process)
        self.assertIn(
            'export PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST="\\$PWD/${final_evidence_manifest}"',
            process,
        )
        self.assertIn(
            'export PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT="\\$PWD/${final_evidence_root}"',
            process,
        )
        self.assertIn("stage:phase3-fast-deterministic-report", process)
        self.assertIn("FAST_STAGE_DETERMINISTIC_REPORT(FAST_VERIFY_AND_PUBLISH.out)", text)

    def test_stage_rosalind_packet_consumes_phase3_fast_deterministic_report(self) -> None:
        text = MAIN_NF.read_text(encoding="utf-8")

        process = text[text.index("process FAST_STAGE_ROSALIND_PACKET") :]
        process = process[: process.index("process FAST_STAGE_BLOCKED_CROSSCHECKS")]
        self.assertIn("label 'cpu_io'", process)
        self.assertIn("tuple path(report_md)", process)
        self.assertIn("path(crosscheck_input_plans)", process)
        self.assertIn("path(final_evidence_root)", process)
        self.assertIn('cp "${crosscheck_input_plans}" deterministic_report/crosscheck_input_plans.json', process)
        self.assertIn("workspace/results/rosalind_hrd/${params.phase3_fast_run_id}/run_manifest.json", process)
        self.assertIn("workspace/results/rosalind_hrd/${params.phase3_fast_run_id}/packet_index.md", process)
        self.assertIn("workspace/results/rosalind_hrd/${params.phase3_fast_run_id}/cloud_materialization_plan.md", process)
        self.assertIn("workspace/results/rosalind_hrd/diana_wgs", process)
        self.assertIn("input_evidence_index.json", process)
        self.assertIn("sample_validation_summary.csv", process)
        self.assertIn("hrd_adapter_status.csv", process)
        self.assertIn("report_manifest.json", process)
        self.assertIn('export DIANA_OMICS_ROOT="\\$PWD/workspace"', process)
        self.assertIn('export ROSALIND_HRD_SAMPLE_SET="diana_wgs"', process)
        self.assertIn('export ROSALIND_HRD_RUN_ID="${params.phase3_fast_run_id}"', process)
        self.assertIn(
            'export ROSALIND_HRD_ARTIFACT_ROOT="\\$PWD/${final_evidence_root}"',
            process,
        )
        self.assertIn(
            'export ROSALIND_HRD_DETERMINISTIC_REPORT_DIR="\\$PWD/deterministic_report"',
            process,
        )
        self.assertIn("export ROSALIND_HRD_FORBIDDEN_TOKENS_JSON='${params.phase3_fast_forbidden_tokens_json}'", process)
        self.assertIn("phase3_wgs_fast execute mode requires: phase3_fast_forbidden_tokens_json", text)
        self.assertIn("build:rosalind-hrd-packet", process)
        self.assertIn(
            "FAST_STAGE_ROSALIND_PACKET(FAST_STAGE_DETERMINISTIC_REPORT.out, FAST_VERIFY_AND_PUBLISH.out)",
            text,
        )


if __name__ == "__main__":
    unittest.main()
