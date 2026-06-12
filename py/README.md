# Diana Omics Python Package

This directory contains the Python implementation of the Diana HRD omics workflow.

## Install For Development

The repo currently runs without installing the package by setting `PYTHONPATH=py/src`.

Optional editable install:

```sh
python3 -m pip install -e 'py[dev]'
```

## Run Commands

Direct Python:

```sh
PYTHONPATH=py/src python3 -m diana_omics verify:outputs
```

Task alias:

```sh
PYTHONPATH=py/src /usr/bin/python3 -m diana_omics verify:outputs
```

List available commands:

```sh
PYTHONPATH=py/src python3 -m diana_omics --help
```

## Test And Typecheck

```sh
PYTHONPATH=py/src /usr/bin/python3 -m diana_omics py:format
PYTHONPATH=py/src /usr/bin/python3 -m diana_omics py:lint
PYTHONPATH=py/src /usr/bin/python3 -m diana_omics py:format:check
PYTHONPATH=py/src /usr/bin/python3 -m diana_omics py:typecheck
PYTHONPATH=py/src /usr/bin/python3 -m diana_omics py:test
python3 -m compileall -q py/src py/tests
```

## Implementation Notes

- `diana_omics.cli` maps command names to command modules.
- `diana_omics.diana_raw` owns the Diana samplesheet contract.
- `diana_omics.utils` owns common IO, hashing, and subprocess helpers.
- `commands/verify_outputs.py` is the generated-artifact contract.
- Tests focus on command wiring, manifest parsing, helper semantics, Diana raw intake, and Phase 3 WGS helper behavior.

Keep new functionality boring: one command module, typed helpers, unit tests, output summaries, and verifier coverage.
