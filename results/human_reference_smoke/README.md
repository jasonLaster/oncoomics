# Human-Reference Smoke Test

Status: **passed**.

Smoke pair: `seqc2_hcc1395_wes_minimal_smoke`

Input: Phase 2A local SEQC2/HCC1395 FASTQ subset.

References:

1. `ucsc_hg38_chr13_chr17` / GRCh38 / hg38 / chr13 + chr17.
2. `ucsc_hg19_chr13_chr17` / GRCh37 / hg19 / chr13 + chr17.

Why these chromosomes:

1. chr13 contains BRCA2.
2. chr17 contains BRCA1.
3. Two real reference builds validate build-specific samplesheet and BAM-contract handling without requiring a full local genome bundle.

What this validates:

1. Real UCSC human-reference FASTA download and checksum validation.
2. FASTA indexing with `samtools faidx`.
3. BWA indexing for multiple reference builds.
4. Tumor and normal FASTQ alignment to hg38 and hg19 partial references.
5. Coordinate-sorted/indexed BAMs with read groups and mapped reads.
6. Shared reference-hash tracking in the samplesheet and result summaries.

What this does not validate yet:

1. Full GRCh37/GRCh38/hs37d5 genome bundles.
2. Capture intervals and known-sites resources.
3. Full-depth WES/WGS runtime, coverage, or storage behavior.
4. Somatic SNV/indel, CNV, or SV calling.
5. scarHRD/CHORD/HRDetect/SBS3 evidence.

Boundary: this is a real-human-reference alignment smoke for plumbing and reference-build validation, not a biological HRD result.
