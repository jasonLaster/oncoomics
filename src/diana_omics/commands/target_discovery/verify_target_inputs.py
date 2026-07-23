from __future__ import annotations

import sys

from ...paths import path_from_root
from ...target_discovery import TARGET_DISCOVERY_RESULTS, check_files, selected_inputs_path, validate_input_rows
from ...utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json


def main() -> None:
    samplesheet = selected_inputs_path()
    path = path_from_root(samplesheet)
    rows = parse_csv(read_text(path)) if path.exists() else []
    errors, warnings, summary = validate_input_rows(rows, require_files=check_files())
    if not path.exists():
        errors.insert(0, f"Missing target discovery inputs: {samplesheet}.")

    status = "passed" if not errors else "failed"
    ensure_dir(path_from_root(TARGET_DISCOVERY_RESULTS))
    write_csv(
        path_from_root(f"{TARGET_DISCOVERY_RESULTS}/input_validation_summary.csv"),
        [
            {
                "status": status,
                "samplesheet": samplesheet,
                "row_count": summary["rowCount"],
                "dna_row_count": summary["dnaRowCount"],
                "rna_rows": summary["rnaRows"],
                "protein_rows": summary["proteinRows"],
                "phospho_protein_rows": summary["phosphoProteinRows"],
                "report_rows": summary["reportRows"],
                "ready_to_interpret": "no",
                "error_count": len(errors),
                "warning_count": len(warnings),
            }
        ],
    )
    write_json(
        path_from_root(f"{TARGET_DISCOVERY_RESULTS}/input_validation_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": status,
            "samplesheet": samplesheet,
            "summary": summary,
            "errors": errors,
            "warnings": warnings,
            "interpretationBoundary": "Input validation stages evidence lanes only and never scores ADC, bispecific, CDK12/13, or CDK4/6 hypotheses.",
        },
    )
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Target discovery input validation passed: {summary['rowCount']} evidence rows.")


if __name__ == "__main__":
    main()
