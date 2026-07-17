from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Any

from ...diana_raw import DIANA_RAW_COLUMNS, DIANA_RAW_RESULTS
from ...paths import path_from_root
from ...utils import ensure_parent, iso_now, parse_csv, read_text, write_csv, write_json
from .verify_diana_raw import selected_samplesheet, validate_rows

DELIVERY_MANIFEST_DEFAULT = "manifests/diana_raw_delivery_manifest.csv"
DELIVERY_CHECKSUMS_DEFAULT = "manifests/diana_raw_delivery_checksums.sha256"
DELIVERY_MAPPING_DEFAULT = f"{DIANA_RAW_RESULTS}/delivery_manifest_mapping.json"
DELIVERY_ROOT_DEFAULT = "data/raw/diana"

REFERENCE_ID_DEFAULT = "ucsc_hg38_analysis_set_full"
REFERENCE_PATH_DEFAULT = "data/raw/reference/full_reference_smoke/ucsc_hg38_analysis_set_full/ucsc_hg38_analysis_set_full.fa"
REFERENCE_FAI_PATH_DEFAULT = f"{REFERENCE_PATH_DEFAULT}.fai"
REFERENCE_DICT_PATH_DEFAULT = "data/raw/reference/full_reference_smoke/ucsc_hg38_analysis_set_full/ucsc_hg38_analysis_set_full.dict"

DELIVERY_REQUIRED_COLUMNS = [
    "dataset",
    "sample_id",
    "role",
    "assay",
    "data_type",
    "relative_path",
    "size_bytes",
    "sha256",
    "reference_build",
    "source_vendor",
    "notes",
]

REFERENCE_ALIASES = {
    "ucsc_hg38_analysis_set_full": {"grch38", "hg38", "ucsc_hg38_analysis_set_full"},
}


def selected_delivery_manifest() -> str:
    return os.environ.get("DIANA_RAW_DELIVERY_MANIFEST", DELIVERY_MANIFEST_DEFAULT)


def selected_delivery_checksums() -> str:
    return os.environ.get("DIANA_RAW_DELIVERY_CHECKSUMS", DELIVERY_CHECKSUMS_DEFAULT)


def selected_delivery_mapping() -> str:
    return os.environ.get("DIANA_RAW_DELIVERY_MAPPING", DELIVERY_MAPPING_DEFAULT)


def selected_delivery_root() -> str:
    return os.environ.get("DIANA_RAW_DELIVERY_ROOT", DELIVERY_ROOT_DEFAULT).rstrip("/")


def selected_reference_id() -> str:
    return os.environ.get("DIANA_RAW_REFERENCE_ID", REFERENCE_ID_DEFAULT)


def selected_reference_path() -> str:
    return os.environ.get("DIANA_RAW_REFERENCE_PATH", REFERENCE_PATH_DEFAULT)


def selected_reference_fai_path() -> str:
    return os.environ.get("DIANA_RAW_REFERENCE_FAI_PATH", REFERENCE_FAI_PATH_DEFAULT)


def selected_reference_dict_path() -> str:
    return os.environ.get("DIANA_RAW_REFERENCE_DICT_PATH", REFERENCE_DICT_PATH_DEFAULT)


def parse_sha256_lines(text: str) -> tuple[dict[str, str], list[str]]:
    checksums: dict[str, str] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            checksum, relative_path = line.split(maxsplit=1)
        except ValueError:
            errors.append(f"Line {line_number} is not a sha256sum row.")
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{64}", checksum):
            errors.append(f"Line {line_number} does not start with a SHA-256 digest.")
        checksums[relative_path.lstrip("*")] = checksum.lower()
    return checksums, errors


def validate_delivery_manifest(rows: list[dict[str, str]], checksums: dict[str, str]) -> list[str]:
    errors: list[str] = []
    columns = set(rows[0].keys()) if rows else set()
    for column in DELIVERY_REQUIRED_COLUMNS:
        if column not in columns:
            errors.append(f"Delivery manifest is missing required column {column}.")

    relative_paths: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        relative_path = row.get("relative_path", "")
        sha256 = row.get("sha256", "").lower()
        size_bytes = row.get("size_bytes", "")
        if not relative_path:
            errors.append(f"Delivery manifest row {row_number} is missing relative_path.")
            continue
        if PurePosixPath(relative_path).is_absolute() or ".." in PurePosixPath(relative_path).parts:
            errors.append(f"Delivery manifest row {row_number} has an unsafe relative_path: {relative_path}")
        if relative_path in relative_paths:
            errors.append(f"Delivery manifest repeats relative_path: {relative_path}")
        relative_paths.add(relative_path)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            errors.append(f"Delivery manifest row {row_number} has an invalid sha256 for {relative_path}.")
        if checksums.get(relative_path) != sha256:
            errors.append(f"Delivery manifest SHA-256 does not match checksums.sha256 for {relative_path}.")
        try:
            if int(size_bytes) <= 0:
                errors.append(f"Delivery manifest row {row_number} has non-positive size_bytes for {relative_path}.")
        except ValueError:
            errors.append(f"Delivery manifest row {row_number} has invalid size_bytes for {relative_path}.")

    for relative_path in checksums:
        if relative_path not in relative_paths:
            errors.append(f"checksums.sha256 contains {relative_path}, but the delivery manifest does not.")

    return errors


def is_rna_row(row: dict[str, str]) -> bool:
    haystack = " ".join([row.get("sample_id", ""), row.get("assay", ""), row.get("relative_path", "")]).lower()
    return row.get("data_type", "").upper() == "RNA_FASTQ" or "rna" in haystack or "transcript" in haystack


def normalize_dna_assay(row: dict[str, str]) -> str:
    assay = row.get("assay", "").lower()
    if "wgs" in assay or "whole genome" in assay:
        return "WGS"
    if "wes" in assay or "immunoid" in assay or "exome" in assay:
        return "WES"
    return ""


def normalize_role(row: dict[str, str]) -> str:
    role = row.get("role", "").lower()
    if role in {"normal", "matched_normal", "matched-normal", "germline"}:
        return "normal"
    if role == "tumor":
        return "rna_tumor" if is_rna_row(row) else "tumor"
    return role


def safe_token(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return safe or "sample"


def lane_token(relative_path: str, fallback: int) -> str:
    match = re.search(r"_L(\d{3})_", PurePosixPath(relative_path).name)
    if match:
        return f"L{match.group(1)}"
    return f"pair{fallback:02d}"


def fastq_pair_signature(relative_path: str) -> tuple[str, str] | None:
    patterns = [
        (r"(?i)(?P<prefix>.*)reads(?P<mate>[12])(?P<suffix>.*)", "readsX"),
        (r"(?P<prefix>.*)_R(?P<mate>[12])_(?P<suffix>.*)", "_RX_"),
        (r"(?P<prefix>.*)_R(?P<mate>[12])\\.(?P<suffix>.*)", "_RX."),
    ]
    for pattern, replacement in patterns:
        match = re.fullmatch(pattern, relative_path)
        if not match:
            continue
        return f"{match.group('prefix')}{replacement}{match.group('suffix')}", match.group("mate")
    return None


def read_group_platform_unit(relative_path: str, fallback: int) -> str:
    match = re.search(r"_L(\d{3})_", PurePosixPath(relative_path).name)
    if match:
        return match.group(1)
    return f"pair{fallback:02d}"


def joined_path(root: str, relative_path: str) -> str:
    return f"{root.rstrip('/')}/{relative_path.lstrip('/')}"


def row_note(row: dict[str, str], extra: str = "") -> str:
    parts = [
        f"source_dataset={row.get('dataset', '')}",
        f"source_sample_id={row.get('sample_id', '')}",
        f"source_vendor={row.get('source_vendor', '')}",
        f"source_reference_build={row.get('reference_build', '')}",
        f"source_notes={row.get('notes', '')}",
    ]
    if extra:
        parts.append(extra)
    return "; ".join(part for part in parts if part and not part.endswith("="))


def make_blank_row() -> dict[str, str]:
    return {column: "" for column in DIANA_RAW_COLUMNS}


def compatible_bam_reference(source_reference: str, target_reference_id: str) -> bool:
    if not source_reference:
        return False
    aliases = REFERENCE_ALIASES.get(target_reference_id, {target_reference_id.lower()})
    return source_reference.lower() in aliases


def build_fastq_rows(
    rows: list[dict[str, str]],
    *,
    delivery_root: str,
    reference_id: str,
    reference_path: str,
    reference_fai_path: str,
    reference_dict_path: str,
    skipped: list[dict[str, str]],
) -> list[dict[str, str]]:
    paired: dict[tuple[str, str, str, str, str], dict[str, dict[str, str]]] = {}
    for row in rows:
        if row.get("data_type", "").upper() != "FASTQ":
            continue
        assay = "RNA" if is_rna_row(row) else normalize_dna_assay(row)
        role = normalize_role(row)
        signature = fastq_pair_signature(row.get("relative_path", ""))
        if assay not in {"WGS", "WES", "RNA"} or role not in {"tumor", "normal", "rna_tumor"}:
            skipped.append({"relative_path": row.get("relative_path", ""), "reason": "unsupported_fastq_assay_or_role"})
            continue
        if signature is None:
            skipped.append({"relative_path": row.get("relative_path", ""), "reason": "unpaired_fastq_name"})
            continue
        pair_key, mate = signature
        key = (row.get("dataset", ""), row.get("sample_id", ""), role, assay, pair_key)
        paired.setdefault(key, {})[mate] = row

    converted: list[dict[str, str]] = []
    for index, (key, mates) in enumerate(sorted(paired.items()), start=1):
        dataset, source_sample_id, role, assay, _pair_key = key
        r1 = mates.get("1")
        r2 = mates.get("2")
        if not r1 or not r2:
            row = r1 or r2 or {}
            skipped.append({"relative_path": row.get("relative_path", ""), "reason": "missing_fastq_mate"})
            continue

        row = make_blank_row()
        lane = lane_token(r1["relative_path"], index)
        sample_id = safe_token(f"{dataset}_{source_sample_id}_{lane}")
        pair_id = safe_token(f"DIANA_{assay}_{dataset}")
        row.update(
            {
                "patient_id": "DIANA",
                "pair_id": pair_id,
                "sample_id": sample_id,
                "role": role,
                "assay": assay,
                "data_type": "RNA_FASTQ" if assay == "RNA" else "FASTQ",
                "library_layout": "PAIRED",
                "read_group_id": safe_token(f"{sample_id}.rg1"),
                "read_group_sample": source_sample_id,
                "read_group_library": pair_id,
                "read_group_platform": "ILLUMINA",
                "read_group_platform_unit": read_group_platform_unit(r1["relative_path"], index),
                "notes": row_note(r1, f"source_sha256_r1={r1.get('sha256', '')}; source_sha256_r2={r2.get('sha256', '')}"),
                "caveat": "Mapped from a delivered object manifest; run strict file and checksum validation after local staging.",
            }
        )
        if assay == "RNA":
            row.update(
                {
                    "rna_fastq_1": joined_path(delivery_root, r1["relative_path"]),
                    "rna_fastq_2": joined_path(delivery_root, r2["relative_path"]),
                }
            )
        else:
            row.update(
                {
                    "fastq_1": joined_path(delivery_root, r1["relative_path"]),
                    "fastq_2": joined_path(delivery_root, r2["relative_path"]),
                    "reference_id": reference_id,
                    "reference_path": reference_path,
                    "reference_fai_path": reference_fai_path,
                    "reference_dict_path": reference_dict_path,
                    "normal_type": "matched_normal" if role == "normal" else "",
                }
            )
        converted.append(row)
    return converted


def build_bam_rows(
    rows: list[dict[str, str]],
    *,
    delivery_root: str,
    reference_id: str,
    reference_path: str,
    reference_fai_path: str,
    reference_dict_path: str,
    skipped: list[dict[str, str]],
) -> list[dict[str, str]]:
    by_relative_path = {row.get("relative_path", ""): row for row in rows}
    converted: list[dict[str, str]] = []
    for row in rows:
        if row.get("data_type", "").upper() != "BAM":
            continue
        if is_rna_row(row):
            skipped.append({"relative_path": row.get("relative_path", ""), "reason": "rna_bam_not_in_strict_samplesheet"})
            continue
        assay = normalize_dna_assay(row)
        role = normalize_role(row)
        if assay not in {"WGS", "WES"} or role not in {"tumor", "normal"}:
            skipped.append({"relative_path": row.get("relative_path", ""), "reason": "unsupported_bam_assay_or_role"})
            continue
        if not compatible_bam_reference(row.get("reference_build", ""), reference_id):
            skipped.append({"relative_path": row.get("relative_path", ""), "reason": "bam_reference_not_selected_analysis_reference"})
            continue
        bam_path = row["relative_path"]
        bai = by_relative_path.get(f"{bam_path}.bai") or by_relative_path.get(re.sub(r"\\.bam$", ".bai", bam_path))
        if not bai:
            skipped.append({"relative_path": bam_path, "reason": "missing_bai"})
            continue

        strict = make_blank_row()
        sample_id = safe_token(f"{row.get('dataset', '')}_{row.get('sample_id', '')}_bam")
        pair_id = safe_token(f"DIANA_{assay}_{row.get('dataset', '')}")
        strict.update(
            {
                "patient_id": "DIANA",
                "pair_id": pair_id,
                "sample_id": sample_id,
                "role": role,
                "assay": assay,
                "data_type": "BAM",
                "library_layout": "PAIRED",
                "bam": joined_path(delivery_root, bam_path),
                "bai": joined_path(delivery_root, bai["relative_path"]),
                "reference_id": reference_id,
                "reference_path": reference_path,
                "reference_fai_path": reference_fai_path,
                "reference_dict_path": reference_dict_path,
                "read_group_sample": row.get("sample_id", ""),
                "read_group_library": pair_id,
                "read_group_platform": "ILLUMINA",
                "read_group_platform_unit": "vendor_alignment",
                "normal_type": "matched_normal" if role == "normal" else "",
                "notes": row_note(row, f"source_sha256_bam={row.get('sha256', '')}; source_sha256_bai={bai.get('sha256', '')}"),
                "caveat": "Mapped from a delivered BAM manifest; confirm the BAM reference exactly matches the selected analysis reference.",
            }
        )
        converted.append(strict)
    return converted


def map_delivery_rows(rows: list[dict[str, str]], delivery_root: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    skipped: list[dict[str, str]] = []
    reference_id = selected_reference_id()
    reference_path = selected_reference_path()
    reference_fai_path = selected_reference_fai_path()
    reference_dict_path = selected_reference_dict_path()
    mapped = [
        *build_fastq_rows(
            rows,
            delivery_root=delivery_root,
            reference_id=reference_id,
            reference_path=reference_path,
            reference_fai_path=reference_fai_path,
            reference_dict_path=reference_dict_path,
            skipped=skipped,
        ),
        *build_bam_rows(
            rows,
            delivery_root=delivery_root,
            reference_id=reference_id,
            reference_path=reference_path,
            reference_fai_path=reference_fai_path,
            reference_dict_path=reference_dict_path,
            skipped=skipped,
        ),
    ]
    return sorted(mapped, key=lambda row: (row["assay"], row["pair_id"], row["role"], row["sample_id"], row["data_type"])), skipped


def write_failed_mapping(mapping_path: str, manifest_path: str, checksums_path: str, output_path: str, errors: list[str]) -> None:
    ensure_parent(path_from_root(mapping_path))
    write_json(
        path_from_root(mapping_path),
        {
            "generatedAt": iso_now(),
            "status": "failed",
            "sourceManifest": manifest_path,
            "sourceChecksums": checksums_path,
            "outputSamplesheet": output_path,
            "errors": errors,
        },
    )


def main() -> None:
    manifest_path = selected_delivery_manifest()
    checksums_path = selected_delivery_checksums()
    mapping_path = selected_delivery_mapping()
    output_path = selected_samplesheet()
    missing_inputs = [
        f"Missing {label}: {path}"
        for label, path in (
            ("delivery manifest", manifest_path),
            ("delivery checksums", checksums_path),
        )
        if not path_from_root(path).is_file()
    ]
    if missing_inputs:
        write_failed_mapping(mapping_path, manifest_path, checksums_path, output_path, missing_inputs)
        for error in missing_inputs:
            print(f"error: {error}")
        raise SystemExit(1)

    rows = parse_csv(read_text(path_from_root(manifest_path)))
    checksums, checksum_parse_errors = parse_sha256_lines(read_text(path_from_root(checksums_path)))
    errors = [*checksum_parse_errors, *validate_delivery_manifest(rows, checksums)]
    if errors:
        write_failed_mapping(mapping_path, manifest_path, checksums_path, output_path, errors)
        for error in errors:
            print(f"error: {error}")
        raise SystemExit(1)

    mapped_rows, skipped = map_delivery_rows(rows, selected_delivery_root())
    validation_errors, validation_warnings, validation_summary = validate_rows(mapped_rows, require_files=False)
    status = "mapped" if mapped_rows and not validation_errors else "failed"
    mapping = {
        "generatedAt": iso_now(),
        "status": status,
        "sourceManifest": manifest_path,
        "sourceChecksums": checksums_path,
        "outputSamplesheet": output_path,
        "deliveryRoot": selected_delivery_root(),
        "summary": {
            "manifestRows": len(rows),
            "mappedRows": len(mapped_rows),
            "skippedRows": len(skipped),
            "validation": validation_summary,
        },
        "skipped": skipped,
        "validationErrors": validation_errors,
        "validationWarnings": validation_warnings,
    }

    ensure_parent(path_from_root(mapping_path))
    write_json(path_from_root(mapping_path), mapping)
    if validation_errors:
        for error in validation_errors:
            print(f"error: {error}")
        raise SystemExit(1)
    write_csv(path_from_root(output_path), mapped_rows, DIANA_RAW_COLUMNS)
    print(f"Mapped {len(mapped_rows)} Diana raw rows from {len(rows)} delivered objects: {output_path}")


if __name__ == "__main__":
    main()
