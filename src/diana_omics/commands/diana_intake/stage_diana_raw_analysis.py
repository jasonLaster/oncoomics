from __future__ import annotations

import os

from ...diana_raw import DIANA_RAW_RESULTS, diana_raw_contract
from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json, write_text
from .verify_diana_raw import check_files, selected_samplesheet, validate_rows

PY_COMMAND = "PYTHONPATH=src /usr/bin/python3 -m diana_omics"


def analysis_id() -> str:
    return os.environ.get("DIANA_RAW_ANALYSIS_ID", "diana_raw_initial")


def main() -> None:
    samplesheet = selected_samplesheet()
    path = path_from_root(samplesheet)
    if not path.exists():
        raise SystemExit(f"Missing {samplesheet}. Run build:diana-template, copy the template, and fill in actual Diana paths first.")

    rows = parse_csv(read_text(path))
    errors, warnings, summary = validate_rows(rows, require_files=check_files())
    if errors:
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)

    output_dir = f"results/diana_raw_analysis/{analysis_id()}"
    ensure_dir(path_from_root(output_dir))
    dna_rows = [row for row in rows if row.get("role") in {"tumor", "normal"} and row.get("assay") in {"WGS", "WES"}]
    rna_rows = [row for row in rows if row.get("assay") == "RNA" or row.get("data_type") == "RNA_FASTQ"]
    command_rows = [
        {
            "step": 1,
            "name": "validate_public_reference_ladder",
            "command": f"{PY_COMMAND} run:all",
            "purpose": "Recompute the public validation ladder alongside Diana-specific staging.",
        },
        {
            "step": 2,
            "name": "validate_diana_inputs",
            "command": f"DIANA_RAW_SAMPLESHEET={samplesheet} DIANA_RAW_REQUIRE_DATA=1 {PY_COMMAND} verify:diana-raw",
            "purpose": "Fail fast if Diana raw paths, pair roles, or reference metadata are incomplete.",
        },
        {
            "step": 3,
            "name": "stage_diana_analysis_packet",
            "command": f"DIANA_RAW_SAMPLESHEET={samplesheet} DIANA_RAW_REQUIRE_DATA=1 DIANA_RAW_ANALYSIS_ID={analysis_id()} {PY_COMMAND} stage:diana-raw",
            "purpose": "Write the Diana-specific run packet, input manifest, and reviewer boundary.",
        },
    ]
    if any(row.get("assay") == "WGS" for row in dna_rows):
        command_rows.append(
            {
                "step": 4,
                "name": "run_wgs_feature_lanes",
                "command": "Use the staged DNA rows with the Phase 3 WGS runner settings: alignment, Mutect2, coverage-CNV bins, SBS96 matrix, and SV evidence. For full WGS, set final interval/scatter policy before launch.",
                "purpose": "Recompute DNA HRD feature inputs from Diana WGS once compute policy is approved.",
            }
        )
    else:
        command_rows.append(
            {
                "step": 4,
                "name": "run_wes_small_variant_lanes",
                "command": "Use the staged DNA rows with the Phase 2F WES benchmark mechanics: alignment or supplied BAMs, duplicate marking, contamination, Mutect2, and small-variant evidence.",
                "purpose": "Recompute Diana WES small-variant HRD-supporting evidence once capture/resource policy is approved.",
            }
        )

    write_csv(path_from_root(f"{output_dir}/diana_input_manifest.csv"), rows)
    write_csv(path_from_root(f"{output_dir}/recompute_command_plan.csv"), command_rows)
    write_json(
        path_from_root(f"{output_dir}/analysis_packet.json"),
        {
            "generatedAt": iso_now(),
            "status": "staged",
            "analysisId": analysis_id(),
            "samplesheet": samplesheet,
            "summary": summary,
            "warnings": warnings,
            "contract": diana_raw_contract(),
            "dnaRows": dna_rows,
            "rnaRows": rna_rows,
            "validationSidecar": {
                "publicValidationCommand": f"{PY_COMMAND} run:all",
                "dianaInputValidationCommand": f"DIANA_RAW_SAMPLESHEET={samplesheet} DIANA_RAW_REQUIRE_DATA=1 {PY_COMMAND} verify:diana-raw",
                "outputVerifier": f"{PY_COMMAND} verify:outputs",
            },
            "interpretationBoundary": "Staged Diana raw-data analysis is ready for computation, but clinical interpretation still requires final CNV/SV/signature policy, reviewer sign-off, and clinician-owned validation.",
        },
    )
    write_text(
        path_from_root(f"{output_dir}/README.md"),
        f"""# Diana Raw Analysis Packet

Status: **staged**.

Analysis ID: `{analysis_id()}`

Samplesheet: `{samplesheet}`

DNA rows: `{summary["dnaRowCount"]}`

RNA rows: `{summary["rnaRows"]}`

Matched DNA pair IDs: `{";".join(summary["matchedPairIds"])}`

## Run Alongside Validation

1. `{PY_COMMAND} run:all`
2. `DIANA_RAW_SAMPLESHEET={samplesheet} DIANA_RAW_REQUIRE_DATA=1 {PY_COMMAND} verify:diana-raw`
3. `DIANA_RAW_SAMPLESHEET={samplesheet} DIANA_RAW_REQUIRE_DATA=1 DIANA_RAW_ANALYSIS_ID={analysis_id()} {PY_COMMAND} stage:diana-raw`

The staged packet records Diana raw inputs and the exact validation sidecar. It is designed so Diana's HRD recompute can be compared against the public SEQC2/HCC1395 validation outputs in the same repository.

## Boundary

This packet stages computation. It does not make a treatment-changing HRD call until full-depth DNA results, CNV/SV/signature outputs, and reviewer sign-off are complete.
""",
    )
    write_json(
        path_from_root(f"{DIANA_RAW_RESULTS}/latest_staged_analysis.json"),
        {"generatedAt": iso_now(), "status": "staged", "analysisId": analysis_id(), "outputDir": output_dir, "samplesheet": samplesheet},
    )
    print(f"Diana raw analysis staged: {output_dir}")


if __name__ == "__main__":
    main()
