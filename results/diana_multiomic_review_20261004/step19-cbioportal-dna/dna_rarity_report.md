# How unusual are Diana's DNA changes? (step 19)

Diana multi-omic review · 2026-10-05 · research only, not a clinical interpretation.

**Question:** how often do Diana's copy-number changes and driver mutations occur in thousands of public breast tumors,
especially triple-negative ones?

**Data:** public cBioPortal studies. Only gene symbols and study IDs were queried; nothing about Diana was sent.

| Cohort | Tumors | TNBC (receptor status) | Basal-like (PAM50) | Copy-number method |
|---|---|---|---|---|
| TCGA PanCancer Atlas | 1,070 | 155 | 171 | Genome-wide (SNP array, GISTIC) |
| METABRIC | 2,173 | 320 | 209 | Genome-wide (SNP array) |
| MSK-IMPACT 2018 | 1,918 | 174 | — | Gene panel; amplifications/deletions of panel genes only |

**Matching Diana's changes to the public calls.**
- **Amplified ("2"):** CD44 (~12 copies), ELF5/EHF (9), 11q13 (9) and 22q12 (8-10). Each is roughly 3-4 times her
  average ploidy of 2.8.
- **Gain ("+1"):** 3q (4 copies).
- **Loss ("-1"):** B2M (1 copy).
- **Caveat:** thresholds differ between our whole-genome fit and the public array calls, so treat percentages as
  approximate.

## Results

Percent of tumors with each change. Ranges are across the two genome-wide cohorts (TCGA, METABRIC).

| DNA change | Diana | TNBC | Basal-like | All breast | How unusual for TNBC |
|---|---|---|---|---|---|
| **11q13 + 22q12 + CD44 all amplified** | **yes** | **0 of 475** | 0 of 380 | **0 of 3,243** | **Not seen in any public tumor** |
| 11q13 and 22q12 both amplified | yes | 0-0.3% | 0% | 0.1-0.6% | Very rare |
| 11q13 and CD44 both amplified | yes | 0-0.9% | 0-0.5% | 0.6-1.5% | Very rare |
| 22q12 amplified (EWSR1/SPECC1L) | yes | 2-3% | 2-5% | 1-2% | Rare |
| 11q13 amplified (CCND1/CTTN/SHANK2) | yes | 3-6% (MSK 2%) | 4-7% | 16-19% | Uncommon in TNBC; common in ER+ |
| CD44 amplified | yes | ~6% | 6-8% | 2-3% | Uncommon |
| ELF5 or EHF amplified | yes | 6-9% | 6-11% | ~3% | Uncommon; usually together with CD44 |
| 3q gain (MECOM/ATR) | yes | 41-63% | 52-69% | 18-32% | Common |
| B2M copy loss | yes | 50-63% | 64-70% | 25-35% | Common |
| MYC amplified | **no** | 27-35% | 36-44% | 15-26% | Diana lacks a common TNBC driver |
| CCNE1 amplified | **no** | 8-10% | 10-11% | ~3% | — |

**Mutations in TNBC**

| Change | TCGA (n=155) | METABRIC (n=320) | MSK (n=174) |
|---|---|---|---|
| TP53 mutated (any) | 75% | 74% | 90% |
| TP53 splice-site mutation | 5.8% | 4.1% | 7.5% |
| BRCA1 somatic mutation | 5.8% | 4.4% | 2.9% |

- Diana's TP53 c.559+2T>G is at the codon-187 splice donor. MSK lists a splice variant at that site (X187_splice), so it
  is a recurrent but uncommon site.
- Somatic (non-inherited) BRCA1 mutation is itself uncommon in TNBC, about 3-6%.

**Co-amplification check**
- CD44 and ELF5/EHF are usually amplified together: 19 of 23 CD44-amplified TCGA tumors and 65 of 74 METABRIC ones.
  This is a known 11p13 amplicon.
- What is unusual is its fusion with 11q13 and 22q12:
  - any two of the three amplicons: 8 of 1,070 (TCGA) and 50 of 2,173 (METABRIC);
  - all three: none.

## What this means

1. **Diana's amplicon architecture is genuinely rare.** The 11q13 + 22q12 + CD44 structure, physically joined by WGS
   junctions (step 17), was found in none of ~3,200 genome-wide-profiled breast tumors. Any target built on it (CD44,
   SHANK2/CTTN, the chr22q12 genes) is specific to her tumor, which also means there is little published experience
   with it.
2. **The lineage amplicon is uncommon but recognized.** CD44 with ELF5/EHF appears in ~6-9% of TNBC. This supports
   step 18: her luminal-progenitor programme is partly genetic, and similar tumors exist.
3. **Her other changes are typical TNBC.** 3q gain and B2M single-copy loss occur in about half of TNBC, so B2M "one hit
   from loss" is a common TNBC situation rather than a unique risk.
4. **She lacks the most common TNBC amplifications (MYC, CCNE1).** CCNE1 amplification is a known marker of PARP
   inhibitor and platinum resistance in HR-deficient tumors, so its absence fits the HRD-driven picture.
5. **Somatic BRCA1 plus a TP53 splice-site mutation** puts her in a small group: each is present in only ~3-8% of TNBC.

## Limitations

- **Thresholds:** public calls use array/GISTIC thresholds relative to each tumor's ploidy; ours come from an absolute
  whole-genome fit. Borderline amplifications may be classified differently.
- **Physical linkage is not tested:** co-amplification in public data shows both regions are gained, not that they are
  physically joined as in Diana's tumor.
- **MSK panel:** reports amplifications only for panel genes and no shallow gains or losses. Its 3q and B2M rows were
  excluded, and CD44, ELF5 and 22q12 genes are not on the panel.
- **Cohort mix:** primary tumors are mostly untreated; MSK includes metastases.

## Files

- `fetch.py`: cBioPortal queries.
- `analyze.py`: TNBC definitions and frequencies.
- `feature_frequencies.csv`.
- Raw per-study tables: `cna_*.csv`, `mut_*.csv`, `clin*_*.csv`.
