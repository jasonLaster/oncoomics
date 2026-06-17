# Dinah Raw File Handoff Plan

Status: `waiting_for_dinah_files`
Samplesheet: `manifests/diana_raw_inputs.csv`
Analysis ID: `diana_raw_initial`

## Current State

- DNA rows: `0`
- RNA rows: `0`
- Matched pair IDs: `none`
- Structural errors: `1`
- Warnings: `1`

## Handoff Steps

| step | name | command_or_action | success_evidence | boundary |
| --- | --- | --- | --- | --- |
| 1 | refresh_template_and_contract | `PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template` | manifests/diana_raw_inputs.template.csv; results/diana_raw_intake/input_contract.json | Template readiness only; no Diana files are validated. |
| 2 | copy_and_fill_samplesheet | `cp manifests/diana_raw_inputs.template.csv manifests/diana_raw_inputs.csv` | Tumor and matched normal DNA rows contain real local paths, reference metadata, and shared pair_id. | Do not leave template placeholder paths or pending metadata in strict mode. |
| 3 | cloud_upload_permission_gate | `Record whether human-data cloud upload is allowed before S3, Batch, or external transfer.` | Reviewer-visible approval note in samplesheet notes/caveat or analysis packet. | No AWS Batch or S3 upload for human data until permission is explicit. |
| 4 | strict_validate_diana_inputs | `DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw` | results/diana_raw_intake/input_validation_summary.json status passed | Passing validation proves files and pairing are staged; it is not an HRD result. |
| 5 | stage_diana_raw_analysis_packet | `DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 DIANA_RAW_ANALYSIS_ID=diana_raw_initial PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw` | results/diana_raw_analysis/diana_raw_initial/analysis_packet.json | Staging records inputs and planned commands; compute lanes still require review. |
| 6 | refresh_rosalind_raw_intake_packet | `ROSALIND_HRD_SAMPLE_SET=diana_raw_intake ROSALIND_HRD_RUN_ID=diana-raw-diana_raw_initial PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet` | results/rosalind_hrd/diana_raw_intake/diana-raw-diana_raw_initial/reviewer_packet.md | The packet should remain no-call until downstream feature lanes pass. |
| 7 | refresh_readiness_triage | `ROSALIND_HRD_TRIAGE_PACKET_RUN=public-evidence-hg008-depth-20260617 ROSALIND_HRD_TRIAGE_ID=diana-raw-diana_raw_initial-triage PYTHONPATH=src /usr/bin/python3 -m diana_omics triage:rosalind-hrd-readiness` | results/rosalind_hrd/readiness_triage/diana-raw-diana_raw_initial-triage/blocker_triage.md | Triage should show file-arrival blockers closed only after strict validation passes. |
| 8 | route_first_compute_lane | `Use WGS rows for WGS feature lanes; use WES rows for small-variant mechanics; keep RNA as context.` | A reviewed lane-specific command plan in results/diana_raw_analysis/<analysis_id>/recompute_command_plan.csv. | Do not compute scarHRD, CHORD, SBS3, or HRDetect-style results until their adapters and policies are locked. |

## Interpretation Boundary

This plan prepares intake and routing only. It does not validate Dinah's actual files, run HRD feature lanes, or support a clinical HRD interpretation until strict validation, downstream evidence generation, public sidecar checks, and reviewer sign-off are complete.
