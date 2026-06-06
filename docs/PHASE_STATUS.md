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

Status: **complete and validated for local BAM file-contract smoke**.

Goal: take the Phase 2A smoke FASTQs through local alignment/BAM generation and somatic-caller input validation.

Completed work:

1. Installed a minimal local alignment stack: `bwa` and `samtools`.
2. Built `manifests/alignment_smoke_samplesheet.csv`.
3. Built a read-backed synthetic smoke reference from the HCC1395 tumor-normal FASTQ subset.
4. Ran `bwa mem` and `samtools sort/index/quickcheck/stats` for tumor and normal.
5. Validated coordinate-sorted BAMs, indexes, read groups, shared reference hash, mapped reads, and tumor-normal rows.
6. Recorded the boundary that this is not GRCh37/GRCh38 alignment, somatic calling, or HRD signature evidence.

Exit criteria:

1. Tumor and normal representative FASTQs align locally. **Complete.**
2. BAM/BAI files are generated, coordinate-sorted, indexed, and read-grouped. **Complete.**
3. Somatic-caller input file-contract checks pass. **Complete.**
4. Biological and reference-build limitations are explicit. **Complete.**

Key outputs:

1. `manifests/alignment_smoke_samplesheet.csv`
2. `results/alignment_smoke/README.md`
3. `results/alignment_smoke/reference_summary.json`
4. `results/alignment_smoke/alignment_smoke_summary.csv`
5. `results/alignment_smoke/bam_validation_summary.csv`

## Phase 2C: Human-Reference And Full-Depth Readiness

Status: **complete and validated for partial real-human-reference smoke**.

Goal: move from local file-contract smoke to a real human-reference WES/WGS workflow.

Completed work:

1. Added two partial UCSC human-reference bundles:
   - `ucsc_hg38_chr13_chr17` / GRCh38 / hg38.
   - `ucsc_hg19_chr13_chr17` / GRCh37 / hg19.
2. Used chr13 and chr17 because they cover BRCA2 and BRCA1 while keeping the local smoke repeatable.
3. Downloaded UCSC per-chromosome FASTA files, validated md5s, concatenated FASTA bundles, and built `.fai` plus BWA indexes locally.
4. Built `manifests/human_reference_smoke_references.csv` and `manifests/human_reference_smoke_samplesheet.csv`.
5. Aligned HCC1395 tumor and normal FASTQs to both references.
6. Validated coordinate-sorted BAMs, indexes, read groups, shared reference hashes, expected contigs, mapped reads, and build comparison summaries.

Exit criteria:

1. At least two human reference builds are represented. **Complete: hg38/GRCh38 and hg19/GRCh37.**
2. Reference source checksums validate. **Complete.**
3. Tumor and normal HCC1395 FASTQs align to both builds. **Complete.**
4. BAM/BAI file contracts pass for every sample/build row. **Complete.**
5. Limitations remain explicit: partial chr13/chr17 only, not full-depth WES/WGS, somatic calling, CNV/SV calling, or HRD signatures. **Complete.**

Key outputs:

1. `manifests/human_reference_smoke_references.csv`
2. `manifests/human_reference_smoke_samplesheet.csv`
3. `results/human_reference_smoke/README.md`
4. `results/human_reference_smoke/human_reference_alignment_summary.csv`
5. `results/human_reference_smoke/bam_validation_summary.csv`
6. `results/human_reference_smoke/reference_comparison_summary.csv`

## Phase 2D: Full Reference, Intervals, And Somatic Caller Readiness

Status: **next**.

Goal: move from partial human-reference smoke to full WES/WGS caller readiness.

Required work:

1. Decide the exact production reference bundle for Diana intake: GRCh38, GRCh37/hg19, hs37d5, or vendor-specific reference.
2. Add WES capture intervals and known-sites resources if WES/GATK-style workflows are used.
3. Install or containerize full QC/workflow tools: FastQC/MultiQC, SRA Toolkit or ENA download route, Nextflow or another pinned workflow runtime, and a somatic caller path.
4. Run a larger HCC1395 WES downsample or full WES pair against the selected full reference.
5. Produce full-reference BAM/CRAM/QC artifacts and somatic-caller-ready inputs.
6. Keep WES-limited evidence separate from WGS signature evidence.

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
