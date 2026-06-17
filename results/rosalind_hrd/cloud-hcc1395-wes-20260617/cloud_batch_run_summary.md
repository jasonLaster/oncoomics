# Cloud HCC1395 WES Batch Run Summary

Run ID: `cloud-hcc1395-wes-20260617`

## Result

| Field | Value |
| --- | --- |
| AWS Batch job | `e616e07e-2a4a-479d-a305-33e1e67df13f` |
| Status | `SUCCEEDED` |
| Exit code | `0` |
| Region | `us-east-1` |
| Queue | `diana-omics-prod-use1-ondemand` |
| Image | `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:hrd-packet-20260617T060000Z` |
| Source commit | `5e73953960e5e798028b4a6ceb2cfe6765b83a0f` |
| S3 prefix | `s3://diana-omics-results-172630973301-us-east-1/runs/rosalind_hrd/cloud-hcc1395-wes-20260617` |
| CloudWatch stream | `nf-172630973301-dkr-ecr-us-east-1-amazonaws-com-diana-omics-hrd-packet-20260617T060000Z/default/5307dde3201048fdafe39dfa217ac0f7` |

## Command Path

This run used the reusable cloud submit wrapper with the HCC1395 WES materialized artifact root:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set hcc1395_wes --artifact-root-rel artifacts/hcc1395_wes_validation --run-id cloud-hcc1395-wes-20260617
```

The Batch job downloaded the pushed archive for commit `5e73953960e5e798028b4a6ceb2cfe6765b83a0f`, read WES validation evidence from `artifacts/hcc1395_wes_validation`, and uploaded generated packet outputs to S3.

## Packet Result

| Metric | Value |
| --- | --- |
| Sample set | `hcc1395_wes` |
| Evidence rows | `5` |
| Adapter rows | `6` |
| Packet blocker count | `0` |
| Packet index SHA-256 | `f31634a55b22bf72dce25f79251d82e599bb65142702225a7a87c728e8063eba` |
| Run manifest SHA-256 | `d419aa4d4ceec7b6bd6e5725decbe1bde135708ffcd9030aa737e7f8ffbfffcc` |
| Reviewer packet SHA-256 | `90ce9bb4bd375f4b84c6c9c42d69b358fd9b0e6cd28c9c173c3e03aff8f74eb1` |

## Interpretation Boundary

This run proves the cloud submit wrapper can execute the SEQC2/HCC1395 WES readiness packet from a small materialized artifact root. It validates packet reproducibility for WES FASTQ/BAM validation and Mutect2 truth-overlap summaries. It does not produce a genome-wide HRD score; biallelic/LOH, SBS3, scarHRD, CHORD, and HRDetect-style interpretation remain no-call until WGS-scale production adapters and locked validation evidence are available.
