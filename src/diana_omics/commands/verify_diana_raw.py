from __future__ import annotations

import os
import sys
from typing import Any

from ..diana_raw import (
    DIANA_RAW_COLUMNS,
    DIANA_RAW_DEFAULT,
    DIANA_RAW_RESULTS,
    DNA_ASSAYS,
    DNA_ROLES,
    diana_raw_contract,
    resolve_existing_file,
    row_has_bam_pair,
    row_has_cram_pair,
    row_has_fastq_pair,
)
from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_text, write_csv, write_json, write_text


def selected_samplesheet() -> str:
    return os.environ.get("DIANA_RAW_SAMPLESHEET", DIANA_RAW_DEFAULT)


def require_data() -> bool:
    return os.environ.get("DIANA_RAW_REQUIRE_DATA") == "1"


def check_files() -> bool:
    return os.environ.get("DIANA_RAW_CHECK_FILES", "1") != "0"


def validate_rows(rows: list[dict[str, str]], *, require_files: bool) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    columns = set(rows[0].keys()) if rows else set()
    for column in DIANA_RAW_COLUMNS:
        if column not in columns:
            errors.append(f"Diana raw samplesheet is missing required column {column}.")

    sample_ids = [row.get("sample_id", "") for row in rows]
    if len(sample_ids) != len(set(sample_ids)):
        errors.append("Diana raw samplesheet sample_id values must be unique.")

    dna_rows = [row for row in rows if row.get("role") in DNA_ROLES and row.get("assay") in DNA_ASSAYS]
    tumor_rows = [row for row in dna_rows if row.get("role") == "tumor"]
    normal_rows = [row for row in dna_rows if row.get("role") == "normal"]
    if not tumor_rows:
        errors.append("Diana raw samplesheet must include a tumor DNA row.")
    if not normal_rows:
        errors.append("Diana raw samplesheet must include a matched normal DNA row.")
    tumor_pair_ids = {str(row.get("pair_id", "")) for row in tumor_rows}
    normal_pair_ids = {str(row.get("pair_id", "")) for row in normal_rows}
    matched_pair_ids = sorted((tumor_pair_ids & normal_pair_ids) - {""})
    if dna_rows and not matched_pair_ids:
        errors.append("Diana raw tumor and normal DNA rows must share at least one non-empty pair_id.")

    reference_ids = {str(row.get("reference_id", "")) for row in dna_rows if row.get("reference_id")}
    if len(reference_ids) > 1:
        warnings.append(f"Diana raw DNA rows contain multiple reference_id values: {', '.join(sorted(reference_ids))}.")
    for row in dna_rows:
        data_type = row.get("data_type", "")
        if data_type not in {"FASTQ", "BAM", "CRAM"}:
            errors.append(f"DNA row {row.get('sample_id')} must use data_type FASTQ, BAM, or CRAM.")
        has_fastq = row_has_fastq_pair(row)
        has_bam = row_has_bam_pair(row)
        has_cram = row_has_cram_pair(row)
        if not (has_fastq or has_bam or has_cram):
            errors.append(f"DNA row {row.get('sample_id')} must provide FASTQ pairs, BAM+BAI, or CRAM+CRAI.")
        if data_type == "FASTQ" and not has_fastq:
            errors.append(f"DNA row {row.get('sample_id')} data_type FASTQ must provide fastq_1 and fastq_2.")
        if data_type == "BAM" and not has_bam:
            errors.append(f"DNA row {row.get('sample_id')} data_type BAM must provide bam and bai.")
        if data_type == "CRAM" and not has_cram:
            errors.append(f"DNA row {row.get('sample_id')} data_type CRAM must provide cram and crai.")
        for column in ["reference_id", "reference_path", "reference_fai_path", "reference_dict_path"]:
            if not row.get(column):
                errors.append(f"DNA row {row.get('sample_id')} is missing {column}.")

    rna_rows = [row for row in rows if row.get("assay") == "RNA" or row.get("data_type") == "RNA_FASTQ"]
    for row in rna_rows:
        if row.get("data_type") != "RNA_FASTQ":
            errors.append(f"RNA row {row.get('sample_id')} must use data_type RNA_FASTQ.")
        if not row.get("rna_fastq_1") or not row.get("rna_fastq_2"):
            warnings.append(f"RNA row {row.get('sample_id')} is present but does not include paired RNA FASTQs.")

    if require_files:
        path_columns = [
            "fastq_1",
            "fastq_2",
            "bam",
            "bai",
            "cram",
            "crai",
            "reference_path",
            "reference_fai_path",
            "reference_dict_path",
            "capture_bed",
            "rna_fastq_1",
            "rna_fastq_2",
        ]
        for row in rows:
            for column in path_columns:
                value = row.get(column, "")
                if not value:
                    continue
                path = resolve_existing_file(value)
                if not path.exists():
                    errors.append(f"{row.get('sample_id')} {column} path does not exist: {value}")

    summary = {
        "rowCount": len(rows),
        "dnaRowCount": len(dna_rows),
        "tumorDnaRows": len(tumor_rows),
        "normalDnaRows": len(normal_rows),
        "rnaRows": len(rna_rows),
        "matchedPairIds": matched_pair_ids,
        "referenceIds": sorted(reference_ids),
        "assays": sorted({row.get("assay", "") for row in rows if row.get("assay")}),
        "dataTypes": sorted({row.get("data_type", "") for row in rows if row.get("data_type")}),
    }
    return errors, warnings, summary


def write_validation(status: str, samplesheet: str, summary: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    ensure_dir(path_from_root(DIANA_RAW_RESULTS))
    row = {
        "status": status,
        "samplesheet": samplesheet,
        "row_count": summary.get("rowCount", 0),
        "dna_row_count": summary.get("dnaRowCount", 0),
        "tumor_dna_rows": summary.get("tumorDnaRows", 0),
        "normal_dna_rows": summary.get("normalDnaRows", 0),
        "rna_rows": summary.get("rnaRows", 0),
        "matched_pair_ids": ";".join(summary.get("matchedPairIds", [])),
        "ready_to_stage": "yes" if status == "passed" else "no",
        "error_count": len(errors),
        "warning_count": len(warnings),
    }
    write_csv(path_from_root(f"{DIANA_RAW_RESULTS}/input_validation_summary.csv"), [row])
    write_json(
        path_from_root(f"{DIANA_RAW_RESULTS}/input_validation_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": status,
            "samplesheet": samplesheet,
            "summary": summary,
            "errors": errors,
            "warnings": warnings,
            "contract": diana_raw_contract(),
        },
    )


def main() -> None:
    samplesheet = selected_samplesheet()
    path = path_from_root(samplesheet)
    if not path.exists():
        status = "missing_diana_raw_samplesheet" if require_data() else "waiting_for_diana_raw_data"
        summary: dict[str, Any] = {
            "rowCount": 0,
            "dnaRowCount": 0,
            "tumorDnaRows": 0,
            "normalDnaRows": 0,
            "rnaRows": 0,
            "matchedPairIds": [],
        }
        errors = (
            [f"Missing {samplesheet}. Copy manifests/diana_raw_inputs.template.csv to {samplesheet} and fill in actual paths."]
            if require_data()
            else []
        )
        warnings = [] if require_data() else [f"{samplesheet} is not present yet; Diana raw data are still pending."]
        write_validation(status, samplesheet, summary, errors, warnings)
        write_text(
            path_from_root(f"{DIANA_RAW_RESULTS}/README.md"),
            f"""# Diana Raw Intake

Status: **{status}**.

Expected samplesheet: `{samplesheet}`

Run `PYTHONPATH=src /usr/bin/python3 -m diana_omics build:diana-template` to refresh the template and documentation.
""",
        )
        if errors:
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            raise SystemExit(1)
        print(f"Diana raw intake waiting for actual data: {samplesheet}")
        return

    rows = parse_csv(read_text(path))
    errors, warnings, summary = validate_rows(rows, require_files=check_files())
    status = "passed" if not errors else "failed"
    write_validation(status, samplesheet, summary, errors, warnings)
    if warnings:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Diana raw input validation passed: {summary['dnaRowCount']} DNA rows, {summary['rnaRows']} RNA rows.")


if __name__ == "__main__":
    main()
