# Clinical Validation Packet Template

This is a template for a future clinical-grade HRD assay validation packet. It is not a completed CLIA/CAP submission, not an approved report, and not evidence that the assay is ready for clinical interpretation.

## Current Status

- Packet status: template only.
- Clinical reporting allowed: no.
- Reportable range locked: no.
- Clinical signoff: not approved.
- Current evidence baseline: Phase 3 full-source public WGS mechanics passed on SEQC2/HCC1395.
- Current interpretation status: HRD interpretation adapters remain no-call.
- Current known-answer status: HG008 and COLO829 fixtures are planned, with thresholds not locked.

## Required Sections

The section manifest is `manifests/clinical_validation_packet_sections.csv`. The verifier writes the current packet readiness summary to `results/clinicalization/clinical_validation_packet_readiness_summary.json`.

Required domains:

- Intended use and assay claim.
- End-to-end workflow and traceability.
- Specimen and input acceptance criteria.
- Accuracy for SNV/indel, CNV/LOH, SV, signature, and integrated HRD features.
- Repeatability precision.
- Reproducibility across runs and environments.
- Limit of detection and tumor fraction sensitivity.
- Reportable range.
- Interferences, limitations, and failure modes.
- QC gates and acceptance thresholds.
- Report template and no-call language.
- Change control and versioning.
- Review approval and release signoff.

## Interpretation Boundary

Until all required validation evidence is generated, reviewed, and signed off, the only allowed conclusion is that the assay candidate is under validation. Unsupported feature classes must be reported as no-call, not negative.

Prohibited report language includes:

- Clinically diagnostic HRD positive.
- HRD deficient.
- PARP inhibitor eligible.
- Treatment recommendation.
- Companion diagnostic equivalent.

## Evidence Dependencies

The template depends on these upstream readiness checks:

- `verify:clinical-assay-boundaries`
- `verify:known-answer-readiness`
- `verify:hrd-interpretation-readiness`
- `verify:cnv-loh-readiness`
- `verify:sv-caller-readiness`

The packet can only move out of template-only status after HG008/COLO829 known-answer fixtures, production CNV/SV callers, signature/integrated HRD adapter validation, reportable-range thresholds, and reviewer signoff are complete.
