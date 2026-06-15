from __future__ import annotations

import gzip
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Optional

from ...paths import path_from_root
from ...telemetry import RunTelemetry, run_traced_command
from ...utils import (
    bcftools_norm_ref_mismatch_count,
    capture_command,
    ensure_dir,
    existing_output_current,
    iso_now,
    md5_file,
    parse_csv,
    quote_shell_arg,
    read_json,
    read_text,
    round_value,
    run_command,
    write_csv,
    write_json,
    write_text,
)

RESULTS_DIR = "results/full_wes_benchmark"
VALIDATION_CACHE_KEY = "_validation_cache"
FORCE = os.environ.get("PHASE2F_FORCE") == "1"
THREADS = int(os.environ.get("PHASE2F_THREADS", "8"))
BAM_SCAN_THREADS = max(1, int(os.environ.get("PHASE2F_BAM_SCAN_THREADS", str(max(1, THREADS // 2)))))
FASTQ_VALIDATION_WORKERS = max(1, int(os.environ.get("PHASE2F_FASTQ_VALIDATION_WORKERS", str(min(4, THREADS)))))
BAM_VALIDATION_WORKERS = max(1, int(os.environ.get("PHASE2F_BAM_VALIDATION_WORKERS", str(min(2, THREADS)))))
REUSE_FASTQ_VALIDATION = os.environ.get("PHASE2F_REUSE_FASTQ_VALIDATION", "1") != "0"
REUSE_BAM_VALIDATION = os.environ.get("PHASE2F_REUSE_BAM_VALIDATION", "1") != "0"
MIN_TRUTH_DEPTH = int(os.environ.get("PHASE2F_MIN_TRUTH_DEPTH", "10"))
MAX_TRUTH_VARIANTS = int(os.environ.get("PHASE2F_MAX_TRUTH_VARIANTS", "5000"))
INTERVAL_PADDING = int(os.environ.get("PHASE2F_INTERVAL_PADDING", "100"))
# Cap on REF-mismatch records bcftools norm may drop before we treat it as a
# wrong-reference misconfiguration rather than a few benign discordances.
NORM_MAX_REF_MISMATCH = int(os.environ.get("PHASE2F_NORM_MAX_REF_MISMATCH", "1000"))


def file_non_empty(relative_path: str) -> bool:
    path = path_from_root(relative_path)
    return path.exists() and path.stat().st_size > 0


def quickcheck(bam_path: str) -> bool:
    if not path_from_root(bam_path).exists():
        return False
    result = subprocess.run(
        ["samtools", "quickcheck", "-v", str(path_from_root(bam_path))],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0


def read_group(row: dict[str, str]) -> str:
    return "\\t".join(
        [
            "@RG",
            f"ID:{row['read_group_id']}",
            f"SM:{row['read_group_sample']}",
            f"LB:{row['read_group_library']}",
            f"PL:{row['read_group_platform']}",
            f"PU:{row['read_group_platform_unit']}",
        ]
    )


def parse_header(header: str, row: dict[str, str]) -> dict[str, Any]:
    lines = header.splitlines()
    hd = next((line for line in lines if line.startswith("@HD")), "")
    sort_match = re.search(r"\bSO:([^\t]+)", hd)
    rg_lines = [line for line in lines if line.startswith("@RG")]
    sq_lines = [line for line in lines if line.startswith("@SQ")]
    contigs = [match.group(1) for line in sq_lines if (match := re.search(r"\bSN:([^\t]+)", line))]
    read_group_present = any(f"ID:{row['read_group_id']}" in line and f"SM:{row['read_group_sample']}" in line for line in rg_lines)
    return {
        "sortOrder": sort_match.group(1) if sort_match else "",
        "readGroupPresent": read_group_present,
        "readGroupCount": len(rg_lines),
        "contigs": contigs,
    }


def count(command: str) -> int:
    text = capture_command(command)
    return int(text or "0")


def standard_contig(contig: str) -> bool:
    return re.match(r"^chr([1-9]|1[0-9]|2[0-2]|X|Y)$", contig) is not None


def parse_duplicate_metrics(relative_path: str) -> dict[str, str]:
    lines = read_text(path_from_root(relative_path)).splitlines()
    try:
        header_index = next(index for index, line in enumerate(lines) if line.startswith("LIBRARY\t"))
    except StopIteration:
        return {}
    if header_index + 1 >= len(lines):
        return {}
    headers = lines[header_index].split("\t")
    values = lines[header_index + 1].split("\t")
    return {header: values[index] if index < len(values) else "" for index, header in enumerate(headers)}


def parse_depth_summary(depth_text: str) -> dict[str, Any]:
    bases = tumor_depth = normal_depth = both_at_10 = 0
    for line in depth_text.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        tumor = int(fields[2] or "0")
        normal = int(fields[3] or "0")
        bases += 1
        tumor_depth += tumor
        normal_depth += normal
        if tumor >= 10 and normal >= 10:
            both_at_10 += 1
    return {
        "bases": bases,
        "tumorMeanDepth": round_value(tumor_depth / bases if bases else None, 2),
        "normalMeanDepth": round_value(normal_depth / bases if bases else None, 2),
        "basesBothDepthAtLeast10": both_at_10,
        "fractionBothDepthAtLeast10": round_value(both_at_10 / bases if bases else None, 4),
    }


def load_truth_variants(vcf_path: str, variant_type: str) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    with gzip.open(path_from_root(vcf_path), "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            contig, position_text, _id, ref, alt_text, *_rest = line.rstrip("\n").split("\t")
            position = int(position_text)
            if not standard_contig(contig):
                continue
            for alt in alt_text.split(","):
                variants.append(
                    {
                        "key": f"{contig}:{position}:{ref}:{alt}",
                        "type": variant_type,
                        "contig": contig,
                        "position": position,
                        "ref": ref,
                        "alt": alt,
                    }
                )
    return variants


def run_tool_command(
    command: str,
    log_path: str,
    telemetry: Optional[RunTelemetry],
    span_name: str,
    attributes: Optional[dict[str, Any]] = None,
    parent_span_id: Optional[str] = None,
) -> str:
    if telemetry:
        return run_traced_command(command, log_path, telemetry, span_name, attributes or {}, parent_span_id=parent_span_id)
    return run_command(command, log_path)


def normalize_vcf_for_comparison(
    vcf_path: str,
    reference_path: str,
    output_path: str,
    log_path: str,
    telemetry: Optional[RunTelemetry] = None,
) -> str:
    if FORCE or not file_non_empty(output_path):
        ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
        # --check-ref x excludes records whose REF allele does not match the
        # reference instead of aborting the whole benchmark on the first one
        # (bcftools defaults to --check-ref e, which exits 255). A handful of
        # discordant sites outside the compared region are tolerated; a flood
        # means the wrong reference, so we fail closed below.
        run_tool_command(
            f"bcftools norm -m -both --check-ref x -f {quote_shell_arg(reference_path)} -Oz -o {quote_shell_arg(output_path)} {quote_shell_arg(vcf_path)}",
            log_path,
            telemetry,
            "vcf.normalize",
            {"vcfPath": vcf_path, "outputPath": output_path},
        )
        run_tool_command(
            f"bcftools index -t -f {quote_shell_arg(output_path)}",
            f"{log_path}.index",
            telemetry,
            "vcf.index",
            {"vcfPath": output_path},
        )
        mismatches = bcftools_norm_ref_mismatch_count(read_text(path_from_root(log_path)))
        if mismatches:
            print(f"[norm] {output_path}: bcftools norm excluded {mismatches} REF-mismatch record(s) vs {reference_path}", flush=True)
        if mismatches > NORM_MAX_REF_MISMATCH:
            raise RuntimeError(
                f"bcftools norm excluded {mismatches} REF-mismatch records from {vcf_path} "
                f"(cap {NORM_MAX_REF_MISMATCH}); reference {reference_path} likely does not match this VCF build."
            )
    return output_path


def write_truth_position_bed(variants: list[dict[str, Any]], output_path: str) -> None:
    ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
    value = "\n".join(f"{variant['contig']}\t{int(variant['position']) - 1}\t{variant['position']}\t{variant['key']}" for variant in variants)
    path = Path(path_from_root(output_path))
    normalized = value if value.endswith("\n") else f"{value}\n"
    if path.exists() and read_text(path) == normalized:
        return
    write_text(path, value)


def read_reference_order(fai_path: str) -> dict[str, int]:
    order: dict[str, int] = {}
    for index, line in enumerate(read_text(path_from_root(fai_path)).splitlines()):
        if line:
            order[line.split("\t")[0]] = index
    return order


def pick_covered_truth_variants(variants: list[dict[str, Any]], depth_text: str) -> list[dict[str, Any]]:
    by_position: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        by_position.setdefault(f"{variant['contig']}:{variant['position']}", []).append(variant)
    unique: dict[str, dict[str, Any]] = {}
    for line in depth_text.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        contig, position_text, tumor_text, normal_text = fields[:4]
        position = int(position_text)
        tumor_depth = int(tumor_text or "0")
        normal_depth = int(normal_text or "0")
        if tumor_depth < MIN_TRUTH_DEPTH or normal_depth < MIN_TRUTH_DEPTH:
            continue
        for variant in by_position.get(f"{contig}:{position}", []):
            enriched = dict(variant)
            enriched["tumorDepth"] = tumor_depth
            enriched["normalDepth"] = normal_depth
            enriched["minDepth"] = min(tumor_depth, normal_depth)
            unique[enriched["key"]] = enriched
    return sorted(unique.values(), key=lambda row: (-int(row["minDepth"]), str(row["contig"]), int(row["position"])))[:MAX_TRUTH_VARIANTS]


def write_benchmark_intervals(variants: list[dict[str, Any]], reference_order: dict[str, int], output_path: str) -> list[dict[str, Any]]:
    intervals = sorted(
        [
            {
                "contig": variant["contig"],
                "start": max(0, int(variant["position"]) - 1 - INTERVAL_PADDING),
                "end": int(variant["position"]) + INTERVAL_PADDING,
            }
            for variant in variants
        ],
        key=lambda row: (reference_order.get(str(row["contig"]), 9999), int(row["start"]), int(row["end"])),
    )
    merged: list[dict[str, Any]] = []
    for interval in intervals:
        last = merged[-1] if merged else None
        if not last or last["contig"] != interval["contig"] or int(interval["start"]) > int(last["end"]) + 50:
            merged.append(dict(interval))
        else:
            last["end"] = max(int(last["end"]), int(interval["end"]))
    ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
    value = "\n".join(f"{row['contig']}\t{row['start']}\t{row['end']}" for row in merged)
    path = Path(path_from_root(output_path))
    normalized = value if value.endswith("\n") else f"{value}\n"
    if not path.exists() or read_text(path) != normalized:
        write_text(path, value)
    return merged


def variant_keys(vcf_path: str, region_bed_path: Optional[str] = None) -> dict[str, Any]:
    region_part = f"-R {quote_shell_arg(region_bed_path)}" if region_bed_path else ""
    rows = capture_command(f"bcftools view {region_part} -H {quote_shell_arg(vcf_path)}")
    keys: set[str] = set()
    pass_keys: set[str] = set()
    snv_count = indel_count = pass_count = 0
    for line in rows.splitlines():
        contig, position, _id, ref, alt_text, _qual, filter_value, *_rest = line.split("\t")
        for alt in alt_text.split(","):
            key = f"{contig}:{position}:{ref}:{alt}"
            keys.add(key)
            if len(ref) == 1 and len(alt) == 1:
                snv_count += 1
            else:
                indel_count += 1
            if filter_value == "PASS":
                pass_keys.add(key)
                pass_count += 1
    return {
        "keys": keys,
        "passKeys": pass_keys,
        "totalCount": len(keys),
        "passCount": pass_count,
        "snvCount": snv_count,
        "indelCount": indel_count,
    }


def parse_contamination_table(relative_path: str) -> dict[str, str]:
    if not file_non_empty(relative_path):
        return {"contamination": "", "error": ""}
    rows = [line for line in read_text(path_from_root(relative_path)).splitlines() if line and not line.startswith("#")]
    header_index = next((index for index, line in enumerate(rows) if "contamination" in line.split("\t")), -1)
    if header_index == -1 or header_index + 1 >= len(rows):
        return {"contamination": "", "error": ""}
    headers = rows[header_index].split("\t")
    values = rows[header_index + 1].split("\t")
    contamination_index = headers.index("contamination") if "contamination" in headers else -1
    error_index = headers.index("error") if "error" in headers else -1
    return {
        "contamination": values[contamination_index] if contamination_index >= 0 and contamination_index < len(values) else "",
        "error": values[error_index] if error_index >= 0 and error_index < len(values) else "",
    }


def tool_version(tool: str) -> str:
    result = subprocess.run(
        ["bash", "-lc", f"{tool} 2>&1 | head -n 8"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return f"{result.stdout}{result.stderr}".strip()


def fastq_validation_outputs() -> list[str]:
    return [f"{RESULTS_DIR}/full_wes_fastq_validation.csv", f"{RESULTS_DIR}/full_wes_fastq_validation.json"]


def bam_validation_outputs() -> list[str]:
    return [f"{RESULTS_DIR}/full_wes_bam_validation.csv", f"{RESULTS_DIR}/full_wes_bam_validation.json"]


def brca_depth_path() -> str:
    return f"{RESULTS_DIR}/logs/cache/brca_interval_depth.tsv"


def truth_depth_path() -> str:
    return f"{RESULTS_DIR}/logs/cache/seqc2_truth_depth.tsv"


def validation_cache_status(row: dict[str, Any]) -> str:
    return str(row.get(VALIDATION_CACHE_KEY, ""))


def strip_internal_keys(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if not key.startswith("_") and key != "validation_cache"}
        for row in rows
    ]


def variant_key_sort_value(key: str) -> tuple[int, int, str, str]:
    contig, position_text, ref, alt = key.split(":", 3)
    contig_suffix = contig.removeprefix("chr")
    if contig_suffix.isdigit():
        contig_order = int(contig_suffix)
    elif contig_suffix == "X":
        contig_order = 23
    elif contig_suffix == "Y":
        contig_order = 24
    else:
        contig_order = 999
    return (contig_order, int(position_text), ref, alt)


def parse_flagstat_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        primary = line.split(" + ", 1)[0]
        if not primary.isdigit():
            continue
        count_value = int(primary)
        if " in total " in line:
            counts["total"] = count_value
        elif " mapped (" in line and "primary mapped" not in line:
            counts["mapped"] = count_value
        elif " properly paired (" in line:
            counts["properly_paired"] = count_value
        elif " duplicates" in line and "primary duplicates" not in line:
            counts["duplicates"] = count_value
    return counts


def validate_fastq_entry(row: dict[str, str], read: str) -> dict[str, Any]:
    path = row[f"fastq_{read}"]
    expected_md5 = row[f"fastq_{read}_md5"]
    expected_bytes = int(row[f"fastq_{read}_bytes"])
    actual_md5 = md5_file(path)
    actual_bytes = path_from_root(path).stat().st_size
    if actual_md5 != expected_md5 or actual_bytes != expected_bytes:
        raise RuntimeError(f"{path} failed md5/byte validation.")
    return {
        "pair_id": row["pair_id"],
        "sample": row["sample"],
        "role": row["role"],
        "run_accession": row["run_accession"],
        "read": read,
        "fastq_path": path,
        "expected_md5": expected_md5,
        "actual_md5": actual_md5,
        "expected_bytes": expected_bytes,
        "actual_bytes": actual_bytes,
        "source_read_pairs": row["source_read_pairs"],
        "status": "passed",
        VALIDATION_CACHE_KEY: "computed",
    }


def reusable_fastq_rows(rows: list[dict[str, str]], telemetry: Optional[RunTelemetry]) -> Optional[list[dict[str, Any]]]:
    if FORCE or not REUSE_FASTQ_VALIDATION:
        return None
    inputs = [row[f"fastq_{read}"] for row in rows for read in ("1", "2")]
    if not existing_output_current(fastq_validation_outputs(), inputs):
        return None
    summary = read_json(path_from_root(f"{RESULTS_DIR}/full_wes_fastq_validation.json"))
    cached_rows = summary.get("rows", [])
    if summary.get("status") != "passed" or len(cached_rows) != len(inputs):
        return None
    expected_by_path = {row[f"fastq_{read}"]: (row[f"fastq_{read}_md5"], int(row[f"fastq_{read}_bytes"])) for row in rows for read in ("1", "2")}
    reusable_rows: list[dict[str, Any]] = []
    for cached in cached_rows:
        path = str(cached.get("fastq_path", ""))
        if path not in expected_by_path:
            return None
        expected_md5, expected_bytes = expected_by_path[path]
        actual_path = path_from_root(path)
        if not actual_path.exists() or actual_path.stat().st_size != expected_bytes:
            return None
        if cached.get("actual_md5") != expected_md5 or int(cached.get("actual_bytes") or 0) != expected_bytes:
            return None
        reusable_rows.append({**cached, VALIDATION_CACHE_KEY: "reused"})
    if telemetry:
        telemetry.event("cache.reuse", {"stage": "fastq_validation", "rows": len(reusable_rows)})
    return reusable_rows


def validate_fastqs(rows: list[dict[str, str]], telemetry: Optional[RunTelemetry]) -> list[dict[str, Any]]:
    cached = reusable_fastq_rows(rows, telemetry)
    if cached is not None:
        return cached
    entries = [(row, read) for row in rows for read in ("1", "2")]
    if telemetry:
        telemetry.event("cache.miss", {"stage": "fastq_validation", "files": len(entries)})
    with ThreadPoolExecutor(max_workers=min(FASTQ_VALIDATION_WORKERS, len(entries))) as pool:
        return list(pool.map(lambda item: validate_fastq_entry(item[0], item[1]), entries))


def command_text_current(
    command: str,
    output_path: str,
    log_path: str,
    inputs: list[str],
    telemetry: Optional[RunTelemetry],
    span_name: str,
    attributes: Optional[dict[str, Any]] = None,
) -> str:
    if not FORCE and existing_output_current([output_path], inputs):
        if telemetry:
            telemetry.event("cache.reuse", {"stage": span_name, "outputPath": output_path})
        return read_text(path_from_root(output_path))
    stdout = run_tool_command(command, log_path, telemetry, span_name, attributes)
    write_text(path_from_root(output_path), stdout)
    return stdout


def log_text_current(
    command: str,
    log_path: str,
    inputs: list[str],
    telemetry: Optional[RunTelemetry],
    span_name: str,
    attributes: Optional[dict[str, Any]] = None,
    parent_span_id: Optional[str] = None,
) -> str:
    if not FORCE and existing_output_current([log_path], inputs):
        if telemetry:
            telemetry.event("cache.reuse", {"stage": span_name, "logPath": log_path})
        return read_text(path_from_root(log_path))
    return run_tool_command(command, log_path, telemetry, span_name, attributes, parent_span_id=parent_span_id)


def alignment_flag_counts(
    reference_id: str,
    row: dict[str, str],
    telemetry: Optional[RunTelemetry],
    parent_span_id: Optional[str] = None,
) -> dict[str, int]:
    flagstat_log = f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_flagstat.txt"
    text = log_text_current(
        f"samtools flagstat -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['dedup_bam'])}",
        flagstat_log,
        [row["dedup_bam"], row["dedup_bai"]],
        telemetry,
        "bam.flagstat",
        {"role": row["role"], "runAccession": row["run_accession"]},
        parent_span_id=parent_span_id,
    )
    counts = parse_flagstat_counts(text)
    if {"total", "mapped", "properly_paired", "duplicates"} <= counts.keys():
        return counts
    raise RuntimeError(f"Could not parse samtools flagstat counts for {row['dedup_bam']}")


def reusable_bam_validation_rows(rows: list[dict[str, str]], telemetry: Optional[RunTelemetry]) -> Optional[list[dict[str, Any]]]:
    if FORCE or not REUSE_BAM_VALIDATION:
        return None
    inputs = [path for row in rows for path in [row["dedup_bam"], row.get("dedup_bai", ""), row.get("duplicate_metrics_path", "")]]
    if not existing_output_current(bam_validation_outputs(), inputs):
        return None
    summary = read_json(path_from_root(f"{RESULTS_DIR}/full_wes_bam_validation.json"))
    cached_rows = summary.get("rows", [])
    if summary.get("status") != "passed" or len(cached_rows) != len(rows):
        return None
    cached_by_role = {row.get("role"): row for row in cached_rows}
    reusable_rows: list[dict[str, Any]] = []
    for row in rows:
        cached = cached_by_role.get(row["role"])
        if not cached:
            return None
        if cached.get("run_accession") != row["run_accession"] or cached.get("dedup_bam") != row["dedup_bam"]:
            return None
        bam_path = path_from_root(row["dedup_bam"])
        bai_path = path_from_root(row["dedup_bai"])
        if not bam_path.exists() or not bai_path.exists() or not quickcheck(row["dedup_bam"]):
            return None
        cached_size = cached.get("bam_size_bytes")
        if cached_size not in ("", None) and int(cached_size) != bam_path.stat().st_size:
            return None
        reusable_rows.append({**cached, VALIDATION_CACHE_KEY: "reused"})
    if telemetry:
        telemetry.event("cache.reuse", {"stage": "bam_validation", "rows": len(reusable_rows)})
    return reusable_rows


def validate_bam_row(
    reference_id: str,
    row: dict[str, str],
    telemetry: Optional[RunTelemetry],
    parent_span_id: Optional[str] = None,
) -> dict[str, Any]:
    header_state = parse_header(capture_command(f"samtools view -H {quote_shell_arg(row['dedup_bam'])}"), row)
    flag_counts = alignment_flag_counts(reference_id, row, telemetry, parent_span_id)
    total_alignments = flag_counts["total"]
    mapped_alignments = flag_counts["mapped"]
    properly_paired_alignments = flag_counts["properly_paired"]
    duplicate_alignments = flag_counts["duplicates"]
    brca_interval_alignments = count(
        f"samtools view -@ {BAM_SCAN_THREADS} -c -L {quote_shell_arg(row['brca_interval_bed_path'])} {quote_shell_arg(row['dedup_bam'])}"
    )
    duplicate_metrics = parse_duplicate_metrics(row["duplicate_metrics_path"])
    status = (
        "passed"
        if quickcheck(row["dedup_bam"])
        and path_from_root(row["dedup_bai"]).exists()
        and header_state["sortOrder"] == "coordinate"
        and header_state["readGroupPresent"]
        and mapped_alignments > 0
        and brca_interval_alignments > 0
        else "failed"
    )
    return {
        "pair_id": row["pair_id"],
        "reference_id": row["reference_id"],
        "assembly": row["assembly"],
        "genome_build": row["genome_build"],
        "role": row["role"],
        "run_accession": row["run_accession"],
        "sample": row["sample"],
        "source_read_pairs": row["source_read_pairs"],
        "raw_bam": row["raw_bam"],
        "dedup_bam": row["dedup_bam"],
        "dedup_bai": row["dedup_bai"],
        "dedup_bam_exists": "yes" if path_from_root(row["dedup_bam"]).exists() else "no",
        "dedup_bai_exists": "yes" if path_from_root(row["dedup_bai"]).exists() else "no",
        "quickcheck": "passed" if quickcheck(row["dedup_bam"]) else "failed",
        "sort_order": header_state["sortOrder"],
        "read_group_present": "yes" if header_state["readGroupPresent"] else "no",
        "read_group_count": header_state["readGroupCount"],
        "reference_contig_count": len(header_state["contigs"]),
        "total_alignments": total_alignments,
        "mapped_alignments": mapped_alignments,
        "mapped_fraction": round_value(mapped_alignments / total_alignments if total_alignments else None, 4),
        "properly_paired_alignments": properly_paired_alignments,
        "properly_paired_fraction": round_value(properly_paired_alignments / total_alignments if total_alignments else None, 4),
        "duplicate_alignments": duplicate_alignments,
        "duplicate_fraction": round_value(duplicate_alignments / total_alignments if total_alignments else None, 4),
        "picard_percent_duplication": duplicate_metrics.get("PERCENT_DUPLICATION", ""),
        "brca_interval_alignments": brca_interval_alignments,
        "bam_size_bytes": path_from_root(row["dedup_bam"]).stat().st_size,
        "duplicate_metrics_path": row["duplicate_metrics_path"],
        "status": status,
        "caveat": row["caveat"],
        VALIDATION_CACHE_KEY: "computed",
    }


def validate_bam_rows(rows: list[dict[str, str]], reference_id: str, telemetry: Optional[RunTelemetry]) -> list[dict[str, Any]]:
    cached = reusable_bam_validation_rows(rows, telemetry)
    if cached is not None:
        return cached
    if telemetry:
        telemetry.event("cache.miss", {"stage": "bam_validation", "rows": len(rows)})
    parent_span_id = telemetry.current_span_id() if telemetry else None
    with ThreadPoolExecutor(max_workers=min(BAM_VALIDATION_WORKERS, len(rows))) as pool:
        return list(pool.map(lambda row: validate_bam_row(reference_id, row, telemetry, parent_span_id), rows))


def run_benchmark(telemetry: Optional[RunTelemetry] = None) -> dict[str, Any]:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    rows = parse_csv(read_text(path_from_root("manifests/full_wes_benchmark_samplesheet.csv")))
    if len(rows) != 2 or not any(row["role"] == "tumor" for row in rows) or not any(row["role"] == "normal" for row in rows):
        raise RuntimeError("Expected tumor and normal rows in manifests/full_wes_benchmark_samplesheet.csv.")
    tumor = next(row for row in rows if row["role"] == "tumor")
    normal = next(row for row in rows if row["role"] == "normal")
    reference_id = tumor["reference_id"]
    output_root = f"data/raw/full_wes_benchmark/seqc2_hcc1395_wes_minimal/{reference_id}"
    interval_dir = f"{output_root}/intervals"
    metrics_dir = f"{output_root}/metrics"
    vcf_dir = f"{output_root}/vcf"
    truth_position_bed = f"{interval_dir}/seqc2_truth_positions.bed"
    benchmark_intervals = f"{interval_dir}/covered_truth_benchmark_intervals.bed"
    contamination_intervals = tumor["brca_interval_bed_path"]
    covered_truth_tsv = f"{interval_dir}/covered_truth_variants.tsv"
    unfiltered_vcf = f"{vcf_dir}/hcc1395.full_wes.resource_aware.mutect2.unfiltered.vcf.gz"
    filtered_vcf = f"{vcf_dir}/hcc1395.full_wes.resource_aware.mutect2.filtered.vcf.gz"
    f1r2_path = f"{vcf_dir}/hcc1395.full_wes.resource_aware.mutect2.f1r2.tar.gz"
    tumor_pileups = f"{metrics_dir}/{tumor['run_accession']}.tumor.getpileupsummaries.table"
    normal_pileups = f"{metrics_dir}/{normal['run_accession']}.normal.getpileupsummaries.table"
    contamination_table = f"{metrics_dir}/hcc1395.calculate_contamination.table"
    if telemetry:
        telemetry.heartbeat(
            "setup",
            {
                "referenceId": reference_id,
                "pairId": tumor["pair_id"],
                "threads": THREADS,
                "bamScanThreads": BAM_SCAN_THREADS,
                "fastqValidationWorkers": FASTQ_VALIDATION_WORKERS,
                "bamValidationWorkers": BAM_VALIDATION_WORKERS,
                "force": FORCE,
            },
        )

    with telemetry.span("fastq.validation", {"files": 4}) if telemetry else nullcontext():
        fastq_rows = validate_fastqs(rows, telemetry)
        if telemetry:
            telemetry.heartbeat(
                "fastq.validation",
                {
                    "status": "passed",
                    "files": len(fastq_rows),
                    "bytes": sum(int(row.get("actual_bytes") or 0) for row in fastq_rows),
                    "cacheRows": sum(1 for row in fastq_rows if validation_cache_status(row) == "reused"),
                },
            )
    fastq_artifact_rows = strip_internal_keys(fastq_rows)
    write_csv(path_from_root(f"{RESULTS_DIR}/full_wes_fastq_validation.csv"), fastq_artifact_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/full_wes_fastq_validation.json"),
        {"generatedAt": iso_now(), "status": "passed", "rows": fastq_artifact_rows},
    )

    with telemetry.span("bam.prepare", {"samples": len(rows)}) if telemetry else nullcontext():
        for row in rows:
            ensure_dir(path_from_root("/".join(row["raw_bam"].split("/")[:-1])))
            ensure_dir(path_from_root("/".join(row["duplicate_metrics_path"].split("/")[:-1])))
            if FORCE or not quickcheck(row["raw_bam"]):
                align_command = (
                    "set -o pipefail; "
                    f"bwa mem -t {THREADS} -R {quote_shell_arg(read_group(row))} {quote_shell_arg(row['reference_path'])} "
                    f"{quote_shell_arg(row['fastq_1'])} {quote_shell_arg(row['fastq_2'])} | "
                    f"samtools sort -@ {THREADS} -o {quote_shell_arg(row['raw_bam'])} -"
                )
                run_tool_command(
                    align_command,
                    f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.full_wes_align.log",
                    telemetry,
                    "bam.align",
                    {"role": row["role"], "runAccession": row["run_accession"]},
                )
            should_mark_duplicates = FORCE or not quickcheck(row["dedup_bam"]) or not path_from_root(row["duplicate_metrics_path"]).exists()
            if should_mark_duplicates:
                run_tool_command(
                    " ".join(
                        [
                            f"{quote_shell_arg(row['java_path'])} -Xmx12g -jar {quote_shell_arg(row['gatk_jar_path'])} MarkDuplicates",
                            f"-I {quote_shell_arg(row['raw_bam'])}",
                            f"-O {quote_shell_arg(row['dedup_bam'])}",
                            f"-M {quote_shell_arg(row['duplicate_metrics_path'])}",
                            "--VALIDATION_STRINGENCY SILENT",
                        ]
                    ),
                    f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.mark_duplicates.log",
                    telemetry,
                    "bam.mark_duplicates",
                    {"role": row["role"], "runAccession": row["run_accession"]},
                )
                run_tool_command(
                    f"samtools index -@ {THREADS} -o {quote_shell_arg(row['dedup_bai'])} {quote_shell_arg(row['dedup_bam'])}",
                    f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_index.log",
                    telemetry,
                    "bam.index",
                    {"role": row["role"], "runAccession": row["run_accession"]},
                )
            elif not path_from_root(row["dedup_bai"]).exists():
                run_tool_command(
                    f"samtools index -@ {THREADS} -o {quote_shell_arg(row['dedup_bai'])} {quote_shell_arg(row['dedup_bam'])}",
                    f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_index.log",
                    telemetry,
                    "bam.index",
                    {"role": row["role"], "runAccession": row["run_accession"]},
                )
            log_text_current(
                f"samtools stats -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['dedup_bam'])}",
                f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_stats.txt",
                [row["dedup_bam"], row["dedup_bai"]],
                telemetry,
                "bam.stats",
                {"role": row["role"], "runAccession": row["run_accession"]},
            )

    with telemetry.span("bam.validation", {"samples": len(rows)}) if telemetry else nullcontext():
        bam_rows = validate_bam_rows(rows, reference_id, telemetry)
        if telemetry:
            telemetry.heartbeat(
                "bam.validation",
                {
                    "status": "passed" if all(row["status"] == "passed" for row in bam_rows) else "failed",
                    "samples": len(bam_rows),
                    "cacheRows": sum(1 for row in bam_rows if validation_cache_status(row) == "reused"),
                    "totalAlignments": sum(int(row.get("total_alignments") or 0) for row in bam_rows),
                },
            )
    bam_status = "passed" if all(row["status"] == "passed" for row in bam_rows) else "failed"
    bam_artifact_rows = strip_internal_keys(bam_rows)
    write_csv(path_from_root(f"{RESULTS_DIR}/full_wes_bam_validation.csv"), bam_artifact_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/full_wes_bam_validation.json"),
        {"generatedAt": iso_now(), "status": bam_status, "rows": bam_artifact_rows},
    )
    if bam_status != "passed":
        raise RuntimeError("Full WES BAM validation failed.")

    with telemetry.span("depth.brca_interval", {"intervalBed": tumor["brca_interval_bed_path"]}) if telemetry else nullcontext():
        brca_depth = command_text_current(
            f"samtools depth -@ {BAM_SCAN_THREADS} -a -b {quote_shell_arg(tumor['brca_interval_bed_path'])} "
            f"{quote_shell_arg(tumor['dedup_bam'])} {quote_shell_arg(normal['dedup_bam'])}",
            brca_depth_path(),
            f"{RESULTS_DIR}/logs/{reference_id}.brca_interval_depth.log",
            [tumor["brca_interval_bed_path"], tumor["dedup_bam"], tumor["dedup_bai"], normal["dedup_bam"], normal["dedup_bai"]],
            telemetry,
            "depth.brca_interval",
            {"intervalBed": tumor["brca_interval_bed_path"]},
        )
        brca_depth_summary = parse_depth_summary(brca_depth)
        if telemetry:
            telemetry.heartbeat("depth.brca_interval", brca_depth_summary)
    truth_snv_path = "data/raw/reference/seqc2_hcc1395_truth/latest/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz"
    truth_indel_path = "data/raw/reference/seqc2_hcc1395_truth/latest/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz"
    normalized_truth_snv_path = normalize_vcf_for_comparison(
        truth_snv_path,
        tumor["reference_path"],
        f"{vcf_dir}/seqc2.high_confidence_sSNV.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.truth_snv.norm.log",
        telemetry,
    )
    normalized_truth_indel_path = normalize_vcf_for_comparison(
        truth_indel_path,
        tumor["reference_path"],
        f"{vcf_dir}/seqc2.high_confidence_sINDEL.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.truth_indel.norm.log",
        telemetry,
    )
    truth_variants = load_truth_variants(normalized_truth_snv_path, "snv") + load_truth_variants(normalized_truth_indel_path, "indel")
    all_truth_keys = {str(variant["key"]) for variant in truth_variants}
    write_truth_position_bed(truth_variants, truth_position_bed)
    with telemetry.span("depth.truth_positions", {"truthVariants": len(truth_variants)}) if telemetry else nullcontext():
        truth_depth_text = command_text_current(
            f"samtools depth -@ {BAM_SCAN_THREADS} -a -b {quote_shell_arg(truth_position_bed)} "
            f"{quote_shell_arg(tumor['dedup_bam'])} {quote_shell_arg(normal['dedup_bam'])}",
            truth_depth_path(),
            f"{RESULTS_DIR}/logs/{reference_id}.truth_depth.log",
            [truth_position_bed, tumor["dedup_bam"], tumor["dedup_bai"], normal["dedup_bam"], normal["dedup_bai"]],
            telemetry,
            "depth.truth_positions",
            {"truthVariantPositions": len(truth_variants)},
        )
        covered_truth_variants = pick_covered_truth_variants(truth_variants, truth_depth_text)
        if telemetry:
            telemetry.heartbeat(
                "depth.truth_positions",
                {
                    "truthVariants": len(truth_variants),
                    "coveredTruthVariants": len(covered_truth_variants),
                    "minTruthDepth": MIN_TRUTH_DEPTH,
                },
            )
    if not covered_truth_variants:
        raise RuntimeError("No covered truth variants passed the Phase 2F depth threshold.")
    benchmark_interval_rows = write_benchmark_intervals(
        covered_truth_variants, read_reference_order(tumor["reference_fai_path"]), benchmark_intervals
    )
    write_csv(
        path_from_root(covered_truth_tsv.replace(".tsv", ".csv")),
        [
            {
                "key": variant["key"],
                "type": variant["type"],
                "contig": variant["contig"],
                "position": variant["position"],
                "ref": variant["ref"],
                "alt": variant["alt"],
                "tumor_depth": variant["tumorDepth"],
                "normal_depth": variant["normalDepth"],
                "min_depth": variant["minDepth"],
            }
            for variant in covered_truth_variants
        ],
    )
    write_text(
        path_from_root(covered_truth_tsv),
        "\n".join(
            ["key\ttype\tcontig\tposition\tref\talt\ttumor_depth\tnormal_depth\tmin_depth"]
            + [
                f"{variant['key']}\t{variant['type']}\t{variant['contig']}\t{variant['position']}\t{variant['ref']}\t{variant['alt']}\t{variant['tumorDepth']}\t{variant['normalDepth']}\t{variant['minDepth']}"
                for variant in covered_truth_variants
            ]
        ),
    )

    ensure_dir(path_from_root(metrics_dir))
    contamination_inputs_ready = (
        file_non_empty(tumor["common_biallelic_resource_path"])
        and file_non_empty(tumor["common_biallelic_resource_index_path"])
        and file_non_empty(contamination_intervals)
    )
    contamination_status = "not_run"
    contamination_reason = ""
    with telemetry.span("contamination", {"inputsReady": contamination_inputs_ready}) if telemetry else nullcontext():
        if contamination_inputs_ready:
            try:
                if FORCE or not file_non_empty(tumor_pileups):
                    run_tool_command(
                        f"{quote_shell_arg(tumor['java_path'])} -Xmx8g -jar {quote_shell_arg(tumor['gatk_jar_path'])} GetPileupSummaries -R {quote_shell_arg(tumor['reference_path'])} -I {quote_shell_arg(tumor['dedup_bam'])} -V {quote_shell_arg(tumor['common_biallelic_resource_path'])} -L {quote_shell_arg(contamination_intervals)} -O {quote_shell_arg(tumor_pileups)}",
                        f"{RESULTS_DIR}/logs/{reference_id}.{tumor['run_accession']}.tumor.get_pileup_summaries.log",
                        telemetry,
                        "contamination.tumor_pileups",
                        {"runAccession": tumor["run_accession"]},
                    )
                if FORCE or not file_non_empty(normal_pileups):
                    run_tool_command(
                        f"{quote_shell_arg(normal['java_path'])} -Xmx8g -jar {quote_shell_arg(normal['gatk_jar_path'])} GetPileupSummaries -R {quote_shell_arg(normal['reference_path'])} -I {quote_shell_arg(normal['dedup_bam'])} -V {quote_shell_arg(normal['common_biallelic_resource_path'])} -L {quote_shell_arg(contamination_intervals)} -O {quote_shell_arg(normal_pileups)}",
                        f"{RESULTS_DIR}/logs/{reference_id}.{normal['run_accession']}.normal.get_pileup_summaries.log",
                        telemetry,
                        "contamination.normal_pileups",
                        {"runAccession": normal["run_accession"]},
                    )
                if FORCE or not file_non_empty(contamination_table):
                    run_tool_command(
                        f"{quote_shell_arg(tumor['java_path'])} -Xmx8g -jar {quote_shell_arg(tumor['gatk_jar_path'])} CalculateContamination -I {quote_shell_arg(tumor_pileups)} -matched {quote_shell_arg(normal_pileups)} -O {quote_shell_arg(contamination_table)}",
                        f"{RESULTS_DIR}/logs/{reference_id}.calculate_contamination.log",
                        telemetry,
                        "contamination.calculate",
                        {"tumorPileups": tumor_pileups, "normalPileups": normal_pileups},
                    )
                contamination_status = "passed" if file_non_empty(contamination_table) else "failed"
            except RuntimeError as error:
                contamination_status = "not_assessable"
                contamination_reason = str(error)
        else:
            contamination_status = "not_assessable"
            contamination_reason = "Common-biallelic resource, index, or contamination intervals were unavailable."
        if telemetry:
            telemetry.heartbeat("contamination", {"status": contamination_status, "reason": contamination_reason})
    contamination_estimate = parse_contamination_table(contamination_table)

    ensure_dir(path_from_root(vcf_dir))
    with telemetry.span("variant_calling", {"caller": tumor["production_caller"]}) if telemetry else nullcontext():
        mutect2_ready = not FORCE and path_from_root(filtered_vcf).exists() and path_from_root(f"{filtered_vcf}.tbi").exists()
        if telemetry:
            telemetry.event("cache.reuse" if mutect2_ready else "cache.miss", {"stage": "variant_calling", "filteredVcf": filtered_vcf})
        if not mutect2_ready:
            run_tool_command(
                " ".join(
                    [
                        f"{quote_shell_arg(tumor['java_path'])} -Xmx12g -jar {quote_shell_arg(tumor['gatk_jar_path'])} Mutect2",
                        f"-R {quote_shell_arg(tumor['reference_path'])}",
                        f"-L {quote_shell_arg(benchmark_intervals)}",
                        f"-I {quote_shell_arg(tumor['dedup_bam'])} -tumor {quote_shell_arg(tumor['sample'])}",
                        f"-I {quote_shell_arg(normal['dedup_bam'])} -normal {quote_shell_arg(normal['sample'])}",
                        f"--panel-of-normals {quote_shell_arg(tumor['mutect2_panel_of_normals_path'])}",
                        f"--native-pair-hmm-threads {max(1, min(THREADS, 8))}",
                        f"--f1r2-tar-gz {quote_shell_arg(f1r2_path)}",
                        f"-O {quote_shell_arg(unfiltered_vcf)}",
                    ]
                ),
                f"{RESULTS_DIR}/logs/{reference_id}.full_wes.resource_aware.mutect2.log",
                telemetry,
                "variant_calling.mutect2",
                {"intervalBed": benchmark_intervals},
            )
            contamination_arg = f"--contamination-table {quote_shell_arg(contamination_table)}" if contamination_status == "passed" else ""
            run_tool_command(
                f"{quote_shell_arg(tumor['java_path'])} -Xmx8g -jar {quote_shell_arg(tumor['gatk_jar_path'])} FilterMutectCalls -R {quote_shell_arg(tumor['reference_path'])} -V {quote_shell_arg(unfiltered_vcf)} {contamination_arg} -O {quote_shell_arg(filtered_vcf)}",
                f"{RESULTS_DIR}/logs/{reference_id}.full_wes.resource_aware.filter_mutect_calls.log",
                telemetry,
                "variant_calling.filter_mutect_calls",
                {"unfilteredVcf": unfiltered_vcf, "filteredVcf": filtered_vcf},
            )
            run_tool_command(
                f"bcftools index -t -f {quote_shell_arg(filtered_vcf)}",
                f"{RESULTS_DIR}/logs/{reference_id}.full_wes.filtered_vcf_index.log",
                telemetry,
                "variant_calling.index",
                {"filteredVcf": filtered_vcf},
            )
        log_text_current(
            f"bcftools stats {quote_shell_arg(filtered_vcf)}",
            f"{RESULTS_DIR}/logs/{reference_id}.full_wes.filtered_vcf_stats.txt",
            [filtered_vcf, f"{filtered_vcf}.tbi"],
            telemetry,
            "variant_calling.stats",
            {"filteredVcf": filtered_vcf},
        )
    normalized_filtered_vcf = normalize_vcf_for_comparison(
        filtered_vcf,
        tumor["reference_path"],
        f"{vcf_dir}/hcc1395.full_wes.mutect2.filtered.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.full_wes.filtered_vcf.norm.log",
        telemetry,
    )

    with telemetry.span("truth_overlap", {"benchmarkIntervalCount": len(benchmark_interval_rows)}) if telemetry else nullcontext():
        filtered_calls = variant_keys(normalized_filtered_vcf, benchmark_intervals)
        truth_keys = {str(variant["key"]) for variant in covered_truth_variants}
        pass_truth_matches = sorted((key for key in filtered_calls["passKeys"] if key in truth_keys), key=variant_key_sort_value)
        all_truth_matches = sorted((key for key in filtered_calls["keys"] if key in truth_keys), key=variant_key_sort_value)
        truth_outside_recall_matches = sorted(
            (key for key in filtered_calls["passKeys"] if key in all_truth_keys and key not in truth_keys), key=variant_key_sort_value
        )
        false_positive_pass = sorted((key for key in filtered_calls["passKeys"] if key not in all_truth_keys), key=variant_key_sort_value)
        false_negative_truth = sorted((key for key in truth_keys if key not in filtered_calls["passKeys"]), key=variant_key_sort_value)
        truth_snv_count = len([variant for variant in covered_truth_variants if variant["type"] == "snv"])
        truth_indel_count = len([variant for variant in covered_truth_variants if variant["type"] == "indel"])
        recall = len(pass_truth_matches) / len(truth_keys) if truth_keys else None
        precision_denominator = len(pass_truth_matches) + len(false_positive_pass)
        precision = len(pass_truth_matches) / precision_denominator if precision_denominator else None
        if telemetry:
            telemetry.heartbeat(
                "truth_overlap",
                {
                    "filteredRecordsInBenchmarkIntervals": filtered_calls["totalCount"],
                    "passRecordsInBenchmarkIntervals": filtered_calls["passCount"],
                    "exactPassTruthMatches": len(pass_truth_matches),
                    "falsePositivePassRecords": len(false_positive_pass),
                    "falseNegativeTruthRecords": len(false_negative_truth),
                    "exactPassRecall": round_value(recall, 4),
                    "exactPassPrecision": round_value(precision, 4),
                },
            )
    mutect_status = "passed" if path_from_root(filtered_vcf).exists() and path_from_root(f"{filtered_vcf}.tbi").exists() else "failed"
    ready_for_phase3 = (
        mutect_status == "passed"
        and bam_status == "passed"
        and len(fastq_rows) == 4
        and contamination_status == "passed"
        and bool(covered_truth_variants)
    )

    benchmark_rows = [
        {
            "status": mutect_status,
            "phase": "2F",
            "caller": tumor["production_caller"],
            "reference_id": reference_id,
            "pair_id": tumor["pair_id"],
            "tumor_sample": tumor["sample"],
            "normal_sample": normal["sample"],
            "tumor_run": tumor["run_accession"],
            "normal_run": normal["run_accession"],
            "source_tumor_read_pairs": tumor["source_read_pairs"],
            "source_normal_read_pairs": normal["source_read_pairs"],
            "duplicate_marking_tool": tumor["duplicate_marking_tool"],
            "germline_resource": tumor["mutect2_germline_resource_path"],
            "germline_resource_source_url": tumor["mutect2_germline_resource_source_url"],
            "panel_of_normals": tumor["mutect2_panel_of_normals_path"],
            "common_biallelic_resource": tumor["common_biallelic_resource_path"],
            "bqsr_known_sites_policy": tumor["bqsr_known_sites_policy"],
            "contamination_policy": tumor["contamination_policy"],
            "contamination_status": contamination_status,
            "contamination_table": contamination_table if contamination_status == "passed" else "",
            "contamination_interval_bed_path": contamination_intervals,
            "contamination_estimate": contamination_estimate["contamination"],
            "contamination_error": contamination_estimate["error"],
            "contamination_reason": contamination_reason,
            "benchmark_interval_bed_path": benchmark_intervals,
            "benchmark_interval_count": len(benchmark_interval_rows),
            "truth_variants_total": len(truth_variants),
            "truth_variants_depth_eligible": len(covered_truth_variants),
            "truth_snv_depth_eligible": truth_snv_count,
            "truth_indel_depth_eligible": truth_indel_count,
            "min_truth_depth": MIN_TRUTH_DEPTH,
            "max_truth_variants": MAX_TRUTH_VARIANTS,
            "filtered_vcf": filtered_vcf,
            "normalized_filtered_vcf": normalized_filtered_vcf,
            "filtered_records_in_benchmark_intervals": filtered_calls["totalCount"],
            "pass_records_in_benchmark_intervals": filtered_calls["passCount"],
            "exact_pass_truth_matches": len(pass_truth_matches),
            "exact_all_filter_truth_matches": len(all_truth_matches),
            "pass_truth_matches_outside_recall_subset": len(truth_outside_recall_matches),
            "false_positive_pass_records": len(false_positive_pass),
            "false_negative_truth_records": len(false_negative_truth),
            "exact_pass_recall": round_value(recall, 4),
            "exact_pass_precision": round_value(precision, 4),
            "brca_tumor_mean_depth": brca_depth_summary["tumorMeanDepth"],
            "brca_normal_mean_depth": brca_depth_summary["normalMeanDepth"],
            "brca_fraction_both_depth_at_least_10": brca_depth_summary["fractionBothDepthAtLeast10"],
            "boundary": "Full WES FASTQs and resource-aware Mutect2 were run on covered SEQC2 truth-overlap intervals. This is full-depth WES small-variant benchmark evidence, not WGS HRD signature, CNV, or SV evidence.",
        }
    ]
    write_csv(path_from_root(f"{RESULTS_DIR}/truth_overlap_benchmark_summary.csv"), benchmark_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/truth_overlap_benchmark_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": mutect_status,
            "rows": benchmark_rows,
            "truthMatchExamples": pass_truth_matches[:20],
            "falsePositiveExamples": false_positive_pass[:20],
            "falseNegativeExamples": false_negative_truth[:20],
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/tool_versions.json"),
        {
            "generatedAt": iso_now(),
            "bwa": {"path": capture_command("command -v bwa"), "version": tool_version("bwa")},
            "samtools": {"path": capture_command("command -v samtools"), "version": tool_version("samtools")},
            "bcftools": {"path": capture_command("command -v bcftools"), "version": tool_version("bcftools")},
            "java": {
                "path": tumor["java_path"],
                "version": capture_command(f"{quote_shell_arg(tumor['java_path'])} -version 2>&1 | head -n 1"),
            },
            "gatk": {
                "jarPath": tumor["gatk_jar_path"],
                "version": capture_command(
                    f"{quote_shell_arg(tumor['java_path'])} -jar {quote_shell_arg(tumor['gatk_jar_path'])} --version 2>&1 | head -n 1"
                ),
            },
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/full_wes_benchmark_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": mutect_status,
            "phase": "2F",
            "caller": tumor["production_caller"],
            "referenceId": reference_id,
            "pairId": tumor["pair_id"],
            "tumorRun": tumor["run_accession"],
            "normalRun": normal["run_accession"],
            "fullWesFastqsValidated": len(fastq_rows),
            "bamValidationStatus": bam_status,
            "benchmarkIntervalCount": len(benchmark_interval_rows),
            "truthVariantsDepthEligible": len(covered_truth_variants),
            "passRecordsInBenchmarkIntervals": filtered_calls["passCount"],
            "exactPassTruthMatches": len(pass_truth_matches),
            "passTruthMatchesOutsideRecallSubset": len(truth_outside_recall_matches),
            "exactPassRecall": round_value(recall, 4),
            "exactPassPrecision": round_value(precision, 4),
            "contaminationStatus": contamination_status,
            "contaminationTable": contamination_table if contamination_status == "passed" else "",
            "contaminationIntervalBedPath": contamination_intervals,
            "contaminationEstimate": contamination_estimate["contamination"],
            "bqsrKnownSitesPolicy": tumor["bqsr_known_sites_policy"],
            "contaminationPolicy": tumor["contamination_policy"],
            "readyForPhase3": ready_for_phase3 and "not WGS HRD signature" in benchmark_rows[0]["boundary"],
            "boundary": "Phase 2F closes raw WES readiness with full FASTQ download, full-reference alignment, duplicate marking, resource-aware Mutect2, and bounded SEQC2 truth comparison. Phase 3 starts WGS HRD signature/CNV/SV capability.",
        },
    )
    write_csv(
        path_from_root(f"{RESULTS_DIR}/full_wes_benchmark_summary.csv"),
        [
            {
                "status": mutect_status,
                "phase": "2F",
                "caller": tumor["production_caller"],
                "reference_id": reference_id,
                "full_wes_fastqs_validated": len(fastq_rows),
                "bam_validation_status": bam_status,
                "benchmark_interval_count": len(benchmark_interval_rows),
                "truth_variants_depth_eligible": len(covered_truth_variants),
                "pass_records_in_benchmark_intervals": filtered_calls["passCount"],
                "exact_pass_truth_matches": len(pass_truth_matches),
                "exact_pass_recall": round_value(recall, 4),
                "exact_pass_precision": round_value(precision, 4),
                "contamination_status": contamination_status,
                "contamination_table": contamination_table if contamination_status == "passed" else "",
                "contamination_interval_bed_path": contamination_intervals,
                "contamination_estimate": contamination_estimate["contamination"],
                "ready_for_phase3": "yes" if ready_for_phase3 else "no",
                "boundary": "Full-depth WES small-variant benchmark complete; WGS HRD signature/CNV/SV evidence remains Phase 3.",
            }
        ],
    )
    write_text(
        path_from_root(f"{RESULTS_DIR}/README.md"),
        f"""# Full WES Benchmark

Status: **{mutect_status}**.

Phase 2F caller path: `{tumor["production_caller"]}`

Reference: `{reference_id}` ({tumor["genome_build"]}/{tumor["assembly"]})

Input: full ENA FASTQ gzip files for SEQC2/HCC1395 WES tumor-normal pair.

Benchmark interval count: `{len(benchmark_interval_rows)}`

Depth-eligible truth variants: `{len(covered_truth_variants)}`

PASS truth matches: `{len(pass_truth_matches)}`

Exact PASS recall: `{round_value(recall, 4)}`

Exact PASS precision: `{round_value(precision, 4)}`

Contamination status: `{contamination_status}`

Contamination estimate: `{contamination_estimate["contamination"] or "not_available"}`

Boundary: this closes Phase 2 raw WES readiness; Phase 3 is WGS HRD signature, CNV, and SV capability.
""",
    )
    if not ready_for_phase3:
        raise RuntimeError("Full WES benchmark failed the Phase 2F ready-for-Phase-3 gate.")
    print(
        f"Full WES benchmark {mutect_status}: {len(covered_truth_variants)} depth-eligible truth variants, {len(pass_truth_matches)} exact PASS truth matches."
    )
    return {
        "status": mutect_status,
        "readyForPhase3": ready_for_phase3,
        "truthVariantsDepthEligible": len(covered_truth_variants),
        "exactPassTruthMatches": len(pass_truth_matches),
        "exactPassRecall": round_value(recall, 4),
        "exactPassPrecision": round_value(precision, 4),
        "fastqCacheRows": sum(1 for row in fastq_rows if validation_cache_status(row) == "reused"),
        "bamCacheRows": sum(1 for row in bam_rows if validation_cache_status(row) == "reused"),
        "telemetryRunId": telemetry.run_id if telemetry else "",
    }


def main() -> None:
    telemetry = RunTelemetry(
        "phase2f_full_wes_benchmark",
        RESULTS_DIR,
        {
            "threads": THREADS,
            "bamScanThreads": BAM_SCAN_THREADS,
            "fastqValidationWorkers": FASTQ_VALIDATION_WORKERS,
            "bamValidationWorkers": BAM_VALIDATION_WORKERS,
            "force": FORCE,
            "reuseFastqValidation": REUSE_FASTQ_VALIDATION,
            "reuseBamValidation": REUSE_BAM_VALIDATION,
        },
    )
    try:
        with telemetry.span("benchmark.full_wes", {"phase": "2F"}):
            result = run_benchmark(telemetry)
        telemetry.finalize("passed", result)
    except Exception as error:
        telemetry.finalize("failed", {"error": str(error)})
        raise


if __name__ == "__main__":
    main()
