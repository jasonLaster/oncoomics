# Cloud Materialization Plan

Run ID: `hcc1395-wes-materialized-20260617`

Artifact root mode: `materialized_artifact_root`

Use this when the container image does not include repository `results/`, `manifests/`, or `docs/operations` artifacts.

## Required Environment

```sh
export ROSALIND_HRD_ARTIFACT_ROOT=/workspace/artifacts
export ROSALIND_HRD_RUN_ID=hcc1395-wes-materialized-20260617
export ROSALIND_HRD_SAMPLE_SET=hcc1395_wes
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

Materialize the artifact root so paths like `results/phase3_wgs_smoke/phase3_wgs_summary.json` resolve under `$ROSALIND_HRD_ARTIFACT_ROOT`.

## Typical Prefixes

- `results/full_wes_benchmark/`
- `results/phase3_wgs_smoke/`
- `results/clinicalization/`
- `results/diana_raw_intake/`
- `manifests/`
- `docs/operations/`

## Missing Prefixes In This Run
- None.

The packet builder writes new output to the repo checkout, but reads source evidence from `$ROSALIND_HRD_ARTIFACT_ROOT` when that variable is set.
