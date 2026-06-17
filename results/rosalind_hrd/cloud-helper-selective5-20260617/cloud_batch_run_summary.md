# Cloud Helper Batch Run Summary

Run ID: `cloud-helper-selective5-20260617`

## Result

| Field | Value |
| --- | --- |
| AWS Batch job | `e8d00f20-26c8-4a32-8198-8aa10c916859` |
| Status | `SUCCEEDED` |
| Exit code | `0` |
| Region | `us-east-1` |
| Queue | `diana-omics-prod-use1-ondemand` |
| Image | `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:hrd-packet-20260617T060000Z` |
| Source commit | `52212f105be129836f3c435b6929030a22d36722` |
| S3 prefix | `s3://diana-omics-results-172630973301-us-east-1/runs/rosalind_hrd/cloud-helper-selective5-20260617` |
| CloudWatch stream | `nf-172630973301-dkr-ecr-us-east-1-amazonaws-com-diana-omics-hrd-packet-20260617T060000Z/default/da529cc36d704059b21e7802d7333156` |

## Command Path

This run was submitted through the reusable repo wrapper:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --run-id cloud-helper-selective5-20260617
```

The Batch job downloaded the pushed archive for commit `52212f105be129836f3c435b6929030a22d36722`, read materialized evidence from `artifacts/phase3_wgs_selective5`, and uploaded generated packet outputs to S3.

## Packet Result

| Metric | Value |
| --- | --- |
| Sample set | `hcc1395_wgs` |
| Evidence rows | `7` |
| Adapter rows | `7` |
| Packet blocker count | `0` |
| Packet index SHA-256 | `b5f3fcbd241986da8ede71be9433d6254f606c17c8db95c66319e0c4d9db8728` |
| Run manifest SHA-256 | `0da4e95bb315ab148cc316245e1a1a83c95b17dd52be96b8e999f5c420dd2b2e` |
| Reviewer packet SHA-256 | `01fd7e334388d33b296c8b19716a6dc4ba55039179f4f795e4ca5b427c0ffeb9` |

## Interpretation Boundary

This run proves the reusable cloud submit wrapper can execute the materialized HCC1395 WGS packet path from the latest pushed commit and publish cloud-generated packet evidence. It does not prove final HRD interpretation readiness; SBS3, scarHRD, CHORD, and HRDetect-style calls remain no-call until the required production inputs and validation are locked.
