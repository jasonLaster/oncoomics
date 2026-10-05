# Tumor-cell-enriched, potentially druggable targets from single-nucleus RNA (2026-10-04)

Research prioritization only. It is not a treatment recommendation; any target needs protein confirmation (IHC)
and oncologist review. KH022 is an undated specimen, possibly taken at a different time than the March FFPE block.

## Method
- KH022, two libraries analysed separately: ~12.8k malignant vs ~11k non-malignant nuclei each (QC-pass, doublets
  removed; malignant calls from step 6).
- Malignant vs non-malignant nuclei and vs normal epithelial/myoepithelial nuclei; pseudobulk CPM.
- Ambient-RNA share was estimated from empty droplets (rho 0.145). Genes were kept if, in **both** libraries:
  - malignant CPM >= 20;
  - detected in >= 10% of malignant nuclei;
  - log2FC vs non-malignant >= 1;
  - ambient share <= 30%.
- This left 1,080 genes (`tumor_enriched_genes.csv`). Annotation: Human Protein Atlas (protein class, membrane,
  FDA-approved drug targets, normal-tissue specificity), step-5 allele-specific copy number at the locus, and the
  CP0216 proteomics panel.
- **Caveats:**
  - Nuclei over-count long intron-rich genes, so rank by fold change and detection, not raw CPM.
  - Nuclear RNA is not protein or surface abundance.
  - Single-exon and secreted genes are ambient-prone (e.g. TACSTD2).
  - The comparison with normal epithelium uses small groups (594 and 1,500 nuclei).

## 1. Established ADC/antibody antigens (`adc_antigen_panel.csv`)

| Antigen | Tumor nuclei detection | log2FC vs non-malignant | vs normal epithelium | CN (major:minor) | Protein (CP0216) | Note |
|---|---|---|---|---|---|---|
| **VTCN1 (B7-H4)** | 54% | +2.2 | +0.75 | 2:1 | not measured | Several investigational B7-H4 ADCs in breast/gynecologic trials; normal breast/fallopian tube expression |
| **ERBB4 (HER4)** | 95% | +2.3 | +0.2 | 2:1 | not measured | Lineage gene; no approved HER4-directed drug |
| **PRLR** | 79% | +2.3 | +0.7 | 1:1 | not measured | PRLR ADCs have been in early development |
| **FOLH1 (PSMA)** | 49% | +2.2 | +1.3 | 2:1 | not measured | PSMA-directed agents exist (prostate); breast tumor-cell expression would need IHC/PSMA imaging to matter |
| **FGFR2** | 74% | +2.1 | +0.3 | 3:0 | FGFR1-4 not detected | Expressed, not amplified; protein ND |
| **ENPP3** | 60% | +2.0 | +0.7 | 3:0 | not measured | ENPP3 ADCs in early development (renal) |
| **CD44** | 92% | +1.1 | +1.0 | **10:2 (~12 copies, focal 1.2-Mb amplicon chr11:35.1-36.3 Mb)** | not measured | DNA and RNA concordant; earlier CD44v6 ADC (bivatuzumab) stopped for skin toxicity |
| ERBB3 (HER3) | 48% | +1.1 | +0.3 | 1:1 | **HER3 not detected** | RNA tumor-enriched but protein ND |
| NECTIN4 | 26% | +0.7 | -0.2 | 3:2 | not measured | Modest |
| PTK7 | 42% | +0.9 | 0.0 | 3:2 | not measured | Modest |
| TACSTD2 (TROP-2) | n/a | n/a | n/a | 3:1 | **1,705 amol/ug (present)** | Ambient-dominated in nuclei, so the RNA can't be judged; protein is the evidence |
| EGFR | 44% | -0.6 | -1.4 | 2:0 | 171 amol/ug | Higher in stroma/normal epithelium |
| FOLR1 | 6% | -1.2 | -1.5 | 3:1 | 697 amol/ug | Nuclear RNA low/ambient |
| ERBB2, MET, CD276 (B7-H3), SLC39A6 (LIV-1), MUC1, MSLN, ROR1, GPNMB, AXL, F3, CLDN6/18, DLL3, CD70, CD274 | low or not tumor-enriched | | | | HER2, MET, AXL, PD-L1 ND | |

## 2. Other tumor-enriched genes with FDA-approved drugs against the protein (HPA class), both libraries
- **CDK6:** 81% of tumor nuclei, +1.3 (CDK4/6 inhibitors exist; context-dependent in TNBC).
- **EZH2:** +1.4; **RRM2:** +1.3; **POLA1:** +1.3. These are proliferation/replication enzymes.
- **PDE4B** and **PDE5A**: lineage/long genes; weak cancer rationale.
- Many neuronal/ion-channel genes (ESRRG, KCNK2, SCN1A, MAP2, CACNB2, CHRM3) are tumor-lineage or long-gene
  signals without an oncology rationale. They are listed in `tumor_enriched_genes.csv` but not prioritized.

## 3. How this fits the other layers
- **Strongest multi-layer TROP-2 story:** protein present (pre-treatment block) and TOP1 broadly expressed in tumor
  nuclei. SLFN11 is low in tumor nuclei. These are the payload-context genes for TOP1-payload ADCs.
- **New candidates to check at protein level (IHC):** B7-H4 (VTCN1), PRLR, ENPP3, PSMA (FOLH1), and CD44 (focal
  amplification + expression).
- **HRD-high, BRCA1/TP53 biallelic loss (steps 4/5/8):** DNA-repair-directed therapy context is genomic, not
  expression-based.

## Files
`tumor_enriched_genes.csv`, `all_genes_tumor_vs_other.csv.gz`, `adc_antigen_panel.csv`,
`scripts/01_tumor_enriched_targets.py`.
