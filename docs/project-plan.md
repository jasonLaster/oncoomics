# Project Plan

The plan is organized around evidence gates. A phase is complete only when it produces artifacts that a reviewer can inspect and a verifier can re-check.

## Goal

Be ready to recompute Diana's HRD-relevant findings from actual raw data while keeping public validation results beside the Diana-specific run.

Implementation assumptions:

- Python owns workflow orchestration and generated evidence tables.
- Full-depth HRD interpretation should eventually connect to established tools such as CHORD and scarHRD instead of relying only on local smoke summaries.

The end state should answer:

- Did the files arrive in a valid shape?
- Were tumor and normal paired correctly?
- Did alignment, calling, CNV/SV/signature, and RNA context steps run?
- Did known public reference samples produce known answers?
- Which findings are strong enough for reviewer discussion, and which are only exploratory?

## Phase 1: Processed Public HRD/RNA Panel

Status: complete for processed-data triage.

Purpose:

- Build a small public breast cancer reference panel.
- Separate positive, negative, and ambiguous HRD controls.
- Generate reviewer tables without pretending processed TCGA-like data are raw clinical files.

Primary artifacts:

- `manifests/hrd_reference_panel.csv`
- `results/hrd_event_table.csv`
- `results/allele_state_table.csv`
- `results/scar_signature_table.csv`
- `results/hrd_predictions.csv`
- `results/rna_subtype_context.csv`
- `results/reviewer_packet.md`

Verifier:

```sh
bun run build:panel
bun run analyze:hrd
bun run analyze:rna
bun run build:packet
bun run verify:outputs
```

Main limitation:

Processed public labels are not a clinical HRD truth source. They are a structured reasoning panel.

## Phase 2: Raw WES and Caller Readiness

Status: complete for representative WES mechanics.

Purpose:

- Prove that raw FASTQ validation, alignment, duplicate marking, BAM validation, and somatic calling can run locally.
- Use the SEQC2/HCC1395 truth overlap benchmark to show that the caller produces expected small-variant answers.

Primary artifacts:

- `manifests/full_wes_benchmark_samplesheet.csv`
- `results/full_wes_benchmark/full_wes_benchmark_summary.json`
- `results/full_wes_benchmark/truth_overlap_benchmark_summary.json`

Latest evidence:

- Full WES FASTQs validated: 4.
- BAM validation status: passed.
- Depth-eligible truth variants: 1307.
- Exact PASS truth matches: 1122.
- Exact PASS recall: 0.8585.
- Exact PASS precision: 0.9842.

Verifier:

```sh
bun run fetch:full-wes
bun run benchmark:full-wes
bun run verify:outputs
```

Main limitation:

This is WES small-variant readiness, not full WGS HRD interpretation.

## Phase 3: Full Public WGS Validation

Status: in progress for full-source WGS validation.

Purpose:

- Prove that full-source representative WGS FASTQs can flow through validation, alignment, small-variant calling, coverage-CNV bins, SBS96 summaries, and SV evidence summaries.
- Confirm parallel CPU usage knobs exist before Diana raw-data runs.

Primary artifacts:

- `manifests/phase3_wgs_smoke_samplesheet.csv`
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`
- `results/phase3_wgs_smoke/coverage_cnv_bins.csv`
- `results/phase3_wgs_smoke/wgs_sbs96_matrix.csv`
- `results/phase3_wgs_smoke/sv_evidence_summary.csv`

Latest evidence:

- Completion now requires `readPairsMode=full`.
- Bounded subsets are developer checks and fail final verification.
- Full-run values are recorded in `results/phase3_wgs_smoke/phase3_wgs_summary.json`.

Verifier:

```sh
bun run fetch:phase3-wgs
bun run validate:phase3-wgs
bun run verify:outputs
```

Main limitation:

The SEQC2/HCC1395 full WGS run is a representative public validation example, not a final clinical HRD truth set. It should still be strengthened with HG008 and COLO829 truth-set runs.

## Phase 3B: Orthogonal Known-Answer Validation

Status: planned.

Purpose:

Prove correctness on one or more full public truth sets before Diana data arrives.

Recommended order:

1. HG008 tumor/normal WGS from NIST Cancer Genome in a Bottle.
2. COLO829/COLO829BL tumor/normal WGS from ENA and Zenodo truth files.
3. Seraseq ctDNA MRD Panel Mix if a true MRD dilution answer is needed before Diana plasma files arrive.

Planned gates:

- HG008 SNV/indel calls overlap the NIST v0.3 small-variant truth set inside benchmark regions.
- HG008 SV/CNV calls overlap the NIST v0.5 SV/CNV truth set.
- COLO829 recovers expected BRAF/UV-signature biology and matches SV/CNV truth.
- COLO829 purity series shows monotonic degradation with lower tumor fraction.
- Seraseq 0 percent tumor is negative and positive dilutions are positive, if files are obtained.

Primary planning artifacts:

- `docs/orthogonal-validation-samples.md`
- `manifests/orthogonal_public_examples.csv`
- `manifests/orthogonal_validation_candidates.csv`

Verifier:

```sh
bun run verify:orthogonal
```

## Phase 4: Diana Raw-Data Recompute

Status: ready for input, blocked on actual files.

Purpose:

Accept Diana's file paths and metadata, validate them strictly, stage a recompute packet, and run the same evidence workflow beside public validation.

Required inputs:

- Tumor DNA FASTQ/BAM/CRAM, ideally tumor-normal WGS or WES.
- Matched normal DNA FASTQ/BAM/CRAM.
- RNA FASTQ/BAM/counts if available.
- Reference build and platform metadata.
- Tumor purity, sample provenance, and timing.
- Any vendor VCF/CNV/SV/RNA/report files.

Verifier:

```sh
bun run build:diana-template
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run verify:diana-raw
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run stage:diana-raw
```

Exit criteria:

- Diana samplesheet validates.
- Diana recompute packet is staged.
- Public validation sidecar remains green.
- Reviewer signs off on interpretation policy.
- No clinical claim is made from open-source output alone.

## Continuous Quality Gates

Run before committing changes:

```sh
bun run py:format
bun run py:lint
bun run py:format:check
bun run py:typecheck
bun run py:test
python3 -m compileall -q py/src py/tests
bun run verify:outputs
git diff --check
```
