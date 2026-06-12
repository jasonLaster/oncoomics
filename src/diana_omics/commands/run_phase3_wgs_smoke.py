from __future__ import annotations

import gzip
import math
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from ..native import native_tool_versions, reference_context, vcf_sample_names
from ..paths import path_from_root
from ..utils import (
    bcftools_norm_ref_mismatch_count,
    capture_allow_empty,
    capture_command,
    detect_cpu_count,
    ensure_dir,
    file_non_empty,
    iso_now,
    median,
    parse_csv,
    quickcheck_bam,
    quote_shell_arg,
    read_json,
    read_text,
    round_value,
    run_command,
    run_commands_parallel,
    standard_contig,
    tool_version,
    write_csv,
    write_json,
    write_text,
)
from . import fetch_phase3_wgs_smoke_assets as phase3_assets

RESULTS_DIR = "results/phase3_wgs_smoke"
FORCE = os.environ.get("PHASE3_WGS_FORCE") == "1"
STAGE = os.environ.get("PHASE3_WGS_STAGE", "all").lower().replace("-", "_")
SAMPLE_ROLE = os.environ.get("PHASE3_WGS_SAMPLE_ROLE", "").lower()
AVAILABLE_CPUS = detect_cpu_count()
TOTAL_THREADS = max(2, int(os.environ.get("PHASE3_WGS_THREADS", str(min(16, AVAILABLE_CPUS)))))
PARALLEL_ALIGN = os.environ.get("PHASE3_WGS_PARALLEL_ALIGN") != "0"
PER_SAMPLE_THREADS = max(2, TOTAL_THREADS // 2) if PARALLEL_ALIGN else TOTAL_THREADS


def optional_positive_int_env(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value or value == "0":
        return fallback
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return parsed


def alignment_thread_plan(default_threads: int) -> tuple[int, int]:
    return (
        optional_positive_int_env("PHASE3_WGS_BWA_THREADS", default_threads),
        optional_positive_int_env("PHASE3_WGS_SORT_THREADS", default_threads),
    )


ALIGN_BWA_THREADS, ALIGN_SORT_THREADS = alignment_thread_plan(TOTAL_THREADS)
PER_SAMPLE_BWA_THREADS, PER_SAMPLE_SORT_THREADS = alignment_thread_plan(PER_SAMPLE_THREADS)
BAM_VALIDATION_WORKERS = max(1, int(os.environ.get("PHASE3_WGS_BAM_VALIDATION_WORKERS", str(min(2, TOTAL_THREADS)))))
REUSE_BAM_VALIDATION = os.environ.get("PHASE3_WGS_REUSE_BAM_VALIDATION", "1") != "0"
GATK_THREADS = max(1, min(int(os.environ.get("PHASE3_WGS_GATK_THREADS", str(TOTAL_THREADS // 2))), 8))
BAM_SCAN_THREADS = max(1, int(os.environ.get("PHASE3_WGS_BAM_SCAN_THREADS", str(max(1, TOTAL_THREADS // 2)))))
ALIGNMENT_CACHE_WORKERS = max(1, int(os.environ.get("PHASE3_WGS_ALIGNMENT_CACHE_WORKERS", str(min(2, TOTAL_THREADS)))))
MIN_TRUTH_DEPTH = int(os.environ.get("PHASE3_WGS_MIN_TRUTH_DEPTH", "1"))
MAX_TRUTH_VARIANTS = int(os.environ.get("PHASE3_WGS_MAX_TRUTH_VARIANTS", "300"))
INTERVAL_PADDING = int(os.environ.get("PHASE3_WGS_INTERVAL_PADDING", "100"))
BIN_SIZE = int(os.environ.get("PHASE3_WGS_CNV_BIN_SIZE", "5000000"))
MATRIX_RECORD_POLICY = os.environ.get("PHASE3_WGS_MATRIX_RECORD_POLICY", "pass_preferred_all_filtered_fallback")
# Cap on REF-mismatch records bcftools norm may drop before we treat it as a
# wrong-reference misconfiguration rather than a few benign discordances.
NORM_MAX_REF_MISMATCH = int(os.environ.get("PHASE3_WGS_NORM_MAX_REF_MISMATCH", "1000"))

MUTATION_TYPES = ["C>A", "C>G", "C>T", "T>A", "T>C", "T>G"]
BASES = ["A", "C", "G", "T"]
COMPLEMENT = {"A": "T", "C": "G", "G": "C", "T": "A"}
SV_CANDIDATE_COLUMNS = [
    "sample",
    "role",
    "run_accession",
    "read_name",
    "chrom1",
    "pos1",
    "chrom2",
    "pos2",
    "template_length",
    "mapq",
    "cigar",
]
SV_SUMMARY_COLUMNS = [
    "status",
    "tool",
    "sample",
    "role",
    "run_accession",
    "input_bam",
    "total_alignments",
    "supplementary_alignments",
    "discordant_mapped_pairs",
    "interchromosomal_pairs",
    "large_insert_pairs",
    "sv_candidate_rows_written",
    "chord_input_status",
    "caveat",
]


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
    sort_order = re.search(r"\bSO:([^\t]+)", hd)
    rg_lines = [line for line in lines if line.startswith("@RG")]
    sq_lines = [line for line in lines if line.startswith("@SQ")]
    contigs = [match.group(1) for line in sq_lines if (match := re.search(r"\bSN:([^\t]+)", line))]
    read_group_present = any(f"ID:{row['read_group_id']}" in line and f"SM:{row['read_group_sample']}" in line for line in rg_lines)
    return {
        "sortOrder": sort_order.group(1) if sort_order else "",
        "readGroupPresent": read_group_present,
        "readGroupCount": len(rg_lines),
        "contigs": contigs,
    }


def count(command: str) -> int:
    return int(capture_command(command) or "0")


def existing_output_current(outputs: list[str], inputs: list[str]) -> bool:
    output_paths = [path_from_root(output) for output in outputs]
    input_paths = [path_from_root(input_path) for input_path in inputs if input_path]
    if not output_paths or any(not output.exists() for output in output_paths):
        return False
    if not input_paths or any(not input_path.exists() for input_path in input_paths):
        return False
    newest_input = max(input_path.stat().st_mtime for input_path in input_paths)
    return all(output.stat().st_mtime >= newest_input for output in output_paths)


def write_text_if_changed(relative_path: str, value: str) -> bool:
    path = path_from_root(relative_path)
    text = value if value.endswith("\n") else f"{value}\n"
    if path.exists() and read_text(path) == text:
        return False
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")
    return True


def cache_safe_name(relative_path: str) -> str:
    return relative_path.strip("/").replace("/", "__")


def sample_validation_cache_uri(row: dict[str, str], relative_path: str) -> str:
    read_label = read_label_from_fastq(row) if row.get("fastq_1") else str(row.get("read_pairs_per_end", "unknownreads"))
    return phase3_assets.cache_uri("validation", row.get("reference_id", "unknown_reference"), read_label, row["role"], cache_safe_name(relative_path))


def pair_validation_cache_uri(tumor: dict[str, str], normal: dict[str, str], group: str, relative_path: str) -> str:
    read_label = read_label_from_fastq(tumor) if tumor.get("fastq_1") else str(tumor.get("read_pairs_per_end", "unknownreads"))
    pair_id = tumor.get("pair_id") or f"{tumor.get('run_accession', 'tumor')}_{normal.get('run_accession', 'normal')}"
    return phase3_assets.cache_uri("validation", tumor.get("reference_id", "unknown_reference"), read_label, "pair", pair_id, group, cache_safe_name(relative_path))


def restore_cached_output(relative_path: str, uri: str, inputs: list[str], label: str) -> bool:
    if FORCE or not uri or not phase3_assets.cache_reads_enabled():
        return False
    if existing_output_current([relative_path], inputs):
        return True
    aws = phase3_assets.aws_cli_path()
    if phase3_assets.s3_object_size(aws, uri) is None:
        print(f"[cache-miss] label={label} uri={uri}", flush=True)
        return False
    phase3_assets.restore_cached_asset(aws, uri, path_from_root(relative_path), None, label)
    if existing_output_current([relative_path], inputs):
        print(f"[cache-reuse] label={label} path={relative_path}", flush=True)
        return True
    path_from_root(relative_path).unlink(missing_ok=True)
    print(f"[cache-skip] label={label} reason=restored_output_not_current path={relative_path}", flush=True)
    return False


def publish_cached_output(relative_path: str, uri: str, label: str) -> bool:
    if not uri or not phase3_assets.cache_writes_enabled():
        return False
    return phase3_assets.publish_cached_asset(phase3_assets.aws_cli_path(), path_from_root(relative_path), uri, label)


def restore_cached_outputs(outputs: list[str], uri_by_output: dict[str, str], inputs: list[str], label: str) -> bool:
    if FORCE or not phase3_assets.cache_reads_enabled() or existing_output_current(outputs, inputs):
        return not FORCE and existing_output_current(outputs, inputs)
    aws = phase3_assets.aws_cli_path()
    if any(not uri_by_output.get(output) or phase3_assets.s3_object_size(aws, uri_by_output[output]) is None for output in outputs):
        print(f"[cache-miss] label={label} outputs={len(outputs)}", flush=True)
        return False
    for output in outputs:
        phase3_assets.restore_cached_asset(aws, uri_by_output[output], path_from_root(output), None, f"{label}.{Path(output).name}")
    if existing_output_current(outputs, inputs):
        print(f"[cache-reuse] label={label} outputs={len(outputs)}", flush=True)
        return True
    for output in outputs:
        path_from_root(output).unlink(missing_ok=True)
    print(f"[cache-skip] label={label} reason=restored_outputs_not_current outputs={len(outputs)}", flush=True)
    return False


def publish_cached_outputs(outputs: list[str], uri_by_output: dict[str, str], label: str) -> int:
    published = 0
    for output in outputs:
        if publish_cached_output(output, uri_by_output.get(output, ""), f"{label}.{Path(output).name}"):
            published += 1
    return published


def run_cached_command(command: str, output_path: str, inputs: list[str], uri: str, label: str) -> str:
    if restore_cached_output(output_path, uri, inputs, label):
        return read_text(path_from_root(output_path))
    output = run_command(command, output_path)
    publish_cached_output(output_path, uri, label)
    return output


def run_cached_output_command(command: str, output_path: str, log_path: str, inputs: list[str], uri: str, label: str) -> None:
    if restore_cached_output(output_path, uri, inputs, label):
        return
    run_command(command, log_path)
    publish_cached_output(output_path, uri, label)
    publish_cached_output(log_path, uri.rsplit("/", 1)[0] + f"/{cache_safe_name(log_path)}" if uri else "", f"{label}.log")


def run_cached_commands_parallel(commands: list[tuple[str, str, list[str], str, str]], workers: int) -> list[str]:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda item: run_cached_command(item[0], item[1], item[2], item[3], item[4]), commands))


def indexed_alignment_count(row: dict[str, str]) -> int:
    if not path_from_root(row["output_bai"]).exists():
        return 0
    return count(f"samtools idxstats {quote_shell_arg(row['output_bam'])} | awk '{{s += $3 + $4}} END {{print s + 0}}'")


def bam_satisfies_read_scope(row: dict[str, str]) -> bool:
    if not quickcheck_bam(row["output_bam"]) or not path_from_root(row["output_bai"]).exists():
        return False
    expected_read_pairs = int(row["read_pairs_per_end"])
    return indexed_alignment_count(row) >= expected_read_pairs


def remove_stale_alignment(row: dict[str, str]) -> None:
    for relative_path in [row["output_bai"], row["output_bam"]]:
        path = path_from_root(relative_path)
        if path.exists():
            path.unlink()


def bam_validation_summary_path() -> str:
    return f"{RESULTS_DIR}/bam_validation_summary.json"


def parse_flagstat_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in text.splitlines():
        primary_count = int(line.split(" + ", 1)[0]) if " + " in line and line.split(" + ", 1)[0].isdigit() else None
        if primary_count is None:
            continue
        if " in total " in line:
            counts["total"] = primary_count
        elif " mapped (" in line and "primary mapped" not in line:
            counts["mapped"] = primary_count
        elif " properly paired (" in line:
            counts["properly_paired"] = primary_count
    return counts


def reusable_bam_validation_rows(rows: list[dict[str, str]]) -> Optional[list[dict[str, Any]]]:
    if FORCE or not REUSE_BAM_VALIDATION:
        return None
    summary_path = path_from_root(bam_validation_summary_path())
    if not summary_path.exists():
        return None
    summary = read_json(summary_path)
    cached_rows = summary.get("rows", [])
    if summary.get("status") != "passed" or len(cached_rows) != len(rows):
        return None
    cached_by_role = {row.get("role"): row for row in cached_rows}
    reusable_rows: list[dict[str, Any]] = []
    for row in rows:
        cached = cached_by_role.get(row["role"])
        if not cached:
            return None
        if cached.get("run_accession") != row["run_accession"] or cached.get("output_bam") != row["output_bam"]:
            return None
        bam_path = path_from_root(row["output_bam"])
        bai_path = path_from_root(row["output_bai"])
        if not bam_path.exists() or not bai_path.exists() or not quickcheck_bam(row["output_bam"]):
            return None
        cached_size = cached.get("bam_size_bytes")
        if cached_size not in ("", None) and int(cached_size) != bam_path.stat().st_size:
            return None
        reusable_rows.append({**cached, "validation_cache": "reused"})
    return reusable_rows


def alignment_flag_counts(reference_id: str, row: dict[str, str]) -> dict[str, int]:
    flagstat_log = f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.flagstat.txt"
    if path_from_root(flagstat_log).exists() and not FORCE:
        counts = parse_flagstat_counts(read_text(path_from_root(flagstat_log)))
        if {"total", "mapped", "properly_paired"} <= counts.keys():
            return counts
    text = run_cached_command(
        f"samtools flagstat -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
        flagstat_log,
        [row["output_bam"], row.get("output_bai", "")],
        sample_validation_cache_uri(row, flagstat_log),
        f"{row['role']}.flagstat",
    )
    counts = parse_flagstat_counts(text)
    if {"total", "mapped", "properly_paired"} <= counts.keys():
        return counts
    raise RuntimeError(f"Could not parse samtools flagstat counts for {row['output_bam']}")


def validate_bam_row(row: dict[str, str]) -> dict[str, Any]:
    header = parse_header(capture_command(f"samtools view -H {quote_shell_arg(row['output_bam'])}"), row)
    flag_counts = alignment_flag_counts(row["reference_id"], row)
    total_alignments = flag_counts["total"]
    mapped_alignments = flag_counts["mapped"]
    properly_paired = flag_counts["properly_paired"]
    standard_mapped_contigs = count(
        f"samtools idxstats {quote_shell_arg(row['output_bam'])} | awk '$1 ~ /^chr([1-9]|1[0-9]|2[0-2]|X|Y)$/ && $3 > 0 {{n++}} END {{print n+0}}'"
    )
    status = (
        "passed"
        if quickcheck_bam(row["output_bam"])
        and path_from_root(row["output_bai"]).exists()
        and header["sortOrder"] == "coordinate"
        and header["readGroupPresent"]
        and len(header["contigs"]) > 20
        and mapped_alignments > 0
        and standard_mapped_contigs > 0
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
        "read_pairs_per_end": row["read_pairs_per_end"],
        "reference_sha256": row["reference_sha256"],
        "output_bam": row["output_bam"],
        "output_bai": row["output_bai"],
        "bam_exists": "yes" if path_from_root(row["output_bam"]).exists() else "no",
        "bai_exists": "yes" if path_from_root(row["output_bai"]).exists() else "no",
        "quickcheck": "passed" if quickcheck_bam(row["output_bam"]) else "failed",
        "sort_order": header["sortOrder"],
        "read_group_present": "yes" if header["readGroupPresent"] else "no",
        "read_group_count": header["readGroupCount"],
        "reference_contig_count": len(header["contigs"]),
        "total_alignments": total_alignments,
        "mapped_alignments": mapped_alignments,
        "mapped_fraction": round_value(mapped_alignments / total_alignments if total_alignments else None, 4),
        "properly_paired_alignments": properly_paired,
        "properly_paired_fraction": round_value(properly_paired / total_alignments if total_alignments else None, 4),
        "mapped_standard_contigs": standard_mapped_contigs,
        "bam_size_bytes": path_from_root(row["output_bam"]).stat().st_size if path_from_root(row["output_bam"]).exists() else "",
        "status": status,
        "caveat": row["caveat"],
        "validation_cache": "computed",
    }


def validate_bam_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    reusable_rows = reusable_bam_validation_rows(rows)
    if reusable_rows is not None:
        print(f"[phase3-wgs] Reusing passed BAM validation summary from {bam_validation_summary_path()}.", flush=True)
        return reusable_rows
    with ThreadPoolExecutor(max_workers=min(BAM_VALIDATION_WORKERS, len(rows))) as pool:
        return list(pool.map(validate_bam_row, rows))


def write_stage_marker(stage: str, payload: dict[str, Any]) -> None:
    marker_path = path_from_root(f"{RESULTS_DIR}/stage_markers/{stage}.json")
    write_json(marker_path, {"generatedAt": iso_now(), "stage": stage, **payload})


def read_label_from_fastq(row: dict[str, str]) -> str:
    match = re.search(r"_R1\.([^.]+)\.fastq(?:\.gz)?$", Path(row["fastq_1"]).name)
    return match.group(1) if match else str(row["read_pairs_per_end"])


def alignment_cache_uris(row: dict[str, str]) -> tuple[str, str]:
    read_label = read_label_from_fastq(row)
    prefix = phase3_assets.cache_uri("bam", row["reference_id"], read_label, row["role"])
    if not prefix:
        return "", ""
    return f"{prefix}/{Path(row['output_bam']).name}", f"{prefix}/{Path(row['output_bai']).name}"


def restore_cached_alignment(row: dict[str, str]) -> bool:
    if FORCE or not phase3_assets.cache_reads_enabled():
        return False
    bam_uri, bai_uri = alignment_cache_uris(row)
    if not bam_uri or not bai_uri:
        return False
    aws = phase3_assets.aws_cli_path()
    if phase3_assets.s3_object_size(aws, bam_uri) is None or phase3_assets.s3_object_size(aws, bai_uri) is None:
        print(f"[cache-miss] label={row['role']}.alignment uri={bam_uri.rsplit('/', 1)[0]}", flush=True)
        return False
    for relative_path in [row["output_bam"], row["output_bai"]]:
        path_from_root(relative_path).unlink(missing_ok=True)
    try:
        phase3_assets.restore_cached_asset(aws, bam_uri, path_from_root(row["output_bam"]), None, f"{row['role']}.bam")
        phase3_assets.restore_cached_asset(aws, bai_uri, path_from_root(row["output_bai"]), None, f"{row['role']}.bai")
    except Exception:
        remove_stale_alignment(row)
        raise
    if bam_satisfies_read_scope(row):
        write_stage_marker(
            f"align_{row['role']}",
            {
                "status": "restored_cache",
                "role": row["role"],
                "runAccession": row["run_accession"],
                "bam": row["output_bam"],
                "bai": row["output_bai"],
                "cacheUri": bam_uri.rsplit("/", 1)[0],
            },
        )
        return True
    print(f"[cache-skip] label={row['role']}.alignment reason=restored_bam_failed_scope_check", flush=True)
    remove_stale_alignment(row)
    return False


def publish_cached_alignment(row: dict[str, str]) -> list[dict[str, Any]]:
    if not phase3_assets.cache_writes_enabled() or not bam_satisfies_read_scope(row):
        return []
    aws = phase3_assets.aws_cli_path()
    bam_uri, bai_uri = alignment_cache_uris(row)
    published: list[dict[str, Any]] = []
    for kind, relative_path, uri in [("bam", row["output_bam"], bam_uri), ("bai", row["output_bai"], bai_uri)]:
        source_path = path_from_root(relative_path)
        if uri and phase3_assets.publish_cached_asset(aws, source_path, uri, f"{row['role']}.{kind}", source_path.stat().st_size):
            published.append({"kind": kind, "uri": uri, "bytes": source_path.stat().st_size})
    return published


def ensure_bwa_index(reference_id: str, reference_path: str) -> None:
    if FORCE or not path_from_root(f"{reference_path}.bwt").exists():
        run_command(f"bwa index {quote_shell_arg(reference_path)}", f"{RESULTS_DIR}/logs/{reference_id}.bwa_index.log")


def align_and_index_sample(reference_id: str, row: dict[str, str]) -> None:
    ensure_dir(path_from_root("/".join(row["output_bam"].split("/")[:-1])))
    if not FORCE and bam_satisfies_read_scope(row):
        write_stage_marker(
            f"align_{row['role']}",
            {
                "status": "skipped_existing",
                "role": row["role"],
                "runAccession": row["run_accession"],
                "bam": row["output_bam"],
                "bai": row["output_bai"],
            },
        )
        return
    if restore_cached_alignment(row):
        return
    remove_stale_alignment(row)
    command = (
        "set -o pipefail; "
        f"bwa mem -t {ALIGN_BWA_THREADS} -R {quote_shell_arg(read_group(row))} {quote_shell_arg(row['reference_path'])} "
        f"{quote_shell_arg(row['fastq_1'])} {quote_shell_arg(row['fastq_2'])} | "
        f"samtools sort -@ {ALIGN_SORT_THREADS} -o {quote_shell_arg(row['output_bam'])} -"
    )
    run_command(command, f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.align.log")
    run_command(
        f"samtools index -@ {TOTAL_THREADS} -o {quote_shell_arg(row['output_bai'])} {quote_shell_arg(row['output_bam'])}",
        f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.index.log",
    )
    flagstat_log = f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.flagstat.txt"
    stats_log = f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.stats.txt"
    run_cached_command(
        f"samtools flagstat -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
        flagstat_log,
        [row["output_bam"], row["output_bai"]],
        sample_validation_cache_uri(row, flagstat_log),
        f"{row['role']}.flagstat",
    )
    run_cached_command(
        f"samtools stats -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
        stats_log,
        [row["output_bam"], row["output_bai"]],
        sample_validation_cache_uri(row, stats_log),
        f"{row['role']}.stats",
    )
    if not bam_satisfies_read_scope(row):
        raise RuntimeError(f"Aligned BAM for {row['role']} did not satisfy requested read scope: {row['output_bam']}")
    published = publish_cached_alignment(row)
    write_stage_marker(
        f"align_{row['role']}",
        {
            "status": "passed",
            "role": row["role"],
            "runAccession": row["run_accession"],
            "threads": TOTAL_THREADS,
            "bwaThreads": ALIGN_BWA_THREADS,
            "sortThreads": ALIGN_SORT_THREADS,
            "bam": row["output_bam"],
            "bai": row["output_bai"],
            "cachePublished": published,
        },
    )


def load_truth_variants(vcf_path: str, variant_type: str) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    with gzip.open(path_from_root(vcf_path), "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            contig, position_text, _id, ref, alt_text, *_rest = line.rstrip("\n").split("\t")
            if not standard_contig(contig):
                continue
            position = int(position_text)
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


def normalize_vcf_for_comparison(vcf_path: str, reference_path: str, output_path: str, log_path: str) -> str:
    if FORCE or not existing_output_current([output_path, f"{output_path}.tbi"], [vcf_path, reference_path]):
        ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
        # --check-ref x excludes records whose REF allele does not match the
        # reference instead of aborting the whole validation on the first one
        # (bcftools defaults to --check-ref e, which exits 255). A handful of
        # discordant sites outside the compared region are tolerated; a flood
        # means the wrong reference, so we fail closed below.
        run_command(
            f"bcftools norm -m -both --check-ref x -f {quote_shell_arg(reference_path)} -Oz -o {quote_shell_arg(output_path)} {quote_shell_arg(vcf_path)}",
            log_path,
        )
        run_command(f"bcftools index -t -f {quote_shell_arg(output_path)}", f"{log_path}.index")
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
    write_text(
        path_from_root(output_path),
        "\n".join(f"{variant['contig']}\t{int(variant['position']) - 1}\t{variant['position']}\t{variant['key']}" for variant in variants),
    )


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
        tumor_depth = int(tumor_text or "0")
        normal_depth = int(normal_text or "0")
        if tumor_depth < MIN_TRUTH_DEPTH or normal_depth < MIN_TRUTH_DEPTH:
            continue
        for variant in by_position.get(f"{contig}:{position_text}", []):
            enriched = dict(variant)
            enriched["tumorDepth"] = tumor_depth
            enriched["normalDepth"] = normal_depth
            enriched["minDepth"] = min(tumor_depth, normal_depth)
            unique[str(enriched["key"])] = enriched
    return sorted(unique.values(), key=lambda row: (-int(row["minDepth"]), str(row["contig"]), int(row["position"])))[:MAX_TRUTH_VARIANTS]


def truth_depth_path() -> str:
    return f"{RESULTS_DIR}/seqc2_truth_depth.tsv"


def truth_depth_text(tumor: dict[str, str], normal: dict[str, str], truth_position_bed: str, reference_id: str) -> str:
    output_path = truth_depth_path()
    inputs = [truth_position_bed, tumor["output_bam"], tumor["output_bai"], normal["output_bam"], normal["output_bai"]]
    if FORCE or not existing_output_current(
        [output_path],
        inputs,
    ):
        run_cached_output_command(
            f"samtools depth -@ {BAM_SCAN_THREADS} -a -b {quote_shell_arg(truth_position_bed)} "
            f"{quote_shell_arg(tumor['output_bam'])} {quote_shell_arg(normal['output_bam'])} > {quote_shell_arg(output_path)}",
            output_path,
            f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.truth_depth.log",
            inputs,
            pair_validation_cache_uri(tumor, normal, "truth_depth", output_path),
            "pair.truth_depth",
        )
    return read_text(path_from_root(output_path))


def run_mutect2_call(
    tumor: dict[str, str],
    normal: dict[str, str],
    mutect_intervals: str,
    unfiltered_vcf: str,
    f1r2_path: str,
    reference_id: str,
    pon_part: str,
) -> None:
    outputs = [unfiltered_vcf, f"{unfiltered_vcf}.tbi"]
    inputs = [
        tumor["output_bam"],
        tumor["output_bai"],
        normal["output_bam"],
        normal["output_bai"],
        tumor["reference_path"],
        mutect_intervals,
    ]
    cache_uris = {output: pair_validation_cache_uri(tumor, normal, "mutect2", output) for output in outputs}
    if not FORCE and (existing_output_current(outputs, inputs) or restore_cached_outputs(outputs, cache_uris, inputs, "pair.mutect2")):
        return
    run_command(
        " ".join(
            [
                f"{quote_shell_arg(tumor['java_path'])} -Xmx10g -jar {quote_shell_arg(tumor['gatk_jar_path'])} Mutect2",
                f"-R {quote_shell_arg(tumor['reference_path'])}",
                f"-L {quote_shell_arg(mutect_intervals)}",
                f"-I {quote_shell_arg(tumor['output_bam'])} -tumor {quote_shell_arg(tumor['sample'])}",
                f"-I {quote_shell_arg(normal['output_bam'])} -normal {quote_shell_arg(normal['sample'])}",
                pon_part,
                f"--native-pair-hmm-threads {GATK_THREADS}",
                f"--f1r2-tar-gz {quote_shell_arg(f1r2_path)}",
                f"-O {quote_shell_arg(unfiltered_vcf)}",
            ]
        ),
        f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.mutect2.log",
    )
    publish_cached_outputs(outputs, cache_uris, "pair.mutect2")
    if path_from_root(f1r2_path).exists():
        publish_cached_output(f1r2_path, pair_validation_cache_uri(tumor, normal, "mutect2", f1r2_path), "pair.mutect2.f1r2")


def run_filter_mutect_calls(
    tumor: dict[str, str],
    normal: dict[str, str],
    unfiltered_vcf: str,
    filtered_vcf: str,
    reference_id: str,
) -> None:
    outputs = [filtered_vcf, f"{filtered_vcf}.tbi"]
    inputs = [unfiltered_vcf, f"{unfiltered_vcf}.tbi", tumor["reference_path"]]
    cache_uris = {output: pair_validation_cache_uri(tumor, normal, "filter_mutect_calls", output) for output in outputs}
    if not FORCE and (existing_output_current(outputs, inputs) or restore_cached_outputs(outputs, cache_uris, inputs, "pair.filter_mutect_calls")):
        return
    run_command(
        f"{quote_shell_arg(tumor['java_path'])} -Xmx6g -jar {quote_shell_arg(tumor['gatk_jar_path'])} "
        f"FilterMutectCalls -R {quote_shell_arg(tumor['reference_path'])} -V {quote_shell_arg(unfiltered_vcf)} -O {quote_shell_arg(filtered_vcf)}",
        f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.filter_mutect_calls.log",
    )
    run_command(
        f"bcftools index -t -f {quote_shell_arg(filtered_vcf)}", f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.filtered_vcf_index.log"
    )
    publish_cached_outputs(outputs, cache_uris, "pair.filter_mutect_calls")


def write_filtered_vcf_stats(tumor: dict[str, str], normal: dict[str, str], filtered_vcf: str, filtered_vcf_stats_log: str) -> None:
    if not FORCE and existing_output_current([filtered_vcf_stats_log], [filtered_vcf, f"{filtered_vcf}.tbi"]):
        return
    run_cached_command(
        f"bcftools stats {quote_shell_arg(filtered_vcf)}",
        filtered_vcf_stats_log,
        [filtered_vcf, f"{filtered_vcf}.tbi"],
        pair_validation_cache_uri(tumor, normal, "filter_mutect_calls", filtered_vcf_stats_log),
        "pair.filter_mutect_calls.stats",
    )


def read_reference_order(fai_path: str) -> dict[str, int]:
    order: dict[str, int] = {}
    for index, line in enumerate(read_text(path_from_root(fai_path)).splitlines()):
        if line:
            order[line.split("\t")[0]] = index
    return order


def write_intervals(variants: list[dict[str, Any]], reference_order: dict[str, int], output_path: str) -> list[dict[str, Any]]:
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
    write_text(path_from_root(output_path), "\n".join(f"{row['contig']}\t{row['start']}\t{row['end']}" for row in merged))
    return merged


def write_fallback_mapped_intervals(rows: list[dict[str, str]], reference_order: dict[str, int], output_path: str) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    for row in rows:
        mapped = capture_allow_empty(
            f'samtools view -F 4 {quote_shell_arg(row["output_bam"])} | awk \'NR<=10000 {{print $3 "\\t" $4 "\\t" length($10)}}\''
        )
        for line in mapped.splitlines():
            contig, start_text, length_text = line.split("\t")
            start_one = int(start_text)
            read_length = int(length_text)
            if not standard_contig(contig) or read_length <= 0:
                continue
            intervals.append(
                {"contig": contig, "start": max(0, start_one - 1 - INTERVAL_PADDING), "end": start_one - 1 + read_length + INTERVAL_PADDING}
            )
    intervals.sort(key=lambda row: (reference_order.get(str(row["contig"]), 9999), int(row["start"]), int(row["end"])))
    step = max(1, len(intervals) // MAX_TRUTH_VARIANTS)
    picked = intervals[::step][:MAX_TRUTH_VARIANTS]
    if not picked:
        raise RuntimeError("No mapped-read fallback intervals could be built for Phase 3 WGS validation.")
    write_text(path_from_root(output_path), "\n".join(f"{row['contig']}\t{row['start']}\t{row['end']}" for row in picked))
    return picked


def parse_vcf_sample_names(vcf_path: str) -> list[str]:
    native_samples = vcf_sample_names(vcf_path)
    if native_samples is not None:
        return native_samples
    header = capture_command(f"bcftools view -h {quote_shell_arg(vcf_path)}")
    sample_line = next((line for line in header.splitlines() if line.startswith("#CHROM")), "")
    return sample_line.split("\t")[9:]


def variant_keys(vcf_path: str, region_bed_path: Optional[str] = None) -> dict[str, Any]:
    region_part = f"-R {quote_shell_arg(region_bed_path)}" if region_bed_path else ""
    rows = capture_allow_empty(f"bcftools view {region_part} -H {quote_shell_arg(vcf_path)}")
    keys: set[str] = set()
    pass_keys: set[str] = set()
    snv_count = indel_count = pass_count = 0
    for line in rows.splitlines():
        if not line:
            continue
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


def build_bins(fai_path: str, output_path: str) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    for line in read_text(path_from_root(fai_path)).splitlines():
        if not line:
            continue
        contig, length_text, *_rest = line.split("\t")
        if not standard_contig(contig):
            continue
        length = int(length_text)
        for start in range(0, length, BIN_SIZE):
            intervals.append({"contig": contig, "start": start, "end": min(length, start + BIN_SIZE)})
    write_text_if_changed(output_path, "\n".join(f"{row['contig']}\t{row['start']}\t{row['end']}" for row in intervals))
    return intervals


def build_coverage_cnv(tumor: dict[str, str], normal: dict[str, str], bins_path: str) -> dict[str, Any]:
    bedcov_output = f"{RESULTS_DIR}/coverage_cnv_bedcov.tsv"
    bins_output = f"{RESULTS_DIR}/coverage_cnv_bins.csv"
    summary_output = f"{RESULTS_DIR}/coverage_cnv_summary.csv"
    summary_json = f"{RESULTS_DIR}/coverage_cnv_summary.json"
    inputs = [bins_path, tumor["output_bam"], tumor["output_bai"], normal["output_bam"], normal["output_bai"]]
    final_outputs = [bins_output, summary_output, summary_json]
    final_cache_uris = {output: pair_validation_cache_uri(tumor, normal, "coverage_cnv", output) for output in final_outputs}
    if not FORCE and (
        existing_output_current(final_outputs, inputs) or restore_cached_outputs(final_outputs, final_cache_uris, inputs, "pair.coverage_cnv")
    ):
        cached_rows = read_json(path_from_root(summary_json)).get("rows", [])
        if cached_rows:
            return {**cached_rows[0], "cnv_cache": "reused"}
    if FORCE or not existing_output_current([bedcov_output], inputs):
        run_cached_output_command(
            f"samtools bedcov {quote_shell_arg(bins_path)} {quote_shell_arg(tumor['output_bam'])} "
            f"{quote_shell_arg(normal['output_bam'])} > {quote_shell_arg(bedcov_output)}",
            bedcov_output,
            f"{RESULTS_DIR}/logs/{tumor.get('reference_id', 'unknown_reference')}.phase3_wgs.coverage_cnv_bedcov.log",
            inputs,
            pair_validation_cache_uri(tumor, normal, "coverage_cnv", bedcov_output),
            "pair.coverage_cnv.bedcov",
        )
    rows: list[dict[str, Any]] = []
    bedcov = read_text(path_from_root(bedcov_output)).strip()
    for line in bedcov.splitlines():
        contig, start_text, end_text, tumor_sum_text, normal_sum_text = line.split("\t")
        start = int(start_text)
        end = int(end_text)
        length = max(1, end - start)
        tumor_depth = float(tumor_sum_text or "0") / length
        normal_depth = float(normal_sum_text or "0") / length
        log2_ratio = math.log2((tumor_depth + 0.0001) / (normal_depth + 0.0001))
        rows.append(
            {
                "contig": contig,
                "start": start,
                "end": end,
                "length": length,
                "tumor_depth_sum": int(tumor_sum_text or "0"),
                "normal_depth_sum": int(normal_sum_text or "0"),
                "tumor_mean_depth": round_value(tumor_depth, 6),
                "normal_mean_depth": round_value(normal_depth, 6),
                "log2_tumor_normal": round_value(log2_ratio, 4),
                "coverage_class": "relative_gain"
                if log2_ratio >= 0.5
                else "relative_loss"
                if log2_ratio <= -0.5
                else "neutral_or_low_signal",
            }
        )
    write_csv(path_from_root(bins_output), rows)
    log2_values = [float(row["log2_tumor_normal"]) for row in rows if row["log2_tumor_normal"] != ""]
    summary = {
        "status": "passed" if rows else "failed",
        "tool": "samtools bedcov",
        "bin_size": BIN_SIZE,
        "bin_count": len(rows),
        "median_log2_tumor_normal": round_value(median(log2_values), 4),
        "relative_gain_bins": sum(1 for row in rows if row["coverage_class"] == "relative_gain"),
        "relative_loss_bins": sum(1 for row in rows if row["coverage_class"] == "relative_loss"),
        "output_bins": "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
        "scarhrd_input_status": "not_assessable_without_allele_specific_segments",
        "caveat": "Real WGS BAM coverage-derived CNV bins from samtools bedcov. This validates CNV feature plumbing but is not allele-specific segmentation or scarHRD.",
    }
    write_csv(path_from_root(summary_output), [summary])
    write_json(
        path_from_root(summary_json),
        {"generatedAt": iso_now(), "status": summary["status"], "rows": [summary]},
    )
    publish_cached_outputs(final_outputs, final_cache_uris, "pair.coverage_cnv")
    return summary


def reverse_complement(sequence: str) -> str:
    return "".join(COMPLEMENT.get(base, "N") for base in reversed(sequence.upper()))


def normalized_context(context: str, ref: str, alt: str) -> Optional[dict[str, str]]:
    context = context.upper()
    ref = ref.upper()
    alt = alt.upper()
    if len(context) != 3 or any(base not in BASES for base in context):
        return None
    if ref in ("C", "T"):
        return {"mutationType": f"{ref}>{alt}", "trinucleotide": f"{context[0]}[{ref}>{alt}]{context[2]}"}
    rc = reverse_complement(context)
    normalized_ref = COMPLEMENT.get(ref, "N")
    normalized_alt = COMPLEMENT.get(alt, "N")
    return {"mutationType": f"{normalized_ref}>{normalized_alt}", "trinucleotide": f"{rc[0]}[{normalized_ref}>{normalized_alt}]{rc[2]}"}


def all_sbs96_rows() -> list[dict[str, Any]]:
    return [
        {
            "sample": "HCC1395",
            "mutation_type": mutation_type,
            "trinucleotide": f"{left}[{mutation_type}]{right}",
            "count": 0,
            "source_records": 0,
            "source_vcf_policy": MATRIX_RECORD_POLICY,
        }
        for mutation_type in MUTATION_TYPES
        for left in BASES
        for right in BASES
    ]


def build_sbs96_matrix(filtered_vcf: str, reference_path: str) -> dict[str, Any]:
    matrix_output = f"{RESULTS_DIR}/wgs_sbs96_matrix.csv"
    summary_output = f"{RESULTS_DIR}/signature_assignment_summary.csv"
    summary_json = f"{RESULTS_DIR}/signature_assignment_summary.json"
    if not FORCE and existing_output_current(
        [matrix_output, summary_output, summary_json],
        [filtered_vcf, f"{filtered_vcf}.tbi", reference_path, f"{reference_path}.fai"],
    ):
        cached_rows = read_json(path_from_root(summary_json)).get("rows", [])
        if cached_rows:
            return {**cached_rows[0], "sbs96_cache": "reused"}
    pass_rows = capture_allow_empty(f"bcftools view -f PASS -v snps -H {quote_shell_arg(filtered_vcf)}")
    all_filtered_rows = capture_allow_empty(f"bcftools view -v snps -H {quote_shell_arg(filtered_vcf)}")
    selected_rows = pass_rows if pass_rows.strip() else all_filtered_rows
    selected_policy = "pass_only" if pass_rows.strip() else "all_filtered_fallback"
    matrix_rows = all_sbs96_rows()
    by_trinucleotide = {str(row["trinucleotide"]): row for row in matrix_rows}
    usable_snvs = skipped_snvs = 0
    for line in selected_rows.splitlines():
        if not line:
            continue
        contig, position_text, _id, ref, alt_text, *_rest = line.split("\t")
        position = int(position_text)
        if not standard_contig(contig) or len(ref) != 1:
            skipped_snvs += 1
            continue
        for alt in alt_text.split(","):
            if len(alt) != 1 or ref.upper() not in BASES or alt.upper() not in BASES:
                skipped_snvs += 1
                continue
            context = reference_context(reference_path, contig, position)
            normalized = normalized_context(context, ref, alt)
            if not normalized or normalized["mutationType"] not in MUTATION_TYPES:
                skipped_snvs += 1
                continue
            row = by_trinucleotide.get(normalized["trinucleotide"])
            if not row:
                skipped_snvs += 1
                continue
            row["count"] = int(row["count"]) + 1
            row["source_records"] = int(row["source_records"]) + 1
            usable_snvs += 1
    write_csv(path_from_root(matrix_output), matrix_rows)
    summary = {
        "status": "passed",
        "tool": "local_sbs96_matrix_builder",
        "source_vcf": filtered_vcf,
        "source_record_policy": selected_policy,
        "sbs96_rows": len(matrix_rows),
        "usable_snv_records": usable_snvs,
        "skipped_snv_records": skipped_snvs,
        "total_matrix_count": sum(int(row["count"]) for row in matrix_rows),
        "sigprofiler_assignment_status": "input_ready_threshold_met" if usable_snvs >= 50 else "not_assessable_low_mutation_count",
        "output_matrix": matrix_output,
        "caveat": "SBS96 matrix is built from actual Phase 3 WGS VCF records. Signature assignment is not interpreted unless mutation count is sufficient.",
    }
    write_csv(path_from_root(summary_output), [summary])
    write_json(
        path_from_root(summary_json),
        {"generatedAt": iso_now(), "status": "passed", "rows": [summary]},
    )
    return summary


def sv_role_cache_paths(row: dict[str, str]) -> tuple[str, str]:
    role = row["role"]
    return f"{RESULTS_DIR}/sv_evidence_cache/{role}.candidates.csv", f"{RESULTS_DIR}/sv_evidence_cache/{role}.summary.json"


def restore_cached_sv_role(row: dict[str, str]) -> Optional[tuple[list[dict[str, Any]], dict[str, Any]]]:
    candidates_path, summary_path = sv_role_cache_paths(row)
    inputs = [row["output_bam"], row.get("output_bai", "")]
    outputs = [candidates_path, summary_path]
    uris = {output: sample_validation_cache_uri(row, output) for output in outputs}
    if FORCE or not restore_cached_outputs(outputs, uris, inputs, f"{row['role']}.sv_evidence"):
        return None
    summary = read_json(path_from_root(summary_path)).get("row", {})
    expected = (row["role"], row["run_accession"], row["output_bam"])
    actual = (summary.get("role"), summary.get("run_accession"), summary.get("input_bam"))
    if actual != expected or summary.get("status") != "passed":
        print(f"[cache-skip] label={row['role']}.sv_evidence reason=metadata_mismatch", flush=True)
        return None
    candidates = parse_csv(read_text(path_from_root(candidates_path)))
    return candidates, {**summary, "sv_cache": "reused_role"}


def publish_cached_sv_role(row: dict[str, str], candidate_rows: list[dict[str, Any]], summary_row: dict[str, Any]) -> None:
    candidates_path, summary_path = sv_role_cache_paths(row)
    write_csv(path_from_root(candidates_path), candidate_rows, SV_CANDIDATE_COLUMNS)
    write_json(path_from_root(summary_path), {"generatedAt": iso_now(), "status": summary_row["status"], "row": summary_row})
    outputs = [candidates_path, summary_path]
    publish_cached_outputs(outputs, {output: sample_validation_cache_uri(row, output) for output in outputs}, f"{row['role']}.sv_evidence")


def build_sv_evidence(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    candidates_output = f"{RESULTS_DIR}/sv_evidence_candidates.csv"
    summary_output = f"{RESULTS_DIR}/sv_evidence_summary.csv"
    summary_json = f"{RESULTS_DIR}/sv_evidence_summary.json"
    expected_keys = {(row["role"], row["run_accession"], row["output_bam"]) for row in rows}
    inputs = [path for row in rows for path in [row["output_bam"], row.get("output_bai", "")]]
    final_outputs = [candidates_output, summary_output, summary_json]
    final_cache_uris = (
        {output: pair_validation_cache_uri(rows[0], rows[1] if len(rows) > 1 else rows[0], "sv_evidence", output) for output in final_outputs}
        if rows
        else {}
    )
    if not FORCE and (
        existing_output_current(final_outputs, inputs) or restore_cached_outputs(final_outputs, final_cache_uris, inputs, "pair.sv_evidence")
    ):
        cached_rows = read_json(path_from_root(summary_json)).get("rows", [])
        cached_keys = {(row.get("role", ""), row.get("run_accession", ""), row.get("input_bam", "")) for row in cached_rows}
        if cached_rows and cached_keys == expected_keys and all(row.get("status") == "passed" for row in cached_rows):
            return [{**row, "sv_cache": "reused"} for row in cached_rows]
    summary_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for row in rows:
        cached_role = restore_cached_sv_role(row)
        if cached_role is not None:
            cached_candidates, cached_summary = cached_role
            candidate_rows.extend(cached_candidates)
            summary_rows.append(cached_summary)
            continue
        total_alignments = indexed_alignment_count(row)
        supplementary = 0
        discordant_mapped_pairs = 0
        interchromosomal_pairs = 0
        large_insert_pairs = 0
        candidate_count = 0
        role_candidate_rows: list[dict[str, Any]] = []
        command = ["samtools", "view", "-@", str(BAM_SCAN_THREADS), row["output_bam"]]
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 9:
                    continue
                flag = int(fields[1])
                if flag & 2048:
                    supplementary += 1
                is_discordant_mapped_pair = (flag & 1) and not (flag & 14)
                if not is_discordant_mapped_pair:
                    continue
                discordant_mapped_pairs += 1
                mate_ref = fields[6]
                template_length = int(fields[8]) if fields[8].lstrip("-").isdigit() else 0
                if mate_ref not in ("=", "*"):
                    interchromosomal_pairs += 1
                if mate_ref == "=" and abs(template_length) > 100000:
                    large_insert_pairs += 1
                if candidate_count >= 100:
                    continue
                read_name, chrom1, pos1, chrom2, pos2, mapq, cigar = (
                    fields[0],
                    fields[2],
                    fields[3],
                    fields[6],
                    fields[7],
                    fields[4],
                    fields[5],
                )
                candidate_rows.append(
                    {
                        "sample": row["sample"],
                        "role": row["role"],
                        "run_accession": row["run_accession"],
                        "read_name": read_name,
                        "chrom1": chrom1,
                        "pos1": pos1,
                        "chrom2": chrom2,
                        "pos2": pos2,
                        "template_length": str(template_length),
                        "mapq": mapq,
                        "cigar": cigar,
                    }
                )
                role_candidate_rows.append(candidate_rows[-1])
                candidate_count += 1
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            if proc.wait() != 0:
                raise RuntimeError(f"samtools view failed for {row['output_bam']}: {stderr}")
        summary_row = {
            "status": "passed",
            "tool": "samtools view flag/evidence counters",
            "sample": row["sample"],
            "role": row["role"],
            "run_accession": row["run_accession"],
            "input_bam": row["output_bam"],
            "total_alignments": total_alignments,
            "supplementary_alignments": supplementary,
            "discordant_mapped_pairs": discordant_mapped_pairs,
            "interchromosomal_pairs": interchromosomal_pairs,
            "large_insert_pairs": large_insert_pairs,
            "sv_candidate_rows_written": candidate_count,
            "chord_input_status": "not_assessable_requires_validated_sv_caller_vcf",
            "caveat": "Real BAM-derived split/discordant/interchromosomal evidence counts. This is WGS SV evidence, not a validated production SV caller VCF.",
        }
        summary_rows.append(summary_row)
        publish_cached_sv_role(row, role_candidate_rows, summary_row)
    write_csv(path_from_root(candidates_output), candidate_rows, SV_CANDIDATE_COLUMNS)
    write_csv(path_from_root(summary_output), summary_rows, SV_SUMMARY_COLUMNS)
    write_json(
        path_from_root(summary_json),
        {
            "generatedAt": iso_now(),
            "status": "passed" if all(row["status"] == "passed" for row in summary_rows) else "failed",
            "rows": summary_rows,
        },
    )
    publish_cached_outputs(final_outputs, final_cache_uris, "pair.sv_evidence")
    return summary_rows


def main() -> None:
    allowed_stages = {"all", "reference_index", "align_sample", "downstream"}
    if STAGE not in allowed_stages:
        raise RuntimeError(f"Unsupported PHASE3_WGS_STAGE={STAGE!r}; choose one of {sorted(allowed_stages)}.")
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    asset_summary = read_json(path_from_root(f"{RESULTS_DIR}/asset_summary.json"))
    if asset_summary.get("status") != "ready":
        raise RuntimeError("Phase 3 WGS asset summary is not ready. Run fetch:phase3-wgs first.")

    rows = parse_csv(read_text(path_from_root("manifests/phase3_wgs_smoke_samplesheet.csv")))
    if len(rows) != 2 or {row["role"] for row in rows} != {"tumor", "normal"}:
        raise RuntimeError("Expected tumor and normal rows in manifests/phase3_wgs_smoke_samplesheet.csv.")
    tumor = next(row for row in rows if row["role"] == "tumor")
    normal = next(row for row in rows if row["role"] == "normal")
    reference_id = tumor["reference_id"]
    output_root = "/".join(tumor["output_bam"].split("/")[:-2])
    interval_dir = f"{output_root}/intervals"
    vcf_dir = f"{output_root}/vcf"
    bins_path = f"{interval_dir}/standard_contig_{BIN_SIZE}bp_bins.bed"
    truth_position_bed = f"{interval_dir}/seqc2_truth_positions.bed"
    mutect_intervals = f"{interval_dir}/phase3_wgs_mutect2_intervals.bed"
    unfiltered_vcf = f"{vcf_dir}/hcc1395.phase3_wgs.mutect2.unfiltered.vcf.gz"
    filtered_vcf = f"{vcf_dir}/hcc1395.phase3_wgs.mutect2.filtered.vcf.gz"
    f1r2_path = f"{vcf_dir}/hcc1395.phase3_wgs.mutect2.f1r2.tar.gz"

    common_required_paths = [
        tumor["reference_path"],
        tumor["reference_fai_path"],
        tumor["reference_dict_path"],
    ]
    if STAGE == "reference_index":
        required_paths = common_required_paths
    elif STAGE == "align_sample":
        if SAMPLE_ROLE not in {"tumor", "normal"}:
            raise RuntimeError("PHASE3_WGS_STAGE=align_sample requires PHASE3_WGS_SAMPLE_ROLE=tumor or normal.")
        selected_row = tumor if SAMPLE_ROLE == "tumor" else normal
        required_paths = common_required_paths + [selected_row["fastq_1"], selected_row["fastq_2"]]
    elif STAGE == "downstream":
        required_paths = common_required_paths + [
            tumor["gatk_jar_path"],
            tumor["truth_snv_vcf_path"],
            tumor["truth_indel_vcf_path"],
            tumor["truth_high_confidence_bed_path"],
            tumor["output_bam"],
            tumor["output_bai"],
            normal["output_bam"],
            normal["output_bai"],
        ]
    else:
        required_paths = []
        for row in rows:
            required_paths.extend(
                [
                    row["fastq_1"],
                    row["fastq_2"],
                    row["reference_path"],
                    row["reference_fai_path"],
                    row["reference_dict_path"],
                    row["gatk_jar_path"],
                ]
            )
    for required_path in dict.fromkeys(required_paths):
        if not path_from_root(required_path).exists():
            raise RuntimeError(f"Required Phase 3 WGS input is missing: {required_path}")

    if STAGE == "reference_index":
        ensure_bwa_index(reference_id, tumor["reference_path"])
        write_stage_marker(
            "reference_index",
            {
                "status": "passed",
                "referenceId": reference_id,
                "referencePath": tumor["reference_path"],
                "threads": TOTAL_THREADS,
            },
        )
        print(f"Phase 3 WGS reference index is ready for {reference_id}.")
        return

    if STAGE == "align_sample":
        ensure_bwa_index(reference_id, tumor["reference_path"])
        align_and_index_sample(reference_id, tumor if SAMPLE_ROLE == "tumor" else normal)
        return

    align_commands: list[tuple[str, str]] = []
    for row in rows:
        ensure_dir(path_from_root("/".join(row["output_bam"].split("/")[:-1])))
        if not FORCE and bam_satisfies_read_scope(row):
            continue
        if restore_cached_alignment(row):
            continue
        remove_stale_alignment(row)
        command = (
            "set -o pipefail; "
            f"bwa mem -t {PER_SAMPLE_BWA_THREADS} -R {quote_shell_arg(read_group(row))} {quote_shell_arg(row['reference_path'])} "
            f"{quote_shell_arg(row['fastq_1'])} {quote_shell_arg(row['fastq_2'])} | "
            f"samtools sort -@ {PER_SAMPLE_SORT_THREADS} -o {quote_shell_arg(row['output_bam'])} -"
        )
        align_commands.append((command, f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.align.log"))
    if align_commands:
        ensure_bwa_index(reference_id, tumor["reference_path"])
        if PARALLEL_ALIGN:
            run_commands_parallel(align_commands, len(align_commands))
        else:
            for command, log_path in align_commands:
                run_command(command, log_path)

    bam_summary_outputs = [f"{RESULTS_DIR}/bam_validation_summary.csv", f"{RESULTS_DIR}/bam_validation_summary.json"]
    bam_summary_inputs = [path for row in rows for path in [row["output_bam"], row.get("output_bai", "")]]
    restore_cached_outputs(
        bam_summary_outputs,
        {output: pair_validation_cache_uri(tumor, normal, "bam_validation", output) for output in bam_summary_outputs},
        bam_summary_inputs,
        "pair.bam_validation",
    )
    reusable_bam_rows = reusable_bam_validation_rows(rows)
    if reusable_bam_rows is None:
        index_commands: list[tuple[str, str]] = []
        stats_commands: list[tuple[str, str, list[str], str, str]] = []
        for row in rows:
            if FORCE or not existing_output_current([row["output_bai"]], [row["output_bam"]]):
                index_commands.append(
                    (
                        f"samtools index -@ {PER_SAMPLE_THREADS} -o {quote_shell_arg(row['output_bai'])} {quote_shell_arg(row['output_bam'])}",
                        f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.index.log",
                    )
                )
            flagstat_log = f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.flagstat.txt"
            stats_log = f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.stats.txt"
            if FORCE or not existing_output_current([flagstat_log], [row["output_bam"]]):
                stats_commands.append(
                    (
                        f"samtools flagstat -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
                        flagstat_log,
                        [row["output_bam"], row["output_bai"]],
                        sample_validation_cache_uri(row, flagstat_log),
                        f"{row['role']}.flagstat",
                    )
                )
            if FORCE or not existing_output_current([stats_log], [row["output_bam"]]):
                stats_commands.append(
                    (
                        f"samtools stats -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
                        stats_log,
                        [row["output_bam"], row["output_bai"]],
                        sample_validation_cache_uri(row, stats_log),
                        f"{row['role']}.stats",
                    )
                )
        if index_commands:
            run_commands_parallel(index_commands, len(index_commands))
        if stats_commands:
            run_cached_commands_parallel(stats_commands, min(4, len(stats_commands)))

    with ThreadPoolExecutor(max_workers=min(ALIGNMENT_CACHE_WORKERS, len(rows))) as pool:
        alignment_cache_rows = list(pool.map(publish_cached_alignment, rows))
    bam_rows = reusable_bam_rows if reusable_bam_rows is not None else validate_bam_rows(rows)
    bam_status = "passed" if all(row["status"] == "passed" for row in bam_rows) else "failed"
    write_csv(path_from_root(f"{RESULTS_DIR}/bam_validation_summary.csv"), bam_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/bam_validation_summary.json"), {"generatedAt": iso_now(), "status": bam_status, "rows": bam_rows}
    )
    publish_cached_outputs(
        bam_summary_outputs,
        {output: pair_validation_cache_uri(tumor, normal, "bam_validation", output) for output in bam_summary_outputs},
        "pair.bam_validation",
    )
    if bam_status != "passed":
        raise RuntimeError("Phase 3 WGS BAM validation failed.")

    ensure_dir(path_from_root(interval_dir))
    ensure_dir(path_from_root(vcf_dir))
    build_bins(tumor["reference_fai_path"], bins_path)
    cnv_summary = build_coverage_cnv(tumor, normal, bins_path)

    normalized_truth_snv_path = normalize_vcf_for_comparison(
        tumor["truth_snv_vcf_path"],
        tumor["reference_path"],
        f"{vcf_dir}/seqc2.phase3.high_confidence_sSNV.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.truth_snv.norm.log",
    )
    normalized_truth_indel_path = normalize_vcf_for_comparison(
        tumor["truth_indel_vcf_path"],
        tumor["reference_path"],
        f"{vcf_dir}/seqc2.phase3.high_confidence_sINDEL.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.truth_indel.norm.log",
    )
    truth_variants = load_truth_variants(normalized_truth_snv_path, "snv") + load_truth_variants(normalized_truth_indel_path, "indel")
    write_truth_position_bed(truth_variants, truth_position_bed)
    covered_truth = pick_covered_truth_variants(truth_variants, truth_depth_text(tumor, normal, truth_position_bed, reference_id))
    reference_order = read_reference_order(tumor["reference_fai_path"])
    interval_rows = (
        write_intervals(covered_truth, reference_order, mutect_intervals)
        if covered_truth
        else write_fallback_mapped_intervals(rows, reference_order, mutect_intervals)
    )
    write_csv(
        path_from_root(f"{RESULTS_DIR}/covered_truth_variants.csv"),
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
            for variant in covered_truth
        ],
    )

    pon_part = (
        f"--panel-of-normals {quote_shell_arg(tumor['mutect2_panel_of_normals_path'])}"
        if file_non_empty(tumor["mutect2_panel_of_normals_path"])
        else ""
    )
    run_mutect2_call(tumor, normal, mutect_intervals, unfiltered_vcf, f1r2_path, reference_id, pon_part)
    run_filter_mutect_calls(tumor, normal, unfiltered_vcf, filtered_vcf, reference_id)
    filtered_vcf_stats_log = f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.filtered_vcf_stats.txt"
    write_filtered_vcf_stats(tumor, normal, filtered_vcf, filtered_vcf_stats_log)

    filtered_samples = parse_vcf_sample_names(filtered_vcf)
    normalized_filtered_vcf = normalize_vcf_for_comparison(
        filtered_vcf,
        tumor["reference_path"],
        f"{vcf_dir}/hcc1395.phase3_wgs.mutect2.filtered.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.phase3_wgs.filtered_vcf.norm.log",
    )
    filtered_calls = variant_keys(normalized_filtered_vcf, mutect_intervals)
    truth_snv_active = variant_keys(normalized_truth_snv_path, mutect_intervals)
    truth_indel_active = variant_keys(normalized_truth_indel_path, mutect_intervals)
    truth_active_keys = set(truth_snv_active["keys"]) | set(truth_indel_active["keys"])
    exact_matches = [key for key in filtered_calls["passKeys"] if key in truth_active_keys]
    mutect_status = (
        "passed"
        if path_from_root(filtered_vcf).exists()
        and path_from_root(f"{filtered_vcf}.tbi").exists()
        and tumor["sample"] in filtered_samples
        and normal["sample"] in filtered_samples
        else "failed"
    )
    comparison_status = (
        "not_assessable_no_depth_covered_truth_variants_in_wgs_validation"
        if not covered_truth
        else "assessed_no_passing_mutect2_calls"
        if filtered_calls["passCount"] == 0
        else "assessed_exact_key_overlap"
    )
    mutect_row = {
        "status": mutect_status,
        "phase": "3",
        "caller": tumor["production_caller"],
        "reference_id": reference_id,
        "pair_id": tumor["pair_id"],
        "tumor_sample": tumor["sample"],
        "normal_sample": normal["sample"],
        "tumor_run": tumor["run_accession"],
        "normal_run": normal["run_accession"],
        "read_pairs_per_end": tumor["read_pairs_per_end"],
        "interval_strategy": "covered_seqc2_truth_variants" if covered_truth else "mapped_read_fallback_intervals",
        "mutect_interval_bed_path": mutect_intervals,
        "mutect_interval_count": len(interval_rows),
        "truth_variants_total": len(truth_variants),
        "truth_variants_depth_eligible": len(covered_truth),
        "truth_snv_records_in_intervals": truth_snv_active["totalCount"],
        "truth_indel_records_in_intervals": truth_indel_active["totalCount"],
        "filtered_vcf": filtered_vcf,
        "filtered_tbi": f"{filtered_vcf}.tbi",
        "filtered_records_in_intervals": filtered_calls["totalCount"],
        "pass_records_in_intervals": filtered_calls["passCount"],
        "exact_pass_truth_matches": len(exact_matches),
        "comparison_status": comparison_status,
        "panel_of_normals_used": tumor["mutect2_panel_of_normals_path"] if pon_part else "",
        "caveat": "Real GATK Mutect2 WGS small-variant output over covered SEQC2 truth intervals. Genome-wide HRD interpretation still needs production caller policy.",
    }
    write_csv(path_from_root(f"{RESULTS_DIR}/mutect2_wgs_summary.csv"), [mutect_row])
    write_json(
        path_from_root(f"{RESULTS_DIR}/mutect2_wgs_summary.json"), {"generatedAt": iso_now(), "status": mutect_status, "rows": [mutect_row]}
    )

    signature_summary = build_sbs96_matrix(filtered_vcf, tumor["reference_path"])
    sv_rows = build_sv_evidence(rows)
    hrd_tool_rows = [
        {
            "tool": "SigProfilerAssignment",
            "evidence_input": "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
            "local_phase3_output": "results/phase3_wgs_smoke/signature_assignment_summary.csv",
            "real_output_status": "real_sbs96_matrix_output",
            "interpretability_status": signature_summary["sigprofiler_assignment_status"],
            "caveat": "Classification is deferred for low mutation count; the matrix is a real VCF-derived output, not a proxy.",
        },
        {
            "tool": "scarHRD",
            "evidence_input": "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
            "local_phase3_output": "results/phase3_wgs_smoke/coverage_cnv_summary.csv",
            "real_output_status": "real_coverage_cnv_bin_output",
            "interpretability_status": cnv_summary["scarhrd_input_status"],
            "caveat": "scarHRD needs allele-specific segmented CN calls; this run validates WGS coverage-bin plumbing only.",
        },
        {
            "tool": "CHORD",
            "evidence_input": "results/phase3_wgs_smoke/sv_evidence_summary.csv",
            "local_phase3_output": "results/phase3_wgs_smoke/sv_evidence_summary.csv",
            "real_output_status": "real_bam_sv_evidence_output",
            "interpretability_status": "not_assessable_requires_validated_sv_caller_vcf",
            "caveat": "CHORD-style interpretation needs full-depth SNV/indel/SV/CNV feature inputs; this validates the feature lanes.",
        },
    ]
    write_csv(path_from_root(f"{RESULTS_DIR}/hrd_tool_readiness_summary.csv"), hrd_tool_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/hrd_tool_readiness_summary.json"),
        {"generatedAt": iso_now(), "status": "passed", "rows": hrd_tool_rows},
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
            "optionalNativeIntegrations": native_tool_versions(),
        },
    )

    phase3_complete = (
        bam_status == "passed"
        and mutect_status == "passed"
        and cnv_summary["status"] == "passed"
        and signature_summary["status"] == "passed"
        and all(row["status"] == "passed" for row in sv_rows)
    )
    summary_row = {
        "status": "passed" if phase3_complete else "failed",
        "phase": "3",
        "pair_id": tumor["pair_id"],
        "reference_id": reference_id,
        "read_pairs_per_end": tumor["read_pairs_per_end"],
        "read_pairs_mode": asset_summary.get("readPairsMode", ""),
        "read_request": asset_summary.get("readRequest", ""),
        "available_cpus": AVAILABLE_CPUS,
        "total_threads": TOTAL_THREADS,
        "align_bwa_threads": ALIGN_BWA_THREADS,
        "align_sort_threads": ALIGN_SORT_THREADS,
        "parallel_align": "yes" if PARALLEL_ALIGN else "no",
        "per_sample_threads": PER_SAMPLE_THREADS,
        "per_sample_bwa_threads": PER_SAMPLE_BWA_THREADS,
        "per_sample_sort_threads": PER_SAMPLE_SORT_THREADS,
        "gatk_threads": GATK_THREADS,
        "alignment_cache_workers": ALIGNMENT_CACHE_WORKERS,
        "bam_validation_status": bam_status,
        "mutect2_status": mutect_status,
        "normalized_filtered_vcf": normalized_filtered_vcf,
        "mutect_interval_count": len(interval_rows),
        "truth_variants_depth_eligible": len(covered_truth),
        "pass_records_in_intervals": filtered_calls["passCount"],
        "exact_pass_truth_matches": len(exact_matches),
        "coverage_cnv_status": cnv_summary["status"],
        "coverage_cnv_bins": cnv_summary["bin_count"],
        "sbs96_matrix_status": signature_summary["status"],
        "sbs96_usable_snv_records": signature_summary["usable_snv_records"],
        "sv_evidence_status": "passed" if all(row["status"] == "passed" for row in sv_rows) else "failed",
        "alignment_cache_events": sum(len(row) for row in alignment_cache_rows),
        "phase3_complete": "yes" if phase3_complete else "no",
        "ready_for_phase4_when_diana_raw_arrives": "yes" if phase3_complete else "no",
        "boundary": "Phase 3 validates WGS-capable mechanics with real representative WGS FASTQ, BAM, small-variant VCF, coverage-CNV bins, SBS96 matrix, and SV evidence outputs. Full-depth Diana interpretation still needs Diana raw data and production CNV/SV/signature policy.",
    }
    write_csv(path_from_root(f"{RESULTS_DIR}/phase3_wgs_summary.csv"), [summary_row])
    write_json(
        path_from_root(f"{RESULTS_DIR}/phase3_wgs_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": summary_row["status"],
            "phase": "3",
            "pairId": tumor["pair_id"],
            "referenceId": reference_id,
            "readPairsPerEnd": int(tumor["read_pairs_per_end"]),
            "readPairsMode": asset_summary.get("readPairsMode", ""),
            "readRequest": asset_summary.get("readRequest", ""),
            "fullSourceFastqs": asset_summary.get("readPairsMode") == "full",
            "availableCpus": AVAILABLE_CPUS,
            "totalThreads": TOTAL_THREADS,
            "alignBwaThreads": ALIGN_BWA_THREADS,
            "alignSortThreads": ALIGN_SORT_THREADS,
            "parallelAlign": PARALLEL_ALIGN,
            "perSampleThreads": PER_SAMPLE_THREADS,
            "perSampleBwaThreads": PER_SAMPLE_BWA_THREADS,
            "perSampleSortThreads": PER_SAMPLE_SORT_THREADS,
            "gatkThreads": GATK_THREADS,
            "alignmentCacheWorkers": ALIGNMENT_CACHE_WORKERS,
            "bamValidationStatus": bam_status,
            "mutect2Status": mutect_status,
            "normalizedFilteredVcf": normalized_filtered_vcf,
            "mutectIntervalCount": len(interval_rows),
            "truthVariantsDepthEligible": len(covered_truth),
            "passRecordsInIntervals": filtered_calls["passCount"],
            "exactPassTruthMatches": len(exact_matches),
            "coverageCnvStatus": cnv_summary["status"],
            "coverageCnvBins": cnv_summary["bin_count"],
            "sbs96MatrixStatus": signature_summary["status"],
            "sbs96UsableSnvRecords": signature_summary["usable_snv_records"],
            "svEvidenceStatus": summary_row["sv_evidence_status"],
            "alignmentCacheEvents": summary_row["alignment_cache_events"],
            "phase3Complete": phase3_complete,
            "readyForPhase4WhenDianaRawArrives": phase3_complete,
            "boundary": summary_row["boundary"],
        },
    )
    write_text(
        path_from_root(f"{RESULTS_DIR}/README.md"),
        f"""# Phase 3 WGS HRD Capability Validation

Status: **{"passed" if phase3_complete else "failed"}**.

Representative pair: `{tumor["pair_id"]}`

Reference: `{reference_id}` ({tumor["genome_build"]}/{tumor["assembly"]})

Reads per FASTQ end: `{tumor["read_pairs_per_end"]}`

Read mode: `{asset_summary.get("readPairsMode", "")}`

Parallelism:

1. Available CPUs detected: `{AVAILABLE_CPUS}`
2. Total thread budget: `{TOTAL_THREADS}`
3. Tumor/normal alignment in parallel: `{"yes" if PARALLEL_ALIGN else "no"}`
4. Split-process BWA threads: `{ALIGN_BWA_THREADS}`
5. Split-process samtools sort threads: `{ALIGN_SORT_THREADS}`
6. Monolith per-sample BWA threads: `{PER_SAMPLE_BWA_THREADS}`
7. Monolith per-sample samtools sort threads: `{PER_SAMPLE_SORT_THREADS}`
8. GATK PairHMM threads: `{GATK_THREADS}`

What this validates:

1. Real representative HCC1395 WGS FASTQ alignment to the full hg38 analysis-set reference.
2. Coordinate-sorted, indexed, read-grouped tumor and matched-normal WGS BAM contracts.
3. Real GATK Mutect2/FilterMutectCalls tumor-normal WGS VCF output.
4. Real coverage-derived tumor/normal CNV bin output from `samtools bedcov`.
5. Real SBS96 mutation matrix output from the actual WGS VCF.
6. Real BAM-derived SV evidence counts from split/supplementary/discordant/interchromosomal read evidence.
7. A clear boundary between WES small-variant evidence, WGS-capable smoke outputs, and full-depth WGS HRD interpretation.

What remains Diana-specific:

1. Full-depth WGS or WES input inventory, reference policy, and production compute target.
2. Allele-specific CNV segmentation for scarHRD.
3. Validated SV caller VCF for CHORD/HRDetect-style feature extraction.
4. Stable SBS signature assignment only when mutation count and coverage are adequate.
5. Reviewer sign-off before any treatment-changing interpretation.
""",
    )
    if not phase3_complete:
        raise RuntimeError("Phase 3 WGS validation failed.")
    print(
        f"Phase 3 WGS validation passed: {len(interval_rows)} intervals, {filtered_calls['passCount']} PASS calls, {cnv_summary['bin_count']} CNV bins."
    )


if __name__ == "__main__":
    main()
