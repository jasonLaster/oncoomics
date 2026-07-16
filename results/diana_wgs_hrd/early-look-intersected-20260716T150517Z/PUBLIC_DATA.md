# Public S3 access

The entire `diana-omics-results-172630973301-us-east-1` bucket is anonymously
listable and readable over HTTPS. Objects use SSE-S3 (`AES256`), and insecure
HTTP requests remain denied.
The same access, encryption, and CORS configuration is declared in
`infra/aws/main.tf` so a future Terraform apply preserves this public state.

## Early-look run

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/
```

Browse the run as S3 XML:

<https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/?list-type=2&prefix=runs%2Fdiana-hrd%2Fdiana-wgs-hrd-20260716T033101Z%2Fearly-look%2Fearly-look-intersected-20260716T150517Z%2F>

The Git-tracked `PUBLIC_S3_MANIFEST.tsv` records each public object present
when this packet was published, including bytes, ETag, encryption, and URL;
the manifest excludes only its own S3 object.

Download the full run anonymously:

```bash
aws s3 sync \
  s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/ \
  ./early-look-intersected-20260716T150517Z/ \
  --no-sign-request --only-show-errors
```

List the entire public results bucket:

```bash
aws s3 ls s3://diana-omics-results-172630973301-us-east-1/ \
  --recursive --human-readable --summarize --no-sign-request
```

## Direct result links

- [Public S3 manifest](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/handoff/PUBLIC_S3_MANIFEST.tsv)
- [Early-look summary](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/early_look_summary.json)
- [PASS HRR variants](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/variants/core_hrr_pass_variants.csv)
- [Filtered VCF](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/variants/core_hrr.mutect2.filtered.vcf.gz)
- [Coverage-CNV bins](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/coverage_cnv/coverage_cnv_bins.csv)
- [Contamination summary](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/contamination/contamination_summary.json)
- [BAM QC summary](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/qc/bam_qc_summary.json)
