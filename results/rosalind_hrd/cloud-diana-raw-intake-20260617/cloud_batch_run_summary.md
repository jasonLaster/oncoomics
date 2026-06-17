# Cloud Diana Raw Intake Batch Run Summary

Run ID: `cloud-diana-raw-intake-20260617`

## Result

| Field | Value |
| --- | --- |
| AWS Batch job | `5640a9f1-8f8c-4560-a8dc-338f3b39c655` |
| Status | `SUCCEEDED` |
| Exit code | `0` |
| Region | `us-east-1` |
| Queue | `diana-omics-prod-use1-ondemand` |
| Image | `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:hrd-packet-20260617T060000Z` |
| Source commit | `cefbe73ea1797e081e5735c6010ff258ee092b11` |
| S3 prefix | `s3://diana-omics-results-172630973301-us-east-1/runs/rosalind_hrd/cloud-diana-raw-intake-20260617` |
| CloudWatch stream | `nf-172630973301-dkr-ecr-us-east-1-amazonaws-com-diana-omics-hrd-packet-20260617T060000Z/default/5086642ba33d42e3bf0a43a8b2c84358` |

## Command Path

This run used the reusable cloud submit wrapper with the Diana raw-intake materialized artifact root:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set diana_raw_intake --artifact-root-rel artifacts/diana_raw_intake_ready --run-id cloud-diana-raw-intake-20260617
```

The Batch job downloaded the pushed archive for commit `cefbe73ea1797e081e5735c6010ff258ee092b11`, read raw-intake packet evidence from `artifacts/diana_raw_intake_ready`, and uploaded generated packet outputs to S3.

## Packet Result

| Metric | Value |
| --- | --- |
| Sample set | `diana_raw_intake` |
| Evidence rows | `4` |
| Adapter rows | `4` |
| Packet blocker count | `1` |
| Packet index SHA-256 | `3c30cd702c8e4bcb73016360e4943ba4ed709ad1291112d66cb12db9e3a48a8d` |
| Run manifest SHA-256 | `7e1b79c215a3eb07dbb1a5e19ba61a97b9c394ae5104aa64e43b0fa18c0c0d21` |
| Reviewer packet SHA-256 | `04aecd1c35d0945228c48339315a8ded14be61b7f296b668015487a9af667f32` |

## Interpretation Boundary

This run proves the cloud submit wrapper can execute the Diana raw-intake readiness packet from a small materialized artifact root. It does not validate Diana's actual files or produce HRD evidence. Raw file intake and tumor-normal DNA pairing remain blocked until real BAM/FASTQ/CRAM paths pass strict validation.
