# Diana HRD Omics

This repository is a reproducible Python workspace for testing whether we can analyze Diana's future raw omics files for homologous recombination deficiency (HRD) in a way that is auditable before any real Diana FASTQ, BAM, CRAM, VCF, or RNA files arrive.

The project has two jobs:

1. Build a validation sidecar from public data so the pipeline is already exercised on known samples.
2. Provide a clean plug-in contract for Diana's real data so we can rerun the same checks when the files arrive.

It does not make treatment recommendations. It produces evidence tables, quality summaries, and reviewer packets that still require expert review and clinical confirmation.

## Current State

The implementation is Python-only. `bun` is retained only as a convenient task runner around `PYTHONPATH=py/src python3 -m diana_omics ...`.

The latest full run passed:

- Phase 2F full WES benchmark: 4 FASTQs validated, BAM validation passed, GATK Mutect2 ran, 1307 depth-eligible SEQC2/HCC1395 truth variants, 1122 exact PASS truth matches, recall 0.8585, precision 0.9842.
- Phase 3 WGS smoke: 500000 read pairs per end, parallel alignment enabled, BAM validation passed, WGS Mutect2 smoke passed, 631 coverage-CNV bins generated, SBS96 and SV evidence tables generated.
- Phase 1 public HRD/RNA tables: 28 reference-panel samples processed into reviewer-facing evidence tables.
- Diana intake: template and strict validation contract are ready; interpretation waits for actual Diana files.

## Quick Start

Run the lightweight checks:

```sh
bun run verify:plan
bun run py:lint
bun run py:format:check
bun run py:typecheck
bun run py:test
bun run verify:outputs
```

Run the whole public validation workflow:

```sh
bun run run:all
```

Prepare for Diana's actual files:

```sh
bun run build:diana-template
bun run verify:diana-raw
```

When the real samplesheet exists:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
bun run verify:diana-raw

DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
bun run stage:diana-raw
```

## How To Read The Repo

Start here:

- [docs/README.md](/Users/jasonlaster/src/projects/diana-omics/docs/README.md): new-reader guide, concepts, and map.
- [docs/PROJECT_PLAN.md](/Users/jasonlaster/src/projects/diana-omics/docs/PROJECT_PLAN.md): milestone plan from current state to Diana recompute.
- [docs/PHASE_STATUS.md](/Users/jasonlaster/src/projects/diana-omics/docs/PHASE_STATUS.md): what is done, what is partial, and what blocks clinical interpretation.
- [docs/BUG_AUDIT.md](/Users/jasonlaster/src/projects/diana-omics/docs/BUG_AUDIT.md): likely failure modes and what currently catches them.
- [docs/DIANA_RAW_INPUTS.md](/Users/jasonlaster/src/projects/diana-omics/docs/DIANA_RAW_INPUTS.md): raw-data manifest contract.
- [docs/ORTHOGONAL_VALIDATION_SAMPLES.md](/Users/jasonlaster/src/projects/diana-omics/docs/ORTHOGONAL_VALIDATION_SAMPLES.md): HG008, COLO829, and Seraseq validation candidates.
- [docs/PYTHON_IMPLEMENTATION.md](/Users/jasonlaster/src/projects/diana-omics/docs/PYTHON_IMPLEMENTATION.md): package architecture and command map.

Main code:

- [py/src/diana_omics](/Users/jasonlaster/src/projects/diana-omics/py/src/diana_omics): Python package.
- [py/tests](/Users/jasonlaster/src/projects/diana-omics/py/tests): unit and integration-style contract tests.
- [package.json](/Users/jasonlaster/src/projects/diana-omics/package.json): task aliases only.

Main data contracts:

- [manifests/diana_raw_inputs.template.csv](/Users/jasonlaster/src/projects/diana-omics/manifests/diana_raw_inputs.template.csv): fill-in template for Diana.
- [manifests/orthogonal_validation_candidates.csv](/Users/jasonlaster/src/projects/diana-omics/manifests/orthogonal_validation_candidates.csv): next public truth-set targets.
- [results/reviewer_packet.md](/Users/jasonlaster/src/projects/diana-omics/results/reviewer_packet.md): current reviewer summary.
- [results/diana_readiness_gate.md](/Users/jasonlaster/src/projects/diana-omics/results/diana_readiness_gate.md): readiness boundary.

## Tools

Python orchestrates everything. The current workflow uses:

- Python standard library for manifests, JSON/CSV, downloads, hashing, and subprocess orchestration.
- Ruff, mypy, and pytest for formatting, static checks, and tests.
- BWA and samtools for FASTQ-to-BAM alignment and BAM QC.
- bcftools for VCF indexing, statistics, and caller-contract checks.
- Java plus GATK Mutect2, FilterMutectCalls, and MarkDuplicates for production-style somatic smoke tests.
- Local Python evidence builders for HRD tables, RNA context tables, WGS SBS96 summaries, coverage-CNV bins, and SV evidence summaries.

Future full-depth work should add native-backed libraries where they reduce bug risk: `pysam` for BAM/VCF IO, `polars` for larger tabular joins, `pyfaidx` for reference sequence access, `truvari` for SV benchmarking, and SigProfiler/CHORD/scarHRD/FACETS/ASCAT/PURPLE-compatible adapters for real HRD interpretation.

## Boundaries

Current public validation proves mechanics and partial correctness. It does not prove that Diana is HRD-positive or HRD-negative.

Before Diana interpretation, we still need:

- Diana's actual raw files and metadata.
- Reference build and tumor-normal pairing confirmation.
- Tumor purity and sample provenance.
- Orthogonal HG008/COLO829 correctness validation for full WGS truth sets.
- Reviewer sign-off on HRD interpretation policy and companion-diagnostic boundaries.
