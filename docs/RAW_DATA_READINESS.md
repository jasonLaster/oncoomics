# Raw-Data Readiness Plan

The current Phase 1 project validates processed-data evidence logic. It does not yet validate the mechanics we will need when Diana's FASTQ, BAM, or CRAM files arrive. This page closes that gap by defining representative public raw-data candidates and the checks to run before Diana's files arrive.

## Why SEQC2/HCC1395

The best current representative source is the SEQC2/HCC1395 benchmark collection:

1. It is a breast cancer tumor-normal pair: HCC1395 tumor and HCC1395BL matched normal.
2. It includes WES and WGS raw FASTQ data.
3. It includes cross-site, cross-platform, FFPE/process-stress, and tumor-content style benchmark designs.
4. It is explicitly intended for somatic-calling benchmark work.
5. The raw data are public in NCBI SRA under `SRP162370`.
6. Associated SEQC2 benchmark/truth-set materials are available from the NCBI ReferenceSamples FTP area.

This is not a perfect Diana match: it is a cell-line benchmark, not a patient tumor sample. But it is much closer to Diana's future raw-data problem than TCGA processed tables because it exercises FASTQ conversion, tumor-normal pairing, QC, alignment, somatic calling, and file provenance.

## Candidate Ladder

Use `manifests/raw_representative_panel.csv`.

| Step | Pair | Why it comes next |
|---|---|---|
| 1 | `seqc2_hcc1395_wes_minimal_smoke` | Smallest practical WES tumor-normal pair. Use first for local FASTQ/QC/alignment/somatic-caller plumbing. |
| 2 | `seqc2_hcc1395_wes_ffpe_like` | Adds fixation/process-stress behavior, closer to FFPE-derived clinical material. |
| 3 | `seqc2_hcc1395_wgs_hiseqx_full` | WGS pair for real SV/signature readiness and truth-set comparison. Too large for a casual local first run. |
| 4 | `seqc2_hcc1395_wgs_novaseq_full` | Modern-platform WGS robustness check after the HiSeq X WGS path works. |

## Immediate Work Before Diana Files Arrive

1. Confirm raw tooling:
   - SRA Toolkit: `prefetch`, `fasterq-dump`.
   - QC: FastQC/MultiQC.
   - Alignment: BWA-MEM/BWA-MEM2 or nf-core/sarek-compatible container runtime.
   - BAM utilities: samtools.
   - Somatic caller route: nf-core/sarek, GATK Mutect2, Strelka2, or another pinned workflow.
2. Build a raw-data samplesheet for the WES minimal pair.
3. Run a local targeted/downsampled smoke test.
4. Record exact reference build and interval handling.
5. Produce tiny smoke outputs: FASTQ validation, QC report, aligned BAM or command-ready alignment plan, and somatic-caller input validation.
6. Only then scale to full WES or WGS.

## Verifiers

Phase 2 should not be considered complete until these pass:

1. `bun run fetch:raw-candidates` refreshes public SRA metadata.
2. `bun run verify:outputs` confirms all raw representative pairs have public tumor and normal runs.
3. A raw samplesheet exists and validates.
4. A small raw-data smoke run completes and leaves a report.
5. The smoke report says whether the test used full SRA, SRA Lite, downsampled FASTQ, or a regional subset.

## Phase 2A Result

Status: **complete**.

The project now streams a tiny real-read subset from ENA direct FASTQ links for the SEQC2/HCC1395 minimal WES pair:

1. Tumor: `SRR7890850`.
2. Normal: `SRR7890851`.
3. Reads per FASTQ end: `1000`.
4. Output report: `results/raw_smoke/README.md`.
5. Summary table: `results/raw_smoke/fastq_smoke_summary.csv`.
6. Local ignored FASTQs: `data/raw/smoke/seqc2_hcc1395_wes_minimal_smoke/`.

This validates direct raw-read access, paired FASTQ layout, read-ID pairing, basic read metrics, and samplesheet shape.

## Phase 2B Remaining Gate

The local machine does not currently have SRA Toolkit, FastQC/MultiQC, BWA/BWA-MEM2, samtools, Nextflow, or a container runtime installed. The next raw-readiness step is therefore alignment/caller input readiness on a genomics-ready environment.

Required Phase 2B output:

1. A reference-build decision.
2. An alignment-capable environment.
3. BAM/CRAM/QC artifact generation from the minimal WES pair or a larger downsample.
4. Somatic-caller input validation.
5. A report that distinguishes format smoke, alignment smoke, and full-depth benchmark runs.

## Boundary

The representative data should prove system readiness, not Diana biology. Use it to harden:

1. Download and provenance handling.
2. FASTQ splitting and pairing.
3. Sample-sheet conventions.
4. QC thresholds and failure reporting.
5. Reference build consistency.
6. Tumor-normal calling flow.
7. Evidence-table ingestion from raw-derived outputs.

Do not use it to decide Diana treatment or infer Diana HRD status.
