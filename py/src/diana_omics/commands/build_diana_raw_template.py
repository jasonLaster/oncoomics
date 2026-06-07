from __future__ import annotations

from ..diana_raw import DIANA_RAW_RESULTS, DIANA_RAW_TEMPLATE, diana_raw_contract, template_rows
from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, write_csv, write_json, write_text


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
                "next_step": "Copy the template to manifests/diana_raw_inputs.csv, replace placeholder paths, then run verify:diana-raw with DIANA_RAW_REQUIRE_DATA=1.",
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
            "validationCommand": contract["validationCommand"],
            "recomputeCommand": contract["recomputeCommand"],
        },
    )
    write_text(
        path_from_root("docs/DIANA_RAW_INPUTS.md"),
        """# Diana Raw Data Plug-In Contract

Status: **template ready; waiting for Diana raw FASTQ/BAM/CRAM paths**.

Use this when Diana's files arrive:

```sh
cp manifests/diana_raw_inputs.template.csv manifests/diana_raw_inputs.csv
```

Fill `manifests/diana_raw_inputs.csv` with the actual local paths and metadata, then run:

```sh
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run verify:diana-raw
DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 bun run stage:diana-raw
bun run run:all
```

The validation workflow and Diana staging workflow are intentionally separate. `bun run run:all` keeps the public validation ladder reproducible. `stage:diana-raw` checks the Diana-specific samplesheet and writes a Diana analysis packet that records exactly which inputs, reference, resource policy, and next compute commands should be used.

## Required DNA Rows

The samplesheet must contain at least:

1. One tumor DNA row.
2. One matched-normal DNA row.
3. A shared `pair_id` for the tumor-normal DNA rows.
4. Either FASTQ pairs, BAM+BAI, or CRAM+CRAI paths for each DNA row.
5. A reference policy: `reference_id`, `reference_path`, `reference_fai_path`, and `reference_dict_path`.

## Supported Input Shapes

| data_type | Required path columns |
| --- | --- |
| `FASTQ` | `fastq_1`, `fastq_2` |
| `BAM` | `bam`, `bai` |
| `CRAM` | `cram`, `crai` |
| `RNA_FASTQ` | `rna_fastq_1`, `rna_fastq_2` |

## Boundary

This contract makes Diana raw data easy to plug in without changing code. It does not make a clinical HRD claim by itself. Clinical interpretation still requires reviewer sign-off, final CNV/SV/signature policy, and any clinician-owned orthogonal validation.
""",
    )
    write_text(
        path_from_root(f"{DIANA_RAW_RESULTS}/README.md"),
        """# Diana Raw Intake

Status: **template ready**.

Artifacts:

1. `manifests/diana_raw_inputs.template.csv`
2. `docs/DIANA_RAW_INPUTS.md`
3. `results/diana_raw_intake/input_contract.json`
4. `results/diana_raw_intake/intake_readiness_summary.csv`

The project can now accept Diana raw FASTQ, BAM, or CRAM paths through `manifests/diana_raw_inputs.csv` and validate them with `bun run verify:diana-raw`.
""",
    )
    print(f"Diana raw input template ready: {DIANA_RAW_TEMPLATE}")


if __name__ == "__main__":
    main()
