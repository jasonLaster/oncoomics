# Known-Answer Public Finding Confirmation

This generated status answers whether the current Diana Omics analysis confirms each expanded known-answer pull target.

- Status: `passed`
- Confirmed targets: `0`
- Bounded non-dry confirmations: `5`
- Partial bounded non-dry results: `1`
- Not-run or blocked targets: `10`
- Ready for clinical interpretation: `no`

| Pull target | Public finding check | Current confirmation | Analysis artifact | Next gate |
| --- | --- | --- | --- | --- |
| hg008_tumor_wgs | HG008-T is the first Cancer GIAB tumor sample and should be analyzed as the tumor member of the HG008 tumor-normal WGS pair. | bounded_non_dry_confirmed | results/clinicalization/known_answer_runs/hg008/input_provenance_summary.json | No-call until HG008-T WGS input files are approved downloaded checksum verified and run. |
| hg008_normal_wgs | HG008-N-D is a paired normal sample for the HG008 tumor and should be analyzed as the normal member of the HG008 tumor-normal WGS pair. | bounded_non_dry_confirmed | results/clinicalization/known_answer_runs/hg008/input_provenance_summary.json | No-call until HG008-N-D WGS input files are approved downloaded checksum verified and run. |
| hg008_tumor_rna | HG008-T bulk RNA-seq should validate RNA intake and quantification plumbing but is not an HRD-positive truth label. | not_confirmed_gap_identified | results/clinicalization/known_answer_runs/hg008/rna_qc_summary.json | No-call until HG008-T RNA files are approved downloaded checksum verified and run. |
| hg008_small_variant_truth | NIST HG008-T v0.3 somatic small-variant benchmark should support SNV indel recall and precision measurement inside callable regions. | bounded_non_dry_confirmed | results/clinicalization/known_answer_runs/hg008/small_variant_concordance_summary.json | No-call until HG008 small-variant truth assets and WGS inputs are approved downloaded checksum verified and run. |
| hg008_sv_cnv_truth | NIST HG008-T v0.5 somatic SV and CNV benchmark should support reciprocal-overlap SV and CNV correctness summaries. | bounded_non_dry_partial | results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json | No-call until HG008 SV/CNV truth assets and WGS inputs are approved downloaded checksum verified and run. |
| colo829_tumor_wgs | COLO829 is a metastatic melanoma tumor cell line in a documented matched tumor-normal reference standard and should be analyzed as the tumor member. | bounded_non_dry_confirmed | results/clinicalization/known_answer_runs/colo829/input_provenance_summary.json | No-call until COLO829 tumor WGS input files are approved downloaded checksum verified and run. |
| colo829_normal_wgs | COLO829BL is the matched lymphoblastoid normal line for COLO829 and should be analyzed as the normal member. | bounded_non_dry_confirmed | results/clinicalization/known_answer_runs/colo829/input_provenance_summary.json | No-call until COLO829BL normal WGS input files are approved downloaded checksum verified and run. |
| colo829_sv_cna_truth | The COLO829 Zenodo truth set provides final somatic SV truth and copy-number alteration files for independent SV/CNA benchmarking. | not_confirmed_gap_identified | results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json | No-call until COLO829 SV/CNA truth assets and WGS inputs are approved downloaded checksum verified and run. |
| colo829_purity_series | Selected COLO829 dilution levels should show lower variant or truth-overlap sensitivity as tumor fraction decreases. | not_confirmed_gap_identified | results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json | No-call until selected COLO829 purity inputs labels and truth assets are approved downloaded checksum verified and run. |
| seraseq_ctdna_mrd_panel | Seraseq ctDNA MRD Panel Mix includes 0 percent 0.5 percent 0.05 percent and 0.005 percent tumor fractions for MRD positive-negative and dilution validation. | blocked_request_or_purchase | results/clinicalization/known_answer_runs/seraseq_mrd/positive_negative_summary.json | No-call until Seraseq material or variant files are obtained and assay-specific acceptance ranges are established. |
