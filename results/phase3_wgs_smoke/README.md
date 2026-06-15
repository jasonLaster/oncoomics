# Phase 3 WGS HRD Capability Validation

Status: **passed**.

Representative pair: `seqc2_hcc1395_wgs_hiseqx_full`

Reference: `ucsc_hg38_analysis_set_full` (GRCh38/hg38)

Reads per FASTQ end: `942559447`

Read mode: `full`

Parallelism:

1. Available CPUs detected: `32`
2. Total thread budget: `16`
3. Tumor/normal alignment in parallel: `no`
4. Split-process BWA threads: `16`
5. Split-process samtools sort threads: `16`
6. Monolith per-sample BWA threads: `16`
7. Monolith per-sample samtools sort threads: `16`
8. GATK PairHMM threads: `8`

What this validates:

1. Real representative HCC1395 WGS FASTQ alignment to the full hg38 analysis-set reference.
2. Coordinate-sorted, indexed, read-grouped tumor and matched-normal WGS BAM contracts.
3. Real GATK Mutect2/FilterMutectCalls tumor-normal WGS VCF output.
4. Real coverage-derived tumor/normal CNV bin output from `samtools bedcov`.
5. Real SBS96 mutation matrix output from the actual WGS VCF.
6. Real BAM-derived SV evidence counts from split/supplementary/discordant/interchromosomal read evidence.
7. A clear boundary between WES small-variant evidence, WGS-capable smoke outputs, and full-depth WGS HRD interpretation.

What remains Diana-specific:

1. Full-depth WGS or WES input inventory, reference policy, and production compute target.
2. Allele-specific CNV segmentation for scarHRD.
3. Validated SV caller VCF for CHORD/HRDetect-style feature extraction.
4. Stable SBS signature assignment only when mutation count and coverage are adequate.
5. Reviewer sign-off before any treatment-changing interpretation.
