# GIAB HG008 Truth-Set Readiness Packet

Run ID: `ngs-prep-20260718T000013Z`

## Use Case
Pressure-test correctness against independent NIST tumor-normal small-variant and CNV truth probes.

## Allowed Conclusion
HG008 is a truth-set validation sample. It should improve confidence in caller correctness and CNV/SV benchmarking, not produce a Diana-style HRD interpretation.

## Sample Evidence
| evidence_id | status | detail | artifact | caveat |
| --- | --- | --- | --- | --- |
| snv_truth_panel | expanded_non_dry_passed | 40/40 HG008 truth SNVs passed tumor ALT and normal REF pileup gates. | results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json |  |
| cnv_depth_sweep | expanded_non_dry_passed | 4/4 HG008 CNV truth intervals passed normalized tumor-normal depth direction checks. Bounded reciprocal depth signal present: yes. | results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json |  |
| sv_truth_asset | expanded_non_dry_gap_identified | HG008 SV truth asset is present but no Diana SV callset exists for reciprocal-overlap confirmation. | results/clinicalization/known_answer_runs/expanded_cohort/hg008_sv_truth_asset.json |  |
| sv_cnv_reciprocal_overlap | bounded_non_dry_partial | HG008 CNV truth loss shows reduced tumor-normal depth after neutral-region normalization; SV reciprocal-overlap remains unrun. Bounded CNV depth signal: yes; normalized loss tumor-normal ratio: 0.438786. No Diana-generated SV/CNV callset or reciprocal-overlap caller output was produced in this bounded run. | results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json |  |

## HRD Adapter Status
| adapter | state | blocker | next_action |
| --- | --- | --- | --- |
| SNV correctness validation | partial_evidence | Bounded truth-pileup confirmations are present, but full caller-level recall/precision is not complete. | Run full small-variant caller concordance. |
| CNV/LOH correctness validation | partial_evidence | Bounded depth-direction checks passed, but no Diana-generated CNV segment callset or segment-level reciprocal-overlap result exists. | Run CNV calling and segment-level reciprocal-overlap against HG008 truth. |
| SV correctness validation | blocked | No Diana-generated SV callset exists for HG008; SV reciprocal-overlap remains unrun. | Run SV caller and reciprocal-overlap against HG008 v0.5 truth. |
| HRD interpretation | no_call | HG008 is a truth-set validator, not a Diana HRD interpretation sample. | Use only for pipeline correctness. |

## Blockers
- No Diana-generated CNV segment callset exists for HG008; current HG008 CNV evidence is bounded depth-direction validation, not segment-level reciprocal overlap.
- No Diana-generated SV callset exists for HG008; SV reciprocal-overlap against v0.5 truth remains unrun.

## Research Context Boundary
Use external databases only to enrich observed sample events. Do not use literature or database context to override missing inputs, failed QC, or no-call adapter states.
