# Integrated candidate drug targets (2026-10-04)

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

Research prioritization from Diana's data, to discuss with her oncology team. It is not a treatment recommendation.
Approval status and trial eligibility must come from the treating oncologist. Each candidate lists the
evidence layers that support it and what would confirm or refute it.

## How we got here

This list is the end of a 14-step review (2026-10-02 to 10-04). Each step had an independent spot-check (a second
tool or recount) before its result was used. Several earlier claims were overturned along the way; those corrections
matter as much as the final list. Step reports sit alongside this file.

1. **Starting point.** The prior work had three pieces:
   - Codex's careful but metadata-held scRNA diagnostics on the new KH022 delivery.
   - An EVEE (Goodfire-style) report proposing autophagy, mTOR, lipid, NRF2, Notch, FGFR4 and BET hypotheses from nine
     "tier-1" variants.
   - A July 17 summary claiming HRD 62 and biallelic BRCA1.
2. **Pipeline reliability first.**
   - The scRNA seed-stability screen compared one seed pair at a fixed resolution. It was replaced with a multi-seed,
     label-free resolution choice.
   - Public TNBC captures (GSE161529) passed retention; earlier failures came from a dead-cell-rich demo sample, not
     the pipeline.
3. **Specimen ledger (step 1).** One tumor genome runs through every assay: shared somatic BRCA1 and BRCA2 alleles
   appear in exome, WGS, RNA, Altera and both scRNA libraries. Dates, prep and the KH022 timepoint remain undocumented.
4. **Identity and material (steps 2a, 2b).** KH022 matches the patient's germline (log10 LR > 800), from one donor.
   It is **nuclei**, not whole cells: ribosomal-protein UMIs 1%, intronic about 56%, ambient RNA cytoplasmic. So
   whole-cell labels and per-nucleus TACSTD2/HLA/B2M readouts are unreliable.
5. **EVEE variants (step 3).** All nine highlighted SNVs are absent from the deep exome (0 alt reads at 172-740x),
   while the same exome reproduces Altera's variants. The EVEE hypotheses lost their genetic premise.
6. **BRCA1 function (step 4).** Tumor RNA shows ~83% aberrant splicing at the c.81-1 acceptor, against a 0.6%
   background. The variant allele dominates BRCA1 RNA.
7. **Provenance (step 7).**
   - Neither the EVEE report nor the July 17 summary has a recoverable callset; 0/18 EVEE-only variants reproduce.
   - TP53 c.559+2T>G (exome 35%), missed by both reports, is confirmed.
   - The exome is a different tissue piece than the Altera block and WGS: a subclone is missing from it.
8. **Germline (step 11).** No pathogenic or likely pathogenic variant in 29 hereditary/HR genes. BRCA1 and BRCA2 are
   confirmed somatic. Research only; CLIA confirmation is still advised.
9. **Bulk RNA (step 9).**
   - The library is capture-based (Personalis ACE4), which inflates panel genes about 3.4x and makes earlier bulk TPM
     comparisons unreliable.
   - PAM50 basal-like.
   - The piece is tumor-poor and B/plasma/macrophage-rich.
10. **Copy number (step 5).**
    - The July 22 Sequenza fit (HRD 72) failed its own self-consistency checks.
    - An independent refit, cross-checked with FACETS, the clonal-SNV VAFs, scRNA haplotypes and H&E, gives purity
      ~0.35 and ploidy ~2.8 with whole-genome doubling.
    - TP53 and BRCA1 are biallelically lost, and HRD scars are 67-99 in every plausible fit.
    - B2M is single-copy; there is no clonal HLA loss.
11. **WGS somatic (step 8, $10.33 cloud).**
    - Mutect2 + Strelka2 consensus of 16,967 calls; TMB 6.1/Mb genome-wide (~3.7 clonal).
    - Known drivers recovered; EVEE sites absent.
    - SBS3 depends on the fitting method; microhomology deletions are 60%.
12. **Tumor nuclei (step 6).** About 50% of KH022 nuclei are malignant: expression CNV and haplotype loss agree for
    ~98% of decisive nuclei, and BRCA1 mutant reads fall in malignant nuclei. TOP1 is broad; SLFN11 is low in tumor.
13. **Pathology.**
    - The computational H&E sTIL (~6%) was **wrong** and has been withdrawn.
    - HistoWiz's board-certified read: sTIL **50%** on the breast core, 10% on the axillary node; HER2 IHC 0;
      grade 3; Ki67 40-50%.
14. **Serova vaccine audit (step 12).**
    - All 22 missense antigens are reproduced in our reads.
    - The NCKAP1 SV is confirmed in DNA but has no RNA junction reads.
    - The SHANK2 "fusion" is not supported: its reads are soft-clipped normal splicing, adapters and rRNA chimeras, with
      no DNA breakpoint.
    - Antigen-processing genes are 0.3-0.6x in tumor nuclei.
15. **Targets (steps 13-14).**
    - Tumor-vs-non-tumor nuclei comparison with ambient filtering in both libraries (1,080 genes); HPA druggability.
    - Genome-wide amplicon scan: 11q13/CCND1 at ~9 copies; CD44 focal at ~12 copies.
    - OncoKB cancer-gene coding variants (20); proteomics and pathology.

**Inputs:**
- WGS consensus somatic calls (step 8)
- Allele-specific CN: purity 0.35, ploidy 2.8 (step 5)
- BRCA1 RNA splicing (step 4)
- KH022 single-nucleus tumor vs non-tumor nuclei (steps 6 and 13)
- Proteomics CP0216
- HistoWiz pathology: sTIL 50%, HER2 IHC 0, grade 3, Ki67 40-50%
- Germline (step 11)
- Bulk RNA (capture library, tumor-poor piece: used only as context)

## Tier 1: multiple independent layers agree

### A. Homologous-recombination deficiency (DNA damage response)
- **DNA:**
  - Somatic BRCA1 c.81-1G>A is on the retained haplotype after 17q LOH, so no wild-type BRCA1 is left in the main
    clone.
  - HRD scars (HRD-LOH+TAI+LST) are 67-99, >= 42 in every plausible fit.
  - 60% of larger deletions show microhomology.
  - Germline cross-check is negative, so the BRCA1 variant is somatic.
- **RNA:** ~83% aberrant splicing at the BRCA1 exon-3 acceptor (bulk RNA). **POLQ is ~4x higher in tumor than
  non-tumor nuclei** (log2FC +1.97, 23% detection).
- **Drug classes to discuss:**
  - PARP inhibitors. Labels are for germline BRCA. Trial data exist for somatic BRCA1/2, e.g. TBCRC 048 (olaparib).
  - Platinum chemotherapy (HRD/BRCA context in TNBC).
  - Investigational POLQ inhibitors, which are synthetic-lethal with HRD. The microhomology deletions are the
    polymerase-theta footprint.
- **Uncertainties:**
  - A reversion or secondary event restoring BRCA1 after therapy would change this. ctDNA or re-biopsy can
    monitor it.
  - SBS3 is fit-dependent (0.41 vs 0).

### B. TROP-2-directed ADCs (TOP1-payload)
- **Protein:** TROP-2 1,705 amol/ug in microdissected tumor (assay median 1,891); TOPO1 568 amol/ug.
- **RNA:** TOP1 is broadly expressed in tumor nuclei (62%), with no TOP1-negative subgroup. TACSTD2 itself can't be
  read in nuclei (ambient-dominated).
- **Caution:** SLFN11 is ~4x lower in tumor than non-tumor nuclei, and SLFN11 protein was not detected. Low SLFN11 is
  linked to reduced sensitivity to TOP1 inhibitors and DNA-damaging agents in preclinical and some clinical data.
  That is a hypothesis to raise, not a predictor validated for ADCs.
- **Confirmation needed:** membranous TROP-2 IHC (H-score) on current tissue.

### C. Immune-rich microenvironment (immunotherapy context)
- **Pathology:** sTIL 50% on the breast core, which is in the lymphocyte-rich range.
- **RNA:** B and plasma cells (IgA-dominant) and macrophages are prominent. CD8/cytolytic signals are mid-range in a
  tumor-poor bulk piece. CXCL12 is high, made by fibroblasts and endothelium.
- **Protein:** PD-L1 was not detected in microdissected tumor cells. That is not the clinical CPS, which includes
  immune cells.
- **To discuss:** checkpoint-inhibitor context (stage-dependent use in TNBC). PD-L1 22C3 CPS on clinical tissue is the
  standard test.

## Tier 2: genomic plus expression evidence, protein unconfirmed

| Candidate | DNA | Tumor nuclei RNA | Protein | Drug class (status) | What would confirm |
|---|---|---|---|---|---|
| **11q13 amplicon: CCND1, CTTN, PPFIA1 (+ FGF3/4/19, SHANK2)** | chr11:69.6-71.8 Mb at ~9 copies (9:0) | CCND1 31% detection, **not** tumor-enriched; CTTN/PPFIA1 tumor-enriched; FGF19 undetected; RB1 expressed (53%), 2:0 LOH, no mutation | not measured | CDK4/6 inhibitors (approved in HR+ disease; limited evidence in TNBC) | Cyclin D1 and Rb IHC; this amplicon also explains SHANK2's high expression |
| **CD44** | Focal 1.2-Mb amplicon chr11:35.1-36.3 Mb, ~12 copies (with SLC1A2, TRIM44, LDLRAD3) | 92% detection, 2.2x | not measured | CD44/CD44v6 antibodies/ADCs (earlier ADC stopped for skin toxicity) | CD44 IHC; isoform (v6) status |
| **VTCN1 / B7-H4** | 2:1 | 54% detection, 4.6x vs non-tumor, 1.7x vs normal epithelium | not measured | B7-H4 ADCs (investigational, breast trials) | B7-H4 IHC |
| **PRLR** | 1:1 | 79% detection, 4.8x | not measured | PRLR ADCs (early development) | IHC |
| **ENPP3** | 3:0 | 60%, 4x | not measured | ENPP3 ADC (early, renal) | IHC |
| **FOLH1 / PSMA** | 2:1 | 49%, 4.5x | not measured | PSMA radioligand or ADC (approved in prostate; investigational elsewhere) | PSMA IHC/PET |
| **EZH2** | 2:1 | 42%, 2.6x | not measured | EZH2 inhibitors (investigational in BRCA1-deficient TNBC models) | Functional/IHC |
| **CDK6** | 2:1 | 81%, 2.4x | not measured | CDK4/6 inhibitors | As 11q13 |

## Tier 3: hypotheses only
- **TP53 loss (c.559+2T>G on all retained copies) plus replication stress (CHEK1 2.2x, ATR):** WEE1/ATR/CHK1 inhibitors
  are investigational.
- **mTOR-axis variants** (TSC2 R59W at 17%, subclonal; MTOR P1125A failed Mutect2 strand filter): low support.
- **Serova antigens / vaccine:** see `step12-serova-vaccine/serova_audit.md`. The SHANK2 fusion is not supported;
  most missense antigens are confirmed.

## Deprioritized by the data
- HER2: IHC 0 / ISH 0.
- HER3: RNA tumor-enriched, protein not detected.
- MET, AXL, FGFR1-4, PD-L1 (tumor-cell): protein not detected.
- B7-H3, LIV-1, FRalpha, NECTIN4, MSLN: weak or not tumor-enriched.
- All EVEE-derived targets: variants absent.
- FGFR4/FGF19: FGF19 not expressed despite the 11q13 amplification.

## Most informative next tests
1. IHC on current tissue: TROP-2 (membranous), B7-H4, CD44, cyclin D1/Rb, PD-L1 CPS (22C3), and SLFN11 if available.
2. Ask whether the HRD/BRCA1 findings should be confirmed by a clinical assay (e.g. tumor BRCA testing or a clinical HRD
   score), and germline confirmation by a CLIA lab.
3. ctDNA monitoring using the somatic BRCA1/TP53 variants (tumor-informed MRD), if clinically useful.

## Files
`coding_cancer_gene_variants.json` (20 annotated variants), `amplified_segments.csv`, plus step-13 tables.
