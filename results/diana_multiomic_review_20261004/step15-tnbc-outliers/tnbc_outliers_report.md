# Bottom-up: genes Diana's tumor expresses above other TNBC tumors (2026-10-04)

> **Update (step 19 QC, 2026-10-05).** A six-module quality control changed several single-nucleus claims (see
> [QC report](../step20-qc/QC_REPORT.md)):
> - **CARD18** is withdrawn: a gene-model artifact in the 2024 reference.
> - **VTCN1/B7-H4** is not an outlier vs other TNBC once intronic counts are removed (~0.7x on mature mRNA).
> - **ERBB4** is 99% unspliced RNA; mature mRNA is ~30x other TNBC, and HER4 protein was not detected.
> - The earlier "same as her normal luminal cells" statements (PRLR, ERBB4, B7-H4) are withdrawn: that comparison group
>   was mostly tumor.
> - The genes that pass every check (Tier A) are FOLH1/PSMA, ENPP3, SLC28A3, SLC6A14, HORMAD1, POLQ, KIF18A, SHANK2,
>   SPECC1L, LDLRAD3, EHF, ESRRG and MECOM. The "outlier vs other TNBC" rule has an estimated FDR of ~0.5 at 2x, so rank
>   by fold.

Research prioritization for discussion with the oncology team. It is not a treatment recommendation. RNA is not
protein: every candidate needs IHC or another protein assay.

## Approach (and why the first pass was discarded)

1. **Bulk RNA vs TCGA TNBC (n=180), genome-wide** (`01_outliers.py`). Discarded as a standalone result. Diana's bulk
   RNA is a capture library (Personalis ACE4) and TCGA is poly-A. The top "outliers" were zinc-finger and ANKRD36
   paralogs, very long genes and cancer-panel genes, many at the 100th percentile. That is a technical signature.
2. **Bias-corrected bulk** (`02_bias_corrected.py`). A model of the deviation from gene structure only (span, exonic
   length, exon count, intron fraction, ZNF flag, panel proxy, expression; no chromosome, so copy-number biology is
   kept) explained 26% of it out-of-fold. The residual list was better but still panel/paralog-contaminated.
3. **Tumor cells vs tumor cells** (`03_tumor_cells_vs_public_tnbc.py`).
   - Diana's malignant nuclei (KH022, two libraries) compared with tumor cells of 8 public TNBC (GSE161529; 4
     sporadic, 4 BRCA1).
   - A per-gene nuclei-vs-whole-cell correction was learned from T/NK, myeloid and fibroblast compartments in both
     datasets: out-of-fold R2 0.60 on 8,840 genes.
   - A gene counts if Diana exceeds at least 7 of 8 tumors by more than 2-fold, is tumor-enriched within her own
     sample, and is not ambient.
4. **Concordance:** genes passing both 2 and 3, which have different technical biases (capture vs nuclei). This
   gives 91 genes (`concordant_outliers.csv`), then annotation with tumor copy number and HPA protein class.

Caveats:
- The public tumor cells include some normal epithelium.
- Very long epithelial-only genes get extrapolated corrections.
- Paralog families (ZNF, ANKRD36, NBPF) remain suspect in both comparisons.
- KH022 and the bulk RNA are different specimens.

## Findings

### 1. Over-expression explained by Diana's DNA amplifications (most robust)
- **chr22q12 amplicon (8-10 copies):** EWSR1, SPECC1L, DEPDC5, PRR14L, XNDC1N, RNF121, all above 8/8 public tumors
  and in the bulk top percentiles.
- **11q13 amplicon (~9 copies):** SHANK2 and LTO1. Note that **CCND1 itself is not over-expressed** in tumor cells
  (exceeds 1/8).
- **CD44 amplicon (chr11p13, ~12 copies):** CD44 is above 7/8 public tumors (median ~5.9x), bulk 98th percentile.
  It is the **only established surface target that is concordant on every axis**: amplified, tumor-enriched, high
  vs other TNBC.

### 2. Potentially druggable genes high relative to other TNBC

| Gene | Tumor cells vs 8 TNBC (median fold) | Bulk vs TCGA TNBC | DNA | Drug context (all need protein confirmation) |
|---|---|---|---|---|
| **CD44** | ~5.9x, 7/8 exceeded | 98th pct | amplified ~12 copies | CD44/CD44v6 antibodies/ADCs (earlier ADC halted for skin toxicity) |
| **SLC28A3 (CNT3)** | ~21x, 8/8 | 98th pct | 2:0 | Nucleoside transporter; uptake of nucleoside-analog chemotherapy (hypothesis; hENT1 protein 174 amol/ug measured) |
| **ATR** | ~5x, 8/8 | 100th pct (panel gene) | 3:1 | ATR inhibitors (investigational); fits TP53 loss + HRD replication-stress context |
| **SLC6A14** | ~34x, 8/8 | 100th pct | — | Amino-acid transporter; inhibitors preclinical |
| **HORMAD1** | ~27x, 8/8 | 96th pct | — | Cancer-testis antigen linked to HR-deficient TNBC; a candidate immunotherapy/vaccine antigen (research) |
| **ERBB4** | ~77x, 8/8 | off-scale (TCGA TNBC median ~0) | 2:1 | No approved HER4-directed drug |
| **ENPP3** | ~50x, 8/8 | off-scale | 3:0 | ENPP3 ADC (early, renal) |
| **FOLH1 (PSMA)** | ~21x, 8/8 | 89th pct (panel) | 2:1 | PSMA radioligand/ADC (approved in prostate) |
| **POLQ** | ~10x, 8/8 | low after panel correction (discordant) | — | POLQ inhibitors (investigational, HRD) |
| **FGFR2** | ~7x, 6/8 | 98th pct | 3:0 | FGFR inhibitors; FGFR protein not detected |
| **VTCN1 (B7-H4)** | ~2.9x, 8/8 | 22nd pct (panel; discordant) | 2:1 | B7-H4 ADCs (investigational) |

### 3. Typical for TNBC (not outliers)
TACSTD2/TROP-2 (exceeds 2/8; protein near the assay median), TOP1, NECTIN4, EGFR, CD276 (below), CCND1 and SLFN11.
The TROP-2 rationale rests on presence, not over-expression.

### 4. Biology signal
- Diana's tumor cells express **very little basal keratin** compared with other TNBC: KRT5 ~30x lower, KRT17 ~85x
  lower than the public median.
- They express **high ERBB4, PRLR, ESRRG and MECOM**.
- With PAM50 basal-like but an indeterminate Lehmann subtype, this suggests a less keratin-basal, more
  luminal-progenitor-like TNBC state, a pattern described in BRCA1-associated tumors. This is a hypothesis to confirm
  with pathology (CK5/6, CK14).

## Files
- `all_genes_vs_tcga_tnbc.csv.gz`, `all_genes_bias_corrected.csv.gz` (bulk)
- `tumor_cells_vs_public_tnbc.csv.gz` (per-gene excess vs each public tumor)
- `candidates_tumor_cells_vs_public_tnbc.csv`, `concordant_outliers.csv`
- `scripts/01-03`
