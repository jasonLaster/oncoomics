# Current State

This page combines the project plan, phase status, and raw-data readiness ladder. It is intentionally short: what has passed, what is partial, what is blocked, and what should happen next.

## Summary

| Area | Status | Meaning |
| --- | --- | --- |
| Python workflow | Passed | Workflow logic lives in `src/diana_omics`; commands, verifiers, and Nextflow process glue are Python-owned. |
| Phase 1: Processed Public HRD/RNA Panel | Passed | Public processed breast-cancer data generate HRD, RNA, TNBC subtype, and reviewer tables for 28 reference-panel samples. |
| Phase 2: Raw WES and Caller Readiness | Passed | SEQC2/HCC1395 WES runs from full FASTQ through alignment, GATK Mutect2, and truth-overlap scoring. |
| Phase 3: Full Public WGS Validation | Passed for mechanics | SEQC2/HCC1395 full-source WGS exercises WGS-scale BAM, VCF, CNV-bin, SBS96, and SV-evidence outputs. |
| Phase 3B: Orthogonal Known-Answer Validation | Partially implemented | Bounded non-dry checks now confirm HG008 SNV/CNV probes and COLO829 BRAF V600E; full caller-level truth benchmarking is still open. |
| Phase 4: Diana Raw-Data Recompute | Ready, waiting | Template and strict validator exist; actual Diana files are not present. |
| Clinical interpretation | Blocked | Requires Diana data, full-depth validation, HRD policy, and reviewer signoff. |

## What We Have Shown

- HRD evidence tables can be built from public processed data while preserving caveats and label boundaries.
- TNBC subtype context can be generated beside HRD evidence without turning subtype into an HRD truth claim.
- Full WES public data can be validated, aligned, called, and compared to SEQC2/HCC1395 truth-overlap variants.
- Full-source public WGS data can generate the major evidence surfaces needed before Diana: BAM validation, small-variant VCFs, coverage-CNV bins, SBS96 summaries, and SV evidence.
- COLO829 tumor-normal BAMs recover the expected BRAF V600E melanoma driver across Illumina, PacBio, Oxford Nanopore, and phased NovaSeq public submissions.
- GIAB HG008 bounded checks confirm `40/40` simple somatic SNV truth loci and `4/4` CNV truth-interval depth directions.
- The expanded known-answer cohort runs locally and in AWS Batch.

## Latest Evidence

Key public validation numbers:

- Full WES FASTQs validated: `4`.
- Full WES exact PASS truth matches: `1122`.
- Full WES recall: `0.8585`.
- Full WES precision: `0.9842`.
- Phase 3 WGS read-pair mode: `full`.
- Phase 3 WGS full-source read pairs per end: `568040077`.
- Phase 3 WGS exact truth matches: `268`.
- Phase 3 WGS coverage-CNV bins: `631`.
- Phase 3 WGS SBS96 usable SNVs: `265`.
- Expanded known-answer cohort: `29` targets, `19` confirmations, `1` partial, `3` strict-validation gaps, `6` blockers.

Primary reports:

- `results/full_wes_benchmark/full_wes_benchmark_summary.json`
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`
- `results/clinicalization/known_answer_expanded_cohort_execution.md`
- `results/reviewer_packet.md`
- `results/diana_readiness_gate.md`

## Phase 1: Processed Public HRD/RNA Panel

Purpose:

- Build a small public breast-cancer reference panel.
- Separate positive, negative, and ambiguous HRD controls.
- Add Lehmann TNBC subtype context and RNA evidence as context, not diagnosis.

Main limitation:

Processed public labels are not clinical HRD truth. They are structured examples for reviewer discussion.

Verifier:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:hrd
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:lehmann
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
```

## Phase 2: Raw WES and Caller Readiness

Purpose:

- Prove raw FASTQ validation, alignment, duplicate marking, BAM validation, and somatic calling.
- Use SEQC2/HCC1395 truth overlap to show expected small-variant behavior.

Main limitation:

WES does not validate full-genome HRD signatures, allele-specific CNV, or SV behavior.

Verifier:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics fetch:full-wes
PYTHONPATH=src /usr/bin/python3 -m diana_omics benchmark:full-wes
```

## Phase 3: Full Public WGS Validation

Purpose:

- Prove WGS-scale mechanics on public tumor-normal data.
- Generate the major evidence outputs needed before Diana raw-data runs.

Main limitation:

SEQC2/HCC1395 proves mechanics. HG008 and COLO829 still need full caller-level truth-set benchmarking before we can call the WGS validation ladder strong.

Verifier:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics fetch:phase3-wgs
PYTHONPATH=src /usr/bin/python3 -m diana_omics validate:phase3-wgs
```

## Phase 3B: Orthogonal Known-Answer Validation

Purpose:

- Prove the pipeline recovers expected answers on independent public truth samples.
- Keep public validation beside Diana-specific work.

Current state:

- SEQC2/HCC1395 WES and WGS are implemented.
- HG008 SNV and CNV bounded probes pass.
- COLO829 BRAF V600E bounded probes pass across multiple platforms.
- HG008 SV, COLO829 SV/CNA, COLO829 purity, and Seraseq MRD remain gaps or access blockers.

Next targets:

1. Generate Diana-style HG008 small-variant, SV, and CNV callsets; compare against NIST truth.
2. Run full COLO829 tumor-normal calling and compare SV/CNA output against Zenodo truth assets.
3. Transfer/index selected COLO829 purity files and build a monotonic recall table.
4. Buy or request Seraseq ctDNA MRD material/files if MRD-like validation is required before Diana plasma data.

Verifier:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:orthogonal
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:known-answer-expanded-cohort
```

## Phase 4: Diana Raw-Data Recompute

Purpose:

- Accept Diana's raw or vendor-derived file paths.
- Validate reference build, role, pairing, modality, and file shape.
- Stage a recompute packet beside the public validation sidecar.

Required inputs:

- Tumor DNA FASTQ/BAM/CRAM, ideally tumor-normal WGS or WES.
- Matched normal DNA FASTQ/BAM/CRAM.
- RNA FASTQ/BAM/counts if available.
- Vendor VCF/CNV/SV/RNA/report files if available.
- Reference build, tumor purity, sample provenance, platform, and collection timing.

Verifier:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
```

## Continuous Quality Gates

Run before committing code or generated evidence:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:format:check
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:lint
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:typecheck
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:test
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
git diff --check
```

## Interpretation Boundary

The repo is ready for public-data validation and Diana file intake. It is not ready to make a Diana clinical HRD claim. Before interpretation, we need Diana raw data, full HG008/COLO829 truth benchmarking, robust CNV/SV/signature inputs, CHORD/scarHRD or equivalent policy, and reviewer signoff.
