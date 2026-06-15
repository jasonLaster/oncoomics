# Source Map

The Python package owns workflow orchestration, evidence generation, validation contracts, and Nextflow process glue.

## Layout

```text
src/diana_omics/
  cli.py                 command router
  workflow_tasks.py      local, Docker, AWS, and deploy task aliases
  nextflow_process.py    Nextflow workspace setup and split-stage process plans
  diana_raw.py           Diana raw-data manifest contract
  alignment.py           alignment helpers
  telemetry.py           durable events, spans, resource samples, heartbeat files
  pipeline_diagnostics.py Nextflow and runtime log classification
  utils.py               CSV/JSON/files/download/subprocess helpers
  commands/              one module per workflow command
```

## Command Families

- HRD and RNA context: `build:panel`, `analyze:hrd`, `analyze:rna`, `analyze:lehmann`, `build:packet`.
- Raw public validation: `fetch:raw-candidates`, `smoke:raw`, `benchmark:full-wes`, `validate:phase3-wgs`.
- Known-answer validation: `verify:orthogonal`, `run:known-answer-public-findings`, `run:known-answer-expanded-cohort`.
- Diana intake: `build:diana-template`, `verify:diana-raw`, `stage:diana-raw`.
- Quality: `py:format`, `py:lint`, `py:typecheck`, `py:test`, `verify:plan`, `verify:outputs`.
- Nextflow/AWS aliases: commands beginning with `nf:`.

For the system sequence diagram, see [../docs/operations/analytics-sequence.md](../docs/operations/analytics-sequence.md).

## Design Rules

- Prefer one command module per validation gate.
- Fail loudly when required files, columns, statuses, or tool outputs are missing.
- Add important generated artifacts to a verifier instead of relying on prose.
- Keep clinical boundaries explicit in summaries and reviewer-facing outputs.
- Use native packages such as `pysam`, `polars`, `pyfaidx`, and `truvari` where they reduce parsing risk, while preserving audited fallbacks where useful.
