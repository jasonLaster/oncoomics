# QC module 1: counting audit (BAM recount, exonic vs intronic, multimapping, annotation)

Step 19 QC · 2026-10-05 · research only.
- **Write-up:** module 1 returned its report as text because the subagent file policy blocked the write; the
  coordinator saved it here.
- **Data:** every number comes from files in this folder.
- **Coverage:** 54 genes (the candidate list plus NAALADL2, PLCH1, FMNL2, CADM1, FGFR2, IGF1R, ERBB3), both libraries.

## 1. Counts are verified
- **Matrix match:** xf-counted UMIs equal the Cell Ranger matrix exactly, per barcode, for 51/53 recounted genes in
  both libraries. ELF5 matches at 99.94%.
- **Independent recount:** deduplicating (CB, UB) gives 100.2-100.8% of the matrix for every gene, with r ≥ 0.994.
- **Index files:** the L2 .bai indexes all 55 queried regions correctly.

## 2. CARD18 is an annotation artifact
- **Where the UMIs fall:** the GENCODE v23 2 kb CARD18 span holds 1.1% of its matrix UMIs (413 / 395 out of 37,004 /
  34,593). The rest lie in a ~390 kb 5' extension of the GRCh38-2024-A CARD18 model (chr11:105.14-105.53 Mb).
- **Not CARD18 mRNA:** those UMIs are 99.7% intronic and spread across the locus. Exonic CARD18 is about 1 CPM.
- **What the signal is:** transcription of the locus is tumor-enriched (intronic log2FC 3.26 / 3.34), but it is not
  CARD18 mRNA. **Remove CARD18 as an outlier.**

## 3. Long genes are pre-mRNA

| Gene | Intronic share in tumor nuclei | Note |
|---|---|---|
| ERBB4 | 98.9% | 1,975 intronic vs 21 exonic CPM; exonic detection 11.5% vs 95.7% for any UMI |
| ESRRG, NAALADL2, FMNL2, MECOM, LDLRAD3 | 95-98% | |

## 4. Ambient: intronic-only tumor enrichment
Intronic counts carry far less ambient RNA, so this test separates real tumor transcription from background.
- **Against all non-malignant nuclei:** every testable enriched gene passes (lower CI bound > 1 log2 in both
  libraries).
- **Against strict normal epithelium:**

| Result | Genes |
|---|---|
| Fail | ERBB4 (log2FC 0.27 / 0.22; CI crosses 0) |
| Weak | FGFR2 (0.40 / 0.46) |
| Partial | VTCN1, PRLR, ENPP3, SLC6A14, CD44, CTTN, EWSR1, SPECC1L, HORMAD1, BRCA1, ERBB3 |
| Untestable | TACSTD2 (intronless); HLA-A, TAP1, CD274, KRT5, COL1A1, GAPDH, ACTB, CDKN1A (fewer than 200 intronic UMIs); MALAT1 (not recounted, ~3.4 GB) |

- **Intronic counts are not ambient-free.** Their ambient floor (T/NK ÷ malignant intronic CPM) is 0.09-0.30, about
  2-7% after rho scaling.
- **Exonic fold changes are deflated** because tumor mRNA sits in the reference nuclei. VTCN1, SLC6A14, LDLRAD3 and
  CADM1 show exonic log2FC ≈ 0.

## 5. Multimapping
- No gene loses more than 20% of reads to MAPQ < 255.
- ENPP3 loses 11.7%, because the OR2A paralog cluster lies in an ENPP3 intron. FOLH1 loses 4.5% and SLFN11 4.7%.

## 6. Surprise: tumor nuclei transcribe κ-casein (CSN3)

| | Tumor nuclei | Non-tumor nuclei |
|---|---|---|
| Intronic CPM | 636-661 | 180-206 |
| Intronic detection | 82-83% | 26-30% |
| Exonic CPM | ~840 | ~1,930 (T/NK ~2,900) |

- **Pre-mRNA:** intronic CSN3 is ~3.3x higher in tumor nuclei, in both libraries.
- **Mature mRNA:** exonic counts are higher outside the tumor nuclei because mature mRNA is exported and dominates the
  ambient pool.
- **Correction:** this revises the step 18 statement that casein is "pure background". Tumor cells transcribe κ-casein,
  and are the likely source of the casein-rich ambient RNA.
- β-casein (CSN2) and α-lactalbumin (LALBA) are still absent.

## 7. Detection ceiling
- Detection follows a Poisson model on mean UMI.
- log10 intron length correlates with detection: Spearman 0.42 overall, -0.24 at matched expression.
- The p99 detection ceiling rises from ~0.6 for genes with <30 kb of intron to 0.98 for >300 kb.
- Detection agrees between libraries (L1 vs L2 Spearman 0.999).

## 8. Caveats
- The normal-epithelium group has 594 / 1,500 nuclei and is labeled inconsistently between the libraries (see module 2).
- KRTAP5-10 was not in the candidate list, so it was not checked.

## Files
- `per_gene.csv`: 54 genes, every metric and verdict.
- `exonic_only_by_group.csv`.
- `figures/intronic_vs_exonic_enrichment.png`, `figures/detection_ceiling.png`.
- `tables/`: reconcile*, bam_read_tallies*, lfc_by_lib*, annotation_v23*, ensembl_spans, detection_ceiling_*, transfer_*,
  gene_table*.
- `scripts/` (run order in README).
- Per-barcode counts and the subset BAMs (860 MB) stay in scratch (`scratchpad/m1`).
