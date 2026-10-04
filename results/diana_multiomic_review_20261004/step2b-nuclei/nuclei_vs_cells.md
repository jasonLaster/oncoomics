# KH022: single-nucleus or whole-cell material? (step 2b, private)

Research prioritization only; no clinical claims. Private, git-ignored. Analysis date 2026-10-03.

## Verdict

**Nuclei (snRNA-seq-like, cytoplasm-depleted material). Confidence: high (~95%).** Every compartment-sensitive
metric points the same way, and in both libraries. The data cannot separate isolated nuclei from cells that lost their
cytoplasm during preparation (for example, cells lysed during freeze-thaw). For analysis the two have the same
consequences, but only the vendor can confirm the protocol.

Strongest numbers (KH022-1 / KH022-1-1):

1. **Ribosomal-protein (RPS/RPL) share: median 1.0% / 1.0%** (95th percentile 3.3 / 3.2). The 8 whole-cell TNBC
   captures (GSE161529) have per-capture medians of 14.5-41.8%, and the PBMC controls 18-25%. Even after correcting
   for intron counting (exon-only equivalent: pooled 2.1% / 2.0%), RPS/RPL is 6-22x below every whole-cell capture.
   80% of KH022 barcodes have RP <2%, against at most 8.5% in any whole-cell capture. AUC is 0.98.
2. **Intronic UMI fraction in called cells: 57.0% / 56.1%** (sense, gene-assigned UMIs; BAM subset chr1:0-40 Mb;
   per-barcode median 0.57 / 0.55, 5-95%: 0.36-0.69). The distribution is unimodal. Reference ranges from the 10x
   technical note CG000376, Table 1 (3' v3.1): **19-41% in whole-cell datasets** (breast cancer cells 19%) and
   **25-63% in nuclei datasets**. The region is conservative: its all-barcode reads are about 8 points less intronic
   than the vendor's genome-wide figure (49.6% intronic and 37.7% exonic of all reads).
3. **Cytoplasmic housekeeping mRNA is missing from the barcodes.** In epithelial-marker-high barcodes at 3-6k UMIs,
   GAPDH is detected in 39% / 42% and ACTB in 65% / 66%. The six whole-cell captures in the same depth bin (two had
   too few epithelial barcodes there) show GAPDH 96-100% and ACTB 75-100%. Only about 30% of all GAPDH, ACTB, B2M
   and TACSTD2 UMIs sit in called barcodes (the library average is 73%). By contrast, 80-92% of UMIs for nuclear,
   intron-rich genes are in called barcodes (EGFR, TRPS1, ESRRG, PDE4B, MALAT1, NEAT1).
4. **Ambient RNA is cytoplasmic and the barcodes are nuclear.** Reads from non-called barcodes in the region are 76%
   exonic and 19% intronic, while called barcodes are 38% exonic and 56% intronic. Ambient is enriched for MT
   (2.3-2.7x) and RPS/RPL (3.2-4.2x) relative to called barcodes; the PBMC whole-cell control shows 1.0-1.3x and
   0.85x. Across 440 chr1 genes, a gene's ambient/cell ratio falls as its intronic fraction rises (Spearman -0.66).

Weak or non-discriminating metrics (reported for calibration):

- **MT%.** Median 0.87 / 0.95% (95th percentile 4.7 / 4.8%) against whole-cell capture medians of 2.0-14.6%. After
  intron correction, the pooled value (3.0%) overlaps the cleanest whole-cell captures (2.1-3.5%). AUC 0.92.
  99.8-99.97% of barcodes carry at least one MT UMI (median 28-29), which points to cytoplasmic or ambient carry-over.
- **MALAT1.** Median 5.3 / 5.2% against 1.3-7.3% in whole cells, so the raw values overlap (AUC 0.71-0.73). The
  exon-only equivalent (pooled about 13.5%) exceeds every whole-cell capture (at most 5.8%), but that step depends on
  an assumption.
- **NEAT1.** 0.06% versus 0.04-0.27% in whole cells, so it is not elevated. With 3' poly(A) capture, NEAT1 is a poor
  nuclear marker. (Interpretation: the long NEAT1_2 isoform is not polyadenylated. This is general knowledge and was
  not checked in this session.)

## Benchmark table (all called/deposited barcodes per capture)

| capture | n | median UMIs | median genes | MT % median (IQR; 5-95%) | RPS/RPL % median (IQR; 5-95%) | MALAT1 % | NEAT1 % |
|---|---:|---:|---:|---|---|---:|---:|
| KH022-1 | 38,994 | 4,190 | 2,400 | 0.9 (0.4-1.8; 0.2-4.7) | 1.0 (0.7-1.8; 0.5-3.3) | 5.32 | 0.055 |
| KH022-1-1 | 37,805 | 3,899 | 2,288 | 0.9 (0.5-1.9; 0.2-4.8) | 1.0 (0.7-1.7; 0.5-3.2) | 5.16 | 0.056 |
| TNBC mh0114 | 2,015 | 2,642 | 971 | 4.2 (2.9-7.7; 1.0-95.5) | 20.2 (12.9-26.6; 1.0-36.6) | 5.19 | 0.065 |
| TNBC mh0126 | 3,666 | 2,378 | 946 | 2.7 (1.5-4.5; 0.4-10.1) | 18.6 (14.0-22.7; 5.3-28.8) | 2.40 | 0.117 |
| TNBC mh0135 | 15,870 | 4,636 | 1,750 | 4.9 (3.6-6.6; 1.7-12.1) | 19.8 (16.2-24.0; 11.6-32.4) | 1.34 | 0.113 |
| TNBC sh0106 | 1,065 | 3,813 | 1,262 | 2.4 (1.3-3.8; 0.2-13.6) | 15.6 (8.7-22.9; 2.9-33.0) | 7.32 | 0.114 |
| TNBC b1-mh0131 | 6,456 | 8,826 | 1,849 | 13.0 (10.3-17.5; 5.6-40.2) | 41.8 (32.0-49.2; 7.7-55.5) | 2.15 | 0.039 |
| TNBC b1-mh0177 | 21,130 | 1,902 | 815 | 7.6 (4.8-11.4; 2.1-31.4) | 16.3 (9.3-22.8; 2.5-33.3) | 4.20 | 0.159 |
| TNBC b1-mh4031 | 5,581 | 11,872 | 2,781 | 2.0 (1.5-2.6; 0.5-5.9) | 33.5 (28.4-38.1; 14.7-44.2) | 2.74 | 0.070 |
| TNBC b1-tum0554 | 9,593 | 2,645 | 912 | 14.6 (9.0-24.2; 4.3-54.7) | 14.5 (9.3-20.5; 2.3-32.8) | 4.57 | 0.271 |
| pbmc1k-v3 | 1,222 | 6,628 | 1,919 | 10.3 (8.7-12.6; 6.2-46.9) | 24.6 (14.6-34.3; 1.0-41.7) | 4.01 | 0.084 |
| 5k pbmc nextgem | 5,527 | 5,676 | 1,836 | 8.0 (6.2-13.6; 4.4-45.8) | 18.1 (12.1-30.0; 3.8-38.9) | 5.27 | 0.099 |

The benchmarks use exon-only counting (Cell Ranger 3-6 era) and KH022 counts introns, so UMI and gene counts are not
comparable across the table. Barcodes with MT <3%, RP <3% and MALAT1 >2%: KH022 81% / 80%; every benchmark 0-0.7%.

Intronic-fraction comparator (literature; 10x CG000376 Rev A, Table 1; sense intronic as a share of sense UMIs):

| dataset | whole cells | nuclei |
|---|---:|---:|
| human breast cancer | 19.4% | 25.2% |
| human PBMC | 31-36% | 54-63% |
| Jurkat / 293T / Raji | 41 / 21 / 28% | 36 / 31 / 33% |
| mouse E18 brain | 36% | 50% |

KH022 gives 56-57% in the chr1:0-40 Mb subset; the genome-wide value is probably higher. The 10x note itself warns
that this fraction varies widely between datasets. It supports the verdict but would not decide it alone.

## Per-analysis detail

- **Ambient (raw matrix, non-called barcodes with 1-99 UMIs; about 2.0M barcodes).** Top ambient genes are MALAT1
  (4.4%), then MT-CO3/CO1/CO2/ND4/ATP6/CYB. Next come secreted or cytoplasmic transcripts enriched 3-6x over called
  barcodes: CSN3, SCGB3A1, IGKC, SLPI, CD59, B2M, EEF1A1. Nuclear long genes (TRPS1, ZBTB20, ESRRG, PDE4B, DMD) are
  depleted at 0.4-0.7x. Called barcodes hold 73.2% / 70.9% of all UMIs (PBMC control: 90.6%).
  - These secretory ambient genes are detected in 74-99% of all barcodes (CSN3 in 98.8%).
  - That is a likely mechanism for the 38% "goblet cell" labels from 10x Cloud.
- **BAM-level validation.** Representative reads (xf & 8) reproduce the vendor matrix exactly: per-gene ratio 1.00,
  per-cell Spearman 1.00, and no duplicate CB/UB/GN molecules.
- **Bimodality.** None found. The Hartigan dip statistic is 0.010 / 0.012; the p-value is near 0 only because n is
  about 30k. The observed SD (0.10) exceeds the binomial expectation (0.06), consistent with cell-type and gene-mix
  variation.
  - Only 2.1 / 2.5% of barcodes fall below 0.30 intronic, and just 0.6% of barcodes have both intronic <0.30 and
    RP >3%. A whole-cell subpopulation, if present, is at most about 1-2%.
  - Intronic fraction falls with RP% (Spearman -0.53) and MT% (-0.31): the more cytoplasm a barcode retains, the
    less intronic it is.
- **Gene level.** Intronic fraction rises with gene span (Spearman 0.61, n = 457 genes):
  - <10 kb: median 7%;
  - 10-50 kb: 46%;
  - 50-200 kb: 72%;
  - >200 kb: 85%.

  Highly expressed long genes are mostly unspliced: KAZN 95%, EIF4G3 89%, CAMTA1 88%, RERE 80%, PUM1 80% and MTOR
  70%. Short genes are mostly spliced: RPL11 6%, CCNL2 3% and MARCKSL1 0%.
- **TACSTD2.** It is a single-exon gene (Ensembl canonical ENST00000371225, chr1:58,575,433-58,577,252), so 100% of
  its UMIs are exonic.
  - About 70% of the gene-assigned reads at its locus come from non-called barcodes (65.9k vs 27.8k, and 70.6k vs
    28.7k).
  - 29.6% / 29.1% of all TACSTD2 UMIs sit in called barcodes; ambient/cell share is 4.3-4.4x.
  - Detected in 32.0% / 33.3% of barcodes, with 1.32-1.36 UMIs per detecting barcode.

## Consequences

1. **MT% filters.** Whole-cell MT cut-offs (5-25%) do not transfer. In nuclei, MT signal measures cytoplasmic or
   ambient contamination, not dying cells.
   - Fixed cut-offs flag 4.5-4.7% of barcodes at 5%, 1.4% at 10% and 0.6-0.7% at 20%. The last group is a distinct
     cluster (MT 40-60%, low MALAT1) that looks like debris or ambient.
   - The previous MAD-derived cut-off of 2.5% would flag 15-17%.
   - Use an outlier rule as a contamination flag (median + 3 MAD ≈ 3.3-3.6%, with a minimum-difference floor, as in
     the OSCA snRNA chapter) and review it rather than excluding barcodes.
   - Do not apply RP% or dissociation-stress reviews: nuclei show little dissociation signature (Slyper 2020).
   - UMI and gene floors must be set on intron-included counts and are not comparable with exon-only benchmarks.
2. **Annotation.** Azimuth and 10x Cloud references are whole-cell. Nuclei lack most cytoplasmic mRNA (GAPDH
   detected in about 40% of epithelial nuclei) and carry a strong secretory ambient signal. Treat vendor labels and the
   55% "unknown" as uninformative.
   - Use a nuclei-trained breast reference, or marker scoring built on nuclear-robust (long, intron-rich) genes.
   - Do the cell-type assignment with ambient-aware clusters.
3. **Ambient correction.** Correct ambient RNA with a method that is aware of nuclei.
   - Ambient here is mature cytoplasmic mRNA, so intronic UMIs are nearly free of it, while intronless or short genes
     (TACSTD2, KRT8/18/19, EPCAM, VIM, GAPDH, CSN3) are the most contaminated.
   - SoupX's global rho of 8-12% is plausible but averages over very different gene classes. Run it with clusters, or
     use CellBender, and cross-check targets with intronic-only or exonic-only layers (velocyto or STARsolo on the
     full BAM).
4. **Doublets.** At about 38-39k nuclei per lane, the GEM-X rate (about 0.4% per 1,000 cells) implies about 15%
   multiplets. Nuclei clumping can add to that. The 25-26% scDblFinder flags exceed this expectation and are not
   calibrated for nuclei. Genotype-based checks (step 2a) are the better arbiter.
5. **TACSTD2 and other targets.** A 32% detection rate is nuclear plus ambient RNA detection, not a percent-positive
   figure.
   - In epithelial-marker-high nuclei, TACSTD2 detection (34-36%) sits at the same ceiling as GAPDH (39-42%). That is
     compatible with broad epithelial expression but cannot be quantified per nucleus. The data cannot show
     heterogeneity, membrane presence or IHC equivalence.
   - Do not compare these rates with whole-cell TNBC (TACSTD2 0.01-0.99 in epithelial cells across the 8 tumors),
     bulk TPM or protein.
   - Long, intron-rich targets keep 68-84% of their UMIs in called barcodes and are more robust: EGFR, MTOR, BRCA1,
     TOP1, MET, SLFN11.
   - Cross-target comparisons of detection within KH022 are confounded by compartment and gene length.
6. **Calibration needed.** Re-count one matched fresh-cell vs frozen-nucleus pair through Cell Ranger 10.1 with
   GRCh38-2024-A and introns included. That gives per-gene detection ceilings as a function of intronic fraction,
   ambient share and MT/RP baselines. Candidates:
   - **GSE140819** (Slyper et al. 2020, PMID 32405060). Verified from the GEO SOFT header: 40 samples across 8 tumor
     types, including 10 "MBC" metastatic breast cancer samples with fresh-cell and CST/TST/NST nuclei preparations
     from the same specimens. Raw reads are controlled access (DUOS). That GEO holds processed matrices is assumed,
     not verified.
   - **Kumar et al. 2023, Nature (HBCA, normal breast).** 117,346 nuclei from 20 women, verified on the HCA Data
     Explorer. Its listed GEO series are GSE195665, GSE234817, GSE235326 and GSE234814; which one holds the snRNA data
     was not verified.
   - **Whole-cell normal-breast counterpart, not nuclei:** Reed et al. 2024, Nat Genet: CELLxGENE collection
     48259aa8-f168-4bf5-b797-af8e88da6637 and ArrayExpress E-MTAB-13664 (about 800k cells, 10x 3' v3; verified via
     the API). A search snippet had wrongly attributed E-MTAB-13664 to the HBCA nuclei.
   - Also confirm the protocol with the vendor (Signios): nuclei isolation kit, fresh or frozen tissue, and the number
     of nuclei loaded.

## Limitations

- **Benchmarks.** The 8 whole-cell captures come from one study (exon-only counting, older chemistry and Cell Ranger,
  different patients). PBMCs are a different tissue. Cell-type mix affects RP% and MT%, though even the lowest-RP
  whole-cell capture medians (14.5%) are 4x above the KH022 95th percentile.
- **BAM subset.** BAM metrics cover chr1:0-40 Mb only, about 1.2 GB streamed, and that region's composition is more
  exonic than genome-wide. Intronic comparators are literature values (10x technical notes), not values recomputed
  through the same pipeline.
- **Corrections.** The intron correction assumes all MT, RP and MALAT1 UMIs are exonic.
- **Specimen identity.** Unresolved (steps 0.1 and 2a); the verdict concerns material type only.

Sources: 10x CG000376 https://cdn.10xgenomics.com/image/upload/v1660261286/support-documents/CG000376_TechNote_Antisense_Intronic_Reads_SingleCellGeneExpression_RevA.pdf ;
10x CG000554 https://cdn.10xgenomics.com/image/upload/v1660261285/support-documents/CG000554_Interpreting_SingleCellGEX_with_introns_RevA.pdf ;
OSCA snRNA chapter https://bioconductor.org/books/3.16/OSCA.advanced/single-nuclei-rna-seq-processing.html ;
Slyper 2020 https://pmc.ncbi.nlm.nih.gov/articles/PMC7220853 ; Osorio & Cai 2021 (whole-cell human MT ranges) https://pmc.ncbi.nlm.nih.gov/articles/PMC8599307 ;
HBCA https://explore.data.humancellatlas.org/projects/1ffa2223-28a6-4133-a5a4-badd00faf4bc .

Files: `metrics_*.csv/json`, `table_benchmark_composition.md`, `fig_composition_vs_benchmarks.png`,
`fig_scatter_mt_rp_malat1.png`, `fig_ambient_vs_cells.png`, `fig_bam_intronic_fraction.png`, `scripts/`, `README.md`.
