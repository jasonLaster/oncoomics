# Production Somatic Smoke

Status: **passed**.

Phase 2E caller path: `GATK Mutect2 + FilterMutectCalls`

Reference: `ucsc_hg38_analysis_set_full` (GRCh38/hg38)

Input: SEQC2/HCC1395 public WES tumor-normal pair, downsampled to `50000` read pairs per FASTQ end.

What this validates:

1. GATK is pinned locally and executable with Java 17+.
2. The full hg38 analysis-set reference has FASTA, `.fai`, and GATK sequence dictionary assets.
3. Tumor and matched normal FASTQs align to coordinate-sorted, indexed, read-grouped BAMs.
4. Active Mutect2 intervals are derived from real mapped reads and truth-overlap-prioritized where compatible.
5. Mutect2 and FilterMutectCalls produce an indexed, production-style somatic VCF.
6. SEQC2 high-confidence SNV/INDEL truth VCFs are available for exact-key overlap checks inside active intervals.

What this does not validate:

1. Full-depth WES sensitivity or specificity.
2. Production PoN, germline-resource, contamination, orientation-bias, BQSR, or duplicate-marking resource policy.
3. CNV/SV calling.
4. scarHRD/CHORD/HRDetect/SBS3 or other WGS-grade HRD signature evidence.
5. Clinical actionability for Diana.

Truth comparison status: `assessed_no_passing_mutect2_calls`

Boundary: WES-limited Mutect2 smoke evidence is kept separate from WGS HRD signature evidence.
