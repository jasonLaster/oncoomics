# Step 9: bulk tumor RNA vs TCGA (2026-10-03)

This is research prioritization only. It makes no clinical or treatment claims. There is one bulk sample, so every
number below is a relative position against public tumors, not a diagnosis. Sources and commands are in `README.md`;
every number is in `summary_numbers.json`.

## Bottom line

1. **Read every TCGA comparison through a capture artefact.** The library is not poly(A). The tumor RNA FASTQs carry the
   Personalis `ACE4` capture tag. Its profile correlates with TCGA-TNBC less well than any TCGA tumor does: Spearman 0.76
   vs 0.84-0.93. Its dynamic range is compressed: log-log slope 0.77 vs 0.89-1.03.
   - **Cancer-panel genes are inflated.** FoundationOne-panel genes (from the OncoKB list) sit a median **+1.78 log2
     (~3.4x)** above expectation. 45% of them are inflated more than 4x, vs 4% of other genes (MWU p ~1e-64; fig1).
   - **Affected genes include the ones we care about:** ATM, BRCA1/2, PALB2, PARP1, ERBB3, MET, AXL, IGF1R, FGFR1-3,
     ERBB2, EGFR, AR, ESR1, FOLR1, CD274 and CDH1. Their high TCGA percentiles cannot be interpreted.
   - **Replication histones are about +4.7 log2**, which is consistent with non-poly(A) chemistry.
   - **`percentiles.csv` flags each gene** in the `capture_concern` column.
2. **Subtype: PAM50 Basal-like is robust, Lehmann TNBCtype-4 is not.**
   - **PAM50 Basal-like.** Spearman to the Basal centroid is 0.51, and 0.62 on the 34 non-panel PAM50 genes. Gene
     bootstrap gives Basal 90% / Normal-like 10%. Noise injection keeps Basal 99.7% of the time.
   - **No robust TNBCtype-4 call.** The answer depends on the method: LAR by signature z-score, BL1 by rank score, BL2 by
     TCGA-derived centroids. The strongest Lehmann signal is MSL (93-94th percentile), which tracks stroma and normal
     tissue rather than tumor cells.
3. **Microenvironment: B/plasma- and macrophage-rich, not T-cell-inflamed.**
   - **Immunoglobulin.** IG genes are 22.6% of all TPM, the 96th percentile of TCGA-TNBC. They are **IgA-dominant**: 80%
     of IgA+IgG, vs a TNBC median of 14% (98th percentile).
   - **Cell-type scores.** B cells are at the 87-90th percentile and macrophages at the 91st.
   - **T-cell and IFN-γ scores sit mid-range.** CD8 is at the 36th percentile, cytolytic activity at the 41st and
     IFN-γ-6 at the 49th. Among immune-high TCGA-TNBC, cytotoxic, cytolytic, IFN-γ and GEP scores fall to the 0-10th percentile.
4. **This specimen looks epithelium-poor.**
   - **Epithelial and proliferation markers are low.** The non-panel keratin/claudin panel is at the 7th percentile and
     the PAM50 proliferation score at the 9th.
   - **Benign breast and adipose markers are high:** SCGB3A1, PIGR, PIP, ANKRD30A, PLIN1 and ADIPOQ.
   - **Low tumor content in this RNA specimen is the leading explanation.** Note that KH022 nuclei are 50-57%
     CNV/allele-confirmed malignant, but KH022's relationship to this RNA specimen is unknown.
5. **RNA vs protein.** Most "high RNA / protein not detected" discordances are better explained by capture inflation,
   or by RNA from non-tumor cells, than by tumor biology. Details are in the RNA-protein section below.

## 1. Reference and harmonization

- **Reference cohort.** UCSC Xena TOIL RSEM TPM uses the same GENCODE v23 annotation, so all 59,939 patient gene IDs
  match exactly; 19,736 are protein-coding.
  - It covers 1,092 TCGA-BRCA primary tumors.
  - The **TNBC reference is the 180 Lehmann 2016 TCGA TNBC tumors** (PAM50: 115 Basal, 12 Her2, 6 Normal, 5 Luminal).
  - 139 PAM50-Basal tumors give secondary context.
- **Normalization.**
  - **TPM renormalization.** Both datasets were renormalized to protein-coding genes. In the patient, raw TPM is 61%
    protein-coding, 22.6% IG genes and 9.3% rRNA (RNA5-8S5).
  - **Quantile normalization.** The patient was quantile-normalized (QN) onto the TCGA-TNBC log2 distribution, and so
    were all TCGA samples.
  - **Rank-based checks.** These were run alongside: within-sample rank scores, Spearman correlations and ssGSEA.
- **Platform noise calibration.** The patient's per-gene |z| vs TCGA-TNBC has a 90th percentile of 2.94. A typical TCGA
  tumor's is 1.55, and the largest of any TCGA-TNBC tumor is 2.54. So single-gene percentiles are noisy even outside the
  panel.
  - **Gene-set null.** For each gene set, `null_frac_as_extreme` gives the share of expression-matched random gene sets
    (n = 2,000) whose patient percentile is at least as extreme as the observed one.
  - **No single signature beats this null.** Every null fraction is 0.36 or higher, so read the overall pattern, not
    any one percentile.

## 2. Subtypes (`subtype_scores.csv`, fig2)

**PAM50** uses genefu centroids (Parker 2009) and median-centers on all 1,092 TCGA-BRCA tumors.

| Centroid | Spearman | Rank variant | Non-panel (34 genes) |
|---|---:|---:|---:|
| Basal | **0.51** | 0.47 | **0.62** |
| Her2 | -0.05 | -0.07 | -0.04 |
| LumA | -0.29 | -0.27 | -0.46 |
| LumB | -0.41 | -0.39 | -0.32 |
| Normal | 0.27 | 0.25 | 0.10 |

- **Basal correlation.** TCGA basal TNBCs correlate 0.62-0.87 with the Basal centroid (5th-95th percentile). The
  patient's 0.51 is attenuated, as platform noise and low tumor content would predict.
- **Method agreement.** This implementation reproduces TCGA `PAM50Call_RNAseq` in 73% of tumors. The difference reflects
  centering choices.

**Lehmann** uses the Bordet implementation of the Lehmann 2011 gene lists. The score is the mean z of up genes minus
the mean z of down genes, relative to TCGA-TNBC. Signature gene coverage is 83-95%.

| Signature | Score | TCGA-TNBC percentile | Percentile, panel genes removed |
|---|---:|---:|---:|
| BL1 | -0.31 | 27 | 21 |
| BL2 | -0.98 | 2 | 3 |
| IM | 0.42 | 71 | 69 |
| M | -0.21 | 36 | 33 |
| MSL | **1.10** | **93** | 94 |
| LAR | 0.14 | 73 | 72 |

- **6-type call: MSL** (bootstrap 100%).
- **4-type call, by method:**

| Method | Agreement with Lehmann S1 refined calls in TCGA | Patient call |
|---|---:|---|
| Signature z-score | 85% | LAR (bootstrap 99%; 93% retained under noise injection) |
| Rank score | 61% | BL1 |
| TCGA leave-one-out centroids | 72% | BL2 (ρ only 0.18; LAR 0.07, M -0.02, BL1 -0.17) |

- **Conclusion: indeterminate.** At most there is a weak LAR lean.
- **Caution on the LAR lean.** The LAR-side markers AR, ESR1, FOXA1 and GATA3 are all capture-inflated panel genes, and
  AR protein is not detected. PGR (8.5 TPM, 97th percentile; not a panel gene) is more consistent with an admixture of
  benign luminal breast cells, and so are the SCGB3A1 and PIP signals.

**Burstein (LAR/MES/BLIS/BLIA).** No public, reproducible classifier exists, so no call is made.

- **Proxies:**

| Axis | Proxy | Position |
|---|---|---|
| LAR | Lehmann LAR | 73rd percentile |
| MES | Lehmann M / MSL | 36th / 93rd percentile |
| BLIS marker | VTCN1 | 22nd percentile |
| BLIA | IFN-γ / GEP | ~50th percentile |

- **Reading.** Nothing distinguishes BLIA from BLIS here.

## 3. Proliferation, immune and stromal context (`signature_scores.csv`, fig3; TCGA-TNBC percentiles)

| Axis | Percentile | Panel genes removed | Note |
|---|---:|---:|---|
| PAM50 proliferation (11 genes) | 9 | 7 | MKI67 85th, TOP2A 11th, CCNB1 7th; null 0.60 |
| Epithelial content (KRT8/18/19/7, CLDN4/7, ELF3) | 7 | 9 | consistent with low tumor content |
| ESTIMATE stromal / immune / total | 78 / 64 / 74 | 65 / 59 / - | ssGSEA re-implementation |
| B cells (Danaher) | 87 | 90 | MS4A1 is panel-inflated |
| Plasma markers (MZB1, JCHAIN, TNFRSF17, DERL3) | 73 | 76 | IG fraction 96th; IgA share 98th |
| Macrophages (Danaher) | 91 | 91 | CD163 91st, CD68 84th, GPNMB 99th |
| T cells / CD8 / cytotoxic | 74 / 36 / 42 | 79 / 36 / 43 | |
| Cytolytic (GZMA, PRF1) | 41 | 44 | |
| IFN-γ 6 / GEP 18 (unweighted) | 49 / 57 | 49 / 42 | weights not applied |
| TLS 9 genes (Cabrita) | 62 | 63 | |
| Checkpoint set | 83 | **44** | high value is a panel artefact |

**EPIC deconvolution** used the TRef profiles.

| Cell type | Patient | TCGA-TNBC median |
|---|---:|---:|
| Uncharacterized ("other") | **65%** (75% without OncoKB signature genes) | 83% |
| B cells | 4.2% | 0.4% |
| CAFs | 7.7% | 5.8% |
| CD4 T cells | 15.8% (3.7% without OncoKB signature genes, so panel-driven) | |
| CD8 T cells | 0-3.6% | |
| Endothelial | 5.6% | |
| Macrophages | 1.6% | |

- **No plasma-cell profile.** EPIC has no plasma reference, so IG mRNA falls into "other".
- **Isotype pattern.** IgA dominance, together with PIGR and SCGB3A1, is typical of mucosal-type or benign breast plasma
  cells. TNBC-infiltrating plasma cells are usually IgG-dominant. This is a hypothesis about tissue composition, not a
  result.

## 4. HR/DDR transcriptional context (descriptive; not an HRD call)

- **BRCA1 total RNA (100.9 TPM) is uninterpretable against TCGA.**
  - It is a capture-inflated panel gene. Its residual sits at the 71st percentile of FoundationOne genes, so there is no
    hint of relative loss.
  - Total gene TPM cannot show the documented exon-3 acceptor defect (about 83% aberrant splicing; step 4). Junction-level
    evidence is the right readout and is already in hand.
- **KEGG HR gene set.** It is at the 95th percentile, but drops to the **26th** once the 13 panel genes are removed, so
  the high value is an artefact.
- **Severson BRCA1ness (77 genes, cross-platform adaptation).** Patient r = 0.42, which is the 29th percentile of
  TCGA-TNBC (28th without panel genes) and the 84th of all BRCA.
  - **What the score tracks in TCGA:** basal-like status (AUC 0.97) and, within TNBC, the genomic HRD sum (Knijnenburg;
    ρ 0.45, p 8e-10, n = 167).
  - **Reading:** the patient's lower-than-typical value fits low tumor content and platform noise. It says nothing about
    this tumor's HRD.
  - **Context in TCGA-TNBC:** BRCA1 expression barely relates to HRD (ρ -0.15). Proliferation and HR-set expression
    relate weakly (ρ 0.33).
- **Other DDR genes:**
  - **ERCC1:** 1st percentile, not capture-flagged; protein not detected, which is concordant.
  - **MGMT:** 26th percentile; protein 1,281.
  - **SLFN11:** 77th percentile, not inflated.
  - **POLQ:** 92nd percentile.

## 5. Payload / ADC context (`percentiles.csv`, fig4; QN percentile in TCGA-TNBC)

| Gene | TPM | Percentile | Capture concern | Protein (CP0216) | Reading |
|---|---:|---:|---|---|---|
| TACSTD2 | 176 | 34 | none | 1,705 (near assay median) | Average RNA; protein presence is the better evidence |
| TOP1 | 62 | 28 | none | 568 (LOQ 400) | Concordant: modest |
| SLFN11 | 33 | 77 | none | ND (LOQ 100) | Nuclei: malignant 5 CPM / 2.9% detected, vs myeloid 42, fibroblast 31, T/NK 27 CPM. Bulk RNA is largely non-tumor |
| ABCB1 / ABCG2 | 9.7 / 1.8 | 94 / 69 | ABCB1 modest | ABCB1 ND (LOQ 125) | Low absolute levels |
| ERBB3 | 1,157 | 100 | panel-inflated (+4.2 log2) | ND | Nuclei: malignant 128 CPM, 48% detected. Real tumor RNA, magnitude inflated; protein below LOQ |
| MET | 104 | 99 | panel-inflated | ND | Nuclei: mostly non-malignant epithelium (78 vs 14 CPM) |
| AXL / IGF1R / FGFR1-3 | 155-749 | 98-100 | panel-inflated | ND | Artefact-dominated |
| FOLR1 | 308 | 97 | panel-inflated (+3.6) | 697 (LOQ 500) | Concordant with low-level protein once inflation is discounted |
| ERBB2 | 248 | 98 | panel-inflated | ND | |
| EGFR | 180 | 97 | panel-inflated | 171 | Nuclei: fibroblast ≈ non-malignant epithelium > malignant |
| CD274 | 29 | 98 | panel-inflated | ND | Nuclei: myeloid 19.5 vs malignant 1.1 CPM |
| GPNMB | 789 | 99 | outlier, not a panel gene | 1,984 | Macrophage-rich context |
| NECTIN4 / CD276 / F3 | 103 / 149 / 19 | 79 / 62 / 54 | none | not measured | Mid-to-high RNA |
| SLC39A6 (LIV-1) / PTK7 | 53 / 99 | 18 / 17 | none | not measured | Low-to-mid RNA |
| SLC29A1 / TYMP / RRM1 | 62 / 45 / 45 | 22 / 11 / 13 | none | 174 / 960 / ND | |

**Discordance explanations, in order of weight:**

1. **Capture augmentation inflates panel-gene RNA.** This affects HER3, MET, AXL, FGFR, IGF1R, AR, HER2 and PD-L1.
2. **Non-tumor cells contribute RNA.** This applies to SLFN11, PD-L1, MET and EGFR, and the step-6 nuclei readouts
   support it. The protein assay used microdissected tumor, so this mechanism predicts lower tumor protein.
3. **The specimens may differ.** RNA comes from an undated specimen with apparently low tumor content. Protein comes from
   the 2026-03-13 pre-treatment microdissected block.
4. **Assay sensitivity.** LOQs differ; for example, HER3 LOQ was not reported.

## 6. Reconciliation with single-nucleus data (step 6, read while still in progress)

- **Composition.** KH022 nuclei are about 50-59% epithelial and 50-57% CNV/allele-confirmed malignant (97.6%
  concordance of the two methods). The rest:

| Compartment | Share of nuclei |
|---|---:|
| T/NK | 11-12% |
| Fibroblast | 8% |
| Myeloid | 5% |
| B | 3.1-3.5% |
| Plasma | 1.7-1.8% |
| Adipocyte | 3% |
| Myoepithelial | 2-4% |

- **The plasma signal reconciles.** Only about 2% of nuclei are plasma cells, yet 22.6% of bulk mRNA is IG. Plasma cells
  carry very large amounts of cytoplasmic/ER IG mRNA, and nuclei preparations lose that cytoplasm. So nuclei
  under-count plasma mRNA, and bulk mRNA over-weights plasma cells relative to their cell numbers.
- **Tumor content does not reconcile.** Nuclei give about 55% malignant. In bulk, EPIC "other" is only 65% (13th
  percentile of TNBC) and the epithelial markers sit at the 7th percentile. If both come from the same tumor, the bulk RNA
  specimen likely has lower tumor content than KH022. The specimen ledger cannot yet confirm that.
- **Target localization.** Nuclei place SLFN11, PD-L1 and MET RNA mainly outside malignant nuclei, while ERBB3, TOP1 and
  NECTIN4 have their highest detection rates in malignant nuclei. Treat TACSTD2 nuclei detection as ambient-prone (step 2b).

## Limitations

- **One sample.** It has an undated specimen and a capture-based library with no matching public reference. Per-gene
  capture efficiency is unknown; the OncoKB lists are only a proxy for the ACE4 augmented content. Gene-specific bias
  remains even after QN.
- **Cross-platform comparison.** Salmon vs RSEM and GENCODE v23 on both sides; QN and rank methods correct only global
  monotone effects.
- **Classifiers off their home platform.** Lehmann, Severson and the Ayers weights are re-implementations or adaptations,
  not the locked published classifiers. The TCGA agreement rates above bound their accuracy.
- **Deconvolution and comparators.** EPIC lacks plasma cells and was built on non-capture RNA-seq. TCGA-TNBC is a
  primary, untreated, US-centred cohort.
- **Nothing here is an HRD call or a target-eligibility statement.**

## Suggested follow-ups (information per cost)

1. **Ask Personalis** for the RNA capture design (ACE4 RNA bait list and augmented genes) and for specimen identity and
   tumor content. That would let panel genes be corrected rather than excluded.
2. **Build a same-platform reference.** If other ImmunoID RNA samples or the vendor's normalized expression are
   available, use them instead of TCGA for per-gene percentiles.
3. **Re-run the comparisons** once step-6 malignant-nucleus pseudobulk is final. A malignant-only comparison against
   TCGA single-cell-derived references avoids the tumor-content problem entirely.
