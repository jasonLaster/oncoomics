# Full WES Benchmark

Status: **passed**.

Phase 2F caller path: `GATK Mutect2 + FilterMutectCalls with hg38 PoN; common-biallelic gnomAD for contamination pileups`

Reference: `ucsc_hg38_analysis_set_full` (GRCh38/hg38)

Input: full ENA FASTQ gzip files for SEQC2/HCC1395 WES tumor-normal pair.

What this validates:

1. Full WES FASTQ downloads match source MD5 and byte counts.
2. Full WES tumor and matched normal reads align to the full hg38 analysis-set reference.
3. BAMs are coordinate-sorted, duplicate-marked, indexed, read-grouped, and pass `samtools quickcheck`.
4. Mutect2 runs with the Broad hg38 1000g panel of normals; the full af-only gnomAD resource is documented as a production-scale input.
5. GetPileupSummaries and CalculateContamination run with the common-biallelic gnomAD resource inside the bounded BRCA interval set.
6. The filtered VCF is indexed and compared to SEQC2 high-confidence truth variants inside covered benchmark intervals.
7. The output separates full-depth WES small-variant readiness from WGS HRD signature/CNV/SV readiness.

Benchmark interval count: `1277`

Depth-eligible truth variants: `1307`

PASS truth matches: `1122`

Exact PASS recall: `0.8585`

Exact PASS precision: `0.9842`

Contamination status: `passed`

Contamination estimate: `0.0`

Deferred production policies:

1. BQSR is documented but not run until matching known-sites and capture intervals are selected.
2. The full Broad af-only gnomAD germline resource is documented but not downloaded into the local Phase 2F gate because the canonical file is multi-GB.
3. Capture-interval behavior is inferred from full WES coverage and SEQC2 truth-overlap intervals, not from a vendor BED.

Boundary: this closes Phase 2 raw WES readiness; Phase 3 is WGS HRD signature, CNV, and SV capability.
