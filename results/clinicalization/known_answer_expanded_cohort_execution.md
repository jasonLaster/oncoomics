# Expanded Known-Answer Cohort Execution

This generated report records non-dry bounded evidence and explicit gaps across a larger representative public cohort.

- Status: `completed_with_confirmations_and_gaps`
- Targets: `29`
- Cohort groups: `5`
- Non-dry confirmations: `19`
- Partial confirmations: `1`
- Gap-identified targets: `3`
- Blocked targets: `6`
- Clinical use allowed: `0`

| Target | Group | Status | Public-doc alignment | Result |
| --- | --- | --- | --- | --- |
| hcc1395_wes_tumor_fastq | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full WES benchmark passed with 1122 exact truth matches and 0.9842 precision. |
| hcc1395_wes_normal_fastq | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full WES benchmark passed with 1122 exact truth matches and 0.9842 precision. |
| hcc1395_wes_truth_overlap | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full WES benchmark passed with 1122 exact truth matches and 0.9842 precision. |
| hcc1395_wes_contamination | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full WES benchmark passed with 1122 exact truth matches and 0.9842 precision. |
| hcc1395_wgs_tumor_fastq | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full-source WGS artifact passed with 268 exact truth matches, 631 CNV bins, 265 SBS96 SNVs, and SV evidence. |
| hcc1395_wgs_normal_fastq | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full-source WGS artifact passed with 268 exact truth matches, 631 CNV bins, 265 SBS96 SNVs, and SV evidence. |
| hcc1395_wgs_truth_depth | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full-source WGS artifact passed with 268 exact truth matches, 631 CNV bins, 265 SBS96 SNVs, and SV evidence. |
| hcc1395_wgs_cnv_bins | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full-source WGS artifact passed with 268 exact truth matches, 631 CNV bins, 265 SBS96 SNVs, and SV evidence. |
| hcc1395_wgs_sbs96 | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full-source WGS artifact passed with 268 exact truth matches, 631 CNV bins, 265 SBS96 SNVs, and SV evidence. |
| hcc1395_wgs_sv_evidence | seqc2_hcc1395 | expanded_non_dry_passed | aligned | SEQC2/HCC1395 full-source WGS artifact passed with 268 exact truth matches, 631 CNV bins, 265 SBS96 SNVs, and SV evidence. |
| hg008_tumor_wgs_remote | giab_hg008 | expanded_non_dry_passed | aligned | 40/40 HG008 truth SNVs passed tumor ALT and normal REF pileup gates. |
| hg008_normal_wgs_remote | giab_hg008 | expanded_non_dry_passed | aligned | 40/40 HG008 truth SNVs passed tumor ALT and normal REF pileup gates. |
| hg008_snv_panel_40 | giab_hg008 | expanded_non_dry_passed | aligned | 40/40 HG008 truth SNVs passed tumor ALT and normal REF pileup gates. |
| hg008_cnv_loss_depth | giab_hg008 | expanded_non_dry_passed | aligned | 4/4 HG008 CNV truth intervals passed normalized tumor-normal depth direction checks. |
| hg008_cnv_gain_depth | giab_hg008 | expanded_non_dry_passed | aligned | 4/4 HG008 CNV truth intervals passed normalized tumor-normal depth direction checks. |
| hg008_sv_truth_asset | giab_hg008 | expanded_non_dry_gap_identified | gap | HG008 SV truth asset is present but no Diana SV callset exists for reciprocal-overlap confirmation. |
| hg008_rna_paired_stats | giab_hg008 | expanded_non_dry_partial | aligned | HG008 RNA paired FASTQ stats are internally consistent but quantification has not run. |
| colo829_illumina_hiseqx_braf | colo829 | expanded_non_dry_passed | aligned | COLO829 Illumina HiSeq X tumor has BRAF V600E ALT fraction 0.670968 while normal ALT fraction is 0.0. |
| colo829_pacbio_braf | colo829 | expanded_non_dry_passed | aligned | COLO829 PacBio Sequel tumor has BRAF V600E ALT fraction 0.568182 while normal ALT fraction is 0.018868. |
| colo829_ont_braf | colo829 | expanded_non_dry_passed | aligned | COLO829 Oxford Nanopore MinION tumor has BRAF V600E ALT fraction 0.610169 while normal ALT fraction is 0.04. |
| colo829_novaseq_phased_braf | colo829 | expanded_non_dry_passed | aligned | COLO829 Illumina NovaSeq phased tumor has BRAF V600E ALT fraction 0.753846 while normal ALT fraction is 0.0. |
| colo829_sv_truth_asset | colo829 | expanded_non_dry_gap_identified | gap | COLO829 SV/CNA truth assets are present but no build-matched Diana SV/CNA callset exists. |
| colo829_cna_truth_asset | colo829 | expanded_non_dry_gap_identified | gap | COLO829 SV/CNA truth assets are present but no build-matched Diana SV/CNA callset exists. |
| colo829_purity_illumina_levels | colo829_purity | expanded_non_dry_blocked_remote_index_missing | gap | COLO829 purity illumina metadata exposes 5 runs across levels 10, 20, 25, 50, 75 but submitted BAM indexes are missing for remote slicing. |
| colo829_purity_long_read_levels | colo829_purity | expanded_non_dry_blocked_remote_index_missing | gap | COLO829 purity long_read metadata exposes 10 runs across levels 10, 20, 25, 50, 75 but submitted BAM indexes are missing for remote slicing. |
| seraseq_mrd_0pct | seraseq_ctdna_mrd | expanded_non_dry_blocked_request_or_purchase | blocked_request_or_purchase | Seraseq ctDNA MRD components are documented at 0, 0.005, 0.05, and 0.5 percent tumor fractions, but material or VCF files require request or purchase. |
| seraseq_mrd_0_005pct | seraseq_ctdna_mrd | expanded_non_dry_blocked_request_or_purchase | blocked_request_or_purchase | Seraseq ctDNA MRD components are documented at 0, 0.005, 0.05, and 0.5 percent tumor fractions, but material or VCF files require request or purchase. |
| seraseq_mrd_0_05pct | seraseq_ctdna_mrd | expanded_non_dry_blocked_request_or_purchase | blocked_request_or_purchase | Seraseq ctDNA MRD components are documented at 0, 0.005, 0.05, and 0.5 percent tumor fractions, but material or VCF files require request or purchase. |
| seraseq_mrd_0_5pct | seraseq_ctdna_mrd | expanded_non_dry_blocked_request_or_purchase | blocked_request_or_purchase | Seraseq ctDNA MRD components are documented at 0, 0.005, 0.05, and 0.5 percent tumor fractions, but material or VCF files require request or purchase. |

## Interpretation

The expanded cohort confirms public WES and WGS baseline mechanics plus bounded HG008 and COLO829 driver/CNV evidence. It also exposes the remaining strict-validation gaps: HG008 and COLO829 SV/CNA caller overlap, HG008 RNA quantification, COLO829 purity local indexing, and Seraseq MRD material or request-only VCF access.

## Next Step

Promote bounded confirmations to strict pipeline confirmations by generating caller outputs for HG008 and COLO829, running reciprocal-overlap truth comparisons, indexing purity inputs locally, and obtaining Seraseq MRD material or VCFs.
