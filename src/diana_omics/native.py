from __future__ import annotations

import importlib.metadata
import importlib.util
from typing import Any, Optional

from .paths import path_from_root
from .utils import capture_allow_empty, quote_shell_arg

OPTIONAL_INTEGRATIONS = [
    {
        "name": "pysam",
        "package": "pysam",
        "purpose": "native BAM/VCF/BCF parsing for full-depth variant and alignment checks",
    },
    {
        "name": "pyfaidx",
        "package": "pyfaidx",
        "purpose": "indexed reference-sequence lookup for SBS96 and normalization features",
    },
    {
        "name": "polars",
        "package": "polars",
        "purpose": "larger manifest and result joins once multi-sample validation scales",
    },
    {
        "name": "truvari",
        "package": "truvari",
        "purpose": "SV truth-set comparison for HG008 and COLO829 orthogonal validation",
    },
    {
        "name": "SigProfilerAssignment",
        "package": "SigProfilerAssignment",
        "purpose": "SBS signature assignment once full WGS mutation counts are adequate",
    },
]


def optional_module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def optional_package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return ""


def optional_integration_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for integration in OPTIONAL_INTEGRATIONS:
        name = str(integration["name"])
        package = str(integration["package"])
        available = optional_module_available(name)
        rows.append(
            {
                "name": name,
                "package": package,
                "available": "yes" if available else "no",
                "version": optional_package_version(package) if available else "",
                "purpose": integration["purpose"],
            }
        )
    return rows


def native_tool_versions() -> dict[str, dict[str, str]]:
    return {
        row["name"]: {
            "available": row["available"],
            "package": row["package"],
            "version": row["version"],
            "purpose": row["purpose"],
        }
        for row in optional_integration_rows()
    }


def vcf_sample_names(vcf_path: str) -> Optional[list[str]]:
    if not optional_module_available("pysam"):
        return None
    import pysam  # type: ignore[import-not-found]

    with pysam.VariantFile(str(path_from_root(vcf_path))) as variant_file:
        return list(variant_file.header.samples)


def reference_context(reference_path: str, contig: str, position: int, flank: int = 1) -> str:
    if flank < 0:
        raise ValueError("flank must be non-negative")
    expected_length = flank * 2 + 1
    if optional_module_available("pyfaidx"):
        try:
            from pyfaidx import Fasta  # type: ignore[import-not-found]

            fasta = Fasta(str(path_from_root(reference_path)), rebuild=False, as_raw=True, sequence_always_upper=True)
            start = max(0, position - 1 - flank)
            end = position + flank
            sequence = str(fasta[contig][start:end]).upper()
            if len(sequence) == expected_length:
                return sequence
        except Exception:
            pass
    return capture_allow_empty(
        f"samtools faidx {quote_shell_arg(reference_path)} {quote_shell_arg(f'{contig}:{position - flank}-{position + flank}')} "
        "| awk 'NR>1 {printf \"%s\", $0}'"
    ).upper()
