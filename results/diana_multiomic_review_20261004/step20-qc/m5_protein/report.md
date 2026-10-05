# QC module 5: protein vs single-nucleus RNA concordance

**Inputs**
- **Protein:** OncoOmicsDx targeted mass-spectrometry panel (CP0216). Laser-microdissected tumor area from the 4/10
  Stanford core, FFPE block A1, in amol/µg. ND means below the limit of quantitation (LOQ). Values were transcribed from
  the report PDF (`protein_vs_rna.py` holds the table).
- **RNA:** KH022 single-nucleus pseudobulk from step 13 (mean of the two libraries). The groups are malignant nuclei,
  non-malignant nuclei and normal epithelium.
- **Specimen match:** same biopsy event (4/10), different pieces (FFPE block vs frozen vial).
- **Coverage:** 66 proteins mapped to genes; 26 detected, 40 ND.

## Results

| Test | Result | Reading |
|---|---|---|
| Tumor RNA for detected vs ND proteins | median 65.5 vs 5.9 CPM; Mann-Whitney p = 4×10⁻⁵ | **Presence/absence agrees.** Proteins the assay finds are expressed at the RNA level, and absent proteins mostly have little RNA. |
| Spearman, protein level vs tumor-nucleus RNA (26 detected) | ρ = 0.17 (p = 0.40) | **Levels do not track tumor RNA.** |
| Spearman, protein level vs non-malignant-nucleus RNA | ρ = 0.43 (p = 0.03) | The microdissected protein sample carries a stromal and immune contribution. |
| Spearman, protein level vs normal-epithelium RNA | ρ = 0.29 (p = 0.15) | |

## Discordances that matter for target claims

**1. Detected protein, but most of its RNA is in non-tumor cells.** The share of RNA from tumor nuclei is below 0.5 for
these:
- Vimentin, Cav-1 and GPNMB (tumor share 0.09-0.26). These are stromal.
- TYMP (0.15) and hENT1 (0.23). The vendor's "likely benefit" calls for capecitabine and gemcitabine rest on these.
- TROP-2 (0.30), but its single-nucleus RNA is 74% ambient, so the tumor share cannot be measured. Membrane IHC remains
  the decisive test.
- EGFR (0.39).

Reading: protein readouts from a microdissected area are not tumor-cell-pure. For any protein whose RNA is mainly
stromal, the reported level may reflect the stroma.

**2. Not detected as protein despite high tumor RNA.**

| Protein | LOQ (amol/µg) | Tumor RNA CPM | % tumor nuclei | Interpretation |
|---|---|---|---|---|
| **HER4 (ERBB4)** | 125 | **1,992** | 95% | Major discordance (see below). |
| FGFR2 | 1,000 | 418 | 74% | The LOQ is high, so this is compatible with low-moderate protein. |
| IGF1R | n/a | 387 | 75% | Gene spans ~315 kb. |
| HER3 (ERBB3) | n/a | 129 | 48% | |

**Why ERBB4 is the major discordance**
- The gene spans 1.16 Mb.
- Single-nucleus counts include intronic reads, which inflate long genes relative to their mature mRNA.
- The public TNBC comparator is exon-only whole cells.
- So part or all of ERBB4's "~77x vs other TNBC" may be a gene-length artifact. Other very long outliers carry the
  same risk: ESRRG, SOX6, NAALADL2, MECOM, PLCH1, FMNL2, CADM1.
- **Follow-up:** module 1 is computing exonic-only counts, and module 4 is testing whether the outlier list is enriched
  for long genes.

## What this module establishes
- **Assay agreement:** RNA presence/absence calls agree with an orthogonal protein assay on the same biopsy event.
- **Quantification:** RNA levels in tumor nuclei are not a reliable proxy for protein abundance. Rank-based "high vs
  low" target claims need protein confirmation (IHC on tumor cells specifically).
- **Long-gene flag:** every long-gene outlier needs an exon-only re-check before it is presented as over-expressed.

**Caveats**
- n = 26 detected proteins.
- Different pieces of tissue.
- The vendor's LOQ varies 75-1,000 amol/µg by protein.
- Housekeeping-like abundant proteins (HSP90, vimentin) depend on cytoplasmic mRNA that nuclei under-sample.

Files: `protein_vs_rna.csv`, `protein_vs_rna.py`, `run.log`.
