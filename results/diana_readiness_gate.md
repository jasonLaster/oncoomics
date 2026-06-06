# Diana Readiness Gate

Status: **not ready to run on Diana files without raw-file inventory, full-reference/caller decision, and reviewer sign-off**.

## Required Before Diana Data

1. Confirm tumor-normal DNA source, data type, reference build, matched normal, and whether data are WES or WGS.
2. Confirm bulk RNA source, library type, normalization route, batch, and RNA quality metadata.
3. Confirm sample timing, tissue block/core, tumor purity or tumor content, fixation, and extraction context.
4. Decide whether open analysis is for reviewer biology only or whether a clinician will order orthogonal validation.
5. Confirm whether the requested DNA workflow should be GRCh38, GRCh37/hg19, hs37d5, or a vendor-specific reference bundle.
6. Confirm WES intervals, known-sites resources, and somatic-caller route if raw DNA is FASTQ/BAM/CRAM.
7. Get reviewer sign-off on the benchmark caveats.

## Validation State

The benchmark mechanics are runnable and validated on open processed public data. The raw-read lane now has:

1. Phase 2A direct FASTQ smoke on SEQC2/HCC1395 tumor-normal WES.
2. Phase 2B local FASTQ-to-coordinate-sorted-BAM smoke with read groups and indexes.
3. Phase 2C partial real-human-reference alignment smoke across UCSC hg38/GRCh38 and hg19/GRCh37 chr13+chr17 references.

The current workflow is sufficient to validate project plumbing, samplesheet shape, local BAM file contracts, partial human-reference handling, and evidence-table boundaries. It is not sufficient to make a treatment-changing HRD claim, and it does not yet validate full-depth WES/WGS coverage, somatic calls, CNV/SV calls, or WGS-grade HRD signatures.
