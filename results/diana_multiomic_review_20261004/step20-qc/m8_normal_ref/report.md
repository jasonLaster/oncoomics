# Module 8: Diana's tumor nuclei vs a clean normal-breast epithelial reference

Step 19 QC · 2026-10-05 · research use only. Scripts and commands are in `README.md`; every number below comes from
`scripts/0*.py`.

## 1. Question and answer

**Question.** Module 2 showed that Diana's "normal luminal epithelium" nuclei were mostly tumor. So which candidate genes
are tumor-selective, and which are simply genes that normal breast duct cells also express?

**Answer.** Diana's malignant nuclei were compared with three normal-breast references:
- Luminal progenitors (LP), mature/hormone-sensing luminal cells (ML) and basal cells from 8 non-carrier donors (GSE161529).
- The same three lineages from 3 BRCA1 carriers.
- Her own clean normals: myoepithelium, and 79 hormone-sensing (HS) luminal nuclei in library L2.

**Verdicts across all 47 candidates**

| Verdict | Count |
|---|---|
| **PASS** (tumor-selective vs normal breast epithelium) | 16 |
| **LINEAGE** (shared with a normal lineage) | 17 |
| **BELOW** (below normal) | 8 |
| **NA** | 6 |

**Specific answers (§5)**
- **PRLR, ERBB4 (HER4) and VTCN1 (B7-H4) are normal-lineage genes.** Her own HS-luminal nuclei express each of them at
  levels equal to or above the tumor, on the same chemistry.
- **ELF5, EHF, ESRRG, MECOM and SOX6 pass.** They are 15-300x above public LP and ML, in 8/8 donors and 3/3 carriers.
  - The ESRRG, MECOM and SOX6 margins are very large; normal epithelium has essentially none of these transcripts.
  - ELF5 and EHF are normal LP-lineage genes that the tumor over-expresses (both sit on its 9-copy segment). ELF5's margin
    over her own HS luminal nuclei is only ~3.5x, and EHF's only ~2x.
- **All ten Tier A targets exceed normal luminal progenitors.** The margins are ≥2x in 8/8 donors and 3/3 BRCA1 carriers.
  - Median folds vs LP run from 5.3x (LDLRAD3) to 109x (HORMAD1).
  - **SLC6A14, SLC28A3 and LDLRAD3 are LP-lineage genes amplified up, not tumor-restricted.** Normal LP cells express
    them, with 17-24% of LP cells positive.

## 2. Reference samples and lineage annotation

**Samples.** All 8 normal samples are EpCAM-sorted total epithelium ("Epithelial"), which keeps all three lineages; none
is a single-population sort. The 4 BRCA1-carrier samples are unsorted ("Total"), the only carrier samples in GSE161529.

**Processing.** Each sample was processed separately:
- **QC:** ≥500 genes, ≥1,000 UMI, <20% MT, then scrublet doublets removed.
- **Clustering:** Leiden clustering.
- **Labels:** each cluster gets the marker module with the highest mean score.
  - Basal: KRT5, KRT14, ACTA2, TP63, KRT17, MYLK, OXTR.
  - LP: KIT, ELF5, ALDH1A3, SLPI, KRT15, MMP7, LTF, PROM1.
  - ML: ESR1, PGR, FOXA1, ANKRD30A, AREG, AR, TBX3, MSMB.
  - Five non-epithelial sets (immune, endothelial, fibroblast, pericyte, adipocyte).

**Lineages used per donor**

| Sample (GSM) | Group | Menopause / parity | Cells after QC | LP | ML | Basal |
|---|---|---|---|---|---|---|
| N-PM0095-Epi (4909256) | normal | Pre / nulliparous | 6,378 | 4,522 | 798 | 940 |
| N-N1105-Epi (4909260) | normal | Pre / nulliparous | 4,887 | 1,560 | 2,439 | 805 |
| N-MH0064-Epi (4909262) | normal | Pre / nulliparous | 3,567 | 2,144 | 1,401 | 22 (not used, <50) |
| N-N1B-Epi (4909264) | normal | Pre / parous | 1,762 | 1,013 | 548 | 124 |
| N-MH0023-Epi (4909267) | normal | Pre / parous | 2,741 | 832 | 1,450 | 337 |
| N-PM0342-Epi (4909269) | normal | Post / nulliparous | 7,455 | 1,992 | 1,392 | 3,985 |
| N-MH275-Epi (4909273) | normal | Post / parous | 5,947 | 3,147 | 2,556 | 175 |
| N-PM0372-Epi (4909275) | normal | Post / parous | 10,742 | 6,029 | 4,023 | 588 |
| B1-KCF0894 (4909277) | BRCA1 carrier | Pre / nulliparous | 7,109 | 1,711 | 339 | 1,353 |
| B1-MH0033 (4909278) | BRCA1 carrier | Pre / nulliparous | 5,888 | 1,040 | 400 | 400 |
| B1-MH0023 (4909279) | BRCA1 carrier | Post (oophorectomy) / parous | 4,920 | 919 | 1,129 | 56 |
| B1-MH0090 (4909280) | BRCA1 carrier | Post (oophorectomy) / parous | 4,946 | **excluded** | 164 | 365 |

**Label checks**
- **Marker profiles are canonical** (`tables/marker_means_by_lineage.csv`):
  - LP clusters are ALDH1A3/SLPI/KRT15/KIT-high.
  - ML clusters are ANKRD30A/AREG/FOXA1-high.
  - Basal clusters are KRT5/KRT14/ACTA2-high.
- **Not circular:** dropping every candidate gene (ELF5, KRT5, ...) from the marker sets reproduces 100% of cell labels in
  10/12 samples, and 96% and 98% in the other two (`tables/label_sensitivity.csv`).

**Exclusion.** B1-MH0090 has no LP cluster. Its "basal" cluster is ACTA2-high but KRT5/KRT14-low, which looks like
vascular smooth muscle. It is excluded, so carrier results are based on 3 donors.

**Metadata quirk.** GEO file names do not always match the patient field:
- N-PM0095 is patient 0093.
- N-MH0023-Epi is patient 0123, and B1-MH0023 is a different patient, 0023.

The patient field is used throughout.

**Diana's own clean normals** (module 2), all qc_pass, not doublets, and genetically non-malignant:

| Group | Libraries | Nuclei |
|---|---|---|
| Myoepithelial | L1, L2 | 427 + 402 |
| `epithelial_luminal_HS` | L2 | 79 |

Her HS nuclei are a genuine hormone-sensing population (`tables/lineage_marker_crosscheck.csv`):

| Marker | HS nuclei (CPM) | Tumor nuclei (CPM) |
|---|---|---|
| ESR1 | 671 | 29 |
| AR | 308 | 2.8 |
| ANKRD30A | 5,148 | 1.9 |

## 3. Methods: three tests and the verdict rule

**(A) Conservative: cross-platform, exon-only, no bias model**
- **Diana:** tumor exon CPM from module 1 (exonic UMIs / (group UMIs × library exonic fraction 0.431 / 0.438), mean of L1
  and L2), as in module 7.
- **Ambient correction.** The raw exon-only value is ambient-exposed: in the raw version PTPRC, COL1A1 and CSN3 all
  "passed". So the tumor value is ambient-corrected:
  - Corrected = raw × max(0, 1 − K·f).
  - f is module 3's ambient share of tumor counts.
  - K = 2 (sensitivity 1-3), because ambient RNA is mostly mature mRNA while nuclei are ~43% exonic.
- **Public:** pseudobulk CPM per donor and lineage. These are whole cells counted exon-only.
- **Statistic:** fold = (tumor + 1)/(normal + 1) per donor.
- **Uncertainty:** donor bootstrap 95% CI of the median.

**(B) Bias-corrected (step 15 / module 4 model)**
- Diana's tumor matrix CPM (introns counted) vs public CPM, minus `bias_hat` from module 4 (`genes_master.csv.gz`).
- P(call) integrates the bias uncertainty `bias_sd`.

**(W) Within-sample, same chemistry**
- Tumor nuclei vs her own myoepithelium (each library) and vs her own HS luminal nuclei (L2), on matrix counts.
- Every group is decontaminated with the empty-droplet ambient profile:
  - Tumor ρ = 0.12.
  - Normal epithelial ρ = 0.245, from module 3's plateau estimate, with sensitivity at 0.15 and 0.40.

**Verdict (`G11_vs_normal_breast`)**

| Verdict | Rule |
|---|---|
| **PASS** | (A) ambient-corrected tumor exon CPM ≥10 and ≥2x above both LP and ML in ≥6/8 normal donors, **and** (W) ≥2x above her own HS luminal and her own myoepithelium (both libraries) |
| **BELOW** | (A) ≥2x below the highest normal lineage, **and** (W) ≥2x below her own HS luminal nuclei |
| **NA** | Not measurable: <10 CPM in tumor and in every normal lineage, or missing from the module 1 recount |
| **LINEAGE** | Everything else. `G11_reason` says which arm failed. |

The scorecard folds are test A medians over donors.

Test B is reported but **does not decide verdicts**, for the reason given in §4.

## 4. Calibration (read before the per-gene table)

**1. Genome-wide, the bias-model test B has no demonstrable specificity for this question.**

*Setup.* The same "≥2x above ≥75% of donors" rule was applied with a query whose truth is "same lineage":
- Diana's decontaminated myoepithelium vs public basal.
- Her decontaminated HS luminal nuclei vs public ML.

*Result* (`tables/fdr_by_fold_threshold_by_floor.csv`):

| Query | Genes "called" at 2x |
|---|---|
| Myoepithelium vs public basal | 27.9% |
| HS luminal vs public ML | 25.7% |
| Tumor vs public LP and ML | 22.2% |

- The tumor rate is no higher than either same-lineage null.
- The null rate tracks the tumor rate at every threshold from 2x to 64x, at expression floors of both 10 and 50 CPM. So
  the FDR proxy is ≈1 throughout, falling only to ~0.45-0.8 at 64x.

*Why.* Nuclei-vs-cell differences, partly the intron/long-gene effect module 4 described, are as large as tumor-vs-normal
differences. The null rate is an upper bound on the method's error, because Diana's normal cells may also truly differ
from the donors (age, chemotherapy, tumor adjacency).

*Consequence.* B can rank genes but cannot certify them. This is consistent with, and harsher than, module 4's FDR of
about 0.5 at 2x against TNBC.

**2. The candidate-level null for test A is contaminated by ambient RNA.**
- Diana's myoepithelium as the query "passes" for 30 of 47 candidates raw, and for 16 even after decontamination
  (`tables/calibration_myo_vs_public_basal_candidates.csv`). Examples: ELF5, SOX6, CSN3, PTPRC.
- These are tumor and immune transcripts in a normal lineage, so they are ambient or residual contamination of the small
  normal groups (ρ ≈ 0.25 in whole-UMI space, higher on exons), not biology.
- So test A cannot be calibrated cleanly with her normals as the query.

**3. That is why the verdict requires W.**
- W uses one chemistry, one library prep and one ambient pool, so it is immune to the platform artifacts in point 1.
- Its error modes are:
  - Ambient correction. Handled with a ρ range of 0.15-0.40; the `W_pass_HS_rho_range` column agrees with `W_pass` for
    every called gene. The only exception is SLFN11, which is NA anyway.
  - Small HS counts. The 79 HS nuclei hold 198k UMIs; Poisson CIs are given in `per_gene.csv`.
- **A cleaner reference would change these calls.** A PASS would be falsified if a same-chemistry, ambient-light
  single-nucleus normal-breast reference showed the gene within 2x of LP or ML.

**4. Replicates and sensitivity.**
- Test A gives identical PASS/fail in L1-only and L2-only for all 47 genes.
- No PASS gene changes under ambient K = 1 or 3. LDLRAD3 drops to 7/8 at K = 3.
- Every PASS gene exceeds LP and ML in 3/3 BRCA1 carriers as well.

**5. Controls**

| Control | Expected | Observed | Status |
|---|---|---|---|
| KRT5, CDKN1A | BELOW | BELOW | Behave |
| CSN3, PTPRC, COL1A1 | Not PASS | Not PASS | Behave, but only because of the ambient correction and W |
| GAPDH, ACTB | Not BELOW | LINEAGE | Behave (W keeps the nuclear-loss bias from producing a "below" call) |
| MALAT1 | – | NA | Not in the module 1 exonic recount |
| **BRCA1** | Not PASS | **PASS** | **Fails as a "target" control** |

BRCA1's PASS is real RNA, but it is the patient's mutant, nuclear-retained pre-mRNA (module 1: 97% mutant). So test A
is not conservative for nuclear-retained transcripts. Any target-like gene with a very high intronic share is exposed to
the same effect; W mitigates this, but only partly, because her normal nuclei share the platform.

## 5. Specific answers

**Lineage genes**

| Gene | Verdict | Evidence |
|---|---|---|
| **PRLR** | Normal-lineage | ML gene: 53 CPM in public ML, 24% of ML cells. Tumor ≥2x above LP and ML in only 5/8 donors (2/3 carriers). **Her own HS nuclei have more PRLR than her tumor** (tumor/HS 0.59x, ρ range 0.50-0.65x). Not tumor-selective. |
| **ERBB4 (HER4)** | Normal-lineage | Test A "passes" 6/8 (exonic 41 CPM vs ML 14 CPM). But **her own HS nuclei have ~7x more ERBB4 than her tumor** (2,374 UMIs in 79 nuclei; tumor/HS 0.14x), and her myoepithelium is at tumor level (1.2x). So ERBB4 is a normal HS-luminal gene, and the cross-platform excess is a nuclei-vs-cell artifact of a 1.16 Mb, 99%-intronic gene. HER4 protein was not detected (module 5). |
| **VTCN1 (B7-H4)** | Normal-lineage | Test A 6/8 (3.0x vs ML, 11x vs LP), but **tumor/own-HS 0.51x** (66 UMIs; ρ range 0.43-0.56x). B7-H4 is a hormone-sensing luminal gene in this breast. It is above LP but not above HS luminal cells. Consistent with module 6 (highest normal-tissue expression is breast) and module 7 (not an outlier vs TNBC). |
| **ELF5** | Tumor-selective (PASS) | LP transcription factor: 4.2 CPM in normal LP (2.9% of cells) vs 423 in tumor, so 84x vs LP and 312x vs ML, 8/8 and 3/3. The within-sample margin over her HS nuclei is the smallest of the lineage genes (3.5x; 3.0-5.1x across ρ). ELF5 is a lineage program (LP identity) massively amplified (9-copy segment), not a neo-expressed gene. |
| **EHF** | Tumor-selective (PASS), borderline within-sample | Broadly expressed in normal luminal cells (54 / 50 CPM in LP / ML, 30% / 17% of cells). Tumor 15-16x above, 8/8, 3/3. But **only 2.1x above her own HS nuclei** (2.0-2.5x across ρ). Treat as an over-expressed lineage gene; a modest drop in tumor or ambient-model change would flip it to LINEAGE. |
| **ESRRG** | Tumor-selective (PASS) | 0.08 / 1.2 CPM in normal LP / ML (<1% of cells). 158x / 79x, 8/8, 3/3. 5.3x above own HS, >100x above own myo. |
| **MECOM** | Tumor-selective (PASS) | 1.8 / 0.03 CPM in normal LP / ML; 29x / 78x; >100x above own HS and myo. |
| **SOX6** | Tumor-selective (PASS) | 2.0 / 0.4 CPM in normal LP / ML; 137x / 299x; >100x above own normals. |

**ESRRG, MECOM and SOX6 caveat.** All three are 90-98% intronic long genes (span 0.58-0.77 Mb). On exons, normal whole
cells have essentially none of these transcripts, while tumor nuclei have 80-415 CPM. Whole cells should capture more
mature mRNA than nuclei, so that gap is hard to attribute to platform. The residual risk is nascent-transcript exon reads
in nuclei, the same mechanism as the BRCA1 control.

**Tier A targets vs normal luminal progenitors (test A).** All ten exceed both LP and ML in 8/8 donors and 3/3 carriers,
and pass W.

| Gene | Fold vs LP (95% donor-bootstrap CI) | Normal LP CPM (% of LP cells +) | Notes |
|---|---|---|---|
| HORMAD1 | 109x (71-121) | 0.13 (0.2%) | Absent from normal epithelium |
| ENPP3 | 46x (44-46) | 0 (0%) | Absent |
| SHANK2 | 31x (21-42) | 11 (8.5%) | Low LP expression |
| KIF18A | 27x (21-31) | 0.32 (0.2%) | Proliferation-linked |
| SPECC1L | 26x (26-43) | 10 (8.7%) | |
| POLQ | 26x (20-34) | 0.33 (0.2%) | Proliferation-linked |
| FOLH1 | 20x (9-29) | 1.7 (1.5%) | 50x vs ML |
| SLC28A3 | 9.8x (6.5-13) | 28 (18%) | **LP-lineage gene**; 48x vs ML |
| SLC6A14 | 6.2x (5.0-7.1) | 58 (24%) | **LP-lineage gene**; 38x vs ML |
| LDLRAD3 | 5.3x (4.5-6.2) | 25 (17%) | Expressed in all lineages; 4.0x vs ML; 12-copy dosage |

**Reading the Tier A table**
- **Low in normal epithelium:** HORMAD1, ENPP3, POLQ, KIF18A, FOLH1 and SHANK2 are near-absent or low.
- **Proliferation-linked:** POLQ and KIF18A. Normal resting epithelium is not a fair comparator for them; proliferating
  normal tissues are.
- **LP-lineage genes:** SLC6A14 and SLC28A3 are expressed by about a fifth of normal LP cells. Normal-LP on-target
  exposure exists, at ~6-10x lower RNA.

**Other gene notes**
- **ATR and EWSR1** pass test A, but are <2x above her own normal nuclei. They are amplified housekeeping-type genes, so
  the cross-platform fold is platform-driven. This agrees with module 3/4's "no tumor-cell enrichment" for ATR.
- **CD44, CTTN, CCND1, NECTIN4 and KYNU** are within 2x of normal LP or ML: lineage-shared.
- **TACSTD2 (TROP-2), CD276, CD274, B2M, HLA-A and PSMB9 are BELOW.** On the cross-platform test this is driven partly
  by the ambient correction; within-sample, the tumor is ≥2x below her own HS nuclei. Bias model B disagrees for B2M,
  HLA-A and PSMB9.

## 6. Per-gene table

Column guide:
- **Tumor:** ambient-corrected exon CPM.
- **Public LP / ML / basal:** median CPM over 8 normal donors (basal over 7).
- **Folds:** test A medians.
- **Donors:** donors where tumor ≥2x above both LP and ML.
- **B fold:** bias-model fold vs LP / ML.
- **W:** fold over her own decontaminated HS luminal and myoepithelium (minimum of L1 and L2).
- **Fold ≈0.00x:** the module 3 ambient share was ≥1/K, so the tumor exon signal is fully attributable to ambient under
  K = 2. These are ambient-dominated, ubiquitous genes; do not quote their test A folds, and use W instead.

| Gene | Verdict | Tumor | Public LP / ML / basal | Fold vs LP | Fold vs ML | Donors | BRCA1 carriers | B fold LP / ML | W vs own HS | W vs own myo | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CD44 | **LINEAGE** | 495 | 374 / 370 / 491 | 1.3x | 1.3x | 0/8 | 0/3 | 1.7x / 1.7x | 3.6x | 4.6x | A: within 2x of LP or ML in >25% of donors |
| VTCN1 | **LINEAGE** | 27 | 1.5 / 8.6 / 0 | 11x | 3x | 6/8 | 3/3 | 55x / 15x | 0.51x | 4x | passes A but not >=2x above own HS luminal |
| FOLH1 | **PASS** | 52 | 1.7 / 0.054 / 0 | 20x | 50x | 8/8 | 3/3 | 27x / 70x | 64x | 6.3x | A+W |
| ENPP3 | **PASS** | 45 | 0 / 0.25 / 0 | 46x | 37x | 8/8 | 3/3 | 73x / 58x | >100x | 39x | A+W |
| PRLR | **LINEAGE** | 128 | 13 / 53 / 1.4 | 9.3x | 2.4x | 5/8 | 2/3 | 5x / 1.3x | 0.59x | 5.3x | A: within 2x of LP or ML in >25% of donors |
| ERBB4 | **LINEAGE** | 41 | 0.64 / 14 / 0.39 | 26x | 2.7x | 6/8 | 2/3 | 85x / 9x | 0.14x | 1.2x | passes A but not >=2x above own HS luminal and own myoepithelium |
| SLC28A3 | **PASS** | 277 | 28 / 4.8 / 2.6 | 9.8x | 48x | 8/8 | 3/3 | 5.8x / 28x | 83x | 17x | A+W |
| SLC6A14 | **PASS** | 362 | 58 / 9.1 / 4.3 | 6.2x | 38x | 8/8 | 3/3 | 9.2x / 57x | >100x | 4.6x | A+W |
| HORMAD1 | **PASS** | 122 | 0.13 / 0 / 0 | 109x | 123x | 8/8 | 3/3 | 105x / 119x | >100x | 62x | A+W |
| ATR | **LINEAGE** | 180 | 13 / 12 / 8.3 | 13x | 14x | 8/8 | 3/3 | 3.9x / 4.2x | 1.5x | 1.6x | passes A but not >=2x above own HS luminal and own myoepithelium |
| POLQ | **PASS** | 33 | 0.33 / 0 / 0 | 26x | 34x | 8/8 | 3/3 | 19x / 26x | 93x | 6.1x | A+W |
| KIF18A | **PASS** | 35 | 0.32 / 0.3 / 0 | 27x | 28x | 8/8 | 3/3 | 20x / 20x | 18x | 12x | A+W |
| TACSTD2 | **BELOW** | 0 | 1450 / 2157 / 973 | 0.00069x | 0.00047x | 0/8 | 0/3 | 0.44x / 0.3x | 0.3x | 0.26x | A and own-HS both >=2x below |
| TOP1 | **LINEAGE** | 100 | 149 / 222 / 263 | 0.67x | 0.45x | 0/8 | 0/3 | 0.78x / 0.52x | 1.5x | 1.1x | below public normals on A but not >=2x below own HS luminal |
| SLFN11 | **NA** | 2.5 | 0 / 0.26 / 0 | 3.5x | 2.8x | 7/8 | 1/3 | 5.4x / 4.3x | 5.6x | 0.82x | <10 CPM in tumor (ambient-corrected exon) and all normal lineages |
| NECTIN4 | **LINEAGE** | 63 | 19 / 52 / 2 | 3.1x | 1.2x | 0/8 | 0/3 | 3.5x / 1.4x | 1.2x | 1.6x | A: within 2x of LP or ML in >25% of donors |
| EGFR | **LINEAGE** | 21 | 58 / 11 / 71 | 0.37x | 1.8x | 0/8 | 0/3 | 0.66x / 3.2x | 2x | 0.22x | below public normals on A but not >=2x below own HS luminal |
| CD276 | **BELOW** | 1.6 | 12 / 22 / 8 | 0.2x | 0.12x | 0/8 | 0/3 | 0.76x / 0.44x | 0.49x | 1.6x | A and own-HS both >=2x below |
| SHANK2 | **PASS** | 354 | 11 / 14 / 2.6 | 31x | 24x | 8/8 | 3/3 | 14x / 11x | 6.5x | >100x | A+W |
| CCND1 | **LINEAGE** | 58 | 117 / 130 / 40 | 0.51x | 0.45x | 0/8 | 0/3 | 1.3x / 1.1x | 2.1x | 1.9x | below public normals on A but not >=2x below own HS luminal |
| CTTN | **LINEAGE** | 356 | 165 / 181 / 98 | 2.2x | 2x | 3/8 | 2/3 | 1.8x / 1.6x | 6.2x | 3.6x | A: within 2x of LP or ML in >25% of donors |
| EWSR1 | **LINEAGE** | 508 | 91 / 78 / 114 | 5.6x | 6.4x | 8/8 | 3/3 | 5.1x / 5.8x | 2x | 4.3x | passes A but not >=2x above own HS luminal |
| SPECC1L | **PASS** | 300 | 10 / 13 / 11 | 26x | 22x | 8/8 | 3/3 | 19x / 16x | 4x | 6.1x | A+W |
| LDLRAD3 | **PASS** | 137 | 25 / 34 / 15 | 5.3x | 4x | 8/8 | 3/3 | 17x / 12x | 7.2x | 19x | A+W |
| ELF5 | **PASS** | 423 | 4.2 / 0.36 / 0.16 | 84x | 312x | 8/8 | 3/3 | 85x / 315x | 3.5x | 23x | A+W |
| EHF | **PASS** | 836 | 54 / 50 / 3.7 | 15x | 16x | 8/8 | 3/3 | 16x / 17x | 2.1x | 8.6x | A+W |
| ESRRG | **PASS** | 169 | 0.08 / 1.2 / 0.48 | 158x | 79x | 8/8 | 3/3 | 184x / 93x | 5.3x | >100x | A+W |
| MECOM | **PASS** | 80 | 1.8 / 0.032 / 0 | 29x | 78x | 8/8 | 3/3 | 26x / 70x | >100x | >100x | A+W |
| SOX6 | **PASS** | 415 | 2 / 0.4 / 0 | 137x | 299x | 8/8 | 3/3 | 41x / 90x | >100x | >100x | A+W |
| CARD18 | **NA** | 1.7 | 0 / 0 / 0 | 2.7x | 2.7x | 8/8 | 3/3 | 785x / 785x | >100x | 66x | <10 CPM in tumor (ambient-corrected exon) and all normal lineages |
| KYNU | **LINEAGE** | 106 | 40 / 103 / 1.8 | 2.6x | 1x | 3/8 | 3/3 | 4.2x / 1.7x | 7.7x | >100x | A: within 2x of LP or ML in >25% of donors |
| B2M | **BELOW** | 0 | 2238 / 2437 / 1167 | 0.00045x | 0.00041x | 0/8 | 0/3 | 1.6x / 1.5x | 0.065x | 0.066x | A and own-HS both >=2x below (bias model B disagrees) |
| HLA-A | **BELOW** | 0 | 400 / 397 / 468 | 0.0025x | 0.0025x | 0/8 | 0/3 | 1.4x / 1.4x | 0.076x | 0.13x | A and own-HS both >=2x below (bias model B disagrees) |
| TAP1 | **LINEAGE** | 0 | 28 / 33 / 25 | 0.035x | 0.03x | 0/8 | 0/3 | 0.52x / 0.44x | 0.81x | 0.27x | below public normals on A but not >=2x below own HS luminal |
| PSMB9 | **BELOW** | 0 | 15 / 26 / 5.3 | 0.062x | 0.038x | 0/8 | 0/3 | 1.1x / 0.66x | 0.18x | 0.21x | A and own-HS both >=2x below (bias model B disagrees) |
| NLRC5 | **NA** | 2.2 | 5 / 4.6 / 0.48 | 0.53x | 0.57x | 0/8 | 0/3 | 0.52x / 0.56x | 0.36x | 0.23x | <10 CPM in tumor (ambient-corrected exon) and all normal lineages |
| CD274 | **BELOW** | 0.17 | 3 / 8.9 / 9.4 | 0.29x | 0.12x | 0/8 | 0/3 | 0.56x / 0.23x | 0.27x | 0.13x | A and own-HS both >=2x below |
| CSN3 | **LINEAGE** | 52 | 6.9 / 0.37 / 0 | 8.5x | 40x | 7/8 | 2/3 | 624x / 2909x | 6.9x | 0.86x | passes A but not >=2x above own myoepithelium |
| KRT5 | **BELOW** | 0 | 119 / 9.3 / 1406 | 0.0084x | 0.1x | 0/8 | 0/3 | 0.05x / 0.59x | 0.19x | 0.014x | A and own-HS both >=2x below |
| PTPRC | **NA** | 0 | 0 / 0 / 0 | 1x | 1x | 0/8 | 0/3 | 4.1x / 4.1x | 0.025x | 0.052x | <10 CPM in tumor (ambient-corrected exon) and all normal lineages |
| COL1A1 | **NA** | 0 | 1 / 4.9 / 2.7 | 0.49x | 0.17x | 0/8 | 0/3 | 7.5x / 2.6x | 1x | 0.049x | <10 CPM in tumor (ambient-corrected exon) and all normal lineages |
| GAPDH | **LINEAGE** | 0 | 1780 / 1086 / 1524 | 0.00056x | 0.00092x | 0/8 | 0/3 | 0.48x / 0.8x | 0.71x | 0.32x | below public normals on A but not >=2x below own HS luminal |
| ACTB | **LINEAGE** | 0 | 4866 / 6727 / 3294 | 0.00021x | 0.00015x | 0/8 | 0/3 | 0.4x / 0.29x | 0.63x | 0.13x | below public normals on A but not >=2x below own HS luminal |
| MALAT1 | NA | – | – | – | – | – | – | – | – | – | not in m1 exonic recount |
| BRCA1 | **PASS** | 31 | 2.2 / 3.6 / 0.67 | 10x | 6.9x | 8/8 | 3/3 | 4.9x / 3.4x | 2.5x | 15x | A+W |
| TP53 | **LINEAGE** | 39 | 36 / 27 / 23 | 1.1x | 1.4x | 0/8 | 1/3 | 1.2x / 1.5x | 1.7x | 1.7x | A: within 2x of LP or ML in >25% of donors |
| CDKN1A | **BELOW** | 0 | 53 / 80 / 193 | 0.018x | 0.012x | 0/8 | 0/3 | 0.084x / 0.056x | 0.06x | 0.099x | A and own-HS both >=2x below |

## 7. Caveats

- **Whole cells vs nuclei.** Public cells hold cytoplasmic mRNA; Diana's nuclei mostly hold nuclear and nascent RNA. Test
  A is conservative for stable cytoplasmic transcripts but **not** for nuclear-retained or nascent transcripts (BRCA1
  control, §4). Test B's correction does not remove the platform gap genome-wide (§4).
- **Chemistry.** The public data are older 10x 3' with Cell Ranger 3.0 and exon-only counting. Diana's are GEM-X 3' v4
  with Cell Ranger 10.1 and introns counted. The gene models differ slightly; for example, CARD18's 2024-A 5' extension
  does not exist in the public annotation.
- **Ambient.** Diana's sample is ambient-heavy (module 3). Her small normal groups carry about 25% ambient that is
  tumor-dominated, which compresses W toward 1 for tumor genes. So W is conservative for genuine tumor genes, but the
  decontamination is a model. CellBender (module 3, pending) is the independent check.
- **Exon-space correction.** The ambient correction for test A uses module 3's matrix-space ambient share times K = 2.
  For ubiquitous genes (GAPDH, B2M, TACSTD2) it removes the whole tumor signal, which is an over-correction for those
  genes.
- **Donor variation.** The normal donors span pre/post-menopause and parity, and ML expression of hormone-responsive genes
  (PRLR, AREG) varies several-fold between donors. With 8 donors, "≥6/8" is a coarse quantile; donor-bootstrap CIs are in
  `per_gene.csv`.
- **Diana's comparators.** She is a single, post-chemotherapy, tumor-adjacent sample. Her HS and myo nuclei are the only
  same-chemistry comparator, and she has no LP-like normal population, so tumor vs her own LP cannot be tested.
- **BRCA1 carriers vs non-carriers.** The carrier samples are unsorted total tissue: fewer epithelial cells and more
  stroma. One carrier had no usable epithelium. Carrier donors gave the same PASS set (3/3 for every PASS gene).
- **RNA, not protein.** RNA ≥2x above normal LP is not the same as a therapeutic window. Surface protein density in
  normal duct cells is not measured here.

## 8. What would falsify these conclusions

- **PASS calls (ESRRG, MECOM, SOX6, HORMAD1, ENPP3, POLQ, KIF18A, FOLH1, SHANK2, SPECC1L).** A normal-breast single-nucleus
  dataset on matching chemistry and counting showing the gene within 2x of LP or ML would falsify the PASS.
- **ELF5 and EHF.** A drop below 2x vs her own HS nuclei under an independent ambient estimate (e.g. CellBender) would flip
  them to LINEAGE.
- **PRLR, VTCN1 and ERBB4 as LINEAGE.** These rest on 79 HS nuclei from one library. Evidence that those nuclei are
  tumor-contaminated would undo them; module 2 estimates 0% tumor (CI 0-18%), and ESR1/AR/ANKRD30A are high and tumor-low.
  Higher tumor than HS-luminal protein for B7-H4 or PRLR by IHC would also contradict them.
