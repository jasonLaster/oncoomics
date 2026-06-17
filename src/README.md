# Source Map

The Python package owns workflow orchestration, evidence generation, validation contracts, task aliases, and Nextflow process glue.

For the package-level map, see [diana_omics/README.md](diana_omics/README.md).

## Layout

```text
src/diana_omics/
  cli.py                  command router
  workflow_tasks.py       local, Docker, AWS, and deploy task aliases
  nextflow_process.py     Nextflow workspace setup and split-stage process plans
  diana_raw.py            Diana raw-data manifest contract
  domain.py               shared domain helpers
  paths.py                repository path helpers
  alignment.py            alignment helpers
  telemetry.py            durable events, spans, resource samples, heartbeat files
  pipeline_diagnostics.py Nextflow and runtime log classification
  native.py               optional native-package integration checks
  utils.py                CSV/JSON/files/download/subprocess helpers
  commands/               command modules grouped by workflow family
    registry.py           public command names, families, and implementation modules
    hrd_context/
    raw_validation/
    alignment_validation/
    phase3_wgs/
    known_answer/
    clinical_readiness/
    diana_intake/
    quality/
```

## Command Families

The CLI uses the same families for `PYTHONPATH=src python3 -m diana_omics --help`. The single source of truth is [commands/registry.py](diana_omics/commands/registry.py); see [commands/README.md](diana_omics/commands/README.md) for the folder map and command naming pattern.

* HRD and RNA context: `fetch:phase1`, `build:panel`, `analyze:hrd`, `analyze:lehmann`, `analyze:rna`, `build:packet`, `build:rosalind-hrd-packet`, `triage:rosalind-hrd-readiness`.
* Raw public validation: `fetch:raw-candidates`, `audit:raw-tools`, `build:raw-samplesheets`, `smoke:raw`.
* Alignment and representative validation: `build:alignment-smoke`, `smoke:alignment`, `fetch:human-reference-smoke`, `smoke:human-reference`, `fetch:full-reference-smoke`, `smoke:full-reference`, `fetch:production-somatic`, `smoke:production-somatic`, `fetch:full-wes`, `benchmark:full-wes`.
* Phase 3 WGS: `fetch:phase3-wgs`, `validate:phase3-wgs`, `benchmark:sra-range`, and commands beginning with `phase3:stage:`.
* Known-answer validation: `plan:known-answer-benchmarks`, `benchmark:known-answer`, `run:known-answer-*`, `verify:orthogonal`, and commands beginning with `verify:known-answer-`.
* Clinical readiness: commands beginning with `verify:clinical-`, plus `verify:clinicalization-readiness-rollup`, `verify:cnv-loh-readiness`, `verify:hrd-interpretation-readiness`, and `verify:sv-caller-readiness`.
* Diana intake: `build:diana-template`, `plan:diana-raw-handoff`, `verify:diana-raw`, `stage:diana-raw`.
* Quality and diagnostics: `py:format`, `py:format:check`, `py:lint`, `py:typecheck`, `py:test`, `typecheck`, `test`, `verify:plan`, `verify:plan:online`, `verify:outputs`, `verify:phase3-outputs`, `diagnose:pipeline`.
* Local Nextflow: commands beginning with `nf:` for local or Docker profiles.
* AWS and deployment: commands beginning with `infra:aws:`, `aws:ecr:push`, `aws:hrd-packet:cloud-submit`, `deploy:aws`, and commands beginning with `nf:aws:`.
* Workflow aliases: `run:all`.

## Design Rules

* Prefer one command module per validation gate.
* Keep command modules inside family folders and group the public command surface through `commands/registry.py`.
* Fail loudly when required files, columns, statuses, or tool outputs are missing.
* Add important generated artifacts to a verifier instead of relying on prose.
* Keep clinical boundaries explicit in summaries and reviewer-facing outputs.
