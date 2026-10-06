# Step 19 / QC module 3: ambient RNA

## Method
- **Empty droplets.** Three soup profiles were built:
  - E10_100 is the brief's window; in L1 it has only 6,957 barcodes and 103k UMIs.
  - E1_99 is the step 6/13 window.
  - Eplateau is non-called barcodes at ranks 100,001–160,000: about 60k droplets at a median 494/499 UMIs, 30M UMIs.
  - CellBender's own empty prior was 527/537 UMIs.
- **Contamination (rho).** Same "foreign marker" method as step 6, using IG genes for epithelial groups and secretory genes for the rest. Values are L1/L2:

  | Compartment | Step 6 | Plateau soup | Physical bound | Cell mixture θ | CellBender removed |
  |---|---|---|---|---|---|
  | Malignant | 0.146/0.140 | 0.090/0.093 | 0.08–0.13 | 0.15 | 0.078/0.084 |
  | T/NK | 0.5 (capped) | 0.43/0.42 | 0.38–0.43 | 0.25 | 0.71 |
  | Fibroblast | 0.35 | 0.22/0.24 | 0.20–0.27 | — | 0.38/0.41 |

- **Corrections.**
  - (a) Raw.
  - (b) Step 6 group rho.
  - (c) SoupX global (L1 0.121, L2 0.081).
  - (d) CellBender 0.3.2:
    - expected cells set to the Cell Ranger call; 70k droplets; 60 epochs; learning rate 1e-4;
    - FPR 0.01 is primary, 0.05 is saved;
    - ambient-count threshold 1, so 3,340 low-ambient genes pass through uncorrected;
    - convergence 0.03/0.46.
  - Reported but outside the verdict: group rho with the plateau soup, and a DecontX-style per-cell mixture model.
  - CIs come from 500 bootstraps over nuclei, with rho re-estimated each time.
- **Empty-droplet test.** For each gene, R = observed / (rho × N × soup), with rho uncapped. "Above background" means the lower 95% bound of R is >1 under all 3 soups in both libraries. Genome-wide with the plateau soup:
  - malignant: 23,942/24,504 genes (L1) and 23,677/24,275 (L2);
  - T/NK: about 12k of 15.8k.
- **Circularity caveat.** For stromal and immune groups, CSN3, SCGB3A1 and LTF are the rho markers, so their R is ≈1 there by construction.
- **Depth check (model-free).** A purely ambient gene's CPM in a nucleus falls as 1/N (slope −1); an expressed gene's stays flat (slope 0). In malignant nuclei:
  - IGKC −0.98/−0.85, B2M −0.92/−0.85, COL1A1 −0.95;
  - targets −0.1 to +0.3;
  - CSN3 −0.42/−0.39;
  - TACSTD2 −0.69/−0.63.

## Results
- Per-candidate numbers are in `tables/candidate_robustness_verdicts.csv` and `figures/candidates_before_after.png`.
  - Tumor CPM moves ≤10% for expressed genes under every correction.
  - Fold changes grow, because non-malignant nuclei are 25–70% ambient and that ambient is largely tumor-derived.
- **CellBender log2FC (L1 [CI]):**
  - CD44 2.09 [1.99, 2.20]
  - VTCN1 3.87
  - FOLH1 5.85
  - ENPP3 4.68
  - PRLR 3.89
  - ERBB4 2.28
  - SLC28A3 5.54
  - SLC6A14 4.73
  - HORMAD1 5.53
  - POLQ 4.50
  - KIF18A 5.21
  - SLFN11 −3.19
  - NECTIN4 4.28 [3.85, 4.85]
  - CCND1 4.31 [3.85, 4.80]
  - CSN3 2.17 [2.08, 2.27]
  - TACSTD2 −0.02 [−0.26, 0.22]
- **No ≥2x effect in raw data:** ATR, TOP1, EGFR, CD276, MALAT1 and TP53.
- **Public TNBC (median log2 excess over 8 tumors, raw → CellBender with re-fitted bias):**
  - CD44 2.56 → 3.34
  - VTCN1 1.53 → 1.81
  - FOLH1 4.39 → 3.59
  - ENPP3 5.64 → 4.48
  - CARD18 9.6 → 10.0
  - NECTIN4 0.24 → 1.02
  - TACSTD2 0.06 → −1.60
  - B2M 0.10 → −3.14
- **Public ambient.** The public data have no empty droplets, so I estimated contamination with IG genes against each sample's pooled-cell profile: 0.5–8% in 7 of 8 tumors. MH4031 was not identifiable and left uncorrected.
- **What would falsify these results:**
  - For CSN3: casein RNA stuck to nuclei, residual doublets, or a BAM intronic or allele check showing it is not transcribed in tumor nuclei.
  - For the TNBC comparison: correcting the public raw matrices against their empty droplets raising public tumor CPM >2x for FOLH1, ENPP3, VTCN1 or CD44.

## Limits
- 60 epochs instead of 150; L2 is less converged.
- CellBender over-removes in small immune nuclei and the mixture model under-removes, so absolute immune levels are bounds, not measurements.
- RNA attached to nuclei and residual doublets look like expression to every method here.
