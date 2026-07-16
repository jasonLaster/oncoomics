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

The inbox is a public-read landing zone with authenticated uploads:

- Any authenticated AWS principal can upload objects to `diana/inbox/*` when the request uses S3-managed `AES256` encryption.
- Anyone can list the `diana/inbox/` prefix and download its objects without AWS credentials.
- Uploaders do not need presigned URLs.
- Uploaders do not get delete access from this policy.
- Bucket-owner-enforced ownership makes uploaded objects owned by the Diana Omics bucket owner.
- Public objects use S3-managed `AES256` encryption because S3 does not permit anonymous reads of SSE-KMS objects.

Only upload data that is approved for unrestricted public distribution. This prefix is not appropriate for private or controlled-access data.

For external teams without an AWS account, provision temporary credentials with
an identity policy that restricts listing and writes to one batch prefix. Send
credentials through an approved secret-sharing channel, never email or a source
repository. Deactivate the access key after delivery acceptance.

For deliveries originating in Google Cloud, use the sender checklist in
`docs/operations/gce-s3-upload.md`.

## What To Include

Each delivery should include:

- Raw FASTQ, BAM, CRAM, VCF, CNV, SV, fusion, or report files.
- Required index files, such as BAI or CRAI.
- A file manifest with sample IDs, file names, assay type, tumor/normal role, reference build, and source/vendor.
- Checksums from the source system, preferably SHA-256.

## Upload From Local Files

Use `aws s3 cp --recursive` or individual `aws s3 cp` commands:

```sh
aws s3 cp /path/to/diana-files/ s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/ --recursive --sse AES256 --region us-east-1 --only-show-errors
```

Upload the manifest and checksum files into the same batch folder:

```sh
aws s3 cp manifest.csv s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/manifest.csv --sse AES256 --region us-east-1 --only-show-errors
aws s3 cp checksums.sha256 s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/checksums.sha256 --sse AES256 --region us-east-1 --only-show-errors
```

## Transfer From Bucket A To Our Bucket

The source bucket owner must grant the transfer principal read access to `s3://SOURCE-BUCKET/SOURCE-PREFIX/`. Then run:

```sh
aws s3 cp s3://SOURCE-BUCKET/SOURCE-PREFIX/ s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/ --recursive --sse AES256 --source-region SOURCE-REGION --region us-east-1 --only-show-errors
```

If the source files use a source KMS key, the transfer principal also needs decrypt permission on that source key. The destination copy must still specify `--sse AES256` so the result is anonymously readable.

## Verify The Transfer

The uploader can list the inbox prefix after upload:

```sh
aws s3 ls s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/ --recursive --summarize --region us-east-1
```

Spot-check one object without credentials:

```sh
aws s3api head-object --bucket diana-omics-raw-inputs-172630973301-us-east-1 --key diana/inbox/YYYY-MM-DD-source-name/example.fastq.gz --region us-east-1 --no-sign-request
```

The uploader and Diana operator can both verify the public object metadata, prefix listing, and source-side checksums without credentials.

Compare the delivered checksum manifest against the source checksums before using the files for intake validation. Do not run Diana interpretation from inbox files until manifests, tumor-normal pairing, references, indexes, and checksums pass validation.
