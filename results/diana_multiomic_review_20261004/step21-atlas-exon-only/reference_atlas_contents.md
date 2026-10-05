# Public single-cell reference atlas: what was built (2026-10-05)

The atlas was built by a background agent. Details are in `inventory.md`, `manifest.csv` and `README.md`. Research
use only.

**Targets:** ~150 TNBC tumors and ~200 normal-breast donors.

| Category | Distinct patients | Detail |
|---|---|---|
| TNBC, any data | 90 | Zhang 2021's 16 tumor biopsies contain immune cells only |
| TNBC with tumor cells (≥50 malignant/tumor-epithelial cells) | **65** | Shiao 2024 28, Bassez 2021 18, Pal/Gao 11, Wu 2021 8 |
| … before treatment | 52 | |
| … on treatment | 43 | All anti-PD-1 windows (~1 dose pembrolizumab ± radiation); none on chemo + pembrolizumab |
| … same patient before and on | 33 | |
| … germline BRCA1 | 4 | Pal 2021. No source records somatic BRCA1 loss |
| ER+ / HER2+ tumors | 64 / 15 | |
| Tumors, subtype unknown | 35 | |
| Normal-breast donors | ~273, plus 18 pooled libraries (~80 donors) | 38 BRCA1 carriers; parity recorded for 64 |
| Normal donors profiled as both nuclei and cells | 17 | Kumar 2023 |

**Size:** ~38 GB downloaded, ~40 GB on disk.

## Gaps

- **No TNBC single-nucleus data.** The only tumor nuclei are 3 metastatic tumors of unknown subtype.
- **Chemistry mismatch.**
  - 51 of 65 TNBC tumors use 10x 5' chemistry; Diana's sample is 3' v4.
  - Corrections should be fitted per study or per chemistry.
- **No pregnancy-associated tumors.**
  - Lactation is represented only by milk-derived cells from 10 donors.
  - Parity fields exist for 64 normal donors.
- **Uneven malignant labels.**
  - One integrated atlas labels all epithelium "Malignant"; those cells are kept as `tumor_epi_unlabeled`.
  - Bassez has no normal-epithelium class.
  - Zhang cell types were assigned by the agent.
- **Uneven gene coverage.** Bassez lacks PTPRC, and one normal object stores 15k genes. Use the `measured_in_<study>`
  masks.
- **Skipped sources.**
  - Slyper 2020: NCBI returned 403.
  - Karaayvaz 2018: non-UMI chemistry.
  - HTAN and controlled-access raw reads: not attempted.

## Recommended use

1. Compare Diana with author-labelled TNBC tumor cells, splitting pre- and on-treatment, and report per-gene
   percentiles (step 20).
2. Fit the technical correction separately for 3' and 5' studies. Check the nuclei correction against the 17
   same-donor nuclei-vs-cells pairs.
3. Compare with the BRCA1 tumors, the BRCA1-carrier normal epithelium, and the parity/lactation ranges.
