# Diana Raw Intake Artifact Root

This materialized artifact root supports bounded Rosalind HRD packet cloud runs for `diana_raw_intake`.

It contains only the raw-intake template, operations runbook, handoff plan, and contract/readiness summary files needed by `build:rosalind-hrd-packet` when `ROSALIND_HRD_ARTIFACT_ROOT` is set to this directory. It does not contain BAM, FASTQ, CRAM, VCF, BED, report PDFs, or any raw human sequence data.

Allowed packet conclusion: this proves the Diana raw-data intake contract and run path are ready. It does not validate Diana files or produce HRD evidence until actual BAM/FASTQ/CRAM paths are supplied and pass strict validation.

## Files

| Path | SHA-256 |
| --- | --- |
| `manifests/diana_raw_inputs.template.csv` | `d6a26801a48fe4147b02186db6c124c1a66c029a167c2a83e273cbbe75ec1b96` |
| `docs/operations/diana-raw-inputs.md` | `bb626beeef58556367eaf3f190557e5dd9d0f60de5f6951c46945dcd140a5065` |
| `results/diana_raw_intake/input_contract.json` | `2a35c6f8099de914332361d580fa753583f691c8ced59a36f1053d31235e2381` |
| `results/diana_raw_intake/intake_readiness_summary.json` | `b628fc39eec45ca508cb4d53fab90d4c68d78614ad896613464d8fdc710584f8` |
| `results/diana_raw_intake/input_validation_summary.json` | `9a1f48a0f1960a962a483d931336b3365a7ac9be4ff2099cb99e6cbac091de56` |
| `results/diana_raw_intake/dinah_handoff_plan.json` | `cba41769c9ff9619c5034e86deb8340e411a7c20c4a6ba9c2ade64fb7447faea` |
| `results/diana_raw_intake/dinah_handoff_plan.md` | `7c8c3ab86815d843e44e2d66d79838143e2c96154278f7906d01af46fbc1fb4a` |
| `results/diana_raw_intake/dinah_handoff_plan.csv` | `c6d7784b341e4038a359bc9ff17222c52ab818c14296151690349b61bb9a4220` |

## Local Smoke

```sh
ROSALIND_HRD_SAMPLE_SET=diana_raw_intake ROSALIND_HRD_ARTIFACT_ROOT=artifacts/diana_raw_intake_ready ROSALIND_HRD_RUN_ID=diana-raw-intake-materialized-YYYYMMDD PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

Expected packet result: 5 evidence rows and 4 adapter rows. The handoff plan should be present as packet evidence, while raw file intake and tumor-normal pairing remain blocked until Dinah's actual paths pass strict validation.

## Cloud Smoke

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set diana_raw_intake --artifact-root-rel artifacts/diana_raw_intake_ready --run-id cloud-diana-raw-intake-YYYYMMDD
```
