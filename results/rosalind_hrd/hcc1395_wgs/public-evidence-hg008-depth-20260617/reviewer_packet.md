# SEQC2/HCC1395 WGS HRD Evidence-Surface Packet

Run ID: `public-evidence-hg008-depth-20260617`

## Use Case
Exercise the current WGS HRD evidence surfaces: BAM QC, small variants, coverage CNV bins, SBS96, and SV evidence.

## Allowed Conclusion
This sample exercises the WGS evidence surfaces needed for HRD review. It remains a partial HRD evidence packet until allele-specific CNV/LOH, production SV calls, signature thresholds, CHORD/scarHRD/HRDetect policy, and known-answer performance are locked.

## Sample Evidence
| evidence_id | status | detail | artifact | caveat |
| --- | --- | --- | --- | --- |
| wgs_pair_validation | passed | Full-source FASTQs: True; read pairs per end: 942559447; BAM validation: passed. | results/phase3_wgs_smoke/phase3_wgs_summary.json |  |
| small_variant_lane | skipped_public_bam_timing | Truth-depth eligible variants: 0; exact PASS matches: 0. | results/phase3_wgs_smoke/phase3_wgs_summary.json | Public-BAM timing runs may skip local variant calling; do not infer HRD score readiness from this alone. |
| coverage_cnv_bins | passed | 631 coverage CNV bins generated. | results/phase3_wgs_smoke/coverage_cnv_summary.json | Coverage bins are not allele-specific CNV/LOH segments. |
| sbs96_matrix | skipped_public_bam_timing | 0 usable SNV records for SBS96. | results/phase3_wgs_smoke/signature_assignment_summary.json | SBS3 interpretation remains no-call until thresholds and known-answer performance are locked. |
| sv_evidence | passed | SV evidence rows: 2; discordant mapped pairs: 0; CHORD statuses: not_assessable_metadata_only. | results/phase3_wgs_smoke/sv_evidence_summary.json | CHORD and HRDetect need validated SV caller VCF/BEDPE, not metadata-only evidence. |
| sv_caller_readiness | passed | Candidate SV caller rows: 4; discordant mapped pairs in sidecar: 0; ready for clinical interpretation: no. | results/clinicalization/sv_caller_readiness_summary.json | Use this as a readiness gate only after it agrees with the current SV evidence summary. |
| cnv_loh_readiness | passed | CNV bins: 631; allele-specific segments available: no; ready for clinical interpretation: no. | results/clinicalization/cnv_loh_readiness_summary.json | Coverage bins remain a plumbing check, not scarHRD-ready allele-specific CNV/LOH evidence. |

## HRD Adapter Status
| adapter | state | blocker | next_action |
| --- | --- | --- | --- |
| SigProfilerAssignment | not_assessable_variant_calling_skipped | Classification is deferred for low mutation count; the matrix is a real VCF-derived output, not a proxy. | Promote to ready only after the required production adapter and known-answer validation pass. |
| scarHRD | not_assessable_without_allele_specific_segments | scarHRD needs allele-specific segmented CN calls; this run validates WGS coverage-bin plumbing only. | Promote to ready only after the required production adapter and known-answer validation pass. |
| CHORD | not_assessable_requires_validated_sv_caller_vcf | CHORD-style interpretation needs full-depth SNV/indel/SV/CNV feature inputs; this validates the feature lanes. | Promote to ready only after the required production adapter and known-answer validation pass. |
| sigprofiler_sbs3 | no_call | SBS3 interpretation thresholds and known-answer performance are not locked. | validated SBS96/SBS288 mutation matrix plus reconstruction metrics and locked minimum-mutation policy |
| scarhrd | no_call | Allele-specific CNV/LOH segments are not available. | validated allele-specific copy-number segments with total/minor copy number purity and ploidy |
| chord | no_call | Validated production SV caller VCF/BEDPE input is not available. | validated somatic SNV/indel features plus production SV caller VCF or BEDPE and CNV context |
| hrdetect | no_call | Integrated HRDetect-style feature classes and model calibration are not complete. | locked six-feature HRD model inputs including substitution signatures indel signatures rearrangement signatures and CNV/LOH features |

## Blockers
- Current SV evidence summary has no discordant mapped-pair counts; regenerate full SV evidence before using WGS as the flagship HRD packet.

## Research Context Boundary
Use external databases only to enrich observed sample events. Do not use literature or database context to override missing inputs, failed QC, or no-call adapter states.
