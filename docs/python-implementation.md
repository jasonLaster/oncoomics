# Python Implementation

The project is implemented as a small Python package plus shell-invoked bioinformatics tools. There is no JavaScript or TypeScript workflow code.

## Package Layout

```text
src/diana_omics/
  cli.py                 command router
  diana_raw.py           Diana raw-data manifest contract
  domain.py              shared domain helpers
  paths.py               repository path helpers
  types.py               typed dictionaries and aliases
  utils.py               CSV/JSON/files/download/subprocess helpers
  alignment.py           alignment-oriented helpers
  nextflow_process.py    testable Nextflow process plans and workspace glue
  commands/              one module per workflow command
```

Tests live in `tests/`.

The package can be run directly:

```sh
PYTHONPATH=src python3 -m diana_omics verify:outputs
```

Local, Docker, AWS, and deploy task aliases live in `diana_omics.workflow_tasks`, so they stay on the Python CLI surface instead of a separate JavaScript task runner. Nextflow process sequencing lives in `diana_omics.nextflow_process`, which keeps workflow conditionals and workspace merge behavior unit-testable instead of buried in inline process scripts.

## Command Families

Plan and verification:

- `verify:plan`
- `verify:outputs`
- `verify:diana-raw`
- `verify:orthogonal`
- `diagnose:pipeline`

Public data and processed-panel analysis:

- `fetch:phase1`
- `build:panel`
- `analyze:hrd`
- `analyze:rna`
- `build:packet`

Raw representative data:

- `fetch:raw-candidates`
- `audit:raw-tools`
- `build:raw-samplesheets`
- `smoke:raw`

Alignment and caller readiness:

- `build:alignment-smoke`
- `smoke:alignment`
- `fetch:human-reference-smoke`
- `smoke:human-reference`
- `fetch:full-reference-smoke`
- `smoke:full-reference`
- `fetch:production-somatic`
- `smoke:production-somatic`
- `fetch:full-wes`
- `benchmark:full-wes`

WGS validation:

- `fetch:phase3-wgs`
- `validate:phase3-wgs`
- `benchmark:sra-range`

Phase 3 full-source mode:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics fetch:phase3-wgs
PYTHONPATH=src /usr/bin/python3 -m diana_omics validate:phase3-wgs
```

This streams each complete SEQC2/HCC1395 public source FASTQ. Set `PHASE3_WGS_READS` to an integer only for developer plumbing checks; bounded runs do not satisfy `verify:outputs`.

Stage-local Phase 3 loops are exposed as package aliases around the same Python commands:

- `phase3:stage:fetch:tumor`
- `phase3:stage:fetch:normal`
- `phase3:stage:ref`
- `phase3:stage:align:tumor`
- `phase3:stage:align:normal`
- `phase3:stage:downstream`

`benchmark:sra-range` owns the SRA Open Data range-read benchmark that Nextflow uses for cheap AWS network experiments. Keep benchmark parsing and summary behavior covered in local tests before changing cloud command lines.

Diana intake:

- `build:diana-template`
- `verify:diana-raw`
- `stage:diana-raw`

## Libraries and Tools

Python dependencies are intentionally small:

- Standard library: CSV, JSON, paths, hashing, urllib, subprocess, gzip, statistics.
- Ruff: formatting and linting.
- mypy: static type checking.
- pytest: tests.

External command-line tools do the bioinformatics heavy lifting:

- `bwa`: alignment.
- `samtools`: BAM validation, indexing, stats, depth, flagstat.
- `bcftools`: VCF stats, indexing, filtering, key extraction.
- `java`: runtime for GATK.
- `gatk`: MarkDuplicates, Mutect2, FilterMutectCalls, contamination steps.

## Observability

Long-running commands should emit durable run artifacts, not just terminal text. The shared telemetry helper writes:

- `events.jsonl` for stage events, cache hits/misses, command starts/ends, and heartbeat updates.
- `otel_spans.jsonl` with trace IDs, span IDs, parent span IDs, start/end nanoseconds, duration, status, and attributes.
- `resource_samples.jsonl` with load average, disk usage, and command process-tree CPU/RSS samples.
- `heartbeat.json` with the latest stage and data-level progress.
- `run_manifest.json` with the run ID, trace ID, status, and artifact paths.

For `benchmark:full-wes`, these live under `results/full_wes_benchmark/logs/telemetry/<run-id>/`. Set `DIANA_OMICS_LOG_UPLOAD_URI=s3://bucket/prefix` to sync the telemetry directory to S3 after success or failure. A local path also works for a filesystem mirror. Set `DIANA_OMICS_TRACE_HEARTBEAT_SECONDS` to control command resource-sample cadence and `DIANA_OMICS_TELEMETRY=0` only for intentionally quiet developer runs.

## Native Package Integration

The current implementation keeps the orchestration transparent and avoids requiring heavy dependencies before the workflow stabilizes. That is useful for auditing, but it has limits:

- Hand-parsed VCF/BED/BAM summaries are easier to get subtly wrong than `pysam`.
- CSV joins will not scale as well as `polars`.
- Reference sequence operations are safer with `pyfaidx` or htslib-backed tools.
- SV comparison should use `truvari` instead of local interval approximations.

The first integration tranche is optional rather than mandatory:

- `native`: `pysam`, `pyfaidx`, and `polars`.
- `sv`: `truvari`.
- `hrd`: the native/SV foundation plus `SigProfilerAssignment`.

Phase 3 uses native VCF sample parsing and reference sequence lookup when those packages are installed, while preserving the existing `bcftools`/`samtools` fallbacks. CHORD, scarHRD, and FACETS/ASCAT/PURPLE-compatible interpretation should wait until full-depth SNV/indel, allele-specific CNV, SV, signature, purity, and orthogonal validation gates are met.

## Error Philosophy

Commands should fail loudly when required files, columns, or status fields are missing. Generated summaries should include:

- `status`
- input paths or source accessions
- reference build
- tool versions when external tools are used
- caveats or boundaries

`verify:outputs` is the final contract checker. If a new result becomes important, add it to the verifier instead of relying on a README statement.

## Quality Commands

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:format
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:lint
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:format:check
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:typecheck
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:test
python3 -m compileall -q src tests
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
git diff --check
```

## Design Tradeoffs

The current code optimizes for auditability over abstraction. Most commands are independent modules because each phase has a distinct input/output contract. Shared helpers exist only where repeated behavior is stable: path resolution, CSV/JSON IO, shell execution, hashing, and validation helpers.

When adding new work:

- Prefer one command module per validation gate.
- Write a small test for manifest parsing and summary semantics.
- Add generated artifacts to `verify_outputs.py`.
- Document whether the output is a smoke check, truth benchmark, or clinical-candidate evidence.
