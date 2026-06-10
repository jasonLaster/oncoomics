# Nextflow Orchestration

This repository keeps the Python commands as the source of truth and uses Nextflow as a portable runner around those commands. The first Nextflow layer is command-stage based: each selected workflow copies the repo into a task workspace, sets `DIANA_OMICS_ROOT` to that workspace, and runs the existing `python -m diana_omics ...` commands there.

## Local Runs

Install Nextflow, then run one of the task aliases:

```sh
bun run nf:quick
bun run nf:full-wes
bun run nf:phase3-fetch:dev
bun run nf:phase3-fetch:full
bun run nf:phase3-wgs:dev
bun run nf:phase3-wgs:full
bun run nf:all-public
```

Direct Nextflow equivalents:

```sh
nextflow run main.nf -profile local --workflow quick
nextflow run main.nf -profile local --workflow full_wes
nextflow run main.nf -profile local --workflow phase3_fetch --phase3_reads 500000
nextflow run main.nf -profile local --workflow phase3_fetch --phase3_reads full --phase3_fetch_concurrency 4 --phase3_aria2_split 1
nextflow run main.nf -profile local --workflow phase3_wgs --phase3_reads 500000
nextflow run main.nf -profile local --workflow phase3_wgs --phase3_reads full
nextflow run main.nf -profile local --workflow all_public --phase3_reads 500000
```

`phase3_wgs` defaults to `500000` read pairs when `--phase3_reads` is omitted. Full-source WGS is intentionally opt-in:

```sh
nextflow run main.nf -profile local --workflow phase3_wgs --phase3_reads full
```

`all_public` requires an explicit `--phase3_reads` value. If that value is `full`, it also requires:

```sh
nextflow run main.nf -profile local --workflow all_public --phase3_reads full --allow_full_wgs true
```

Outputs are published under `nextflow-out/<workflow>/`.

Bounded Phase 3 runs are developer plumbing checks. They may run `verify:outputs` for visibility, but a failing full-output verifier is non-fatal unless `--phase3_reads full` is selected. Full-source runs keep `verify:outputs` fatal because that verifier is the acceptance gate for Diana-readiness evidence.

## Phase 3 Fetch Experiments

Use `phase3_fetch` to benchmark WGS FASTQ download strategies without running the full WES benchmark or WGS validation ladder:

```sh
nextflow run main.nf \
  -profile awsbatch_ondemand \
  -params-file infra/aws/nextflow.aws.json \
  --workflow phase3_fetch \
  --phase3_reads full \
  --phase3_source_mode aws_sra \
  --phase3_fetch_cpus 8 \
  --phase3_fetch_memory '48 GB' \
  --phase3_fetch_concurrency 8 \
  --phase3_s3_range_concurrency 8 \
  --phase3_sra_run_concurrency 1
```

`phase3_fetch` still fetches the small prerequisites needed by `fetch:phase3-wgs`, then downloads and checks the full SEQC2/HCC1395 WGS reads. The default source mode is `ena_fastq`, which downloads the published gzip FASTQs directly from ENA and verifies provider MD5s. AWS cloud runs should use `--phase3_source_mode aws_sra` to range-read public SRA objects from the AWS Open Data bucket `sra-pub-run-odp`, convert them with `fasterq-dump`, gzip the split FASTQs, and leave the existing validation logic unchanged. This path validates SRA spot counts and full FASTQ scans; it does not claim ENA provider-MD5 validation because the FASTQ gzip bytes are regenerated in the task.

Measured from `us-east-1`, ENA direct HTTP was about 4-6 MB/s and did not scale meaningfully with four streams, while SRA Open Data S3 range reads scaled to hundreds of MB/s. Optimize the AWS path around conversion and compression, not around ENA download concurrency.

Use `phase3_sra_benchmark` for cheap network-only experiments before a full download and conversion run:

```sh
nextflow run main.nf \
  -profile awsbatch_ondemand \
  -params-file infra/aws/nextflow.aws.json \
  --workflow phase3_sra_benchmark \
  --phase3_fetch_cpus 4 \
  --phase3_fetch_memory '16 GB' \
  --phase3_fetch_concurrency 8 \
  --sra_benchmark_bytes 268435456 \
  --sra_benchmark_parts 4
```

This range-reads the public SRA objects and reports per-range plus aggregate MB/s without keeping the downloaded bytes. `--sra_benchmark_bytes` is bytes per range and `--sra_benchmark_parts` is ranges per run accession. It tests the AWS S3 path only; full `aws_sra` performance also includes SRA-to-FASTQ conversion and gzip compression. Keep `--phase3_aria2_split 1` for ENA acceptance data unless a segmented transfer strategy has already been proven against provider MD5s and gzip validation.

AWS Batch profiles retry failed processes once by default through `--aws_max_retries 1`. Increase this only for transient cloud failures; deterministic analysis failures should be fixed and relaunched with a new image.

## Docker Profile

Build the local image:

```sh
docker build -t diana-omics:local .
```

Run with the Docker profile:

```sh
nextflow run main.nf -profile docker --workflow quick
nextflow run main.nf -profile docker --workflow phase3_wgs --phase3_reads 500000
```

Use `-stub-run` for a fast container wiring check that does not fetch data or run analysis:

```sh
nextflow run main.nf -profile docker --workflow quick -stub-run
```

The Docker image includes the repo skeleton, manifests, docs, result summaries, Python package, Java 17, BWA, samtools, bcftools, seqkit, sra-tools, pigz, aria2, curl, unzip, and rsync. It does not bake bulky `data/raw` files into the image; fetch commands recreate raw inputs inside the task workspace.

The Docker and AWS Batch profiles set `DIANA_OMICS_SKIP_WIKI_CHECKS=true` because the external Diana wiki checkout is not part of the container image. Local profile runs keep the wiki source checks enabled.

## AWS Batch Profile

The AWS Batch profile is cloud-ready but requires account-specific values:

```sh
nextflow run main.nf \
  -profile awsbatch \
  --workflow phase3_wgs \
  --phase3_reads 500000 \
  --container '<account>.dkr.ecr.<region>.amazonaws.com/diana-omics:<tag>' \
  --aws_queue '<aws-batch-job-queue>' \
  --aws_region '<region>' \
  --aws_workdir 's3://<bucket>/nextflow-work'
```

Use an ECR image built from this `Dockerfile`, an AWS Batch compute environment with enough local disk for FASTQ/BAM/VCF work, and an S3 work bucket in the same region as the compute. Prefer Spot for repeatable public validation runs and On-Demand for precious Diana recomputes.

## Blob Storage Rule

Blob stores are good for durable inputs, references, logs, and final outputs. They are not a substitute for local task scratch when the tools do heavy BAM/VCF IO.

For cloud runs:

- Keep raw inputs and references in S3.
- Let Nextflow/AWS Batch stage objects into the task workspace.
- Run alignment, sorting, indexing, depth, and variant calling against local task disk.
- Write final manifests, summaries, BAM/VCF outputs, and logs back to S3 through Nextflow publishing or an explicit upload step.

If repeated full WGS runs spend too much time restaging references or large shared assets, add a fast shared scratch layer such as FSx for Lustre after the AWS Batch path is proven.
