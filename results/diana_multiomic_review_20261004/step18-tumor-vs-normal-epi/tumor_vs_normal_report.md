# Tumor cells vs Diana's own normal breast cells (step 18)

> **Correction (step 19 QC, 2026-10-05).** Genetic checks (module 2) showed that the "normal luminal" nuclei used
> here are 80-100% tumor, so every "tumor vs normal luminal" comparison in this report is invalid. That covers the
> module-score column and the PRLR/ERBB4/B7-H4/POLQ table. Only the myoepithelial comparisons stand.
> - **Casein:** tumor nuclei do transcribe κ-casein (intronic signal ~3.3x non-tumor, in 83% of tumor nuclei); the
>   mature mRNA is exported and dominates the background.
> - **CARD18** is a gene-model artifact.
> - See the [QC report](../step20-qc/QC_REPORT.md).

Diana multi-omic review · 2026-10-04 · research hypotheses for discussion with the oncology team, not treatment
recommendations. RNA is not protein.

**Data and comparisons**
- **Data:** single-nucleus RNA KH022 (two libraries; most likely the 4/10 on-treatment core; see step 17).
- **Tumor nuclei:** ~12,000 per library.
- **Comparators:**
  - her own non-malignant cells;
  - her normal luminal (duct-lining) nuclei;
  - her myoepithelial nuclei;
  - tumor cells from 8 public TNBC tumors (step 15).

## Summary

1. **There is no clean within-patient "normal duct" population for a gene-by-gene comparison.**
   - Normal luminal nuclei are ~1% of the sample (~150 per library).
   - Each is supported by only ~5 informative haplotype SNPs, with a median tumor posterior of 0.5-0.64 (clearly
     normal myoepithelium: 0.32).
   - 24-48% of their RNA is background.
   - A depth-matched per-nucleus test found 3 significant genes. That is a power limit, not evidence of similarity.
2. **Module scores still answer the subtype and immune questions.** Tumor cells are:
   - luminal-progenitor-like, not keratin-basal, mesenchymal, androgen-receptor (LAR) or mature-luminal;
   - highest for DNA repair / replication stress and cancer-testis antigens;
   - lowest for MHC class I antigen processing, with no interferon-γ response even though pembrolizumab was given 8
     days earlier.
3. **Most robust over-expressed genes are on DNA gains.**
   - **ELF5 and EHF:** the luminal-progenitor master regulators sit on a 9-copy segment next to the CD44 amplicon.
     The tumor's lineage state is therefore partly genetic, not only a pregnancy effect.
4. **Corrections to earlier reports.**
   - Casein is background RNA, not tumor expression.
   - PRLR, ERBB4, VTCN1/B7-H4 and POLQ are not higher than the normal luminal group, so they are not clearly
     tumor-selective in her breast.

## 1. Casein (milk protein): background, not expression

κ-casein (CSN3) by cell type, in counts per million:

| | Library 1 | Library 2 |
|---|---|---|
| Empty droplets (background only) | **3,790** | **5,460** |
| T/NK cells | 3,222 | 3,134 |
| Fibroblasts | 1,680 | 1,790 |
| Tumor nuclei | 1,466 | 1,499 |

- **No cell type exceeds the background level.** The highest-casein single nucleus is ~1.5% of its counts, within the
  range of T cells.
- **No milk programme:** β-casein (CSN2) and α-lactalbumin (LALBA) are ~0 everywhere. LALBA, the target of the only
  lineage vaccine in the knowledge base, is not expressed by tumor cells.

## 2. Subtype and immune-recognition modules

These are mean per-nucleus log-normalized module scores. The ranges span the two libraries.
- **Tumor** nuclei are depth-matched to the normal luminal group.
- **"Normal luminal"** may include some tumor nuclei.
- **Myoepithelium** is clearly normal.

| Module | Tumor | Normal luminal | Myoepithelial | Reading |
|---|---|---|---|---|
| Luminal progenitor | **0.70** | 0.60-0.63 | 0.48 | Luminal-progenitor-like |
| Basal / myoepithelial keratins | 0.02-0.03 | 0.03-0.04 | 0.56-0.68 | Not keratin-basal |
| Mature luminal / hormone-sensing | 0.10 | 0.13-0.52 | 0.11-0.17 | Not mature-luminal |
| EMT / mesenchymal | 0.11 | 0.12-0.13 | 0.14-0.17 | Not mesenchymal |
| Proliferation | 0.15-0.18 | 0.16-0.18 | 0.12-0.13 | Not proliferation-dominant (on-treatment sample) |
| **HR / replication stress** | **0.24-0.28** | 0.19-0.20 | 0.11 | Highest in tumor |
| **Cancer-testis antigens** | **0.056** | 0.03 | 0.009 | Highest in tumor (HORMAD1) |
| **MHC-I / antigen processing** | **0.33-0.35** | 0.40 | 0.41-0.42 | Lowest in tumor |
| **IFN-γ response** | 0.09 | 0.09-0.10 | 0.13-0.14 | Tumor not responding |
| Type-I IFN / viral mimicry | 0.06 | 0.06 | 0.10 | No STING-type signal in tumor |
| MHC-II, checkpoint ligands | similar | similar | similar | Probably background from immune cells |

**Immune-recognition state.**
- Tumor cells show the lowest antigen presentation in the sample and no interferon response, while neighbouring
  normal myoepithelial cells do respond.
- BRCA1/HRD tumors often carry a type-I interferon ("viral mimicry") signal; this one does not.
- Together with the single remaining B2M copy, this is a tumor that is poorly visible to T cells despite an
  immune-rich stroma.
- Its non-mutated cancer-testis antigens (HORMAD1, SMC1B) are potential vaccine targets.

## 3. Genes over-expressed in tumor nuclei

**Selection criteria**
- higher than all her non-malignant cells (log2FC ≥ 1.5 in both libraries);
- ≥1.75x above the normal luminal group;
- detected in ≥20% of tumor nuclei;
- not explained by background.

Copy number comes from the WGS fit (purity 0.35, ploidy 2.8). Full table: `overexpressed_candidates.csv`.

**Driven by DNA gains**

| Region | Copies (major:minor) | Genes | vs other TNBC tumor cells |
|---|---|---|---|
| chr11p13, next to CD44 | 9-12 (6:3, 10:2) | **ELF5, EHF**, CD44, **LDLRAD3** | 4-30x |
| chr11q13 amplicon | 9 (9:0) | SHANK2, PPFIA1, CTTN, KRTAP5-10 | up to ~30x |
| chr3q gain | 4 (3:1) | MECOM, ZIC1, KBTBD12, PLCH1, NAALADL2, PPM1L, SPTSSB, PPP2R3A, ATR | 3-120x |
| chr11p15 gain | 5 (3:2) | SOX6 (98% of nuclei), PLEKHA7 | 10-28x |
| chr22q12 amplicon | 8 | SPECC1L, EWSR1 | 2-4x |

**Other tumor-enriched genes, by theme**
- **Lineage and transcription factors:** SOX6, MECOM, ZIC1, ESRRG, SOX10.
- **Metabolism:**
  - SLC28A3 (nucleoside transporter, ~21x vs other TNBC);
  - KYNU (kynurenine pathway, potentially immunosuppressive);
  - XDH, ACADL, GLYATL1/2, SPTSSB.
- **Possible targets or antigens:**
  - FOLH1/PSMA (~21x vs other TNBC);
  - HORMAD1 and SMC1B (cancer-testis/meiotic);
  - CADM1, PLEKHA7.
- **Mitosis:** KIF18A, which links to the KIF18A-dependency hypothesis for whole-genome-doubled, TP53-null tumors.
- **CARD18:** the largest outlier vs other TNBC; its function in cancer is unknown.

**Not above her normal luminal cells (treat with caution)**

| Gene | Tumor vs normal luminal | Implication |
|---|---|---|
| ERBB4 | ~0.5x | Not tumor-selective |
| PRLR | ~0.9x | Not tumor-selective |
| VTCN1 (B7-H4) | ~0.9x | On-target, off-tumor risk for B7-H4 ADCs |
| POLQ | ~1.0x | Still ~4x above all non-tumor cells and ~10x above other TNBC |

All four remain far above other TNBC tumors and above her immune and stromal cells. The normal luminal group is small
and possibly mixed, so these four are unresolved. A public normal-breast reference would settle them (next step).

**Typical, not over-expressed:** TROP-2 and proliferation genes.

## 4. E-cadherin (CDH1)

- **Pathology:** positive (3/13).
- **DNA:** no germline or somatic mutation and no structural break. Chromosome 16q has lost one parent's copy (2:0),
  but the remaining copies are intact.
- **RNA:** expressed in 38% of tumor nuclei, about 0.6x her normal duct cells and similar to other TNBC.
- **N-cadherin (CDH2):** off.
- **Reading:** consistent with ductal, not lobular, carcinoma and no EMT. As with B2M, only one parental copy remains.

## Next step

Compare against public normal-breast and BRCA1-carrier preneoplastic luminal progenitors from GSE161529, the same study
as the public TNBC tumors. Apply the step 15 nuclei-vs-whole-cell correction. This would resolve ERBB4, PRLR, B7-H4 and
POLQ against a clean normal baseline.

## Files
- `overexpressed_candidates.csv`
- `module_scores.csv`
- `de_v2_tumor_vs_luminal.csv.gz`, `hallmark_ora_v2.csv`, `run2.log`
- Scripts: `de.py` (v1, background subtraction, superseded), `de2.py`
