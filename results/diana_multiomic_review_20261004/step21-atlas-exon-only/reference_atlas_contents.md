# Public single-cell reference atlas (v2, 2026-10-05)

Details are in `inventory.md`, `manifest.csv` and `README.md`. The v1 report is `report_v1.md`, and the v1 data files
are kept as `*_v1`. Research use only.

## TNBC tumors with ≥50 tumor cells (distinct patients), v1 → v2

The full table is in `tnbc_summary_v1_v2.csv`.

| | v1 | v2 | Added by |
|---|---|---|---|
| **TNBC with tumor cells** | **65** | **109** | |
| … with author/3CA malignant calls | 62 | 83 | HTAPP, MPE, Gao |
| … single-nucleus | 0 | 12 | HTAPP frozen biopsies, all metastatic (11 are 3' v3) |
| … 3' / 5' chemistry | 14 / 51 | 56 / 51 | |
| … pre-treatment | 52 | 71 | |
| … on chemotherapy | 0 | 11 | BREAKFAST, after 1 cycle of AC (10 paired with pre-treatment) |
| … after neoadjuvant chemotherapy | 6 | 9 | |
| … after chemo + pembrolizumab | 0 | 2 | GSE302453; timing not stated |
| … anti-PD-1 window | 43 | 43 | Bassez, Shiao |
| … metastatic, pretreated | 0 | 20 | |
| … germline BRCA1 | 4 | 4 | No new BRCA1 tumors in open data |

**Other counts:**
- TNBC with any data: 135.
- ER+ / HER2+: 117 / 22.
- Unknown subtype: 19.
- Normal donors: unchanged (~273 plus 18 pooled libraries).

**Size:** about 11.5 GB more downloaded, about 50 GB on disk in total.

## Gaps

- **TNBC count:** 109 against the ~150 target. The remaining large cohorts need a login (HTAN/Synapse), are controlled
  access, or are unreleased.
- **Nuclei:**
  - All 12 single-nucleus TNBC samples are metastatic, pretreated biopsies, mostly liver.
  - 4 patients changed receptor status from their primary tumor.
  - There are no primary TNBC nuclei.
- **Regimen:**
  - The on-chemo samples are after AC cycle 1, not carboplatin/paclitaxel.
  - Only 2 samples are on chemo + pembrolizumab, with unstated timing.
- **Labels:** most new tumor cells have no author malignant label. They are kept as `tumor_epi_unlabeled`, assigned by
  marker-scored clusters. GSE252175 and GSE302453 are low confidence.
- **No new BRCA1 tumors, and no pregnancy-associated tumors.**
- **Gene coverage** varies by study; mask with `measured_in_<study>`.
