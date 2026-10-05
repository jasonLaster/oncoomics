# Exon-only check against 59 TNBC patients (step 21)

Diana multi-omic review · 2026-10-05 · research only. RNA is not protein.

**What this is.** It extends the step 20 QC exon-only test (module 7) from 8 public TNBC tumors to a public reference
atlas.
- **Atlas:** 104 author-labelled tumor-cell samples from 59 TNBC patients (Shiao 2024, Bassez 2021, Wu 2021, HBCSCA).
- **Timepoints:** 49 pre-treatment, 55 on anti-PD-1.
- **Chemistry:** 13 samples 10x 3', 91 samples 10x 5'.
- **Method:** Diana's exonic tumor-nucleus counts (QC module 1 recount) vs the authors' count matrices, with **no bias
  model**.

**Why this test.**
- Nuclei under-sample cytoplasmic mRNA, so this comparison understates Diana for most genes. A gene that still exceeds
  the references is a conservative call.
- The QC found that the earlier bias-model approach has an empirical false-discovery rate of about 0.5 at 2x. A
  bias-model comparison against this atlas (initially drafted as "step 20") was therefore set aside in favour of this
  test.

## Results

| Gene | QC tier | Patients exceeded (any) | Median fold | Pre / on treatment | 3' / 5' fold | QC 8-tumor fold |
|---|---|---|---|---|---|---|
| SLC28A3 | A | 100% | ~107x | 100 / 100% | 131 / 104x | 48x |
| MECOM | A | 100% | ~72x | 100 / 100% | 83 / 69x | 75x |
| SLC6A14 | A | 100% | ~64x | 100 / 100% | 33 / 72x | 33x |
| HORMAD1 | A | 100% | ~49x | 100 / 100% | 9 / 76x | 38x |
| SOX6 | B | 100% | ~43x | 100 / 100% | 44 / 43x | 109x |
| ENPP3 | A | 97% | ~40x | 98 / 96% | 55 / 38x | 46x |
| ESRRG | A | 100% | ~39x | 100 / 100% | 68 / 35x | 62x |
| SHANK2 | A | 100% | ~32x | 100 / 100% | 60 / 30x | 47x |
| SPECC1L | A | 100% | ~25x | 100 / 100% | 54 / 24x | 35x |
| EHF | A | 100% | ~19x | 100 / 100% | 46 / 17x | 28x |
| FOLH1 (PSMA) | A | 99% | ~19x | 100 / 98% | 19 / 18x | 19x |
| ATR | C | 100% | ~18x | 100 / 100% | 22 / 17x | 22x |
| POLQ | A | 100% | ~16x | 100 / 100% | 13 / 16x | 21x |
| ELF5 | B | 100% | ~14x | 100 / 100% | 6.5 / 23x | 11x |
| KIF18A | A | 100% | ~11x | 100 / 100% | 11 / 11x | 15x |
| LDLRAD3 | A | 100% | ~10x | 100 / 100% | 14 / 9x | 12x |
| EWSR1 | B | 100% | ~8x | 100 / 100% | 9 / 7x | 8x |
| CD44 | B | 100% | ~6x | 100 / 100% | 7 / 6x | 6x |
| ERBB4 | D | 93% | ~19x | 92 / 95% | 45 / 13x | 30x |
| PRLR | B | 94% | ~4x | 94 / 95% | 9 / 4x | 7x |
| VTCN1 (B7-H4) | D | 42% | ~0.7x | 39 / 46% | 0.6 / 0.8x | 0.7x |
| TACSTD2 (TROP-2) | E | 16% | ~0.4x | — | — | 0.2x |
| TOP1, CCND1, EGFR, CD276 | F | 24-87% | 0.7-1.9x | — | — | typical |

Controls behave as expected:
- GAPDH and ACTB are at ~0% (nuclei bias).
- CDKN1A is at ~1%, consistent with TP53 loss.
- CSN3 is at ~97%, the expected ambient artifact.

## Conclusions

1. **The QC's Tier A genes hold up against 59 patients, before and on treatment, and in both chemistries.** These are
   HORMAD1, POLQ, SLC6A14, SLC28A3, ENPP3, FOLH1, MECOM, ESRRG, SHANK2, SPECC1L, EHF, KIF18A and LDLRAD3. Going from
   8 to 59 references changed none of them.
2. **On-treatment references do not change the picture.** These are anti-PD-1 only; no chemo-plus-immunotherapy
   references are available.
3. **Typical or below for TNBC:** B7-H4, TROP-2, TOP1, EGFR and CCND1, matching the QC.
4. **Chemistry matters for some genes.** HORMAD1 is ~9x vs 3' references but ~76x vs 5' references, and ELF5 is 6.5x vs
   23x. The 3' set (13 samples) is the closer technical match. HORMAD1 is still above every tumor in it.
5. **CD44 is above every reference, but only ~6x.** That is consistent with its 12-copy dosage. It is "amplified and
   expressed", not an extreme outlier.

**Limits**
- No single-nucleus TNBC references.
- Most references use 5' chemistry.
- No chemo-treated or pregnancy-associated tumors.
- Only the QC's candidate genes were tested, because the exonic recount covered those genes. A genome-wide exon-only
  test would need a genome-wide exonic recount of Diana's BAMs.

**Files:**
- `exon_only_vs_atlas.py`, `exon_only_vs_atlas.csv`, `run.log`.
- Atlas contents: `reference_atlas_contents.md`.


---

## Update: expanded atlas (v2: 109 TNBC patients, 2026-10-05)

The atlas grew to 109 TNBC patients with tumor cells. The new tests are below; files are `exon_only_vs_atlas_v2.csv`,
`nuclei_vs_htapp.csv`, `run_v2.log` and `run_nuclei.log`.

### A. More tumor-cell references (exon-only, as above)

- **Author-labelled whole-cell tumors (118 samples):** every Tier A gene still exceeds essentially all of them.
- **Two new reference groups:** the 11 BREAKFAST tumors sampled on chemotherapy (after one AC cycle) and the 42
  tumor-epithelium samples without author labels.
- **On-chemotherapy result:** Tier A genes exceed 91-100% of these tumors. So the signal is not simply what
  chemotherapy does to TNBC cells, although AC is not Diana's carboplatin/paclitaxel regimen.

### B. Like-for-like nuclei comparison (11 HTAPP metastatic TNBC biopsies)

This compares nuclei with nuclei, both with intronic reads counted, with no correction. It is the closest technical
match available, but these are pretreated metastatic tumors, mostly liver.

| Group | Genes | Fold vs HTAPP nuclei (median) |
|---|---|---|
| **Still far above** | SPECC1L, SLC6A14, KYNU, SLC28A3, SOX6, ERBB4, MECOM, FOLH1, HORMAD1, ELF5, ESRRG, ENPP3, EHF, LDLRAD3 | 11-290x |
| Modestly above | SHANK2, CADM1, KIF18A, EWSR1, CTTN, CD44 | 3-8x |
| **Typical** | **POLQ (1.1x), ATR (1.3x)**, TOP1, EGFR, CCND1, B7-H4 (0.8x), TROP-2 (0.6x) | 0.6-1.5x |
| Below | TAP1 0.3x, NLRC5 0.3x, PSMB9 0.4x, CD274 0.4x, CDKN1A 0.3x; but GAPDH 0.4x | 0.3-0.7x |

**What changes**
- **POLQ and ATR are not distinctive against nuclei-profiled metastatic TNBC.**
  - They are 16-18x above whole-cell tumors on exon counts.
  - Two explanations are open: (1) a residual nuclei-vs-cell effect for these genes, or (2) pretreated metastatic TNBC
    genuinely expresses high POLQ/ATR.
  - Until primary TNBC nuclei are available, call POLQ/ATR "high vs untreated primary TNBC, typical vs pretreated
    metastatic TNBC". POLQ's HRD rationale does not depend on it being an outlier.
- **The amplicon, lineage and transporter genes hold on every test:** SLC6A14, SLC28A3, SPECC1L, MECOM, SOX6, FOLH1,
  HORMAD1, ELF5/EHF, ESRRG, ENPP3, LDLRAD3.
- **Antigen-processing genes:** low against nuclei references too (TAP1, PSMB9, NLRC5 at 0.3-0.4x). GAPDH is also
  0.4x, so only part of this is specific.
