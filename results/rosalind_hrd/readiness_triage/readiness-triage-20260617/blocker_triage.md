# Rosalind HRD Readiness Triage

Triage ID: `readiness-triage-20260617`
Packet run: `public-evidence-plus-20260617`

## Decision Board
| sample_set | decision | actionable_now | blocker_count | closed_by_runs | next_action |
| --- | --- | --- | --- | --- | --- |
| colo829 | requires_transfer_or_indexing | no | 4 |  | Transfer or index the selected public purity assets before trying to close this blocker. |
| diana_raw_intake | waiting_for_dinah_files | external | 1 |  | Fill and validate manifests/diana_raw_inputs.csv when Dinah's actual BAM/FASTQ/CRAM paths arrive. |
| hcc1395_wes | packet_has_no_blockers | no | 0 | local-validation;next-readiness-20260617 | Preserve the packet as a public-sample evidence boundary; do not promote no-call HRD adapters without required inputs. |
| hcc1395_wgs | closed_by_materialized_packet | yes | 1 | cloud-selective5-20260617;selective5-materialized-20260617 | Use the zero-blocker selective/materialized HCC1395 WGS packet as the current WGS HRD evidence-surface demo. |
| hg008 | requires_caller_or_truth_overlap_recompute | no | 3 |  | Run or containerize the relevant caller/overlap lane before changing the packet state. |

## Interpretation Boundary
This board identifies packet blockers and existing materialized packet closures. It does not promote SBS3, scarHRD, CHORD, or HRDetect-style interpretation unless the required production inputs and validation are present.

## Blocker Detail

### colo829
- Decision: `requires_transfer_or_indexing`
- Actionable now: `no`
- Closed by runs: `none`
- Next action: Transfer or index the selected public purity assets before trying to close this blocker.
- Blockers:
  - COLO829 submitted BAMs and fetched hg38-lifted truth still require build reconciliation.
  - No Diana SV/CNA callset exists.
  - COLO829 submitted BAMs are GRCh37-style while the fetched SV truth VCF is hg38-lifted.
  - Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested.

### diana_raw_intake
- Decision: `waiting_for_dinah_files`
- Actionable now: `external`
- Closed by runs: `none`
- Next action: Fill and validate manifests/diana_raw_inputs.csv when Dinah's actual BAM/FASTQ/CRAM paths arrive.
- Blockers:
  - Actual Diana BAM/FASTQ/CRAM paths have not passed strict intake validation.

### hcc1395_wes
- Decision: `packet_has_no_blockers`
- Actionable now: `no`
- Closed by runs: `local-validation; next-readiness-20260617`
- Next action: Preserve the packet as a public-sample evidence boundary; do not promote no-call HRD adapters without required inputs.
- Blockers:
  - None beyond adapter no-call boundaries.

### hcc1395_wgs
- Decision: `closed_by_materialized_packet`
- Actionable now: `yes`
- Closed by runs: `cloud-selective5-20260617; selective5-materialized-20260617`
- Next action: Use the zero-blocker selective/materialized HCC1395 WGS packet as the current WGS HRD evidence-surface demo.
- Blockers:
  - Current SV evidence summary has no discordant mapped-pair counts; regenerate full SV evidence before using WGS as the flagship HRD packet.

### hg008
- Decision: `requires_caller_or_truth_overlap_recompute`
- Actionable now: `no`
- Closed by runs: `none`
- Next action: Run or containerize the relevant caller/overlap lane before changing the packet state.
- Blockers:
  - No Diana-generated CNV callset or reciprocal-overlap result exists for HG008.
  - No Diana-generated SV callset exists for HG008 in this expanded bounded run.
  - No Diana-generated SV/CNV callset exists for HG008 in this bounded run.
