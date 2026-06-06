# Raw Tooling Audit

Phase 2A direct-FASTQ smoke ready: **yes**

Alignment/BAM ready locally: **no**

Workflow/container runtime available: **no**

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

- bwa: missing
- bwa-mem2: missing
- minimap2: missing
- samtools: missing

## workflow_runtime

Required for: nf-core/sarek or containerized raw-data workflow execution

- nextflow: missing
- docker: missing
- singularity: missing
- apptainer: missing
- conda: missing
- micromamba: missing

## Conclusion

Local machine can run Phase 2A direct-FASTQ smoke tests. Alignment/caller phases require additional tools or containers.
