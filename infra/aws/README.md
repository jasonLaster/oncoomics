# Diana Omics AWS Stack

This Terraform stack provisions the AWS Batch, S3, ECR, IAM, and network resources needed to run the Diana Omics Nextflow workflows in AWS.

## Non-Negotiable Data Rule

Do not upload local raw data or local generated analysis data.

- Do not upload `data/raw`, local FASTQ/BAM/CRAM/VCF files, local `data/processed`, or local `results` artifacts.
- The Docker image is built with `.dockerignore` rules that exclude raw/generated data.
- Cloud runs must fetch public/reference inputs fresh inside AWS Batch task workspaces.
- S3 `results` objects should be produced by the cloud job that writes them.

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

## Build And Push Image

After the ECR repository exists:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:ecr:push
```

The image push defaults to `us-east-1` and the current git SHA. Override it with `AWS_REGION=...` or `AWS_IMAGE_TAG=...` when testing an image before a commit. Because the ECR repository uses immutable tags, use a new tag for every pushed cloud image.

AWS Batch mounts the host-side AWS CLI path configured in `nextflow.config` into task containers. The Batch launch template creates `/opt/diana-aws/bin/aws` on each EC2 host so Nextflow can stage S3 work files while the container image still carries the Python code and bioinformatics tools.

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

Tune fetch/reference/downstream separately rather than over-sizing every stage.

Cloud Nextflow profiles retry failed Batch processes once by default. Override with `--aws_max_retries 0` for strict fail-fast testing or raise it only when the failure mode is known to be transient.

## Cost Notes

The stack includes a NAT Gateway so private Batch compute can download public data. NAT Gateway, EBS root volumes, Batch EC2 instances, S3 storage, and data transfer can create charges. Work-bucket objects expire by lifecycle policy, but Batch compute and failed runs should still be checked after testing.
