# Diana Private Raw Data Retrieval

> The filename is retained to avoid breaking existing links. Diana raw data is not a public dataset.

Use this document when an authorized Diana operator needs to retrieve or transfer an accepted private delivery. The raw inbox must not be anonymously listable or readable. Do not use `--no-sign-request`, public object URLs, or the legacy public file-tree workflow.

If anonymous S3 listing, `head-object`, or download succeeds, stop and report a security incident. Do not treat successful anonymous access as authorization.

## Private Source

Work only within the approved batch prefix:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/
```

Retrieval requires an authenticated Diana-approved principal with read access to that batch. Sender upload credentials are intentionally write-only and must not be reused for retrieval.

Never email AWS credentials. Exchange access keys, secret keys, session tokens, or credential files only through the approved secret manager or one-time secret channel. Keep credentials out of source control, tickets, command logs, and transfer manifests.

## Before Retrieval

- Confirm the expected IAM ARN, batch prefix, access expiration, and approved destination.
- Confirm the destination is private, encrypted, and approved for the data classification.
- Ensure there is enough space for the selected files and checksum verification.
- Keep delivery structure intact so indexes, manifests, and checksum files remain beside their data.
- Do not copy private raw data to personal storage, Box, public GCS/S3, or another service without explicit data-owner approval.

Verify the authenticated identity:

```sh
aws sts get-caller-identity --query Arn --output text
```

Stop if it does not exactly match the expected authorized ARN.

## Retrieve To An Approved Local Or Attached Disk

Preview the signed inventory:

```bash
SOURCE="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/"
DEST="/approved/private-storage/YYYY-MM-DD-source-name/"

aws s3 ls "$SOURCE" --recursive --human-readable --summarize --region us-east-1
aws s3 sync "$SOURCE" "$DEST" --dryrun --region us-east-1
```

Retrieve the delivery:

```sh
aws s3 sync "$SOURCE" "$DEST" --region us-east-1 --only-show-errors
```

Rerun the same command after an interruption. `sync` resumes at object boundaries.

## Retrieve On Google Compute Engine

Use an approved GCE VM and encrypted persistent disk. Install AWS CLI v2 as described in [GCE to Diana private S3 upload](gce-s3-upload.md), load approved read credentials through the secure channel, verify the expected ARN, and run the authenticated `aws s3 sync` command above. Do not use anonymous flags.

To copy the verified delivery into an approved private GCS bucket:

```sh
gcloud storage rsync \
  /approved/private-storage/YYYY-MM-DD-source-name/ \
  gs://APPROVED-PRIVATE-BUCKET/YYYY-MM-DD-source-name/ \
  --recursive
```

Confirm the active Google principal and destination IAM policy before copying. A direct managed S3-to-GCS transfer requires a separately approved, time-bound AWS read credential; do not place its credential file in email or source control.

## Copy To Another Approved S3 Bucket

The authenticated principal needs source read access and destination list/write access. Add the destination's approved encryption settings:

```bash
SOURCE="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/"
DEST="s3://APPROVED-PRIVATE-BUCKET/YYYY-MM-DD-source-name/"

aws s3 sync "$SOURCE" "$DEST" \
  --source-region us-east-1 \
  --region DESTINATION-REGION \
  --sse aws:kms \
  --sse-kms-key-id DESTINATION-KMS-KEY-ID \
  --only-show-errors
```

The destination key and permissions must be approved for this dataset. Do not reuse the Diana inbox key automatically for another account or bucket.

## Verify The Retrieved Copy

From the delivery root, reconcile the manifest and run the supplied SHA-256 checks:

```sh
cd /approved/private-storage/YYYY-MM-DD-source-name
sha256sum -c checksums.sha256
```

On macOS:

```sh
shasum -a 256 -c checksums.sha256
```

Do not accept the retrieval until object count, total bytes, manifest entries, and every checksum agree. Record the source prefix, authorized ARN, transfer time, destination, and verification result in the private custody log.

Remove temporary credentials when complete:

```sh
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION
```

## Troubleshooting

- `AccessDenied` is expected when a principal lacks authorized list/read access; do not retry anonymously.
- A sender's upload credential normally cannot retrieve or inspect objects.
- KMS failures require both S3 read permission and decrypt permission on the source key.
- If the approved destination changes, stop and obtain updated authorization rather than redirecting the transfer ad hoc.

## Related Documentation

- [Diana raw input intake contract](diana-raw-inputs.md)
- [Diana private raw S3 upload and transfer guide](diana-raw-s3-upload.md)
