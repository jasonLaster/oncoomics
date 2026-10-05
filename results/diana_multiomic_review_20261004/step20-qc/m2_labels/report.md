# Step 19 QC module 2: tumor labels against a somatic-SNV truth set (2026-10-05)

**Question.** How accurate are step 6's malignant / non-malignant / unresolved nucleus labels when checked against an
independent genetic truth set? Is KH022 the same clonal mix as the WGS block? Do the candidate-gene conclusions depend
on label errors?

**Short answer.**
- **The labels are good where it matters.**
  - Malignant precision is 0.94 in both libraries (95% CI 0.92-0.96 L1, 0.91-0.96 L2).
  - Malignant recall is 0.90-0.91.
- **There are two specific errors.**
  - The step-6 "normal epithelium" (non_malignant, compartment `epithelial`) is mostly tumor: about 80% in L1, about
    100% in L2.
  - Unresolved epithelial nuclei are 80-90% tumor.
  - The L2 hormone-sensing luminal cluster is genuinely normal: tumor fraction 0.00, CI 0-0.18.
- **KH022 lacks the ~10% subclone that is in the WGS/Altera block.**
  - At the 9 exome-absent subclone sites, strict malignant nuclei carry 0 alt molecules against 21.2 expected
    (Poisson p = 6e-10; presence scale k <= 0.09).
  - KH022 therefore resembles the Personalis exome piece (4/10), not the 3/13 block.
- **No candidate-gene verdict changes** under strict genetic tumor definitions (0 / 47 changes, max |dlog2FC| 0.37).
  - A genotype-only "strict normal" set cannot be built at this depth (section 4).

## 1. Somatic SNV truth set (scripts 01-04)

| item | value |
|---|---:|
| consensus PASS SNVs (Mutect2 AND Strelka2) | 16,190 |
| SNVs inside gene bodies (GENCODE v23 protein-coding / lncRNA / antisense / processed-transcript / sense genes; introns included) | **8,065** |
| step-7 subclone sites among them | 12 (all 12 are in the consensus) |
| sites with >= 1 UMI molecule in either library | 3,436 |
| removed: matched normal WGS shows >= 1 alt read | 70 |
| removed: alt in stromal/immune non-malignant nuclei exceeds the ambient expectation (>= 3 alt, binomial p < 1e-3 at rho 0.5) | 9 |
| removed: germline-like (stromal/immune alt fraction >= 0.3, >= 5 molecules) | 24 |
| sites used | 7,969 (3,383 with molecules) |
| clonal sites used for label calls | 6,371 (2,663 with molecules) |
| UMI molecules, all barcodes, L1 | 135,584 (100,756 ref, 34,736 alt, 92 other) |
| UMI molecules, all barcodes, L2 | 131,955 (97,059 ref, 34,825 alt, 71 other) |

- **Molecules.** Deduplicated by (CB, UB, site); consensus base = majority of at least 60% of the molecule's reads.
- **Read filters.** MAPQ 255, nM <= 4, BQ >= 20, >= 3 bp from read ends.
- **Sanity sites** in strict malignant nuclei (both agree with step 6):
  - BRCA1 c.81-1G>A: 91/93 alt molecules.
  - TP53 splice site: 9/9 alt.
- **Flagged sites** are in `tables/sites_flagged.tsv`.
  - Some alt everywhere, e.g. PSMB2 with 671/1,102 alt in stromal nuclei. These look like missed germline variants or
    RNA editing.
  - A few are highly tumor-expressed genes whose stromal alt is plausibly ambient (e.g. VPS35, FOXK2). Excluding them
    makes the filter conservative.
- **Leaf-bin fetch.** Only reads lying entirely inside one 16-kb BAI leaf bin were fetched.
  - Checked on step 6's complete chr9/13/17 subsets (`tables/leaf_loss.csv`), this loses 0.3% of molecules.
  - Alt fraction is unchanged: 0.2987 for all reads against 0.2989 for leaf-only (L1), and 0.2998 against 0.3001 (L2).
- **Index check.** Every fetched chunk's first record was checked against its window: 0 / 7,734 bad offsets in L1 and
  0 / 7,370 in L2. The known KH022-1-1 index problem did not affect these regions.

## 2. Label accuracy (script 05)

### Model

Per molecule:

    P(alt | tumor nucleus)  = (1 - rho_i) * s * f_site + rho_i * qa_site
    P(alt | normal nucleus) = rho_i * qa_site

- **f** = mult / CN, from the S1b fit (purity 0.35, ploidy 2.8). Only clonal sites are used.
- **qa** = ambient alt fraction from empty droplets (1-99 UMIs), shrunk toward phi * f.
  - Pooled over clonal sites it is 0.32 (3,969 molecules; phi = 0.68), so the ambient RNA is tumor-dominated.
- **rho_i** = min(c / UMI_i, 0.9). c is calibrated so that the median malignant nucleus has step 6's rho (0.145 L1,
  0.139 L2).
- **s** = RNA/DNA allele-fraction scale.
  - Fitted jointly with the tumor fraction on 2,551 deep (>= 5 molecules) malignant epithelial nuclei:
    **s = 0.74 (CI 0.72-0.74)**.
  - Observed RNA alt fractions are about 0.7x mult/CN in every f bin.
  - Without s, every tumor-fraction estimate is biased about 20% low.
- **pi (tumor fraction)** is fitted by EM per label x compartment group.
  - The fit is done within UMI-quartile strata, reweighted to the group's full UMI distribution, so depth-dependent
    informativeness does not bias pi.
  - CIs come from 500 nucleus bootstraps.

**Model-free check.** Among malignant epithelial nuclei, 1.7% of those with 11-20 molecules have zero alt molecules, and
6.3% of those with 7-10 molecules do. If 25% of malignant labels were normal, about 23% would. Non-malignant
immune/stromal nuclei with >= 2 molecules have 83-93% zero alt.

### Confusion-style table (QC-pass, non-doublet)

Genetic call per nucleus: log10 LR(tumor : normal) >= 1 is "tumor"; <= -1 is "normal".

| lib | label | genetic tumor | genetic normal | ambiguous (few molecules) | no molecule |
|---|---|---:|---:|---:|---:|
| L1 | malignant | 2,028 | 57 | 8,252 | 2,503 |
| L1 | non_malignant | 9 | 28 | 4,359 | 6,841 |
| L1 | unresolved | 22 | 0 | 581 | 786 |
| L2 | malignant | 1,999 | 51 | 7,828 | 2,868 |
| L2 | non_malignant | 6 | 24 | 4,113 | 6,730 |
| L2 | unresolved | 17 | 0 | 463 | 798 |

- About 2,000 nuclei per library are individually genetically confirmed tumor.
- Among malignant-labelled nuclei with a decisive call, 97% are tumor.
- Most nuclei carry only 1-3 informative molecules. The group-level estimates below are the calibrated numbers.

### Precision and recall

Latent truth from the mixture model; 95% bootstrap CIs. The last two columns are ambient sensitivity runs.

| metric | L1 | L2 | rho x0.5 (L1 / L2) | rho x2 (L1 / L2) |
|---|---|---|---|---|
| malignant precision | **0.938** (0.917-0.957) | **0.938** (0.907-0.963) | 0.960 / 0.969 | 0.930 / 0.930 |
| malignant recall | 0.902 (0.888-0.920) | 0.908 (0.881-0.926) | 0.878 / 0.867 | 0.909 / 0.916 |
| non-malignant precision | 0.950 (0.934-0.968) | 0.958 (0.922-0.976) | 0.923 / 0.906 | 0.953 / 0.960 |
| non-malignant recall | 0.881 (0.857-0.898) | 0.888 (0.857-0.912) | 0.908 / 0.924 | 0.868 / 0.873 |
| tumor fraction among unresolved | 0.54 (0.40-0.62) | 0.58 (0.46-0.67) | 0.61 / 0.68 | 0.48 / 0.51 |
| estimated true tumor nuclei (QC-pass, non-doublet) | 13,353 (13,011-13,643) | 13,169 (12,666-13,682) | | |
| malignant-labelled nuclei estimated normal | 799 (552-1,062) | 784 (467-1,181) | | |
| non-malignant-labelled nuclei estimated tumor | 563 (365-747) | 461 (257-851) | | |

- **Replicate agreement.** L1 and L2 agree within 0.01 on every precision and recall.
- **Ambient calibration.** At rho x1 the model over-predicts alt-carrying immune nuclei: T/NK observed 100 against 175
  expected in L1. rho x0.5 fits better (100 against 90). Conclusions hold across rho x0.5 to x2.
- **Where the missed tumor nuclei sit (recall about 0.90).**
  - Unresolved epithelial nuclei.
  - L1 `low_quality` non-malignant nuclei: about 48% tumor, about 390 nuclei.
  - L2 `epithelial_lowq` non-malignant nuclei: about 42% tumor, about 400 nuclei.
  - Step-6 "normal epithelium".
- **Doublet-flagged nuclei.** Malignant-labelled doublet-flagged nuclei are about 88% tumor (L1 0.876, L2 0.879), so
  they are tumor-containing, as step 6 inferred.

### Special groups

Tumor fraction pi with 95% CI, and observed vs ambient-expected nuclei with >= 1 alt molecule.

| group | L1 pi | L2 pi | nuclei with alt >= 1, obs / exp-if-normal | verdict |
|---|---|---|---|---|
| non_malignant / epithelial ("normal luminal epithelium" in steps 6 and 13) | 0.80 (0.40-0.92), n = 167 | 1.00 (0.90-1.00), n = 61 | L1 29 / 12.6; L2 15 / 3.1 | **mostly tumor**; do not use as a normal comparator |
| non_malignant / epithelial_luminal_HS (L2 only) | – | **0.00 (0.00-0.18)**, n = 79 | 4 / 5.5 | genuinely normal (hormone-sensing luminal) |
| non_malignant / myoepithelial | 0.00 (0-0.05) | 0.00 (0-0.02) | L1 18 / 27.6; L2 10 / 24.0 | normal |
| non_malignant / epithelial_lowq (L2) | – | 0.42 (0.19-0.72), n = 958 | 61 / 46.6 | mixed |
| unresolved / epithelial | 0.86 (0.65-0.96), n = 555 | 0.81 (0.57-0.96), n = 191 | L1 132 / 39.3; L2 50 / 13.8 | **mostly tumor** |
| unresolved / epithelial_lowq (L2) | – | 0.90 (0.63-1.00), n = 652 | 84 / 39.7 | mostly tumor |
| non_malignant immune and stromal compartments (each) | 0.00-0.11 | 0.00 | at or below the ambient expectation | normal |

- **Step 13's "vs normal epithelium" comparator is tumor-contaminated.** It pooled non-malignant epithelial and
  myoepithelial nuclei, and the epithelial part is mostly tumor.
- **Clean normal-epithelium references** are myoepithelial nuclei (both libraries) and L2's HS-luminal cluster (79
  nuclei).
- Step 18 compared tumor against luminal nuclei. Check which nuclei it used.

## 3. Clonality and specimen identity (script 06)

### Test

- **Nuclei.** Strict malignant nuclei: malignant label AND cnv_malignant, QC-pass, non-doublet.
- **Expected alt per molecule if KH022 had the WGS composition:**
  e = (1 - rho) * s * CCF * mult/CN + rho * qa.
  - For the 12 step-7 sites, CCF uses their pooled WGS VAF (0.102), which avoids per-site winner's curse.
- **Presence scale k** is fitted with P(alt) = k * e.
  - k = 1 means present as in the WGS; k = 0 means absent.
  - CIs are from the profile likelihood.
- **Error floor:** 3.0e-4 per molecule, from "other" alleles / 2.

| site class | molecules (sites) | alt observed | alt expected if WGS-like | k (95% CI) | P(obs or fewer if WGS-like) |
|---|---:|---:|---:|---|---|
| WGS clonal (calibration) | 53,138 (2,266) | 15,809 | 16,398 | 0.98 (0.97-0.99) | reference (s fitted on these sites) |
| WGS subclonal (binomial test against clonal VAF) | 13,527 (609) | 636 | 1,581 | 0.40 (0.37-0.43) | < 1e-10 |
| **step-7 subclone, exome-absent (9 sites; 7 with molecules)** | 128 (7) | **0** | **21.2** | **0.00 (0.00-0.09)** | **6e-10** |
| step-7 subclone, exome 1-3% (MRPS9, ECT2, ARAF) | 202 (3) | 6 | 28.0 | 0.22 (0.09-0.43) | < 1e-4 |

- **Per library, exome-absent sites:**
  - L1: 0/59 against 9.6 expected.
  - L2: 0/69 against 11.6 expected.
  - All barcodes, including ambient: 2/661 against 114.6 expected.
- **Per-site detail** (`tables/subclone_sites_detail.csv`, strict malignant alt / molecules):

  | gene | alt / molecules |
  |---|---|
  | ATP13A3 | 0/43 |
  | PRRG1 | 0/38 |
  | AP5M1 | 0/17 |
  | OTUD4 | 0/16 |
  | F5 | 0/9 |
  | SVOPL | 0/3 |
  | SYNJ1 | 0/2 |
  | SCN11A | no coverage |
  | ADGRL3 (LPHN3) | no coverage |
  | MRPS9 | 5/47 |
  | ECT2 | 1/154 |
  | ARAF | 0/1 |

### Interpretation

- The ~10% subclone shared by the WGS and Altera (3/13 block) is absent from KH022, or present at no more than about 9%
  of its WGS level.
- The three sites seen at 1-3% in the Personalis exome appear in KH022 at about 0.2x their WGS level. That matches their
  exome/Altera VAF ratio (about 0.15-0.3).
- **KH022 therefore matches the Personalis exome/RNA piece (4/10), not the WGS block.**
- Truncal biology is shared: clonal k = 0.98.
- WGS-called subclonal sites as a class are also depleted in KH022 (k = 0.40). Part of this is likely regional
  heterogeneity. Part may be low-VAF FFPE or WGS artefact. This analysis cannot separate the two.
- **Consequence.** Purity, CCF and subclone structure fitted on the WGS should not be transferred to KH022 without this
  caveat.

### Falsifiers

- Deeper sequencing finding alt molecules at the 9 exome-absent sites in malignant nuclei, above the about 0.04
  error-floor expectation.
- Clonal k departing from 1 when s is fitted on held-out sites. Here s was fitted on the same clonal sites, so clonal
  k close to 1 is by construction.

## 4. Sensitivity of candidate-gene conclusions (script 07)

- **Measure.** log2FC = log2((CPM_tumor + 1) / (CPM_normal + 1)), pseudobulk over Gene Expression features, per
  library. Nuclei are QC-pass with the doublet union removed, as in step 13.
- **Verdict** (as step 13): enriched if min(L1, L2) >= 1; depleted if max(L1, L2) <= -1; otherwise neutral.
- Verdicts with < 200 normal nuclei are marked "not evaluable".
- All 47 candidates and controls are in `tables/candidate_sensitivity.csv`.

| scheme | tumor nuclei L1 / L2 | normal nuclei L1 / L2 | verdict changes vs current | max \|dlog2FC\| |
|---|---|---|---:|---:|
| a. current labels | 12,840 / 12,746 | 11,237 / 10,873 | – | – |
| b. strict tumor = alt >= 1 OR (hap_post_tumor >= 0.9 AND cnv_malignant), vs non-malignant | 9,491 / 9,154 | 10,815 / 10,495 | **0** | 0.16 |
| b2. as b, but the alt >= 1 arm also requires cnv_call != cnv_normal | 9,053 / 8,768 | 11,236 / 10,872 | **0** | 0.35 |
| c. strict normal = 0 alt with >= k = 11 informative ref molecules (genotype only) | 12,840 / 12,746 | **7 / 7** | not evaluable | – |
| c-sweep, k = 2 (genotype only) | 12,840 / 12,746 | 5,342 / 4,894 | 36 (artefact; see below) | 3.1 |
| c-sweep, k = 5 (genotype only) | 12,840 / 12,746 | 515 / 433 | 37 (artefact) | 5.0 |
| c4. non_malignant label AND 0 alt | 12,840 / 12,746 | 10,815 / 10,495 | **0** | 0.08 |
| c5. c4 with >= 2 ref molecules | 12,840 / 12,746 | 1,849 / 1,692 | 5 (composition shift) | 0.88 |
| d. b vs c (k = 11) | 9,491 / 9,154 | 5 / 2 | not evaluable | – |
| d2. b2 vs c4 | 9,053 / 8,768 | 10,815 / 10,495 | **0** | 0.37 |

### Choice of k

- **Rule.** k is the smallest number of informative molecules at which a true tumor nucleus shows 0 alt molecules with
  probability <= 5%.
- **Empirical P(0 alt | n) in strict malignant nuclei:** 0.77, 0.58, 0.43, 0.33, 0.26 for n = 1-5; 0.08 at n = 8;
  about 0 at n >= 11.
- **Binomial calculation** at the observed per-molecule alt rate of 0.246 also gives k = 11.
- **Only 7 nuclei per library qualify.** A genotype-only normal set is not achievable with gene-body SNVs at this depth.
- **At lower k the "normal" set is dominated by tumor.** At k = 2, 3,381 of 5,342 L1 nuclei are malignant-labelled
  epithelial. That collapses every log2FC toward 0, which is why k = 2 and k = 5 "change" 36-37 verdicts. Those changes
  are not label sensitivity.
- **c5 changes 5 verdicts:** TACSTD2, NECTIN4, EGFR, GAPDH, TP53. Requiring >= 2 ref molecules selects deep stromal
  nuclei (fibroblast and adipocyte up, T/NK down). That is a comparator-composition effect, not label error.

### Result

Every candidate's tumor-vs-non-malignant verdict survives the strict genetic tumor definitions (b, b2, d2), including:

- **Targets:** CD44, VTCN1, FOLH1, ENPP3, PRLR, ERBB4, SLC28A3, SLC6A14, HORMAD1, POLQ, KIF18A.
- **Amplicon and lineage genes.**
- **Depleted genes:** SLFN11, TACSTD2, HLA/B2M, antigen-processing genes, CD274, CDKN1A.
- **All controls.**

The largest shifts are PTPRC and COL1A1, at most 0.37 log2.

- **Why it is robust.** Malignant labels are about 94% tumor, and the non-malignant comparator is about 95% non-tumor
  and dominated by immune and stromal nuclei. Moving a few hundred nuclei between groups does not change a pseudobulk
  ratio.
- **Not covered here:** comparisons against "normal epithelium". Given section 2, any claim of the form "X is higher
  in tumor than in normal luminal epithelium" that used step 6's non_malignant/epithelial nuclei is compromised. Redo it
  against myoepithelial nuclei plus L2's HS-luminal nuclei only.

## 5. What would change these conclusions

- **The s calibration.** If the RNA/DNA allele-fraction ratio differs across sites (e.g. allele-specific expression
  concentrated in some genes), the per-group pi values shift.
  - Deep nuclei, which need little calibration, give pi = 0.99 for malignant epithelial nuclei.
  - So the 0.94 malignant precision is more likely an underestimate than an overestimate.
- **The purity / CN fit.** f uses S1b. A different CN at many sites would change s but not the model-free zero-alt
  checks.
- **The ambient model.** Varying rho from x0.5 to x2 changes precision and recall by at most 0.04.
- **The subclone test.** It rests on 7 expressed sites and 128 molecules. Without the two best-covered sites (ATP13A3
  and PRRG1, about 12 expected alt), about 9 alt would still be expected against 0 observed (p about 1e-4).

## Figures

- `figures/fig1_tumor_fraction_by_label.png`: tumor fraction by label x compartment, both libraries.
- `figures/fig2_alt_vs_ambient.png`: nuclei with >= 1 alt molecule against the ambient-only expectation.
- `figures/fig3_clonality_k.png`: presence scale k by site class, strict malignant nuclei.
- `figures/fig4_candidate_sensitivity.png`: candidate log2FC, current labels against (b) strict tumor and the
  (c, k = 2) genotype-only normal.

## Tables (`tables/`)

- **Sites:** `sites_truthset.tsv`, `site_filters.tsv`, `sites_flagged.tsv`, `leaf_loss.csv`.
- **Labels:** `label_groups*.csv`, `precision_recall*.csv`, `confusion_label_vs_genetic*.csv`, `f_scale_profile*.csv`,
  `labels_summary*.json`. The `_rho0.5` and `_rho2` suffixes are the ambient sensitivity runs.
- **Per nucleus:** `nuclei_genotype.tsv.gz` (alt/ref molecules, log10 LR, expected ambient alt).
- **Clonality:** `clonality_tests.csv`, `clonality_params.json`, `subclone_sites_detail.csv`,
  `site_obs_vs_exp_strict_malignant.csv`.
- **Sensitivity:** `candidate_sensitivity.csv`, `candidate_sensitivity_long.csv`, `sensitivity_scheme_sizes.csv`,
  `sensitivity_params.json`.
- **Transfer:** `bytes_samtools_attempt.json`, `bytes_leaf_<lib>.json`, `bytes_leaf_<lib>.ledger.json`.
