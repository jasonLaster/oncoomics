# Full WES Benchmark

Status: **passed**.

Phase 2F caller path: `GATK Mutect2 + FilterMutectCalls with hg38 PoN; common-biallelic gnomAD for contamination pileups`

Reference: `ucsc_hg38_analysis_set_full` (GRCh38/hg38)

Input: full ENA FASTQ gzip files for SEQC2/HCC1395 WES tumor-normal pair.

Benchmark interval count: `1277`

Depth-eligible truth variants: `1307`

PASS truth matches: `1122`

Exact PASS recall: `0.8585`

Exact PASS precision: `0.9842`

Contamination status: `passed`

Contamination estimate: `0.0`

Boundary: this closes Phase 2 raw WES readiness; Phase 3 is WGS HRD signature, CNV, and SV capability.
