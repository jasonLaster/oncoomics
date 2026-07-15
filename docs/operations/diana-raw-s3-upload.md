# Diana Raw S3 Upload And Transfer

Use this when Diana raw files need to land in the Diana Omics S3 inbox.

## Destination

Upload or transfer only to:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/
```

Keep each delivery under a batch-specific folder:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/
```

Do not upload Diana files under `cache/phase3_wgs/`, `s3://diana-omics-results-...`, or `s3://diana-omics-work-...`.

## Access Model

The inbox is list-and-write for external uploaders:

- Any authenticated AWS principal can upload objects to `diana/inbox/*`.
- Any authenticated AWS principal can list the `diana/inbox/` prefix.
- Uploaders do not need presigned URLs.
- Uploaders do not get object download/read or delete access from this policy.
- Bucket-owner-enforced ownership makes uploaded objects owned by the Diana Omics bucket owner.
- The bucket still uses SSE-KMS encryption.
- The KMS policy permits decrypt operations only through S3 for inbox objects. S3 requires this for multipart uploads; it does not grant uploaders object read access.

This is intentionally an inbox, not a shared workspace.

## What To Include

Each delivery should include:

- Raw FASTQ, BAM, CRAM, VCF, CNV, SV, fusion, or report files.
- Required index files, such as BAI or CRAI.
- A file manifest with sample IDs, file names, assay type, tumor/normal role, reference build, and source/vendor.
- Checksums from the source system, preferably SHA-256.

## Upload From Local Files

Use `aws s3 cp --recursive` or individual `aws s3 cp` commands:

```sh
aws s3 cp /path/to/diana-files/ s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/ --recursive --region us-east-1 --only-show-errors
```

Upload the manifest and checksum files into the same batch folder:

```sh
aws s3 cp manifest.csv s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/manifest.csv --region us-east-1 --only-show-errors
aws s3 cp checksums.sha256 s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/checksums.sha256 --region us-east-1 --only-show-errors
```

## Transfer From Bucket A To Our Bucket

The source bucket owner must grant the transfer principal read access to `s3://SOURCE-BUCKET/SOURCE-PREFIX/`. Then run:

```sh
aws s3 cp s3://SOURCE-BUCKET/SOURCE-PREFIX/ s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/ --recursive --source-region SOURCE-REGION --region us-east-1 --only-show-errors
```

If the source files use a source KMS key, the transfer principal also needs decrypt permission on that source key. Our destination bucket applies the Diana Omics SSE-KMS encryption policy.

## Verify The Transfer

The uploader can list the inbox prefix after upload:

```sh
aws s3 ls s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/ --recursive --summarize --region us-east-1
```

Spot-check one object:

```sh
aws s3api head-object --bucket diana-omics-raw-inputs-172630973301-us-east-1 --key diana/inbox/YYYY-MM-DD-source-name/example.fastq.gz --region us-east-1
```

Compare the delivered checksum manifest against the source checksums before using the files for intake validation. Do not run Diana interpretation from inbox files until manifests, tumor-normal pairing, references, indexes, and checksums pass validation.
