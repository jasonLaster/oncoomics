# Diana Omics Package

This package is the Python runtime for the Diana HRD omics workflow. It is organized around a small core plus command families.

## Core Modules

```text
diana_omics/
  cli.py                  parses the public CLI and dispatches commands or task aliases
  paths.py                repository path constants and path resolution helpers
  utils.py                shared CSV, JSON, text, download, hash, and subprocess helpers
  domain.py               HRD and breast-cancer domain classification helpers
  diana_raw.py            Diana raw-data manifest columns, template rows, and validation contract
  alignment.py            reusable alignment, indexing, and BAM validation helpers
  native.py               optional native package probes and adapters
  telemetry.py            durable run events, spans, resource samples, and heartbeat files
  pipeline_diagnostics.py Nextflow and runtime log classification
  workflow_tasks.py       local, Docker, AWS, deploy, and stage task aliases
  nextflow_process.py     testable process plans used by main.nf
  commands/               one module per command, grouped by workflow family
```

## Execution Flow

1. `python -m diana_omics <command>` enters `cli.py`.
2. `cli.py` loads public command metadata from `commands/registry.py`.
3. Direct workflow commands call one module under `commands/<family>/`.
4. Task aliases call `workflow_tasks.py`, which may run multiple commands, Nextflow, Terraform, Docker, or AWS helpers.
5. Nextflow stages call `nextflow_process.py` so workspace setup and merge behavior stay testable in Python.

## Where To Add Work

- Add a new workflow command under the closest `commands/<family>/` folder.
- Register public command names in `commands/registry.py`.
- Add multi-step local/cloud aliases in `workflow_tasks.py`.
- Put reusable IO or validation helpers in `utils.py` only after more than one command needs them.
- Put biology-specific classification logic in `domain.py`.
- Add important output contracts to `commands/quality/verify_outputs.py`.

The main command-family guide is [commands/README.md](commands/README.md).
