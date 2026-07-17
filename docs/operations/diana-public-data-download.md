# Diana Public Analysis Downloads

Use this guide to browse, cite, or copy reviewed Diana Omics analysis outputs.
The public surface is intentionally available to outside collaborators without
AWS credentials. Raw deliveries, FASTQs, BAMs, and direct identifiers are not
part of this surface.

## Browse the reviewed index

Browse the live file tree at [data.diana-tnbc.com](https://data.diana-tnbc.com/).
The site reads the reviewed static index at:

```text
https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json
```

The index contains only current objects under exact Terraform-allowlisted
prefixes. The bucket does not allow anonymous bucket listing, object-version
listing, or historical-version reads.

## Diana WGS HRD analysis

The public root for the current alias-only WGS analysis is:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/
```

The recovered early-look analysis is under:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/
```

Final deterministic, Rosalind, and cross-check reports should be published as
reviewed subtrees under the same alias-only root. The corresponding Rosalind
HRD packet root is:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/rosalind/
```

These paths identify a run alias, not a patient name. Conclusions must preserve
`partial_evidence`, `blocked`, and `no_call` boundaries from the source reports.

## Download one object

Use the live index to find a key, then convert it to a direct HTTPS URL:

```bash
BUCKET=diana-omics-results-172630973301-us-east-1
KEY='runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/artifacts/early_look_summary.json'

curl --fail --location --remote-name \
  "https://${BUCKET}.s3.us-east-1.amazonaws.com/${KEY}"
```

Use `curl -C -` to resume a partial large download.

## Download a reviewed subtree

The results bucket intentionally denies anonymous listing, so discover exact
keys from `public-index/objects.json`. Download those keys individually, or use
an authenticated collaborator identity when a managed bulk transfer requires
S3 listing.

For a small anonymous manifest-driven copy:

```bash
curl --fail --location \
  'https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json' \
  --output diana-public-objects.json

jq -r '.objects[] | select(.key | startswith("runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/")) | .key' \
  diana-public-objects.json
```

Use the recorded byte size and any report manifest SHA-256 values to verify the
copy. Method-report manifests are the canonical integrity and provenance
surface for deterministic, Rosalind, and cross-check reports.

## Citation and cross-reference policy

- Cite the direct HTTPS object URL and the run identifier.
- Prefer `report.md`, `report_manifest.json`, packet indexes, and explicit
  publication receipts over transient logs.
- Keep public validation evidence, sample-derived evidence, and external
  research context distinct.
- Do not promote a public `no_call` or `partial_evidence` report into a clinical
  conclusion.
- Do not copy raw uploads, FASTQs, BAMs, direct identifiers, or private
  version-history receipts into a public prefix.

## Related documentation

- [Diana raw input intake contract](diana-raw-inputs.md)
- [GCE to Diana S3 upload](gce-s3-upload.md)
- [Rosalind HRD workflow](../rosalind/hrd-workflow.md)
