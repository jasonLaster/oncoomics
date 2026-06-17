# Diana Readiness Gate

Status: **ready for Phase 4 setup once Diana raw files arrive; also not ready for clinical interpretation without raw-file inventory, Diana-specific production resource decisions, WGS/CNV/SV/signature policy, and reviewer sign-off**.

## Required Before Diana Data

1. Confirm tumor-normal DNA source, data type, reference build, matched normal, and whether data are WES or WGS.
2. Confirm bulk RNA source, library type, normalization route, batch, and RNA quality metadata.
3. Confirm sample timing, tissue block/core, tumor purity or tumor content, fixation, and extraction context.
4. Decide whether open analysis is for reviewer biology only or whether a clinician will order orthogonal validation.
5. Confirm whether the requested DNA workflow should be GRCh38, GRCh37/hg19, hs37d5, or a vendor-specific reference bundle.
6. Confirm WES intervals, known-sites resources, germline-resource/PoN/contamination policy, and final production somatic-caller route if raw DNA is FASTQ/BAM/CRAM.
7. If Diana DNA is WGS, confirm CNV/SV/signature tooling, compute target, and benchmark thresholds before interpreting HRD signatures.
8. Run or confirm the Phase 3 full-source public WGS validation before Diana data arrive.
9. Get reviewer sign-off on the benchmark caveats.

## Validation State

The benchmark mechanics are runnable and validated on open processed public data. The raw-read lane now has:

1. Phase 2A direct FASTQ smoke on SEQC2/HCC1395 tumor-normal WES.
2. Phase 2B local FASTQ-to-coordinate-sorted-BAM smoke with read groups and indexes.
3. Phase 2C partial real-human-reference alignment smoke across UCSC hg38/GRCh38 and hg19/GRCh37 chr13+chr17 references.
4. Phase 2D full-reference caller-readiness smoke using the UCSC hg38 analysis set, BRCA1/BRCA2 interval metadata, and an indexed bcftools VCF contract smoke.
5. Phase 2E GATK Mutect2 production-style tumor-normal smoke on a larger HCC1395 WES downsample, with SEQC2 truth VCFs available for bounded overlap checks.
6. Phase 2F full WES benchmark on the SEQC2/HCC1395 tumor-normal pair, with full FASTQ MD5 validation, full-reference BAM contracts, GATK duplicate marking, common-biallelic contamination estimation, PoN-aware Mutect2, and bounded truth-overlap metrics.
7. Phase 3 full-source representative WGS validation on the SEQC2/HCC1395 tumor-normal WGS pair, with full-reference BAM contracts, Mutect2 WGS output, coverage-CNV bins, SBS96 matrix output, and BAM-derived SV evidence.

The current workflow is sufficient to validate project plumbing, samplesheet shape, local BAM file contracts, partial and full human-reference handling, a production-style Mutect2 execution path, indexed somatic VCF outputs, full WES small-variant benchmark behavior, WGS feature-lane mechanics, and evidence-table boundaries. It is not sufficient to make a treatment-changing HRD claim, and it does not yet validate allele-specific CNV calls, production SV caller VCFs, or WGS-grade HRD signatures.
