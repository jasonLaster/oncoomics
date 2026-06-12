# Clinicalization Orchestration

This runbook is the working loop for moving from the current public WGS validation pipeline toward a clinical-grade HRD assay candidate. It is intentionally separate from the Diana-specific handoff: the work here should improve general clinical readiness without depending on Diana raw files.

## Current Baseline

The latest completed public validation packet is local at:

- `artifacts/phase3_wgs_selective5/`

The synced S3 result location is:

- `s3://diana-omics-results-172630973301-us-east-1/runs/phase3_wgs/`

Key evidence from that packet:

- Phase 3 WGS validation status: `passed`
- Full-source FASTQs: `true`
- Read-pair mode: `full`
- Read pairs per end: `568040077`
- Mutect2 intervals: `295`
- PASS calls in intervals: `273`
- Exact PASS truth matches: `268`
- Coverage CNV bins: `631`
- SBS96 usable SNVs: `265`
- SV evidence status: `passed`
- Phase 3 ready for Phase 4 when Diana raw arrives: `true`

This proves WGS-scale mechanics. It does not prove a clinical HRD assay.

The current clinicalization readiness rollup is local at:

- `results/clinicalization/clinicalization_readiness_rollup.json`

## Clinicalization Workstream

Work the queue in this order unless current evidence shows a higher-risk gap.

1. Lock the completed public WGS validation as a durable evidence baseline.
2. Promote fine-grained S3 validation caches and post-validation context staging into reusable pipeline code instead of ad hoc Batch scripts.
3. Add production allele-specific CNV/LOH tooling candidates and a validation harness.
4. Add production SV caller VCF/BEDPE tooling candidates and a validation harness.
5. Add CHORD/HRDetect/scarHRD-style interpretation adapters with locked thresholds and explicit no-call behavior.
6. Add independent known-answer truth sets, starting with HG008 and COLO829/COLO829BL.
7. Define the clinical assay claim, reportable range, QC gates, and report language boundaries.
8. Prepare a CLIA/CAP validation packet template: accuracy, precision, LoD, reproducibility, reportable range, failure modes, and change control.

## Heartbeat Loop

Each heartbeat turn should do one small, verifiable unit of work:

1. Inspect current repo state with `git status --short`.
2. Read this file plus `docs/phase-status.md`, `docs/project-plan.md`, and the latest relevant result summary.
3. Choose the next smallest clinicalization step that does not require Diana raw files.
4. Make the change or collect the evidence.
5. Run the narrowest meaningful verification.
6. Report:
   - what changed
   - evidence inspected
   - verification command/output
   - remaining next step
   - whether the heartbeat should continue

Do not rerun full WGS, alignment, or high-cost Batch work without explicit user approval. Prefer local code/docs/tests and small public-context checks until a concrete implementation requires a cloud run.

## Current Next Step

The completed Phase 3 public WGS baseline has been locked into the status docs. Next, promote the lessons from the selective3/selective4/selective5 recovery into reusable code:

- Make post-validation continuation a first-class runner mode. Done locally as `phase3_post_validation`.
- Stage required cBioPortal/Xena/catalog context explicitly. Done locally for `phase3_post_validation`.
- Reuse persisted Phase 3 WGS validation artifacts rather than redoing BAM scans. Done locally for samtools/CNV/SV summaries and Mutect2/FilterMutectCalls outputs.
- Add production allele-specific CNV/LOH tooling candidates and a validation harness. Started locally with `manifests/allele_specific_cnv_tool_candidates.csv` and `verify:cnv-loh-readiness`.
- Add production SV caller VCF/BEDPE tooling candidates and a validation harness. Started locally with `manifests/sv_caller_tool_candidates.csv` and `verify:sv-caller-readiness`.
- Add CHORD/HRDetect/scarHRD-style interpretation adapter scaffolding with explicit no-call behavior. Started locally with `manifests/hrd_interpretation_adapters.csv` and `verify:hrd-interpretation-readiness`.
- Add independent HG008 and COLO829/COLO829BL known-answer fixture scaffolding. Started locally with `manifests/clinical_known_answer_fixtures.csv` and `verify:known-answer-readiness`.
- Add dry-run HG008 and COLO829/COLO829BL benchmark-runner plans. Started locally with `manifests/known_answer_benchmark_plan.csv` and `plan:known-answer-benchmarks`.
- Define the clinical assay claim, reportable range, QC gates, and report language boundaries. Started locally with `manifests/clinical_assay_claim_boundaries.csv`, `manifests/clinical_qc_threshold_locks.csv`, `verify:clinical-assay-boundaries`, and `verify:clinical-qc-thresholds`.
- Prepare a CLIA/CAP-style validation packet template covering accuracy, precision, LoD, reproducibility, reportable range, failure modes, change control, and signoff. Started locally with `manifests/clinical_validation_packet_sections.csv`, `manifests/clinical_validation_evidence_links.csv`, `manifests/clinical_change_control_triggers.csv`, `manifests/clinical_signoff_workflow.csv`, `docs/clinical-validation-packet-template.md`, `verify:clinical-validation-packet`, `verify:clinical-validation-evidence-links`, `verify:clinical-change-control`, and `verify:clinical-signoff-workflow`.

The immediate target is now monitoring the clinicalization readiness rollup and acting only when a gate changes. The rollup summarizes remaining approval gates across known-answer assets, benchmark execution, QC thresholds, validation packet evidence, change control, signoff, and clinical reporting boundaries. Signoff workflow scaffolding is defined locally for assay owner, bioinformatics owner, clinical scientist, quality reviewer, and laboratory director roles, but all decisions are pending and release remains disabled. Change-control/revalidation triggers are defined locally for workflow, reference, input, caller, threshold, model, report-language, benchmark-asset, packet, and signoff changes, but all clinical release remains disabled. Validation-packet evidence linking maps every CLIA/CAP template section to the readiness summaries that block it, but all packet sections remain locked. Reportable-range/QC threshold locking machinery is defined locally with all thresholds draft/not locked; the known-answer benchmark approval packet still waits for owner review. Asset acquisition planning, checksum capture policy, and approval-packet summaries keep raw upload, execution, and clinical use disabled until explicit approval plus source-published or verified local checksums. Do not start those benchmark runs without explicit approval.
