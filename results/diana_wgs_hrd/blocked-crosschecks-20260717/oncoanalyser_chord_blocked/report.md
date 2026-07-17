# Oncoanalyser and CHORD — blocked method report

- execution_status: `not_run`
- evidence_status: `blocked`
- interpretation_status: `no_call`
- classification_authorization: `none`
- patient_result: `none`
- generated_at: `2026-07-17T19:30:00+00:00`

The method was not run. This artifact contains no patient result, reports no inferred result, and authorizes no HRD classification.

## Alias scope

`subject01_tumor`, `subject01_normal`

No direct identifiers, source object names, or patient-derived values are included.

## Intended computation — not executed

- Run nf-core/oncoanalyser in WGTS mode against the selected GRCh38_hmf resource bundle.
- Independently align and process the paired WGS lanes, call small variants with SAGE, structural variants with ESVEE, and allele-specific copy number, purity, and ploidy with AMBER, COBALT, and PURPLE.
- Give CHORD the PURPLE somatic small-variant VCF, PURPLE structural-variant VCF, and exact reference resources.
- Compute SNV, indel, and structural-variant contexts and the CHORD probability and category fields, subject to CHORD QC and Diana validation policy.

## Exact prerequisites

- Original checksummed paired tumor and normal FASTQ lanes with an alias-only lane mapping and samplesheet.
- Exact GRCh38_hmf reference and WiGiTS resource identities, with every file bound to SHA-256.
- An nf-core/oncoanalyser commit and compatible Nextflow version pinned in the route contract.
- Every workflow process image mirrored and pinned by immutable digest with license review, SBOM, and provenance.
- A tested linux/amd64 Nextflow controller and Batch runtime plus a durable, validated CHORD output parser.
- Passed dry-run and known-answer validation with locked QC, classification, and change-control policy.

## Current blockers

- The active contract contains no original FASTQ lane hashes or alias-only lane mapping for this route.
- The HMF reference and resource identities are not frozen.
- The workflow process images are tag-based and unmirrored rather than digest-attested.
- The x86 controller and Batch runtime are not applied and tested.
- No durable CHORD result parser is present, and license and intended-use review is incomplete.
- Known-answer performance, QC limits, interpretation thresholds, and change-control authorization are not locked.

## Next gate

Reconcile and hash the alias-only FASTQ lanes and HMF resources; mirror every process image by digest with SBOM and provenance; apply and test the x86 Nextflow runtime and CHORD parser; then pass dry-run and known-answer validation before paired-WGS execution or interpretation.

## Primary sources

- [nf-core/oncoanalyser 2.3.0](https://github.com/nf-core/oncoanalyser/tree/234fd82acc16a3beb01bf301900d83346b6ec812) — `234fd82acc16a3beb01bf301900d83346b6ec812`
- [oncoanalyser usage contract](https://github.com/nf-core/oncoanalyser/blob/234fd82acc16a3beb01bf301900d83346b6ec812/docs/usage.md) — `234fd82acc16a3beb01bf301900d83346b6ec812`
- [oncoanalyser CHORD module](https://github.com/nf-core/oncoanalyser/blob/234fd82acc16a3beb01bf301900d83346b6ec812/modules/local/chord/main.nf) — `234fd82acc16a3beb01bf301900d83346b6ec812`
- [HMF CHORD 2.1.2 source](https://github.com/hartwigmedical/hmftools/tree/ecb124834636dc722a2450375fa6126bc86689f9/chord) — `ecb124834636dc722a2450375fa6126bc86689f9`

## Interpretation boundary

Execution remains `not_run`; evidence remains `blocked`; interpretation remains `no_call`; classification authorization remains `none`. No patient result exists in this report or its manifest.
