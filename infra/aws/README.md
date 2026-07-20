# Diana Omics AWS Stack

This Terraform stack provisions the AWS Batch, S3, ECR, IAM, and network resources needed to run the Diana Omics Nextflow workflows in AWS.

## Non-Negotiable Data Rule

Do not upload raw data or generated analysis data from a developer workstation or the normal analysis workflow.

- Do not upload `data/raw`, local FASTQ/BAM/CRAM/VCF files, local `data/processed`, or local `results` artifacts.
- The Docker image is built with `.dockerignore` rules that exclude raw/generated
  data, local scratch, local virtualenv/cache directories, generated Nextflow
  AWS params, Terraform state/plans, and local `.env` files.
- Cloud runs must fetch public/reference inputs fresh inside AWS Batch task workspaces.
- S3 `results` objects should be produced by the cloud job that writes them.
- An approved external raw delivery is a separate custody workflow: it must use
  the public-read `diana/inbox/YYYY-MM-DD-source-name/` prefix, Diana-issued
  scoped write credentials, destination SSE-S3, a manifest, and source SHA-256
  checksums as documented in `docs/operations/diana-raw-s3-upload.md`.

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

The stack deliberately separates reviewed public validation and alias-only
analysis outputs from raw inputs and durable restricted custody copies:

- `diana-omics-results-...` exposes only exact reviewed prefixes in Terraform.
  Public Diana analysis belongs under `runs/diana-hrd-public/<subject-alias>/<run>/`
  and must use aliases rather than direct identifiers. The original worker run
  prefix remains explicitly denied to external readers. Raw uploads, BAM inputs,
  pileup evidence, and custody/version-history manifests do not belong in the
  public alias tree.
- `diana-omics-private-results-...` is the durable, versioned custody source for
  analysis artifacts, method reports, provenance, reviewer packets, and any
  restricted inputs. Reviewed alias-only report trees can be copied from this
  bucket to an allowlisted public prefix without weakening the custody copy.
  The private bucket uses SSE-KMS, versioning, bucket-owner-enforced ownership,
  TLS-only access, and all four S3 public-access-block controls.
- `diana-omics-raw-inputs-...` exposes current objects under `diana/inbox/` for
  public list/read, while keeping public writes disabled. Approved senders upload
  with scoped credentials and SSE-S3 so browser and anonymous CLI downloads work
  without KMS grants.
- `diana-omics-work-...` is private scratch space with lifecycle expiry, not the
  sole durable copy of a report.

## Build And Push Image

After the ECR repository exists:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:ecr:push
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:ecr:push:use2
```

The default image push uses the current Terraform workspace and infers the ECR
login region from that workspace's `region` output. Use `aws:ecr:push:use1` for
the existing `sra-use1` CPU stack and `aws:ecr:push:use2` for the P5
`phase3-fast-use2` stack; those aliases select the intended workspace before
reading the regional ECR repository URL and restore the prior workspace when
the push exits. Override the current git SHA with `AWS_IMAGE_TAG=...` when
testing an image before a commit. Because the ECR repository uses immutable
tags, use a new tag for every pushed cloud image.

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

## Parabricks P5 Hopper GPU Smoke Lane

The selected fast WGS rerun uses a separate On-Demand GPU Batch lane instead of
mixing Parabricks jobs into the ARM CPU queues:

- Compute environment: `<project>-<environment>-gpu-p5en-ondemand`
- Queue: `<project>-<environment>-gpu-p5en`
- Instance types: `p5en.48xlarge`, `p5e.48xlarge`, or `p5.48xlarge` only
- AMI family: AWS Batch NVIDIA Amazon Linux 2023 for ECS
- Capacity: `min_vcpus = 0`, `desired_vcpus = 0`, and
  `gpu_p5en_max_vcpus = 384` by default

Provision the P5 lane in its own `us-east-2` Terraform workspace so the
existing `sra-use1` CPU queues and `infra/aws/nextflow.aws.json` stay bound to
`us-east-1`. The `use2` wrappers set `enable_gpu_p5en_batch=true`; the default
workspace settings leave the P5 queue absent so the daily cost guard can be
applied to CPU workspaces without creating a stray GPU lane.

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:plan:use2
PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:apply:use2
```

Terraform writes `aws_gpu_queue`, `phase3_fast_cache_prefix`,
`parabricks_mirror_repository`, `parabricks_container`, and the daily Batch cost
guard bindings to `infra/aws/nextflow.aws.use2.json`. The cache prefix uses the
regional private-results bucket under `phase3-fast-cache/wgs-v2`, the mirror
repository gives the Diana Parabricks runtime an immutable `us-east-2` ECR
destination, and the P5 smoke/execute preflights reject generated params unless
the daily guard covers the P5 queue and compute environment, caps same-day spend
at no more than `$200`, and keeps the live Batch EC2 stop threshold at no more
than 80% of that cap. Keep `parabricks_container` empty until a reviewed NVIDIA
Parabricks base image has been selected, wrapped with the Diana runtime, and
pinned by digest. The `awsbatch_gpu` profile maps `gpu_parabricks` processes to
that queue and image, binds the host instance-store `/scratch` volume into the
container, and sets the Nextflow `accelerator` request to
`phase3_fast_parabricks_num_gpus`, so Batch receives an explicit eight-GPU
request for the P5 jobs.

After the selected NVIDIA Parabricks `linux/amd64` image digest has been
reviewed, build the Diana Parabricks runtime from that exact base digest and
mirror it into the regional immutable ECR repository:

```sh
PARABRICKS_SOURCE_IMAGE='nvcr.io/.../parabricks@sha256:<reviewed-digest>' \
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:ecr:mirror-parabricks:use2
```

The helper pulls only digest-pinned source images, logs into the `us-east-2`
ECR registry from the `phase3-fast-use2` Terraform workspace, builds
`infra/aws/Dockerfile.parabricks` with `pbrun`, the AWS CLI, and the checked-out
`diana_omics` CLI under `/opt/diana-omics`, refuses to run unless the checked-in
Docker context is clean and the selected Git commit is present on a remote, pushes a
`sha256-<full-source-digest>-diana-<git-prefix>` tag into
`parabricks_mirror_repository`, writes and verifies
`results/phase3_wgs_fast/parabricks_mirror_receipt.json` against the live ECR
digest, the exact source-digest/Git tag, and the Diana Git commit in the
receipt, and prints the exact
`TF_VAR_parabricks_container=<repository>@sha256:<digest>` value to review and
apply. Re-running the helper for the same source digest and Diana Git revision
reuses the immutable ECR tag. Leave `parabricks_container` empty until that
mirror receipt has passed `verify:parabricks-mirror-receipt`; the verifier also
checks that the receipt's Diana Git commit and `Dockerfile.parabricks` SHA-256
match the checkout that is about to pin or execute the image.

Keep the reviewed receipt in
`results/phase3_wgs_fast/parabricks_mirror_receipt.json` or export
`PARABRICKS_MIRROR_RECEIPT=/path/to/parabricks_mirror_receipt.json` before any
P5 smoke or full execution attempt. Both launch preflights reject receipts
whose pinned ECR image, immutable source-digest/Git tag, Diana Git commit, or
`Dockerfile.parabricks` SHA-256 no longer match the current launcher source.

The `us-east-2` Batch job role also receives versioned read permission on the
`us-east-1` raw-inputs and private-results source buckets and KMS decrypt
permission constrained to the `alias/diana-omics-prod-use1` source key. The
generated GPU params bind `phase3_fast_cache_region=us-east-2` and a
`us-east-2` destination `phase3_fast_cache_kms_key_arn`; the smoke/execute
preflight rejects stale or hand-edited params before Batch submission if that
destination key drifts. Those grants are what let `FAST_REPLICATE_INPUTS`
promote the reviewed dry-run plan into the regional private cache without
giving the GPU stack broad cross-region S3 or KMS access.
`FAST_REPLICATE_INPUTS` also plans deterministic UploadPartCopy byte ranges and
encoded CopySource `VersionId`s for the large BAMs so apply mode can cross the
5 GiB single-object `CopyObject` limit without losing the reviewed source
version.

After P-family quota is approved and the pinned image is supplied, run only the
bounded placement/visibility smoke first. The alias starts with a local
`verify:phase3-fast-gpu-smoke` preflight so a missing `nextflow.aws.use2.json`,
tagged/empty/missing Parabricks image, source-mismatched mirror receipt,
non-P5 queue, or too-small P5 capacity fails before Nextflow can submit to
AWS Batch. The same preflight reads the live Batch queue and requires it to be
`ENABLED`, `VALID`, and still routed only to the isolated P5 compute
environment. It also reads that compute environment and requires it to be
managed, enabled, valid, scale-to-zero, On-Demand EC2 capacity backed only by
`p5en.48xlarge`, `p5e.48xlarge`, and `p5.48xlarge`, sized to at least one full P5, and configured with only the
NVIDIA Amazon Linux 2023 ECS image. It then reads the live EC2
`Running On-Demand P instances` quota and requires at least 192 vCPUs, the size
of one allowed P5 48xlarge, so a submitted but still-open Service Quotas case
cannot leak into an expensive doomed smoke job. It also verifies that the
receipt's pinned Parabricks ECR digest exists in the mirror repository with its
exact source-bound immutable tag before Batch tries to pull it:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs-fast:gpu-smoke
```

The smoke workflow verifies that the Batch job lands on the isolated GPU queue
with the pinned Diana Parabricks image, that the host `/scratch` mount was built
from all eight P5 NVMe instance-store devices, and that `nvidia-smi` reports
the expected eight H100 or H200 GPUs. It also captures `pbrun version`, a tiny
`pbrun prepon` execution, `java -version`, `bcftools --version`,
`aws --version`, and `python3 -m diana_omics --help` from inside the selected
container. Those Java and bcftools checks are required because the same GPU
process runs FilterMutectCalls and VCF indexing after Parabricks emits its
caller checkpoint. The smoke is a placement/startup gate only; it does not run Parabricks MutectCaller or Diana WGS evidence.

Use `nf:aws:phase3-wgs-fast:execute` only after Gate 0 inputs, the pinned image,
and the smoke output have been reviewed. That alias runs the full
BAM-to-evidence P5 path and therefore requires
`ALLOW_PHASE3_FAST_AWS_EXECUTE=YES`, `PHASE3_FAST_GPU_SMOKE_RESULT` pointed at
the reviewed `gpu_smoke.json` with its sibling `nvidia-smi-gpus.csv`,
`PARABRICKS_MIRROR_RECEIPT` pointed at the reviewed mirror receipt, plus the
reviewed Nextflow receipt parameters after `--`. It still repeats the GPU
params, mirror-receipt, cache, ECR-image, and live-quota checks before Nextflow
starts, then rejects missing, deleted-image, stubbed, stale-queue, stale-image,
malformed, non-H100/H200, or non-Parabricks-starting smoke output so a full run
cannot skip the bounded placement gate or reuse an already-reviewed smoke after
the mirrored digest is removed.

## Smoke Test

Run a cloud-side stub only. This submits a real AWS Batch job but does not fetch data or run analysis:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:quick:stub
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:stub
```

Confirm:

- AWS Batch job succeeds.
- CloudWatch logs appear under `/aws/batch/job`.
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

The required custody contract for `diana/inbox/` is public-read,
scoped-write access:

- Every sender uses Diana-issued IAM credentials scoped to one assigned
  `YYYY-MM-DD-source-name/` prefix.
- The `diana/inbox/` prefix allows anonymous list and current-object reads.
  Anonymous writes are denied.
- Uploads use destination SSE-S3 (`AES256`) so public downloads do not need KMS
  grants.
- Credentials are exchanged through the approved secret manager or one-time
  secret channel, never email, tickets, logs, or source control.
- Every delivery includes `manifest.csv` and source-side
  `checksums.sha256`; an authorized Diana operator validates encryption,
  inventory, and checksums before analysis.

If anonymous writes to the inbox succeed, treat the deployed stack as
misconfigured and stop intake until the access policy is remediated.
Documentation does not override the actual scoped IAM and bucket policies.

After any failed or interrupted AWS run, refresh the local diagnostic report:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics diagnose:pipeline
```

If a running AWS Batch host has already generated validated public FASTQs, preserve them from that host with SSM or the task container AWS CLI into the private `raw-inputs` cache. This is still cloud-side generation; do not copy from the developer laptop.

AWS profiles delete local `.sra` files after validated conversion and cache publication to reduce disk pressure before alignment. Override with `--phase3_delete_sra_after_conversion false` if you need to inspect the local SRA file inside a retained work directory.

## Full-Source WGS

Do not use this legacy full-source CPU launcher for the current Diana
tumor/matched-normal evidence rerun. The July 2026 single-node CPU evidence
retry was intentionally stopped before final publication; the rerun is now
gated on the `phase3_wgs_fast` P5/Parabricks architecture in
`docs/operations/next-generation-fast-rerun.md`.

The legacy AWS full-source CPU aliases intentionally fail unless
`ALLOW_LEGACY_PHASE3_AWS_FULL=YES` is set. If a legacy public WGS regression run
is explicitly approved, the default alias uses the Spot queue with quota-aware
sizing for the current 32-vCPU Spot quota:

```sh
ALLOW_LEGACY_PHASE3_AWS_FULL=YES \
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:full
```

Full-source WGS is the acceptance-scale path and can be expensive.

That script requests memory-rich split alignment jobs through:

```txt
--phase3_align_cpus 16 --phase3_align_memory '96 GB'
```

After EC2 quota approval, use the larger On-Demand shape if interruption risk is unacceptable:

```sh
ALLOW_LEGACY_PHASE3_AWS_FULL=YES \
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:full:ondemand-large
```

After an alignment/I/O experiment, weak-scaling manual termination, or any run where automatic retry would blur the evidence, use the conservative On-Demand fail-fast alias instead:

```sh
ALLOW_LEGACY_PHASE3_AWS_FULL=YES \
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:full:ondemand-failfast
```

That path keeps alignment at 16 CPUs/96 GB, splits each alignment job into 12 BWA threads plus 4 samtools sort threads, and sets `--aws_max_retries 0`.

Tune fetch/reference/downstream separately rather than over-sizing every stage.

Cloud Nextflow profiles retry failed Batch processes once by default. Override with `--aws_max_retries 0` for strict fail-fast testing or raise it only when the failure mode is known to be transient.

## Cost Notes

The stack includes a NAT Gateway so private Batch compute can download public
data. NAT Gateway, EBS root volumes, Batch EC2 instances, S3 storage, and data
transfer can create charges. Work-bucket objects expire by lifecycle policy,
but Batch compute and failed runs should still be checked after testing.

Each Terraform workspace also installs a two-layer daily Batch cost guard with
a default and maximum `daily_cost_guard_limit_usd = 200`. The live guard scans
`daily_cost_guard_regions` for every Diana-tagged Batch EC2 host, so the use1
CPU/x86 queues, the phase3-fast use2 P5 Hopper queue, and the west-region quota
hedge share one $200/day Diana Batch allowance instead of independent regional
allowances.

- a live EventBridge rule invokes `${project}-${environment}-batch-cost-guard`
  every minute, estimates the current UTC day's Diana Batch EC2 spend from
  Diana-tagged Batch instances in `us-east-1`, `us-east-2`, and `us-west-2`,
  persists the observed region-qualified runtime in a DynamoDB ledger, and
  disables this workspace's Batch job queues and compute environments before
  cancelling queued jobs and terminating visible running jobs once the
  account-wide Diana Batch EC2 estimate reaches
  `daily_cost_guard_live_stop_threshold_percent = 80` of the daily limit, or
  $160 of the default $200/day limit;
- an account-wide AWS Budget publishes to the same Lambda through SNS when
  actual same-day spend crosses `daily_cost_guard_stop_threshold_percent = 80`,
  and again at 100%, as a delayed whole-account backstop for non-Batch costs.

The live estimator deliberately overprices P5-family 48xlarge hosts in
`daily_cost_guard_instance_hourly_rates_usd`, uses the same conservative
`daily_cost_guard_unknown_instance_hourly_rate_usd = 140` fallback for any
future unlisted Batch instance type, and reserves 20% of the daily cap for
slower NAT Gateway, S3, ECR, DynamoDB, Lambda, logs, EventBridge, and AWS
Budgets metering. That makes a GPU run stop early rather than late. AWS billing
telemetry is still delayed, so leave GPU smoke and execute runs bounded and
re-check Batch state after every high-cost test.

Mutating submitters that bypass Nextflow must also re-read the same UTC-day
DynamoDB ledger immediately before `SubmitJob`. The static HRD route submitter,
v4 cross-check materializer submitter, and bounded cloud Rosalind packet helper
fail closed once the ledger reaches the live stop, so setting an explicit
`--submit` flag or `HRD_CROSSCHECK_ALLOW_EXPENSIVE_RUN=YES` cannot jump around
the daily guard.

All `diana_omics` task aliases that run Nextflow against an `awsbatch_*`
profile also get an automatic first-party preflight step:
`infra/aws/check-daily-cost-guard.sh <generated-nextflow-params>`. That wrapper
loads `aws_region`, `daily_cost_guard_ledger`, and
`daily_cost_guard_live_stop_usd` from the generated Terraform params and fails
closed before `nextflow` can submit Batch work when the shared live Batch EC2
ledger has already reached the $160 default stop.
