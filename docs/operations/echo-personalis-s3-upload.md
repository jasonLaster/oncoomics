# Echo / Personalis S3 Upload Handoff

This is the sender checklist for Akhil and the Echo team to deliver Diana's two
Personalis datasets, WGS and ImmunoID, from a Google Compute Engine VM to the
Diana Omics write-only S3 inbox.

## Delivery Destination

Upload only to this exact prefix:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/
```

Use these subfolders so WGS and ImmunoID remain distinct:

```text
2026-07-14-echo-personalis/
├── wgs/
├── immunoid/
├── manifest.csv
└── checksums.sha256
```

Do not classify ImmunoID files as WGS or assume they are interchangeable with a
matched-normal or RNA dataset. Preserve the Personalis file names and assay
labels. The Diana team will map the two deliveries into the analysis samplesheet
after receipt.

## Access And Expiration

Jason will provide the AWS access key ID and secret access key through a secure
channel separate from email. Do not commit, email, or paste the credentials into
tickets or logs.

The credentials:

- Identify `diana-echo-personalis-upload-202607`.
- Can list and write only the exact batch prefix above.
- Cannot read or delete objects, list the parent inbox, or write elsewhere.
- Stop working after August 14, 2026 at 23:59:59 UTC.

The destination applies AWS KMS encryption automatically. AWS S3 uses multipart
upload for large genomics files; the credential and KMS policies already include
the operations required for multipart upload.

## 1. Prepare The Delivery

Keep WGS and ImmunoID in separate local directories under one delivery root. The
bundle should contain the raw and derived files Personalis made available,
including required index, QC, and report files. Examples include FASTQ pairs,
BAM/CRAM plus BAI/CRAI, VCF/gVCF plus indexes, CNV/SV outputs, and reports. Do not
omit a file solely because it is derived; identify its type in the manifest.

Create `manifest.csv` with one row per delivered file and this header:

```csv
dataset,sample_id,role,assay,data_type,relative_path,size_bytes,sha256,reference_build,source_vendor,notes
```

Required details:

- `dataset`: `WGS` or `ImmunoID`.
- `sample_id`: the Personalis sample identifier.
- `role`: tumor, matched normal, tumor RNA, report, or other accurate role.
- `assay`: the exact Personalis assay or workflow name.
- `data_type`: FASTQ, BAM, CRAM, VCF, CNV, SV, report, QC, or another precise type.
- `relative_path`: path below the delivery root, such as `wgs/sample_R1.fastq.gz`.
- `size_bytes` and `sha256`: source-side byte count and SHA-256 checksum.
- `reference_build`: for example GRCh38/hg38, or `not_applicable` for a report.
- `source_vendor`: `Personalis`.
- `notes`: library, lane, capture, pipeline version, or other provenance not represented elsewhere.

An existing Personalis manifest is acceptable if it contains equivalent fields.
Please identify tumor-normal pairing, reference build, and assay provenance
explicitly rather than inferring them from file names.

From the delivery root, generate a checksum file for the data directories:

```sh
find wgs immunoid -type f -print0 | sort -z | xargs -0 sha256sum > checksums.sha256
```

Confirm every data file appears once in both `manifest.csv` and
`checksums.sha256` before upload.

## 2. Configure The GCE VM

Use a GCE VM with an attached persistent disk, not the boot disk, for the
delivery working directory. The disk should have enough free space for the
staged files plus at least 20 percent headroom for manifests, checksums, and
retries. Keep the source GCS objects until Diana confirms acceptance.

If the Personalis files exist only in GCS, stage them onto the attached disk:

```sh
DELIVERY_ROOT=/mnt/echo-personalis/delivery
mkdir -p "$DELIVERY_ROOT/wgs" "$DELIVERY_ROOT/immunoid"

gcloud auth list
gcloud storage du --summarize gs://PERSONALIS-WGS-BUCKET/PREFIX/
gcloud storage du --summarize gs://PERSONALIS-IMMUNOID-BUCKET/PREFIX/
df -h "$DELIVERY_ROOT"

gcloud storage rsync --recursive gs://PERSONALIS-WGS-BUCKET/PREFIX/ "$DELIVERY_ROOT/wgs/"
gcloud storage rsync --recursive gs://PERSONALIS-IMMUNOID-BUCKET/PREFIX/ "$DELIVERY_ROOT/immunoid/"
```

Replace the two `gs://` placeholders with the actual Echo locations. If the
files are already on an attached disk, set `DELIVERY_ROOT` to their common
parent and skip the GCS copy. Do not stream large files directly from
`gcloud storage cat` into `aws s3 cp -`; a broken pipe would need to restart the
object and makes source-side SHA-256 verification harder.

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
```

Verify the identity:

```sh
aws sts get-caller-identity --query Arn --output text
```

Expected result:

```text
arn:aws:iam::172630973301:user/diana-echo-personalis-upload-202607
```

Run the transfer inside `tmux`, `screen`, or another persistent terminal so an
SSH disconnect does not stop the upload. The standard AWS CLI v2 multipart
defaults are suitable for this delivery; no custom S3 endpoint or encryption
flags are required.

## 3. Upload WGS And ImmunoID

Set the local and destination paths:

```sh
: "${DELIVERY_ROOT:=/mnt/echo-personalis/delivery}"
DEST=s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/
```

Review the planned object paths first:

```sh
aws s3 cp "$DELIVERY_ROOT/wgs/" "${DEST}wgs/" --recursive --dryrun --region us-east-1
aws s3 cp "$DELIVERY_ROOT/immunoid/" "${DEST}immunoid/" --recursive --dryrun --region us-east-1
```

Upload the data directories, then upload the manifest and checksums last:

```sh
aws s3 cp "$DELIVERY_ROOT/wgs/" "${DEST}wgs/" --recursive --region us-east-1 --only-show-errors
aws s3 cp "$DELIVERY_ROOT/immunoid/" "${DEST}immunoid/" --recursive --region us-east-1 --only-show-errors
aws s3 cp "$DELIVERY_ROOT/manifest.csv" "${DEST}manifest.csv" --region us-east-1 --only-show-errors
aws s3 cp "$DELIVERY_ROOT/checksums.sha256" "${DEST}checksums.sha256" --region us-east-1 --only-show-errors
```

The AWS CLI automatically uses multipart upload for large files. If a command is
interrupted, rerun the same command. Because these credentials cannot read or
delete objects, contact Jason before changing a key that has already been
uploaded; do not upload a correction under an ambiguous duplicate name.

## 4. Confirm Delivery

List the exact delivery prefix and report the final object count and total size:

```sh
aws s3 ls "$DEST" --recursive --summarize --region us-east-1
```

The credentials intentionally cannot run `head-object`, download an object, or
delete an object. A failure of those operations is expected and does not mean the
upload failed.

Send Jason:

- Confirmation that both `wgs/` and `immunoid/` completed.
- The total object count and total size from the command above.
- The manifest and checksum file names.
- Any upload warning or retry, with the UTC timestamp and affected relative path.

After confirmation, remove the credentials from the VM environment:

```sh
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
```

## Diana Operator Acceptance

The Diana operator performs the read-side checks that Echo cannot perform:

1. List the exact prefix and reconcile object count and bytes with Echo.
2. Use `head-object` to confirm size and SSE-KMS metadata for representative WGS,
   ImmunoID, manifest, and checksum objects.
3. Copy the accepted delivery into an approved analysis staging location and run
   `sha256sum -c checksums.sha256` from the delivery root.
4. Map the vendor manifest into `manifests/diana_raw_inputs.csv`, preserving WGS
   versus ImmunoID assay boundaries, sample roles, pairing, and reference build.
5. Run strict intake validation:

   ```sh
   DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
   ```

6. Deactivate the Echo access key immediately after acceptance. Do not begin HRD
   interpretation until checksum, reference, index, and tumor-normal pairing
   checks pass.
