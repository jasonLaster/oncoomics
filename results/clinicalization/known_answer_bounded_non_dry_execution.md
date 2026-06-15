# Known-Answer Bounded Non-Dry Execution

This generated report records real remote-read probes for the expanded public known-answer targets.

- Status: `completed_with_bounded_results_and_gaps`
- Targets: `10`
- Bounded confirmations: `5`
- Partial bounded results: `1`
- Gap-identified targets: `2`
- Blocked targets: `2`
- Strict full-pipeline confirmations: `0`

| Pull target | Bounded status | Pipeline confirmation | Evidence | Result |
| --- | --- | --- | --- | --- |
| hg008_tumor_wgs | bounded_non_dry_passed | bounded_confirmed | remote_indexed_bam_pileup | HG008-T carries truth ALT alleles while HG008-N-D remains reference-like across the bounded SNV panel. |
| hg008_normal_wgs | bounded_non_dry_passed | bounded_confirmed | remote_indexed_bam_pileup | HG008-T carries truth ALT alleles while HG008-N-D remains reference-like across the bounded SNV panel. |
| hg008_tumor_rna | bounded_non_dry_gap_identified | not_confirmed | public_fastq_stats_only | HG008 RNA stats are present and paired, but no RNA quantification or truth target was run. |
| hg008_small_variant_truth | bounded_non_dry_passed | bounded_confirmed | truth_vcf_remote_bam_pileup | 10/10 HG008 truth SNVs had tumor ALT support and normal REF support. |
| hg008_sv_cnv_truth | bounded_non_dry_partial | bounded_partial_cnv_depth_only | truth_cnv_remote_bam_depth | HG008 CNV truth loss shows reduced tumor-normal depth after neutral-region normalization; SV reciprocal-overlap remains unrun. |
| colo829_tumor_wgs | bounded_non_dry_passed | bounded_confirmed | remote_indexed_bam_pileup | COLO829 tumor has BRAF V600E ALT support while COLO829R normal remains reference-like at the same locus. |
| colo829_normal_wgs | bounded_non_dry_passed | bounded_confirmed | remote_indexed_bam_pileup | COLO829 tumor has BRAF V600E ALT support while COLO829R normal remains reference-like at the same locus. |
| colo829_sv_cna_truth | bounded_non_dry_gap_identified | not_confirmed | truth_assets_only_with_driver_pileup_context | COLO829 SV/CNA truth assets are present, but no SV/CNA caller output or reciprocal-overlap result was generated. |
| colo829_purity_series | bounded_non_dry_blocked_remote_index_missing | not_confirmed | ena_metadata_and_failed_remote_region_probe | COLO829 dilution BAMs are public but cannot be remotely region-sliced because ENA does not expose submitted BAI files for selected levels. |
| seraseq_ctdna_mrd_panel | blocked_request_or_purchase | not_confirmed | source_access_blocker | Seraseq ctDNA MRD material or variant files are not freely downloadable for non-dry analysis. |
