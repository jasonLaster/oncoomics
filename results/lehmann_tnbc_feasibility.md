# Lehmann TNBC Subtype Feasibility

## Bottom Line

The current 28-sample HRD reference panel can be cross-checked against the official Lehmann TCGA TNBC supplementary table, but it cannot be used to compute new Lehmann/TNBCtype calls from the current RNA marker lane. The panel has 8 official TCGA Lehmann calls and 20 no-calls relative to the 2016 TCGA TNBC table.

For Diana's sample, Lehmann subtype computation belongs in the RNA/WTS lane. It needs genome-wide tumor expression, TNBC-only normalization or an equivalent locked classifier input, clinical ER/PR/HER2 confirmation, and a locked TNBCtype/TNBCtype-4 implementation or documented Vanderbilt web-tool run.

## Current TCGA Panel Cross-Check

| sample_id | lehmann_tnbctype | lehmann_refined_tnbctype | xena_er | xena_pr | xena_her2 |
| --- | --- | --- | --- | --- | --- |
| TCGA-A1-A0SO-01 | M | M | Negative | Negative | Negative |
| TCGA-A2-A0T0-01 | M | M | Negative | Negative | Negative |
| TCGA-AO-A129-01 | BL1 | BL1 | Negative | Negative | Negative |
| TCGA-AR-A2LH-01 | LAR | LAR |  |  |  |
| TCGA-BH-A42U-01 | MSL | LAR |  |  |  |
| TCGA-A7-A6VW-01 | BL2 | BL2 |  |  |  |
| TCGA-AR-A0U4-01 | IM | BL1 | Negative | Negative | Negative |
| TCGA-BH-A0WA-01 | M | M | Negative | Negative | Negative |

## Evidence Status Counts

| status | count |
| --- | --- |
| basal_context_but_not_official_lehmann_tnbc | 2 |
| confirmed_from_lehmann_tcga_s1 | 8 |
| no_call_not_in_official_lehmann_tcga_tnbc | 5 |
| not_applicable_not_tnbc_from_available_fields | 13 |

## Feasibility Notes

- Source table: `https://doi.org/10.1371/journal.pone.0157368.s006`.
- The current repo RNA context uses marker genes only; it is not TNBCtype.
- The Vanderbilt TNBCtype tool expects a genome-wide gene-expression CSV and recommends preprocessing/normalization on TNBC samples only.
- Missing panel rows should stay no-call for Lehmann subtype unless they are re-qualified as TNBC and run through a locked classifier.

## Non-Dry Expression Classifier Validation

- Run mode: `non_dry_expression_classifier_validation`
- Expression records fetched: 719938
- Assessable TCGA TNBC samples: 179 / 180
- Local TNBCtype match rate: 124 / 179 (0.6927)
- Local refined TNBCtype match rate: 142 / 179 (0.7933)

This confirms the expression-data acquisition and signature-scoring path works end to end. It does not replace the locked Vanderbilt TNBCtype centroid/permutation implementation, because the local signature-score helper is a related public method rather than the exact official classifier.

