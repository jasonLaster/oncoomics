# Diana Raw Analysis Packet

Status: **staged**.

Analysis ID: `echo-personalis-20260714`

Samplesheet: `manifests/diana_raw_inputs.csv`

DNA rows: `10`

RNA rows: `1`

Matched DNA pair IDs: `DIANA_WES_immunoid;DIANA_WGS_wgs`

## Run Alongside Validation

1. `PYTHONPATH=src /usr/bin/python3 -m diana_omics run:all`
2. `DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw`
3. `DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 DIANA_RAW_ANALYSIS_ID=echo-personalis-20260714 PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw`
4. `ROSALIND_HRD_SAMPLE_SET=diana_raw_intake ROSALIND_HRD_RUN_ID=diana-raw-echo-personalis-20260714 PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet`

The staged packet records Diana raw inputs and the exact validation sidecar. It is designed so Diana's HRD recompute can be compared against the public SEQC2/HCC1395 validation outputs in the same repository.

## Boundary

This packet stages computation. It does not make a treatment-changing HRD call until full-depth DNA results, CNV/SV/signature outputs, and reviewer sign-off are complete.
