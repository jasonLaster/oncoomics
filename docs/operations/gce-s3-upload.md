# GCE To Diana S3 Upload

Use this sender checklist to deliver one or more datasets from a Google Compute
Engine VM or Google Cloud Storage into the Diana Omics public-read,
sender-scoped S3 inbox. The process is vendor-agnostic: dataset and
organization names belong only in the assigned batch name and manifest, not in
the access model.

## Delivery Destination

The Diana operator will assign a batch name with this format:

```text
YYYY-MM-DD-source-name
```

Upload only to the assigned batch prefix:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-source-name/
```

Use descriptive subfolders to keep datasets and assays distinct:

```text
YYYY-MM-DD-source-name/
├── data/
│   ├── dataset-a/
│   └── dataset-b/
├── manifest.csv
└── checksums.sha256
```

Preserve source file names, sample roles, assay labels, and dataset boundaries.
Do not combine assays or infer that tumor, matched-normal, DNA, and RNA files are
interchangeable. The Diana operator will map the delivery into the analysis
samplesheet after receipt.

## Access And Expiration

The Diana operator will provide these values through an approved secret manager
or one-time secret channel:

- AWS access key ID and secret access key.
- Expected AWS identity ARN.
- Assigned batch name and exact destination prefix.
- Credential expiration time.

The operator may email the non-secret guide, assigned prefix, expected ARN, and
expiration time, but must not email the access key, secret key, session token,
credential file, or a credential-bearing secret URL. Do not commit or paste
credentials into tickets or logs. The temporary
credentials should:

- List and write only the assigned batch prefix.
- Prevent deletes, parent-inbox listing, and writes elsewhere.
- Expire shortly after the expected delivery window.

The destination must use S3-managed `AES256` encryption so public reads work
without AWS KMS grants. AWS S3 uses multipart upload for large genomics files;
the credential policy must include only the operations needed for multipart
upload beneath the assigned prefix.

Uploaded objects under `diana/inbox/` are publicly listable and readable. The
scoped sender credentials are still required for writes because anonymous
`PutObject` is denied.

## 1. Prepare The Delivery

Place every dataset below a common `data/` directory. Include the raw and derived
files supplied by the source, along with required indexes, QC outputs, and
reports. Examples include FASTQ pairs, BAM/CRAM plus BAI/CRAI, VCF/gVCF plus
indexes, CNV/SV outputs, expression or fusion outputs, and reports. Do not omit a
file solely because it is derived; identify its type and provenance in the
manifest.

Create `manifest.csv` with one row per delivered file and this header:

```csv
dataset,sample_id,role,assay,data_type,relative_path,size_bytes,sha256,reference_build,source_vendor,notes
```

Required details:

- `dataset`: the source dataset or product label.
- `sample_id`: the source sample identifier.
- `role`: tumor, matched normal, tumor RNA, report, or another accurate role.
- `assay`: the exact assay or workflow name.
- `data_type`: FASTQ, BAM, CRAM, VCF, CNV, SV, report, QC, or another precise type.
- `relative_path`: path below the delivery root, such as `data/wgs/sample_R1.fastq.gz`.
- `size_bytes` and `sha256`: source-side byte count and SHA-256 checksum.
- `reference_build`: for example GRCh38/hg38, or `not_applicable` for a report.
- `source_vendor`: the organization that produced the file.
- `notes`: library, lane, capture, pipeline version, or other provenance not represented elsewhere.

An existing source manifest is acceptable if it contains equivalent fields.
Identify tumor-normal pairing, reference build, and assay provenance explicitly
rather than inferring them from file names.

From the delivery root, generate a checksum file for the data directory:

```sh
find data -type f -print0 | sort -z | xargs -0 sha256sum > checksums.sha256
```

Confirm every data file appears once in both `manifest.csv` and
`checksums.sha256` before upload.

## 2. Configure The GCE VM

Use a GCE VM with an attached persistent disk, not the boot disk, for the
delivery working directory. The disk should have enough free space for the
staged files plus at least 20 percent headroom for manifests, checksums, and
retries. Keep the source GCS objects until Diana confirms acceptance.

If the source files exist only in GCS, stage each dataset onto the attached disk:

```sh
DELIVERY_ROOT=/mnt/diana-delivery
DATASET_NAME=replace-with-dataset-name
SOURCE_GCS_URI=gs://SOURCE-BUCKET/SOURCE-PREFIX/

mkdir -p "$DELIVERY_ROOT/data/$DATASET_NAME"
gcloud auth list
gcloud storage du --summarize "$SOURCE_GCS_URI"
df -h "$DELIVERY_ROOT"
gcloud storage rsync --recursive "$SOURCE_GCS_URI" "$DELIVERY_ROOT/data/$DATASET_NAME/"
```

Repeat the staging commands for each dataset. If the files are already on an
attached disk, set `DELIVERY_ROOT` to their common parent and skip the GCS copy.
Do not stream large files directly from `gcloud storage cat` into
`aws s3 cp -`; a broken pipe would need to restart the object and makes
source-side SHA-256 verification harder.

Install AWS CLI v2. This block supports the common x86-64 and Arm GCE machine
architectures:

```sh
case "$(uname -m)" in
  x86_64) AWSCLI_ARCH=x86_64 ;;
  aarch64|arm64) AWSCLI_ARCH=aarch64 ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

AWSCLI_TMP=$(mktemp -d)
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWSCLI_ARCH}.zip" -o "$AWSCLI_TMP/awscliv2.zip"
unzip -q "$AWSCLI_TMP/awscliv2.zip" -d "$AWSCLI_TMP"
if command -v aws >/dev/null 2>&1; then
  sudo "$AWSCLI_TMP/aws/install" --update
else
  sudo "$AWSCLI_TMP/aws/install"
fi
rm -rf "$AWSCLI_TMP"
aws --version
```

Load the securely shared credentials without placing the secret in shell
history:

```sh
read -r -p "AWS access key ID: " AWS_ACCESS_KEY_ID
read -r -s -p "AWS secret access key: " AWS_SECRET_ACCESS_KEY
echo
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true
```

If the operator supplied a session token, read it without echo and export it:

```sh
read -r -s -p "AWS session token: " AWS_SESSION_TOKEN
echo
export AWS_SESSION_TOKEN
```

Verify the identity:

```sh
aws sts get-caller-identity --query Arn --output text
```

The result must exactly match the expected ARN supplied by the Diana operator.
Stop and ask the operator if it does not match.

Run the transfer inside `tmux`, `screen`, or another persistent terminal so an
SSH disconnect does not stop the upload. The standard AWS CLI v2 multipart
defaults are suitable.

## 3. Upload The Delivery

Set the assigned batch name and paths:

```bash
: "${DELIVERY_ROOT:=/mnt/diana-delivery}"
BATCH_NAME=YYYY-MM-DD-source-name
DEST="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/${BATCH_NAME}/"
SSE_ARGS=(--sse AES256)
```

Replace `BATCH_NAME` with the exact value supplied by the Diana operator. Review
the planned object paths first.

```bash
aws s3 cp "$DELIVERY_ROOT/data/" "${DEST}data/" --recursive "${SSE_ARGS[@]}" --dryrun --region us-east-1
```

Upload the data directory, then upload the manifest and checksums last:

```bash
aws s3 cp "$DELIVERY_ROOT/data/" "${DEST}data/" --recursive "${SSE_ARGS[@]}" --region us-east-1 --only-show-errors
aws s3 cp "$DELIVERY_ROOT/manifest.csv" "${DEST}manifest.csv" "${SSE_ARGS[@]}" --region us-east-1 --only-show-errors
aws s3 cp "$DELIVERY_ROOT/checksums.sha256" "${DEST}checksums.sha256" "${SSE_ARGS[@]}" --region us-east-1 --only-show-errors
```

The AWS CLI automatically uses multipart upload for large files. If a command is
interrupted, rerun the same command. Contact the Diana operator before changing
a key that has already been uploaded; do not upload a correction under an
ambiguous duplicate name.

## 4. Confirm Delivery

List the exact delivery prefix and report the final object count and total size:

```sh
aws s3 ls "$DEST" --recursive --summarize --region us-east-1
```

The sender's scoped credentials may list the assigned prefix for this summary.
Anyone can independently list and download the finished public objects without
AWS credentials.

Send the Diana operator:

- Confirmation that every dataset completed.
- The total object count and total size from the command above.
- The manifest and checksum file names.
- Any upload warning or retry, with the UTC timestamp and affected relative path.

After confirmation, remove the credentials from the VM environment:

```sh
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION AWS_EC2_METADATA_DISABLED
```

## Diana Operator Acceptance

The Diana operator performs the read-side checks that the sender cannot perform:

1. List the exact prefix and reconcile object count and bytes with the sender.
2. Use `head-object` to confirm size and `AES256` encryption for representative
   data, manifest, and checksum objects.
3. Copy the accepted delivery into an approved analysis staging location and run
   `sha256sum -c checksums.sha256` from the delivery root.
4. Map the source manifest into `manifests/diana_raw_inputs.csv`, preserving
   dataset and assay boundaries, sample roles, pairing, and reference build.
   For a GCE manifest/checksum pair that uses the header above:

   ```sh
   DIANA_RAW_DELIVERY_MANIFEST=data/raw/diana/${BATCH_NAME}/manifest.csv \
   DIANA_RAW_DELIVERY_CHECKSUMS=data/raw/diana/${BATCH_NAME}/checksums.sha256 \
   DIANA_RAW_DELIVERY_ROOT=data/raw/diana/${BATCH_NAME} \
   DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
   PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-samplesheet-from-delivery
   ```
5. Run strict intake validation:

   ```sh
   DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
   ```

6. Deactivate the sender access key immediately after acceptance. Do not begin
   interpretation until checksum, reference, index, and tumor-normal pairing
   checks pass.
