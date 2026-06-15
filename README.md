# Diana HRD Omics

This repository is a validation-first workspace for Diana's future tumor-normal omics data. The goal is to understand whether we can recompute HRD-relevant evidence from raw or near-raw files, while keeping every claim auditable against public known-answer samples before any Diana-specific interpretation is attempted.

The project does four things:

- Builds HRD and TNBC subtype evidence tables from public processed breast-cancer data.
- Runs raw public WES/WGS tumor-normal examples through alignment, calling, and validation paths.
- Tests known-answer samples such as SEQC2/HCC1395, GIAB HG008, and COLO829 so the pipeline returns expected findings.
- Defines the handoff contract for Diana's future FASTQ, BAM, CRAM, VCF, CNV, SV, RNA, and vendor-report files.

## Current State

What is working:

- **HRD evidence tables:** public TCGA/BRCA-style processed data produce reviewer-facing HRR event, allele-state, scar/signature, RNA-context, and failure-mode tables for 28 reference-panel samples.
- **TNBC event subtypes:** Lehmann TNBC subtype context is wired into generated evidence tables, so subtype biology can be discussed beside HRD evidence without treating subtype as a clinical HRD truth label.
- **Raw WES benchmark:** SEQC2/HCC1395 full WES FASTQs run through validation, alignment, duplicate marking, GATK Mutect2, and truth overlap. Current evidence: `1122` exact PASS truth matches, recall `0.8585`, precision `0.9842`.
- **Raw WGS mechanics:** SEQC2/HCC1395 full-source WGS FASTQs exercise BAM validation, Mutect2, coverage-CNV bins, SBS96 mutation context, and SV evidence summaries.
- **Known-answer confirmations:** the expanded 29-target cohort has `19` confirmations, `1` partial confirmation, `3` strict-validation gaps, and `6` request/access blockers. The clearest result is COLO829 BRAF V600E recovery across four public tumor-normal BAM pairs.
- **Diana intake:** the samplesheet template and strict validator are ready. Actual Diana files are still pending.

What is still missing:

- Full Diana raw data, metadata, sample provenance, reference build, and tumor-normal pairing confirmation.
- Full HG008 caller-level recall/precision and SV/CNV reciprocal-overlap benchmarking.
- Full COLO829 SV/CNA benchmarking and tumor-purity sensitivity table.
- True MRD/plasma validation material, likely Seraseq or another request/purchase dataset.
- Reviewer-approved HRD interpretation policy, including CHORD/scarHRD/FACETS/ASCAT/PURPLE-style input requirements and no-call thresholds.

The safe boundary is simple: this repo can produce public-data validation evidence and reviewer packets. It does not make a treatment recommendation or a clinical companion-diagnostic call.

## How It Works

Python owns orchestration and evidence generation. The bioinformatics work is done by familiar tools:

| Layer | Tools |
| --- | --- |
| Workflow and evidence | Python package in `src/diana_omics`, CSV/JSON manifests, generated Markdown reports |
| Alignment and BAM/VCF work | BWA, samtools, bcftools |
| Somatic calling | Java plus GATK MarkDuplicates, Mutect2, FilterMutectCalls, contamination helpers |
| Portable execution | Nextflow, Docker, AWS Batch, S3 |
| Development checks | Ruff, mypy, pytest |
| Optional native scale-up | pysam, pyfaidx, polars, truvari, SigProfiler-compatible signature assignment |

```mermaid
gantt
    title HRD Evidence Computation Path
    dateFormat YYYY-MM-DD
    axisFormat %b %d

    section Inputs
    Load manifests and metadata              :inputs_meta, 2026-01-01, 1d
    Validate omics inputs                    :inputs_validate, after inputs_meta, 1d

    section DNA Processing
    Align tumor-normal reads                 :dna_align, after inputs_validate, 3d
    Call somatic SNVs and indels             :dna_call, after dna_align, 2d
    Normalize and score VCFs                 :dna_score, after dna_call, 1d

    section HRD Evidence
    Build HRR and allele-state tables        :hrd_events, after dna_score, 1d
    Compute CNV SV SBS96 signature surfaces  :hrd_surfaces, after dna_score, 2d
    Add TNBC subtype and RNA context         :rna_context, after hrd_events, 1d

    section Validation
    Compare public samples to known answers  :known_answers, after hrd_surfaces, 2d
    Run verifier gates and no-call boundaries :verify, after known_answers, 1d

    section Output
    Write reviewer packet and readiness docs :outputs, after verify, 1d
```

Commands all use the same entry point:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
```

A few representative commands show the shape of the project:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:hrd
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:lehmann
PYTHONPATH=src /usr/bin/python3 -m diana_omics benchmark:full-wes
PYTHONPATH=src /usr/bin/python3 -m diana_omics validate:phase3-wgs
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:known-answer-expanded-cohort
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template
```

Most readers do not need to run the project. For run instructions, see [docs/operations/running-the-pipeline.md](docs/operations/running-the-pipeline.md).

## Documentation

Start here:

- [docs/README.md](docs/README.md): short documentation map.
- [docs/status/current-state.md](docs/status/current-state.md): what has passed, what is partial, what is blocked.
- [docs/validation/known-answer-datasets.md](docs/validation/known-answer-datasets.md): public validation samples and dataset priorities.
- [docs/operations/analytics-sequence.md](docs/operations/analytics-sequence.md): systems architecture for analytics orchestration and OSS tool calls.
- [docs/data/source-map.md](docs/data/source-map.md): provenance for datasets, tools, truth sets, and vendor context.
- [docs/operations/running-the-pipeline.md](docs/operations/running-the-pipeline.md): local, Docker, Nextflow, and AWS commands.

Directory guides:

- [src/README.md](src/README.md): implementation map.
- [results/README.md](results/README.md): generated evidence map.
- [scripts/README.md](scripts/README.md): shell utilities.
