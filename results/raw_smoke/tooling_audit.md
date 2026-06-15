# Raw Tooling Audit

Phase 2A direct-FASTQ smoke ready: **yes**

Alignment/BAM ready locally: **yes**

Full aligner toolbox available: **yes**

Workflow/container runtime available: **yes**

Full QC/workflow runtime available: **yes**

Alignment-ready definition: At least one short-read aligner from bwa/bwa-mem2/minimap2 plus samtools.

Phase 2C partial human-reference smoke ready: **yes**

Phase 2D full-reference caller-readiness smoke ready: **yes**

Phase 2E production somatic Mutect2 smoke ready: **yes**

Phase 2F full WES benchmark ready: **yes**

Phase 3 WGS validation toolchain ready: **yes**

Phase 3 optional signature runtime available: **yes**

Native Python HRD foundation ready: **no**

SV benchmark comparator ready: **no**

SigProfilerAssignment ready: **no**

## baseline_streaming

Required for: Phase 2A direct FASTQ metadata and tiny read-subset smoke

- curl: /usr/bin/curl
- gunzip: /usr/bin/gunzip
- gzip: /usr/bin/gzip
- python3: /usr/bin/python3

## sra_conversion

Required for: NCBI SRA prefetch and local full-run conversion

- prefetch: /usr/bin/prefetch
- fasterq-dump: /usr/bin/fasterq-dump
- fastq-dump: /usr/bin/fastq-dump
- vdb-config: /usr/bin/vdb-config

## qc

Required for: Standard FASTQ QC and aggregate reports

- fastqc: missing
- multiqc: missing
- seqtk: missing
- seqkit: /usr/bin/seqkit

## alignment_and_bam

Required for: Reference alignment and BAM/CRAM generation

- bwa: /usr/bin/bwa
- bwa-mem2: /usr/local/bin/bwa-mem2
- minimap2: /usr/local/bin/minimap2
- samtools: /usr/bin/samtools

## caller_smoke

Required for: Tiny local variant-caller smoke and VCF contract checks

- bcftools: /usr/bin/bcftools

## production_somatic_caller

Required for: Phase 2E GATK Mutect2 production-style tumor-normal somatic smoke

- java17: /usr/bin/java
- unzip: /usr/bin/unzip

## full_wes_benchmark

Required for: Phase 2F full WES benchmark download, duplicate marking, contamination, and truth-overlap calling

- curl: /usr/bin/curl
- gzip: /usr/bin/gzip
- bwa: /usr/bin/bwa
- samtools: /usr/bin/samtools
- bcftools: /usr/bin/bcftools
- java17: /usr/bin/java

## phase3_wgs_smoke

Required for: Phase 3 representative WGS alignment, Mutect2, coverage-CNV bins, SBS96 matrix, and BAM-derived SV evidence

- curl: /usr/bin/curl
- gunzip: /usr/bin/gunzip
- gzip: /usr/bin/gzip
- bwa: /usr/bin/bwa
- samtools: /usr/bin/samtools
- bcftools: /usr/bin/bcftools
- java17: /usr/bin/java

## phase3_wgs_optional_signature_callers

Required for: Full-depth WGS CHORD/scarHRD/HRDetect/SigProfiler production interpretation

- R: missing
- python3: /usr/bin/python3
- nextflow: missing
- docker: missing
- singularity: missing
- apptainer: missing

## workflow_runtime

Required for: nf-core/sarek or containerized raw-data workflow execution

- nextflow: missing
- docker: missing
- singularity: missing
- apptainer: missing
- conda: missing
- micromamba: /usr/local/bin/micromamba

## native_python_integrations

Optional extras are staged in `pyproject.toml`; missing packages do not block fallback-safe smoke validation.

- pysam: missing - native BAM/VCF/BCF parsing for full-depth variant and alignment checks
- pyfaidx: missing - indexed reference-sequence lookup for SBS96 and normalization features
- polars: missing - larger manifest and result joins once multi-sample validation scales
- truvari: missing - SV truth-set comparison for HG008 and COLO829 orthogonal validation
- SigProfilerAssignment: missing - SBS signature assignment once full WGS mutation counts are adequate

## Conclusion

Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, Phase 2D full-reference caller-readiness smoke tests, Phase 2E GATK Mutect2 production-style somatic smoke tests, Phase 2F full WES benchmark mechanics, and Phase 3 full-source WGS validation mechanics. Final HRD interpretation still requires Diana data and reviewer-approved CNV/SV/signature policy.
