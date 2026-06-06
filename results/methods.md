# Methods

## Data Sources

- cBioPortal study: `brca_tcga_pan_can_atlas_2018`, imported by cBioPortal on 2026-06-05 according to live study metadata.
- GDC: TCGA-BRCA open file catalog metadata only, used to verify public/open project availability and access posture.
- UCSC Xena: TCGA-BRCA clinical matrix, used for PAM50/receptor-status context and sample-ID cross-checking.

## HRD Evidence

The phase-1 analysis uses processed public TCGA-BRCA evidence:

1. HRR mutation records from cBioPortal's processed WES mutation profile.
2. GISTIC discrete copy-number calls as a copy-loss proxy.
3. Sample clinical fields for fraction genome altered, aneuploidy score, mutation count, and nonsynonymous TMB.

Likely damaging variants are rule-classified as nonsense, frameshift, splice-site, translation-start, nonstop, or cBioPortal keyword matches for truncating/frameshift/splice events. This is not manual clinical variant curation.

## RNA Context

RNA context uses selected marker genes from cBioPortal RNA Seq V2 RSEM batch-normalized values. Scores are log2(value + 1), z-scored across the fetched cohort, then averaged into marker modules.

## Non-Run Lanes

WGS rearrangement signatures, SBS3 assignment, scarHRD, CHORD, HRDetect, FACETS/ASCAT/PURPLE allele-specific LOH, methylation-specific second-hit evidence, and companion diagnostics were not run in this phase. They are explicit future or external validation lanes.
