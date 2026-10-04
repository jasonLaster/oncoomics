# Step 5: allele-specific copy number (tumor/normal WGS), subject01

Research prioritization only. This is not a clinical result. All numbers come from one FFPE tumor WGS (~40-55x tumor,
~50x normal) plus a deep exome taken from a different tissue piece. Run 2026-10-03. This resumes an earlier agent's
partial run: its seqz-derived tracks, segmentations, FACETS run and grid search were reused, not redone.

## 0. Bottom line

| question | answer | confidence |
|---|---|---|
| purity (tumor **cell** fraction) / ploidy | **~0.35 (0.32-0.39) / ~2.8 (2.5-2.9)** | moderate-high |
| WGD | **yes, one doubling likely**: major CN >= 2 over 67-87% of the autosomal genome in every plausible fit | moderate-high |
| TP53 c.559+2T>G | **on every retained copy; no wild-type TP53 left.** 17p LOH (2:0 or 3:0, depending on fit). Purity-free test: exome VAF/expected 1.05 (0.97-1.13); WGS 14/27 vs 0.40 | high |
| BRCA1 c.81-1G>A | **the wild-type haplotype is lost (17q LOH), and the variant sits on the retained haplotype.** DNA VAF is 0.83x (0.71-0.96) the all-copies expectation in the deep exome. Single-nucleus pre-mRNA is 97% mutant (100/103) | high for biallelic loss of wild-type; moderate for "every retained copy" |
| BRCA2 S2695L | LOH region, but the variant is on **one** of 2-3 copies (WGS 7/54; m=2 rejected, p=0.002). Not a second hit; ClinVar likely benign | high |
| HRD scars (HRD-LOH + TAI + LST) | **67-99** across plausible fits and settings; **56-99** including rejected fits. **>= 42 in every fit** | high for ">= 42"; the absolute value depends on method |
| HLA (chr6:29.6-33.4 Mb) | **no clonal LOH of an HLA haplotype.** CN ~4-5, allelic imbalance, minor haplotype at ~1-2 copies. Lowest at HLA-A (minor CN ~0.6-1.0), where subclonal or partial loss cannot be excluded | moderate (WGS in the HLA region is mismapping-prone) |
| B2M (chr15:44.7 Mb) | **single copy (1:0, LOH)** in every plausible fit. A 30.6-Mb somatic Manta deletion (chr15:19.9-50.4 Mb) supports it. No coding SNV/indel on the remaining copy; one intronic SNV, likely clonal | high for 1:0 |

## 1. Inventory: what was reused and what is new

- **Reused** (from the earlier agent's run):
  - binned Sequenza seqz checkpoints, parsed into GC-corrected depth and het-SNP BAF tracks (`scripts/01-02b`);
  - joint logR+BAF PCF segmentation (`03`) and the ASCAT-style grid (`04` -> `fit_landscape.csv`);
  - state assignment (`08`), scarHRD re-implementation (`09`), segmentation sensitivity (`12`, `sensitivity/`);
  - FACETS 0.6 on Modal with cval 100/150/300 and alternative dipLogR (`07`, `facets/`);
  - exome BRCA1 local BAF (`11`).
- **New in this session**:
  - one evaluation of all candidate fits against the same data (`16`);
  - Strelka2 somatic SNVs from the sibling step8 run, used as the clonal-SNV check (no consensus VCF existed yet; see §9);
  - WGS BAM-based HLA and B2M BAF (`17`); exome TP53 local BAF (`19`);
  - variant/HLA/B2M/HRD integration (`18`); focal table (`20`); HLA gene windows (`21`).
- **Superseded**:
  - The earlier `vaf/` purity estimate of 0.28 used seqz candidates. Low-VAF calls there are artifact-rich (see §2), so it is replaced.
  - `known_variants.tsv` (seqz-era WGS counts, and a "S3" p0.48/psi1.54 solution) is replaced by `variant_states_by_fit.tsv`.

## 2. Candidate fits and how one was chosen

Candidates evaluated (`eval/fit_diagnostics.tsv`):

- **S1**: custom joint segmentation (260 segments) with integer states at p 0.32 / psi 2.92. This is the best local optimum of the grid.
- **S1b**: the same segments at p 0.35 / psi 2.80, the purity the clonal SNV peaks favour.
- **FACETS**: cval 100/150/300 with all alternative dipLogR levels. FACETS cval300 with dipLogR -0.133 (p 0.37 / psi 2.52) is essentially the Serova ASCAT solution.
- **S2**: p 0.48 / psi 4.9, the WGD-of-S1 twin.
- **Low-ploidy FACETS** (psi ~1.5) and the **July-22 Sequenza** fit (p 0.31 / psi 1.6).

**Purity from clonal SNVs.** Source: Strelka2 PASS calls with SomaticEVS >= 16, n = 8,379.

- PASS calls with EVS < 16 are dominated by VAF < 0.08 C>T and T>C changes, which look like artifacts, so they are excluded.
- The fit is a truncated-binomial mixture with clonal peaks at m*p/(p*n + 2(1-p)) plus a subclonal component, run separately by state class.
- Under S1 states the class estimates are: 1:1 -> 0.34 (0.33-0.36), 2:0 -> 0.36 (0.35-0.37), 2:2 -> 0.36 (0.33-0.39), 3:0 -> 0.32 (0.29-0.34).
- Under FACETS states they are 0.37-0.40.
- BAF alone gives:
  - main 2:0 cluster b 0.33 -> p 0.34;
  - 1:0 regions b 0.39-0.40 -> p 0.33.

**Choice.** The primary fit is **S1** (states). **S1b** is the purity-sensitivity companion. **FACETS c150** and **FACETS c300 dip-0.133** are the independent-caller checks. Reasons:

- S1/S1b pass every checklist item.
- S1/S1b have the best BAF and depth agreement and the highest SNV likelihood.
- FACETS agrees on purity (0.37-0.39), ploidy (2.5-2.9), LOH fraction (0.44) and the key locus states. Its weaknesses are listed in the checklist table.

### Diagnostics against the checklist (`memory: cn-fit-and-nuclei-sanity-checks`)

| check | S1 0.32/2.92 | S1b 0.35/2.80 | FACETS c150 0.39/2.64 | FACETS c300 dip-0.133 0.37/2.52 | S2 0.48/4.90 | FACETS low-ploidy 0.42/1.49 | Sequenza Jul-22 0.31/1.6 |
|---|---|---|---|---|---|---|---|
| genome below own CN=0 ratio (want ~0) | 0 | 0 | 0.005% | 0 | 0 | 0.5% | **3.5%** (12.9% in its own normalisation) |
| CNt=0 share (want small) | 0 | 0 | 3.7%* | 4.7%* | 0 | **25.6%** | **14.6%** |
| somatic variant on a CNt=0 segment | none | none | none | none | none | **MTOR, PTPN23** | **BRCA1, MTOR** |
| ploidy (from states) | 2.94 | 2.84 | 2.85 | 2.57 | 4.94 | **1.36** | 2.26 (param 1.6) |
| segments (<1 Mb) | 260 (33) | 260 (33) | 1200 (465) | 609 (142) | 260 (33) | 1200 (465) | **4169 (3394)** |
| BAF agreement: length-weighted mean abs(b_obs - b_exp) | **0.014** | 0.018 | 0.043 | 0.040 | 0.014 | 0.047 | 0.040 |
| depth agreement: mean abs(dlogR) | **0.068** | 0.073 | 0.136 | 0.112 | 0.069 | 0.181 | 0.214 |
| clonal-SNV log-lik per SNV (higher = better) | **-2.620** | -2.625 | -2.683 | -2.664 | -2.763 | -2.807 | -2.742 |
| SNVs with VAF above the max clonal VAF the state allows (p<0.001) | 0.14% | 0.06% | 0.22% | 0.33% | 0 | 0.77% | 1.1% |
| LOH fraction | 0.44 | 0.44 | 0.44 | 0.44 | **0.0006** | 0.46 | 0.42 |
| scRNA haplotype loss on 17/13q/9 (tumor-haplotype fraction 0.87 in malignant nuclei; BRCA1 pre-mRNA 100/103 mutant) | consistent (LOH) | consistent | consistent | consistent | **inconsistent** (no LOH; predicts >= 25% wild-type BRCA1 molecules) | consistent | n/a |
| WGD (major CN >= 2 fraction) | 0.87 | 0.85 | 0.72 | 0.67 | 1.00 | 0.21 | 0.53 |
| H&E (slide B nuclei 28-32%, area 46%) | consistent | consistent | consistent | consistent | marginal | marginal | consistent |

\* **FACETS CN0 calls are not homozygous deletions.** Its 102-132 Mb of CN0 has length-weighted median observed BAF 0.43, and 63% of that length has b < 0.45. A true CN0 gives b = 0.5. Examples where tumor alleles are clearly present:

- chr15 22-32 and 40-46 Mb (incl. B2M), b 0.38-0.40;
- chr22 15-22 Mb;
- 5q end;
- 1p 18-48 Mb (called 1:1 at b 0.39).

These are FACETS lcn/tcn assignment errors (`facets_cn0_vs_baf.tsv`). This is why FACETS states are used as a cross-check, not as the primary fit.

**Rejected:**

- **S2.** It has no LOH anywhere, which contradicts the scRNA haplotype loss and the 97% mutant BRCA1 pre-mRNA. It also has the worst SNV likelihood (about 1,200 log-units below S1).
- **Low-ploidy FACETS and Sequenza Jul-22.** CN0 calls sit under somatic variants, and a large share of the genome is CN0.

## 3. BRCA1, TP53, BRCA2: is the variant on the only retained copy?

WGS counts are Strelka2 tier-1 (PASS). Exome counts are fragments from step7. Expected VAF = m*p/(p*n + 2(1-p)). **The purity-free test** in any LOH state is: a variant on all copies has VAF = 1 - 2b, with b the local minor-allele fraction. Full table: `variant_states_by_fit.tsv`; exome tests: `exome_purity_free_tests.tsv`.

| variant | WGS state (S1 / S1b / FACETS c150 / c300) | WGS alt/depth (VAF) | WGS expected VAF | exome: local b -> all-copies VAF; observed | verdict |
|---|---|---|---|---|---|
| **TP53 c.559+2T>G** (17p) | 3:0 / 2:0 / 2:0 / 2:0 | 14/27 (0.52; CI 0.32-0.71) | all copies 0.35-0.41 (purity-free 1-2b = 0.40, P(>=14) = 0.14); one copy 0.14-0.20 (p <= 2e-4) | b 0.335 (327 SNPs) -> 0.33; observed 441/1269 = 0.348; ratio **1.05 (0.97-1.13)**; one-copy p = 7e-56 | **mutant on every copy; wild-type TP53 lost (LOH)** |
| **BRCA1 c.81-1G>A** (17q21) | 2:0 / 2:0 / 1:0 / 1:0 | 7/34 (0.21; CI 0.09-0.38) | all copies 0.23-0.35 (1-2b = 0.34, P(<=7) = 0.07); one of two copies 0.16-0.18 | b 0.365 (113 SNPs) -> 0.27; observed 134/598 = 0.224; ratio **0.83 (0.71-0.96)**, p = 0.011 vs all copies; half-copies (0.135) p = 3e-9 | **wild-type haplotype lost; variant on the retained haplotype**; small DNA shortfall vs "every copy" (see below) |
| BRCA2 p.S2695L (13q) | 2:0 / 2:0 / 3:0 / 3:0 | 7/54 (0.13) | m=1 0.16 (p 0.5-0.7); m=2 0.31-0.35 (p 0.0005-0.003) | n/a (exome 14.8%) | on **one** of 2-3 copies (post-LOH); not a second hit |
| MTOR P1125A (1p, 1:0) | 1:0 all fits | 4/54 (0.07) | 0.19-0.25 (p 0.002-0.024) | exome 9.4% | **subclonal** |
| PIKFYVE I1548T (2q, 2:1) | 2:1 / 2:1 / 2:2 / 2:2 | 10/62 (0.16) | m=1 0.14-0.15 | exome 8.7% | clonal single copy in WGS piece; lower in exome |
| TSC2 R59W, PTPN23 P981A, OTUD4, F5 | see table | | | | OTUD4 and F5 fit clonal m=1 in WGS but are absent in the exome (the known WGS/Altera-only subclone) |

How the BRCA1 evidence fits together:

1. **LOH is real.** The haplotype imbalance at 17q21 is LOH in both specimens (WGS b 0.33, exome b 0.365). The scRNA phasing shows the same haplotype retained in malignant nuclei: tumor-haplotype fraction 0.87, with 100% phase agreement against WGS allele direction.
2. **The mutation is on the retained haplotype.** In KH022 malignant nuclei the mutant allele is 100/103 molecules. These are nuclei, which are pre-mRNA-rich, and the site is intronic -1, so the reads come from unspliced RNA. NMD would lower the mutant share, not raise it, so this means essentially no wild-type BRCA1 template in malignant nuclei.
3. **The DNA VAF is 15-20% below "every retained copy".** The causes cannot be separated here:
   - (a) allele-specific capture or mapping bias at this site;
   - (b) a minority of tumor cells (up to ~30%) carrying an unmutated copy of the retained haplotype;
   - (c) local CN at the locus differing from the 2-Mb BAF window.

   The exome and WGS do exclude the alternative that the variant sits on only one of two retained copies in all tumor cells (exome p = 3e-9).

   **Practical reading:** biallelic BRCA1 inactivation (splice-site variant plus loss of the wild-type haplotype) in the dominant tumor population. Whether every last cell carries it is not resolved.

**Is 17q truly copy-neutral?** It depends on the fit:

- S1: 2:0 (CN2 against ploidy ~2.9, so a mild relative loss, logR -0.2);
- FACETS: 1:0 at higher purity.

This is why the scRNA sees haplotype loss with no expression-dosage change. Either way there is no wild-type BRCA1 haplotype.

## 4. HLA and B2M (vaccine-design relevant)

WGS BAM-based BAF: MAPQ >= 30, normal-het 0.30-0.70, gene-body SNPs reported separately because they are mismapping-prone. Combined with GC-corrected depth. Files: `hla_b2m/hla_b2m_windows.tsv`, `hla_b2m_states_by_fit.tsv`, `hla_gene_windows_by_fit.tsv`, `figures/hla_b2m_baf.png`.

| window (hg38) | SNPs | logR | tumor b (95% CI) | continuous CN (S1 ... FACETS c300) | minor-haplotype CN | nearest integer state (S1) |
|---|---|---|---|---|---|---|
| 6p22.1 flank 28.0-29.6 Mb | 395 | +0.18 | 0.445 (0.44-0.455) | 3.3-3.9 | 1.3-1.5 | 2:1 |
| HLA class I 29.6-31.5 (A, G, F, E, C, B) | 5,844 | +0.32 | 0.395 (0.395-0.395) | 4.0-4.7 | 1.2-1.4 | 3:1 |
| - HLA-A +/-50 kb (non-gene / gene-body SNPs) | 1,434 / 223 | +0.31 | 0.355 / 0.310 | 3.9-4.6 | **0.9-1.0 / 0.6** | 4:1 |
| - HLA-B +/-50 kb | 504 / 127 | +0.35 | 0.415 / 0.43 | 4.2-4.9 | 1.4-1.8 | 3:2 |
| - HLA-C +/-50 kb | 13 / 4 | +0.40 | 0.375 (0.35-0.405) | 4.4-5.2 | 1.2-1.4 (wide) | - |
| class III 31.5-32.4 | 1,028 | +0.35 | 0.435 | 4.1-4.9 | 1.6-1.8 | 3:2 |
| class II 32.4-33.4 (DR, DQ, DP) | 4,604 | +0.41 | 0.41 | 4.5-5.3 | 1.5-1.8 | 4:2 |
| 6p21.3 flank 33.4-35.0 | 1,357 | +0.21 | 0.42 | 3.5-4.1 | 1.2-1.4 | 2:1 |
| **B2M +/-250 kb** | 105 | -0.40 | 0.405 (0.39-0.42) | 1.1-1.3 | **0.08-0.22** | **1:0** |
| B2M +/-1.5 Mb | 1,280 | -0.48 | 0.385 | 0.85-1.0 | ~0 | 1:0 |

**HLA findings:**

- No clonal LOH of an HLA haplotype. At CN 4-5, full LOH would give b ~0.23-0.26, far below every window. The minor haplotype is retained at ~1-2 copies across class I, II and III, and the major haplotype is gained (6p gain).
- HLA-A has the lowest minor CN (~0.6-1.0, against 1.4-1.8 at HLA-B and class II). That fits a 4:1 state there, or partial/subclonal loss of the minor HLA-A haplotype in a fraction of tumor cells.
- Allele-level HLA LOH (LOHHLA/DASH-type analysis with the patient's HLA typing) is still needed. Mismapping in HLA genes widens the per-SNP spread visibly in the figure.
- Strelka called no SNVs or indels in HLA-A/B/C. Its sensitivity there is low.

**B2M findings:**

- B2M is hemizygous (1:0) in every plausible fit. This agrees with Serova's "single-copy loss". FACETS c300 dip-0.133 calls it 0:0, which BAF contradicts.
- The remaining copy has no coding SNV or indel by Strelka2.
- One intronic SNV is present: chr15:44,717,154 G>T, intron 3 of MANE ENST00000648006, ~800 bp after exon 3 and ~450 bp before exon 4 (the 3' UTR exon), VAF 7/41 = 0.17. A clonal variant on the single copy would be expected at ~0.19. Its effect is unknown.
- Loss of the remaining B2M copy would abolish HLA-I presentation, so B2M expression and IHC are worth confirming.

## 5. HRD scars (`hrd_scars_all_fits.tsv`, `figures/hrd_sum_ranges.png`)

Definitions (re-implemented in `09_hrd_scars.py` as in scarHRD v0.1.1; reproduces the stored scarHRD output on the July-22 segments as 24/18/28 against 24/20/28):

- **HRD-LOH** (Abkevich 2012): LOH segments >= 15 Mb, excluding whole-chromosome LOH.
- **TAI** (Birkbak 2012): telomeric allelic imbalance not crossing the centromere.
- **LST** (Popova 2012): breaks between adjacent >= 10 Mb segments after smoothing < 3 Mb. Raw LST, not ploidy-adjusted.
- **HRD-sum >= 42** is the Telli 2016 / Myriad myChoice cut-off. It was defined on SNP arrays with Myriad's own pipeline, so WGS-derived values are not calibrated to it.

| set | n | HRD-sum | HRD-LOH | TAI | LST |
|---|---|---|---|---|---|
| plausible: S1/S1b over 6 segmentations (gamma 80-640, K 10-40) and purity +/- 0.03 | 18 | **88-99** | 15-24 | 33-37 | 33-47 |
| plausible: FACETS cval 100/150/300 x dipLogR -0.12..-0.25 | 6 | **67-79** | 10-23 | 23-28 | 25-35 |
| rejected: S2 (psi 4.9) | 6 | 69-79 | 0 | 33-38 | 35-44 |
| rejected: low-ploidy FACETS (psi ~1.5) | 3 | 56-57 | 15-21 | 13-17 | 22-24 |
| rejected: Sequenza Jul-22 (our re-implementation) | 1 | 70 | 24 | 18 | 28 |

- **HRD-sum >= 42 is robust.** The minimum over every fit and setting, including the rejected ones, is 56. LST is >= 22 everywhere, above Popova's ploidy-dependent cut-offs (15 near-diploid, 20 near-tetraploid).
- **The absolute value is method-dependent.** Custom segments give 88-99 and FACETS gives 67-79. The gap is mostly TAI (33-37 vs 23-28), likely from how short telomeric segments are resolved or merged. Quote "HRD-high, ~70-100 depending on caller", not a point value.

## 6. Genome-wide state (S1), WGD, arm summary vs scRNA

- **WGD.** One whole-genome doubling is likely. Major CN >= 2 covers 67-87% of the genome in all plausible fits. Ploidy is ~2.6-2.9 with 44% of the genome LOH, the classic HRD-TNBC pattern of LOH followed by doubling. S2 would imply a second doubling and is rejected.
- **Arms** (`arm_summary_S1.tsv`):
  - LOH-dominant: 3p, 5q, 6q, 7p, 9p, 9q, 10q, 13q, 14q, 15q, 16q, 17p (3:0), 17q (2:0), 18p, 21q, 22q.
  - Gains: 1q (4:1), 3q (4:1), 7q (3:1), 10p (3:2), 11p/q (CN ~4.4), 6p (2:2-3:2), 20p (2:2), 8q distal (MYC 5:1).
  - Near-balanced: 4p (1:1), 18q (1:1), 12q.
- **Against single-nucleus data** (`arm_vs_scrna_correlations.json`), both libraries:
  - per-arm expression-CNV score vs S1 arm mean CN: Spearman 0.73-0.74;
  - vs mean logR: 0.68-0.70;
  - scRNA allele-imbalance excess vs WGS imbalance: 0.62.

  The arms with the strongest scRNA haplotype loss (17, 13q, 9) are LOH at CN 2-3 in S1, close to the ploidy. That explains "haplotype loss without dosage change".

## 7. Focal / driver loci (`focal_loci_by_fit.tsv`)

| gene | S1 | S1b | FACETS c150 | FACETS c300 dip-0.133 | S1 segment | S1 local CN +/-50 kb | reading |
|---|---|---|---|---|---|---|---|
| TACSTD2 (1p32) | 3:1 | 3:1 | 3:1 | 3:1 | 13.2 Mb, logR +0.16 | 4.4 | modest gain. Lies in a 31-Mb somatic Manta tandem duplication (chr1:51.2-82.3 Mb). Not amplified |
| SLFN11 (17q12) | 2:0 | 2:0 | 2:0 | 1:0 | 29 Mb, logR -0.22 | 2.6 | LOH, relative loss. Fits low tumor SLFN11 RNA in scRNA |
| TOP1 (20q12) | 2:1 | 2:1 | 1:1 | 1:1 | 15.3 Mb | 3.7 | near-ploidy |
| ERBB3 (12q13) | 1:1 | 1:1 | 1:1 | 0:0* | 9.5 Mb, logR -0.24 | 2.8 | balanced, relative loss; *FACETS CN0 contradicted by BAF 0.475 |
| CD274 (9p24) | 3:0 | 3:0 | 3:0 | 3:0 | 14.8 Mb | 3.6 | LOH at ~ploidy; no amplification |
| MYC (8q24) | 5:1 | 4:1 | 3:1 | 3:1 | 20.8 Mb, logR +0.46 | 5.0 | broad 8q gain (~1.7-2x ploidy), not focal |
| CCNE1 (19q12) | 2:1 | 2:1 | 1:0 | 1:1 | 12.5 Mb, logR -0.14 | 2.1 | no gain or amplification |
| PTEN (10q23) | 2:0 | 2:0 | 2:1 | 2:0 | 50.5 Mb | 3.2 | LOH; no homozygous deletion |
| RB1 (13q14) | 2:0 | 2:0 | 3:0 | 2:0 | 38.8 Mb | 3.3 | LOH; no homozygous deletion |
| TP53 (17p13) | 3:0 | 2:0 | 2:0 | 2:0 | 9.0 Mb | 1.8 | LOH + clonal splice variant on all copies |
| BRCA1 (17q21) | 2:0 | 2:0 | 1:0 | 1:0 | 29 Mb | 1.9 | LOH + splice variant on the retained haplotype |
| BRCA2 (13q13) | 2:0 | 2:0 | 3:0 | 3:0 | 38.8 Mb | 2.7 | LOH; S2695L on one copy |
| B2M (15q21) | 1:0 | 1:0 | 1:0 | 0:0* | 20.8 Mb, logR -0.40 | - | single copy; Manta 30.6-Mb deletion |

- No high-level focal amplifications and no homozygous deletions at these loci in any plausible fit.
- No somatic SV breakpoints (Manta PASS) fall inside PTEN, RB1, BRCA1, BRCA2, TP53, MYC, SLFN11 or the HLA region.
- Events below ~100 kb would be missed by this segmentation.

## 8. Comparison to earlier and external claims

- **Sequenza July 22 (p 0.31, psi 1.6, HRD-sum 72).** It fails the checklist:
  - 3.5% of genome below its own CN0 ratio here (12.9% in its own normalisation);
  - 14.6% of genome at CN0;
  - BRCA1 and MTOR variants sitting on CN0;
  - 3,394 segments under 1 Mb.

  Its HRD-sum (72; 70 in our re-implementation) lands inside today's range by coincidence. Do not cite it.
- **July 17 "HRD 62".** Unverifiable (no callset). It sits below the plausible range here (67-99) but agrees on HRD-high (>= 42).
- **Serova ASCAT (purity 0.37, ploidy 2.4, GoF 91.6; B2M single-copy loss; HLA LOH not assessed).**
  - Purity agrees: 0.32-0.39 here, and clonal SNVs give 0.33-0.40.
  - Ploidy 2.4 is at the low edge. The FACETS dipLogR -0.12/-0.13 alternatives (psi 2.46-2.52) reproduce it, and S1/S1b favour ~2.8-2.9. These are the same tumor genome on two absolute scales; the key locus states do not change.
  - B2M single copy is confirmed.
  - HLA: no clonal haplotype LOH (see §4).
  - ASCAT GoF is not comparable to the metrics here.
- **H&E** (step10). Slide B nuclei-count tumor cellularity is ~28-32%. ASCAT/FACETS/S1 purity is already a tumor-**cell** fraction, so it compares directly. Agreement is reasonable. The step10 table converts it as if it were a DNA fraction, which is not needed.

## 9. Limitations

- **One FFPE WGS at ~40-55x.**
  - Single-variant VAFs have wide CIs (BRCA1 7/34, TP53 14/27).
  - Low-VAF Strelka PASS calls are artifact-rich; only EVS >= 16 calls were used.
  - The step8 consensus somatic VCF did not exist at run time, so Strelka2 alone was used. Re-run `18_integrate.py` (VAF part) and the SNV-purity check when it appears.
- **The exome is a different tissue piece** (exome purity ~0.25-0.27 from 17p/17q BAF). It is used only for purity-free tests.
- **Purity and ploidy trade off.** S1 at psi ~2.9 and FACETS/ASCAT-like at psi ~2.5 are both acceptable. Integer states at some loci (TP53 3:0 vs 2:0; BRCA1 2:0 vs 1:0) depend on that choice. The LOH conclusions and the purity-free tests do not.
- **The custom segmentation is not a published caller**, although FACETS agrees on the main conclusions.
  - FACETS has its own errors here: spurious CN0 and 1:1 calls over imbalanced segments.
  - PURPLE/ASCAT were not run.
  - The scarHRD re-implementation reproduces the stored scarHRD output except for TAI (18 vs 20).
- **HLA.** Read mismapping in HLA genes; no HLA typing; no allele-specific HLA tool. Subclonal or HLA-A-restricted loss cannot be excluded.
- **BRCA1 DNA VAF shortfall** (0.83x expected) is unexplained; see §3.
- **Subclonality.** Integer-state fits ignore subclonal CN. Several segments (e.g. HLA class I b 0.395) sit between integer states.
- **Transfer and compute.**
  - S3 transfer this task, cumulative: WGS ~8.35 GB (including 0.32 GB new for HLA/B2M), exome ~0.40 GB (including 0.23 GB new for TP53), seqz ~0.86 GB. Total **~9.6 GB** of the 20 GB cap.
  - No Modal jobs were run in this session.
