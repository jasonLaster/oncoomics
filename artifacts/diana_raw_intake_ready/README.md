# Diana Raw Intake Artifact Root

This materialized artifact root supports bounded Rosalind HRD packet cloud runs for `diana_raw_intake`.

It contains only the raw-intake template, operations runbook, and contract/readiness summary JSON files needed by `build:rosalind-hrd-packet` when `ROSALIND_HRD_ARTIFACT_ROOT` is set to this directory. It does not contain BAM, FASTQ, CRAM, VCF, BED, report PDFs, or any raw human sequence data.

Allowed packet conclusion: this proves the Diana raw-data intake contract and run path are ready. It does not validate Diana files or produce HRD evidence until actual BAM/FASTQ/CRAM paths are supplied and pass strict validation.

## Files

| Path | SHA-256 |
| --- | --- |
| `manifests/diana_raw_inputs.template.csv` | `d6a26801a48fe4147b02186db6c124c1a66c029a167c2a83e273cbbe75ec1b96` |
| `docs/operations/diana-raw-inputs.md` | `b6b4f5cc92c938fd798c4922fa7740d56eff9fc26a9df0962a0a9299b8f897b1` |
| `results/diana_raw_intake/input_contract.json` | `01fb59916ffed9be6467c0fc6360aad233c65d3f99d21082ce410935c5bd9077` |
| `results/diana_raw_intake/intake_readiness_summary.json` | `6695629627375598dbd7e061f45f398099b94f1e4bb87baa6ed6db8a9f43d4a0` |
| `results/diana_raw_intake/input_validation_summary.json` | `081e775d15cb57b2361133e1b845a450a315b984091f3c68e085b3c850d69497` |

## Local Smoke

```sh
ROSALIND_HRD_SAMPLE_SET=diana_raw_intake ROSALIND_HRD_ARTIFACT_ROOT=artifacts/diana_raw_intake_ready ROSALIND_HRD_RUN_ID=diana-raw-intake-materialized-YYYYMMDD PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

## Cloud Smoke

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set diana_raw_intake --artifact-root-rel artifacts/diana_raw_intake_ready --run-id cloud-diana-raw-intake-YYYYMMDD
```
