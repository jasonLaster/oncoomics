# Diana Raw BAM/FASTQ Intake Readiness Packet

Run ID: `public-evidence-plus-20260617`

## Use Case
Prepare the exact validation and staging path for Diana tumor-normal BAM, CRAM, FASTQ, and optional RNA FASTQ files.

## Allowed Conclusion
This packet proves the raw-data intake contract is ready. It does not validate Diana files or produce HRD evidence until the actual BAM/FASTQ/CRAM paths are supplied and pass strict intake validation.

## Sample Evidence
| evidence_id | status | detail | artifact | caveat |
| --- | --- | --- | --- | --- |
| intake_template | template_ready | Template: manifests/diana_raw_inputs.template.csv; samplesheet: manifests/diana_raw_inputs.csv; ready for raw data: True. | results/diana_raw_intake/intake_readiness_summary.json | Template readiness only confirms the intake surface exists. |
| input_contract | present | 30 required columns; DNA assays: WES;WGS; data types: BAM;CRAM;FASTQ;MANIFEST_ONLY;RNA_FASTQ. | results/diana_raw_intake/input_contract.json |  |
| strict_file_validation | waiting_for_diana_raw_data | Rows: 0; DNA rows: 0; tumor DNA rows: 0; normal DNA rows: 0; matched pair IDs: none. | results/diana_raw_intake/input_validation_summary.json | Expected to remain waiting until actual Diana BAM/FASTQ/CRAM paths are supplied. |
| run_path | ready_to_validate | Validate with `DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw`; stage with `DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw`. | results/diana_raw_intake/input_contract.json | Passing intake validation still does not produce an HRD score. |

## HRD Adapter Status
| adapter | state | blocker | next_action |
| --- | --- | --- | --- |
| Raw file intake | blocked_until_files | Actual Diana BAM/FASTQ/CRAM paths have not passed strict intake validation. | Copy the template to manifests/diana_raw_inputs.csv, fill actual paths and metadata, then run verify:diana-raw with DIANA_RAW_REQUIRE_DATA=1. |
| Tumor-normal DNA pairing | blocked_until_files | No validated matched tumor-normal DNA pair is staged. | Confirm tumor and normal rows share pair_id before compute. |
| Reference/index preflight | ready_to_validate | Reference files must exist and match all DNA rows when strict validation runs. | Validate reference FASTA, FAI, and dict paths in verify:diana-raw. |
| HRD interpretation | no_call | No Diana sample evidence exists yet. | Run the staged DNA feature lanes and public validation sidecars before interpretation. |

## Blockers
- Actual Diana BAM/FASTQ/CRAM paths have not passed strict intake validation.

## Research Context Boundary
Use external databases only to enrich observed sample events. Do not use literature or database context to override missing inputs, failed QC, or no-call adapter states.
