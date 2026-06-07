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
6. The alignment smoke produces coordinate-sorted tumor and normal BAMs with indexes and read groups.
7. The alignment report preserves the boundary between file-contract validation and human-reference biology.
8. The partial human-reference smoke validates hg38 and hg19 reference handling with checksum-verified FASTA inputs.
9. The full-reference smoke validates one full analysis-set reference, BRCA interval metadata, caller-ready BAM contracts, and indexed VCF generation.
10. The production somatic smoke validates a pinned tumor-normal caller path, larger WES downsample, indexed filtered somatic VCF, and explicit SEQC2 truth-comparison status.
11. The full WES benchmark validates complete representative FASTQs, full-reference alignment, duplicate marking, contamination estimation, PoN-aware Mutect2, and covered truth-overlap metrics.

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

## Phase 2B Result

Status: **complete for local file-contract validation**.

The local machine now has a minimal alignment stack for a contained BAM smoke:

1. `bwa 0.7.19`.
2. `samtools 1.23.1`.
3. A read-backed synthetic smoke reference built from the Phase 2A FASTQ subset.
4. Tumor and normal coordinate-sorted BAMs under ignored local `data/raw/smoke/`.
5. Tracked validation summaries under `results/alignment_smoke/`.

This validates FASTQ-to-BAM mechanics, read groups, BAM sorting/indexing, shared reference hash, mapped reads, and `samtools quickcheck`.

It does **not** validate GRCh37/GRCh38 alignment, capture interval behavior, full-depth WES/WGS performance, somatic calls, CNV/SV calls, or HRD signatures.

## Phase 2C Result

Status: **complete for partial real-human-reference validation**.

The project now downloads and validates partial UCSC human references for two builds:

1. `ucsc_hg38_chr13_chr17`: GRCh38/hg38 chr13 + chr17.
2. `ucsc_hg19_chr13_chr17`: GRCh37/hg19 chr13 + chr17.

The smoke run validates:

1. UCSC FASTA download and md5 validation.
2. `samtools faidx` indexing.
3. BWA reference indexing.
4. HCC1395 tumor and normal alignment to both builds.
5. Coordinate-sorted/indexed BAMs with read groups.
6. Expected chr13/chr17 contig handling and mapped reads.

This intentionally uses chr13 and chr17 because they carry BRCA2 and BRCA1. It is a real-reference alignment smoke, not a full genome bundle and not a full-depth WES/WGS run.

## Phase 2D Result

Status: **complete for one full-reference caller-readiness smoke**.

The project now validates one full reference bundle:

1. `ucsc_hg38_analysis_set_full`: UCSC hg38 / GRCh38 analysis set.
2. Source: `https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/analysisSet/hg38.analysisSet.fa.gz`.
3. Local cached footprint after FASTA, `.fai`, and BWA index: about 9 GB.

The smoke run validates:

1. Full reference download and md5 validation.
2. `samtools faidx` indexing.
3. BWA full-reference indexing.
4. HCC1395 tumor and normal alignment to the full reference.
5. Coordinate-sorted/indexed BAMs with read groups.
6. BRCA1/BRCA2 interval metadata for caller readiness.
7. `bcftools mpileup/call` execution and indexed VCF output.

The VCF smoke produced zero variants, which is acceptable here because the tiny downsample and interval slice are not intended to recover biology. The exit criterion is caller execution and VCF contract validation.

## Phase 2E Result

Status: **complete for one downsampled production-style somatic-caller smoke**.

The project now validates a pinned production-style somatic caller path:

1. Caller: `GATK Mutect2 + FilterMutectCalls`.
2. GATK version: `4.6.2.0`.
3. Java runtime: OpenJDK 17.
4. Reference: `ucsc_hg38_analysis_set_full`.
5. Caller-specific reference extra: GATK sequence dictionary.
6. Truth materials: SEQC2/HCC1395 high-confidence SNV/INDEL v1.2.1 VCFs and high-confidence BED.
7. Downsample: 50,000 read pairs per FASTQ end from `SRR7890850` tumor and `SRR7890851` normal.
8. Active intervals: 500 mapped-read intervals, with 245 SNV and 12 indel truth records inside the active interval set.
9. Mutect2 result: indexed filtered VCF produced; zero filtered/PASS records in this bounded downsample.

The zero-call result is acceptable for Phase 2E because the exit criterion is production-style execution and file-contract validation, not sensitivity. Full-depth WES sensitivity remains a separate gate.

## Phase 2F Result

Status: **complete and validated**.

The project now validates the full SEQC2/HCC1395 WES representative pair:

1. Full tumor FASTQs: `SRR7890850` R1/R2.
2. Full matched-normal FASTQs: `SRR7890851` R1/R2.
3. Reference: `ucsc_hg38_analysis_set_full`.
4. Duplicate marking: GATK MarkDuplicates.
5. Somatic caller: GATK Mutect2 + FilterMutectCalls.
6. Production resource used locally: Broad hg38 1000g panel of normals.
7. Contamination resource used locally: common-biallelic gnomAD.
8. Production resource documented for cloud/full production: Broad hg38 af-only gnomAD germline resource.
9. Truth benchmark: SEQC2/HCC1395 high-confidence SNV/INDEL truth variants covered by the full WES BAMs.

Measured Phase 2F benchmark:

1. Full FASTQs validated: 4.
2. Tumor source read pairs: 26,749,449.
3. Normal source read pairs: 34,905,382.
4. Benchmark intervals: 1,277.
5. Depth-eligible truth variants: 1,307.
6. PASS calls in benchmark intervals: 1,140.
7. Exact PASS truth matches: 1,122.
8. Exact PASS recall: 0.8585.
9. Exact PASS precision: 0.9842.
10. Contamination estimate: 0.0.
11. Ready for Phase 3: yes.

The output distinguishes full-depth WES small-variant readiness from WGS-grade HRD signature readiness. Remaining production decisions are Diana-specific or Phase 3 decisions: BQSR known-sites, vendor capture BEDs, orientation-bias modeling, full af-only gnomAD use, allele-specific copy-number, SV calling, and WGS signatures.

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
