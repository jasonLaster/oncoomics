# Phase Status

## Phase 1: Complete

Status: **complete and validated**.

Phase 1 proved the processed-data evidence workflow:

1. Fetched public TCGA-BRCA/cBioPortal, GDC catalog, and UCSC Xena processed data.
2. Built a frozen HRD reference panel with positive, mechanistic, ambiguous, and negative controls.
3. Generated HRR event, copy-loss proxy, scar-proxy, RNA-context, and failure-mode tables.
4. Produced a reviewer packet and Diana readiness gate.
5. Validated the outputs with `bun run verify:outputs`.

Phase 1 deliberately did **not** prove raw FASTQ/BAM ingestion or WGS-grade HRD signature calling.

## Phase 2A: Direct FASTQ Raw-Data Smoke

Status: **complete and validated**.

Goal: prove that the project can ingest representative raw tumor-normal data before Diana's FASTQ/BAM/CRAM files arrive.

Completed work:

1. Use `manifests/raw_representative_panel.csv` as the raw-data candidate ladder.
2. Started with the SEQC2/HCC1395 minimal WES pair before attempting full WGS.
3. Created a tumor-normal remote samplesheet and a local smoke samplesheet.
4. Streamed 1,000 real read pairs per FASTQ end from ENA direct FASTQ links.
5. Validated R1/R2 FASTQ structure, 151 bp read length, read-ID pairing, GC/N fractions, and local smoke file paths.
6. Recorded the local tooling audit.

Exit criteria:

1. One representative tumor-normal raw pair can be subsetted reproducibly. **Complete.**
2. FASTQ pairing, read layout, and basic QC are validated. **Complete.**
3. Limitations are explicit: ENA direct FASTQ subset versus full-depth WES/WGS. **Complete.**

Key outputs:

1. `manifests/raw_samplesheet.csv`
2. `manifests/raw_smoke_samplesheet.csv`
3. `results/raw_smoke/README.md`
4. `results/raw_smoke/fastq_smoke_summary.csv`
5. `results/raw_smoke/tooling_audit.md`

## Phase 2B: Alignment And Somatic-Caller Input Readiness

Status: **next**.

Goal: take the Phase 2A smoke FASTQs or a larger downsample through alignment/BAM generation and somatic-caller input validation.

Required work:

1. Install or containerize a genomics stack: SRA Toolkit or ENA download route, FastQC/MultiQC, BWA/BWA-MEM2 or nf-core/sarek, samtools, and a somatic caller path.
2. Confirm reference build and intervals before any alignment.
3. Run the minimal WES pair through either a tiny synthetic/reference smoke or a small real-reference subset on a genomics-ready machine.
4. Produce BAM/CRAM/QC artifacts or a complete nf-core/sarek test-profile equivalent.
5. Keep WES-limited evidence separate from WGS signature evidence.

## Phase 3: WGS HRD Signature Capability

Status: **planned**.

Goal: test the full WGS-capable HRD interpretation lane.

Required work:

1. Run representative HCC1395 WGS tumor-normal data on cloud/HPC or sufficiently large local storage.
2. Produce alignment/QC, somatic SNV/indel calls, copy-number/SV calls, and mutation matrices.
3. Compare against SEQC2 truth-set or benchmark artifacts where available.
4. Add SigProfilerAssignment, CHORD, scarHRD, and eventually HRDetect-style feature handling where inputs support it.
5. Keep WGS-specific evidence separate from WES-limited evidence.

Exit criteria:

1. WGS smoke or full run completes without hidden manual steps.
2. Signature/SV/CHORD/scar evidence tables have real tool outputs, not proxies.
3. The reviewer packet can distinguish WES partial HRD evidence from WGS-grade HRD evidence.

## Phase 4: Diana Data Application

Status: **blocked until Diana raw files and reviewer gate**.

Required before starting:

1. Tumor-normal DNA file inventory: FASTQ/BAM/CRAM, WES/WGS, reference build, matched normal, and sample IDs.
2. RNA file inventory if available: FASTQ/BAM/counts, library type, strandness, batch, and quality metadata.
3. Sample context: tissue block/core, timing, fixation, tumor purity/content, and extraction details.
4. Reviewer agreement that Phase 2/3 representative-data checks are adequate.
5. Clear action boundary: reviewer biology versus clinician/companion-diagnostic decision.

Exit criteria:

1. Diana data runs through the same validated samplesheet and evidence-table workflow.
2. Results are caveated by input suitability and reviewer sign-off.
3. No treatment-changing claim is made from open-source outputs alone.
