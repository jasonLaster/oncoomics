# Cloud Diana Raw Intake Handoff Batch Run Summary

Run ID: `cloud-diana-raw-intake-handoff-20260617`

## Result

| Field | Value |
| --- | --- |
| AWS Batch job | `d868a987-79d1-4aa1-93f0-433fbde91686` |
| Status | `SUCCEEDED` |
| Exit code | `0` |
| Region | `us-east-1` |
| Queue | `diana-omics-prod-use1-ondemand` |
| Image | `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:hrd-packet-20260617T060000Z` |
| Source commit | `84c3019c86ec9ad8b71e1d59c1efbf72f249898c` |
| S3 prefix | `s3://diana-omics-results-172630973301-us-east-1/runs/rosalind_hrd/cloud-diana-raw-intake-handoff-20260617` |
| CloudWatch stream | `nf-172630973301-dkr-ecr-us-east-1-amazonaws-com-diana-omics-hrd-packet-20260617T060000Z/default/dbee006a51f64285bc345165e0ff14f2` |

## Command Path

This run used the reusable cloud submit wrapper with the Diana raw-intake materialized artifact root:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set diana_raw_intake --artifact-root-rel artifacts/diana_raw_intake_ready --run-id cloud-diana-raw-intake-handoff-20260617
```

The Batch job downloaded the pushed archive for commit `84c3019c86ec9ad8b71e1d59c1efbf72f249898c`, read handoff-aware raw-intake packet evidence from `artifacts/diana_raw_intake_ready`, and uploaded generated packet outputs to S3.

## Packet Result

| Metric | Value |
| --- | --- |
| Sample set | `diana_raw_intake` |
| Evidence rows | `5` |
| Adapter rows | `4` |
| Packet blocker count | `1` |
| Packet index SHA-256 | `b8e2b4c1ddf392d1033917b1c514047a6040e67e7d3829245b4a965e2525a7b7` |
| Run manifest SHA-256 | `57a24c12c2307467aebd456acc3dfecb27d2a357ff14f88f042d0f3287483a67` |
| Reviewer packet SHA-256 | `f7b0348d146265f27ab41250b46560640fbbf5761f3d4b2164b763608c1c6320` |

## Interpretation Boundary

This run proves the cloud submit wrapper can execute the Diana raw-intake readiness packet from a small materialized artifact root that includes the Dinah handoff plan. It does not validate Diana's actual files or produce HRD evidence. Raw file intake and tumor-normal DNA pairing remain blocked until real BAM/FASTQ/CRAM paths pass strict validation.
