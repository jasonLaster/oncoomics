# Methods

## Data Sources

- cBioPortal study: `brca_tcga_pan_can_atlas_2018`, imported by cBioPortal on 2026-06-05 according to live study metadata.
- GDC: TCGA-BRCA open file catalog metadata only, used to verify public/open project availability and access posture.
- UCSC Xena: TCGA-BRCA clinical matrix, used for PAM50/receptor-status context and sample-ID cross-checking.
- SEQC2/HCC1395: public tumor-normal WES/WGS raw-data benchmark metadata and small FASTQ subsets used for raw-read and alignment smoke tests.
- UCSC Genome Browser: hg38/GRCh38 and hg19/GRCh37 chr13+chr17 FASTA references used for Phase 2C partial human-reference alignment smoke.
- UCSC Genome Browser: hg38/GRCh38 analysisSet FASTA used for Phase 2D full-reference caller-readiness smoke.
- GATK/SEQC2: GATK Mutect2/FilterMutectCalls and SEQC2 HCC1395 high-confidence SNV/INDEL truth VCFs used for Phase 2E production-style somatic-caller smoke, Phase 2F full WES truth-overlap benchmarking, and Phase 3 WGS validation.

## HRD Evidence

The phase-1 analysis uses processed public TCGA-BRCA evidence:

1. HRR mutation records from cBioPortal's processed WES mutation profile.
2. GISTIC discrete copy-number calls as a copy-loss proxy.
3. Sample clinical fields for fraction genome altered, aneuploidy score, mutation count, and nonsynonymous TMB.

Likely damaging variants are rule-classified as nonsense, frameshift, splice-site, translation-start, nonstop, or cBioPortal keyword matches for truncating/frameshift/splice events. This is not manual clinical variant curation.

## RNA Context

RNA context uses selected marker genes from cBioPortal RNA Seq V2 RSEM batch-normalized values. Scores are log2(value + 1), z-scored across the fetched cohort, then averaged into marker modules.

## Raw-Data Smoke Lanes

Phase 2A validates direct raw FASTQ access and pairing from a small SEQC2/HCC1395 tumor-normal WES subset. Phase 2B validates local FASTQ-to-BAM mechanics against a read-backed synthetic smoke reference. Phase 2C validates partial real-human-reference alignment against UCSC hg38 and hg19 chr13+chr17 references. Phase 2D validates one full reference, the UCSC hg38 analysis set, with BRCA1/BRCA2 interval metadata, full-reference BAM contracts, and a tiny indexed VCF caller smoke. Phase 2E validates a production-style GATK Mutect2 tumor-normal execution path on a larger HCC1395 WES downsample. Phase 2F validates full ENA WES FASTQ downloads, full-reference alignment, GATK duplicate marking, Broad hg38 PoN use, common-biallelic contamination estimation, and a bounded SEQC2 truth-overlap Mutect2 benchmark. Phase 3 currently validates bounded developer WGS mechanics; the full-source public WGS acceptance gate is still pending.

These raw lanes are plumbing, file-contract, WES small-variant benchmark, and WGS-capability validators. They do not yet produce clinically interpretable Diana calls, allele-specific CNV segments, validated SV caller VCFs, WGS rearrangement signatures, or HRD signatures.

## Non-Run Lanes

Full-depth WGS rearrangement signature interpretation, scarHRD, CHORD, HRDetect, FACETS/ASCAT/PURPLE allele-specific LOH, methylation-specific second-hit evidence, and companion diagnostics were not run as final clinical classifiers. Phase 3 writes real WGS feature outputs for the relevant lanes, but full-source acceptance and classification remain gated until the public WGS run passes and Diana data plus reviewer-approved production tooling are available.
