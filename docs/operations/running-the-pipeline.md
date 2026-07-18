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
```

Direct Nextflow equivalents:

```sh
nextflow run main.nf -profile local --workflow quick
nextflow run main.nf -profile local --workflow known_answer_expanded_cohort
nextflow run main.nf -profile local --workflow phase3_wgs --phase3_reads 500000
```

Bounded WGS runs are developer checks. The legacy full-source CPU WGS workflows
are blocked unless an explicitly approved public-WGS regression run passes
`--phase3_reads full --allow_legacy_phase3_cpu_full true`; Diana reruns should
use the P5en/Parabricks `phase3_wgs_fast` path or the distributed CPU scatter
architecture instead.

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

Use the local fast stub to exercise the new resumable Diana BAM-to-report DAG
with synthetic receipts, synthetic outputs, and downshifted Parabricks resource
requests:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:phase3-wgs-fast:stub
```

This runs `phase3_wgs_fast` in `-stub-run` execute mode through the
deterministic WGS report, Rosalind `diana_wgs` packet, and blocked HRD
cross-check packets without staging BAMs, calling Parabricks, or touching S3.

## AWS Batch

AWS Batch requires account-specific ECR, queue, region, and S3 workdir values. Prefer the task aliases after the AWS config has been generated:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:known-answer-expanded-cohort
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:phase3-wgs-fast:gpu-smoke
```

The expanded known-answer cohort fetches small public assets in the Batch task and publishes clinicalization reports to S3. The GPU smoke alias is the bounded
placement gate for the isolated `phase3_wgs_fast` P5en/Parabricks queue; it does not run the full WGS caller.

The full `phase3_wgs_fast` execute alias is available as
`nf:aws:phase3-wgs-fast:execute`, accepts reviewed Gate 0 receipt paths and the
alias-only forbidden-token inventory after `--`, and intentionally requires
`ALLOW_PHASE3_FAST_AWS_EXECUTE=YES`. It also requires
`PARABRICKS_MIRROR_RECEIPT` to point at the reviewed ECR mirror receipt and
`PHASE3_FAST_GPU_SMOKE_RESULT` to point at the reviewed `gpu_smoke.json` from
the bounded placement gate. Before it can submit the full P5en/Parabricks
workflow, it repeats the GPU params, live Batch queue, isolated P5en compute
environment, mirror-receipt, cache, ECR-image, live P-instance quota, and
GPU-smoke checks locally so a stale image, missing mirror, deleted digest, wrong
queue, misrouted compute environment, under-quota region, or skipped placement
gate fails before Nextflow.

Do not use the legacy full-source AWS CPU aliases for the current Diana tumor/matched-normal evidence rerun. They are blocked behind
`ALLOW_LEGACY_PHASE3_AWS_FULL=YES` and kept only for explicitly approved legacy public-WGS regression runs.

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
