# COLO829/COLO829BL Tumor-Normal Guardrail Packet

Run ID: `cloud-colo829-guardrail-20260617`

## Use Case
Demonstrate independent tumor-normal driver recovery and multi-platform BAM handling.

## Allowed Conclusion
COLO829 is an independent tumor-normal and driver-recovery guardrail. It does not establish HRD status until full SV/CNA/signature evidence is generated and benchmarked.

## Sample Evidence
| evidence_id | status | detail | artifact | caveat |
| --- | --- | --- | --- | --- |
| colo829_platform_illumina_hiseqx | expanded_non_dry_passed | COLO829 Illumina HiSeq X tumor has BRAF V600E ALT fraction 0.670968 while normal ALT fraction is 0.0. | results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_hiseqx.json |  |
| colo829_platform_pacbio_sequel | expanded_non_dry_passed | COLO829 PacBio Sequel tumor has BRAF V600E ALT fraction 0.568182 while normal ALT fraction is 0.018868. | results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_pacbio_sequel.json |  |
| colo829_platform_ont_minion | expanded_non_dry_passed | COLO829 Oxford Nanopore MinION tumor has BRAF V600E ALT fraction 0.610169 while normal ALT fraction is 0.04. | results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_ont_minion.json |  |
| colo829_platform_illumina_novaseq_phased | expanded_non_dry_passed | COLO829 Illumina NovaSeq phased tumor has BRAF V600E ALT fraction 0.753846 while normal ALT fraction is 0.0. | results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_novaseq_phased.json |  |
| sv_cna_truth_asset | expanded_non_dry_gap_identified | COLO829 SV/CNA truth assets are present but no build-matched Diana SV/CNA callset exists. | results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json |  |
| sv_cna_reciprocal_overlap | bounded_non_dry_gap_identified | COLO829 SV/CNA truth assets are present, but no SV/CNA caller output or reciprocal-overlap result was generated. | results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json |  |
| purity_illumina_metadata | expanded_non_dry_blocked_remote_index_missing | COLO829 purity illumina metadata exposes 5 runs across levels 10, 20, 25, 50, 75 but submitted BAM indexes are missing for remote slicing. | results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_illumina.json |  |
| purity_long_read_metadata | expanded_non_dry_blocked_remote_index_missing | COLO829 purity long_read metadata exposes 10 runs across levels 10, 20, 25, 50, 75 but submitted BAM indexes are missing for remote slicing. | results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_long_read.json |  |
| purity_recall_table | bounded_non_dry_blocked_remote_index_missing | COLO829 dilution BAMs are public but cannot be remotely region-sliced because ENA does not expose submitted BAI files for selected levels. | results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json |  |

## HRD Adapter Status
| adapter | state | blocker | next_action |
| --- | --- | --- | --- |
| BRAF driver guardrail | partial_evidence | BRAF V600E pileup recovery is confirmed across available platforms. | Use as a tumor-normal handling guardrail only. |
| SV/CNA benchmark | blocked | No build-matched Diana SV/CNA callset exists. | Fetch or generate build-matched COLO829 calls and run reciprocal overlap. |
| Purity sensitivity benchmark | blocked | Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested. | Transfer selected dilution BAM/FASTQ inputs and index locally before running purity recall. |
| HRD interpretation | no_call | Driver recovery does not establish HRD status. | Run full SV/CNA/signature evidence before any HRD interpretation. |

## Blockers
- COLO829 submitted BAMs and fetched hg38-lifted truth still require build reconciliation.
- No Diana SV/CNA callset exists.
- COLO829 submitted BAMs are GRCh37-style while the fetched SV truth VCF is hg38-lifted.
- Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested.

## Research Context Boundary
Use external databases only to enrich observed sample events. Do not use literature or database context to override missing inputs, failed QC, or no-call adapter states.
