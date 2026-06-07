# Diana HRD Omics

This project is the reproducible analysis workspace for Diana's HRD-focused omics validation work. It starts from the validation-atlas packet in `../diana-tnbc/obsidian/wiki/omics` and turns it into a project plan, source map, frozen benchmark manifest, and eventually runnable analyses.

The active scope is intentionally conservative:

1. HRD, biallelic BRCA/HRR state, and mutational-signature biology from tumor-normal DNA.
2. RNA subtype biology only as a context lane when it helps interpret TNBC biology or validate sample handling.
3. No treatment-changing claim without clinician review and orthogonal or companion-diagnostic validation.

## Stack Decision

- **Bun** is used for one-off project scripts: source checks, dataset-catalog fetchers, manifest generation, and validation utilities.
- **Python** is the primary local analysis language for the first phase because Python 3.9 is available here and R is not installed locally.
- **BWA + samtools** are used for the local Phase 2B FASTQ-to-BAM smoke test, Phase 2C partial human-reference smoke, and Phase 2D full-reference BAM smoke.
- **bcftools** is used for the Phase 2D tiny VCF caller-contract smoke.
- **GATK Mutect2 + FilterMutectCalls** is used for the Phase 2E production-style tumor-normal somatic smoke and Phase 2F full WES benchmark.
- **GATK Mutect2, samtools bedcov, and local SBS96/SV evidence builders** are used for the Phase 3 representative WGS smoke.
- **External workflow adapters** are planned for raw WGS or R-only HRD tools: nf-core/sarek, SigProfiler, CHORD, scarHRD, FACETS/ASCAT/PURPLE-style outputs, and containerized R when needed.

## Current Artifacts

- `docs/PROJECT_PLAN.md` - detailed milestones, deliverables, and verifiers.
- `docs/PHASE_STATUS.md` - current phase status and remaining gates.
- `docs/RAW_DATA_READINESS.md` - representative raw-data plan for pre-Diana FASTQ/BAM readiness.
- `docs/PHASE3_PARALLEL_COMPUTE.md` - local and full-depth WGS parallel compute strategy.
- `docs/SOURCE_MAP.md` - researched datasets, tools, and access paths.
- `docs/WIKI_SOURCE_SUMMARY.md` - local wiki findings that drive the project boundary.
- `manifests/validation_atlases.json` - machine-readable source manifest for phase planning.
- `manifests/raw_representative_panel.csv` - public SEQC2/HCC1395 raw-data candidate ladder.
- `manifests/alignment_smoke_samplesheet.csv` - local Phase 2B tumor-normal alignment smoke samplesheet.
- `manifests/human_reference_smoke_samplesheet.csv` - Phase 2C hg38/hg19 partial human-reference alignment smoke samplesheet.
- `manifests/full_reference_smoke_samplesheet.csv` - Phase 2D full hg38 analysis-set caller-readiness smoke samplesheet.
- `manifests/production_somatic_smoke_samplesheet.csv` - Phase 2E GATK Mutect2 tumor-normal smoke samplesheet.
- `manifests/full_wes_benchmark_samplesheet.csv` - Phase 2F full SEQC2/HCC1395 WES benchmark samplesheet.
- `manifests/phase3_wgs_smoke_samplesheet.csv` - Phase 3 representative SEQC2/HCC1395 WGS smoke samplesheet.
- `scripts/verify-plan.ts` - Bun verifier for the project plan, source manifest, and local wiki assumptions.

## Verify

Run the local plan checks:

```sh
bun run verify:plan
```

Refresh representative raw-data metadata:

```sh
bun run fetch:raw-candidates
```

Build and run the Phase 2A raw FASTQ smoke test:

```sh
bun run build:raw-samplesheets
bun run smoke:raw
```

Build and run the Phase 2B local alignment/BAM smoke test:

```sh
bun run build:alignment-smoke
bun run smoke:alignment
```

Fetch and run the Phase 2C partial human-reference smoke test:

```sh
bun run fetch:human-reference-smoke
bun run smoke:human-reference
```

Fetch and run the Phase 2D full-reference caller-readiness smoke test:

```sh
bun run fetch:full-reference-smoke
bun run smoke:full-reference
```

Fetch and run the Phase 2E production-style somatic smoke test:

```sh
bun run fetch:production-somatic
bun run smoke:production-somatic
```

Fetch and run the Phase 2F full WES benchmark:

```sh
bun run fetch:full-wes
bun run benchmark:full-wes
```

Fetch and run the Phase 3 representative WGS smoke:

```sh
bun run fetch:phase3-wgs
bun run smoke:phase3-wgs
```

Phase 3 parallel knobs:

```sh
PHASE3_WGS_READS=500000 PHASE3_WGS_THREADS=16 PHASE3_WGS_PARALLEL_ALIGN=1 bun run smoke:phase3-wgs
```

Run the full workflow:

```sh
bun run run:all
```

Optionally check the online source links too:

```sh
bun run verify:plan:online
```
