# Diana Private Raw S3 Upload And Transfer

Use this guide when an approved sender needs to deliver private raw files to the Diana Omics S3 inbox. The instructions are sender- and vendor-agnostic; the sender may upload from a workstation, VM, or another cloud bucket.

## Private Destination

The Diana operator assigns one batch prefix:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/
```

Upload only to that exact prefix. Do not place Diana files under `cache/phase3_wgs/`, `s3://diana-omics-results-...`, or `s3://diana-omics-work-...`.

The inbox is private controlled-access storage. It must not allow anonymous listing, `head-object`, or downloads. Never use `--no-sign-request`, publish direct object URLs, or describe this prefix as a public dataset. If anonymous access succeeds, stop the transfer and report a security incident to the Diana operator.

## Access And Credential Handoff

Every upload requires Diana-issued AWS credentials for an IAM principal scoped to the assigned batch prefix. A typical sender policy permits only:

- `s3:ListBucket` constrained to the assigned prefix.
- Object and multipart-upload writes beneath the assigned prefix.
- The minimum KMS encrypt/data-key operations required by the destination policy.

The sender must not receive object reads, deletes, parent-prefix listing, or access to another batch. The Diana operator should deactivate the credentials immediately after acceptance.

The operator may email the non-secret guide, assigned prefix, expected IAM ARN, and expiration time. Do not email any AWS access key, secret access key, session token, credential file, or secret-sharing URL containing the credentials. Exchange credentials only through the approved secret manager or one-time secret channel, separately from ordinary email and tickets. Never commit credentials or paste them into logs.

## Destination Encryption

Use destination SSE-KMS. Unless the scoped policy supplied by the Diana operator explicitly requires bucket-default KMS with no request headers, pass:

```sh
--sse aws:kms --sse-kms-key-id 45aa290c-d70c-4d86-9c8d-c4a76f1ff97f
```

If the operator confirms that the actual scoped policy requires bucket-default KMS, omit both flags and let the bucket apply its default KMS key. The scoped policy is authoritative. Do not substitute `AES256`, a sender-owned key, or an unapproved KMS key. The Diana operator must verify the resulting `aws:kms` metadata and expected destination key after upload.

## Delivery Contents

Keep raw and derived source files under `data/`. Include required indexes, source QC, and reports. Include:

- `manifest.csv`, one row per delivered object.
- `checksums.sha256`, generated from the source files before upload.

Recommended manifest header:

```csv
dataset,sample_id,role,assay,data_type,relative_path,size_bytes,sha256,reference_build,source_vendor,notes
```

Preserve the source's sample identifiers and explicitly record assay, tumor/normal or RNA role, pairing, reference build, file type, byte size, SHA-256, and provenance. Do not infer that files from different assays or workflows are interchangeable.

Generate checksums from the delivery root:

```sh
find data -type f -print0 | sort -z | xargs -0 sha256sum > checksums.sha256
```

Confirm every data file appears exactly once in both the manifest and checksum file.

## Configure AWS CLI Credentials

Load the securely supplied credentials without writing the secret to shell history:

```sh
read -r -p "AWS access key ID: " AWS_ACCESS_KEY_ID
read -r -s -p "AWS secret access key: " AWS_SECRET_ACCESS_KEY
echo
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=us-east-1
```

If the operator supplied a temporary session token, read and export it the same way:

```sh
read -r -s -p "AWS session token: " AWS_SESSION_TOKEN
echo
export AWS_SESSION_TOKEN
```

Verify the identity before transferring anything:

```sh
aws sts get-caller-identity --query Arn --output text
```

It must exactly match the expected ARN supplied by the Diana operator.

## Upload Local Files

Set the destination and encryption arguments in Bash:

```bash
DEST="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/"
SSE_ARGS=(--sse aws:kms --sse-kms-key-id 45aa290c-d70c-4d86-9c8d-c4a76f1ff97f)
```

Only when the operator says the scoped policy requires bucket-default KMS, use `SSE_ARGS=()` instead.

Preview and then upload the data. Upload the manifest and checksum file last:

```bash
aws s3 cp data/ "${DEST}data/" --recursive "${SSE_ARGS[@]}" --dryrun --region us-east-1
aws s3 cp data/ "${DEST}data/" --recursive "${SSE_ARGS[@]}" --region us-east-1 --only-show-errors
aws s3 cp manifest.csv "${DEST}manifest.csv" "${SSE_ARGS[@]}" --region us-east-1 --only-show-errors
aws s3 cp checksums.sha256 "${DEST}checksums.sha256" "${SSE_ARGS[@]}" --region us-east-1 --only-show-errors
```

The AWS CLI uses multipart upload for large files. Rerun an interrupted command. Because the sender cannot read or delete existing objects, contact the Diana operator before replacing or correcting an uploaded key.

## Transfer From Another S3 Bucket

The transfer principal also needs source `ListBucket`/`GetObject` access and source-key decrypt permission when applicable. Use the same approved destination SSE-KMS mode:

```bash
SOURCE="s3://SOURCE-BUCKET/SOURCE-PREFIX/"
DEST="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/"
SSE_ARGS=(--sse aws:kms --sse-kms-key-id 45aa290c-d70c-4d86-9c8d-c4a76f1ff97f)

aws s3 cp "$SOURCE" "${DEST}data/" \
  --recursive \
  "${SSE_ARGS[@]}" \
  --source-region SOURCE-REGION \
  --region us-east-1 \
  --only-show-errors
```

Use `SSE_ARGS=()` only when the Diana operator confirms bucket-default KMS is required by the actual scoped policy.

## Sender Confirmation

If the scoped credentials include prefix-constrained listing, record the signed inventory:

```sh
aws s3 ls "s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/" --recursive --summarize --region us-east-1
```

Send the operator only the object count, total bytes, manifest/checksum filenames, and any warnings or retries. Do not send credentials. The sender's inability to read objects is expected.

Then remove credentials from the environment:

```sh
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION
```

## Diana Operator Acceptance

Using an authorized Diana read principal, the operator must:

1. Reconcile the signed prefix inventory with the sender's object count and total bytes.
2. Run `head-object` on representative data, manifest, and checksum objects. Confirm `ServerSideEncryption` is `aws:kms` and that the KMS key matches the approved destination policy.
3. Stage the private delivery in an approved private analysis location and run `sha256sum -c checksums.sha256` from the delivery root.
4. Reconcile every file, size, checksum, assay, role, pairing, index, and reference build against `manifest.csv`.
5. Run strict Diana raw intake validation only after those checks pass.
6. Deactivate the sender credentials immediately after acceptance.

Do not begin interpretation from inbox files until custody, checksum, reference, index, and tumor-normal pairing checks pass.

For Google Compute Engine, follow [GCE to Diana private S3 upload](gce-s3-upload.md).
