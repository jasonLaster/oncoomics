# Clinicalization Orchestration

This is the working loop for moving from public validation toward a clinical-grade HRD assay candidate. It improves readiness without depending on Diana raw files.

## Baseline

Current evidence supports public-data validation and reviewer discussion, not clinical reporting.

What is already in place:

- Phase 3 full-source SEQC2/HCC1395 WGS mechanics passed.
- The expanded known-answer cohort runs locally and in AWS Batch.
- HG008 bounded SNV/CNV checks and COLO829 BRAF V600E checks provide positive known-answer evidence.
- Clinical assay boundaries, QC threshold scaffolds, change-control triggers, validation-packet sections, and signoff roles are represented in manifests.

What is still missing:

- Full HG008 small-variant, SV, and CNV benchmarking.
- Full COLO829 SV/CNA benchmarking and purity-series sensitivity.
- Production CNV/SV/signature/HRD adapter validation.
- Reportable-range thresholds and reviewer-approved no-call policy.
- Diana raw data and metadata.

## Workstream

Work the queue in this order unless a higher-risk gap appears:

1. Keep the public validation sidecar green.
2. Promote HG008 from bounded probes to full caller-level truth benchmarking.
3. Promote COLO829 from driver guardrail to SV/CNA and purity benchmarking.
4. Add production allele-specific CNV/LOH tooling candidates and validation harnesses.
5. Add production SV caller benchmarking with `truvari` or an equivalent reciprocal-overlap workflow.
6. Add CHORD, HRDetect, scarHRD, or equivalent HRD interpretation adapters with explicit no-call behavior.
7. Lock reportable range, QC gates, and report language only after evidence exists.
8. Prepare the validation packet for reviewer signoff.

## Heartbeat Loop

Each clinicalization pass should do one small verifiable unit:

1. Inspect `git status --short`.
2. Read [../status/current-state.md](../status/current-state.md) and the latest relevant result summary.
3. Choose the smallest next readiness gap.
4. Make the change or collect evidence.
5. Run the narrowest meaningful verifier.
6. Report the change, evidence, verification, and next gap.

Do not rerun full WGS, alignment, or high-cost Batch work without explicit approval.

## Packet Scaffolding

Current clinical packet inputs:

- `manifests/clinical_validation_packet_sections.csv`
- `manifests/clinical_validation_evidence_links.csv`
- `manifests/clinical_change_control_triggers.csv`
- `manifests/clinical_signoff_workflow.csv`
- [validation-packet-template.md](validation-packet-template.md)

Useful verifiers:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-validation-packet
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-validation-evidence-links
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-change-control
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-signoff-workflow
```

Clinical reporting remains disabled until all required evidence, thresholds, and signoffs are complete.
