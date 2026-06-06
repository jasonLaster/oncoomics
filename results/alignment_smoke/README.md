# Alignment Smoke Test

Status: **passed**.

Smoke pair: `seqc2_hcc1395_wes_minimal_smoke`

Input: Phase 2A local SEQC2/HCC1395 FASTQ subset.

Reference: `seqc2_hcc1395_readback_smoke_v1`

Tools:

1. `bwa mem`
2. `samtools sort/index/quickcheck/stats`

What this validates:

1. Tumor and normal FASTQs can be aligned locally.
2. BAMs are coordinate-sorted and indexed.
3. Read groups are present with sample identifiers.
4. Tumor and normal BAMs use the same reference dictionary.
5. BAM files pass `samtools quickcheck` and expose mapped reads.

What this does not validate yet:

1. GRCh37/GRCh38 or hs37d5 alignment.
2. Full WES/WGS depth or capture interval performance.
3. Somatic SNV/indel calling.
4. CNV/SV calling.
5. scarHRD/CHORD/HRDetect/SBS3 evidence.

Boundary: this is a local file-contract smoke against a read-backed synthetic reference, not a biological result.
