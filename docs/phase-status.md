# Phase Status

This file is the current operational status. It intentionally distinguishes passed mechanics, partial biological evidence, and work that still needs known-answer validation.

## Summary

| Area | Status | Meaning |
| --- | --- | --- |
| Python rewrite | Passed | Workflow logic lives in `src/diana_omics`; JS/TS scripts were removed. |
| Phase 1 processed HRD/RNA panel | Passed | Public processed data generate review tables for 28 samples. |
| Phase 2 raw WES benchmark | Passed | Full SEQC2/HCC1395 WES FASTQs, alignment, GATK Mutect2, and truth overlap run. |
| Phase 3 WGS validation | Passed for full-source public WGS | Full SEQC2/HCC1395 WGS FASTQs passed the acceptance gate; bounded subsets remain developer checks only. |
| Diana raw-data intake | Ready, waiting | Template and strict validation exist; actual Diana files are not present. |
| Orthogonal known-answer WGS validation | Partially implemented | SEQC2/HCC1395 public WES and WGS examples are verified; a 10-target HG008/COLO829/Seraseq pull plan is staged for owner review. |
| Clinical interpretation | Blocked | Requires Diana files, full-depth analysis policy, and reviewer/clinical sign-off. |

## Latest Full-Run Evidence

The latest `PYTHONPATH=src /usr/bin/python3 -m diana_omics run:all` completed with these key outputs:

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
- Phase 3 WGS validation status: `passed`.
- Phase 3 WGS completion evidence: `readPairsMode=full`, `fullSourceFastqs=true`, and `readPairsPerEnd=568040077`.
- Phase 3 WGS truth overlap: `mutectIntervalCount=295`, `passRecordsInIntervals=273`, and `exactPassTruthMatches=268`.
- Phase 3 WGS feature outputs: `coverageCnvBins=631`, `sbs96UsableSnvRecords=265`, and `svEvidenceStatus=passed`.
- Phase 3 WGS ready for Phase 4 when Diana raw arrives: `true`.
- Orthogonal public examples verified: `2` implemented, `5` planned or request-only.
- Expanded known-answer pull targets staged for review: `10`.
- Expanded known-answer public findings confirmed by current analysis: `0/10`.
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
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:panel
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:hrd
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:rna
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:lehmann
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:packet
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
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
PYTHONPATH=src /usr/bin/python3 -m diana_omics fetch:full-wes
PYTHONPATH=src /usr/bin/python3 -m diana_omics benchmark:full-wes
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
```

## Phase 3

Status: complete for full-source public WGS validation.

What passed:

- Full-source WGS FASTQ fetch and validation passed.
- Parallel alignment path is configured.
- The full-source run exercised BAM validation, Mutect2, coverage-CNV, SBS96, SV evidence, and HRD tool readiness outputs.

Known risks:

- Bounded WGS subsets can prove mechanics but do not satisfy Phase 3 completion.
- Old bounded BAM/VCF outputs must not be reused for the full-source gate; the runner checks indexed alignment counts and output timestamps before reusing expensive artifacts.
- Current CNV/SV/signature outputs are feature evidence, not final clinical-grade callers.
- The SEQC2/HCC1395 public WGS pass proves WGS-scale mechanics, not a clinical HRD assay.

Verifier:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics fetch:phase3-wgs
PYTHONPATH=src /usr/bin/python3 -m diana_omics validate:phase3-wgs
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:orthogonal
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
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
- `manifests/known_answer_sample_pull_plan.csv`
- `manifests/known_answer_public_finding_checks.csv`
- `results/clinicalization/known_answer_public_finding_execution.md`
- `results/clinicalization/known_answer_public_finding_confirmation.md`

Verifier:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:known-answer-sample-pull-plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:known-answer-public-findings
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:known-answer-public-findings
```

## Diana Intake

Status: ready, waiting on actual files.

Ready-now commands:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
```

Strict validation when files arrive:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
```

Stage a Diana-specific recompute packet:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
DIANA_RAW_ANALYSIS_ID=diana_initial_raw_recompute \
PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw
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
