# Full-Reference Caller-Readiness Smoke

Status: **passed**.

Reference: `ucsc_hg38_analysis_set_full` / GRCh38 / hg38

Input: Phase 2A local SEQC2/HCC1395 FASTQ subset.

Tools:

1. `bwa mem`
2. `samtools sort/index/quickcheck/stats/faidx`
3. `bcftools mpileup/call/index/stats`

What this validates:

1. Full UCSC hg38 analysis-set FASTA download and md5 validation.
2. Full-reference `.fai` and BWA index creation.
3. BRCA1/BRCA2 interval metadata is present in the samplesheet.
4. Tumor and normal FASTQs align to the full reference.
5. BAMs are coordinate-sorted, indexed, read-grouped, and pass `samtools quickcheck`.
6. A tiny VCF caller smoke runs over the BRCA interval BED and produces an indexed VCF.

What this does not validate yet:

1. Full-depth WES/WGS coverage or sensitivity.
2. Vendor capture interval compatibility.
3. A true tumor-normal somatic caller such as Mutect2/Strelka2.
4. CNV/SV calling.
5. scarHRD/CHORD/HRDetect/SBS3 evidence.

Boundary: this is full-reference and caller-readiness plumbing, not biological interpretation.
