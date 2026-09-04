from __future__ import annotations

import math
import re
from typing import Any, Iterable

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def require_run_id(value: str) -> str:
    run_id = value.strip()
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must be 1-128 characters using only letters, numbers, dot, underscore, or dash")
    return run_id


def parse_idxstats(text: str) -> dict[str, Any]:
    contigs: list[dict[str, int | str]] = []
    total_mapped = 0
    total_unmapped = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            raise ValueError(f"idxstats line {line_number} does not have four tab-separated fields")
        contig, length_text, mapped_text, unmapped_text = fields
        try:
            length = int(length_text)
            mapped = int(mapped_text)
            unmapped = int(unmapped_text)
        except ValueError as error:
            raise ValueError(f"idxstats line {line_number} has a non-integer metric") from error
        if min(length, mapped, unmapped) < 0:
            raise ValueError(f"idxstats line {line_number} has a negative metric")
        if contig != "*":
            contigs.append({"contig": contig, "length": length, "mapped": mapped, "unmapped": unmapped})
        total_mapped += mapped
        total_unmapped += unmapped
    if not contigs:
        raise ValueError("idxstats did not contain reference contigs")
    return {
        "contigCount": len(contigs),
        "totalMappedAlignments": total_mapped,
        "totalUnmappedAlignments": total_unmapped,
        "contigs": contigs,
    }


def parse_flagstat(text: str) -> dict[str, int]:
    patterns = {
        "totalAlignments": r"^(\d+) \+ \d+ in total ",
        "primaryAlignments": r"^(\d+) \+ \d+ primary$",
        "secondaryAlignments": r"^(\d+) \+ \d+ secondary$",
        "supplementaryAlignments": r"^(\d+) \+ \d+ supplementary$",
        "duplicateAlignments": r"^(\d+) \+ \d+ duplicates$",
        "primaryDuplicateAlignments": r"^(\d+) \+ \d+ primary duplicates$",
        "mappedAlignments": r"^(\d+) \+ \d+ mapped ",
        "primaryMappedAlignments": r"^(\d+) \+ \d+ primary mapped ",
        "pairedAlignments": r"^(\d+) \+ \d+ paired in sequencing$",
        "read1Alignments": r"^(\d+) \+ \d+ read1$",
        "read2Alignments": r"^(\d+) \+ \d+ read2$",
        "properlyPairedAlignments": r"^(\d+) \+ \d+ properly paired ",
    }
    metrics: dict[str, int] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            raise ValueError(f"flagstat output is missing {key}")
        metrics[key] = int(match.group(1))
    if metrics["primaryDuplicateAlignments"] > metrics["primaryAlignments"]:
        raise ValueError("flagstat primary duplicates exceed primary alignments")
    metrics["primaryNonduplicateAlignments"] = (
        metrics["primaryAlignments"] - metrics["primaryDuplicateAlignments"]
    )
    return metrics


def parse_depth(text: str, *, contig: str, start: int, end: int) -> list[int]:
    if start < 1 or end < start:
        raise ValueError("depth interval must use one-based inclusive coordinates")
    depths = [0] * (end - start + 1)
    seen: set[int] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            raise ValueError(f"depth line {line_number} has fewer than three fields")
        observed_contig, position_text, depth_text = fields[:3]
        if observed_contig != contig:
            raise ValueError(f"depth line {line_number} has unexpected contig {observed_contig}")
        position = int(position_text)
        depth = int(depth_text)
        if position < start or position > end or depth < 0:
            raise ValueError(f"depth line {line_number} is outside the requested interval")
        if position in seen:
            raise ValueError(f"depth line {line_number} duplicates position {position}")
        seen.add(position)
        depths[position - start] = depth
    return depths


def summarize_depth(depths: Iterable[int]) -> dict[str, float | int]:
    values = sorted(int(value) for value in depths)
    if not values:
        raise ValueError("at least one depth value is required")
    if values[0] < 0:
        raise ValueError("depth values cannot be negative")
    count = len(values)
    midpoint = count // 2
    median = float(values[midpoint]) if count % 2 else (values[midpoint - 1] + values[midpoint]) / 2
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    return {
        "bases": count,
        "meanDepth": mean,
        "medianDepth": median,
        "maxDepth": values[-1],
        "coefficientOfVariation": math.sqrt(variance) / mean if mean else 0.0,
        "fractionAtLeast1x": sum(value >= 1 for value in values) / count,
        "fractionAtLeast10x": sum(value >= 10 for value in values) / count,
        "fractionAtLeast100x": sum(value >= 100 for value in values) / count,
    }


def build_expression_metrics(
    *,
    primary_region_reads: int,
    hq_nonduplicate_region_reads: int,
    unique_hq_templates: int,
    total_index_mapped_alignments: int,
    gene_length_bp: int,
) -> dict[str, float | int | str]:
    values = (
        primary_region_reads,
        hq_nonduplicate_region_reads,
        unique_hq_templates,
        total_index_mapped_alignments,
        gene_length_bp,
    )
    if any(value < 0 for value in values):
        raise ValueError("expression metrics cannot be negative")
    if total_index_mapped_alignments == 0 or gene_length_bp == 0:
        raise ValueError("mapped alignment denominator and gene length must be positive")
    if hq_nonduplicate_region_reads > primary_region_reads:
        raise ValueError("filtered region reads cannot exceed primary region reads")

    alignment_rpm = primary_region_reads / total_index_mapped_alignments * 1_000_000
    estimated_mapped_fragments = total_index_mapped_alignments / 2
    approximate_fragment_rpkm = unique_hq_templates / (gene_length_bp / 1_000) / (estimated_mapped_fragments / 1_000_000)
    return {
        "primaryRegionReads": primary_region_reads,
        "hqNonduplicateRegionReads": hq_nonduplicate_region_reads,
        "uniqueHqTemplates": unique_hq_templates,
        "totalIndexMappedAlignments": total_index_mapped_alignments,
        "hqRetentionFraction": hq_nonduplicate_region_reads / primary_region_reads if primary_region_reads else 0.0,
        "alignmentReadsPerMillion": alignment_rpm,
        "approximateFragmentRpkm": approximate_fragment_rpkm,
        "normalizationCaveat": (
            "RPKM is an approximate single-gene diagnostic based on index-level mapped-alignments/2; "
            "it is not Salmon/tximport TPM and is not suitable for cross-study differential expression."
        ),
    }


def compare_counts(first: int, second: int) -> dict[str, float | int | str]:
    if first < 0 or second < 0:
        raise ValueError("counts cannot be negative")
    denominator = max(first, second)
    relative_difference = abs(first - second) / denominator if denominator else 0.0
    return {
        "first": first,
        "second": second,
        "relativeDifference": relative_difference,
        "status": "concordant" if relative_difference <= 0.02 else "discordant_review_required",
    }
