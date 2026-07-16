# Diana WGS HRD early-look handoff

This directory is the Git-tracked handoff for the Diana matched tumor-normal
WGS early-look run. The complete evidence bundle is anonymously available in
public S3; Git intentionally retains the reports and public manifest, not local
mirrors of large evidence objects.

- Full-run ID: `diana-wgs-hrd-20260716T033101Z`
- Successful early-look ID: `early-look-intersected-20260716T150517Z`
- Successful AWS Batch job: `a1aa4109-4b38-46a4-9b58-bfe6335b02d4`
- Early-look completion: 2026-07-16 08:32:54 PDT
- Packet materialized locally: 2026-07-16
- Evidence state: `partial_evidence`
- Overall HRD state: `no_call`

Start with [HANDOFF.md](HANDOFF.md), then follow [NEXT_STEPS.md](NEXT_STEPS.md).
Public access details and download commands are in [PUBLIC_DATA.md](PUBLIC_DATA.md).
Object sizes, ETags, encryption, and direct URLs are indexed in
[PUBLIC_S3_MANIFEST.tsv](PUBLIC_S3_MANIFEST.tsv).

## Public dataset

- S3: `s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/`
- HTTPS: <https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/?list-type=2&prefix=runs%2Fdiana-hrd%2Fdiana-wgs-hrd-20260716T033101Z%2Fearly-look%2Fearly-look-intersected-20260716T150517Z%2F>
- Machine-readable summary: <https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/early_look_summary.json>

## Public object map

- `artifacts/`: all objects emitted by the successful early-look job,
  including complete contamination pileups, coverage-CNV bins, QC, and VCFs.
- `handoff/annotations/`: Ensembl consequence annotation for the
  filtered callset.
- `inputs/validated_bams/`: validated tumor/normal BAMs, indexes, and QC sidecars.
- `inputs/caller_resources/`: exact GATK, PoN, gnomAD, and common-sites inputs.
- `inputs/reference/`: exact hg38 analysis reference and indexes.
- `handoff/references/`: Ensembl release 116 GFF3/checksums and dated ClinVar page
  snapshots for the two reviewed BRCA variants.
- `handoff/provenance/`: AWS Batch descriptions, CloudWatch log, worker scripts, and
  S3 artifact inventory.

## Data-handling boundary

The dataset owner explicitly authorized unrestricted public distribution on
2026-07-16. All current objects in the results bucket are anonymously listable
and readable; no AWS credentials or presigned URLs are required. See
`PUBLIC_DATA.md` for the separate noncurrent-version boundary.
