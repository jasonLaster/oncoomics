# Running The Pipeline

Most readers do not need to run this project. This page is for operators who need local checks, Nextflow, Docker, AWS Batch, or Diana raw-data staging.

## Quick Start

Use the Python entry point from the repo root:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:orthogonal
PYTHONPATH=src /usr/bin/python3 -m diana_omics py:test
```

Run the whole public validation workflow:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:all
```

Run the expanded known-answer cohort:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:known-answer-expanded-cohort
```

## Common Commands

| Goal | Command |
| --- | --- |
| Build HRD tables | `PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:hrd` |
| Build TNBC subtype context | `PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:lehmann` |
| Run WES benchmark | `PYTHONPATH=src /usr/bin/python3 -m diana_omics benchmark:full-wes` |
| Run WGS validation | `PYTHONPATH=src /usr/bin/python3 -m diana_omics validate:phase3-wgs` |
| Build Diana template | `PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template` |
| Plan Diana raw handoff | `PYTHONPATH=src /usr/bin/python3 -m diana_omics plan:diana-raw-handoff` |
| Validate Diana samplesheet | `DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw` |

## Nextflow

Python commands are the source of truth. Nextflow wraps them for portable local, Docker, and AWS execution. The split `phase3_wgs` workflow has resumable checkpoints:

1. Fetch/prerequisites and validated FASTQ generation.
2. Full-reference BWA index.
3. Tumor BAM alignment, sort, index, and stats.
4. Normal BAM alignment, sort, index, and stats.
5. Downstream validation, Mutect2, CNV bins, SBS96, SV evidence, packet build, and output verification.

Use task aliases when possible:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:quick
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:known-answer-expanded-cohort
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:phase3-wgs:stub
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:phase3-wgs:dev
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:phase3-wgs:full
```

Direct Nextflow equivalents:

```sh
nextflow run main.nf -profile local --workflow quick
nextflow run main.nf -profile local --workflow known_answer_expanded_cohort
nextflow run main.nf -profile local --workflow phase3_wgs --phase3_reads 500000
nextflow run main.nf -profile local --workflow phase3_wgs --phase3_reads full
```

Bounded WGS runs are developer checks. A full-source WGS acceptance run must use `--phase3_reads full`.

## Docker

Build and run locally:

```sh
docker build -t diana-omics:local .
nextflow run main.nf -profile docker --workflow quick
nextflow run main.nf -profile docker --workflow phase3_wgs --phase3_reads 500000
```

Use stub mode for container wiring:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:docker:phase3-wgs:stub
```

The image includes the repo skeleton, manifests, docs, result summaries, Python package, Java 17, BWA, samtools, bcftools, seqkit, sra-tools, pigz, aria2, curl, unzip, and rsync. It does not bake bulky `data/raw` files into the image.

## AWS Batch

AWS Batch requires account-specific ECR, queue, region, and S3 workdir values. Prefer the task aliases after the AWS config has been generated:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:known-answer-expanded-cohort
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs:full:ondemand-failfast
```

The expanded known-answer cohort fetches small public assets in the Batch task and publishes clinicalization reports to S3. The full WGS AWS workflow should use the split `phase3_wgs` DAG so `nextflow -resume` can restart after completed expensive stages.

Resource knobs for large WGS runs:

```sh
--phase3_fetch_cpus 8 --phase3_fetch_memory '28 GB'
--phase3_ref_cpus 16 --phase3_ref_memory '28 GB'
--phase3_align_cpus 16 --phase3_align_memory '96 GB'
--phase3_downstream_cpus 16 --phase3_downstream_memory '64 GB'
```

## Logs And Diagnostics

Use the diagnostic command after local or AWS runs:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics diagnose:pipeline
```

Long-running commands should write durable artifacts under `results/*/logs`, including events, spans, resource samples, heartbeat state, and run manifests when telemetry is enabled. Set `DIANA_OMICS_LOG_UPLOAD_URI=s3://bucket/prefix` to mirror telemetry to S3.

## Blob Storage Rule

Blob stores are good for durable inputs, references, logs, and final outputs. They are not a substitute for local task scratch while tools perform heavy BAM/VCF IO.

For cloud runs:

- Keep raw inputs and references in S3.
- Let Nextflow/AWS Batch stage objects into the task workspace.
- Run alignment, sorting, indexing, depth, and variant calling against local task disk.
- Publish final manifests, summaries, BAM/VCF outputs, and logs back to S3.

Add shared scratch such as FSx for Lustre only after the AWS Batch path is proven.
