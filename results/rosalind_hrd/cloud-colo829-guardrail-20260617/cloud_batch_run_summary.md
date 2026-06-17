# Cloud COLO829 Guardrail Batch Run Summary

Run ID: `cloud-colo829-guardrail-20260617`

## Result

| Field | Value |
| --- | --- |
| AWS Batch job | `477dc868-d16a-4bad-a58d-2794b2ed0f91` |
| Status | `SUCCEEDED` |
| Exit code | `0` |
| Region | `us-east-1` |
| Queue | `diana-omics-prod-use1-ondemand` |
| Image | `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:hrd-packet-20260617T060000Z` |
| Source commit | `ee90e775f2b13d79e5fc94f21a54d113557b638c` |
| S3 prefix | `s3://diana-omics-results-172630973301-us-east-1/runs/rosalind_hrd/cloud-colo829-guardrail-20260617` |
| CloudWatch stream | `nf-172630973301-dkr-ecr-us-east-1-amazonaws-com-diana-omics-hrd-packet-20260617T060000Z/default/6c08ccecf5bd4e519c50632baaf19eba` |

## Command Path

This run used the reusable cloud submit wrapper with the COLO829 materialized artifact root:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set colo829 --artifact-root-rel artifacts/colo829_guardrail --run-id cloud-colo829-guardrail-20260617
```

The Batch job downloaded the pushed archive for commit `ee90e775f2b13d79e5fc94f21a54d113557b638c`, read COLO829 guardrail evidence from `artifacts/colo829_guardrail`, and uploaded generated packet outputs to S3.

## Packet Result

| Metric | Value |
| --- | --- |
| Sample set | `colo829` |
| Evidence rows | `9` |
| Adapter rows | `4` |
| Packet blocker count | `4` |
| Packet index SHA-256 | `39cda84e037b9c2b4230b9c6e0e839643fee281843c573c7d979a832c8a4b69d` |
| Run manifest SHA-256 | `6d5b2691bd8628ae5f9d6daa94e85835d8b67d3886906c6b9ffcfc7f40833927` |
| Reviewer packet SHA-256 | `dcbb349e995cc93d79d94420f803d9613e85a1a44fa615156dfd2ef2e93c5b29` |

## Interpretation Boundary

This run proves the cloud submit wrapper can execute the COLO829 tumor-normal and BRAF driver guardrail packet from a small materialized artifact root. It does not prove Diana HRD interpretation readiness. BRAF V600E recovery is partial evidence only; SV/CNA benchmarking, purity sensitivity, and HRD interpretation remain blocked or no-call until build-matched caller output, transferred or indexed purity inputs, and production HRD adapters are available.
