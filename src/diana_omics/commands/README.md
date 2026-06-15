# Command Families

Each module in this directory implements one workflow command or verifier. The folders mirror the CLI families shown by:

```sh
PYTHONPATH=src python3 -m diana_omics --help
```

## Family Folders

```text
commands/
  hrd_context/            processed public HRD/RNA context and reviewer packets
  raw_validation/         public raw-data candidates, tooling, samplesheets, FASTQ smoke checks
  alignment_validation/   alignment, reference, somatic smoke, and full-WES validation
  phase3_wgs/             full-source Phase 3 WGS fetch, validation, and SRA range benchmarks
  known_answer/           known-answer planning, asset policy, benchmark, and orthogonal checks
  clinical_readiness/     clinicalization gates, QC, change control, evidence links, and signoff
  diana_intake/           Diana raw-data template, validation, and staging
  quality/                plan, output, and pipeline diagnostics
```

## Adding A Command

1. Put the module in the folder that owns the evidence contract.
2. Register the public command name in `diana_omics.commands.registry.COMMAND_SPECS`.
3. Add the command name to `diana_omics.commands.registry.COMMAND_FAMILIES`.
4. Add or update focused tests for parsing, summary semantics, or verifier behavior.
5. Add any important generated artifact to `verify_outputs.py` instead of relying only on prose.

`tests/test_cli_parity.py` enforces that commands are registered, grouped, and physically placed under a family folder.

## Naming Pattern

* `fetch:*` downloads or stages source inputs.
* `build:*` creates manifests, panels, templates, or packets.
* `analyze:*` derives evidence tables from already staged inputs.
* `smoke:*` runs a bounded mechanics check.
* `benchmark:*` runs truth-set or performance evidence generation.
* `verify:*` checks an artifact contract and fails loudly if it is incomplete.
* `stage:*` prepares Diana-specific inputs for later recompute.
