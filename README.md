# Diana HRD Omics

This repository is a reproducible Python workspace for testing whether we can analyze Diana's future raw omics files for homologous recombination deficiency (HRD) in a way that is auditable before any real Diana FASTQ, BAM, CRAM, VCF, or RNA files arrive.

The project has two jobs:

1. Build a validation sidecar from public data so the pipeline is already exercised on known samples.
2. Provide a clean plug-in contract for Diana's real data so we can rerun the same checks when the files arrive.

It does not make treatment recommendations. It produces evidence tables, quality summaries, and reviewer packets that still require expert review and clinical confirmation.

## Current State

The implementation is Python-only. From a checkout, run commands with `PYTHONPATH=src /usr/bin/python3 -m diana_omics ...`; installed environments can use the `diana-omics` console script.

The latest full run passed:

- Phase 2F full WES benchmark: 4 FASTQs validated, BAM validation passed, GATK Mutect2 ran, 1307 depth-eligible SEQC2/HCC1395 truth variants, 1122 exact PASS truth matches, recall 0.8585, precision 0.9842.
- Phase 3 WGS validation: full-source SEQC2/HCC1395 WGS FASTQs are the acceptance gate; bounded subsets are developer checks only. The verifier now fails unless Phase 3 records `readPairsMode=full`.
- Orthogonal public examples: SEQC2/HCC1395 full WES and Phase 3 WGS are verified; HG008, COLO829, COLO829 purity, and Seraseq MRD are documented as next known-answer gates.
- Expanded known-answer pull plan: 10 raw-sample or truth-asset targets are staged for owner review before download, including HG008, COLO829, COLO829 purity, and Seraseq MRD.
- Expanded known-answer execution: a 29-target representative cohort now runs non-dry bounded public checks across SEQC2/HCC1395, HG008, COLO829, COLO829 purity, and Seraseq MRD. The current report has 19 confirmations, 1 partial confirmation, 3 strict-validation gaps, and 6 blocked/request-only targets.
- Phase 1 public HRD/RNA tables: 28 reference-panel samples processed into reviewer-facing evidence tables.
- Diana intake: template and strict validation contract are ready; interpretation waits for actual Diana files.

## Quick Start

Run the lightweight checks:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:lint
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:format:check
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:typecheck
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:test
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:orthogonal
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:known-answer-sample-pull-plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:known-answer-public-findings
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:known-answer-public-findings
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:known-answer-expanded-cohort
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
```

Run the whole public validation workflow:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:all
```

Run through Nextflow:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:quick
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:known-answer-public-findings
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:known-answer-expanded-cohort
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:phase3-wgs:stub
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:phase3-wgs:dev
```

`nf:phase3-wgs:*` uses the resumable split Nextflow DAG: fetch, reference index, tumor BAM, normal BAM, and downstream validation are separate checkpoints. Use `nextflow -resume` after transient cloud failures. The legacy one-process runner is available as `nf:phase3-wgs:monolith:full` for fallback comparisons.

See [docs/nextflow.md](/Users/jasonlaster/src/projects/diana-omics/docs/nextflow.md) for Docker, AWS Batch, S3, and full-source WGS options.

Inspect recent pipeline run artifacts and speed diagnostics:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics diagnose:pipeline
```

Full-WES benchmark runs now write structured telemetry under `results/full_wes_benchmark/logs/telemetry/<run-id>/`, including `events.jsonl`, OTEL-shaped `otel_spans.jsonl`, `resource_samples.jsonl`, `heartbeat.json`, and `run_manifest.json`. Set `DIANA_OMICS_LOG_UPLOAD_URI=s3://bucket/prefix` to sync those logs after the run, or set it to a local path for a filesystem mirror.

For local stage-by-stage Phase 3 work, use `phase3:stage:fetch:tumor`, `phase3:stage:fetch:normal`, `phase3:stage:ref`, `phase3:stage:align:tumor`, `phase3:stage:align:normal`, and `phase3:stage:downstream`.

Prepare for Diana's actual files:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
```

When the real samplesheet exists:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw

DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw
```

## Documentation Guide

Start with [docs/readme.md](/Users/jasonlaster/src/projects/diana-omics/docs/readme.md) if you are new to the project. Use the rest of the docs by task:

| Document | Use it when you need to... |
| --- | --- |
| [docs/project-plan.md](/Users/jasonlaster/src/projects/diana-omics/docs/project-plan.md) | Understand the milestone plan, evidence gates, and what still needs to happen before Diana recompute. |
| [docs/phase-status.md](/Users/jasonlaster/src/projects/diana-omics/docs/phase-status.md) | Check what is currently complete, what passed, and what still needs full-data validation. |
| [docs/bug-audit.md](/Users/jasonlaster/src/projects/diana-omics/docs/bug-audit.md) | Review the most likely ways the analysis could be wrong before trusting a result. |
| [docs/diana-raw-inputs.md](/Users/jasonlaster/src/projects/diana-omics/docs/diana-raw-inputs.md) | Fill in Diana's future FASTQ/BAM/CRAM/RNA/vendor files and validate the handoff. |
| [docs/raw-data-readiness.md](/Users/jasonlaster/src/projects/diana-omics/docs/raw-data-readiness.md) | See which public raw-data mechanics already work, from FASTQ smoke tests through WES/WGS validation. |
| [docs/orthogonal-validation-samples.md](/Users/jasonlaster/src/projects/diana-omics/docs/orthogonal-validation-samples.md) | Pick the next known-answer datasets, especially HG008, COLO829, and Seraseq MRD. |
| [docs/phase3-parallel-compute.md](/Users/jasonlaster/src/projects/diana-omics/docs/phase3-parallel-compute.md) | Tune local CPU/thread usage for WGS, full-depth validation, and future Diana runs. |
| [docs/python-implementation.md](/Users/jasonlaster/src/projects/diana-omics/docs/python-implementation.md) | Work on the Python package, command modules, tests, and verifier contracts. |
| [docs/source-map.md](/Users/jasonlaster/src/projects/diana-omics/docs/source-map.md) | Audit where each dataset, truth set, tool, and vendor-context claim came from. |
| [docs/wiki-source-summary.md](/Users/jasonlaster/src/projects/diana-omics/docs/wiki-source-summary.md) | Understand how the original Diana wiki packet shaped the scope and caveats. |
| [docs/reference-panel-label-rules.md](/Users/jasonlaster/src/projects/diana-omics/docs/reference-panel-label-rules.md) | Review how Phase 1 public HRD panel labels are assigned and caveated. |
| [docs/aws-silly-ec2.md](/Users/jasonlaster/src/projects/diana-omics/docs/aws-silly-ec2.md) | Run a tiny self-terminating AWS EC2 smoke test. |

Main code:

- [src/diana_omics](/Users/jasonlaster/src/projects/diana-omics/src/diana_omics): Python package.
- [tests](/Users/jasonlaster/src/projects/diana-omics/tests): unit and integration-style contract tests.
- [src/diana_omics/workflow_tasks.py](/Users/jasonlaster/src/projects/diana-omics/src/diana_omics/workflow_tasks.py): Python task aliases for local, Docker, AWS, and deploy loops.

Main data contracts:

- [manifests/diana_raw_inputs.template.csv](/Users/jasonlaster/src/projects/diana-omics/manifests/diana_raw_inputs.template.csv): fill-in template for Diana.
- [manifests/orthogonal_validation_candidates.csv](/Users/jasonlaster/src/projects/diana-omics/manifests/orthogonal_validation_candidates.csv): next public truth-set targets.
- [manifests/known_answer_sample_pull_plan.csv](/Users/jasonlaster/src/projects/diana-omics/manifests/known_answer_sample_pull_plan.csv): 10-target pull plan for the expanded known-answer suite.
- [manifests/known_answer_public_finding_checks.csv](/Users/jasonlaster/src/projects/diana-omics/manifests/known_answer_public_finding_checks.csv): public finding and analysis-gate map for the 10-target suite.
- [manifests/known_answer_expanded_cohort_plan.csv](/Users/jasonlaster/src/projects/diana-omics/manifests/known_answer_expanded_cohort_plan.csv): 29-target representative non-dry validation cohort.
- [results/clinicalization/known_answer_expanded_cohort_execution.md](/Users/jasonlaster/src/projects/diana-omics/results/clinicalization/known_answer_expanded_cohort_execution.md): generated expanded cohort findings and gap report.
- [results/clinicalization/known_answer_public_finding_confirmation.md](/Users/jasonlaster/src/projects/diana-omics/results/clinicalization/known_answer_public_finding_confirmation.md): generated target-by-target confirmation status.
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

Full-depth work now starts native-backed integration through optional extras: `pysam` for BAM/VCF IO, `pyfaidx` for reference sequence access, `polars` for larger tabular joins, `truvari` for SV benchmarking, and SigProfiler-compatible signature assignment support. The Phase 3 runner uses native VCF/reference adapters when installed and falls back to existing `bcftools`/`samtools` paths otherwise. CHORD, scarHRD, and FACETS/ASCAT/PURPLE-compatible interpretation remain gated on validated full-depth feature inputs.

## Boundaries

Current public validation proves mechanics and partial correctness. It does not prove that Diana is HRD-positive or HRD-negative.

Before Diana interpretation, we still need:

- Diana's actual raw files and metadata.
- Reference build and tumor-normal pairing confirmation.
- Tumor purity and sample provenance.
- Orthogonal HG008/COLO829 correctness validation for full WGS truth sets.
- Reviewer sign-off on HRD interpretation policy and companion-diagnostic boundaries.
