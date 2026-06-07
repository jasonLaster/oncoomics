# Raw Data Readiness

This project validates raw-data mechanics before Diana's files arrive. The current ladder starts with small public data and climbs toward full WES/WGS known-answer validation.

## What Is Already Working

### FASTQ Intake

Command:

```sh
bun run fetch:raw-candidates
bun run build:raw-samplesheets
bun run smoke:raw
```

Purpose:

- Validate representative FASTQ metadata.
- Confirm paired-end read structure.
- Produce small smoke summaries.

Primary outputs:

- `manifests/raw_representative_panel.csv`
- `manifests/raw_smoke_samplesheet.csv`
- `results/raw_smoke/fastq_smoke_summary.json`

### Local Alignment Smoke

Command:

```sh
bun run build:alignment-smoke
bun run smoke:alignment
```

Purpose:

- Confirm FASTQ-to-BAM mechanics.
- Check read groups, coordinate sorting, BAM indexing, and mapped-read counts.

Primary outputs:

- `manifests/alignment_smoke_samplesheet.csv`
- `results/alignment_smoke/bam_validation_summary.json`

### Human Reference Smoke

Command:

```sh
bun run fetch:human-reference-smoke
bun run smoke:human-reference
bun run fetch:full-reference-smoke
bun run smoke:full-reference
```

Purpose:

- Confirm the workflow can use real human reference assets.
- Exercise hg38/hg19 compatibility boundaries.
- Produce a tiny caller-readiness VCF contract.

Primary outputs:

- `manifests/human_reference_smoke_samplesheet.csv`
- `manifests/full_reference_smoke_samplesheet.csv`
- `results/human_reference_smoke/*`
- `results/full_reference_smoke/*`

### Production-Style Somatic Smoke

Command:

```sh
bun run fetch:production-somatic
bun run smoke:production-somatic
```

Purpose:

- Exercise Java/GATK.
- Run MarkDuplicates, Mutect2, FilterMutectCalls, and related summaries on bounded data.

Primary outputs:

- `manifests/production_somatic_smoke_samplesheet.csv`
- `results/production_somatic_smoke/production_somatic_summary.json`

### Full WES Benchmark

Command:

```sh
bun run fetch:full-wes
bun run benchmark:full-wes
```

Purpose:

- Validate full SEQC2/HCC1395 WES FASTQs.
- Align, duplicate-mark, and call somatic variants.
- Compare against depth-eligible truth-overlap variants.

Latest evidence:

- 4 FASTQs validated.
- 1307 depth-eligible truth variants.
- 1122 exact PASS truth matches.
- Recall 0.8585.
- Precision 0.9842.

Primary outputs:

- `manifests/full_wes_benchmark_samplesheet.csv`
- `results/full_wes_benchmark/full_wes_benchmark_summary.json`
- `results/full_wes_benchmark/truth_overlap_benchmark_summary.json`

### Representative WGS Smoke

Command:

```sh
bun run fetch:phase3-wgs
bun run smoke:phase3-wgs
```

Purpose:

- Validate WGS-scale plumbing.
- Generate BAM, VCF, coverage-CNV, SBS96, and SV evidence outputs from representative WGS FASTQs.

Latest evidence:

- 500000 read pairs per end.
- 16 total threads.
- 631 coverage-CNV bins.
- Phase 3 complete.

Primary outputs:

- `manifests/phase3_wgs_smoke_samplesheet.csv`
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`

## What Still Needs A Known Answer

The current workflow is mechanically strong, but Phase 3 WGS needs independent correctness validation. The next validation targets are:

1. HG008 tumor/normal WGS from NIST Cancer Genome in a Bottle.
2. COLO829/COLO829BL tumor/normal WGS from ENA plus Zenodo truth files.
3. Seraseq ctDNA MRD Panel Mix if true liquid-biopsy dilution validation is needed.

See [ORTHOGONAL_VALIDATION_SAMPLES.md](/Users/jasonlaster/src/projects/diana-omics/docs/ORTHOGONAL_VALIDATION_SAMPLES.md).

## Diana Handoff

When Diana's files arrive:

```sh
bun run build:diana-template
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run verify:diana-raw
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run stage:diana-raw
```

Do not skip the public validation sidecar. It is the guardrail that tells us whether the system is still behaving on known inputs.
