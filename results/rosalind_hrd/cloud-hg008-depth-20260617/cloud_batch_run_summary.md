# Cloud HG008 Depth Batch Run Summary

Run ID: `cloud-hg008-depth-20260617`

## Result

| Field | Value |
| --- | --- |
| AWS Batch job | `8a01caf6-5439-4c54-b068-2ecd5d325269` |
| Status | `SUCCEEDED` |
| Exit code | `0` |
| Region | `us-east-1` |
| Queue | `diana-omics-prod-use1-ondemand` |
| Image | `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:hrd-packet-20260617T060000Z` |
| Source commit | `774cbf7c0af091404616fab72a8f5c3c12ed9423` |
| S3 prefix | `s3://diana-omics-results-172630973301-us-east-1/runs/rosalind_hrd/cloud-hg008-depth-20260617` |
| CloudWatch stream | `nf-172630973301-dkr-ecr-us-east-1-amazonaws-com-diana-omics-hrd-packet-20260617T060000Z/default/e36852de96e54f2eb42137b833cc8d62` |

## Command Path

This run used the reusable cloud submit wrapper with the HG008 materialized artifact root:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set hg008 --artifact-root-rel artifacts/hg008_depth_validation --run-id cloud-hg008-depth-20260617
```

The Batch job downloaded the pushed archive for commit `774cbf7c0af091404616fab72a8f5c3c12ed9423`, read HG008 packet evidence from `artifacts/hg008_depth_validation`, and uploaded generated packet outputs to S3.

## Packet Result

| Metric | Value |
| --- | --- |
| Sample set | `hg008` |
| Evidence rows | `4` |
| Adapter rows | `4` |
| Packet blocker count | `2` |
| Packet index SHA-256 | `746f34033cf22f75be3788ce17d943f5808996ddd0f3295aa450270c06230633` |
| Run manifest SHA-256 | `28cf1dc456cace397bea91b98d8ef5a69461eb72c9bfbd31d9ae867eb806a16e` |
| Reviewer packet SHA-256 | `5072a636785deb7c2bb8acae165862ca1269418d6abdba6daa6a307d8750a5f8` |

## Interpretation Boundary

This run proves the cloud submit wrapper can execute the HG008 truth-set packet from a small materialized artifact root. It does not prove Diana HRD interpretation readiness. HG008 remains a validation sample with partial SNV and bounded CNV depth evidence; CNV segment overlap, SV reciprocal overlap, and HRD interpretation remain blocked or no-call.
