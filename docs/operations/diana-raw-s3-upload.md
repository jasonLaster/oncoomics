# Diana Raw S3 Upload And Transfer

Use this when Diana raw files need to land in the Diana Omics private S3 intake area.

## Destination

Upload only to:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/
```

Use these sub-prefixes:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/incoming/
s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/manifests/
s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/validated/
```

Do not upload Diana files under `cache/phase3_wgs/`, `s3://diana-omics-results-...`, or `s3://diana-omics-work-...`.

## What To Include

Each delivery should include:

- Raw FASTQ, BAM, CRAM, VCF, CNV, SV, fusion, or report files.
- Required index files, such as BAI or CRAI.
- A file manifest with sample IDs, file names, assay type, tumor/normal role, reference build, and source/vendor.
- Checksums from the source system, preferably SHA-256.

Keep each delivery under a batch-specific folder:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/incoming/YYYY-MM-DD-source-name/
```

## Option 1: Upload With A Presigned URL

Use this when a collaborator has local files but should not receive AWS credentials. Generate one URL per object:

```sh
python3 scripts/presign_s3_put.py s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/incoming/YYYY-MM-DD-source-name/example.fastq.gz --expires-in 604800
```

Send the URL privately. The collaborator uploads with:

```sh
curl --upload-file example.fastq.gz "PRESIGNED_URL"
```

The URL allows upload only to that exact object key until it expires. Treat it like a secret.

## Option 2: Upload With AWS Credentials

Use this when the uploader has an approved AWS principal with write access to the private intake prefix:

```sh
aws s3 sync /path/to/diana-files/ s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/incoming/YYYY-MM-DD-source-name/ --region us-east-1 --only-show-errors
```

Then upload the manifest and checksum files:

```sh
aws s3 cp manifest.csv s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/manifests/YYYY-MM-DD-source-name/manifest.csv --region us-east-1 --only-show-errors
aws s3 cp checksums.sha256 s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/manifests/YYYY-MM-DD-source-name/checksums.sha256 --region us-east-1 --only-show-errors
```

## Option 3: Transfer From Bucket A To Our Bucket

Preferred path: ask the source bucket owner to grant read access to the Diana transfer operator or role, then run the copy from our side. That keeps ownership and encryption under our bucket policy.

```sh
aws s3 sync s3://SOURCE-BUCKET/SOURCE-PREFIX/ s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/incoming/YYYY-MM-DD-source-name/ --source-region SOURCE-REGION --region us-east-1 --only-show-errors
```

If the source files use a source KMS key, the transfer principal also needs decrypt permission on that source key. Our destination bucket applies its own SSE-KMS encryption.

If the source bucket owner must push into our bucket, create a narrow temporary permission for their AWS principal covering only:

```text
s3:PutObject on arn:aws:s3:::diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/incoming/YYYY-MM-DD-source-name/*
kms:Encrypt and kms:GenerateDataKey on the Diana Omics KMS key
```

Do not grant broad bucket write access.

## Verify The Transfer

List the destination:

```sh
aws s3 ls s3://diana-omics-raw-inputs-172630973301-us-east-1/private/diana/raw-intake/incoming/YYYY-MM-DD-source-name/ --recursive --summarize --region us-east-1
```

Spot-check one object:

```sh
aws s3api head-object --bucket diana-omics-raw-inputs-172630973301-us-east-1 --key private/diana/raw-intake/incoming/YYYY-MM-DD-source-name/example.fastq.gz --region us-east-1
```

Compare the delivered checksum manifest against the source checksums before moving files from `incoming/` to `validated/`. Do not run Diana interpretation from `incoming/` files until manifests, tumor-normal pairing, references, indexes, and checksums pass validation.
