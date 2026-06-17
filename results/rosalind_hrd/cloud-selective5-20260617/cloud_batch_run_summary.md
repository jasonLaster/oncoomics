# Cloud Batch Run Summary

Run ID: `cloud-selective5-20260617`

## Result

| Field | Value |
| --- | --- |
| AWS Batch job | `573cd3de-afe9-4949-80a2-8ba0a523c300` |
| Status | `SUCCEEDED` |
| Exit code | `0` |
| Region | `us-east-1` |
| Queue | `diana-omics-prod-use1-ondemand` |
| Image | `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:hrd-packet-20260617T060000Z` |
| Source commit | `3103ae6ec2a7b7939090409f377b459cbc9d368a` |
| S3 prefix | `s3://diana-omics-results-172630973301-us-east-1/runs/rosalind_hrd/cloud-selective5-20260617` |
| CloudWatch stream | `nf-172630973301-dkr-ecr-us-east-1-amazonaws-com-diana-omics-hrd-packet-20260617T060000Z/default/f99d1daa58d548708555498c32befab7` |

## Command Shape

The Batch container downloaded the pushed GitHub archive for commit `3103ae6ec2a7b7939090409f377b459cbc9d368a`, set `PYTHONPATH` and `DIANA_OMICS_ROOT` inside the extracted repo, and ran the packet builder with:

```sh
export ROSALIND_HRD_RUN_ID=cloud-selective5-20260617
export ROSALIND_HRD_SAMPLE_SET=hcc1395_wgs
export ROSALIND_HRD_ARTIFACT_ROOT=<repo>/artifacts/phase3_wgs_selective5
python3 -m diana_omics build:rosalind-hrd-packet
```

The job uploaded the generated packet outputs and `cloud_batch_run_summary.json` to the S3 prefix above.

## Packet Result

| Metric | Value |
| --- | --- |
| Sample set | `hcc1395_wgs` |
| Evidence rows | `7` |
| Adapter rows | `7` |
| Packet blocker count | `0` |
| Packet index SHA-256 | `a14f066e3f72e9defd1f87e9d162ab944175cbf55161d213a6bd76314ced164c` |
| Run manifest SHA-256 | `dade0688cbf040a8f8681d88dbc48134dd39e3468a45b9513dce8556b59ee5ae` |
| Reviewer packet SHA-256 | `b9979aeb1b04ae46947eaeccd45f2a7ab328befcad26d4d45a92265a524ec4f1` |

## Interpretation Boundary

This cloud run proves the lightweight Rosalind HRD packet builder can operate against materialized evidence artifacts in AWS Batch and can publish its own output evidence to S3.

It does not prove a final HRD score. The HCC1395 WGS packet still reports the true adapter boundaries: SBS3 interpretation thresholds are not locked, allele-specific CNV/LOH segments are unavailable for scarHRD, production SV caller output is not validated for CHORD, and the integrated HRDetect-style feature policy is incomplete.

Use the same materialized-artifact pattern for Diana BAM/FASTQ intake only after strict raw-input validation passes.
