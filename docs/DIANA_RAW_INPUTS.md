# Diana Raw Inputs

This is the contract for plugging Diana's real files into the project.

## Expected Files

The workflow can stage these input types:

- Tumor DNA FASTQ pairs.
- Matched normal DNA FASTQ pairs.
- Tumor or normal BAM/CRAM files with indexes.
- RNA FASTQ pairs or derived RNA files.
- Vendor VCF/CNV/SV/fusion/report files.

The strongest Diana analysis would include tumor-normal WGS plus RNA-seq. WES is still useful for coding variants, but it is weaker for genome-wide HRD signatures, CNVs, and SVs.

## Template

Generate the template:

```sh
bun run build:diana-template
```

This writes:

- `manifests/diana_raw_inputs.template.csv`
- `results/diana_raw_intake/input_contract.json`
- `results/diana_raw_intake/intake_readiness_summary.json`

Copy the template structure into:

```text
manifests/diana_raw_inputs.csv
```

Do not put placeholder paths into the strict samplesheet. Strict mode requires actual files.

## Required Metadata

Each row should identify:

- `sample_id`
- `patient_id`
- `assay`
- `modality`
- `role`
- `pair_id`
- file paths
- reference build
- platform
- library layout
- tumor purity or tumor content when known
- source/vendor notes

The exact column set is defined by the generated template and `diana_omics.diana_raw`.

## Validation

Waiting-state validation:

```sh
bun run verify:diana-raw
```

Strict validation with real files:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
bun run verify:diana-raw
```

Strict validation checks:

- The samplesheet exists.
- Required columns are present.
- Required file paths exist.
- FASTQ pairs are coherent.
- BAM/CRAM index metadata are present where applicable.
- Tumor-normal pair IDs are coherent.
- Reference metadata are present.
- Optional RNA rows are clearly separated from DNA rows.

## Stage A Recompute Packet

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \
DIANA_RAW_REQUIRE_DATA=1 \
DIANA_RAW_ANALYSIS_ID=diana_initial_raw_recompute \
bun run stage:diana-raw
```

The stage command writes:

```text
results/diana_raw_analysis/<analysis_id>/
```

That packet is the handoff point for running the public validation workflow beside Diana-specific analysis.

## Common Mistakes

- Tumor and normal rows have different `pair_id` values.
- FASTQ R1 and R2 paths are swapped or mixed across lanes.
- BAM or CRAM paths are present without indexes.
- Vendor VCFs use a different reference build than raw alignments.
- RNA files are listed as DNA, or DNA files are listed as RNA.
- A report PDF is present but the underlying VCF/CNV/SV files are absent.

## Interpretation Boundary

Passing `verify:diana-raw` means the files are staged correctly. It does not mean Diana has any specific HRD result. Interpretation requires full analysis, public truth-set sidecar validation, and reviewer sign-off.
