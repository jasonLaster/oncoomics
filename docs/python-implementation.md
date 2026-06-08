# Python Implementation

The project is implemented as a small Python package plus shell-invoked bioinformatics tools. There is no JavaScript or TypeScript workflow code.

## Package Layout

```text
py/src/diana_omics/
  cli.py                 command router
  diana_raw.py           Diana raw-data manifest contract
  domain.py              shared domain helpers
  paths.py               repository path helpers
  types.py               typed dictionaries and aliases
  utils.py               CSV/JSON/files/download/subprocess helpers
  alignment.py           alignment-oriented helpers
  commands/              one module per workflow command
```

Tests live in `py/tests/`.

The package can be run directly:

```sh
PYTHONPATH=py/src python3 -m diana_omics verify:outputs
```

Most commands also have a `bun run ...` alias in `package.json`.

## Command Families

Plan and verification:

- `verify:plan`
- `verify:outputs`
- `verify:diana-raw`
- `verify:orthogonal`

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

Phase 3 full-source mode:

```sh
bun run fetch:phase3-wgs
bun run validate:phase3-wgs
```

This streams each complete SEQC2/HCC1395 public source FASTQ. Set `PHASE3_WGS_READS` to an integer only for developer plumbing checks; bounded runs do not satisfy `verify:outputs`.

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

## Why Not More Python Packages Yet

The current implementation keeps the orchestration transparent and avoids adding heavy dependencies before the workflow stabilizes. That is useful for auditing, but it has limits:

- Hand-parsed VCF/BED/BAM summaries are easier to get subtly wrong than `pysam`.
- CSV joins will not scale as well as `polars`.
- Reference sequence operations are safer with `pyfaidx` or htslib-backed tools.
- SV comparison should use `truvari` instead of local interval approximations.

Recommended future package additions:

- `pysam` for BAM/VCF/BCF access.
- `polars` for larger manifests and result joins.
- `pyfaidx` for reference sequence lookup.
- `truvari` as an external or Python-invoked SV truth comparator.
- SigProfiler, CHORD, scarHRD, FACETS/ASCAT/PURPLE-compatible adapters when full-depth HRD interpretation starts.

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
bun run py:format
bun run py:lint
bun run py:format:check
bun run py:typecheck
bun run py:test
python3 -m compileall -q py/src py/tests
bun run verify:outputs
git diff --check
```

## Design Tradeoffs

The current code optimizes for auditability over abstraction. Most commands are independent modules because each phase has a distinct input/output contract. Shared helpers exist only where repeated behavior is stable: path resolution, CSV/JSON IO, shell execution, hashing, and validation helpers.

When adding new work:

- Prefer one command module per validation gate.
- Write a small test for manifest parsing and summary semantics.
- Add generated artifacts to `verify_outputs.py`.
- Document whether the output is a smoke check, truth benchmark, or clinical-candidate evidence.
