# Diana Pan-cancer ADC Atlas patient bridge

Run `adc-atlas-patient-bridge-20260904T183020Z` quantified the paired E019_S01 tumor RNA FASTQs with a GENCODE v23 GRCh38 full-decoy Salmon index.

- QA status: `passed_for_directional_comparison_with_cross_pipeline_caveat`
- Salmon mapping rate: 72.45%
- Gene-level TPM sum: 1,000,000.00
- ADC targets quantified: 23/23
- TCGA BRCA comparison status: `directionally_comparable`, not an exact patient percentile

## Highest patient target TPM values

- HER3 (ERBB3): 710.853 TPM; TCGA-BRCA band `at_or_above_p95`
- GPNMB (GPNMB): 485.048 TPM; TCGA-BRCA band `at_or_above_p95`
- Folate receptor alpha (FOLR1): 189.450 TPM; TCGA-BRCA band `at_or_above_p95`
- HER2 (ERBB2): 152.236 TPM; TCGA-BRCA band `median_to_q3`
- EGFR (EGFR): 110.351 TPM; TCGA-BRCA band `at_or_above_p95`
- TROP-2 (TACSTD2): 108.457 TPM; TCGA-BRCA band `q1_to_median`
- B7-H3 (CD276): 91.474 TPM; TCGA-BRCA band `q1_to_median`
- NaPi2b (SLC34A2): 80.720 TPM; TCGA-BRCA band `at_or_above_p95`

## Interpretation boundary

The private sample and public atlas use the same GENCODE v23 feature model and TPM scale, but Salmon versus Toil/RSEM, library preparation, specimen composition, and batch differ. Ratios and quantile bands are descriptive directional checks, not exact cohort percentiles. This single bulk sample does not support differential expression, malignant-cell localization, membrane-protein abundance, ADC eligibility, response prediction, or treatment recommendation.
