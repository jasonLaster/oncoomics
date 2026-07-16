# Diana Public Data Downloads

Use this document when you need to browse or copy the public Diana Omics dataset.

## Public Dataset

Browse the live file tree at [data.diana-tnbc.com](https://data.diana-tnbc.com).

The public S3 prefix is:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/
```

The prefix is anonymously listable and readable. No Diana-issued AWS credentials or presigned URLs are required. Check the live file tree for the current file count, size, and most recent update before starting a transfer.

## Choose A Download Method

| Destination | Recommended method |
| --- | --- |
| One file | Browser or `curl` |
| Local computer | AWS CLI anonymous `sync` |
| Another S3 bucket | AWS CLI authenticated `sync` |
| Google Compute Engine VM | AWS CLI anonymous `sync` to an attached disk |
| Google Cloud Storage | GCE staging disk or Storage Transfer Service |
| Box | Download locally, then upload with Box CLI |

## Before You Start

- Make sure the destination has enough free space for the files you select.
- Prefer `sync` for large transfers. It can be rerun to copy missing or changed files.
- Keep the directory structure intact so manifests, indexes, and checksums stay beside the sequencing files they describe.
- Use the checksums included with each delivery to verify the completed copy.
- FASTQ and BAM files can be tens of gigabytes each. Confirm destination file-size and storage limits, especially for Box.

## Browse Or Download One File

Use the [live file tree](https://data.diana-tnbc.com) to expand folders and download individual files.

Every object also has a direct HTTPS URL. For example:

```bash
curl -L -O "https://diana-omics-raw-inputs-172630973301-us-east-1.s3.us-east-1.amazonaws.com/diana/inbox/2026-07-14-echo-personalis/manifest.csv"
```

Use `curl -C -` to resume a partially downloaded large file:

```bash
curl -L -C - -O "HTTPS_OBJECT_URL"
```

## Download To A Local Computer

Install the AWS CLI, then preview the inventory:

```bash
SOURCE="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/"

aws s3 ls "$SOURCE" \
  --recursive \
  --human-readable \
  --summarize \
  --no-sign-request
```

Download everything:

```bash
aws s3 sync "$SOURCE" ./diana-inbox/ \
  --no-sign-request \
  --only-show-errors
```

Rerun the same command after an interruption. `sync` skips local files that already match the source.

Download only one subtree:

```bash
aws s3 sync \
  "${SOURCE}2026-07-14-echo-personalis/data/wgs/" \
  ./diana-wgs/ \
  --no-sign-request \
  --only-show-errors
```

Download only selected file types:

```bash
aws s3 sync "$SOURCE" ./diana-indexes-and-manifests/ \
  --no-sign-request \
  --exclude "*" \
  --include "*.csv" \
  --include "*.sha256" \
  --include "*.txt" \
  --include "*.bai"
```

## Copy Directly To Another S3 Bucket

Use AWS credentials that can list and write to the destination bucket. Do not add `--no-sign-request` to this command: the destination write must be signed, and the public source also accepts authenticated reads.

```bash
SOURCE="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/"
DEST="s3://DESTINATION_BUCKET/diana-inbox/"
DEST_REGION="us-east-1"

aws sts get-caller-identity

aws s3 sync "$SOURCE" "$DEST" \
  --source-region us-east-1 \
  --region "$DEST_REGION" \
  --only-show-errors
```

For a KMS-encrypted destination, add:

```bash
--sse aws:kms --sse-kms-key-id "KMS_KEY_ARN"
```

The active AWS principal needs destination permissions such as `s3:ListBucket`, `s3:PutObject`, multipart-upload permissions, and KMS permissions when a customer-managed destination key is used.

## Download To A Google Compute Engine VM

Attach or select a persistent disk with enough free space, install the AWS CLI on the VM, and download anonymously:

```bash
SOURCE="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/"
DEST="/mnt/disks/diana-data/diana-inbox/"

mkdir -p "$DEST"

aws s3 sync "$SOURCE" "$DEST" \
  --no-sign-request \
  --only-show-errors
```

Run the command inside `tmux` or `screen` so an SSH disconnect does not stop the transfer. Rerun it to resume at the object level.

## Copy To Google Cloud Storage

### Stage Through A GCE Disk

First download to the VM as shown above. Then authenticate `gcloud` for a principal that can write to the destination bucket and upload the local tree:

```bash
gcloud storage rsync \
  /mnt/disks/diana-data/diana-inbox/ \
  gs://DESTINATION_BUCKET/diana-inbox/ \
  --recursive
```

This route requires temporary disk space on the VM but does not require AWS credentials for the public source.

### Use Storage Transfer Service

Google Storage Transfer Service can perform a managed S3-to-GCS transfer without a GCE staging disk:

```bash
gcloud transfer jobs create \
  s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/ \
  gs://DESTINATION_BUCKET/diana-inbox/ \
  --source-creds-file=aws-source-creds.json
```

Google requires AWS source credentials for this managed path. Use short-lived, minimally scoped credentials, configure the Google service agent and destination permissions, and follow the current Storage Transfer Service documentation before starting the job.

## Upload To Box

For a complete transfer, first download the dataset to local or attached storage. Then install and authenticate the Box CLI and upload the directory to an existing Box parent folder:

```bash
box folders:upload ./diana-inbox \
  --parent-folder="BOX_PARENT_FOLDER_ID"
```

Before uploading, confirm that the Box plan has enough storage and allows files as large as the biggest BAM or FASTQ in the dataset. For a small subset, downloading individual files from the web file tree and placing them in Box Drive can be more convenient.

## Verify The Copy

Start with the delivery manifest:

```bash
head -n 5 diana-inbox/2026-07-14-echo-personalis/manifest.csv
```

Then verify the supplied SHA-256 checksums from the delivery directory:

```bash
cd diana-inbox/2026-07-14-echo-personalis
sha256sum -c checksums.sha256
```

On macOS, use:

```bash
shasum -a 256 -c checksums.sha256
```

Do not treat a transfer as complete until the expected object count, total bytes, and checksums agree with the source manifest.

## Troubleshooting

- `AccessDenied` while downloading locally usually means `--no-sign-request` was omitted or a stale AWS profile is interfering.
- `AccessDenied` on S3-to-S3 copies usually concerns the destination bucket or destination KMS key.
- Rerun `aws s3 sync` after a disconnect; it compares the source and destination and copies missing or changed objects.
- If a Box upload rejects a large file, check the plan's per-file upload limit before retrying.
- If a GCE disk fills, expand the persistent disk and filesystem before rerunning the sync.

## Related Documentation

- [Diana raw input intake contract](diana-raw-inputs.md)
- [Diana raw S3 upload and transfer guide](diana-raw-s3-upload.md)

## External References

- [AWS CLI high-level S3 commands](https://docs.aws.amazon.com/cli/latest/userguide/cli-services-s3-commands.html)
- [AWS CLI `s3 sync` reference](https://docs.aws.amazon.com/cli/latest/reference/s3/sync.html)
- [Google Storage Transfer Service: Amazon S3 to Cloud Storage](https://docs.cloud.google.com/storage-transfer/docs/create-transfers/agentless/s3)
- [Box: upload all files in a folder](https://developer.box.com/guides/uploads/chunked/folder)
