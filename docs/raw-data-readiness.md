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

### Full Public WGS Validation

Command:

```sh
bun run fetch:phase3-wgs
bun run validate:phase3-wgs
```

Purpose:

- Validate WGS-scale plumbing on full-source public WGS FASTQs.
- Generate BAM, VCF, coverage-CNV, SBS96, and SV evidence outputs from representative WGS FASTQs.
- Preserve the TypeScript-era public Phase 3 example in the Python implementation.

Latest evidence:

- Full-source SEQC2/HCC1395 HiSeq X Ten WGS FASTQs are the acceptance gate.
- Bounded read subsets are developer checks only and fail the final Phase 3 verifier.
- The completion summary records `readPairsMode=full` and `fullSourceFastqs=true` when the full run has passed.

Primary outputs:

- `manifests/phase3_wgs_smoke_samplesheet.csv`
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`

Developer subset mode:

```sh
PHASE3_WGS_READS=500000 bun run fetch:phase3-wgs
PHASE3_WGS_READS=500000 bun run validate:phase3-wgs
```

The developer subset mode uses the same workflow for quick plumbing checks. It is not accepted as completed Phase 3 orthogonal validation.

### Orthogonal Public Example Verification

Command:

```sh
bun run verify:orthogonal
```

Purpose:

- Verify that the implemented public WES/WGS examples have passing completion artifacts.
- Verify that HG008, COLO829, COLO829 purity, and Seraseq MRD are documented as public or obtainable known-answer gates.

Primary outputs:

- `manifests/orthogonal_public_examples.csv`
- `results/orthogonal_validation/public_examples_summary.json`

## What Still Needs A Known Answer

The current workflow is mechanically strong, and the SEQC2/HCC1395 public examples are implemented. Phase 3 WGS still needs independent correctness validation. The next validation targets are:

1. HG008 tumor/normal WGS from NIST Cancer Genome in a Bottle.
2. COLO829/COLO829BL tumor/normal WGS from ENA plus Zenodo truth files.
3. Seraseq ctDNA MRD Panel Mix if true liquid-biopsy dilution validation is needed.

See [orthogonal-validation-samples.md](/Users/jasonlaster/src/projects/diana-omics/docs/orthogonal-validation-samples.md).

## Diana Handoff

When Diana's files arrive:

```sh
bun run build:diana-template
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run verify:diana-raw
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run stage:diana-raw
```

Do not skip the public validation sidecar. It is the guardrail that tells us whether the system is still behaving on known inputs.
