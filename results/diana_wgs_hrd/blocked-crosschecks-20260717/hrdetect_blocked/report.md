# HRDetect — blocked method report

- execution_status: `not_run`
- evidence_status: `blocked`
- interpretation_status: `no_call`
- classification_authorization: `none`
- patient_result: `none`
- generated_at: `2026-07-17T19:30:00+00:00`

The method was not run. This artifact contains no patient result, reports no inferred result, and authorizes no HRD classification.

## Alias scope

`subject01_tumor`, `subject01_normal`

No direct identifiers, source object names, or patient-derived values are included.

## Intended computation — not executed

- Use a formally selected and pinned GRCh38 HRDetect implementation with validated somatic small-variant, structural-variant, and allele-specific copy-number inputs.
- Compute the six HRDetect features: microhomology-mediated deletion proportion, LOH/TAI/LST scar score, SBS3, SBS8, rearrangement signature 3, and rearrangement signature 5.
- Apply the selected fixed model and calibration policy to produce a probability, while withholding classification unless local validation and authorization gates pass.

## Exact prerequisites

- A formally selected implementation, model, reference build, signature definitions, calibration cohort, and reporting threshold.
- An alias-only production somatic SNV and indel VCF plus index, a production structural-variant VCF, and validated allele-specific segmentation and LOH evidence.
- Exact GRCh38 reference and signature resource identities bound to SHA-256.
- A validated microhomology feature path and all six model features produced under one locked contract.
- Every transitive runtime and data dependency pinned by immutable digest with license and intended-use review, SBOM, and provenance.
- Known-answer reproduction and locked QC, calibration, threshold, and change-control authorization.

## Current blockers

- No HRDetect route, contract, digest-pinned runtime, or validated parser has been selected.
- The required production structural-variant, allele-specific LOH and scar, and microhomology feature paths are not available under an approved contract.
- The candidate OICR workflow is GRCh38-capable but depends on site-specific modules and paths, is not digest-portable, and has no detected repository license.
- The public GPL-licensed implementation hard-codes hg19 and cohort-standardizes features, so it is not a reproducible GRCh38 single-sample path.
- No known-answer calibration, local performance limits, threshold, intended-use determination, or classification authorization is locked.

## Next gate

Select the implementation, model, signature versions, reference, and calibration cohort; resolve license and intended use; pin every runtime and data dependency; generate validated SNV, indel, SV, copy-number, LOH, and microhomology inputs; then reproduce known-answer performance and lock the reporting threshold before execution or interpretation.

## Primary sources

- [OICR hrDetect 1.8.0](https://github.com/oicr-gsi/hrDetect/tree/5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35) — `5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35`
- [OICR hrDetect WDL](https://github.com/oicr-gsi/hrDetect/blob/5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35/hrDetect.wdl) — `5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35`
- [Public HRDetect pipeline](https://github.com/eyzhao/hrdetect-pipeline/tree/32e609f0479780e2072bb4b0c39190660d7eb634) — `32e609f0479780e2072bb4b0c39190660d7eb634`
- [Original HRDetect method](https://www.nature.com/articles/nm.4292) — `doi:10.1038/nm.4292`

## Interpretation boundary

Execution remains `not_run`; evidence remains `blocked`; interpretation remains `no_call`; classification authorization remains `none`. No patient result exists in this report or its manifest.
