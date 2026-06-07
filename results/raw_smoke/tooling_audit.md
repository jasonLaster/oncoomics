# Raw Tooling Audit

Phase 2A direct-FASTQ smoke ready: **yes**

Alignment/BAM ready locally: **yes**

Full aligner toolbox available: **no**

Workflow/container runtime available: **no**

Full QC/workflow runtime available: **no**

Alignment-ready definition: At least one short-read aligner from bwa/bwa-mem2/minimap2 plus samtools.

Phase 2C partial human-reference smoke ready: **yes**

Phase 2D full-reference caller-readiness smoke ready: **yes**

Phase 2E production somatic Mutect2 smoke ready: **yes**

## baseline_streaming

Required for: Phase 2A direct FASTQ metadata and tiny read-subset smoke

- bun: /Users/jasonlaster/.bun/bin/bun
- curl: /usr/bin/curl
- gunzip: /usr/bin/gunzip
- gzip: /usr/bin/gzip
- python3: /usr/bin/python3

## sra_conversion

Required for: NCBI SRA prefetch and local full-run conversion

- prefetch: missing
- fasterq-dump: missing
- fastq-dump: missing
- vdb-config: missing

## qc

Required for: Standard FASTQ QC and aggregate reports

- fastqc: missing
- multiqc: missing
- seqtk: missing
- seqkit: missing

## alignment_and_bam

Required for: Reference alignment and BAM/CRAM generation

- bwa: /opt/homebrew/bin/bwa
- bwa-mem2: missing
- minimap2: missing
- samtools: /opt/homebrew/bin/samtools

## caller_smoke

Required for: Tiny local variant-caller smoke and VCF contract checks

- bcftools: /opt/homebrew/bin/bcftools

## production_somatic_caller

Required for: Phase 2E GATK Mutect2 production-style tumor-normal somatic smoke

- java17: /opt/homebrew/opt/openjdk@17/bin/java
- unzip: /usr/bin/unzip

## workflow_runtime

Required for: nf-core/sarek or containerized raw-data workflow execution

- nextflow: missing
- docker: missing
- singularity: missing
- apptainer: missing
- conda: missing
- micromamba: missing

## Conclusion

Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, Phase 2D full-reference caller-readiness smoke tests, and Phase 2E GATK Mutect2 production-style somatic smoke tests. Full workflow/WGS signature phases still require additional tools, resources, or containers.
