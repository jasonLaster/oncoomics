# Quality control of the single-nucleus target claims (step 19)

Diana multi-omic review · 2026-10-05 · research use only. Written for computational biologists reviewing how the KH022
single-nucleus RNA data were turned into target and biology claims, and which of those claims survive.

**Folder note.** Published here as step 20. The private working folder is `private/analysis/step19-qc/`, so module paths inside the reports say step19-qc.

**Status.** Six of seven modules are complete. The CellBender run in module 3 is still training. Its interim robustness
verdicts, based on the group-rho, SoupX, mixture and plateau corrections, are included; the CellBender column will be
added when it finishes.

---

## 1. Data and design

| | |
|---|---|
| Sample | KH022: two 10x GEM-X 3' v4 libraries (L1, L2) from one nuclei suspension, so they are **technical replicates**. Frozen 4/10 breast core, taken on day 8 of chemo-immunotherapy. **Specimen identity confirmed genetically** in module 2. |
| Processing | Cell Ranger 10.1.0, GRCh38-2024-A, introns counted. About 38-39k called nuclei per library; ~50% malignant. |
| Comparators | (1) Her own non-malignant nuclei in the same sample. (2) Tumor cells from 8 public TNBC (GSE161529: whole cells, older chemistry, exon-only counting). (3) Proteomics on the same biopsy event. (4) Human Protein Atlas normal tissues. |
| Unit of inference | n = 1 patient. Nuclei are not independent replicates. Intervals cover measurement and model uncertainty, not biological variation. |
| Candidate set | 47 genes (`candidate_genes.tsv`): targets, amplicon and lineage genes, immune genes, plus positive controls (BRCA1, TP53, CDKN1A) and negative controls (CSN3, KRT5, PTPRC, COL1A1, GAPDH, ACTB, MALAT1). |

**Module summary**

| Module | Question | Method | Headline |
|---|---|---|---|
| m1 Counting | Are counts what we think? | BAM region recount; exonic / intronic / antisense / MAPQ split; GENCODE overlap audit | Counts match the matrix exactly. **CARD18 is a gene-model artifact.** Long genes are 90-99% pre-mRNA. |
| m2 Labels | Are tumor / normal calls right? | Per-nucleus genotypes at 7,969 WGS somatic SNVs; calibrated mixture model | Malignant precision 0.94 and recall 0.90. **The "normal luminal epithelium" group is mostly tumor.** KH022 = 4/10 core. |
| m3 Ambient | Is the signal background RNA? | Empty-droplet test; group rho, SoupX, mixture and plateau corrections; CellBender (running) | 35/47 candidates are robust in direction and ≥2x. Interim. |
| m4 Statistics | Is the "outlier vs TNBC" call calibrated? | Leave-one-compartment-out bias model; reference-compartment null; housekeeping controls; dosage; bootstrap; robustness grid | **Empirical FDR ≈ 0.5 at 2x**, falling to ≈0.15-0.3 at ≥8x. Dosage check passes. |
| m5 Protein | Does RNA agree with protein? | OncoOmicsDx panel (66 proteins) vs pseudobulk | Presence/absence agrees (p = 4×10⁻⁵). Levels do not (ρ = 0.17). **HER4 protein not detected.** |
| m6 Biology | Is it a plausible target? | HPA localization and normal-tissue RNA; gene span | Surface flags; B7-H4 is highest in normal breast; HORMAD1 is testis-restricted. |
| m7 Exon-only | Does the outlier call survive without intron counting and without the bias model? | Diana exonic UMIs vs public exon-only counts | **B7-H4 is not an outlier.** Long-gene outliers survive. |

## 2. What changed

| Claim (before step 19) | Status now | Evidence |
|---|---|---|
| CARD18 is the largest outlier (~800x) | **Withdrawn** | 99% of its UMIs fall in a 390 kb 5' extension of the 2024-A gene model; exonic CARD18 is ~1 CPM (m1). |
| B7-H4 (VTCN1) is an outlier vs TNBC | **Withdrawn** | 92% intronic; ~0.7x public tumors on exons, 0/8 (m7). Still tumor-enriched within the sample. |
| ERBB4 is ~77x above TNBC | **Downgraded** | 99% intronic; exonic ~48 CPM, ~30x but only 6/8; HER4 protein not detected (m1, m5, m7). |
| ATR is ~5x above TNBC | **Unresolved** | Exon-only ~22x (8/8), but tumor-cell enrichment within the sample is <2x, and the measured bias exceeds the model prediction (m4). |
| CD44 outlier | **Reframed** | ~6x, fully explained by 12-copy dosage. "Amplified and expressed" stands; "outlier" is fragile (FDR ~0.5). |
| PRLR, ERBB4, B7-H4 "as high in her normal duct cells" (step 18) | **Withdrawn** | That comparator was 80-100% tumor (m2). Tumor selectivity vs normal luminal cells is unknown. |
| Casein is pure background RNA (step 18) | **Revised** | Tumor nuclei transcribe κ-casein: intronic signal 3.3x non-tumor, in 83% of tumor nuclei. Exported mRNA dominates the ambient pool (m1). |
| KH022 is "probably" the 4/10 core | **Confirmed** | 0 alt molecules where 21.2 were expected at 9 subclone sites absent from the 4/10 exome (p = 6×10⁻¹⁰) (m2). |
| Antigen-processing genes low in tumor | **Confirmed** | TAP1 and PSMB9 are below public tumors (CIs exclude 0); depleted vs non-malignant nuclei; robust to labels and ambient. |
| TROP-2, TOP1, NECTIN4, EGFR, CCND1 typical | **Confirmed** | Every module. |

## 3. Per-gene scorecard

**Tiers**

| Tier | Meaning |
|---|---|
| **A** | Outlier vs TNBC on both the exon-only and the bias-model tests, with tumor-cell origin shown by intronic counts. |
| **B** | Exon-only outlier with tumor-cell origin, but fragile under the bias model (P(call) < 0.8 or fold < 4x). |
| **C** | High vs TNBC, but tumor-cell origin not shown. |
| **D** | Tumor-enriched within the sample, not a robust outlier vs TNBC. |
| **E** | Low or depleted in tumor. |
| **F** | Typical. |

**How to read the columns**
- **FDR proxy** is the reference-compartment null at the gene's fold (m4).
- **Ambient** reports whether the tumor-vs-non-malignant effect keeps its direction and stays ≥2x across corrections
  (m3, interim).
- **Protein** comes from the OncoOmicsDx panel on the 4/10 block. "Not on panel" means the protein was not assayed.

| Gene    | Tier                 | Tumor-cell origin (intronic)   | Label-robust   | Ambient                           | vs TNBC exon-only   | Exon fold vs TNBC   | vs TNBC model   |   P(call) |   FDR proxy |   CN | Intronic share   | Protein               |
|:--------|:---------------------|:-------------------------------|:---------------|:----------------------------------|:--------------------|:--------------------|:----------------|----------:|------------:|-----:|:-----------------|:----------------------|
| EHF     | A                    | PASS                           | PASS           | robust                            | PASS                | 28.3x               | PASS            |      1    |        0.27 |    9 | 57%              | not on panel          |
| ENPP3   | A                    | PASS                           | PASS           | robust                            | PASS                | 46.2x               | PASS            |      1    |        0.16 |    3 | 89%              | not on panel          |
| ESRRG   | A                    | PASS                           | PASS           | robust                            | PASS                | 61.7x               | PASS            |      0.97 |        0.27 |    5 | 98%              | not on panel          |
| FOLH1   | A                    | PASS                           | PASS           | robust                            | PASS                | 19.2x               | PASS            |      1    |        0.3  |    3 | 80%              | not on panel          |
| HORMAD1 | A                    | PASS                           | PASS           | robust                            | PASS                | 37.7x               | PASS            |      0.96 |        0.39 |    4 | 56%              | not on panel          |
| KIF18A  | A                    | PASS                           | PASS           | robust                            | PASS                | 14.5x               | PASS            |      0.89 |        0.39 |    5 | 73%              | not on panel          |
| LDLRAD3 | A                    | PASS                           | PASS           | robust                            | PASS                | 11.6x               | PASS            |      0.99 |        0.27 |   12 | 95%              | not on panel          |
| MECOM   | A                    | PASS                           | PASS           | robust                            | PASS                | 74.8x               | PASS            |      0.92 |        0.3  |    4 | 96%              | not on panel          |
| POLQ    | A                    | PASS                           | PASS           | robust                            | PASS                | 20.6x               | PASS            |      0.86 |        0.39 |    3 | 74%              | not on panel          |
| SHANK2  | A                    | PASS                           | PASS           | robust                            | PASS                | 46.8x               | PASS            |      0.88 |        0.3  |    9 | 93%              | not on panel          |
| SLC28A3 | A                    | PASS                           | PASS           | robust                            | PASS                | 48.4x               | PASS            |      1    |        0.3  |    2 | 71%              | not on panel          |
| SLC6A14 | A                    | PASS                           | PASS           | robust                            | PASS                | 32.9x               | PASS            |      0.98 |        0.3  |    2 | 65%              | not on panel          |
| SPECC1L | A                    | PASS                           | PASS           | robust                            | PASS                | 35.3x               | PASS            |      0.99 |        0.3  |    8 | 84%              | not on panel          |
| CD44    | B                    | PASS                           | PASS           | robust                            | PASS                | 6.1x                | WEAK            |      0.63 |        0.5  |   12 | 68%              | not on panel          |
| CTTN    | B                    | PASS                           | PASS           | robust                            | PASS                | 5.9x                | WEAK            |      0.56 |        0.5  |    9 | 38%              | not on panel          |
| ELF5    | B                    | PASS                           | PASS           | robust                            | PASS                | 11.4x               | WEAK            |      0.81 |        0.44 |    9 | 42%              | not on panel          |
| EWSR1   | B                    | PASS                           | PASS           | robust                            | PASS                | 7.7x                | WEAK            |      0.79 |        0.44 |    8 | 24%              | not on panel          |
| KYNU    | B                    | PASS                           | PASS           | robust                            | PASS                | 19.2x               | WEAK            |      0.75 |        0.44 |    5 | 93%              | not on panel          |
| PRLR    | B                    | PASS                           | PASS           | robust                            | PASS                | 7.3x                | NO              |      0.29 |             |    2 | 82%              | not on panel          |
| SOX6    | B                    | PASS                           | PASS           | robust                            | PASS                | 108.6x              | WEAK            |      0.72 |        0.39 |    5 | 90%              | not on panel          |
| ATR     | C                    | NO                             | PASS           | no ≥2x effect                     | PASS                | 22.5x               | WEAK            |      0.79 |        0.39 |    4 | 65%              | not on panel          |
| ERBB4   | D                    | PASS                           | PASS           | robust                            | NO                  | 30.0x               | WEAK            |      0.79 |        0.39 |    3 | 99%              | ND                    |
| NECTIN4 | D                    | PASS                           | PASS           | no ≥2x effect                     | NO                  | 1.9x                | NO              |      0.03 |             |    5 | 10%              | not on panel          |
| VTCN1   | D                    | PASS                           | PASS           | robust                            | NO                  | 0.7x                | WEAK            |      0.61 |        0.5  |    3 | 91%              | not on panel          |
| B2M     | E                    | DEPLETED                       | PASS           | robust                            | LOW                 | 0.2x                | NO              |      0.06 |             |    1 | 6%               | not on panel          |
| CD274   | E                    | DEPLETED                       | PASS           | robust                            | NO                  | 0.9x                | NO              |      0.1  |             |    3 | 80%              | ND                    |
| HLA-A   | E                    | DEPLETED                       | PASS           | robust                            | LOW                 | 0.2x                | NO              |      0.01 |             |    5 | 0%               | not on panel          |
| NLRC5   | E                    | DEPLETED                       | PASS           | robust                            | NO                  | 0.5x                | NO              |      0    |             |    2 | 79%              | not on panel          |
| PSMB9   | E                    | DEPLETED                       | PASS           | robust                            | LOW                 | 0.1x                | NO              |      0    |             |    5 | 38%              | not on panel          |
| SLFN11  | E                    | DEPLETED                       | PASS           | robust                            | NO                  | 2.1x                | NO              |      0.12 |             |    2 | 54%              | ND                    |
| TACSTD2 | E                    | NO                             | PASS           | holds, <2x some corr.             | LOW                 | 0.2x                | NO              |      0.1  |             |    4 | 0%               | detected 1705 amol/ug |
| TAP1    | E                    | NO                             | PASS           | robust                            | LOW                 | 0.2x                | NO              |      0    |             |    5 | 6%               | not on panel          |
| CCND1   | F                    | NO                             | PASS           | no ≥2x effect; direction unstable | NO                  | 0.7x                | NO              |      0.01 |             |    9 | 7%               | not on panel          |
| CD276   | F                    | NO                             | PASS           | no ≥2x effect                     | NO                  | 0.8x                | NO              |      0.01 |             |    2 | 48%              | not on panel          |
| EGFR    | F                    | NO                             | PASS           | no ≥2x effect                     | NO                  | 1.7x                | NO              |      0.14 |             |    2 | 88%              | detected 171 amol/ug  |
| TOP1    | F                    | NO                             | PASS           | no ≥2x effect                     | NO                  | 1.7x                | NO              |      0.12 |             |    3 | 69%              | detected 568 amol/ug  |
| CARD18  | WITHDRAWN (artifact) | PASS                           | PASS           | robust                            | NO                  | 3.1x                | PASS            |      1    |        0.16 |    4 | 100%             | not on panel          |

**Reading notes**
- **Exon-only folds are conservative.** Nuclei lose cytoplasmic mRNA: GAPDH and ACTB come out 8-16x lower than in whole
  cells. So a gene that still exceeds public tumors on exonic counts is a strong call.
- **The intronic share is high for long genes,** which is expected in nuclei.
- **"Low" calls for intronless or cytoplasmic genes** (TACSTD2, HLA-A, B2M, TAP1) partly reflect the same cytoplasmic
  bias. Their depletion against her own non-malignant nuclei is the more reliable statement.
- **Controls behave as expected:**
  - KRT5 is absent.
  - CDKN1A is far below other TNBC, consistent with TP53 loss.
  - PTPRC and COL1A1 are depleted in tumor.
  - GAPDH and ACTB show the nuclei bias.
  - CSN3 is tumor-transcribed (intronic) but ambient-dominated on exons.
  - The full table, including controls, is in `scorecard/scorecard.csv`.

## 4. Module details

### m1 Counting (`m1_counting/report.md`)
- **Recount:** xf-counted UMIs equal the matrix per barcode for 51/53 genes in both libraries. Independent (CB, UB)
  dedup gives 100.2-100.8% of the matrix.
- **Multimapping:** at most 11.7% (ENPP3, from an OR2A paralog cluster in one of its introns).
- **Annotation audit:** overlapping, antisense and readthrough features were flagged, and strand-specific counting
  separates them. CARD18 is the only failure.
- **Ambient-reduced test:** tumor-cell origin uses intronic-only UMIs (lower 95% CI of log2FC vs non-malignant > 1 in
  both libraries). Intronic counts are ambient-reduced, not ambient-free: the floor is ~2-7% after rho scaling.
- **Detection ceiling:** detection is Poisson in mean UMI. The p99 ceiling rises from 0.6 to 0.98 with intron length,
  so "% of nuclei positive" cannot be compared across genes of different structure.

### m2 Labels (`m2_labels/report.md`)
- **Truth set:** 7,969 gene-body somatic SNVs; ~135k molecules per library.
- **Model:** a per-molecule tumor/normal likelihood with ambient (empty-droplet alt fraction 0.32, so the ambient is
  tumor-dominated) and an RNA/DNA allele scale s = 0.74.
- **Accuracy:**
  - Malignant precision 0.938 / 0.938 and recall 0.90 / 0.91 (L1 / L2).
  - Within 0.04 for ambient rho varied ×0.5 to ×2.
  - About 2,000 nuclei per library are individually genotype-confirmed.
- **Errors:** the non-malignant `epithelial` group is 80% (L1) and 100% (L2) tumor. The clean normal epithelium is
  myoepithelium plus 79 L2 hormone-sensing luminal nuclei.
- **Sensitivity:** 0/47 candidate verdicts change under strict genetic tumor labels (max |Δlog2FC| 0.37).
- **Clonality:**
  - Clonal k = 0.98.
  - WGS-subclonal sites as a class have k = 0.40.
  - The 3/13-specific subclone has k ≤ 0.09, which places KH022 on the 4/10 core.

### m3 Ambient (`m3_ambient/`, interim)
- **Contamination by group:**
  - Malignant 0.15-0.17.
  - Myeloid, endothelial and fibroblast 0.35-0.44.
  - T/NK and B 0.64-0.75. Small nuclei carry the most ambient.
- **Public TNBC comparators:** immunoglobulin-based rho is ~0.5-8% in 7/8 tumors (one is unestimable). So this sample is
  much more ambient-heavy than the public reference. That inflates ambient genes in Diana's tumor nuclei, which is why
  CSN3 would be the top "outlier" without the ambient filter.
- **Robustness:** 35/47 candidates keep their tumor-vs-non-malignant direction and ≥2x under every correction tried
  (raw, group rho, SoupX global, mixture, plateau). The CellBender column is pending.

### m4 Statistics (`m4_stats/report.md`)
- **Bias model:**
  - Out-of-fold R² 0.605; residual SD 1.11 log2.
  - Leave-one-compartment-out R² 0.54-0.63.
  - A gene's own measured bias, where available, transfers better (R² 0.77-0.87).
- **Empirical FDR of the "≥7/8 tumors at >2x" outlier rule:**

  | Threshold | FDR proxy |
  |---|---|
  | 2x | 0.46-0.61 |
  | 8x | ~0.3 |
  | 16-32x | ~0.15-0.2 |

  Without the bias term, 57% of genes would be called.
- **Housekeeping controls:** median residual excess +0.22 log2, rising with gene span to +1.46 log2 above 500 kb.
- **Dosage:** tumor log2FC vs copy number has slope 0.37 (95% CI 0.33-0.40) and segment Spearman 0.70 / 0.71. This
  orthogonally validates both labels and quantification.
- **Replicates:** L1 vs L2 Spearman 0.993-0.999. Outlier lists overlap with Jaccard 0.957.

### m5 Protein (`m5_protein/report.md`)
- **Agreement:** detected proteins have higher tumor RNA (median 65.5 vs 5.9 CPM; p = 4×10⁻⁵).
- **Levels:** protein correlates with non-malignant RNA (ρ = 0.43) more than with tumor RNA (ρ = 0.17), so the
  microdissected protein sample is not tumor-pure.
- **Discordances:** HER4 is not detected despite high (intronic) ERBB4. Stromal RNA dominates TYMP, hENT1, GPNMB, Cav-1
  and vimentin.

### m7 Exon-only (`m7_exon_only/README.md`)
- **Design:** no bias model; conservative in direction because of cytoplasmic loss; exposed to ambient. Read it with m3.

## 5. How to present the findings

**Lead with the claims that pass every gate (Tier A), stated as RNA in tumor nuclei vs 8 public TNBC tumors.** Give the
fold change and the FDR proxy for each.

| Group | Genes |
|---|---|
| Surface or secreted, target-relevant | FOLH1/PSMA (~19x), ENPP3 (~46x), SLC28A3 (~48x), SLC6A14 (~33x) |
| DNA repair / replication | POLQ (~21x), KIF18A (~15x) |
| Antigen | HORMAD1 (~38x; testis-restricted in normal tissue) |
| Amplicon | SHANK2, SPECC1L, LDLRAD3 |
| Lineage transcription factors | EHF, ESRRG, MECOM |

**Then the immune state**
- Antigen processing (TAP1, PSMB9, NLRC5, B2M, HLA-A) is depleted in tumor nuclei relative to her own non-malignant
  nuclei, and TAP1 and PSMB9 are below public tumors.
- CDKN1A is near-absent, consistent with TP53 loss.

**State plainly what was withdrawn and why:** CARD18 (gene model), B7-H4 (intronic), and the normal-epithelium
comparisons (label contamination).

**Always attach the limitations**
- n = 1.
- Technical replicates only.
- 8 public tumors as the reference, on a different chemistry.
- RNA is not protein: none of the Tier A surface targets were on the proteomics panel.
- On-treatment sample (day 8).

## 6. Open items

1. **CellBender (m3).** Running. Its results will be added to the scorecard as a robustness column; the interim
   verdicts already use four corrections.
2. **Clean normal-epithelium reference.**
   - Use public normal-breast and BRCA1-carrier preneoplastic luminal progenitors (GSE161529).
   - This is needed to say whether any target is tumor-selective against normal duct cells, especially PRLR, ERBB4 and
     B7-H4.
   - Her own clean normal luminal population is too small: 79 nuclei, L2 only.
3. **Same-platform reference.** A nuclei TNBC cohort on GEM-X with introns would remove the need for a bias model.
4. **Protein confirmation** by IHC on tumor cells for Tier A surface targets (PSMA, ENPP3, CNT3/SLC28A3, SLC6A14) and
   for HORMAD1.
5. **ATR:** reconcile the high exon-only excess with the weak within-sample tumor enrichment, for example from the
   measured bias of ATR's nearby genes.

## 7. Reproducibility
- Each module folder has scripts, a README with exact commands and pinned package versions, input checksums, runtime
  and bytes transferred.
- S3 transfer stayed under the per-module 5 GB cap (m1 ~3 GB, m2 ~3.5 GB, m4 0). No cloud jobs; local compute only.
- To rebuild the scorecard: `uv run --no-project --python 3.11 --with pandas python scorecard/build_scorecard.py` reads
  each module's output tables.
