# Phase Status

This file is the current operational status. It intentionally distinguishes passed mechanics, partial biological evidence, and work that still needs known-answer validation.

## Summary

| Area | Status | Meaning |
| --- | --- | --- |
| Python rewrite | Passed | Workflow logic lives in `py/src/diana_omics`; JS/TS scripts were removed. |
| Phase 1 processed HRD/RNA panel | Passed | Public processed data generate review tables for 28 samples. |
| Phase 2 raw WES benchmark | Passed | Full SEQC2/HCC1395 WES FASTQs, alignment, GATK Mutect2, and truth overlap run. |
| Phase 3 WGS smoke | Passed | Representative WGS mechanics generate BAM, VCF, CNV, SBS96, and SV evidence outputs. |
| Diana raw-data intake | Ready, waiting | Template and strict validation exist; actual Diana files are not present. |
| Orthogonal known-answer WGS validation | Planned | HG008 and COLO829 should be added before interpreting Diana WGS. |
| Clinical interpretation | Blocked | Requires Diana files, full-depth analysis policy, and reviewer/clinical sign-off. |

## Latest Full-Run Evidence

The latest `bun run run:all` completed with these key outputs:

- `results/full_wes_benchmark/full_wes_benchmark_summary.json`
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`
- `results/hrd_analysis_summary.json`
- `results/reviewer_packet_summary.json`
- `results/diana_raw_intake/intake_readiness_summary.json`

Important values:

- Full WES benchmark status: `passed`.
- Full WES truth variants depth eligible: `1307`.
- Full WES exact PASS truth matches: `1122`.
- Full WES exact PASS recall: `0.8585`.
- Full WES exact PASS precision: `0.9842`.
- Phase 3 WGS smoke status: `passed`.
- Phase 3 WGS coverage-CNV bins: `631`.
- Phase 3 WGS ready for Phase 4 when Diana raw arrives: `true`.
- Diana raw intake status: `template_ready`.
- Diana raw intake ready to interpret: `false`.

## Phase 1

Status: complete.

What passed:

- Public catalog fetches complete.
- Reference panel has positive, negative, and ambiguous categories.
- HRD evidence, allele-state, scar/signature, RNA context, failure mode, and reviewer packet tables are generated.

What this does not prove:

- It does not prove clinical HRD status for Diana.
- It does not run HRDetect, CHORD, scarHRD, FACETS, ASCAT, or PURPLE.
- It does not resolve biallelic loss from raw allele-specific copy number.

Verifier:

```sh
bun run build:panel
bun run analyze:hrd
bun run analyze:rna
bun run build:packet
bun run verify:outputs
```

## Phase 2

Status: complete for representative raw WES.

What passed:

- Raw candidate metadata fetched.
- FASTQ smoke validation passed.
- Local alignment smoke passed.
- Partial human-reference and full-reference smoke tests passed.
- Production-style GATK Mutect2 smoke passed.
- Full WES benchmark passed against SEQC2/HCC1395 truth-overlap intervals.

Known risks:

- BQSR is deferred.
- Resource choices are intentionally minimal for local validation.
- WES does not cover full-genome HRD signature, CNV, or SV behavior.

Verifier:

```sh
bun run fetch:full-wes
bun run benchmark:full-wes
bun run verify:outputs
```

## Phase 3

Status: complete for representative WGS smoke.

What passed:

- Representative WGS FASTQs fetched.
- Parallel alignment path ran.
- BAM validation passed.
- WGS Mutect2 smoke output exists.
- Coverage-CNV bins, SBS96 matrix, SV evidence, and HRD tool readiness summaries exist.

Known risks:

- Downsampled WGS can prove mechanics but cannot prove full-depth clinical HRD sensitivity.
- Current CNV/SV/signature outputs are smoke evidence, not final clinical-grade callers.
- `0` PASS calls in the WGS smoke reflects the selected intervals/downsampled smoke, not a biological conclusion.

Verifier:

```sh
bun run fetch:phase3-wgs
bun run smoke:phase3-wgs
bun run verify:outputs
```

## Orthogonal Validation

Status: planned and documented.

Why it matters:

The existing workflow finishes and produces structured outputs. The next important question is whether it returns the correct answer on independent full public samples.

Next targets:

- HG008 from NIST Cancer Genome in a Bottle for tumor/normal WGS SNV/indel/SV/CNV truth.
- COLO829/COLO829BL for independent tumor/normal WGS, melanoma UV signature, BRAF sanity check, SV/CNA truth, and tumor-purity stress testing.
- Seraseq ctDNA MRD Panel Mix for MRD positive/negative dilution validation if request-only files or material are obtained.

Planning artifacts:

- `docs/ORTHOGONAL_VALIDATION_SAMPLES.md`
- `manifests/orthogonal_validation_candidates.csv`

## Diana Intake

Status: ready, waiting on actual files.

Ready-now commands:

```sh
bun run build:diana-template
bun run verify:diana-raw
```

Strict validation when files arrive:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
bun run verify:diana-raw
```

Stage a Diana-specific recompute packet:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
DIANA_RAW_ANALYSIS_ID=diana_initial_raw_recompute \
bun run stage:diana-raw
```

Blocked items:

- Actual Diana file paths.
- Confirmed tumor-normal pairing.
- Reference build.
- Tumor purity and sample provenance.
- Vendor report files, if any.
- Reviewer-approved interpretation thresholds.

## Recommended Next Work

1. Implement HG008 truth-set validation.
2. Implement COLO829 truth-set validation and purity stress test.
3. Add a real RNA-seq quantification/fusion-ready path for HG008 or HCC1395 RNA.
4. Decide whether to request/purchase Seraseq ctDNA MRD data.
5. Only then run Diana raw files through the staged recompute path.
