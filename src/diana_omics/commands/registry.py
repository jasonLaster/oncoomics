from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    module: str
    callable_name: str = "main"


@dataclass(frozen=True)
class CommandFamily:
    title: str
    description: str
    commands: tuple[str, ...]


COMMAND_SPECS: dict[str, CommandSpec] = {
    "analyze:hrd": CommandSpec("diana_omics.commands.hrd_context.analyze_hrd"),
    "analyze:lehmann": CommandSpec("diana_omics.commands.hrd_context.analyze_lehmann_subtypes"),
    "analyze:rna": CommandSpec("diana_omics.commands.hrd_context.build_rna_context"),
    "audit:raw-tools": CommandSpec("diana_omics.commands.raw_validation.audit_raw_tools"),
    "build:alignment-smoke": CommandSpec("diana_omics.commands.alignment_validation.build_alignment_smoke_assets"),
    "build:diana-samplesheet-from-delivery": CommandSpec(
        "diana_omics.commands.diana_intake.build_diana_raw_samplesheet_from_delivery"
    ),
    "build:diana-template": CommandSpec("diana_omics.commands.diana_intake.build_diana_raw_template"),
    "build:packet": CommandSpec("diana_omics.commands.hrd_context.build_reviewer_packet"),
    "build:phase3-fast-bam-qc-plan": CommandSpec("diana_omics.commands.phase3_wgs.render_phase3_fast_bam_qc_plan"),
    "build:phase3-fast-input-manifest": CommandSpec("diana_omics.commands.phase3_wgs.render_phase3_fast_input_manifest"),
    "build:phase3-fast-cache-manifest": CommandSpec("diana_omics.commands.phase3_wgs.render_phase3_fast_cache_manifest"),
    "build:phase3-fast-crosscheck-materialization-plan": CommandSpec(
        "diana_omics.commands.phase3_wgs.plan_phase3_fast_crosscheck_inputs"
    ),
    "build:phase3-fast-cnv-evidence-plan": CommandSpec(
        "diana_omics.commands.phase3_wgs.render_phase3_fast_cnv_evidence_plan"
    ),
    "build:phase3-fast-filter-mutect-plan": CommandSpec(
        "diana_omics.commands.phase3_wgs.render_phase3_fast_filter_mutect_plan"
    ),
    "build:phase3-fast-sv-evidence-plan": CommandSpec(
        "diana_omics.commands.phase3_wgs.render_phase3_fast_sv_evidence_plan"
    ),
    "join:phase3-fast-evidence": CommandSpec("diana_omics.commands.phase3_wgs.join_phase3_fast_evidence"),
    "build:phase3-fast-replication-plan": CommandSpec("diana_omics.commands.phase3_wgs.render_phase3_fast_replication_plan"),
    "build:phase3-fast-parabricks-mutect-plan": CommandSpec(
        "diana_omics.commands.phase3_wgs.render_phase3_fast_parabricks_mutect_plan"
    ),
    "build:phase3-fast-staging-plan": CommandSpec("diana_omics.commands.phase3_wgs.render_phase3_fast_staging_plan"),
    "build:panel": CommandSpec("diana_omics.commands.hrd_context.build_reference_panel"),
    "build:raw-samplesheets": CommandSpec("diana_omics.commands.raw_validation.build_raw_samplesheets"),
    "build:rosalind-hrd-packet": CommandSpec("diana_omics.commands.hrd_context.build_rosalind_hrd_packet"),
    "benchmark:sra-range": CommandSpec("diana_omics.commands.phase3_wgs.run_sra_benchmark"),
    "diagnose:pipeline": CommandSpec("diana_omics.commands.quality.diagnose_pipeline"),
    "fetch:full-reference-smoke": CommandSpec("diana_omics.commands.alignment_validation.fetch_full_reference_smoke_assets"),
    "fetch:full-wes": CommandSpec("diana_omics.commands.alignment_validation.fetch_full_wes_benchmark_assets"),
    "fetch:human-reference-smoke": CommandSpec("diana_omics.commands.alignment_validation.fetch_human_reference_smoke_assets"),
    "fetch:phase1": CommandSpec("diana_omics.commands.hrd_context.fetch_phase1"),
    "fetch:phase3-wgs": CommandSpec("diana_omics.commands.phase3_wgs.fetch_phase3_wgs_smoke_assets"),
    "fetch:production-somatic": CommandSpec("diana_omics.commands.alignment_validation.fetch_production_somatic_assets"),
    "fetch:raw-candidates": CommandSpec("diana_omics.commands.raw_validation.fetch_raw_candidate_metadata"),
    "plan:known-answer-benchmarks": CommandSpec("diana_omics.commands.known_answer.plan_known_answer_benchmarks"),
    "plan:diana-raw-handoff": CommandSpec("diana_omics.commands.diana_intake.plan_diana_raw_handoff"),
    "run:known-answer-bounded-non-dry": CommandSpec("diana_omics.commands.known_answer.run_known_answer_bounded_non_dry"),
    "run:known-answer-expanded-cohort": CommandSpec("diana_omics.commands.known_answer.run_known_answer_expanded_cohort"),
    "run:known-answer-public-findings": CommandSpec("diana_omics.commands.known_answer.run_known_answer_public_findings"),
    "run:phase3-fast-bam-qc": CommandSpec("diana_omics.commands.phase3_wgs.run_phase3_fast_bam_qc"),
    "run:phase3-fast-cnv-evidence": CommandSpec("diana_omics.commands.phase3_wgs.run_phase3_fast_cnv_evidence"),
    "run:phase3-fast-filter-mutect": CommandSpec("diana_omics.commands.phase3_wgs.run_phase3_fast_filter_mutect"),
    "run:phase3-fast-parabricks-mutect": CommandSpec(
        "diana_omics.commands.phase3_wgs.run_phase3_fast_parabricks_mutect"
    ),
    "run:phase3-fast-sv-evidence": CommandSpec("diana_omics.commands.phase3_wgs.run_phase3_fast_sv_evidence"),
    "export:phase3-fast-small-variants": CommandSpec(
        "diana_omics.commands.phase3_wgs.export_phase3_fast_small_variant_artifacts"
    ),
    "publish:phase3-fast-final-evidence": CommandSpec(
        "diana_omics.commands.phase3_wgs.publish_phase3_fast_final_evidence"
    ),
    "replicate:phase3-fast-inputs": CommandSpec("diana_omics.commands.phase3_wgs.replicate_phase3_fast_inputs"),
    "stage:phase3-fast-inputs": CommandSpec("diana_omics.commands.phase3_wgs.stage_phase3_fast_inputs"),
    "stage:phase3-fast-deterministic-report": CommandSpec(
        "diana_omics.commands.phase3_wgs.stage_phase3_fast_deterministic_report"
    ),
    "smoke:alignment": CommandSpec("diana_omics.commands.alignment_validation.run_alignment_smoke"),
    "smoke:full-reference": CommandSpec("diana_omics.commands.alignment_validation.run_full_reference_smoke"),
    "benchmark:full-wes": CommandSpec("diana_omics.commands.alignment_validation.run_full_wes_benchmark"),
    "smoke:human-reference": CommandSpec("diana_omics.commands.alignment_validation.run_human_reference_smoke"),
    "validate:phase3-wgs": CommandSpec("diana_omics.commands.phase3_wgs.run_phase3_wgs_smoke"),
    "verify:phase3-fast-aws-execute": CommandSpec("diana_omics.commands.phase3_wgs.verify_phase3_fast_aws_execute"),
    "verify:phase3-fast-gpu-smoke": CommandSpec("diana_omics.commands.phase3_wgs.verify_phase3_fast_gpu_smoke"),
    "verify:phase3-fast-staged-inputs": CommandSpec("diana_omics.commands.phase3_wgs.verify_phase3_fast_staged_inputs"),
    "smoke:production-somatic": CommandSpec("diana_omics.commands.alignment_validation.run_production_somatic_smoke"),
    "smoke:raw": CommandSpec("diana_omics.commands.raw_validation.run_raw_smoke"),
    "stage:diana-raw": CommandSpec("diana_omics.commands.diana_intake.stage_diana_raw_analysis"),
    "triage:rosalind-hrd-readiness": CommandSpec("diana_omics.commands.hrd_context.triage_rosalind_hrd_readiness"),
    "verify:clinical-assay-boundaries": CommandSpec("diana_omics.commands.clinical_readiness.verify_clinical_assay_boundaries"),
    "verify:clinical-change-control": CommandSpec("diana_omics.commands.clinical_readiness.verify_clinical_change_control"),
    "verify:clinical-qc-thresholds": CommandSpec("diana_omics.commands.clinical_readiness.verify_clinical_qc_thresholds"),
    "verify:clinical-signoff-workflow": CommandSpec("diana_omics.commands.clinical_readiness.verify_clinical_signoff_workflow"),
    "verify:clinical-validation-evidence-links": CommandSpec(
        "diana_omics.commands.clinical_readiness.verify_clinical_validation_evidence_links"
    ),
    "verify:clinical-validation-packet": CommandSpec("diana_omics.commands.clinical_readiness.verify_clinical_validation_packet"),
    "verify:clinicalization-readiness-rollup": CommandSpec(
        "diana_omics.commands.clinical_readiness.verify_clinicalization_readiness_rollup"
    ),
    "verify:cnv-loh-readiness": CommandSpec("diana_omics.commands.clinical_readiness.verify_cnv_loh_readiness"),
    "verify:diana-raw": CommandSpec("diana_omics.commands.diana_intake.verify_diana_raw"),
    "verify:hrd-interpretation-readiness": CommandSpec(
        "diana_omics.commands.clinical_readiness.verify_hrd_interpretation_readiness"
    ),
    "verify:known-answer-asset-acquisition": CommandSpec(
        "diana_omics.commands.known_answer.verify_known_answer_asset_acquisition"
    ),
    "verify:known-answer-asset-approval-packet": CommandSpec(
        "diana_omics.commands.known_answer.verify_known_answer_asset_approval_packet"
    ),
    "verify:known-answer-asset-integrity": CommandSpec("diana_omics.commands.known_answer.verify_known_answer_asset_integrity"),
    "verify:known-answer-benchmark-manifests": CommandSpec(
        "diana_omics.commands.known_answer.verify_known_answer_benchmark_manifests"
    ),
    "verify:known-answer-checksum-policy": CommandSpec("diana_omics.commands.known_answer.verify_known_answer_checksum_policy"),
    "verify:known-answer-public-findings": CommandSpec(
        "diana_omics.commands.known_answer.verify_known_answer_public_findings"
    ),
    "verify:known-answer-readiness": CommandSpec("diana_omics.commands.known_answer.verify_known_answer_readiness"),
    "verify:known-answer-sample-pull-plan": CommandSpec(
        "diana_omics.commands.known_answer.verify_known_answer_sample_pull_plan"
    ),
    "verify:orthogonal": CommandSpec("diana_omics.commands.known_answer.verify_orthogonal_validation"),
    "verify:outputs": CommandSpec("diana_omics.commands.quality.verify_outputs"),
    "verify:phase3-outputs": CommandSpec("diana_omics.commands.quality.verify_outputs", "verify_phase3_outputs"),
    "verify:plan": CommandSpec("diana_omics.commands.quality.verify_plan"),
    "verify:sv-caller-readiness": CommandSpec("diana_omics.commands.clinical_readiness.verify_sv_caller_readiness"),
}

TASK_ONLY_MODULES: tuple[str, ...] = (
    "diana_omics.commands.known_answer.run_known_answer_benchmark",
)

COMMAND_FAMILIES: tuple[CommandFamily, ...] = (
    CommandFamily(
        "HRD and RNA context",
        "Build processed public context and reviewer-facing HRD/RNA evidence.",
        (
            "fetch:phase1",
            "build:panel",
            "analyze:hrd",
            "analyze:lehmann",
            "analyze:rna",
            "build:packet",
            "build:rosalind-hrd-packet",
            "triage:rosalind-hrd-readiness",
        ),
    ),
    CommandFamily(
        "Raw public validation",
        "Prepare public raw-data candidates and prove basic FASTQ/tooling mechanics.",
        (
            "fetch:raw-candidates",
            "audit:raw-tools",
            "build:raw-samplesheets",
            "smoke:raw",
        ),
    ),
    CommandFamily(
        "Alignment and representative validation",
        "Exercise alignment, reference, somatic-calling, and full-WES validation ladders.",
        (
            "build:alignment-smoke",
            "smoke:alignment",
            "fetch:human-reference-smoke",
            "smoke:human-reference",
            "fetch:full-reference-smoke",
            "smoke:full-reference",
            "fetch:production-somatic",
            "smoke:production-somatic",
            "fetch:full-wes",
            "benchmark:full-wes",
        ),
    ),
    CommandFamily(
        "Phase 3 WGS",
        "Run full-source WGS fetch, stage-local validation, and range-read experiments.",
        (
            "fetch:phase3-wgs",
            "build:phase3-fast-bam-qc-plan",
            "build:phase3-fast-input-manifest",
            "build:phase3-fast-cache-manifest",
            "build:phase3-fast-crosscheck-materialization-plan",
            "build:phase3-fast-cnv-evidence-plan",
            "build:phase3-fast-filter-mutect-plan",
            "build:phase3-fast-parabricks-mutect-plan",
            "build:phase3-fast-replication-plan",
            "build:phase3-fast-staging-plan",
            "build:phase3-fast-sv-evidence-plan",
            "join:phase3-fast-evidence",
            "replicate:phase3-fast-inputs",
            "run:phase3-fast-bam-qc",
            "run:phase3-fast-cnv-evidence",
            "run:phase3-fast-filter-mutect",
            "run:phase3-fast-parabricks-mutect",
            "run:phase3-fast-sv-evidence",
            "export:phase3-fast-small-variants",
            "publish:phase3-fast-final-evidence",
            "stage:phase3-fast-inputs",
            "stage:phase3-fast-deterministic-report",
            "validate:phase3-wgs",
            "verify:phase3-fast-aws-execute",
            "verify:phase3-fast-gpu-smoke",
            "verify:phase3-fast-staged-inputs",
            "benchmark:sra-range",
            "phase3:stage:fetch:tumor",
            "phase3:stage:fetch:normal",
            "phase3:stage:ref",
            "phase3:stage:align:tumor",
            "phase3:stage:align:normal",
            "phase3:stage:downstream",
        ),
    ),
    CommandFamily(
        "Known-answer validation",
        "Plan and verify truth-set assets before treating output metrics as evidence.",
        (
            "plan:known-answer-benchmarks",
            "benchmark:known-answer",
            "run:known-answer-public-findings",
            "run:known-answer-bounded-non-dry",
            "run:known-answer-expanded-cohort",
            "verify:orthogonal",
            "verify:known-answer-readiness",
            "verify:known-answer-sample-pull-plan",
            "verify:known-answer-public-findings",
            "verify:known-answer-asset-acquisition",
            "verify:known-answer-asset-integrity",
            "verify:known-answer-checksum-policy",
            "verify:known-answer-asset-approval-packet",
            "verify:known-answer-benchmark-manifests",
        ),
    ),
    CommandFamily(
        "Clinical readiness",
        "Check clinicalization gates, QC locks, evidence links, change control, and signoff.",
        (
            "verify:clinical-assay-boundaries",
            "verify:clinical-change-control",
            "verify:clinical-qc-thresholds",
            "verify:clinical-signoff-workflow",
            "verify:clinical-validation-evidence-links",
            "verify:clinical-validation-packet",
            "verify:clinicalization-readiness-rollup",
            "verify:cnv-loh-readiness",
            "verify:hrd-interpretation-readiness",
            "verify:sv-caller-readiness",
        ),
    ),
    CommandFamily(
        "Diana intake",
        "Create, verify, and stage the future Diana raw-data handoff contract.",
        (
            "build:diana-template",
            "build:diana-samplesheet-from-delivery",
            "plan:diana-raw-handoff",
            "verify:diana-raw",
            "stage:diana-raw",
        ),
    ),
    CommandFamily(
        "Quality and diagnostics",
        "Run developer quality checks, output verifiers, and pipeline diagnostics.",
        (
            "py:format",
            "py:format:check",
            "py:lint",
            "py:typecheck",
            "py:test",
            "typecheck",
            "test",
            "verify:plan",
            "verify:plan:online",
            "verify:outputs",
            "verify:phase3-outputs",
            "diagnose:pipeline",
        ),
    ),
    CommandFamily(
        "Local Nextflow",
        "Launch local or Docker Nextflow profiles through the same Python task surface.",
        (
            "nf:quick",
            "nf:full-wes",
            "nf:phase3-fetch:dev",
            "nf:phase3-fetch:full",
            "nf:phase3-sra-benchmark",
            "nf:phase3-wgs-fast:stub",
            "nf:phase3-wgs:stub",
            "nf:docker:phase3-wgs:stub",
            "nf:phase3-wgs:dev",
            "nf:phase3-wgs:full",
            "nf:phase3-wgs:monolith:full",
            "nf:known-answer-public-findings",
            "nf:known-answer-bounded-non-dry",
            "nf:known-answer-expanded-cohort",
            "nf:all-public",
        ),
    ),
    CommandFamily(
        "AWS and deployment",
        "Manage AWS infrastructure, image deployment, Batch monitoring, and cloud Nextflow runs.",
        (
            "infra:aws:init",
            "infra:aws:fmt",
            "infra:aws:fmt:check",
            "infra:aws:validate",
            "infra:aws:use1",
            "infra:aws:use2",
            "infra:aws:plan",
            "infra:aws:apply",
            "infra:aws:plan:use1",
            "infra:aws:apply:use1",
            "infra:aws:plan:use2",
            "infra:aws:apply:use2",
            "aws:ecr:push",
            "aws:ecr:push:use1",
            "aws:ecr:push:use2",
            "aws:ecr:mirror-parabricks:use2",
            "aws:hrd-packet:cloud-submit",
            "deploy:aws",
            "nf:aws:monitor",
            "nf:aws:quick:stub",
            "nf:aws:phase3-fetch:stub",
            "nf:aws:phase3-fetch:tiny",
            "nf:aws:phase3-fetch:dev",
            "nf:aws:phase3-fetch:full",
            "nf:aws:phase3-sra-benchmark",
            "nf:aws:sra-bench:tiny",
            "nf:aws:sra-bench:matrix:2cpu",
            "nf:aws:sra-bench:matrix:4cpu",
            "nf:aws:known-answer-public-findings",
            "nf:aws:known-answer-bounded-non-dry",
            "nf:aws:known-answer-expanded-cohort",
            "nf:aws:phase3-wgs:stub",
            "nf:aws:phase3-wgs:dev",
            "nf:aws:phase3-wgs:full",
            "nf:aws:phase3-wgs:full:ondemand-large",
            "nf:aws:phase3-wgs:full:ondemand-failfast",
            "nf:aws:phase3-wgs-fast:gpu-smoke",
            "nf:aws:phase3-wgs-fast:execute",
            "nf:aws:phase3-wgs:monolith:full",
        ),
    ),
    CommandFamily(
        "Workflow aliases",
        "Run multi-step project workflows composed from lower-level commands.",
        (
            "run:all",
        ),
    ),
)


FAMILY_PACKAGES = {
    "alignment_validation",
    "clinical_readiness",
    "diana_intake",
    "hrd_context",
    "known_answer",
    "phase3_wgs",
    "quality",
    "raw_validation",
}
