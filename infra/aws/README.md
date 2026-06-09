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
bun run infra:aws:init
bun run infra:aws:fmt:check
bun run infra:aws:validate
```

Plan and apply:

```sh
bun run infra:aws:plan
bun run infra:aws:apply
```

To point Terraform at a specific immutable ECR tag:

```sh
AWS_IMAGE_TAG=24d8a65-awswrap2 bun run infra:aws:plan
AWS_IMAGE_TAG=24d8a65-awswrap2 bun run infra:aws:apply
```

The stack defaults to account-local AWS credentials and `us-west-1`. It writes `infra/aws/nextflow.aws.json`, which is ignored by git and used by the AWS Nextflow scripts.

## Build And Push Image

After the ECR repository exists:

```sh
bun run aws:ecr:push
```

The image tag defaults to the current git SHA. Override it with `AWS_IMAGE_TAG=...` when testing an image before a commit. Because the ECR repository uses immutable tags, use a new tag for every pushed cloud image.

AWS Batch mounts the host-side AWS CLI path configured in `nextflow.config` into task containers. The Batch launch template creates `/opt/diana-aws/bin/aws` on each EC2 host so Nextflow can stage S3 work files while the container image still carries the Python code and bioinformatics tools.

## Smoke Test

Run a cloud-side stub only. This submits a real AWS Batch job but does not fetch data or run analysis:

```sh
bun run nf:aws:quick:stub
```

Confirm:

- AWS Batch job succeeds.
- CloudWatch logs appear under `/aws/batch/diana-omics-prod`.
- S3 work objects appear under the `diana-omics-work-...` bucket.
- No raw data was uploaded from local.

## Monitoring

Get the AWS Batch job id from Nextflow output or from `nextflow.log`, then poll status and recent logs:

```sh
bun run nf:aws:monitor -- JOB_ID
```

For a one-time snapshot:

```sh
bun run nf:aws:monitor -- JOB_ID --once
```

For live CloudWatch log following:

```sh
bun run nf:aws:monitor -- JOB_ID --follow
```

The monitor prints Batch job state, queue compute environment capacity, active Batch EC2 hosts, and the assigned CloudWatch stream. By default it repeats every 60 seconds until the job reaches `SUCCEEDED` or `FAILED`; override with `AWS_MONITOR_INTERVAL=...` or `--interval ...`. Use it during long WGS runs; when a run finishes or fails, also confirm Batch compute returns to `desired: 0` and no `diana-omics-prod-batch` EC2 instances are still running.

## Bounded Validation

Only after the stub succeeds:

```sh
bun run nf:aws:phase3-wgs:dev
```

This uses `--phase3_reads 500000` and is still a developer plumbing check. It downloads public/reference inputs in AWS.

## Phase 3 Fetch Experiments

Use the fetch-only workflow to test WGS download throughput on smaller Batch jobs without running the full validation ladder:

```sh
bun run nf:aws:phase3-fetch:full
```

The default full fetch experiment uses:

- `--phase3_fetch_cpus 4`
- `--phase3_fetch_memory '16 GB'`
- `--phase3_fetch_concurrency 4`
- `--phase3_aria2_split 1`

Keep `phase3_aria2_split=1` for acceptance-scale data unless a segmented ENA strategy has been proven against provider MD5s and gzip validation. Raising fetch concurrency is the safer first download experiment. The job writes FASTQs to local task storage first; S3 work/results objects are only durable after the task publishes or exits cleanly.

## Full-Source WGS

Run full WGS only by explicit command, preferably on the On-Demand queue unless Spot interruption is acceptable:

```sh
bun run nf:aws:phase3-wgs:full
```

Full-source WGS is the acceptance-scale path and can be expensive.

## Cost Notes

The stack includes a NAT Gateway so private Batch compute can download public data. NAT Gateway, EBS root volumes, Batch EC2 instances, S3 storage, and data transfer can create charges. Work-bucket objects expire by lifecycle policy, but Batch compute and failed runs should still be checked after testing.
