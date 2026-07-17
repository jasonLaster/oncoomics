# Cloud Materialization Plan

Run ID: `ngs-prep-20260717T231049Z`

Artifact root mode: `repo_root`

Use this when the container image does not include repository `results/`, `manifests/`, or `docs/operations` artifacts.

## Required Environment

```sh
export ROSALIND_HRD_ARTIFACT_ROOT=/workspace/artifacts
export ROSALIND_HRD_RUN_ID=ngs-prep-20260717T231049Z
export ROSALIND_HRD_SAMPLE_SET=hcc1395_wes,hcc1395_wgs,colo829
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
