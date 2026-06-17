# SEQC2/HCC1395 WES HRD Readiness Packet

Run ID: `cloud-hcc1395-wes-20260617`

## Use Case
Demonstrate tumor-normal WES intake, BAM QC, contamination review, Mutect2 calling, and truth-overlap reporting.

## Allowed Conclusion
This sample demonstrates WES small-variant and caller-readiness behavior. It does not support a genome-wide HRD scar, SV, SBS3, CHORD, or HRDetect-style score.

## Sample Evidence
| evidence_id | status | detail | artifact | caveat |
| --- | --- | --- | --- | --- |
| fastq_validation | passed | 4/4 FASTQ rows passed validation. | results/full_wes_benchmark/full_wes_fastq_validation.csv |  |
| bam_validation | passed | 2/2 BAM rows passed validation. | results/full_wes_benchmark/full_wes_bam_validation.csv |  |
| somatic_small_variant_truth_overlap | passed | 1122 exact PASS truth matches; recall 0.8585; precision 0.9842. | results/full_wes_benchmark/full_wes_benchmark_summary.json | WES truth-overlap evidence does not establish genome-wide HRD signatures, SVs, or scarHRD. |
| contamination | passed | Contamination estimate 0.0. | results/full_wes_benchmark/full_wes_benchmark_summary.json |  |
| truth_overlap_detail | passed | Detailed truth-overlap summary is present. | results/full_wes_benchmark/truth_overlap_benchmark_summary.json |  |

## HRD Adapter Status
| adapter | state | blocker | next_action |
| --- | --- | --- | --- |
| HRR SNV/indel evidence | partial_evidence | Small-variant evidence exists but HRR event curation is not a final HRD score. | Curate observed HRR events if Diana WES/WGS calls contain them. |
| Biallelic/LOH evidence | no_call | Allele-specific CNV/LOH segments are unavailable. | Run allele-specific CNV/LOH tooling before assessing second hits. |
| SBS3 | no_call | WES is not sufficient for locked genome-wide SBS3 interpretation. | Use WGS mutation matrix plus locked thresholds. |
| scarHRD | no_call | Allele-specific total/minor copy-number segments are unavailable. | Generate FACETS/ASCAT/PURPLE-like segments. |
| CHORD | no_call | Validated SV caller VCF/BEDPE and full feature vector are unavailable. | Run validated SV/CNV/small-variant feature adapters. |
| HRDetect-style model | no_call | Integrated calibrated feature vector is unavailable. | Lock component adapters and model calibration before scoring. |

## Blockers
- None beyond the listed adapter no-call boundaries.

## Research Context Boundary
Use external databases only to enrich observed sample events. Do not use literature or database context to override missing inputs, failed QC, or no-call adapter states.
