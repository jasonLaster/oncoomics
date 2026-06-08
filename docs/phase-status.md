# Phase Status

This file is the current operational status. It intentionally distinguishes passed mechanics, partial biological evidence, and work that still needs known-answer validation.

## Summary

| Area | Status | Meaning |
| --- | --- | --- |
| Python rewrite | Passed | Workflow logic lives in `py/src/diana_omics`; JS/TS scripts were removed. |
| Phase 1 processed HRD/RNA panel | Passed | Public processed data generate review tables for 28 samples. |
| Phase 2 raw WES benchmark | Passed | Full SEQC2/HCC1395 WES FASTQs, alignment, GATK Mutect2, and truth overlap run. |
| Phase 3 WGS validation | In progress for full-source run | Full SEQC2/HCC1395 WGS FASTQs are the acceptance gate; bounded subsets are developer checks only. |
| Diana raw-data intake | Ready, waiting | Template and strict validation exist; actual Diana files are not present. |
| Orthogonal known-answer WGS validation | Partially implemented | SEQC2/HCC1395 public WES and WGS examples are verified; HG008 and COLO829 remain planned known-answer gates. |
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
- Phase 3 WGS validation status: pending full-source rerun in the current pass.
- Phase 3 WGS completion requires `readPairsMode=full` and `fullSourceFastqs=true`.
- Phase 3 WGS ready for Phase 4 only after the full-source gate passes.
- Orthogonal public examples verified: `2` implemented, `5` planned or request-only.
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

Status: in progress for full-source public WGS validation.

What passed:

- Full-source WGS FASTQ fetch and validation are the active gate.
- Parallel alignment path is configured.
- Bounded developer subsets have exercised BAM, Mutect2, coverage-CNV, SBS96, SV evidence, and HRD tool readiness outputs.

Known risks:

- Bounded WGS subsets can prove mechanics but do not satisfy Phase 3 completion.
- Old bounded BAM/VCF outputs must not be reused for the full-source gate; the runner checks indexed alignment counts and output timestamps before reusing expensive artifacts.
- Current CNV/SV/signature outputs are feature evidence, not final clinical-grade callers.
- Truth-overlap status must be read from the full-source `phase3_wgs_summary.json` after the run.

Verifier:

```sh
bun run fetch:phase3-wgs
bun run validate:phase3-wgs
bun run verify:orthogonal
bun run verify:outputs
```

## Orthogonal Validation

Status: partially implemented and documented.

Why it matters:

The existing workflow finishes and produces structured outputs. `verify:orthogonal` now checks that the TS-era SEQC2/HCC1395 full public examples remain implemented in Python and that the independent full public samples are documented as known-answer gates.

Implemented now:

- SEQC2/HCC1395 full WES benchmark.
- SEQC2/HCC1395 Phase 3 WGS public FASTQ workflow, with full-source mode as the required acceptance gate.

Next targets:

- HG008 from NIST Cancer Genome in a Bottle for tumor/normal WGS SNV/indel/SV/CNV truth.
- COLO829/COLO829BL for independent tumor/normal WGS, melanoma UV signature, BRAF sanity check, SV/CNA truth, and tumor-purity stress testing.
- Seraseq ctDNA MRD Panel Mix for MRD positive/negative dilution validation if request-only files or material are obtained.

Planning artifacts:

- `docs/orthogonal-validation-samples.md`
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
