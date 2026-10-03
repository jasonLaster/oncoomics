# Upload single-cell RNA-seq data to Diana Omics

Use the same delivery pattern as the Echo/Personalis batch: upload to a dedicated
S3 inbox folder, include a file manifest and source checksums, and have Diana
verify the delivery before analysis. This guide covers both single-cell RNA-seq
(`scRNA-seq`) and single-nucleus RNA-seq (`snRNA-seq`); record which assay was
actually performed.

[data.diana-tnbc.com](https://data.diana-tnbc.com/) is the file browser and
download site. Upload files to its backing S3 inbox using the AWS CLI. The
existing Personalis delivery is browsable at
[the Personalis input page](https://data.diana-tnbc.com/inputs/2026-07-14-echo-personalis).
Use a new assigned folder for this delivery.

## 1. Get the destination and upload access

The Diana operator supplies the exact batch name, expected AWS identity ARN,
credential expiration, and upload credentials. The destination follows this
pattern:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/YYYY-MM-DD-vendor-scrna/
```

`YYYY-MM-DD-vendor-scrna` is a placeholder. Use the operator's assigned name and
upload only beneath that prefix. Use new upload credentials for this batch;
the Personalis batch name and credentials belong to that earlier delivery.

**This inbox is public-read. Uploaded files, filenames, manifests, and metadata
are available to anyone without AWS credentials as soon as they are uploaded.**
The operator must confirm that the complete delivery is approved for public
sharing before assigning this destination. Restricted data needs a separately
arranged private destination.

Follow [Diana Public Raw S3 Upload And Transfer](diana-raw-s3-upload.md#access-and-credential-handoff)
for access and secure credential exchange. Credentials should be scoped to the
assigned batch with the required multipart-upload permissions and no deletes.
Exchange secrets through the approved secret manager or one-time secret channel;
keep them out of email, tickets, manifests, and source control.

## 2. Prepare the single-cell delivery

Keep each sample/library/capture separate and preserve source filenames and
barcode identifiers. Deliver the available source files together:

| Files | What to include |
| --- | --- |
| Raw reads | All supplied FASTQ lanes and read files, including barcode/UMI or index reads when supplied. Record the read structure, chemistry, and sample/library mapping. |
| Count matrices | Original integer counts, preferably both filtered and unfiltered matrices. For a 10x MEX bundle, include `matrix.mtx.gz`, `barcodes.tsv.gz`, and `features.tsv.gz` (or the source's equivalent); retain H5 matrices when supplied. |
| Processed objects | Any supplied H5AD or other analysis object, with the original count files and a description of normalization, filtering, and annotation. |
| QC and pipeline outputs | Source QC/report files and pipeline version/parameters. For Cell Ranger, include `web_summary.html`, `metrics_summary.csv`, and available BAM/index, molecule, and analysis outputs. |
| Sample metadata | Sample, donor alias, library, and capture mapping; tissue; cells versus nuclei; assay/platform/chemistry; reference and annotation versions; and multiplexing/demultiplexing details when applicable. Include cell-level annotations if supplied. |

The Cell Ranger examples follow the
[official output documentation](https://www.10xgenomics.com/support/software/cell-ranger/latest/analysis/outputs/cr-outputs-overview).
For another platform, preserve its native output bundle and document the format.
If only FASTQs or only matrices are available, state that explicitly and list
the missing items. A normalized expression export alone is insufficient for
recomputing count-level QC.

Example delivery layout; names below are illustrative:

```text
delivery/
├── data/
│   ├── library-001/
│   │   ├── fastq/
│   │   ├── counts/
│   │   │   ├── filtered/
│   │   │   └── unfiltered/
│   │   └── qc/
│   ├── library-002/
│   └── metadata/
│       └── sample_metadata.csv
├── manifest.csv
└── checksums.sha256
```

## 3. Create the manifest and checksums

Use the same manifest contract as the Personalis-style handoff, with one row
for every file under `data/`, including metadata and reports:

```csv
dataset,sample_id,role,assay,data_type,relative_path,size_bytes,sha256,reference_build,source_vendor,notes
```

Paths are relative to the delivery root, such as
`data/library-001/counts/filtered/matrix.mtx.gz`. Record the actual assay and
file type. Use `notes` for library/capture IDs, read roles, chemistry, count
processing, pipeline versions, and related provenance. Record the exact
alignment/counting reference for derived files; raw FASTQs have no inherent
alignment reference. Explain unknown or inapplicable fields rather than
guessing. See the field descriptions in
[GCE to Diana S3 upload](gce-s3-upload.md#1-prepare-the-delivery).

Generate SHA-256 values from the finalized source files before upload. From the
delivery root, use the command for your operating system:

```bash
# Linux
find data -type f -exec sha256sum {} + > checksums.sha256
```

```bash
# macOS
find data -type f -exec shasum -a 256 {} + > checksums.sha256
```

Every file under `data/` must appear exactly once in both `manifest.csv` and
`checksums.sha256`, with matching paths and hashes. Freeze those files before
transferring. Keep the source copy until Diana confirms acceptance.

## 4. Upload with the AWS CLI

Install AWS CLI v2 and load the supplied credentials using
[the credential setup instructions](diana-raw-s3-upload.md#configure-aws-cli-credentials).
Run the following in Bash, replacing both placeholders. Use `tmux` or `screen`
for a long transfer from a remote VM.

```bash
set -euo pipefail
DELIVERY_ROOT=/path/to/delivery
BATCH_NAME=YYYY-MM-DD-vendor-scrna
DEST="s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/${BATCH_NAME}/"
cd "$DELIVERY_ROOT"

aws sts get-caller-identity --query Arn --output text
aws s3 cp data/ "${DEST}data/" --recursive --sse AES256 \
  --dryrun --region us-east-1
```

Confirm that the ARN matches the operator's expected identity and the preview
contains only the intended files beneath the assigned prefix. Then upload the
data, followed by the manifest and checksum file:

```bash
aws s3 cp data/ "${DEST}data/" --recursive --sse AES256 \
  --region us-east-1 --only-show-errors
aws s3 cp manifest.csv "${DEST}manifest.csv" --sse AES256 \
  --region us-east-1 --only-show-errors
aws s3 cp checksums.sha256 "${DEST}checksums.sha256" --sse AES256 \
  --region us-east-1 --only-show-errors
```

Use S3-managed `AES256` encryption on every upload, as in the current repository
transfer guides. The AWS CLI handles multipart uploads for large files. If a
command is interrupted, rerun it; contact the operator before replacing a file
or changing its contents. The command options are documented in the
[AWS CLI `s3 cp` reference](https://docs.aws.amazon.com/cli/latest/reference/s3/cp.html).

For a source in Google Cloud Storage/GCE, follow
[GCE to Diana S3 upload](gce-s3-upload.md) to stage it on disk first. For a source
in another S3 bucket, follow
[the bucket-to-bucket transfer instructions](diana-raw-s3-upload.md#transfer-from-another-s3-bucket).
Use the same single-cell layout, manifest, and checksums for either route.

## 5. Confirm delivery and share the input page

Record the final inventory:

```bash
aws s3 ls "$DEST" --recursive --summarize --region us-east-1
```

Send the Diana operator the destination, total object count and bytes, assay and
sample/library summary, missing files, and any warnings or retries. The total
object count includes `manifest.csv` and `checksums.sha256` in addition to the
files under `data/`. Send no credentials.

The shareable page uses the same assigned batch name:

```text
https://data.diana-tnbc.com/inputs/YYYY-MM-DD-vendor-scrna
```

The browser lists the raw inbox directly, so the new folder can appear without
rebuilding the reviewed results index. Visibility in the browser means the
files are available; acceptance still requires the checks below. See
[shareable input pages](../../apps/data/README.md#shareable-input-pages) and
[Diana Public Analysis Downloads](diana-public-data-download.md) for browsing
and download instructions.

After the transfer, clear the credentials from the shell:

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION
```

## Diana operator acceptance and analysis handoff

Reconcile the inventory with the sender; confirm object sizes and `AES256`
encryption; download to the approved staging location; and verify every source
SHA-256 against the manifest. From the downloaded delivery root, run
`sha256sum -c checksums.sha256` on Linux or
`shasum -a 256 -c checksums.sha256` on macOS. Check matrix dimensions,
feature/barcode mapping, count representation, and sample/library/capture
metadata before accepting the delivery. Deactivate the upload credentials
immediately after acceptance. The general read-side process is documented in
[Diana Operator Acceptance](diana-raw-s3-upload.md#diana-operator-acceptance).

Single-cell matrices need a separate analysis handoff. Start with the
[single-cell Modal/S3 platform](../scrna-platform.md), the
[breast tumor QC workflow](../scrna-breast-qc.md), and
[breast research release controls](../scrna-production.md). These document
public post-count calibration and research-readiness gates; they do not make
this vendor delivery automatically eligible for analysis. Vendor FASTQ-to-count
processing and a validated nuclei workflow require a separate plan. Calibration
commands are not an intake command for this delivery. The
[Diana raw intake contract](diana-raw-inputs.md) describes the existing DNA/bulk
RNA path, while the
[TROP-2 workflow](../rosalind/trop2-adc-workflow.md#intake) describes the proposed
single-cell metadata and target-expression handoff.
