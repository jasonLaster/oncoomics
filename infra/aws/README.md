# Diana Omics AWS Stack

This Terraform stack provisions the AWS Batch, S3, ECR, IAM, and network resources needed to run the Diana Omics Nextflow workflows in AWS.

## Non-Negotiable Data Rule

Do not upload raw data or generated analysis data from a developer workstation or the normal analysis workflow.

- Do not upload `data/raw`, local FASTQ/BAM/CRAM/VCF files, local `data/processed`, or local `results` artifacts.
- The Docker image is built with `.dockerignore` rules that exclude raw/generated data.
- Cloud runs must fetch public/reference inputs fresh inside AWS Batch task workspaces.
- S3 `results` objects should be produced by the cloud job that writes them.
- An approved external raw delivery is a separate custody workflow: it must use the private `diana/inbox/YYYY-MM-DD-source-name/` prefix, Diana-issued scoped credentials, destination SSE-KMS, a manifest, and source SHA-256 checksums as documented in `docs/operations/diana-raw-s3-upload.md`.

## Bootstrap

Install Terraform:

```sh
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

Initialize and validate:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:init
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:fmt:check
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:validate
```

The preferred cloud stack for public SRA work is `us-east-1`, because the `sra-pub-run-odp` AWS Open Data bucket is in `us-east-1`. Use the `sra-use1` Terraform workspace and the `prod-use1` environment name for this stack:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:use1
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:plan:use1
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:apply:use1
```

Generic plan/apply commands operate on the currently selected Terraform workspace:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:apply
```

To point Terraform at a specific immutable ECR tag:

```sh
AWS_IMAGE_TAG=24d8a65-awswrap2 PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:plan:use1
AWS_IMAGE_TAG=24d8a65-awswrap2 PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:apply:use1
```

The active SRA stack uses account-local AWS credentials and `us-east-1`. It writes `infra/aws/nextflow.aws.json`, which is ignored by git and used by the AWS Nextflow scripts. The original `us-west-1` stack is legacy for this workload because cross-region SRA reads benchmarked much slower.

The stack deliberately separates reviewed public-validation outputs from
sensitive analysis outputs:

- `diana-omics-results-...` exposes only the exact reviewed public prefixes in
  Terraform. Never write patient-derived or otherwise sensitive artifacts to
  it.
- `diana-omics-private-results-...` is the durable destination for sensitive
  analysis results, method reports, provenance, and reviewer packets. It uses
  SSE-KMS, versioning, bucket-owner-enforced ownership, TLS-only access, and all
  four S3 public-access-block controls.
- `diana-omics-work-...` is private scratch space with lifecycle expiry, not the
  sole durable copy of a report.

## Build And Push Image

After the ECR repository exists:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:ecr:push
```

The image push defaults to `us-east-1` and the current git SHA. Override it with `AWS_REGION=...` or `AWS_IMAGE_TAG=...` when testing an image before a commit. Because the ECR repository uses immutable tags, use a new tag for every pushed cloud image.

AWS Batch mounts the host-side AWS CLI path configured in `nextflow.config` into task containers. The Batch launch template creates `/opt/diana-aws/bin/aws` on each EC2 host so Nextflow can stage S3 work files while the container image still carries the Python code and bioinformatics tools.

## Private HRD x86 Cross-Checks

The stack includes a separate On-Demand `linux/amd64` Batch lane for private
HRD cross-check tooling that is unavailable in the ARM image:

- Compute environment: `<project>-<environment>-hrd-x86-ondemand`
- Queue: `<project>-<environment>-hrd-x86`
- Instance families: `c7i`, `m7i`, and `r7i`
- Capacity: `min_vcpus = 0`, `desired_vcpus = 0`, and
  `hrd_x86_max_vcpus = 128` by default

It reuses the encrypted Batch launch template, private subnets, no-ingress
security group, Batch instance profile and service role, and the existing job
and CloudWatch log roles. It has no ARM fallback and Terraform does not
register an analysis job definition. With no submitted jobs it has no EC2
instances or idle compute charge.

Terraform writes `aws_hrd_x86_queue` and `aws_private_results_dir` to
`infra/aws/nextflow.aws.json`. A future cross-check must also supply an
immutable image that was built for `linux/amd64`; the normal `container` value
may refer to the existing ARM image and must not be reused by assumption:

```sh
nextflow run main.nf \
  -profile awsbatch_hrd_x86 \
  -params-file infra/aws/nextflow.aws.json \
  --hrd_x86_container 'ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/IMAGE@sha256:DIGEST' \
  --workflow WORKFLOW
```

The profile writes published results to the private results bucket. Planning
or provisioning this lane does not submit a job; analysis job definitions and
submissions require a separate reviewed change.

## Smoke Test

Run a cloud-side stub only. This submits a real AWS Batch job but does not fetch data or run analysis:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:quick:stub
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:stub
```

Confirm:

- AWS Batch job succeeds.
- CloudWatch logs appear under `/aws/batch/diana-omics-prod-use1`.
- S3 work objects appear under the `diana-omics-work-...` bucket.
- No raw data was uploaded from local.

## HRD Packet Cloud Submit

Use the lightweight HRD packet submitter when the goal is to prove packet-builder behavior against already-materialized evidence artifacts, not to rerun WGS compute:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --dry-run
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --run-id cloud-selective5-YYYYMMDD
```

The script downloads a pushed GitHub archive inside AWS Batch, sets `ROSALIND_HRD_ARTIFACT_ROOT` to a repo-relative materialized artifact root, runs `build:rosalind-hrd-packet`, and uploads only cloud-generated packet outputs to S3. It does not upload local `results/` or raw data.

## Monitoring

Get the AWS Batch job id from Nextflow output or from `nextflow.log`, then poll status and recent logs:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:monitor -- JOB_ID
```

For a one-time snapshot:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:monitor -- JOB_ID --once
```

For live CloudWatch log following:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:monitor -- JOB_ID --follow
```

The monitor prints Batch job state, queue compute environment capacity, active Batch EC2 hosts, and the assigned CloudWatch stream. By default it targets `us-east-1` and repeats every 60 seconds until the job reaches `SUCCEEDED` or `FAILED`; override with `AWS_REGION=...`, `AWS_BATCH_LOG_GROUP=...`, `AWS_MONITOR_INTERVAL=...`, or `--interval ...`. Use it during long WGS runs; when a run finishes or fails, also confirm Batch compute returns to `desired: 0` and no `diana-omics-prod-use1-batch` EC2 instances are still running.

## Bounded Validation

Only after the stub succeeds:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:sra-bench:tiny
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-fetch:tiny
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:dev
```

This uses `--phase3_reads 500000` and is still a developer plumbing check. It downloads public/reference inputs in AWS.

The default `phase3_wgs` workflow is split into fetch, reference-index, tumor-alignment, normal-alignment, and downstream validation jobs. Use `nextflow -resume` after transient failures so Batch restarts from the last completed expensive stage. The monolithic fallback remains available as `--workflow phase3_wgs_monolith`, but it is no longer the preferred cloud path.

## Phase 3 Fetch Experiments

Use the SRA benchmark workflow to test AWS Open Data throughput on smaller Batch jobs without running conversion or the full validation ladder:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:sra-bench:tiny
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-sra-benchmark
```

The tiny benchmark range-reads one 16 MiB range from each HCC1395 SRA object; the default benchmark range-reads four 256 MiB ranges. Both write throughput summaries to the configured results bucket. Increase `--sra_benchmark_bytes`, `--sra_benchmark_parts`, or `--phase3_fetch_concurrency` once the basic path is working.

Observed benchmark results:

- `us-east-1`, same region as `sra-pub-run-odp`: about 196 MB/s aggregate.
- `us-west-1`, cross-region to `sra-pub-run-odp`: about 38-51 MB/s aggregate.

Use the fetch-only workflow to test the full SRA download and FASTQ conversion path without running the full validation ladder:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-fetch:full
```

The default full fetch experiment uses:

- `--phase3_source_mode aws_sra`
- `--phase3_fetch_cpus 8`
- `--phase3_fetch_memory '28 GB'`
- `--phase3_fetch_concurrency 8`
- `--phase3_s3_range_concurrency 8`
- `--phase3_sra_run_concurrency 2`
- `--phase3_cache_upload_workers 4`

The job downloads public SRA objects fresh from the AWS Open Data bucket, converts them with `fasterq-dump`, gzips split FASTQs, and writes those files to local task storage first. R1/R2 compression runs concurrently per SRA run, and validated cache uploads use bounded workers so the Batch node can use available network throughput. S3 work/results objects are only durable after the task publishes or exits cleanly. The `aws_sra` path validates SRA spot counts and full FASTQ scans, not ENA provider MD5s, because the gzip FASTQs are regenerated in AWS. Keep `phase3_aria2_split=1` for ENA acceptance-scale data unless a segmented ENA strategy has been proven against provider MD5s and gzip validation.

The full-WGS stack expects high-throughput gp3 task storage. The Terraform defaults use a 2 TB root volume with 16000 IOPS and 1000 MB/s throughput so future applies do not fall back to the gp3 125 MB/s floor.

## Cloud-Side Asset Cache

Terraform writes `phase3_asset_cache_uri` into `infra/aws/nextflow.aws.json`:

```txt
s3://diana-omics-raw-inputs-<account>-<region>/cache/phase3_wgs
```

This bucket is private, encrypted, and writable by the Batch job role. It is reserved for assets fetched or generated inside AWS Batch:

- `sra/SRR....sra` stores public SRA Open Data objects after cloud-side range download.
- `fastq/SRR..._R1.full.fastq.gz` and `fastq/SRR..._R2.full.fastq.gz` store converted FASTQs after full validation.
- `bam/<reference>/<read-label>/<role>/...` stores cloud-generated public BAM/BAI alignment derivatives after they pass read-scope validation.
- Nextflow work-bucket objects store split-stage workspaces for `nextflow -resume`.

Do not upload local `data/raw`, local FASTQ/BAM/VCF files, or local generated artifacts into this cache. Subsequent AWS Batch runs restore cached FASTQs first, cached SRA objects second, and only then re-download from public SRA. Restored FASTQs still go through the full scan/spot-count checks; restored BAMs still go through quickcheck, BAI, and requested read-scope checks. For resume-heavy runs, tune `phase3_alignment_cache_workers` for concurrent BAM/BAI cache writes and leave downstream-only validation to reuse current CNV, SBS96, and SV evidence artifacts when their inputs are unchanged.

## Diana Raw Inbox Prefix

Diana raw files belong under the raw-inputs bucket, separated from the public validation cache:

```txt
s3://diana-omics-raw-inputs-<account>-<region>/diana/inbox
```

Do not upload Diana files under `cache/phase3_wgs/`, `s3://diana-omics-results-...`, or `s3://diana-omics-work-...`.

Detailed upload and bucket-to-bucket transfer instructions live in `docs/operations/diana-raw-s3-upload.md`.

## Private Analysis Results

Patient-derived VCF, BAM, CNV, SV, signature, HRD, reviewer-packet, and
interpretation artifacts belong under:

```txt
s3://diana-omics-private-results-<account>-<region>/runs/<alias>/<run-id>/
```

Use a de-identified alias in the key. Every method directory must retain the
input object URI and VersionId when available, input SHA-256, immutable image
digest, exact command and parameters, tool versions, output SHA-256 inventory,
QC state, and interpretation state. A report produced in the expiring work
bucket is incomplete until its reviewed durable copy is verified here.

Do not publish this bucket, add it to `public_results_prefixes`, or use it as a
raw-upload inbox. The Batch job role can read and write it so private cloud jobs
can publish their own results without routing data through a developer
workstation.

The required custody contract for `diana/inbox/` is private controlled access:

- Every sender uses Diana-issued IAM credentials scoped to one assigned
  `YYYY-MM-DD-source-name/` prefix.
- The prefix must not allow anonymous list, metadata, or read operations. Never
  use `--no-sign-request` or publish direct object URLs.
- Uploads use destination SSE-KMS key
  `45aa290c-d70c-4d86-9c8d-c4a76f1ff97f` unless the actual scoped policy
  explicitly requires bucket-default KMS. Never substitute `AES256`.
- Credentials are exchanged through the approved secret manager or one-time
  secret channel, never email, tickets, logs, or source control.
- Every delivery includes `manifest.csv` and source-side
  `checksums.sha256`; an authorized Diana operator validates KMS metadata,
  inventory, and checksums before analysis.

If anonymous access to the inbox succeeds, treat the deployed stack as
misconfigured and stop intake until the access policy is remediated. Documentation
does not override the actual scoped IAM and bucket policies.

After any failed or interrupted AWS run, refresh the local diagnostic report:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics diagnose:pipeline
```

If a running AWS Batch host has already generated validated public FASTQs, preserve them from that host with SSM or the task container AWS CLI into the private `raw-inputs` cache. This is still cloud-side generation; do not copy from the developer laptop.

AWS profiles delete local `.sra` files after validated conversion and cache publication to reduce disk pressure before alignment. Override with `--phase3_delete_sra_after_conversion false` if you need to inspect the local SRA file inside a retained work directory.

## Full-Source WGS

Run full WGS only by explicit command. The default script uses the Spot queue with quota-aware sizing for the
current 32-vCPU Spot quota:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:full
```

Full-source WGS is the acceptance-scale path and can be expensive.

That script requests memory-rich split alignment jobs through:

```txt
--phase3_align_cpus 16 --phase3_align_memory '96 GB'
```

After EC2 quota approval, use the larger On-Demand shape if interruption risk is unacceptable:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:full:ondemand-large
```

After an alignment/I/O experiment, weak-scaling manual termination, or any run where automatic retry would blur the evidence, use the conservative On-Demand fail-fast alias instead:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:full:ondemand-failfast
```

That path keeps alignment at 16 CPUs/96 GB, splits each alignment job into 12 BWA threads plus 4 samtools sort threads, and sets `--aws_max_retries 0`.

Tune fetch/reference/downstream separately rather than over-sizing every stage.

Cloud Nextflow profiles retry failed Batch processes once by default. Override with `--aws_max_retries 0` for strict fail-fast testing or raise it only when the failure mode is known to be transient.

## Cost Notes

The stack includes a NAT Gateway so private Batch compute can download public data. NAT Gateway, EBS root volumes, Batch EC2 instances, S3 storage, and data transfer can create charges. Work-bucket objects expire by lifecycle policy, but Batch compute and failed runs should still be checked after testing.
