# Step 19 QC, module 4: statistics and cross-dataset calibration of the "outlier vs public TNBC" claims

Research QC, 2026-10-05. n = 1 patient. L1 and L2 are technical replicates from one suspension, and nuclei are not independent biological replicates. So every interval below covers measurement and model uncertainty only. None of them covers patient-level or biological variation. Reproduction steps are in `README.md`, and every number comes from `scripts/`.

## 0. Bottom line

1. **The 2x / 7-of-8 outlier call is not well calibrated.**
   - **Reference null.** I applied the same rule to Diana's reference compartments against the public reference compartments, using the bias model trained without that compartment.
     - At the list stage it flags **23-32%** of eligible genes. Diana's tumor nuclei give 49-53%.
     - That gives an **empirical FDR of about 0.5 for the step15 list**: 0.46 (fibroblast null), 0.55 (myeloid), 0.61 (T/NK, which is inflated by epithelial ambient RNA).
   - **The FDR falls with effect size.** It is about 0.3 for genes above 8x in 7 of 8 tumors, and about 0.15-0.2 above 16-32x (myeloid and fibroblast nulls).
   - **The bias term is essential.** Without it, 57% of eligible genes would be called.
2. **The bias model is the dominant source of uncertainty; sampling noise is not.**
   - Out-of-fold residual SD is **1.11 log2** (about 2.2-fold). That is the same size as the 2x threshold.
   - **Leave-one-compartment-out:** R2 0.54-0.63, residual SD 1.08-1.15, compartment offsets -0.32 to +0.24 log2.
   - **The error is shared.** One bias error applies to all 8 comparisons of a gene, so the 7/8 rule gives no protection against it.
   - Bootstrap 95% CIs on tumor CPM are about ±1-3%, and the libraries agree at Spearman 0.993-0.999.
3. **Gene length.**
   - **The list is not enriched for long genes on average.** Against a background matched on Diana's expression:
     - Mean span is unchanged for genome-wide calls (geometric fold 1.00) and lower for the final list (0.79).
     - Intron fraction is the same as background.
   - **There is a tail problem.**
     - Genes over 500 kb are 1.8x over-represented among genome-wide calls: 5.3% observed vs 2.9% expected.
     - The correction for long genes is poorly constrained. Residual SD is 1.7 log2 at 500 kb-1 Mb and 2.3 log2 above 1 Mb. Only 100 training genes exceed 500 kb.
     - The tree model levels off above 1 Mb, 0.7 log2 below a linear extrapolation of the training trend.
     - **Housekeeping genes, which should show zero excess, rise with span.** Median corrected excess goes from -0.15 (under 10 kb) to +0.5 (100-500 kb) to +1.46 (500 kb-1 Mb, n=10). The share called rises from 11% to 50%.
     - So the correction under-corrects long genes in tumor nuclei.
   - **Exon-only recount: not done.** Module 1's exon-only counts did not exist when I ran this. `06_exon_only_recall.py` is ready and will run on them.
4. **Dosage check passes.**
   - Tumor-vs-non-malignant log2FC tracks WGS copy number.
     - Gene level: slope 0.37 (95% CI 0.33-0.40) log2 per log2(CN/ploidy).
     - Segment level: Spearman 0.70 / 0.71 in L1 / L2. Median log2FC is -0.44 at CN 1 and +1.19 at CN 9.
   - Corrected excess vs public also tracks CN (slope 0.53).
   - So tumor labels and quantification behave as expected.
5. **Candidates.** Of the 23 candidates called in my reimplementation of the list:
   - **11 are stable to every technical perturbation:** FOLH1, ENPP3, SLC28A3, SLC6A14, HORMAD1, POLQ, KIF18A, SPECC1L, LDLRAD3, EHF, CARD18. Their FDR proxy is still 0.16-0.39.
   - **3 rest on an extrapolated long-gene correction:** SHANK2, ESRRG, MECOM.
   - **9 are fragile:** CD44, VTCN1, ERBB4, ATR, CTTN, EWSR1, ELF5, SOX6, KYNU.
     - **ATR, ELF5, CTTN and EWSR1** lose the call when their own bias, measured directly in the reference compartments, replaces the model prediction (3/8, 3/8, 1/8 and 4/8 tumors exceeded).
     - **ERBB4** (1.16 Mb) has P(call | bias uncertainty) of 0.79 and a correction SD of 2.3 log2.
   - **PRLR is not an outlier** (5/8).
   - All "typical" or "low" targets and the controls behave as stated.

## 1. Bias-model validation

### 1.0 Reproduction

My reimplementation (`common.py`) gives:
- bias model: 8,840 training genes, out-of-fold R2 **0.605** (step15: 0.60);
- bias_hat correlation with the step15 file: r = 0.997;
- tested genes: 7,069; list: **880 genes, 844 shared with step15's 867**.

The small differences come from GBM fold assignment and gene-order effects. All tests below use the 880-gene list (`tables/genes_master.csv.gz`, column `list867`).

### 1a. Leave-one-compartment-out (`tables/1a_loco.csv`, `figures/fig1a_loco.png`)

| held out | R2 (model) | residual SD | mean residual | uncorrected SD | R2 using the other two compartments' observed bias directly |
|---|---:|---:|---:|---:|---:|
| T/NK | 0.54 | 1.08 | +0.24 | 1.63 | 0.77 |
| myeloid | 0.63 | 1.13 | +0.15 | 1.89 | 0.87 |
| fibroblast | 0.56 | 1.15 | -0.32 | 1.80 | 0.79 |

**What the model does.**
- The structural model transfers across cell types. It removes about 40% of the variance and cuts the SD roughly 1.5x.
- A residual SD of about 1.1 log2 is 2.2-fold, the same size as the outlier threshold.
- Each compartment has its own offset of about ±0.3 log2. Tumor nuclei, a fourth cell type, would carry an unknown offset of the same order.

**Direct observed bias transfers better than the model** (R2 0.77-0.87).
- So for genes expressed in the reference compartments, the gene's own measured nuclei/cell ratio is the better correction. step15 used the model prediction for every gene.
- Using measured bias where it exists (392 of the 880 list genes) **keeps 594/880** list genes and calls 638 (`tables/1a_direct_bias_list_size.csv`).
- Among the candidates, ATR, CTTN, EWSR1 and ELF5 drop out (`tables/1a_candidates_direct_bias.csv`):

| gene | measured bias | predicted bias |
|---|---:|---:|
| ATR | 4.37 | 2.46 |
| ELF5 | 2.81 | 0.13 |
| CTTN | 2.22 | 0.52 |
| EWSR1 | 1.16 | -0.12 |

### 1b. Housekeeping negative controls (`tables/1b_housekeeping.csv`, `figures/fig1b_housekeeping.png`)

I used the Eisenberg & Levanon 2013 list (3,804 genes); 2,311 of them are tested in tumor.

| set | n | median corrected excess (log2) | IQR | share called ≥7/8 | share in final list |
|---|---:|---:|---|---:|---:|
| HK tested | 2,311 | 0.22 | -0.48 to 0.92 | 12.9% | 5.9% |
| all tested | 7,069 | 0.56 | -0.24 to 1.45 | 22.3% | 12.4% |
| HK in bias training set | 2,177 | 0.16 | -0.54 to 0.83 | 10.7% | 5.1% |
| HK outside training set | 134 | **1.60** | 0.79 to 2.18 | **50.0%** | 19.4% |
| HK in T/NK (leave-one-out bias) | 2,756 | 0.52 | -0.03 to 1.15 | 19.4% | n/a |
| HK in myeloid (leave-one-out bias) | 2,534 | 0.52 | -0.11 to 1.14 | 17.6% | n/a |
| HK in fibroblast (leave-one-out bias) | 2,484 | 0.01 | -0.55 to 0.59 | 7.2% | n/a |

- **136 housekeeping genes are in the final list.** They include SPECC1L, which is genuinely amplified, and INVS, KAT2B, TRAF6, ZHX2, ETV6 and others (`tables/1b_housekeeping_in_outlier_list.csv`).

**Housekeeping excess by gene span** (`tables/1L_housekeeping_excess_by_span.csv`):

| span | n | median excess | share called |
|---|---:|---:|---:|
| < 10 kb | 228 | -0.15 | 11% |
| 10-30 kb | 642 | 0.08 | 10% |
| 30-100 kb | 1,025 | 0.25 | 12% |
| 100-200 kb | 309 | 0.53 | 18% |
| 200-500 kb | 97 | 0.49 | 22% |
| 500 kb-1 Mb | 10 | 1.46 | 50% |

**Meaning.** The correction leaves a positive offset that grows with gene length. For a gene that is not truly different, the false call rate is 10-20% across most of the genome and about 50% for genes over 500 kb.

### 1c. Calibration of the outlier call (`tables/1c_*.csv`, `figures/fig1c_fdr_by_fold.png`)

**Reference null setup.**
- Diana's T/NK, myeloid and fibroblast nuclei were compared with the same compartment in each public tumor that has at least 50 such cells: 6 tumors for T/NK, 7 for myeloid, 7 for fibroblast.
- The correction is the bias model trained without that compartment.
- The rule is ≥(n-1)/n exceeded by more than 2x, with Diana CPM ≥ 20 and detection ≥ 10%.
- At the list stage the gene must also be enriched (log2FC ≥ 0.5) against the other non-malignant nuclei.
- The tumor rate is averaged over all n-subsets of the 8 public tumors, so the rules match.

**Call rates by stage.**

| stage | tumor rate | T/NK null | myeloid null | fibroblast null | FDR proxy (null / tumor) |
|---|---:|---:|---:|---:|---|
| expression filters only | 22-25% | 29% | 29% | 14% | 0.61 to >1 |
| + enrichment (list stage) | 49-53% | 32% | 28% | 23% | **0.61 / 0.55 / 0.46** |
| list stage, no bias term | 49-53% | 50% | 68% | 72% | ≥0.94 |

**FDR proxy by fold threshold, list stage** (`tables/1c_fdr_by_fold_threshold.csv`):

| fold | list size (≥7/8) | myeloid | fibroblast | T/NK |
|---|---:|---:|---:|---:|
| 1.5x | 1,113 | 0.61 | 0.52 | 0.64 |
| 2x | 880 | 0.55 | 0.46 | 0.61 |
| 3x | 532 | 0.42 | 0.45 | 0.62 |
| 4x | 353 | 0.38 | 0.40 | 0.63 |
| 8x | 143 | 0.27 | 0.32 | 0.86 |
| 16x | 48 | 0.17 | 0.37 | 1.0 |
| 32x | 15 | 0.18 | 0.14 | 1.0 |

**The T/NK null is ambient-inflated.**
- Its false positives are led by epithelial secretory soup genes: CSN3, SCGB3A1, SLPI, WFDC2, LTF and AZGP1.
- T/NK nuclei carry rho 0.6 ambient RNA (step 6), and the tumor list's ambient filter has no counterpart in this null.
- The myeloid and fibroblast nulls are the fairer ones. Their false positives are long genes: median span 108-124 kb, against 82 kb for tested tumor genes (`tables/1c_reference_false_positive_genes.csv`).

**Bias-uncertainty margin** (`tables/1c_fdr_with_uncertainty_margin.csv`).
- Each comparison must clear 2x after subtracting 1.645 SD of the span-specific bias error.
- The list shrinks to 157 genes.
- The FDR proxy is 0.30 (myeloid), 0.31 (fibroblast) and 0.85 (T/NK).

**Within-platform null: each public tumor against the other 7, with no bias term** (`tables/1c_public_tumor_as_query_null.csv`).

| query | rate called (≥6/7, 2x, CPM ≥ 20, detection ≥ 10%) | list-stage rate (also enriched vs own non-tumor cells) |
|---|---|---|
| each public tumor | 1.7-11.2%, median 6.3% | 3.9-19.4%, median 13% (7 tumors) |
| Diana, same rule (7-subsets, with bias term) | 23.6% | 50.8% |

- **Rough decomposition.** If Diana were an ordinary tumor on the same platform, about 13% of eligible genes would be outliers. The cross-platform null adds about 23-28%. Together that explains roughly 36-41 of Diana's 51 points.
- **Alternative reading.** Diana could also be a genuinely unusual tumor (BRCA1-null, amplified 11q13 / 22q12 / 11p13).

**Conclusion.** Treat the 2x list as roughly half technical. Rank by effect size and robustness (section 5), not by list membership.

**What would falsify this.**
- Exon-only Diana counts reproducing the same calls without a bias term would show that the length/intron pathway is not the explanation.
- A same-platform snRNA TNBC cohort (GEM-X with introns) showing Diana's outliers at ≥2x would remove the need for the bias model.

### 1L. Gene-length / intron confound (requested by the coordinator)

**(1) Enrichment against an expression-matched background** (`tables/1L_length_enrichment.csv`, `tables/1L_logistic_call_vs_structure.csv`, `figures/fig1L_span_decile_enrichment.png`).

| outlier set | matched on | geometric fold in span | intron fraction, observed vs expected | share > 500 kb, observed vs expected |
|---|---|---:|---|---|
| genome-wide calls (1,575) | Diana CPM | 1.00 | 0.90 vs 0.89 | **5.3% vs 2.9%** |
| genome-wide calls | public CPM | 0.74 | 0.90 vs 0.92 | 5.3% vs 6.1% |
| final list (880) | Diana CPM | 0.79 | 0.92 vs 0.93 | 6.8% vs 6.3% |
| final list | public CPM | 0.83 | 0.92 vs 0.93 | 6.8% vs 8.5% |

- **Logistic model** of the call among tested genes, adjusting for Diana and public expression (with quadratic terms):
  - log10 span: OR 0.019 per SD, so the model over-penalises long genes on average.
  - Intron fraction: OR 2.4 per SD (95% CI 1.96-3.02).
- **Meaning.** Genes are not called because they are long; the correction removes the mean length trend. The intron-rich and over-500-kb tail is mildly over-represented, and that is where the correction is least reliable.

**(2) Is the correction adequate in the long tail?** (`tables/1L_residual_vs_span.csv`, `tables/1L_gbm_vs_linear_extrapolation.csv`, `figures/fig1L_length.png`, `figures/fig1L_hk_length_trend.png`)

- **Training coverage.** The longest training gene is 2.30 Mb and the 99th percentile is 522 kb. Only 100 training genes exceed 500 kb and 15 exceed 1 Mb. 55 list genes lie beyond the 99th percentile; none lie beyond the maximum.
- **Out-of-fold residual by span:**

| span | mean residual | SD |
|---|---:|---:|
| up to 500 kb | about 0 | 1.0-1.3 |
| 500 kb-1 Mb | about 0 | **1.72** |
| > 1 Mb | about 0 | **2.30** |

- **Leave-one-out residual trends differ in sign.**
  - Myeloid rises with span: +0.46 at 100-200 kb, +0.69 at 0.5-1 Mb, +1.65 above 1 Mb.
  - Fibroblast falls: -0.4 to -0.6.
  - So the length dependence of the nuclei-vs-cell bias is cell-type specific, and tumor nuclei are an extrapolation.
- **Tree-model extrapolation.**
  - The linear trend of observed bias on log span, in training genes of 100 kb or more, is 2.36 log2 per decade.
  - For list genes over 1 Mb, the GBM correction is 0.70 log2 below that linear trend.
- **Housekeeping test (section 1b).** Excess rises with span in tumor. Spearman of span vs excess is 0.15 among housekeeping genes and 0.19 among all tested genes.

**Sensitivity analyses on the 880-gene list** (`tables/1L_recalibrated_list_sizes.csv`, `tables/outlier_list_with_pcall.csv`):

| variant | genes kept | note |
|---|---:|---|
| housekeeping-anchored LOWESS on span added to the correction | 641 (73%) | housekeeping genes in the list drop from 136 to 103 |
| bias-uncertainty margin call | 157 (18%) | |
| both combined | 121 | |
| P(call given bias uncertainty) ≥ 0.8 | 368 | genome-wide |
| P(call given bias uncertainty) ≥ 0.95 | 160 | genome-wide |

**Long-gene watchlist** (`tables/1L_long_gene_watchlist.csv`, `tables/1L_watchlist_linear_bias.csv`). The "n exceeded" column gives four variants in order: base / housekeeping recalibration / margin call / linear-extrapolated bias.

| gene | span | in training? (measured bias) | Diana CPM | public median CPM | bias_hat (SD) | n exceeded | P(call) | log2FC vs Diana normal epithelium |
|---|---:|---|---:|---:|---|---|---:|---:|
| NAALADL2 | 1.37 Mb | yes (6.26) | 5,173 | 24.6 | 4.19 (2.30) | 8 / 8 / 3 / 8 | 0.82 | 1.62 |
| ERBB4 | 1.16 Mb | no | 1,992 | 0.73 | 3.84 (2.30) | 8 / 8 / 5 / 8 | 0.73-0.79 | **0.21** |
| SOX6 | 773 kb | no | 2,199 | 3.6 | 4.13 (1.72) | 8 / 7 / 5 / 8 | 0.72 | 1.74 |
| ESRRG | 635 kb | no | 3,739 | 2.6 | 4.23 (1.72) | 8 / 8 / 7 / 8 | 0.97 | 1.69 |
| MECOM | 580 kb | no | 1,091 | 0.32 | 3.91 (1.72) | 8 / 8 / 6 / 8 | 0.92 | 1.82 |
| PLCH1 | 369 kb | no | 480 | 5.6 | 3.78 (1.29) | 7 / 6 / 2 / 8 | 0.68 | 1.54 |
| CADM1 | 336 kb | yes (2.94) | 995 | 31.9 | 2.88 (1.29) | 7 / 5 / 1 / 7 | 0.52 | 1.12 |
| FMNL2 | 315 kb | yes (4.55) | 1,901 | 12.7 | 3.63 (1.29) | 8 / 8 / 6 / 8 | 0.90 | 1.50 |

- **The raw differences are enormous.** For ERBB4, ESRRG and MECOM, Diana is at 1,000-3,700 CPM while public tumors are at 0.3-3.6 CPM.
- **These survive every plausible length correction against public TNBC.** Even a 16-22x nuclear-intron correction leaves them more than 30x above the public tumors.
- **They do not survive as tumor-selective claims.** ERBB4 is not higher than Diana's own normal epithelium (log2FC 0.21; step 18 found the same), and HER4 protein is below the limit of quantification (module 5).
- **Interpretation for ERBB4.**
  - It fits a long, intron-rich gene whose nuclear pre-mRNA signal greatly overstates mature mRNA and protein. It also fits a luminal-lineage transcript.
  - The nuclei-vs-cell correction cannot tell these apart; an exon-only count can.
  - Until module 1's exon-only numbers exist, **"ERBB4 high vs TNBC" should be reported as nuclear RNA only, with an unresolved length/intron caveat.**

**(3) Exon-only recall.**
- `scripts/06_exon_only_recall.py` reads module 1's `per_barcode/<lib>.<gene>.tsv.gz` (column `ind_exonic`).
- It normalises by total UMIs × the library exonic fraction: 0.431 (L1) and 0.438 (L2), from Cell Ranger `metrics_summary`.
- It compares against public tumors with **no** bias term.
- **Status at run time:** `m1_counting/` contained only scripts, so the recall was skipped. Re-run `./run.sh 06_exon_only_recall.py` from `scripts/` once module 1 finishes.

## 2. Dosage calibration (`tables/2_*.csv`, `figures/fig2_dosage.png`)

Genes were mapped to step5 segments by Ensembl ID (GENCODE v23 GTF). The regression is on log2(CN / 2.8).

**Slopes** (genes ≥10 CPM in both groups, n = 9,335; 95% bootstrap CIs):

| response | gene-level slope (95% CI) | gene-level Spearman | segment-level slope (95% CI) | segment-level Spearman (n segments) |
|---|---|---:|---|---|
| log2FC tumor vs non-malignant, L1 | 0.37 (0.34-0.40) | 0.29 | 0.40 (0.32-0.48) | 0.70 (166) |
| log2FC, L2 | 0.36 (0.33-0.40) | 0.29 | 0.39 (0.33-0.47) | 0.71 (166) |
| corrected excess vs public | 0.53 (0.48-0.58) | 0.23 | 0.50 (0.45-0.68) | 0.66 (161) |

**Median by copy number** (`tables/2_dosage_by_CN.csv`):

| CN | n genes | median log2FC L1 | median log2FC L2 | median excess vs public |
|---:|---:|---:|---:|---:|
| 1 | 566 | -0.44 | -0.43 | -0.25 |
| 2 | 3,355 | -0.28 | -0.27 | 0.11 |
| 3 | 2,986 | 0.01 | 0.00 | 0.36 |
| 4 | 1,477 | 0.18 | 0.18 | 0.78 |
| 5 | 837 | 0.38 | 0.39 | 0.84 |
| 6 | 26 | 0.54 | 0.43 | 1.29 |
| 7 | 11 | 0.83 | 0.76 | 1.86 |
| 8 | 34 | 1.02 | 1.01 | 1.56 |
| 9 | 18 | 1.19 | 1.18 | 2.19 |
| 10 | 21 | 1.13 | 1.04 | 1.97 |
| 12 | 4 | 1.99 | 1.93 | 3.46 |

- **Meaning.** Expression rises with CN at a slope (about 0.4) typical of partial dosage compensation in scRNA, and the replicates agree.
- **This is an orthogonal check that the malignant label and the quantification are sound.** If tumor labels were mixed with normal nuclei, the slope would shrink toward 0.
- **The excess vs public also follows CN.** That is expected, because the public tumors do not share Diana's CNAs. It means part of every "outlier" signal in gained regions is dosage, not regulation.

**Where the candidates sit** (`tables/2_candidates_dosage.csv`). The residual is log2FC minus the median of the gene's segment.

| gene group | CN | residual vs segment | reading |
|---|---|---|---|
| SHANK2 / LDLRAD3 / SPECC1L / CTTN / EWSR1 | 9 / 12 / 8 / 9 / 8 | +1.9 / +1.2 / +0.4 / -0.1 / +0.1 | amplicon genes match or exceed dosage |
| CD44 | 12 | -0.2 | over-expression fully explained by dosage |
| CCND1 | 9 | -1.3 | escapes dosage, as step15 said |
| ENPP3, FOLH1, SLC28A3, VTCN1, PRLR, ERBB4, ESRRG, CARD18 | 2-5 | +2.2 to +3.1 | regulatory or lineage outliers, not dosage |
| B2M | 1 | -0.85 | |
| TAP1, PSMB9, NLRC5 | 5 / 5 / 2 | -1.7 to -2.8 | antigen-processing genes are low beyond dosage |

## 3. Uncertainty for candidates (`tables/3_candidates_bootstrap.csv`, `tables/candidate_summary.csv`, `figures/fig3_candidate_forest.png`)

**Bootstrap design (B = 1,000).**
- Nuclei are resampled within each library, separately for malignant and non-malignant nuclei.
- Public cells are resampled within each tumor.
- The bias term is drawn from N(bias_hat, SD of its span bin). The SD is 1.0-1.3 log2 below 500 kb, 1.72 for 500 kb-1 Mb and 2.30 above 1 Mb. One draw is shared across the 8 comparisons.

**What drives the interval widths.**
- Sampling-only CIs are narrow: ±1-3% on CPM and ±0.05-0.15 on log2FC.
- The excess CI with bias error is about ±2 log2, and ±3.5-4.8 for genes over 500 kb.
- **P(call)** is the share of replicates still meeting ≥7/8 at 2x once bias error is included.

**L1 vs L2 concordance** (`tables/3b_L1_vs_L2_concordance.csv`, `figures/fig3_L1_vs_L2.png`):

| quantity | n genes | Spearman | median abs diff |
|---|---:|---:|---:|
| tumor pseudobulk CPM, CPM > 0 | 28,164 | 0.993 | 0.044 log2 |
| tumor pseudobulk CPM, ≥10 CPM | 10,170 | 0.998 | 0.040 log2 |
| log2FC tumor vs non-malignant | 12,187 | 0.995 | 0.062 |
| median corrected excess | 7,069 | 0.999 | 0.034 |

- Per-library outlier lists: 883 (L1) and 878 (L2), 861 shared, Jaccard **0.957**.
- Because these are technical replicates of one suspension, the agreement bounds only counting noise. It says nothing about the bias model or biology.

## 4. Robustness (`tables/4_*.csv`)

**Downsampling.**
- Diana's malignant nuclei have a median of 5,468 UMIs. Public tumor cells have 6,784 pooled, or 9,895 as the median of per-tumor medians.
- **Diana is not deeper than the public data,** so downsampling to the public median changes little.
- Every called candidate survives every downsampling variant below.

| variant | genes called | share of base list retained |
|---|---:|---:|
| downsample to pooled public median | 856 | 96% |
| downsample to per-tumor median | 880 | 99% |
| 2,000-UMI stress test | 673 | 76% |
| 2,000-UMI, detection floor 5% | 809 | 91% |
| L1 only | 883 | 99% |
| L2 only | 878 | 99% |

At 2,000 UMIs most losses are genes falling below 10% detection.

**Threshold grid: share of the base list retained (min CPM 20)**

| rule | 1.5x | 2x | 3x |
|---|---:|---:|---:|
| ≥6/8 | 100% (1,270) | 100% (1,031) | 74% (674) |
| ≥7/8 | 100% (1,113) | base (880) | 60% (532) |
| ≥8/8 | 89% (862) | 72% (634) | 42% (367) |

- min CPM 10 retains 100%; min CPM 50 retains 82%.

## 5. Per-candidate table (`tables/candidate_summary.csv` has all columns)

**Column definitions.**
- **Excess:** median corrected log2 excess over the 8 public tumors, with a 95% CI that includes bias-model error.
- **n/8:** number of public tumors exceeded by 2x.
- **Fold cleared:** the fold Diana exceeds in at least 7 of 8 tumors (the second-smallest ratio).
- **FDR proxy:** the mean of the myeloid and fibroblast nulls at that fold.
- **P(call):** with bias uncertainty.
- **Measured bias:** n/8 tumors still exceeded when the gene's own reference-compartment bias is used ("n/a" means the gene is not measured there).
- Sampling-only 95% CIs on tumor CPM are about ±1-3%.

**"Robust" means stable to all of these technical perturbations:**
- P(call) ≥ 0.8;
- housekeeping recalibration;
- 3x threshold;
- single-library calls;
- 2,000-UMI downsampling;
- measured bias;
- span within the training range.

"Robust" does not mean true: even robust genes carry an FDR proxy of 0.16-0.39.

### Targets

| gene | tumor CPM (95% CI) | log2FC vs non-malignant L1 (95% CI) | L2 (95% CI) | excess (95% CI) | n/8 | fold cleared | FDR | P(call) | measured bias | CN |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| CD44 | 999 (989-1009) | 1.13 (1.09-1.18) | 1.13 (1.08-1.17) | 2.38 (0.59-4.34) | 7 | 2.5 | 0.50 | 0.63 | 8 | 12 |
| VTCN1 | 194 (191-197) | 2.22 (2.10-2.35) | 2.38 (2.26-2.51) | 1.52 (-0.51-3.59) | 8 | 2.6 | 0.50 | 0.61 | n/a | 3 |
| FOLH1 | 153 (150-155) | 2.19 (2.08-2.30) | 2.16 (2.05-2.28) | 4.32 (2.45-6.21) | 8 | 14.7 | 0.30 | 1.00 | n/a | 3 |
| ENPP3 | 236 (233-239) | 2.04 (1.94-2.14) | 1.99 (1.89-2.09) | 5.81 (3.50-8.03) | 8 | 34 | 0.16 | 1.00 | n/a | 3 |
| PRLR | 455 (450-460) | 2.26 (2.17-2.35) | 2.25 (2.16-2.35) | 1.54 (-0.85-3.76) | 5 | 1.3 | n/a | 0.29 | 5 | 2 |
| ERBB4 | 1,992 (1,974-2,009) | 2.26 (2.10-2.44) | 2.37 (2.23-2.52) | 6.40 (1.92-11.23) | 8 | 5.5 | 0.39 | 0.79 | n/a | 3 |
| SLC28A3 | 529 (523-535) | 2.45 (2.38-2.52) | 2.34 (2.26-2.41) | 4.50 (2.58-6.65) | 8 | 12.5 | 0.30 | 1.00 | n/a | 2 |
| SLC6A14 | 727 (719-736) | 1.19 (1.14-1.23) | 1.19 (1.13-1.23) | 5.09 (3.03-7.00) | 8 | 9.7 | 0.30 | 0.98 | n/a | 2 |
| HORMAD1 | 164 (161-166) | 1.93 (1.83-2.04) | 1.95 (1.85-2.06) | 4.76 (2.54-6.72) | 8 | 7.0 | 0.39 | 0.96 | n/a | 4 |
| ATR | 293 (290-296) | 0.66 (0.60-0.71) | 0.69 (0.64-0.75) | 2.32 (0.02-4.44) | 8 | 4.0 | 0.39 | 0.79 | **3** | 4 |
| POLQ | 86 (84-89) | 1.97 (1.84-2.12) | 2.03 (1.87-2.19) | 3.35 (0.89-5.55) | 8 | 5.1 | 0.39 | 0.86 | n/a | 3 |
| KIF18A | 93 (90-97) | 1.74 (1.60-1.88) | 1.88 (1.75-2.04) | 2.80 (0.82-4.98) | 7 | 5.4 | 0.39 | 0.89 | n/a | 5 |
| TACSTD2 | 70 (69-72) | -1.17 (-1.24 to -1.10) | -1.19 (-1.25 to -1.12) | -0.10 (-2.47-2.53) | 2 | 0.6 | n/a | 0.10 | 1 | 4 |
| TOP1 | 213 (211-216) | 0.19 (0.14-0.25) | 0.20 (0.15-0.26) | 0.51 (-1.48-2.33) | 2 | 0.9 | n/a | 0.12 | 2 | 3 |
| SLFN11 | 5.3 (4.9-5.7) | -2.07 (-2.25 to -1.90) | -1.99 (-2.17 to -1.80) | 0.74 (-1.45-2.65) | 1 | 0.9 | n/a | 0.12 | 1 | 2 |
| NECTIN4 | 55 (54-57) | 0.71 (0.59-0.83) | 0.74 (0.62-0.85) | 0.21 (-1.70-2.17) | 0 | 0.6 | n/a | 0.03 | 0 | 5 |
| EGFR | 144 (141-146) | -0.64 (-0.72 to -0.57) | -0.59 (-0.67 to -0.52) | 0.87 (-1.75-3.24) | 4 | 0.8 | n/a | 0.14 | 1 | 2 |
| CD276 | 15.5 (14.9-16.1) | -0.49 (-0.64 to -0.34) | -0.41 (-0.56 to -0.26) | -1.13 (-3.10-0.96) | 0 | 0.3 | n/a | 0.00 | 2 | 2 |

**Target verdicts**

| gene | verdict |
|---|---|
| CD44 | **Fragile**: fails 3x and housekeeping recalibration (6/8); fully explained by dosage. |
| VTCN1 | **Fragile**: fails 3x; P(call) 0.61. |
| FOLH1 | Robust. |
| ENPP3 | Robust. |
| PRLR | **Not an outlier** vs TNBC. |
| ERBB4 | **Fragile**: 1.16 Mb, correction SD 2.3, P(call) 0.79; see 1L. |
| SLC28A3 | Robust. |
| SLC6A14 | Robust. |
| HORMAD1 | Robust. |
| ATR | **Fragile**: measured bias 4.37 vs 2.46 predicted, so likely technical. |
| POLQ | Robust; fails only the strict margin call (5/8). |
| KIF18A | Robust; fails only the strict margin call (5/8). |
| TACSTD2 | Typical (as claimed). |
| TOP1 | Typical (as claimed). |
| SLFN11 | Low vs non-malignant; typical vs TNBC. |
| NECTIN4 | Typical (as claimed). |
| EGFR | Typical (as claimed). |
| CD276 | Typical or below (as claimed). |

### Amplicon, lineage and outlier genes

| gene | tumor CPM (95% CI) | log2FC L1 (95% CI) | L2 (95% CI) | excess (95% CI) | n/8 | fold cleared | FDR | P(call) | measured bias | CN |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| SHANK2 | 2,877 (2,859-2,895) | 3.30 (3.22-3.37) | 3.19 (3.12-3.26) | 3.99 (0.57-7.47) | 8 | 8.6 | 0.30 | 0.88 | n/a | 9 |
| CCND1 | 69 (68-71) | 0.06 (-0.03-0.15) | -0.01 (-0.10-0.08) | -0.57 (-2.72-1.51) | 1 | 0.35 | n/a | 0.01 | 0 | 9 |
| CTTN | 415 (412-419) | 1.24 (1.19-1.30) | 1.20 (1.15-1.26) | 1.54 (-0.51-3.68) | 8 | 2.4 | 0.50 | 0.56 | **1** | 9 |
| EWSR1 | 426 (422-430) | 1.10 (1.05-1.14) | 1.06 (1.01-1.11) | 2.25 (0.38-4.29) | 8 | 3.5 | 0.44 | 0.79 | **4** | 8 |
| SPECC1L | 1,029 (1,022-1,036) | 1.90 (1.86-1.95) | 1.86 (1.82-1.91) | 4.36 (2.36-6.72) | 8 | 13.5 | 0.30 | 0.99 | 8 | 8 |
| LDLRAD3 | 1,827 (1,813-1,840) | 2.63 (2.57-2.68) | 2.51 (2.46-2.55) | 4.80 (2.21-7.54) | 8 | 22 | 0.27 | 0.99 | 7 | 12 |
| ELF5 | 469 (464-474) | 2.13 (2.06-2.20) | 2.07 (2.01-2.14) | 2.99 (0.96-5.06) | 8 | 3.8 | 0.44 | 0.80 | **3** | 9 |
| EHF | 1,206 (1,198-1,214) | 1.92 (1.88-1.97) | 1.87 (1.83-1.92) | 4.42 (2.61-6.42) | 8 | 17 | 0.27 | 1.00 | n/a | 9 |
| ESRRG | 3,739 (3,711-3,765) | 3.45 (3.38-3.52) | 3.42 (3.35-3.49) | 5.90 (2.38-9.46) | 8 | 22 | 0.27 | 0.97 | n/a | 5 |
| MECOM | 1,091 (1,081-1,103) | 2.23 (2.12-2.35) | 2.47 (2.38-2.56) | 5.78 (2.56-9.02) | 8 | 10.7 | 0.30 | 0.92 | n/a | 4 |
| SOX6 | 2,199 (2,183-2,217) | 2.82 (2.77-2.88) | 2.81 (2.74-2.87) | 4.78 (1.56-7.85) | 8 | 4.0 | 0.39 | 0.72 | n/a | 5 |
| CARD18 | 219 (215-222) | 3.24 (3.09-3.38) | 3.32 (3.17-3.49) | 9.62 (7.14-12.30) | 8 | 667 | 0.16 | 1.00 | n/a | 4 |
| KYNU | 835 (823-847) | 2.23 (2.15-2.31) | 2.31 (2.23-2.39) | 4.57 (2.16-7.03) | 8 | 3.4 | 0.44 | 0.75 | 8 | 5 |

**Amplicon, lineage and outlier verdicts**

| gene | verdict |
|---|---|
| SHANK2 | Outlier; correction extrapolated (785 kb). |
| CCND1 | Not over-expressed (as claimed). |
| CTTN | **Fragile**: fails measured bias and 3x. |
| EWSR1 | **Fragile**: fails measured bias; level matches dosage. |
| SPECC1L | Robust. |
| LDLRAD3 | Robust. |
| ELF5 | **Fragile**: measured bias 2.81 vs 0.13 predicted. |
| EHF | Robust. |
| ESRRG | Outlier; correction extrapolated (635 kb). |
| MECOM | Outlier; correction extrapolated (580 kb). |
| SOX6 | **Fragile**: 773 kb; P(call) 0.72. |
| CARD18 | Robust; the largest and best-supported outlier. |
| KYNU | **Fragile**: P(call) 0.75; fails the margin call (6/8). |

### Immune genes and controls

| gene | tumor CPM (95% CI) | log2FC L1 / L2 | excess (95% CI) | n/8 | P(call) | measured bias | CN |
|---|---|---|---|---:|---:|---:|---:|
| B2M | 261 (258-264) | -1.94 / -1.91 | 0.00 (-2.45-2.40) | 2 | 0.06 | 2 | 1 |
| HLA-A | 97 (95-99) | -1.80 / -1.76 | -1.26 (-3.55-1.22) | 2 | 0.01 | 2 | 5 |
| TAP1 | 8.3 (7.9-8.8) | -1.48 / -1.57 | -2.47 (-5.02 to -0.04) | 1 | 0 | 2 | 5 |
| PSMB9 | 5.2 (4.8-5.6) | -2.52 / -2.73 | -2.93 (-4.95 to -0.75) | 1 | 0 | 2 | 5 |
| NLRC5 | 10.5 (10.0-11.2) | -2.80 / -2.80 | -1.98 (-3.96-0.13) | 2 | 0 | 2 | 2 |
| CD274 | 1.1 (0.9-1.3) | -1.93 / -1.85 | 0.43 (-1.57-2.43) | 2 | 0.10 | 1 | 3 |
| CSN3 (negative control) | 1,482 (1,470-1,494) | -0.52 / -0.51 | **11.90 (9.45-14.28)** | 8 | 1.00 | 8 | 3 |
| KRT5 (negative control) | 0.7 (0.6-0.8) | -1.75 / -1.70 | -4.97 (-7.43 to -2.48) | 0 | 0 | 0 | 2 |
| PTPRC (negative control) | 21 (20-22) | -4.51 / -4.63 | 0.80 (-1.15-3.11) | 4 | 0.03 | 5 | 4 |
| COL1A1 (negative control) | 13 (13-14) | -3.53 / -3.42 | -0.24 (-2.18-1.90) | 2 | 0.07 | 2 | 2 |
| GAPDH (housekeeping) | 85 (84-87) | -1.20 / -1.22 | -1.85 (-4.34-0.50) | 0 | 0 | 0 | 3 |
| ACTB (housekeeping) | 156 (154-158) | -1.61 / -1.59 | -0.61 (-2.65-1.34) | 1 | 0.03 | 1 | 2 |
| MALAT1 (housekeeping) | 54,335 (53,915-54,782) | -0.34 / -0.33 | n/a (no bias_hat) | 0 | n/a | 2 | 3 |
| BRCA1 (positive control) | 56 (54-58) | 1.13 / 1.20 | 1.06 (-0.95-3.06) | 5 | 0.34 | 5 | 2 |
| TP53 (positive control) | 56 (54-57) | 0.74 / 0.92 | 1.10 (-0.75-3.17) | 4 | 0.14 | 4 | 2 |
| CDKN1A (positive control) | 1.0 (0.8-1.2) | -2.25 / -2.19 | -4.43 (-6.42 to -2.45) | 1 | 0 | 1 | 5 |

**Immune and control verdicts**

| gene | verdict |
|---|---|
| B2M | Typical vs TNBC; ambient-dominated. |
| HLA-A | Typical or low. |
| TAP1 | **Below** public tumors (CI excludes 0). |
| PSMB9 | **Below** public tumors (CI excludes 0). |
| NLRC5 | Low (borderline). |
| CD274 | Not interpretable at about 1 CPM. |
| CSN3 | Removed **only** by the ambient filter, which is load-bearing. |
| KRT5 | Absent (as expected). |
| PTPRC | Not called; ambient/immune signal. |
| COL1A1 | Not called. |
| GAPDH | Not called; cytoplasmic gene depleted in nuclei. |
| ACTB | Not called. |
| MALAT1 | Not testable. |
| BRCA1 | Borderline; mutant pre-mRNA is retained (module 1). |
| TP53 | Not called. |
| CDKN1A | **Far below** public tumors, consistent with TP53 loss. |

## 6. What this means for the outlier list

**1. Treat the step15 list as a ranked hypothesis list with an FDR of about 0.5, not as 867 findings.**
- Ranking by fold cleared in 7 of 8 tumors and by P(call) is better calibrated: FDR about 0.3 at 8x and about 0.15-0.2 at 16-32x.
- `tables/outlier_list_with_pcall.csv` gives P(call) for every list gene.

**2. Prefer the gene's measured reference-compartment bias when one exists.**
- It transfers better: R2 0.77-0.87, against 0.54-0.63 for the model.
- ATR, CTTN, EWSR1 and ELF5 should be dropped or downgraded on that basis.

**3. Long genes (over 500 kb) need exon-only counts before any claim.**
- Their correction is extrapolated and noisy (SD 1.7-2.3 log2), and housekeeping genes of that length show +1.5 log2 residual excess.
- ERBB4, SOX6, ESRRG, MECOM, SHANK2 and NAALADL2 fall here.
- They stay far above public TNBC under every correction tried. But that is a statement about nuclear RNA, which can mislead about protein: ERBB4 is high in RNA but HER4 protein was not detected.

**4. The best-supported RNA outliers vs public TNBC** (stable to every technical perturbation tested):
- **Strongest:** CARD18 (about 670x), ENPP3, LDLRAD3, EHF, FOLH1, SPECC1L, SLC28A3, SLC6A14 and HORMAD1 (7-34x).
- **Moderate:** POLQ and KIF18A (about 5x).

**5. CD44's "outlier" status is weak, but the claim survives.**
- CD44 clears only 2.5x, with P(call) 0.63 and FDR about 0.5.
- Its level is exactly what the 12-copy amplicon predicts.
- "Amplified, dosage-driven, modestly above TNBC" is supported. "Outlier" is not robust.

**6. Every "typical", "low" or "not over-expressed" claim holds, and the negative controls behave correctly.**
- TAP1, PSMB9 and CDKN1A are significantly below public tumors.
- Caution: CSN3 shows that without the ambient filter, a pure soup gene becomes the top outlier.

**Caveats.**
- The reference-compartment null contains real between-patient biology, which inflates it. The tumor list contains real Diana-specific biology, which is what we want to find. So the FDR proxy is approximate and may be conservative.
- In the other direction, no reference compartment captures the length bias specific to tumor nuclei. That could make the proxy anti-conservative for long genes.
- Exon-only recounting (module 1) and protein (module 5) are the independent checks.

## 7. Files

All paths are under `private/analysis/step19-qc/m4_stats/`.

**Docs and reference**
- `README.md`: commands, pinned versions, input checksums, runtime, 0 bytes of S3 transfer.
- `ref/HK_genes_Eisenberg2013.txt`: Eisenberg & Levanon, *Trends Genet* 2013; 66,915 bytes; md5 3c29a7d8976857b6242b317bf58ba25b.

**Scripts** (`scripts/`; `run_all.sh` runs everything in about 5.5 min)

| file | purpose |
|---|---|
| `run.sh` | uv wrapper with pinned packages |
| `run_all.sh` | full pipeline |
| `common.py` | shared reimplementation of the step15 model |
| `01_build_pseudobulk.py` | pseudobulks and per-nucleus candidate counts |
| `02_bias_model_validation.py` | tests 1a, 1b, 1c and the length/intron analysis |
| `03_dosage.py` | dosage calibration |
| `04_bootstrap_candidates.py` | candidate bootstrap |
| `05_robustness.py` | replicate concordance, downsampling, threshold grid |
| `06_exon_only_recall.py` | exon-only recall (pending module 1) |
| `07_length_recalibration.py` | length recalibration and FDR curves |
| `09_genomewide_pcall_longgenes.py` | genome-wide P(call), watchlist, direct-bias variant |
| `08_candidate_table.py` | merged candidate table and verdicts |

**Tables** (`tables/`)

| group | files |
|---|---|
| headline | `candidate_summary.csv`, `genes_master.csv.gz`, `outlier_list_with_pcall.csv` |
| 1a bias model | `1a_loco.csv`, `1a_candidates_direct_bias.csv`, `1a_direct_bias_list_size.csv` |
| 1b housekeeping | `1b_housekeeping.csv`, `1b_housekeeping_in_outlier_list.csv` |
| 1c calibration | `1c_calibration_reference_compartments.csv`, `1c_reference_false_positive_genes.csv`, `1c_public_tumor_as_query_null.csv`, `1c_fdr_with_uncertainty_margin.csv`, `1c_fdr_by_fold_threshold.csv` |
| 1L length/intron | `1L_length_enrichment.csv`, `1L_logistic_call_vs_structure.csv`, `1L_residual_vs_span.csv`, `1L_housekeeping_excess_by_span.csv`, `1L_outliers_beyond_training_span.csv`, `1L_outliers_by_span_within_platform.csv`, `1L_recalibrated_list_sizes.csv`, `1L_candidates_recalibrated.csv`, `1L_genomewide_pcall_summary.csv`, `1L_long_gene_watchlist.csv`, `1L_gbm_vs_linear_extrapolation.csv`, `1L_watchlist_linear_bias.csv` |
| 1L exon-only | `1L_exon_only_recall.csv` (written once module 1 output exists) |
| 2 dosage | `2_dosage_slopes.csv`, `2_dosage_by_CN.csv`, `2_dosage_by_CN_LOH.csv`, `2_candidates_dosage.csv` |
| 3 uncertainty | `3_candidates_bootstrap.csv`, `3b_L1_vs_L2_concordance.csv` |
| 4 robustness | `4_threshold_grid_list_sizes.csv`, `4_candidate_calls_by_variant.csv`, `4_candidate_robustness.csv` |
| logs | `02_log.txt`, `run_all.log` |

**Figures** (`figures/`)

| file | shows |
|---|---|
| `fig1a_loco.png` | leave-one-compartment-out predictions vs observed |
| `fig1b_housekeeping.png` | housekeeping vs all-gene excess distributions |
| `fig1c_fdr_by_fold.png` | FDR proxy vs fold threshold |
| `fig1L_length.png` | bias and residuals vs gene span |
| `fig1L_span_decile_enrichment.png` | outlier enrichment by span decile |
| `fig1L_hk_length_trend.png` | housekeeping excess vs span with LOWESS |
| `fig2_dosage.png` | dosage regression with candidates |
| `fig3_L1_vs_L2.png` | library concordance |
| `fig3_candidate_forest.png` | candidate excess with CIs |