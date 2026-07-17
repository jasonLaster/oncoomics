# Public analysis access

The dataset owner authorized unrestricted public distribution of the Diana WGS
analysis for collaborator access and public cross-reference. The reviewed public
surface is pseudonymous and available without AWS credentials at:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/
```

Browse exact public keys through:

- [data.diana-tnbc.com](https://data.diana-tnbc.com/)
- [public-index/objects.json](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json)

Anonymous bucket listing and historical-version reads remain denied. The public
alias contains reviewed summaries, QC, coarse coverage-CNV evidence, filtered
HRR VCFs reheadered to `subject01_normal` and `subject01_tumor`, variant review,
and superseded pre-data Rosalind protocol packets. It excludes raw FASTQs, BAMs,
contamination pileups, direct source identifiers, logs, and custody inventories.

## Direct result links

- [Publication manifest](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/publication_manifest.json)
- [Early-look summary](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/artifacts/early_look_summary.json)
- [HRR variant summary](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/artifacts/variants/core_hrr_variant_summary.json)
- [PASS HRR variants](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/artifacts/variants/core_hrr_pass_variants.csv)
- [Filtered HRR VCF](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/artifacts/variants/core_hrr.mutect2.filtered.vcf.gz)
- [Coverage-CNV bins](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/artifacts/coverage_cnv/coverage_cnv_bins.csv)

The early-look state remains `partial_evidence`, and overall HRD remains
`no_call`. Public availability does not widen that interpretation boundary.
