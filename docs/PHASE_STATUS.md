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

Status: **complete and validated for one full-reference caller-readiness smoke**.

Goal: move from partial human-reference smoke to full WES/WGS caller readiness.

Completed work:

1. Chose the UCSC `hg38.analysisSet.fa.gz` reference for the first full-reference smoke because it is explicitly prepared for next-generation alignment.
2. Downloaded the full hg38 analysis-set FASTA, validated the UCSC md5, decompressed it, built `.fai`, and built a BWA index locally.
3. Added BRCA1/BRCA2 interval metadata for chr17 and chr13 smoke checks.
4. Built `manifests/full_reference_smoke_references.csv` and `manifests/full_reference_smoke_samplesheet.csv`.
5. Aligned HCC1395 tumor and normal FASTQs to the full hg38 analysis-set reference.
6. Validated coordinate-sorted BAMs, indexes, read groups, full-reference contig dictionary shape, mapped reads, BRCA contig presence, and caller-ready scope.
7. Ran a tiny `bcftools mpileup/call` VCF smoke over the BRCA interval BED and validated that an indexed VCF is produced.

Exit criteria:

1. At least one full human reference is downloaded, checksum-validated, indexed, and recorded. **Complete: UCSC hg38 analysis set.**
2. Tumor and normal representative FASTQs align to the full reference. **Complete.**
3. BAM/BAI file contracts pass for every sample. **Complete.**
4. Caller-readiness metadata includes BRCA1/BRCA2 intervals. **Complete.**
5. A caller execution smoke produces an indexed VCF. **Complete.**
6. Limitations remain explicit: not full-depth WES/WGS, not a clinical tumor-normal somatic caller, not CNV/SV calling, and not HRD signature evidence. **Complete.**

Key outputs:

1. `manifests/full_reference_smoke_references.csv`
2. `manifests/full_reference_smoke_samplesheet.csv`
3. `results/full_reference_smoke/README.md`
4. `results/full_reference_smoke/full_reference_alignment_summary.csv`
5. `results/full_reference_smoke/bam_validation_summary.csv`
6. `results/full_reference_smoke/caller_smoke_summary.csv`

## Phase 2E: Production Somatic Workflow And Depth Scale-Up

Status: **complete and validated for one downsampled production-style Mutect2 smoke**.

Goal: move from full-reference/caller-readiness smoke to a production-style tumor-normal somatic workflow.

Completed work:

1. Chose `GATK Mutect2 + FilterMutectCalls` as the first production-style somatic caller path.
2. Pinned GATK `4.6.2.0` under the ignored local tool cache and validated Java 17 execution.
3. Added the GATK sequence dictionary for `ucsc_hg38_analysis_set_full`.
4. Downloaded SEQC2/HCC1395 high-confidence SNV/INDEL v1.2.1 truth VCFs and high-confidence BED.
5. Built `manifests/production_somatic_smoke_samplesheet.csv`.
6. Streamed 50,000 read pairs per FASTQ end from the HCC1395 WES tumor-normal pair.
7. Aligned tumor and normal to the full hg38 analysis-set reference and validated coordinate-sorted, indexed, read-grouped BAMs.
8. Built 500 active Mutect2 intervals from mapped reads, prioritizing intervals with SEQC2 truth overlap where compatible.
9. Ran Mutect2 and FilterMutectCalls and validated an indexed filtered somatic VCF.
10. Kept WES-limited small-variant evidence separate from WGS HRD signature, CNV, and SV evidence.

Exit criteria:

1. A production-style tumor-normal caller path is selected and pinned. **Complete: GATK Mutect2 4.6.2.0.**
2. Caller-specific reference extras include a GATK sequence dictionary. **Complete.**
3. A larger HCC1395 WES downsample runs against the full reference. **Complete: 50,000 read pairs/end.**
4. Production-style somatic VCF/QC outputs are produced. **Complete.**
5. SEQC2 truth materials are available and comparison status is explicit. **Complete: active intervals contained 245 SNV and 12 indel truth records; this downsample produced zero PASS Mutect2 calls.**
6. Limitations remain explicit: not full-depth WES sensitivity, not production PoN/germline-resource/contamination/BQSR policy, not CNV/SV calling, and not HRD signature evidence. **Complete.**

Key outputs:

1. `manifests/production_somatic_smoke_samplesheet.csv`
2. `results/production_somatic_smoke/README.md`
3. `results/production_somatic_smoke/asset_summary.json`
4. `results/production_somatic_smoke/bam_validation_summary.csv`
5. `results/production_somatic_smoke/mutect2_smoke_summary.csv`
6. `results/production_somatic_smoke/production_somatic_summary.csv`

## Phase 2F: Production Resources And Full-Depth WES Benchmark

Status: **complete and validated**.

Goal: move from validated Mutect2 execution smoke to full-depth WES benchmark behavior.

Completed work:

1. Added a full SEQC2/HCC1395 WES asset fetcher for the ENA tumor-normal FASTQ gzip files.
2. Validated full FASTQ MD5 checksums, source byte counts, and gzip readability.
3. Added Broad hg38 resource handling for the 1000g panel of normals and common-biallelic gnomAD contamination resource.
4. Documented the full multi-GB Broad af-only gnomAD germline resource as a production/cloud input rather than a local Phase 2F gating download.
5. Ran full-reference alignment to the UCSC hg38 analysis set for tumor and matched normal.
6. Ran GATK MarkDuplicates, indexed deduplicated BAMs, and validated read groups, coordinate sort, mapped reads, BRCA interval coverage, duplicate fractions, and BAM quickcheck.
7. Ran GetPileupSummaries and CalculateContamination on bounded BRCA intervals.
8. Built covered SEQC2 truth-overlap benchmark intervals from full WES BAM depth.
9. Ran PoN-aware GATK Mutect2 and FilterMutectCalls and compared PASS calls against covered SEQC2 SNV/INDEL truth variants.
10. Kept WES-limited small-variant evidence separate from WGS HRD signature, CNV, and SV evidence.

Measured result:

1. Full WES FASTQs validated: 4.
2. BAM validation status: passed.
3. Benchmark intervals: 1,277.
4. Depth-eligible SEQC2 truth variants: 1,307.
5. PASS calls in benchmark intervals: 1,140.
6. Exact PASS truth matches: 1,122.
7. Exact PASS recall: 0.8585.
8. Exact PASS precision: 0.9842.
9. Contamination status: passed; estimate 0.0.
10. Ready for Phase 3: yes.

Exit criteria:

1. Four full FASTQ files validate against ENA MD5 and byte counts. **Verified by `results/full_wes_benchmark/full_wes_fastq_validation.*`.**
2. Tumor and matched-normal full WES BAM contracts pass. **Verified by `results/full_wes_benchmark/full_wes_bam_validation.*`.**
3. Contamination estimation runs with the common-biallelic resource. **Verified by `results/full_wes_benchmark/truth_overlap_benchmark_summary.*`.**
4. Mutect2/FilterMutectCalls produces an indexed filtered VCF. **Verified by `results/full_wes_benchmark/full_wes_benchmark_summary.*`.**
5. Covered SEQC2 truth variants and benchmark intervals are non-empty. **Verified by `bun run verify:outputs`.**
6. `readyForPhase3` is true. **Complete.**

Key outputs:

1. `manifests/full_wes_benchmark_samplesheet.csv`
2. `results/full_wes_benchmark/README.md`
3. `results/full_wes_benchmark/asset_summary.json`
4. `results/full_wes_benchmark/full_wes_fastq_validation.csv`
5. `results/full_wes_benchmark/full_wes_bam_validation.csv`
6. `results/full_wes_benchmark/truth_overlap_benchmark_summary.csv`
7. `results/full_wes_benchmark/full_wes_benchmark_summary.csv`

## Phase 3: WGS HRD Signature Capability

Status: **complete and validated for representative WGS-capable smoke**.

Goal: test the full WGS-capable HRD interpretation lane before Diana's raw data arrive.

Completed work:

1. Selected the public SEQC2/HCC1395 HiSeq X Ten WGS tumor-normal pair:
   - Tumor: `SRR7890824`.
   - Matched normal: `SRR7890827`.
2. Streamed a bounded real WGS subset from ENA direct FASTQ links:
   - 500,000 read pairs per FASTQ end.
   - Four local FASTQ files validated for structure and R1/R2 pairing.
3. Aligned tumor and normal WGS reads to the full UCSC hg38 analysis-set reference.
4. Used local CPU parallelism:
   - 18 CPUs detected.
   - 16-thread budget.
   - Tumor/normal alignment in parallel.
   - 8 alignment/sort threads per sample.
   - 8 GATK PairHMM threads.
5. Validated full-reference WGS BAM contracts:
   - Coordinate-sorted/indexed BAMs.
   - Read groups present.
   - `samtools quickcheck` passed.
   - More than 1,004,000 alignments per sample.
6. Built covered SEQC2 truth intervals from WGS-smoke BAM depth:
   - 100 depth-eligible truth variants.
   - 99 Mutect2 intervals.
7. Ran GATK Mutect2 + FilterMutectCalls on the WGS-smoke interval set:
   - Indexed filtered VCF produced.
   - Zero PASS calls in this low-depth subset; this is recorded as an interpretability limit, not a workflow failure.
8. Produced real WGS feature-output tables:
   - `samtools bedcov` coverage-CNV bins: 631 bins.
   - VCF-derived SBS96 mutation matrix: 96 rows.
   - BAM-derived SV evidence counts from supplementary, discordant, interchromosomal, and large-insert-pair reads.
   - HRD tool readiness rows for SigProfilerAssignment, scarHRD, and CHORD that point to real local outputs and keep full-depth classification gated.
9. Kept WGS-specific evidence separate from WES-limited evidence in `results/reviewer_packet.md` and `results/diana_readiness_gate.md`.

Measured result:

1. WGS FASTQ subset rows validated: 2 samples / 4 FASTQ ends.
2. Reads per FASTQ end: 500,000.
3. BAM validation status: passed.
4. Mutect2 status: passed.
5. Mutect2 intervals: 99.
6. Depth-eligible SEQC2 truth variants: 100.
7. PASS calls in intervals: 0.
8. Coverage-CNV bins: 631.
9. SBS96 usable SNV records: 0.
10. SV evidence status: passed.
11. Ready for Phase 4 when Diana raw data arrive: yes.

Exit criteria:

1. WGS smoke or full run completes without hidden manual steps. **Complete: `bun run fetch:phase3-wgs && bun run smoke:phase3-wgs`.**
2. Signature/SV/CHORD/scar evidence tables have real tool outputs, not proxies. **Complete: real VCF-derived SBS96 matrix, real `samtools bedcov` CNV bins, and real BAM-derived SV evidence tables are written; final classifier interpretation remains gated for full-depth inputs.**
3. The reviewer packet can distinguish WES partial HRD evidence from WGS-grade HRD evidence. **Complete: reviewer packet and readiness gate now separate Phase 2F WES small-variant benchmark evidence from Phase 3 WGS-capable feature outputs.**

Key outputs:

1. `manifests/phase3_wgs_smoke_samplesheet.csv`
2. `results/phase3_wgs_smoke/README.md`
3. `results/phase3_wgs_smoke/fastq_summary.csv`
4. `results/phase3_wgs_smoke/bam_validation_summary.csv`
5. `results/phase3_wgs_smoke/mutect2_wgs_summary.csv`
6. `results/phase3_wgs_smoke/coverage_cnv_summary.csv`
7. `results/phase3_wgs_smoke/wgs_sbs96_matrix.csv`
8. `results/phase3_wgs_smoke/sv_evidence_summary.csv`
9. `results/phase3_wgs_smoke/hrd_tool_readiness_summary.csv`
10. `results/phase3_wgs_smoke/phase3_wgs_summary.csv`

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
