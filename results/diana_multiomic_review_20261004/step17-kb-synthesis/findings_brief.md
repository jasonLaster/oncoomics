# Verified omics findings to connect against the knowledge base (as of 2026-10-04)

All research-grade. Each item was spot-checked; uncertain items are marked.

**Tumor identity and state**
- TNBC, invasive ductal, grade 3, Ki67 40-50%, ER/PR negative, **HER2 IHC 0 / ISH 0** (HistoWiz).
- Specimen dates are muddled: proteomics specimen SP-26-027487 is listed as collected 3/13 (Sutter), but HistoWiz dates
  SP-26-027487 to 4/10 (Stanford). The axillary node core SP-26-22231 is dated 3/23.
- **Purity ~0.35, ploidy ~2.8, likely whole-genome doubling** (WGS allele-specific CN; agrees with FACETS, Serova
  ASCAT 0.37, H&E).
- **TP53 c.559+2T>G** splice donor: truncal, on every retained copy (17p LOH); missed by the July 17 and EVEE reports.
- **BRCA1 c.81-1G>A** somatic (germline negative), biallelic via 17q LOH. ~83% aberrant exon-3 acceptor splicing
  (dominant +7-nt cryptic acceptor, plus exon-3 skipping) in tumor RNA; 97% mutant pre-mRNA in malignant nuclei.
- **HRD scars 67-99** in every plausible fit (>=42); 60% of larger deletions show microhomology; SBS3 depends on the
  fitting method (0.41 vs 0).
- **POLQ ~4x higher in tumor nuclei** than non-tumor nuclei, and ~10x above other TNBC tumor cells.
- **WGS consensus:** 16,967 somatic calls; TMB 6.1/Mb genome-wide (~3.7 clonal); 511 SVs (163 tandem duplications).
- **Amplicons:**
  - **11q13 (~9 copies:** CCND1, CTTN, PPFIA1, SHANK2, FGF3/4/19 region; CCND1 RNA not over-expressed).
  - **chr22q12 (8-10 copies:** EWSR1, SPECC1L, DEPDC5...).
  - **CD44 focal amplicon chr11p13 (~12 copies,** with SLC1A2, TRIM44, LDLRAD3).
- **B2M single copy (1:0)**, 30.6-Mb chr15 deletion; no clonal HLA haplotype loss (HLA-A least certain).
- Other confirmed somatic variants: BRCA2 S2695L (VUS, 15%), MTOR P1125A (9.5%), TSC2 R59W (10.7%), PIKFYVE I1548T
  (9%), PTPN23 P981A.
- **Tissue heterogeneity:** a ~10% subclone present in the Altera block and WGS is absent from the Personalis exome/RNA
  piece. Different pieces were sampled.

**Single-nucleus RNA (KH022, undated specimen, nuclei)**
- ~50% malignant nuclei.
- **Tumor cells are luminal-progenitor-like rather than keratin-basal:**
  - KRT5 ~30x and KRT17 ~85x LOWER than other TNBC tumor cells.
  - High ERBB4, PRLR, ELF5, EHF, ESRRG, MECOM.
  - PAM50 basal-like, Lehmann subtype indeterminate.
- **TOP1** broadly expressed; **SLFN11 low** in tumor (~4-10x below stroma/immune); SLFN11 protein not detected.
- **Antigen processing genes (TAP1/2, PSMB8/9, NLRC5, IRF1, ERAP2) 0.3-0.6x** of normal breast epithelium in tumor
  cells; JAK/STAT intact.
- **Genes high vs other TNBC tumor cells:**
  - CD44
  - SLC28A3 (CNT3 nucleoside transporter, ~21x)
  - ATR (~5x)
  - HORMAD1 (cancer-testis antigen, ~27x)
  - SLC6A14 (~34x)
  - ERBB4
  - ENPP3
  - FOLH1/PSMA
  - VTCN1/B7-H4
  - PRLR
- **Typical for TNBC (not outliers):** TROP-2, TOP1, NECTIN4, EGFR, B7-H3.

**Microenvironment**
- **HistoWiz pathologist:** stromal TILs ~50% (breast core), ~10% (axillary node).
- **Infiltrate composition:**
  - Rich in B and plasma cells, IgA-dominant (Ig = 22.6% of bulk TPM) and macrophages.
  - CXCL12 high (~90th percentile), made by fibroblasts and endothelium.
  - CD8/cytolytic mid-range in a tumor-poor bulk piece.
- **PD-L1:** protein not detected in microdissected tumor cells (not a CPS); PD-L1 RNA mostly in macrophages.

**Proteomics (CP0216, microdissected tumor)**
- **TROP2 1,705 amol/ug** (assay median 1,891).
- TOPO1 568; EGFR 171; FRalpha 697; hENT1 174; TYMP 960; **MGMT 1,281** (high, "unlikely benefit" temozolomide).
- Not detected: ERCC1, RRM1, TUBB3, HER2, HER3, MET, AXL, FGFR1-4, PD-L1, AR, TOPO2A.
- p16 expressed.

**Vaccine (Serova SRV-DL-T0)**
- 22 missense antigens reproduce in our reads.
- **SHANK2 fusion window not supported** (artifact).
- **NCKAP1 SV** confirmed in DNA, no RNA junction.
- TP53/BRCA1 splice drivers not encoded.

**Discredited**
- EVEE report: none of its 9 tier-1 variants exist.
- "HRD 62" untraceable; Sequenza "HRD 72" from a broken fit.
- Bulk RNA is a capture library (ACE4) from a tumor-poor piece; gene-level comparisons with TCGA are unreliable.
