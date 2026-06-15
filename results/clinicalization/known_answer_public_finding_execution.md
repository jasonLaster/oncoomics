# Known-Answer Public Finding Execution

This generated report records the non-dry public asset fetch and the remaining pipeline-validation gaps for each target.

- Status: `completed_with_gaps`
- Targets exercised: `10`
- Pipeline confirmations: `0`
- Gap-identified targets: `9`
- Request or purchase blockers: `1`

| Pull target | Execution status | Public assets | Pipeline confirmation | Primary gap | Next action |
| --- | --- | --- | --- | --- | --- |
| hg008_tumor_wgs | not_confirmed_input_metadata_only | 3 | not_confirmed | raw_input_and_runner_gap | Approve transfer plan, fetch HG008-T and HG008-N-D WGS inputs, then implement the non-dry benchmark runner and concordance adapter. |
| hg008_normal_wgs | not_confirmed_input_metadata_only | 3 | not_confirmed | raw_input_and_runner_gap | Approve transfer plan, fetch HG008-T and HG008-N-D WGS inputs, then implement the non-dry benchmark runner and concordance adapter. |
| hg008_tumor_rna | not_confirmed_input_metadata_only | 5 | not_confirmed | raw_input_and_runner_gap | Approve RNA transfer, fetch the selected HG008-T RNA FASTQs, and add the RNA QC or quantification smoke gate. |
| hg008_small_variant_truth | not_confirmed_truth_assets_verified | 8 | not_confirmed | truth_assets_without_pipeline_calls | Run HG008 tumor-normal WGS through the small-variant caller and compare against the v0.3 truth VCF/callable BED. |
| hg008_sv_cnv_truth | not_confirmed_truth_assets_verified | 10 | not_confirmed | truth_assets_without_pipeline_calls | Run HG008 tumor-normal WGS through SV/CNV callers and compare using reciprocal-overlap rules. |
| colo829_tumor_wgs | not_confirmed_input_metadata_only | 1 | not_confirmed | raw_input_and_runner_gap | Approve COLO829 transfer, fetch selected tumor-normal WGS inputs, then implement the driver/signature guardrail run. |
| colo829_normal_wgs | not_confirmed_input_metadata_only | 1 | not_confirmed | raw_input_and_runner_gap | Approve COLO829 transfer, fetch selected tumor-normal WGS inputs, then implement the driver/signature guardrail run. |
| colo829_sv_cna_truth | not_confirmed_truth_assets_verified | 4 | not_confirmed | truth_assets_without_pipeline_calls | Run COLO829 tumor-normal WGS through SV/CNA callers and compare against the Zenodo truth assets. |
| colo829_purity_series | not_confirmed_input_metadata_only | 4 | not_confirmed | raw_input_and_runner_gap | Approve selected dilution transfers, run each level, and compute truth-overlap recall by tumor fraction. |
| seraseq_ctdna_mrd_panel | blocked_request_or_purchase | 2 | not_confirmed | request_or_purchase_required | Request or purchase Seraseq material or variant files, then define assay-specific positive-negative and dilution gates. |
