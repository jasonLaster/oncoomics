from __future__ import annotations

from ...diana_raw import (
    DIANA_RAW_RESULTS,
    DIANA_RAW_S3_INBOX_URI,
    DIANA_RAW_TEMPLATE,
    diana_raw_contract,
    template_rows,
)
from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, write_csv, write_json, write_text


def main() -> None:
    ensure_dir(path_from_root(DIANA_RAW_RESULTS))
    rows = template_rows()
    contract = diana_raw_contract()
    write_csv(path_from_root(DIANA_RAW_TEMPLATE), rows, contract["requiredColumns"])
    write_json(path_from_root(f"{DIANA_RAW_RESULTS}/input_contract.json"), {"generatedAt": iso_now(), **contract})
    write_csv(
        path_from_root(f"{DIANA_RAW_RESULTS}/intake_readiness_summary.csv"),
        [
            {
                "status": "template_ready",
                "template": DIANA_RAW_TEMPLATE,
                "actual_samplesheet": contract["samplesheet"],
                "ready_for_diana_raw_data": "yes",
                "ready_to_interpret": "no",
                "next_step": "Run plan:diana-raw-handoff, copy the template to manifests/diana_raw_inputs.csv, replace placeholder paths, then run verify:diana-raw with DIANA_RAW_REQUIRE_DATA=1.",
            }
        ],
    )
    write_json(
        path_from_root(f"{DIANA_RAW_RESULTS}/intake_readiness_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "template_ready",
            "template": DIANA_RAW_TEMPLATE,
            "actualSamplesheet": contract["samplesheet"],
            "readyForDianaRawData": True,
            "readyToInterpret": False,
            "handoffPlanCommand": contract["handoffPlanCommand"],
            "validationCommand": contract["validationCommand"],
            "recomputeCommand": contract["recomputeCommand"],
        },
    )
    write_text(
        path_from_root("docs/operations/diana-raw-inputs.md"),
        f"""# Diana Raw Inputs

Use this document when Diana's real files arrive and you need to tell the project where they are.

## What This Does

This contract validates and stages file paths. It does not interpret HRD by itself.

Supported input types:

- Tumor DNA FASTQ pairs.
- Matched normal DNA FASTQ pairs.
- Tumor or normal BAM/CRAM files with indexes.
- RNA FASTQ pairs or derived RNA files.
- Vendor VCF/CNV/SV/fusion/report files.

The strongest Diana analysis would include tumor-normal WGS plus RNA-seq. WES is still useful for coding variants, but it is weaker for genome-wide HRD signatures, CNVs, and SVs.

## How To Fill The Samplesheet

Generate the template:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template
```

Write the current pre-arrival handoff plan:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics plan:diana-raw-handoff
```

Copy it:

```sh
cp manifests/diana_raw_inputs.template.csv manifests/diana_raw_inputs.csv
```

Fill `manifests/diana_raw_inputs.csv` with actual local paths and metadata. Do not leave placeholder paths in strict mode.

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

## Map A Delivered GCE/S3 Manifest

If the sender followed the GCE upload guide, keep their `manifest.csv` and
`checksums.sha256` with the accepted local delivery and generate the strict
Diana samplesheet from those two small text files:

```sh
DIANA_RAW_DELIVERY_MANIFEST=data/raw/diana/2026-07-14-echo-personalis/manifest.csv \\
DIANA_RAW_DELIVERY_CHECKSUMS=data/raw/diana/2026-07-14-echo-personalis/checksums.sha256 \\
DIANA_RAW_DELIVERY_ROOT=data/raw/diana/2026-07-14-echo-personalis \\
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \\
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-samplesheet-from-delivery
```

The mapper:

- verifies the sender's manifest SHA-256 values against `checksums.sha256`;
- normalizes `matched_normal` to the strict `normal` role;
- pairs `reads1`/`reads2` and `R1`/`R2` FASTQ records;
- writes one strict row per FASTQ lane pair;
- keeps the selected Diana analysis reference on FASTQ rows because raw FASTQs
  are not intrinsically tied to the sender's alignment reference;
- skips delivered BAMs when their `reference_build` is not compatible with the
  selected analysis reference;
- skips RNA BAMs because the strict intake contract represents RNA FASTQs only.

After mapping, stage files locally and run strict validation with file checks
enabled:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv \\
DIANA_RAW_REQUIRE_DATA=1 \\
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
```

## Arrival Checklist

When the files arrive:

1. Confirm whether the bundle contains FASTQ, BAM, CRAM, VCF/CNV/SV, RNA FASTQ, reports, or a mixture.
2. Confirm tumor-normal pairing and use the same `pair_id` for matched DNA rows.
3. Confirm the reference build, contig naming, and index files before compute.
4. Record tumor purity, tumor content, normal type, platform, and vendor notes when known.
5. Confirm that cloud upload, storage, and the proposed analysis destination are approved for the data classification before scheduling Batch or S3 work.
6. Verify the delivery manifest, source-side SHA-256 values, object count, total bytes, indexes, and reference metadata before intake.
7. Rerun `plan:diana-raw-handoff` after filling the samplesheet to capture the current state before strict validation.

## S3 Inbox Location

Diana's raw files should be uploaded or transferred to this inbox prefix:

```text
{DIANA_RAW_S3_INBOX_URI}/
```

Do not place Diana files under `cache/phase3_wgs/`, the results bucket, or the
Nextflow work bucket. The `diana/inbox/` prefix is public-read storage for
approved deliveries: anonymous users may list and download current object
versions, while anonymous writes and deletes stay denied.

Uploads require Diana-issued credentials scoped to one assigned
`YYYY-MM-DD-source-name/` prefix. Never email credentials. Use destination
SSE-S3 (`AES256`) so direct public downloads do not need AWS KMS grants.

If anonymous writes succeed, treat the deployed access policy as a security
incident and stop intake until it is remediated.

See [Diana Public Raw S3 Upload And Transfer](diana-raw-s3-upload.md) for
authenticated upload and bucket-to-bucket transfer instructions.
See [Diana Public Analysis Downloads](diana-public-data-download.md) for public
read and outbound transfer instructions.

## Validate The Files

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
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
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw
```

The stage command writes:

```text
results/diana_raw_analysis/<analysis_id>/
```

## Refresh The Rosalind Intake Packet

After strict validation and staging pass:

```sh
ROSALIND_HRD_SAMPLE_SET=diana_raw_intake ROSALIND_HRD_RUN_ID=diana-raw-<analysis_id> PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

Use this packet to show that Diana files passed intake and pairing checks before any HRD interpretation starts.

## Supported Input Shapes

| data_type | Required path columns |
| --- | --- |
| `FASTQ` | `fastq_1`, `fastq_2` |
| `BAM` | `bam`, `bai` |
| `CRAM` | `cram`, `crai` |
| `RNA_FASTQ` | `rna_fastq_1`, `rna_fastq_2` |

## Common Mistakes

- Tumor and normal rows have different `pair_id` values.
- FASTQ R1 and R2 paths are swapped or mixed across lanes.
- BAM or CRAM paths are present without indexes.
- Vendor VCFs use a different reference build than raw alignments.
- RNA files are listed as DNA, or DNA files are listed as RNA.
- A report PDF is present but the underlying VCF/CNV/SV files are absent.

## Interpretation Boundary

Passing `verify:diana-raw` means the files are staged correctly. It does not mean Diana has any specific HRD result. Interpretation requires full analysis, public truth-set sidecar validation, and reviewer sign-off.
""",
    )
    write_text(
        path_from_root(f"{DIANA_RAW_RESULTS}/README.md"),
        f"""# Diana Raw Intake

Status: **template ready**.

Artifacts:

1. `manifests/diana_raw_inputs.template.csv`
2. `docs/operations/diana-raw-inputs.md`
3. `results/diana_raw_intake/input_contract.json`
4. `results/diana_raw_intake/intake_readiness_summary.csv`
5. `results/diana_raw_intake/dinah_handoff_plan.md`

The project can now accept Diana raw FASTQ, BAM, or CRAM paths through `manifests/diana_raw_inputs.csv`, plan the handoff with `PYTHONPATH=src /usr/bin/python3 -m diana_omics plan:diana-raw-handoff`, and validate paths with `PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw`.

Public-read S3 intake prefix:

```text
{DIANA_RAW_S3_INBOX_URI}
```
""",
    )
    print(f"Diana raw input template ready: {DIANA_RAW_TEMPLATE}")


if __name__ == "__main__":
    main()
