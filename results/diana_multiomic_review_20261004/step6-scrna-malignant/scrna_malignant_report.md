# KH022 single-nucleus RNA: malignant nuclei and target readouts (step 6, private)

Research prioritization only; no clinical or treatment claims. Private, git-ignored. Run 2026-10-03.
Libraries KH022-1 (L1, 38,994 barcodes) and KH022-1-1 (L2, 37,805) were analysed separately and never merged. Every
headline number is given as L1 / L2. Nuclei are the unit of measurement, not independent replicates. All statistics
are descriptive. KH022's timepoint relative to treatment is unknown, so every finding is KH022-specific and is not a
statement about the March FFPE block.

## 1. Summary

- **Malignant nuclei are clearly identifiable from two independent genetic signals that agree.**
  - The expression CNV profile is nearly identical between libraries: the consensus profiles correlate at r = 0.9985.
  - Germline haplotype imbalance on chr17, 13q, 9p and 9q is phased in the other library. Its phase agrees with tumor
    WGS allele direction at 17/17 and 15/15 sites (|AF-0.5| >= 0.1).
  - In nuclei where both calls are decisive, CNV and haplotype calls agree for **97.9% / 98.1%** (n = 6,871 / 6,772).
  - The BRCA1 c.81-1G>A allele is seen in 46 / 52 nuclei: 48 / 52 alt molecules against 0 / 3 ref. Of the nuclei
    carrying any somatic-alt molecule, 57/64 and 56/61 are CNV-malignant.
- **Malignant fraction** (QC-pass, nuclei flagged by either doublet method removed): **50.4% / 51.2%**, with an upper
  bound of 55.9% / 56.3% if unresolved nuclei are counted as malignant. Keeping doublet-flagged nuclei gives
  56.3% / 57.1%.
  - Among non-malignant nuclei: T/NK about 28%, fibroblast 18-19%, myeloid 11%, B 8%, endothelial 6-9%, adipocyte 7%,
    plasma 4%, myoepithelial 4%.
- **The WGS check is only partly confirmatory.**
  - Arm-level scRNA CNV against tumor WGS coverage log2: Pearson r 0.35 / 0.35 (p 0.04 / 0.03), Spearman 0.46 / 0.49.
  - Controlling for gene density, partial r is 0.52 / 0.53 (p < 0.001).
  - The WGS coverage bins correlate with gene density at r = -0.74, so they carry a GC-like bias. The "losses" on
    17, 19, 22 and 16 are GC-rich chromosomes and are not seen in expression.
  - Concordant: gains on 3q, 1q, 11p and 10p; losses on 15q and 7p.
  - Discordant: 22q (scRNA gain, WGS loss).
  - chr17, the arm with the highest WGS allelic imbalance, shows near-zero expression CNV but complete-looking
    haplotype loss in malignant nuclei. That is compatible with copy-neutral LOH of 17. This needs the allele-specific
    CN fit, which had no final output in step5-ascn at writing time.
- **Readouts in malignant nuclei.**
  - Interpretable (nuclei-robust, ambient share <= 20%):
    - TOP1 is broadly detected: 62% raw, 26% at 1,500 UMIs. Its O/E is 0.88-0.99 in every malignant subcluster, so no
      TOP1-null subpopulation is detectable.
    - EGFR, BRCA1, ERBB3, PTK7 and NECTIN4 are interpretable.
  - SLFN11 RNA is low in malignant nuclei: about 4.5 ambient-corrected CPM, against 40-62 in T/NK, myeloid and
    fibroblast nuclei of the same library. That agrees with SLFN11 protein not detected in bulk, but timepoints differ.
  - TACSTD2 (single-exon) is ambient-dominated:
    - 71% of its UMIs in malignant nuclei are expected from ambient.
    - Observed detection is 32-33%, against 24-25% expected from ambient alone.
    - Its presence, absence and heterogeneity cannot be measured per nucleus here.
  - Ambient-dominated, not interpretable: FOLR1, F3, HLA class I, B2M, and the T-cell/checkpoint genes inside
    malignant nuclei.

## 2. QC decisions (task 1)

All barcodes are kept in `barcode_annotations_<lib>.csv.gz` with their flags. Thresholds are derived from the data.

| flag | rule | L1 | L2 |
|---|---|---:|---:|
| low UMI | log10 UMI < median - 3 MAD (floor 234 / 189 UMIs; the Cell Ranger minimum, 553 / 489, already sits above it) | 0 | 0 |
| low genes | log10 genes < median - 3 MAD | 1 | 0 |
| cytoplasmic contamination | residual of log(MT%+RP%) on log(UMI) (Huber fit) > median + 3 MAD | 1,574 | 1,307 |
| (naive MT+RP MAD rule, for comparison) | MT+RP > 6.4 / 6.7% | 2,387 | 2,090 |
| debris | MT > 20% (debris cluster from step 2b) | 266 | 218 |
| high ambient | residual of log(% UMIs in soup-enriched genes) on log(UMI) > median + 3 MAD | 830 | 892 |
| low intronic (reported only) | chr1-subset intronic fraction < 0.30 with >= 40 UMIs | 307 | 341 |
| **qc_pass** | none of rows 1-4 or 6 (the low-intronic flag is reported only) | **36,946 (94.7%)** | **35,946 (95.1%)** |

- **Why the contamination flags are depth-aware.**
  - log(MT+RP share) and log(soup-gene share) fall with log(UMI) at slopes of -0.58 / -0.55 and -0.63 / -0.61. That
    is close to the -1 limit expected if every droplet carried a constant amount of ambient RNA.
  - A flat MAD rule would therefore mostly flag small nuclei, such as T-cell nuclei at a median of 1,200 UMIs, rather
    than contaminated ones.
- **Ambient profile.** Built from non-called barcodes with 1-99 UMIs (2.00M / 2.05M barcodes). Called barcodes hold
  73.2% / 70.9% of UMIs.
  - Soup-enriched genes (ambient/cell >= 3) include TACSTD2, EPCAM (L2), HLA-A/B/C, B2M, CD74, IGKC, JCHAIN, CSN3,
    SCGB3A1, LTF, ACTB, EEF1A1 and CLDN4.
  - These genes, and anything with ambient/cell >= 2, were excluded from HVG selection and from CNV inference.
- **Ambient correction.** Contamination fraction rho is estimated per group from "foreign" soup genes: immunoglobulin
  transcripts for epithelial groups, epithelial secretory transcripts (CSN3, SCGB3A1, LTF, ...) for stromal and immune
  groups.
  - Malignant: 0.145 / 0.139. The SoupX global estimate was 0.121.
  - Fibroblast 0.35, endothelial 0.37-0.39, myeloid 0.36-0.39, plasma 0.45-0.48.
  - T/NK and B: 0.60-0.67, capped at 0.5 when applied.
  - An independent, expression-free check: non-malignant nuclei carry 58-66% tumor-haplotype molecules instead of
    50%. That implies substantial tumor-derived ambient RNA in low-UMI non-malignant nuclei.
  - So readouts for soup genes inside immune or stromal nuclei are unreliable. Readouts are given raw and corrected,
    with SoupX-global rho as a sensitivity check (`readouts_ambient_sensitivity_malignant.csv`).
- **Doublets.**

  | measure | L1 | L2 |
  |---|---:|---:|
  | scDblFinder (GEM-X rate) | 26.4% | 25.0% |
  | cluster-aware heuristic | 13.8% | 16.6% |
  | consensus (both) | 8.3% | 9.9% |
  | union (either) | 31.9% | 31.8% |

  - The heuristic flags heterotypic co-expression above the 99th percentile of panel scores outside the lineage, plus
    the doublet-like clusters below.
  - scDblFinder rises from 0% in the lowest-UMI decile to 77-78% in the top decile, so it is strongly depth-driven in
    these large aneuploid nuclei.
  - Doublet-like clusters: L1 epithelial+fibroblast 2,795 and epithelial+myeloid 511; L2 epithelial+fibroblast 2,716
    and epithelial+T/NK 1,569. These clusters carry the tumor CNV profile at reduced amplitude (median correlation
    0.48-0.52, against 0.62 for epithelial nuclei). They are tumor-containing multiplets or clumps; a mesenchymal tumor
    state is less likely given the 85% scDblFinder rate.
  - Primary readouts exclude the union. Readouts are also given for all nuclei, excluding scDblFinder only, and
    excluding the heuristic only. Malignant ambient-corrected CPM changes by <= about 20% across these policies for
    robust genes; see the last column of the table in section 5.

## 3. Clusters and compartments (task 2)

- **Clustering.** Leiden on a fixed kNN graph (k = 20, 30 PCs, 3,000 HVGs). Resolution was chosen by `stable_leiden`
  (5 seeds, frozen grid 0.2-1.5): 0.3 for L1 (median pairwise ARI 0.916, 14 clusters) and 0.5 for L2 (ARI 0.934, 16
  clusters).
- **Compartment calls.** A rule on cluster-mean panel z-scores, written out in `02_compartments.py` and identical for
  both libraries. Panels are in `common6.py`.
  - Epithelial (calling panel; nuclear-robust): EHF, ELF5, CDH1, ELF3, PRLR, SOX10.
  - Keratins and EPCAM are reported but not used to call. Keratins are ambient-dominated: KRT8/18/19 and EPCAM are
    detected in 16-39% of T-cell nuclei.
  - Basal keratins: KRT5/14/17/6A/6B/16. Luminal keratins: KRT8/18/19/7.
  - Myoepithelial: TP63, OXTR, MYLK, KRT14, KRT5, ACTA2, CNN1.
  - T/NK: PTPRC, CD247, SKAP1, THEMIS, BCL11B, CD3E, CD2, IL7R, NKG7, GNLY.
  - B: BANK1, PAX5, MS4A1, CD79A, FCRL1.
  - Plasma: MZB1, JCHAIN, TXNDC5, PRDM1, FCRL5, TNFRSF17.
  - Myeloid: CD163, MRC1, F13A1, CSF1R, MS4A6A, CD68, LYZ, CD14.
  - Fibroblast: DCN, LUM, COL1A2, COL3A1, FBN1, LAMA2, PDGFRA, COL6A3.
  - Endothelial: VWF, FLT1, PTPRB, EMCN, PECAM1, CDH5.
  - Perivascular: RGS5, PDGFRB, NOTCH3, MYH11, CARMN, KCNJ8.
  - Adipocyte: ADIPOQ, PLIN1, GPAM, PDE3B, ACACB, LEP.
  - Mast: CPA3, HDC, MS4A2, TPSAB1, TPSB2. Reported only: no mast cluster was found. KIT was removed because it marks
    luminal-progenitor-like tumor cells here.
- **Epithelial compartment** (L1 19,798; L2 16,620 plus 3,765 "epithelial_lowq").
  - The tumor is luminal-progenitor-like: EHF 97-99%, ELF5 about 85%, PRLR 83-88%, KIT 22-29%, SOX10 30-36%, basal
    keratins at or below 2%.
  - **KRT5/14/17 are essentially undetected in tumor nuclei** (0-2%); they are present in myoepithelial nuclei
    (7-17%).
- **Non-malignant epithelium.**
  - Myoepithelial nuclei: L1 778, L2 510.
  - A hormone-sensing luminal cluster in L2 only (299 nuclei; ESR1 68%, GATA3 72%, ANKRD30A 51%). It is CNV-flat
    (median correlation -0.02) and an internal normal-epithelium control.
- **Low quality.** L1 has a cluster with intronic fraction 0.28 (1,925 nuclei; cytoplasm-rich and heat-shock genes).
  L2's equivalent has intronic fraction 0.42 and is labelled epithelial_lowq.
- The tables are in `cluster_compartments_<lib>.csv` and `cluster_stability_<lib>.csv`.

## 4. Malignant calls (task 3)

### 4a. Expression CNV (infercnvpy 0.6.1)

- **Method.**
  - 11,475 autosomal genes shared by both libraries: detected in >= 2% of nuclei, with MT/RP/HLA and soup-enriched
    genes excluded. Window 150, step 10, 829 windows.
  - Reference: a random half of the QC-pass, non-doublet stromal and immune nuclei (5,183 / 4,943).
  - The other half (5,184 / 4,943) is held out to set thresholds without reference-centering bias.
  - Per-nucleus statistic: correlation of the nucleus' window profile with the consensus tumor profile of the *other*
    library.
  - Thresholds from the held-out normals: malignant >= q99 (0.33 / 0.30); normal <= q95 (0.20 / 0.19).
- **Results.**
  - Epithelial nuclei: median correlation 0.62 / 0.63.
  - Held-out normals: about 0.0 (q90 about 0.15).
  - Myoepithelial nuclei: 0.05 / 0.01.
  - Hormone-sensing luminal: -0.02.
- **Profile** (`figures/cnv_heatmap_vs_wgs.png`, `cnv_arm_profile_vs_wgs.csv`):
  - Strongest gains: 11p (+0.16), 10p, 3q, 1q, 11q, 20p, 22q.
  - Losses: 15q (-0.047), 5q, 7p, 6q.
- **WGS comparison over 37 arms** (`figures/cnv_arms_vs_wgs_scatter.png`): Pearson 0.35 / 0.35; Spearman
  0.46 / 0.49; partial r controlling gene density 0.52 / 0.53. The WGS coverage log2 against gene density is
  r = -0.74.
- **What the comparison does and does not show.**
  - The task's expected pattern (17q, 19 and 22 loss) comes from coarse coverage. That coverage is confounded with GC
    or gene density and is not reproduced in expression.
  - The concordance is carried by 3q/1q/11p/10p gain and 15q/7p loss.
  - |scRNA CNV| does not track WGS allelic imbalance (Spearman 0.11 / 0.08). The most imbalanced arms (17p/q, 9, 14)
    show about zero expression change, which fits copy-neutral LOH or balanced events.
  - This is a moderate validation, not a strong one.

### 4b. Genotype evidence from the scRNA BAMs

- **Haplotype imbalance.**
  - Regions: chr17, chr13 and chr9 were streamed (filters as in step 2a). These are the WGS-imbalanced arms that fit
    the byte budget.
  - Candidate SNVs come from pooled reads.
  - Germline-het filter, applied in the training library only: stromal/immune nuclei must show both alleles (minor
    share 0.2-0.8, >= 8 molecules). This yields 4,927 / 4,230 phased sites.
  - Phase is learned in one library by a rank-1 iteration and applied to the other library's nuclei. Molecules are
    UMI-deduplicated, with one vote per molecule per arm.
  - Phase agreement between libraries: 96.6% (2,623 shared sites). Against tumor WGS allele direction: 100% (17 / 15
    sites with |AF-0.5| >= 0.1).
- **Binomial mixture per arm.**
  - Tumor component theta: 0.84 (17), 0.83-0.84 (13q), 0.85-0.87 (9p), 0.87-0.88 (9q).
  - Normal component p0: 0.55-0.63, inflated above 0.5 by tumor-dominated ambient RNA.
  - Malignant nuclei behave as if they have lost one haplotype in all four arms: about 85% retained-haplotype
    molecules after phase error and ambient.
- **By group.** Tumor-haplotype molecule fraction: CNV-malignant 0.872 / 0.870; CNV-normal 0.617 / 0.622; stromal or
  immune compartments 0.58-0.66; hormone-sensing luminal 0.59.
- **Informative nuclei.** A posterior >= 0.95 or <= 0.05 (neutral prior) is reached in 27% of QC-pass non-doublet
  nuclei. The median is 8 haplotype molecules per nucleus.
- **Somatic SNVs** (UMI-level; `somatic_sites_grch38.tsv`). MTOR P1125A was lifted to chr1:11212821 and PTPN23 P981A
  to chr3:47410739 (Ensembl REST); reference bases were verified.

  | site | L1 alt / ref molecules | L2 alt / ref | note |
  |---|---|---|---|
  | BRCA1 c.81-1G>A | 48 / 0 | 52 / 3 | alt-dominant, consistent with loss of the wild-type 17 haplotype in tumor |
  | BRCA2 p.S2695L | 1 / 1 | 1 / 0 | too little coverage |
  | PIKFYVE p.I1548T | 8 / 9 | 1 / 14 | subclonal at 9% VAF; ref molecules expected in tumor |
  | MTOR p.P1125A | 3 / 6 | 3 / 5 | |
  | PTPN23 p.P981A | 2 / 0 | 2 / 3 | |
  | four unvalidated core-HRR Mutect2 intronic calls | mostly ref | mostly ref | not used |

  - Somatic-alt nuclei by compartment: epithelial 44 / 46; doublet-like 14 / 11; isolated hits in immune or stromal
    nuclei 4 / 3, compatible with ambient molecules.

### 4c. Combined label and concordance

- **Labelling rule.** Conservative (`07_genotype_labels.py`):
  - Malignant: CNV-malignant without normal-confident alleles, or tumor-confident alleles or a somatic-alt molecule
    without a CNV-normal call.
  - Non-malignant: the mirror rule.
  - Unresolved: conflicts and weak evidence.
- **Concordance.** In decisive nuclei (CNV not unresolved, allele call confident; QC-pass, non-doublet):

  | | L1 | L2 |
  |---|---:|---:|
  | agreement | 97.9% | 98.1% |
  | CNV-malignant but allele-normal | 63 | 50 |
  | CNV-normal but allele-tumor | 79 | 76 |

  - Allele-tumor calls are 5,068 / 5,063 CNV-malignant against 79 / 76 CNV-normal.
  - Allele-normal calls are 1,661 / 1,583 CNV-normal against 63 / 50 CNV-malignant.
- **Malignant fraction** (lower bound malignant; upper bound malignant + unresolved):

  | set | L1 | L2 |
  |---|---|---|
  | all barcodes | 56.3% (to 62.6%) | 57.3% (to 62.7%) |
  | QC-pass | 56.3% (to 62.4%) | 57.1% (to 62.6%) |
  | QC-pass, excluding scDblFinder | 48.4% (to 54.2%) | 49.7% (to 55.2%) |
  | QC-pass, excluding union of doublet flags (primary) | **50.4% (to 55.9%)** | **51.2% (to 56.3%)** |

  - These are nucleus proportions of a dissociated, nuclei-isolated sample. Nuclear yield differs by cell type, so
    they are not tumor cellularity and not WGS purity.
- **Label by compartment** (primary set): epithelial 12,315 malignant / 167 non-malignant / 555 unresolved in L1.
  L2's epithelial_lowq is mixed: 1,459 / 958 / 652. Stromal and immune compartments are 96-99% non-malignant.

## 5. Readouts (task 4)

- **Files.**
  - `readouts_primary.csv`: QC-pass, union doublets excluded, group-specific rho.
  - `readouts_all_variants.csv.gz`: every doublet policy, plus SoupX-global rho.
  - `readouts_primary_wide.csv`, `readouts_doublet_sensitivity_malignant_cpm_corr.csv`,
    `readouts_ambient_sensitivity_malignant.csv`.
  - `readouts_gene_classes.csv`.
  - Figures: `figures/target_dotplot.png` and `figures/target_violins_<lib>.png`.
- **Columns.**
  - det raw: fraction of nuclei with >= 1 UMI.
  - ambient-only det: expected detection if the gene were not expressed.
  - det @1.5k: detection after binomial thinning of every nucleus to 1,500 UMIs, which removes the depth confound;
    malignant nuclei have a median of 5,400-5,600 UMIs against 1,200-2,300 for most stromal and immune nuclei.
  - CPM: pseudobulk, raw and ambient-corrected.
  - ambient share: share of the gene's UMIs in the group that is expected from ambient.
  - CPMc: ambient-corrected CPM.
- **Gene class** (a priori, from Ensembl 110 canonical transcripts plus the soup/cell ratio):
  - ambient_prone: single exon, < 10 kb, or soup-enriched.
  - nuclei_robust: >= 30 kb, >= 5 exons, not soup-enriched.
  - The measured ambient share is the better guide: ERBB3 and NECTIN4 are classed as prone yet show only about 20%.
- Values are L1/L2.

| gene | class | malignant det raw | ambient-only det | det @1.5k | CPM raw | CPM corr | ambient share | non-mal epi CPMc | T/NK CPMc | myeloid CPMc | fibro CPMc | malignant CPMc across doublet policies |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TACSTD2 | ambient_prone | 0.32/0.33 | 0.24/0.25 | 0.108/0.117 | 67/73 | 22/25 | **0.71/0.71** | 33/47 | 125/117* | 0/12 | 13/7 | 20-26 |
| TOP1 | robust | 0.62/0.61 | 0.14/0.14 | 0.260/0.265 | 213/214 | 219/218 | 0.12 | 213/143 | 214/182 | 298/252 | 157/154 | 217-220 |
| SLFN11 | intermediate | 0.03/0.03 | 0.01 | 0.008/0.008 | 5.3/5.4 | **4.4/4.6** | 0.29/0.26 | 4.4/1.9 | 42/40 | 62/56 | 43/42 | 4.3-5.8 |
| ABCB1 | robust | 0.05/0.04 | 0.01 | 0.015/0.012 | 9.9/8.8 | 9.4/7.7 | 0.18/0.25 | 16/2 | 136/130 | 6/1 | 3/1 | 7.7-11.8 |
| ABCG2 | intermediate | 0.01 | 0.00 | 0.004/0.005 | 2.5/2.2 | 2.4/2.1 | 0.18/0.20 | 3/3 | 1/3 | 2/1 | 12/18 | 2.0-2.6 |
| ERBB2 | ambient_prone | 0.13/0.13 | 0.04 | 0.037/0.038 | 25/25 | 21/21 | 0.28/0.26 | 25/29 | 0 | 0 | 9/8 | 20-22 |
| ERBB3 | ambient_prone | 0.48/0.47 | 0.14/0.12 | 0.179/0.176 | 128/129 | 121/123 | 0.19/0.18 | 24/16 | 0 | 0 | 0 | 114-123 |
| EGFR | robust | 0.45/0.44 | 0.08 | 0.174/0.183 | 141/146 | 149/154 | 0.10/0.09 | 541/599 | 0 | 0 | 577/549 | 145-154 |
| MET | robust | 0.07/0.07 | 0.02 | 0.018/0.019 | 14/15 | 13.5/14.3 | 0.19 | 115/122 | 8/0 | 2/0 | 0/1 | 13.5-16.6 |
| FOLR1 | ambient_prone | 0.06/0.06 | 0.05/0.05 | 0.019/0.019 | 10.5/10.0 | 2.1/1.8 | **0.83/0.85** | 4/7 | 7/16 | 1/0 | 6/0 | 0.8-2.3 |
| NECTIN4 | ambient_prone | 0.25/0.26 | 0.07/0.06 | 0.076/0.082 | 53/58 | 48/54 | 0.22/0.20 | 7/48 | 22/4 | 0 | 0 | 48-55 |
| CD276 | ambient_prone | 0.08/0.09 | 0.03/0.02 | 0.023/0.025 | 15/16 | 12/14 | 0.29/0.27 | 8/9 | 8/7 | 11/23 | 34/27 | 12-14 |
| F3 | ambient_prone | 0.02/0.02 | 0.01 | 0.005/0.006 | 3.2/3.6 | 0.9/1.6 | 0.75/0.62 | 38/37 | 0 | 0 | 103/97 | 0.9-2.9 |
| PTK7 | intermediate | 0.43/0.40 | 0.11/0.10 | 0.153/0.142 | 117/111 | 114/107 | 0.16 | 83/59 | 0/17 | 0 | 39/24 | 104-114 |
| SLC39A6 (LIV-1) | ambient_prone | 0.12/0.13 | 0.04/0.05 | 0.035/0.038 | 22/25 | 17.6/17.9 | 0.31/0.37 | 73/107 | 54/46* | 21/20 | 31/19 | 17-18 |
| MKI67 | intermediate | 0.21/0.20 | 0.07/0.09 | 0.081/0.072 | 63/59 | 60/50 | 0.18/0.27 | 44/36 | 114/54 | 48/16 | 22/18 | 50-62 |
| TOP2A | intermediate | 0.15/0.14 | 0.05 | 0.053/0.049 | 44/42 | 42/37 | 0.18/0.23 | 25/15 | 58/33 | 37/7 | 16/3 | 37-45 |
| BRCA1 | robust | 0.19/0.18 | 0.04/0.03 | 0.067/0.067 | 57/55 | 59/58 | 0.11/0.10 | 8/16 | 25/17 | 17/15 | 9/12 | 56-60 |
| RAD51 | intermediate | 0.03/0.02 | 0.00 | 0.007/0.006 | 5.0/4.6 | 5.0/4.6 | 0.14 | 1/3 | 3/4 | 1/0 | 1/2 | 4.6-5.4 |
| PARP1 | intermediate | 0.32/0.32 | 0.09/0.10 | 0.099/0.100 | 69/73 | 64/63 | 0.22/0.26 | 43/72 | 135/114 | 73/49 | 43/17 | 61-64 |
| CD274 | intermediate | 0.01/0.01 | 0.00 | 0.002/0.001 | 1.1/1.1 | 0.8/0.9 | 0.35/0.29 | 12/12 | 16/13 | 30/28 | 5/7 | 0.8-1.4 |
| HLA-A | ambient_prone | 0.42/0.44 | 0.37/0.39 | 0.15/0.16 | 92/102 | 12.5/10.7 | **0.88/0.91** | 80/32 | 477/411 | 116/134 | 61/59 | 11-16 |
| HLA-B | ambient_prone | 0.52/0.55 | 0.45/0.49 | 0.19/0.23 | 124/144 | 18/15 | **0.87/0.91** | 117/42 | 877/932 | 273/360 | 76/71 | 15-27 |
| HLA-C | ambient_prone | 0.27/0.27 | 0.24/0.24 | 0.09/0.09 | 52/57 | 6/7 | **0.90/0.89** | 21/23 | 304/294 | 116/123 | 28/32 | 6-11 |
| B2M | ambient_prone | 0.77/0.77 | 0.70/0.71 | 0.35/0.37 | 252/270 | 22/3 | **0.93/0.99** | 88/61 | 1439/1185 | 413/428 | 241/189 | 3-27 |
| GAPDH (comparator) | ambient_prone | 0.39/0.38 | 0.29/0.30 | 0.14/0.14 | 84/87 | 29/24 | 0.70/0.76 | 19/7 | 198/130 | 0/23 | 14/0 | 22-29 |
| PUM1 (comparator) | robust | 0.82/0.79 | 0.22/0.20 | 0.44/0.44 | 412/412 | 431/432 | 0.11/0.10 | 404/358 | 256/257 | 309/273 | 214/218 | 424-433 |

\* T/NK corrected values for soup genes are under-corrected: the rho estimate of 0.60-0.67 was capped at 0.5 when
applied. TACSTD2 at "125 CPM" in T cells is an artifact of that cap, not T-cell expression.

- **Immune context** (non-malignant compartments; T/NK detection raw / at 1,500 UMIs; ambient-only expectation
  <= 0.011 for all of these):
  - CD3E 11-12% / 16%; CD8A 4-6%; CD4 6%; PDCD1 2.2-2.3% / 2.8-3.4%; TIGIT 5% / 7%; CTLA4 4% / 6%; LAG3 1%;
    HAVCR2 2% (myeloid 21%); FOXP3 0.3-0.6%; NKG7 1%.
  - CD274 is detected mainly in myeloid nuclei (3.1-3.5%) and in about 1% of malignant nuclei (0.8-0.9 corrected CPM).
  - Macrophages: CD163 29-30% and CD68 4.5% (short gene) of myeloid nuclei.
  - T/NK nuclei are about 13% of all QC-pass non-doublet nuclei.
  - In nuclei these short T-cell genes are captured poorly. Read them as within-library relative signals, not
    percent-positive.
  - HLA class I and B2M are ambient-dominated in malignant nuclei (87-99%). Antigen-presentation loss cannot be
    assessed from these data.
- **Readings worth carrying forward** (KH022-specific, RNA only):
  - TOP1 RNA is broadly present in malignant nuclei and similar to other compartments per CPM. That is consistent with
    a TOP1-payload target being present; it says nothing about protein amount.
  - SLFN11 is about 10x lower in malignant nuclei than in immune and stromal nuclei of the same sample. This is
    directionally concordant with bulk protein not detected.
  - ERBB3 RNA is clearly tumor-restricted (121 CPM, about 0 elsewhere), yet HER3 protein was not detected in the March
    FFPE. Timepoint and assay differ; flag for review rather than conclude.
  - EGFR RNA is present in tumor (149 CPM) but higher in fibroblasts and non-malignant epithelium.
  - MET RNA is low in tumor (14 CPM) and higher in non-malignant epithelium (115-122).
  - NECTIN4 (48-54) and PTK7 (107-114) are tumor-enriched.
  - FOLR1 is ambient-dominated (corrected 2 CPM). The FRalpha protein (697 amol/ug) cannot be cross-checked here.
  - LIV-1 (SLC39A6) is low in tumor (18) and higher in non-malignant epithelium.
  - ERBB2 is about 21 CPM in tumor, similar to non-malignant epithelium.
  - CD276 is about 13 CPM.
  - BRCA1 is tumor-enriched (59 CPM against 8-25); its splicing state is not assessable at 3'.
  - RAD51 is low (5 CPM).
  - PARP1 is about 64 CPM.
  - ABCB1/ABCG2 are low in tumor (8-9 / 2 CPM). ABCB1 is higher in T/NK and endothelial nuclei, as expected for
    those cell types.

### Heterogeneity across malignant subclusters

- **Subclusters.** Malignant nuclei were re-clustered with stable_leiden:
  - L1: 3 subclusters (resolution 0.2, ARI 0.93).
  - L2: 5 subclusters (resolution 0.5, ARI 0.72, less stable).
  - Both libraries have a proliferating subcluster (L1 M0, L2 M4: DIAPH3, ATAD2, POLQ, BRIP1, EZH2, MKI67).
  - Both have a TRPS1/PLCB4/PVT1 subcluster (L1 M2, L2 M3).
  - L2 M2 is low-UMI (median 1,669) and carries T-cell genes (PTPRC, SKAP1). It is likely residual doublets or
    ambient-heavy nuclei; treat it with caution.
- **Dropout model.** O/E is observed detected nuclei over the number expected under homogeneous expression (Poisson in
  depth, plus the ambient term). Each gene is compared with 10 comparator genes matched on expression and transcript
  span (`readouts_heterogeneity_*`).
- **TOP1.** O/E 0.88-0.99 in every subcluster of both libraries, inside the comparator range (min 0.69-0.94). No
  TOP1-low or TOP1-null subpopulation is detectable. Detection at 1,500 UMIs is about 26%, so a per-nucleus negative
  is uninformative.
- **TACSTD2.** Observed detection (25-38%) is near the ambient-only expectation (10-31%) in every subcluster. O/E is
  0.82-1.07; the one exception is L2 M2 at 1.90, a low-UMI artifact.
  - The data cannot distinguish "all tumor nuclei express TACSTD2" from "a subset lacks it".
  - Both are compatible with these numbers, because a single-exon cytoplasmic transcript is mostly absent from nuclei
    and the ambient floor sits close to the signal.
- **SLFN11.** Below expectation in the main non-cycling subclusters (O/E 0.64 / 0.51-0.72) and above it in the
  proliferating subclusters (O/E 1.70 / 1.61; comparator max 2.46 / 1.92).
  - This suggests relatively more SLFN11 in cycling tumor nuclei. Detection is 1-7% throughout, so even the
    "higher" subcluster is low in absolute terms.
  - It does not show an SLFN11-high tumor subpopulation comparable to immune or stromal levels.
- BRCA1, MKI67 and TOP2A follow the proliferation axis (O/E about 1.8 / 1.5 in the cycling subcluster). EGFR, ERBB3,
  PTK7, NECTIN4, CD276 and SLC39A6 stay within comparator ranges (O/E about 0.7-1.3), with no clear null subpopulation.

## 6. Library concordance (task 5)

| metric | KH022-1 | KH022-1-1 |
|---|---:|---:|
| qc_pass | 94.7% | 95.1% |
| scDblFinder / heuristic / union | 26.4 / 13.8 / 31.9% | 25.0 / 16.6 / 31.8% |
| stable resolution (ARI) | 0.3 (0.916) | 0.5 (0.934) |
| CNV consensus profile correlation | 0.9985 (between libraries) | |
| held-out-normal CNV q99 threshold | 0.33 | 0.30 |
| arm CNV vs WGS: Pearson / partial | 0.35 / 0.52 | 0.35 / 0.53 |
| haplotype phase agreement L1-L2 | 96.6% (2,623 sites) | |
| tumor-haplotype fraction, CNV-malignant / CNV-normal | 0.872 / 0.617 | 0.870 / 0.622 |
| CNV-allele concordance (decisive) | 97.9% (n 6,871) | 98.1% (n 6,772) |
| BRCA1 c.81-1 alt / ref molecules | 48 / 0 | 52 / 3 |
| malignant fraction, primary (upper bound) | 50.4% (55.9%) | 51.2% (56.3%) |
| rho, malignant | 0.145 | 0.139 |
| TOP1 / SLFN11 / TACSTD2 corrected CPM, malignant | 219 / 4.4 / 22 | 218 / 4.6 / 25 |
| ERBB3 / EGFR / NECTIN4 / PTK7 corrected CPM | 121 / 149 / 48 / 114 | 123 / 154 / 54 / 107 |

Every headline number agrees within a few percent between the libraries.

Differences between the libraries:
- L2 has a hormone-sensing luminal cluster and an epithelial_lowq cluster; L1 has a low-intronic low_quality cluster.
- L2's malignant subclustering is less stable.

The libraries behave like two samplings of one nucleus population. That is consistent with, but does not prove,
technical replication.

## 7. Limitations

- **WGS validation is weak.**
  - It uses coarse, GC-confounded coverage bins.
  - The allele-specific CN fit (step 5) was not final, so copy-neutral LOH of 17 is inferred, not shown.
  - Arm means dilute focal events.
- **Haplotype evidence covers chr17, 13 and 9 only** (byte budget). It is informative for 27% of nuclei.
  - The p0 > 0.5 in normal nuclei shows tumor-derived ambient RNA, which slightly favours false "tumor" allele calls in
    low-UMI normal nuclei. The free-p0 mixture absorbs part of this.
- **The non-malignant "epithelial" group is small** (about 550-600 nuclei: myoepithelial plus hormone-sensing luminal
  plus a few CNV-flat epithelial nuclei). Its CPMs are noisy.
- **Ambient correction is approximate.**
  - The soup is cytoplasmic. One rho per group over-corrects intronic genes and under-corrects exonic or secreted ones.
  - PTPRC "corrected" to about 0 inside malignant nuclei illustrates this: it has a high ambient share and rho was
    estimated from Ig genes.
  - Corrected values near 0 for nuclear genes should not be read as absence.
- **Doublets.** The calls are not calibrated for nuclei. The doublet-like clusters may include tumor cells in
  intermediate states. The primary set excludes about 32% of nuclei.
- **Detection is not prevalence.** Detection fractions in nuclei are not percent-positive. RNA is not protein or
  membrane localization. KH022 timepoint, specimen and treatment state are unknown.
- No orthogonal truth set exists for malignant labels beyond the internal genetic concordance.

## 8. Files

- `barcode_annotations_<lib>.csv.gz`: every barcode, with QC metrics and flags, doublet calls, cluster, compartment,
  CNV group/score/correlations/call, haplotype counts and posterior, somatic molecules, malignant label, malignant
  subcluster and UMAP.
- `genotype_and_labels_summary.json`, `cnv_arm_profile_vs_wgs.csv`, `cluster_*`, `readouts_*`,
  `heterogeneity_summary.json`, `malignant_subcluster_stability_*`, `somatic_sites_grch38.tsv`.
- `figures/`: `umap_<lib>.png`, `cnv_heatmap_vs_wgs.png`, `cnv_arms_vs_wgs_scatter.png`, `target_dotplot.png`,
  `target_violins_<lib>.png`.
- `scripts/` and `README.md`: commands, versions and bytes transferred.
