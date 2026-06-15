from __future__ import annotations

import gzip
import hashlib
import io
import math
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from ...native import native_tool_versions, reference_context, vcf_sample_names
from ...paths import path_from_root
from ...utils import (
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
    validate_fastq_record,
    write_csv,
    write_json,
    write_text,
)
from . import fetch_phase3_wgs_smoke_assets as phase3_assets

RESULTS_DIR = "results/phase3_wgs_smoke"
FORCE = os.environ.get("PHASE3_WGS_FORCE") == "1"
FORCE_SHARD_ALIGNMENT = os.environ.get("PHASE3_WGS_FORCE_SHARD_ALIGNMENT") == "1"
STAGE = os.environ.get("PHASE3_WGS_STAGE", "all").lower().replace("-", "_")
SAMPLE_ROLE = os.environ.get("PHASE3_WGS_SAMPLE_ROLE", "").lower()
AVAILABLE_CPUS = detect_cpu_count()
TOTAL_THREADS = max(2, int(os.environ.get("PHASE3_WGS_THREADS", str(min(16, AVAILABLE_CPUS)))))
PARALLEL_ALIGN = os.environ.get("PHASE3_WGS_PARALLEL_ALIGN") != "0"
PER_SAMPLE_THREADS = max(2, TOTAL_THREADS // 2) if PARALLEL_ALIGN else TOTAL_THREADS
ALIGN_INPUT_MODE = os.environ.get("PHASE3_WGS_ALIGN_INPUT_MODE", "local_fastq").lower().replace("-", "_")
ALIGNER = os.environ.get("PHASE3_WGS_ALIGNER", "bwa").lower().replace("_", "-")
ALIGN_PROFILE_MODE = os.environ.get("PHASE3_WGS_ALIGN_PROFILE_MODE", "pipe").lower().replace("-", "_")
SCATTER_OUTPUT_MODE = os.environ.get("PHASE3_WGS_SCATTER_OUTPUT_MODE", "merged_bam").lower().replace("-", "_")
SHARD_INPUT_MODE = os.environ.get("PHASE3_WGS_SHARD_INPUT_MODE", "fastq_cache").lower().replace("-", "_")
SHARD_INDEX = int(os.environ.get("PHASE3_WGS_SHARD_INDEX", "0") or "0")
SHARD_COUNT = int(os.environ.get("PHASE3_WGS_SHARD_COUNT", "1") or "1")
SORT_MEMORY = os.environ.get("PHASE3_WGS_SORT_MEMORY", "2G")
BAM_VALIDATION_MODE = os.environ.get("PHASE3_WGS_BAM_VALIDATION_MODE", "full").lower().replace("-", "_")
if BAM_VALIDATION_MODE == "fast":
    BAM_VALIDATION_MODE = "flagstat_only"
if BAM_VALIDATION_MODE not in {"full", "flagstat_only"}:
    raise ValueError("PHASE3_WGS_BAM_VALIDATION_MODE must be one of: full, flagstat_only")
COVERAGE_CNV_MODE = os.environ.get("PHASE3_WGS_COVERAGE_CNV_MODE", "full").lower().replace("-", "_")
if COVERAGE_CNV_MODE == "fast":
    COVERAGE_CNV_MODE = "metadata"
if COVERAGE_CNV_MODE not in {"full", "idxstats", "metadata"}:
    raise ValueError("PHASE3_WGS_COVERAGE_CNV_MODE must be one of: full, idxstats, metadata")


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
PUBLIC_BAM_ARIA2_SPLIT = max(1, int(os.environ.get("PHASE3_WGS_PUBLIC_BAM_ARIA2_SPLIT", os.environ.get("PHASE3_WGS_ARIA2_SPLIT", "8"))))
GATK_THREADS = max(1, min(int(os.environ.get("PHASE3_WGS_GATK_THREADS", str(TOTAL_THREADS // 2))), 8))
BAM_SCAN_THREADS = max(1, int(os.environ.get("PHASE3_WGS_BAM_SCAN_THREADS", str(max(1, TOTAL_THREADS // 2)))))
CNV_BEDCOV_WORKERS = max(1, int(os.environ.get("PHASE3_WGS_CNV_BEDCOV_WORKERS", str(min(4, TOTAL_THREADS)))))
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


def bam_stats_enabled() -> bool:
    return BAM_VALIDATION_MODE == "full"


def bam_validation_cache_group() -> str:
    return "bam_validation" if BAM_VALIDATION_MODE == "full" else f"bam_validation_{BAM_VALIDATION_MODE}"


def coverage_cnv_cache_group() -> str:
    return "coverage_cnv" if COVERAGE_CNV_MODE == "full" else f"coverage_cnv_{COVERAGE_CNV_MODE}"


def public_bam_timing_mode(row: dict[str, str]) -> bool:
    return row.get("production_caller") == "skipped_for_public_bam_timing"


def downstream_can_skip_bam_hydration(row: dict[str, str]) -> bool:
    return public_bam_timing_mode(row) and BAM_VALIDATION_MODE == "flagstat_only" and COVERAGE_CNV_MODE in {
        "idxstats",
        "metadata",
    }


def alignment_materialization_required_for_stage(stage: str, row: dict[str, str]) -> bool:
    return not (stage == "downstream" and downstream_can_skip_bam_hydration(row))


def phase3_completion_status(
    tumor: dict[str, str],
    *,
    bam_status: str,
    mutect_status: str,
    cnv_status: str,
    signature_status: str,
    sv_rows: list[dict[str, Any]],
) -> bool:
    sv_status = all(row["status"] == "passed" for row in sv_rows)
    if public_bam_timing_mode(tumor):
        return (
            bam_status == "passed"
            and mutect_status == "skipped_public_bam_timing"
            and cnv_status == "passed"
            and signature_status == "skipped_public_bam_timing"
            and sv_status
        )
    return bam_status == "passed" and mutect_status == "passed" and cnv_status == "passed" and signature_status == "passed" and sv_status


def cached_output_usable(relative_path: str, inputs: list[str], require_current: bool) -> bool:
    path = path_from_root(relative_path)
    if require_current:
        return existing_output_current([relative_path], inputs)
    return path.exists()


def restore_cached_output(relative_path: str, uri: str, inputs: list[str], label: str, *, require_current: bool = True) -> bool:
    if FORCE or not uri or not phase3_assets.cache_reads_enabled():
        return False
    if cached_output_usable(relative_path, inputs, require_current):
        return True
    aws = phase3_assets.aws_cli_path()
    if phase3_assets.s3_object_size(aws, uri) is None:
        print(f"[cache-miss] label={label} uri={uri}", flush=True)
        return False
    phase3_assets.restore_cached_asset(aws, uri, path_from_root(relative_path), None, label)
    if cached_output_usable(relative_path, inputs, require_current):
        print(f"[cache-reuse] label={label} path={relative_path}", flush=True)
        return True
    path_from_root(relative_path).unlink(missing_ok=True)
    print(f"[cache-skip] label={label} reason=restored_output_not_current path={relative_path}", flush=True)
    return False


def publish_cached_output(relative_path: str, uri: str, label: str) -> bool:
    if not uri or not phase3_assets.cache_writes_enabled():
        return False
    return phase3_assets.publish_cached_asset(phase3_assets.aws_cli_path(), path_from_root(relative_path), uri, label)


def cached_outputs_usable(outputs: list[str], inputs: list[str], require_current: bool) -> bool:
    if require_current:
        return existing_output_current(outputs, inputs)
    return bool(outputs) and all(path_from_root(output).exists() for output in outputs)


def restore_cached_outputs(
    outputs: list[str], uri_by_output: dict[str, str], inputs: list[str], label: str, *, require_current: bool = True
) -> bool:
    if FORCE or not phase3_assets.cache_reads_enabled() or cached_outputs_usable(outputs, inputs, require_current):
        return not FORCE and cached_outputs_usable(outputs, inputs, require_current)
    aws = phase3_assets.aws_cli_path()
    if any(not uri_by_output.get(output) or phase3_assets.s3_object_size(aws, uri_by_output[output]) is None for output in outputs):
        print(f"[cache-miss] label={label} outputs={len(outputs)}", flush=True)
        return False
    for output in outputs:
        phase3_assets.restore_cached_asset(aws, uri_by_output[output], path_from_root(output), None, f"{label}.{Path(output).name}")
    if cached_outputs_usable(outputs, inputs, require_current):
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


def run_cached_command(command: str, output_path: str, inputs: list[str], uri: str, label: str, *, require_current: bool = True) -> str:
    if restore_cached_output(output_path, uri, inputs, label, require_current=require_current):
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


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_satisfies_public_manifest(path: Path, expected_bytes: str, expected_md5: str) -> bool:
    if not path.exists():
        return False
    if expected_bytes and path.stat().st_size != int(expected_bytes):
        return False
    if not expected_md5:
        return True
    marker = path.with_name(f"{path.name}.{expected_md5}.md5ok")
    if marker.exists() and marker.stat().st_mtime >= path.stat().st_mtime:
        return True
    if md5_file(path).lower() != expected_md5.lower():
        return False
    write_text(marker, expected_md5)
    return True


def public_bam_aria2_path() -> str:
    candidates = [
        os.environ.get("PHASE3_WGS_ARIA2C", ""),
        phase3_assets.command_path("aria2c"),
        "/usr/bin/aria2c",
        "/usr/local/bin/aria2c",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def download_public_alignment_file(row: dict[str, str], kind: str, url_key: str, output_key: str, md5_key: str, bytes_key: str) -> None:
    url = row.get(url_key, "")
    if not url:
        raise RuntimeError(f"Public alignment row for {row['role']} is missing {url_key}.")
    output_path = path_from_root(row[output_key])
    ensure_dir(output_path.parent)
    expected_md5 = row.get(md5_key, "")
    expected_bytes = row.get(bytes_key, "")
    if file_satisfies_public_manifest(output_path, expected_bytes, expected_md5):
        print(f"[public-bam-cache] label={row['role']}.{kind} path={row[output_key]}", flush=True)
        return
    output_path.unlink(missing_ok=True)
    aria2 = public_bam_aria2_path()
    if aria2:
        command = (
            f"{quote_shell_arg(aria2)} --continue=true "
            f"--max-connection-per-server={PUBLIC_BAM_ARIA2_SPLIT} "
            f"--split={PUBLIC_BAM_ARIA2_SPLIT} "
            "--min-split-size=64M --file-allocation=none "
            "--auto-file-renaming=false --allow-overwrite=true "
            "--retry-wait=20 --max-tries=20 --summary-interval=0 "
            "--console-log-level=error --show-console-readout=false "
            f"--dir={quote_shell_arg(str(output_path.parent))} "
            f"--out={quote_shell_arg(output_path.name)} "
            f"{quote_shell_arg(url)}"
        )
    elif PUBLIC_BAM_ARIA2_SPLIT > 1:
        raise RuntimeError(
            "Split public-BAM restore requested but aria2c is unavailable; "
            "install aria2 or set PHASE3_WGS_PUBLIC_BAM_ARIA2_SPLIT=1 for curl fallback."
        )
    else:
        command = f"curl -L --fail --retry 5 --retry-delay 20 --continue-at - --output {quote_shell_arg(row[output_key])} {quote_shell_arg(url)}"
    run_command(command, f"{RESULTS_DIR}/logs/{row['reference_id']}.{row['run_accession']}.public_{kind}.download.log")
    if not file_satisfies_public_manifest(output_path, expected_bytes, expected_md5):
        raise RuntimeError(f"Downloaded public {kind} for {row['role']} failed size/MD5 validation: {row[output_key]}")


def restore_public_alignment(row: dict[str, str]) -> bool:
    if not row.get("source_bam_url"):
        return False
    download_public_alignment_file(row, "bam", "source_bam_url", "output_bam", "source_bam_md5", "source_bam_bytes")
    download_public_alignment_file(row, "bai", "source_bai_url", "output_bai", "source_bai_md5", "source_bai_bytes")
    if not bam_satisfies_read_scope(row):
        raise RuntimeError(f"Public BAM for {row['role']} did not satisfy requested read scope: {row['output_bam']}")
    published = publish_cached_alignment(row)
    write_stage_marker(
        f"align_{row['role']}",
        {
            "status": "restored_public_bam",
            "role": row["role"],
            "runAccession": row["run_accession"],
            "bam": row["output_bam"],
            "bai": row["output_bai"],
            "sourceBamUrl": row.get("source_bam_url", ""),
            "sourceBaiUrl": row.get("source_bai_url", ""),
            "cachePublished": published,
        },
    )
    return True


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


def flagstat_log_has_counts(relative_path: str) -> bool:
    path = path_from_root(relative_path)
    if not path.exists():
        return False
    counts = parse_flagstat_counts(read_text(path))
    return {"total", "mapped", "properly_paired"} <= counts.keys()


def reusable_bam_validation_rows(rows: list[dict[str, str]], *, require_bams: bool = True) -> Optional[list[dict[str, Any]]]:
    if FORCE or not REUSE_BAM_VALIDATION:
        return None
    summary_path = path_from_root(bam_validation_summary_path())
    if not summary_path.exists():
        return None
    summary = read_json(summary_path)
    cached_rows = summary.get("rows", [])
    summary_mode = summary.get("bamValidationMode", summary.get("bam_validation_mode", "full"))
    if summary_mode != BAM_VALIDATION_MODE:
        return None
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
        if require_bams:
            bam_path = path_from_root(row["output_bam"])
            bai_path = path_from_root(row["output_bai"])
            if not bam_path.exists() or not bai_path.exists() or not quickcheck_bam(row["output_bam"]):
                return None
            cached_size = cached.get("bam_size_bytes")
            if cached_size not in ("", None) and int(cached_size) != bam_path.stat().st_size:
                return None
        reusable_rows.append({**cached, "validation_cache": "reused" if require_bams else "reused_no_bam_hydration"})
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
        require_current=False,
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
        "bam_validation_mode": BAM_VALIDATION_MODE,
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


def alignment_idxstats_path(row: dict[str, str]) -> str:
    run_accession = row.get("run_accession") or row.get("role") or Path(row["output_bam"]).stem
    return f"{RESULTS_DIR}/logs/{row.get('reference_id', 'unknown_reference')}.{run_accession}.idxstats.tsv"


def ensure_alignment_idxstats(row: dict[str, str]) -> str:
    idxstats_path = alignment_idxstats_path(row)
    return run_cached_command(
        f"samtools idxstats {quote_shell_arg(row['output_bam'])}",
        idxstats_path,
        [row["output_bam"], row["output_bai"]],
        sample_validation_cache_uri(row, idxstats_path),
        f"{row['role']}.idxstats",
    )


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


def fastq_cache_uris(row: dict[str, str]) -> tuple[str, str]:
    return (
        phase3_assets.cache_uri("fastq", Path(row["fastq_1"]).name),
        phase3_assets.cache_uri("fastq", Path(row["fastq_2"]).name),
    )


def require_streamable_fastq_cache(row: dict[str, str]) -> tuple[str, str]:
    if not phase3_assets.cache_reads_enabled():
        raise RuntimeError("PHASE3_WGS_ALIGN_INPUT_MODE=cache_stream requires a readable PHASE3_WGS_ASSET_CACHE_URI.")
    aws = phase3_assets.aws_cli_path()
    r1_uri, r2_uri = fastq_cache_uris(row)
    if not r1_uri or not r2_uri:
        raise RuntimeError("PHASE3_WGS_ALIGN_INPUT_MODE=cache_stream requires cached FASTQ URIs.")
    missing = [uri for uri in (r1_uri, r2_uri) if phase3_assets.s3_object_size(aws, uri) is None]
    if missing:
        raise RuntimeError(f"PHASE3_WGS_ALIGN_INPUT_MODE=cache_stream missing cached FASTQ object(s): {', '.join(missing)}")
    return r1_uri, r2_uri


def require_shard_count() -> int:
    if SHARD_COUNT < 1:
        raise RuntimeError("PHASE3_WGS_SHARD_COUNT must be a positive integer.")
    return SHARD_COUNT


def require_shard_index(shard_count: int) -> int:
    if SHARD_INDEX < 0 or SHARD_INDEX >= shard_count:
        raise RuntimeError(f"PHASE3_WGS_SHARD_INDEX must be between 0 and {shard_count - 1}, got {SHARD_INDEX}.")
    return SHARD_INDEX


def shard_label(shard_index: int, shard_count: int) -> str:
    return f"shard{shard_index:02d}of{shard_count:02d}"


def shard_read_count(total_records: int, shard_index: int, shard_count: int) -> int:
    base = total_records // shard_count
    return base + (1 if shard_index < total_records % shard_count else 0)


def shard_spot_range(total_records: int, shard_index: int, shard_count: int) -> tuple[int, int]:
    start = 1 + sum(shard_read_count(total_records, index, shard_count) for index in range(shard_index))
    return start, start + shard_read_count(total_records, shard_index, shard_count) - 1


def fastq_shard_manifest_path(row: dict[str, str], shard_count: int) -> str:
    return f"{RESULTS_DIR}/shards/{row['role']}.{row['run_accession']}.{shard_count}way.fastq_shards.csv"


def fastq_shard_dir(row: dict[str, str], shard_count: int) -> str:
    fastq_root = "/".join(row["fastq_1"].split("/")[:-1])
    return f"{fastq_root}/shards/{row['run_accession']}.{row['role']}.{shard_count}way"


def fastq_shard_rows(row: dict[str, str], shard_count: int) -> list[dict[str, Any]]:
    total_records = int(row["read_pairs_per_end"])
    shard_dir = fastq_shard_dir(row, shard_count)
    read_label = read_label_from_fastq(row)
    rows: list[dict[str, Any]] = []
    for index in range(shard_count):
        label = shard_label(index, shard_count)
        spot_start, spot_end = shard_spot_range(total_records, index, shard_count)
        r1_name = f"{row['run_accession']}.{label}_R1.fastq.gz"
        r2_name = f"{row['run_accession']}.{label}_R2.fastq.gz"
        rows.append(
            {
                "role": row["role"],
                "run_accession": row["run_accession"],
                "sample": row["sample"],
                "shard_index": index,
                "shard_count": shard_count,
                "shard_label": label,
                "expected_read_pairs": shard_read_count(total_records, index, shard_count),
                "spot_start": spot_start,
                "spot_end": spot_end,
                "fastq_1": f"{shard_dir}/{r1_name}",
                "fastq_2": f"{shard_dir}/{r2_name}",
                "fastq_1_uri": phase3_assets.cache_uri("fastq_shards", read_label, row["run_accession"], f"{shard_count}way", r1_name),
                "fastq_2_uri": phase3_assets.cache_uri("fastq_shards", read_label, row["run_accession"], f"{shard_count}way", r2_name),
            }
        )
    return rows


def write_fastq_shard_manifest(row: dict[str, str], shard_rows: list[dict[str, Any]]) -> None:
    write_csv(path_from_root(fastq_shard_manifest_path(row, int(shard_rows[0]["shard_count"]))), shard_rows)


def load_fastq_shard_manifest(row: dict[str, str], shard_count: int) -> list[dict[str, Any]]:
    manifest_path = path_from_root(fastq_shard_manifest_path(row, shard_count))
    if not manifest_path.exists():
        shard_rows = fastq_shard_rows(row, shard_count)
        write_fastq_shard_manifest(row, shard_rows)
        return shard_rows
    return parse_csv(read_text(manifest_path))


def shard_bam_path(row: dict[str, str], shard_index: int, shard_count: int) -> str:
    bam_dir = "/".join(row["output_bam"].split("/")[:-1])
    sample_stem = Path(row["output_bam"]).stem
    return f"{bam_dir}/shards/{sample_stem}.{shard_label(shard_index, shard_count)}.coord.bam"


def shard_bam_cache_uri(row: dict[str, str], shard_index: int, shard_count: int) -> str:
    read_label = read_label_from_fastq(row)
    return phase3_assets.cache_uri(
        "bam_shards",
        row["reference_id"],
        read_label,
        row["role"],
        f"{shard_count}way",
        Path(shard_bam_path(row, shard_index, shard_count)).name,
    )


def shard_bam_cache_uris(row: dict[str, str], shard_count: int) -> list[str]:
    return [shard_bam_cache_uri(row, index, shard_count) for index in range(shard_count)]


def shard_bam_manifest_path(row: dict[str, str], shard_count: int) -> str:
    return f"{RESULTS_DIR}/shards/{row['role']}.{row['run_accession']}.{shard_count}way.bam_shards.csv"


def require_cache_for_shards() -> str:
    if not phase3_assets.cache_reads_enabled() or not phase3_assets.cache_writes_enabled():
        raise RuntimeError("Phase 3 shard experiments require PHASE3_WGS_ASSET_CACHE_URI with readwrite cache mode.")
    return phase3_assets.aws_cli_path()


def cached_uris_ready(aws: str, uris: list[str]) -> bool:
    return bool(uris) and all(uri and phase3_assets.s3_object_size(aws, uri) is not None for uri in uris)


def open_s3_gzip_text(aws: str, uri: str) -> tuple[subprocess.Popen[bytes], io.TextIOWrapper]:
    process = subprocess.Popen([aws, "s3", "cp", "--only-show-errors", uri, "-"], stdout=subprocess.PIPE)
    if process.stdout is None:
        raise RuntimeError(f"Could not open S3 stream for {uri}.")
    gzip_handle = gzip.GzipFile(fileobj=process.stdout, mode="rb")
    return process, io.TextIOWrapper(gzip_handle, encoding="utf-8")


def read_fastq_record(handle: io.TextIOBase, label: str, record_number: int) -> list[str] | None:
    lines = [handle.readline() for _ in range(4)]
    if not lines[0]:
        if any(lines[1:]):
            raise RuntimeError(f"{label} ended mid-record at {record_number}.")
        return None
    if any(not line for line in lines):
        raise RuntimeError(f"{label} ended mid-record at {record_number}.")
    return [line.rstrip("\n") for line in lines]


def seqkit_split_shards_command(
    r1_path: Path,
    r2_path: Path,
    output_dir: Path,
    run_accession: str,
    shard_count: int,
    threads: int,
) -> str:
    return (
        f"seqkit split2 -j {threads} -p {shard_count} "
        f"-1 {quote_shell_arg(str(r1_path))} -2 {quote_shell_arg(str(r2_path))} "
        f"-O {quote_shell_arg(str(output_dir))} -e .gz -f"
    )


def seqkit_split_output_path(output_dir: Path, run_accession: str, read_number: int, shard_index: int) -> Path:
    return output_dir / f"{run_accession}_R{read_number}.full.part_{shard_index + 1:03d}.fastq.gz"


def prepare_fastq_shards(row: dict[str, str], shard_count: int) -> None:
    if ALIGN_INPUT_MODE != "cache_stream":
        raise RuntimeError("Phase 3 fastq sharding currently requires PHASE3_WGS_ALIGN_INPUT_MODE=cache_stream.")
    aws = require_cache_for_shards()
    shard_rows = fastq_shard_rows(row, shard_count)
    if SHARD_INPUT_MODE == "sra_spot_range":
        write_fastq_shard_manifest(row, shard_rows)
        write_stage_marker(
            f"shard_fastq_{row['role']}",
            {
                "status": "spot_range_manifest",
                "role": row["role"],
                "runAccession": row["run_accession"],
                "shards": shard_count,
                "manifest": fastq_shard_manifest_path(row, shard_count),
                "shardInputMode": SHARD_INPUT_MODE,
            },
        )
        return
    require_streamable_fastq_cache(row)
    shard_uris = [str(shard["fastq_1_uri"]) for shard in shard_rows] + [str(shard["fastq_2_uri"]) for shard in shard_rows]
    if not FORCE and cached_uris_ready(aws, shard_uris):
        write_fastq_shard_manifest(row, shard_rows)
        write_stage_marker(
            f"shard_fastq_{row['role']}",
            {
                "status": "skipped_existing_cache",
                "role": row["role"],
                "runAccession": row["run_accession"],
                "shards": shard_count,
                "manifest": fastq_shard_manifest_path(row, shard_count),
            },
        )
        return

    r1_uri, r2_uri = require_streamable_fastq_cache(row)
    ensure_dir(path_from_root(fastq_shard_dir(row, shard_count)))
    shard_dir = path_from_root(fastq_shard_dir(row, shard_count))
    tmp_dir = shard_dir / ".seqkit_split"
    split_dir = tmp_dir / "parts"
    r1_local = tmp_dir / f"{row['run_accession']}_R1.full.fastq.gz"
    r2_local = tmp_dir / f"{row['run_accession']}_R2.full.fastq.gz"
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        ensure_dir(split_dir)
        log_prefix = f"{RESULTS_DIR}/logs/{row['run_accession']}.{shard_count}way.seqkit_shards"
        run_command(
            f"{quote_shell_arg(aws)} s3 cp --only-show-errors {quote_shell_arg(r1_uri)} {quote_shell_arg(str(r1_local))} "
            f"&& {quote_shell_arg(aws)} s3 cp --only-show-errors {quote_shell_arg(r2_uri)} {quote_shell_arg(str(r2_local))}",
            f"{log_prefix}.download.log",
        )
        run_command(
            seqkit_split_shards_command(r1_local, r2_local, split_dir, row["run_accession"], shard_count, TOTAL_THREADS),
            f"{log_prefix}.split.log",
        )
        for shard in shard_rows:
            shard_index = int(shard["shard_index"])
            r1_output = seqkit_split_output_path(split_dir, row["run_accession"], 1, shard_index)
            r2_output = seqkit_split_output_path(split_dir, row["run_accession"], 2, shard_index)
            if not r1_output.exists() or not r2_output.exists():
                raise RuntimeError(
                    f"seqkit split2 did not produce expected shard files for {shard['shard_label']}: "
                    f"{r1_output}, {r2_output}"
                )
            ensure_dir(path_from_root(str(shard["fastq_1"])).parent)
            r1_output.replace(path_from_root(str(shard["fastq_1"])))
            r2_output.replace(path_from_root(str(shard["fastq_2"])))
            phase3_assets.publish_cached_asset(
                aws,
                path_from_root(str(shard["fastq_1"])),
                str(shard["fastq_1_uri"]),
                f"{row['role']}.{shard['shard_label']}.R1.fastq.gz",
            )
            phase3_assets.publish_cached_asset(
                aws,
                path_from_root(str(shard["fastq_2"])),
                str(shard["fastq_2_uri"]),
                f"{row['role']}.{shard['shard_label']}.R2.fastq.gz",
            )
            path_from_root(str(shard["fastq_1"])).unlink(missing_ok=True)
            path_from_root(str(shard["fastq_2"])).unlink(missing_ok=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    if not cached_uris_ready(aws, shard_uris):
        raise RuntimeError("One or more FASTQ shard cache objects are missing after publish.")
    write_fastq_shard_manifest(row, shard_rows)
    write_stage_marker(
        f"shard_fastq_{row['role']}",
        {
            "status": "passed",
            "role": row["role"],
            "runAccession": row["run_accession"],
            "shards": shard_count,
            "readPairs": int(row["read_pairs_per_end"]),
            "manifest": fastq_shard_manifest_path(row, shard_count),
        },
    )


def profiled_unsorted_bam_path(row: dict[str, str]) -> str:
    output_bam = row["output_bam"]
    if output_bam.endswith(".bam"):
        return output_bam[:-4] + ".unsorted.bam"
    return output_bam + ".unsorted.bam"


def alignment_reference_path(row: dict[str, str]) -> str:
    reference_path = row["reference_path"]
    if ALIGNER == "minimap2":
        mmi_path = f"{reference_path}.mmi"
        if path_from_root(mmi_path).exists():
            return mmi_path
    return reference_path


def align_command(row: dict[str, str], bwa_threads: int, sort_threads: int) -> str:
    aligner_command_by_name = {
        "bwa": "bwa mem",
        "bwa-mem2": "bwa-mem2 mem",
        "minimap2": "minimap2 -ax sr",
    }
    if ALIGNER not in aligner_command_by_name:
        raise RuntimeError(f"Unsupported PHASE3_WGS_ALIGNER={ALIGNER!r}.")
    if ALIGN_INPUT_MODE == "local_fastq":
        r1_input = quote_shell_arg(row["fastq_1"])
        r2_input = quote_shell_arg(row["fastq_2"])
        setup = "set -o pipefail; "
    elif ALIGN_INPUT_MODE == "cache_stream":
        aws = quote_shell_arg(phase3_assets.aws_cli_path())
        r1_uri, r2_uri = require_streamable_fastq_cache(row)
        setup = (
            "set -o pipefail; "
            "tmpdir=$(mktemp -d); "
            "trap 'rm -rf \"$tmpdir\"' EXIT; "
            "r1=\"$tmpdir/R1.fastq.gz\"; "
            "r2=\"$tmpdir/R2.fastq.gz\"; "
            "mkfifo \"$r1\" \"$r2\"; "
            f"{aws} s3 cp --only-show-errors {quote_shell_arg(r1_uri)} \"$r1\" & "
            "r1_pid=$!; "
            f"{aws} s3 cp --only-show-errors {quote_shell_arg(r2_uri)} \"$r2\" & "
            "r2_pid=$!; "
            "set +e; "
        )
        r1_input = '"$r1"'
        r2_input = '"$r2"'
    else:
        raise RuntimeError(f"Unsupported PHASE3_WGS_ALIGN_INPUT_MODE={ALIGN_INPUT_MODE!r}.")
    align = (
        f"{aligner_command_by_name[ALIGNER]} -t {bwa_threads} -R {quote_shell_arg(read_group(row))} "
        f"{quote_shell_arg(alignment_reference_path(row))} {r1_input} {r2_input}"
    )
    if ALIGN_PROFILE_MODE == "pipe":
        pipeline = f"{align} | samtools sort -@ {sort_threads} -o {quote_shell_arg(row['output_bam'])} -"
    elif ALIGN_PROFILE_MODE == "mem_only":
        pipeline = f"{align} > /dev/null"
    elif ALIGN_PROFILE_MODE == "unsorted_bam":
        pipeline = f"{align} | samtools view -@ {sort_threads} -b -o {quote_shell_arg(profiled_unsorted_bam_path(row))} -"
    else:
        raise RuntimeError(f"Unsupported PHASE3_WGS_ALIGN_PROFILE_MODE={ALIGN_PROFILE_MODE!r}.")
    command = setup + pipeline
    if ALIGN_INPUT_MODE == "cache_stream":
        command += (
            "; align_status=$?; "
            "wait \"$r1_pid\"; r1_status=$?; "
            "wait \"$r2_pid\"; r2_status=$?; "
            "set -e; "
            "if [ \"$align_status\" -ne 0 ] || [ \"$r1_status\" -ne 0 ] || [ \"$r2_status\" -ne 0 ]; then "
            "echo \"cache_stream alignment failed: align=$align_status r1=$r1_status r2=$r2_status\" >&2; "
            "exit 1; "
            "fi"
        )
    return command


def aligner_command_prefix() -> str:
    aligner_command_by_name = {
        "bwa": "bwa mem",
        "bwa-mem2": "bwa-mem2 mem",
        "minimap2": "minimap2 -ax sr",
    }
    if ALIGNER not in aligner_command_by_name:
        raise RuntimeError(f"Unsupported PHASE3_WGS_ALIGNER={ALIGNER!r}.")
    return aligner_command_by_name[ALIGNER]


def align_shard_command(row: dict[str, str], shard: dict[str, Any], bwa_threads: int, sort_threads: int) -> str:
    if ALIGN_INPUT_MODE != "cache_stream":
        raise RuntimeError("Phase 3 shard alignment currently requires PHASE3_WGS_ALIGN_INPUT_MODE=cache_stream.")
    aws = quote_shell_arg(require_cache_for_shards())
    shard_index = int(shard["shard_index"])
    shard_count = int(shard["shard_count"])
    bam_path = shard_bam_path(row, shard_index, shard_count)
    ensure_dir(path_from_root(bam_path).parent)
    if SHARD_INPUT_MODE == "fastq_cache":
        setup = (
            "set -o pipefail; "
            "tmpdir=$(mktemp -d); "
            "trap 'rm -rf \"$tmpdir\"' EXIT; "
            "r1=\"$tmpdir/R1.fastq.gz\"; "
            "r2=\"$tmpdir/R2.fastq.gz\"; "
            "mkfifo \"$r1\" \"$r2\"; "
            f"{aws} s3 cp --only-show-errors {quote_shell_arg(str(shard['fastq_1_uri']))} \"$r1\" & "
            "r1_pid=$!; "
            f"{aws} s3 cp --only-show-errors {quote_shell_arg(str(shard['fastq_2_uri']))} \"$r2\" & "
            "r2_pid=$!; "
            "set +e; "
        )
        r1_input = '"$r1"'
        r2_input = '"$r2"'
    elif SHARD_INPUT_MODE == "sra_spot_range":
        run, _r1_path, _r2_path, sra_path, _tmp_dir = phase3_assets.aws_sra_run_paths(row)
        fastq_dump = phase3_assets.command_path("fastq-dump")
        if not fastq_dump:
            raise RuntimeError("PHASE3_WGS_SHARD_INPUT_MODE=sra_spot_range requires fastq-dump from sra-tools.")
        setup = (
            "set -o pipefail; "
            "tmpdir=$(mktemp -d); "
            "trap 'rm -rf \"$tmpdir\"' EXIT; "
            "fqdir=\"$tmpdir/fastq\"; "
            "mkdir -p \"$fqdir\"; "
            f"{quote_shell_arg(fastq_dump)} --split-files --skip-technical "
            f"-N {int(shard['spot_start'])} -X {int(shard['spot_end'])} "
            f"-O \"$fqdir\" {quote_shell_arg(str(path_from_root(str(sra_path))))}; "
            f"r1=\"$fqdir/{run}_1.fastq\"; "
            f"r2=\"$fqdir/{run}_2.fastq\"; "
            "if [ ! -s \"$r1\" ] || [ ! -s \"$r2\" ]; then "
            "echo \"spot-range fastq-dump did not produce paired FASTQs\" >&2; exit 1; "
            "fi; "
            "set +e; "
        )
        r1_input = '"$r1"'
        r2_input = '"$r2"'
    else:
        raise RuntimeError("PHASE3_WGS_SHARD_INPUT_MODE must be fastq_cache or sra_spot_range.")
    align = (
        f"{aligner_command_prefix()} -t {bwa_threads} -R {quote_shell_arg(read_group(row))} "
        f"{quote_shell_arg(alignment_reference_path(row))} {r1_input} {r2_input}"
    )
    pipeline = (
        f"{align} | samtools sort -@ {sort_threads} -m {quote_shell_arg(SORT_MEMORY)} "
        f"-o {quote_shell_arg(bam_path)} -"
    )
    command = setup + pipeline + "; align_status=$?; "
    if SHARD_INPUT_MODE == "fastq_cache":
        command += (
            "wait \"$r1_pid\"; r1_status=$?; "
            "wait \"$r2_pid\"; r2_status=$?; "
            "set -e; "
            "if [ \"$align_status\" -ne 0 ] || [ \"$r1_status\" -ne 0 ] || [ \"$r2_status\" -ne 0 ]; then "
            "echo \"cache_stream shard alignment failed: align=$align_status r1=$r1_status r2=$r2_status\" >&2; "
            "exit 1; "
            "fi"
        )
    else:
        command += (
            "set -e; "
            "if [ \"$align_status\" -ne 0 ]; then "
            "echo \"spot-range shard alignment failed: align=$align_status\" >&2; "
            "exit 1; "
            "fi"
        )
    return command


def ensure_sra_for_spot_range(row: dict[str, str]) -> None:
    aws = require_cache_for_shards()
    run, _r1_path, _r2_path, sra_path, _tmp_dir = phase3_assets.aws_sra_run_paths(row)
    target = path_from_root(str(sra_path))
    if target.exists() and target.stat().st_size > 0:
        return
    ensure_dir(target.parent)
    cache_uri = phase3_assets.cache_uri("sra", f"{run}.sra")
    if cache_uri and phase3_assets.s3_object_size(aws, cache_uri) is not None:
        phase3_assets.restore_cached_asset(aws, cache_uri, target, None, f"{run}.sra")
        return
    run_command(
        f"{quote_shell_arg(aws)} s3 cp --no-sign-request --only-show-errors "
        f"{quote_shell_arg(phase3_assets.sra_aws_uri(run))} {quote_shell_arg(str(target))}",
        f"{RESULTS_DIR}/logs/{run}.sra_spot_range_restore.log",
    )


def align_and_publish_shard(reference_id: str, row: dict[str, str], shard_index: int, shard_count: int) -> None:
    aws = require_cache_for_shards()
    shard_rows = load_fastq_shard_manifest(row, shard_count)
    shard = next((item for item in shard_rows if int(item["shard_index"]) == shard_index), None)
    if shard is None:
        raise RuntimeError(f"FASTQ shard manifest does not contain shard {shard_index}/{shard_count} for {row['role']}.")
    shard_uri = shard_bam_cache_uri(row, shard_index, shard_count)
    if not FORCE and not FORCE_SHARD_ALIGNMENT and shard_uri and phase3_assets.s3_object_size(aws, shard_uri) is not None:
        write_stage_marker(
            f"align_{row['role']}_{shard_label(shard_index, shard_count)}",
            {
                "status": "skipped_existing_cache",
                "role": row["role"],
                "runAccession": row["run_accession"],
                "shardIndex": shard_index,
                "shardCount": shard_count,
                "cacheUri": shard_uri,
            },
        )
        return
    if SHARD_INPUT_MODE == "sra_spot_range":
        ensure_sra_for_spot_range(row)
    ensure_bwa_index(reference_id, row["reference_path"])
    bam_path = shard_bam_path(row, shard_index, shard_count)
    path_from_root(bam_path).unlink(missing_ok=True)
    command = align_shard_command(row, shard, ALIGN_BWA_THREADS, ALIGN_SORT_THREADS)
    run_command(command, f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.{shard_label(shard_index, shard_count)}.align.log")
    if not quickcheck_bam(bam_path):
        raise RuntimeError(f"Shard BAM quickcheck failed for {bam_path}")
    source_path = path_from_root(bam_path)
    published = phase3_assets.publish_cached_asset(
        aws,
        source_path,
        shard_uri,
        f"{row['role']}.{shard_label(shard_index, shard_count)}.bam",
        source_path.stat().st_size,
    )
    marker = {
        "status": "passed",
        "role": row["role"],
        "runAccession": row["run_accession"],
        "shardIndex": shard_index,
        "shardCount": shard_count,
        "expectedReadPairs": int(shard["expected_read_pairs"]),
        "threads": TOTAL_THREADS,
        "bwaThreads": ALIGN_BWA_THREADS,
        "sortThreads": ALIGN_SORT_THREADS,
        "sortMemory": SORT_MEMORY,
        "shardInputMode": SHARD_INPUT_MODE,
        "forceShardAlignment": FORCE_SHARD_ALIGNMENT,
        "spotStart": int(shard["spot_start"]) if shard.get("spot_start") else "",
        "spotEnd": int(shard["spot_end"]) if shard.get("spot_end") else "",
        "bam": bam_path,
        "bamBytes": source_path.stat().st_size,
        "cacheUri": shard_uri,
        "cachePublished": published,
    }
    source_path.unlink(missing_ok=True)
    write_stage_marker(f"align_{row['role']}_{shard_label(shard_index, shard_count)}", marker)


def restore_cached_shard_bams(row: dict[str, str], shard_count: int) -> list[str]:
    aws = require_cache_for_shards()
    def restore_one(index: int) -> str:
        bam_path = shard_bam_path(row, index, shard_count)
        uri = shard_bam_cache_uri(row, index, shard_count)
        if not uri:
            raise RuntimeError(f"Missing shard BAM cache URI for {row['role']} {shard_label(index, shard_count)}.")
        phase3_assets.restore_cached_asset(aws, uri, path_from_root(bam_path), None, f"{row['role']}.{shard_label(index, shard_count)}.bam")
        if not quickcheck_bam(bam_path):
            raise RuntimeError(f"Restored shard BAM quickcheck failed for {bam_path}")
        return bam_path

    workers = min(ALIGNMENT_CACHE_WORKERS, shard_count)
    if workers <= 1:
        return [restore_one(index) for index in range(shard_count)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(restore_one, range(shard_count)))


def write_shard_bam_manifest(row: dict[str, str], shard_count: int) -> list[dict[str, Any]]:
    aws = require_cache_for_shards()
    fastq_shards = load_fastq_shard_manifest(row, shard_count)
    rows: list[dict[str, Any]] = []
    for index in range(shard_count):
        shard = next((item for item in fastq_shards if int(item["shard_index"]) == index), None)
        uri = shard_bam_cache_uri(row, index, shard_count)
        size = phase3_assets.s3_object_size(aws, uri)
        if size is None:
            raise RuntimeError(f"Missing shard BAM cache object for {row['role']} {shard_label(index, shard_count)}: {uri}")
        rows.append(
            {
                "role": row["role"],
                "run_accession": row["run_accession"],
                "sample": row["sample"],
                "shard_index": index,
                "shard_count": shard_count,
                "shard_label": shard_label(index, shard_count),
                "expected_read_pairs": int(shard["expected_read_pairs"]) if shard else "",
                "bam_uri": uri,
                "bam_bytes": size,
            }
        )
    write_csv(path_from_root(shard_bam_manifest_path(row, shard_count)), rows)
    return rows


def gather_shards(reference_id: str, row: dict[str, str], shard_count: int) -> None:
    if not cached_uris_ready(require_cache_for_shards(), shard_bam_cache_uris(row, shard_count)):
        missing = [
            uri
            for uri in shard_bam_cache_uris(row, shard_count)
            if not uri or phase3_assets.s3_object_size(phase3_assets.aws_cli_path(), uri) is None
        ]
        raise RuntimeError(f"Cannot gather {row['role']} shards; missing shard BAM cache object(s): {', '.join(missing)}")
    if SCATTER_OUTPUT_MODE == "shard_manifest":
        manifest_rows = write_shard_bam_manifest(row, shard_count)
        write_stage_marker(
            f"gather_{row['role']}_{shard_count}way",
            {
                "status": "passed",
                "role": row["role"],
                "runAccession": row["run_accession"],
                "shardCount": shard_count,
                "scatterOutputMode": SCATTER_OUTPUT_MODE,
                "manifest": shard_bam_manifest_path(row, shard_count),
                "shards": manifest_rows,
            },
        )
        return
    if not FORCE and bam_satisfies_read_scope(row):
        ensure_alignment_idxstats(row)
        return
    remove_stale_alignment(row)
    shard_bams = restore_cached_shard_bams(row, shard_count)
    ensure_dir(path_from_root("/".join(row["output_bam"].split("/")[:-1])))
    merge_inputs = " ".join(quote_shell_arg(path) for path in shard_bams)
    run_command(
        f"samtools merge -@ {TOTAL_THREADS} -f -o {quote_shell_arg(row['output_bam'])} {merge_inputs}",
        f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.{shard_count}way.merge.log",
    )
    run_command(
        f"samtools index -@ {TOTAL_THREADS} -o {quote_shell_arg(row['output_bai'])} {quote_shell_arg(row['output_bam'])}",
        f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.{shard_count}way.index.log",
    )
    flagstat_log = f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.{shard_count}way.flagstat.txt"
    run_cached_command(
        f"samtools flagstat -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
        flagstat_log,
        [row["output_bam"], row["output_bai"]],
        sample_validation_cache_uri(row, flagstat_log),
        f"{row['role']}.{shard_count}way.flagstat",
        require_current=False,
    )
    ensure_alignment_idxstats(row)
    if not bam_satisfies_read_scope(row):
        raise RuntimeError(f"Gathered BAM for {row['role']} did not satisfy requested read scope: {row['output_bam']}")
    published = publish_cached_alignment(row)
    for shard_bam in shard_bams:
        path_from_root(shard_bam).unlink(missing_ok=True)
    write_stage_marker(
        f"gather_{row['role']}_{shard_count}way",
        {
            "status": "passed",
            "role": row["role"],
            "runAccession": row["run_accession"],
            "shardCount": shard_count,
            "threads": TOTAL_THREADS,
            "bam": row["output_bam"],
            "bai": row["output_bai"],
            "cachePublished": published,
        },
    )


def ensure_bwa_index(reference_id: str, reference_path: str) -> None:
    if ALIGNER == "bwa":
        if FORCE or not path_from_root(f"{reference_path}.bwt").exists():
            run_command(f"bwa index {quote_shell_arg(reference_path)}", f"{RESULTS_DIR}/logs/{reference_id}.bwa_index.log")
        return
    if ALIGNER == "bwa-mem2":
        if FORCE or not path_from_root(f"{reference_path}.bwt.2bit.64").exists():
            run_command(f"bwa-mem2 index {quote_shell_arg(reference_path)}", f"{RESULTS_DIR}/logs/{reference_id}.bwa_mem2_index.log")
        return
    if ALIGNER == "minimap2":
        index_path = f"{reference_path}.mmi"
        if FORCE or not path_from_root(index_path).exists():
            run_command(
                f"minimap2 -d {quote_shell_arg(index_path)} {quote_shell_arg(reference_path)}",
                f"{RESULTS_DIR}/logs/{reference_id}.minimap2_index.log",
            )
        return
    raise RuntimeError(f"Unsupported PHASE3_WGS_ALIGNER={ALIGNER!r}.")


def align_and_index_sample(reference_id: str, row: dict[str, str]) -> None:
    ensure_dir(path_from_root("/".join(row["output_bam"].split("/")[:-1])))
    if not FORCE and bam_satisfies_read_scope(row):
        ensure_alignment_idxstats(row)
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
        ensure_alignment_idxstats(row)
        return
    if restore_public_alignment(row):
        ensure_alignment_idxstats(row)
        return
    remove_stale_alignment(row)
    command = align_command(row, ALIGN_BWA_THREADS, ALIGN_SORT_THREADS)
    run_command(command, f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.align.log")
    if ALIGN_PROFILE_MODE != "pipe":
        write_stage_marker(
            f"align_{row['role']}",
            {
                "status": "profiled",
                "profileMode": ALIGN_PROFILE_MODE,
                "role": row["role"],
                "runAccession": row["run_accession"],
                "threads": TOTAL_THREADS,
                "bwaThreads": ALIGN_BWA_THREADS,
                "sortThreads": ALIGN_SORT_THREADS,
                "profiledUnsortedBam": profiled_unsorted_bam_path(row) if ALIGN_PROFILE_MODE == "unsorted_bam" else "",
            },
        )
        return
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
    if bam_stats_enabled():
        run_cached_command(
            f"samtools stats -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
            stats_log,
            [row["output_bam"], row["output_bai"]],
            sample_validation_cache_uri(row, stats_log),
            f"{row['role']}.stats",
        )
    ensure_alignment_idxstats(row)
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


def read_alignment_idxstats(row: dict[str, str]) -> list[dict[str, int | str]]:
    idxstats_path = alignment_idxstats_path(row)
    if not path_from_root(idxstats_path).exists() and path_from_root(row["output_bam"]).exists():
        ensure_alignment_idxstats(row)
    if not path_from_root(idxstats_path).exists():
        raise RuntimeError(f"Missing alignment idxstats for {row['role']}: {idxstats_path}")
    rows: list[dict[str, int | str]] = []
    for line in read_text(path_from_root(idxstats_path)).splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        contig, length_text, mapped_text, unmapped_text, *_rest = parts
        if not standard_contig(contig):
            continue
        rows.append(
            {
                "contig": contig,
                "length": int(length_text or "0"),
                "mapped": int(mapped_text or "0"),
                "unmapped": int(unmapped_text or "0"),
            }
        )
    return rows


def build_idxstats_coverage_cnv_rows(tumor: dict[str, str], normal: dict[str, str]) -> list[dict[str, Any]]:
    tumor_by_contig = {str(row["contig"]): row for row in read_alignment_idxstats(tumor)}
    normal_by_contig = {str(row["contig"]): row for row in read_alignment_idxstats(normal)}
    tumor_total = max(1, sum(int(row["mapped"]) for row in tumor_by_contig.values()))
    normal_total = max(1, sum(int(row["mapped"]) for row in normal_by_contig.values()))
    rows: list[dict[str, Any]] = []
    for contig in sorted(set(tumor_by_contig) & set(normal_by_contig), key=lambda name: (len(name), name)):
        tumor_row = tumor_by_contig[contig]
        normal_row = normal_by_contig[contig]
        length = max(1, int(tumor_row["length"]) or int(normal_row["length"]))
        tumor_mapped = int(tumor_row["mapped"])
        normal_mapped = int(normal_row["mapped"])
        tumor_fraction = tumor_mapped / tumor_total
        normal_fraction = normal_mapped / normal_total
        log2_ratio = math.log2((tumor_fraction + 1e-9) / (normal_fraction + 1e-9))
        rows.append(
            {
                "contig": contig,
                "start": 0,
                "end": length,
                "length": length,
                "tumor_depth_sum": tumor_mapped,
                "normal_depth_sum": normal_mapped,
                "tumor_mean_depth": round_value(tumor_mapped / length, 6),
                "normal_mean_depth": round_value(normal_mapped / length, 6),
                "log2_tumor_normal": round_value(log2_ratio, 4),
                "coverage_class": "relative_gain"
                if log2_ratio >= 0.5
                else "relative_loss"
                if log2_ratio <= -0.5
                else "neutral_or_low_signal",
            }
        )
    return rows


def bedcov_shard_name(contig: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", contig)


def write_bedcov_shards(bins_path: str) -> list[tuple[str, str, str, str]]:
    shard_dir = f"{RESULTS_DIR}/coverage_cnv_bedcov_shards"
    ensure_dir(path_from_root(shard_dir))
    grouped: dict[str, list[str]] = {}
    for line in read_text(path_from_root(bins_path)).splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        contig = line.split("\t", 1)[0]
        grouped.setdefault(contig, []).append(line)
    shards: list[tuple[str, str, str, str]] = []
    for contig, lines in grouped.items():
        shard = bedcov_shard_name(contig)
        bed_path = f"{shard_dir}/{shard}.bed"
        output_path = f"{shard_dir}/{shard}.bedcov.tsv"
        log_path = f"{RESULTS_DIR}/logs/{shard}.phase3_wgs.coverage_cnv_bedcov.log"
        write_text_if_changed(bed_path, "\n".join(lines))
        shards.append((contig, bed_path, output_path, log_path))
    if not shards:
        raise RuntimeError(f"No coverage CNV bins found in {bins_path}")
    return shards


def run_sharded_bedcov(tumor: dict[str, str], normal: dict[str, str], bins_path: str, bedcov_output: str) -> None:
    shards = write_bedcov_shards(bins_path)
    commands: list[tuple[str, str]] = []
    for _contig, bed_path, output_path, log_path in shards:
        commands.append(
            (
                f"samtools bedcov {quote_shell_arg(bed_path)} {quote_shell_arg(tumor['output_bam'])} "
                f"{quote_shell_arg(normal['output_bam'])} > {quote_shell_arg(output_path)}",
                log_path,
            )
        )
    run_commands_parallel(commands, min(CNV_BEDCOV_WORKERS, len(commands)))
    combined = []
    for _contig, _bed_path, output_path, _log_path in shards:
        text = read_text(path_from_root(output_path)).strip()
        if text:
            combined.append(text)
    write_text(path_from_root(bedcov_output), "\n".join(combined))


def build_coverage_cnv(tumor: dict[str, str], normal: dict[str, str], bins_path: str) -> dict[str, Any]:
    bedcov_output = f"{RESULTS_DIR}/coverage_cnv_bedcov.tsv"
    bins_output = f"{RESULTS_DIR}/coverage_cnv_bins.csv"
    summary_output = f"{RESULTS_DIR}/coverage_cnv_summary.csv"
    summary_json = f"{RESULTS_DIR}/coverage_cnv_summary.json"
    idxstats_inputs = [alignment_idxstats_path(tumor), alignment_idxstats_path(normal)]
    inputs = (
        idxstats_inputs
        if COVERAGE_CNV_MODE == "idxstats"
        else [bins_path, tumor["output_bam"], tumor["output_bai"], normal["output_bam"], normal["output_bai"]]
    )
    final_outputs = [bins_output, summary_output, summary_json]
    cache_group = coverage_cnv_cache_group()
    final_cache_uris = {output: pair_validation_cache_uri(tumor, normal, cache_group, output) for output in final_outputs}
    restore_requires_current = COVERAGE_CNV_MODE != "metadata"
    if not FORCE and (
        existing_output_current(final_outputs, inputs)
        or restore_cached_outputs(final_outputs, final_cache_uris, inputs, "pair.coverage_cnv", require_current=restore_requires_current)
    ):
        cached_summary = read_json(path_from_root(summary_json))
        cached_mode = cached_summary.get("coverageCnvMode", cached_summary.get("coverage_cnv_mode", "full"))
        cached_rows = cached_summary.get("rows", [])
        if cached_mode == COVERAGE_CNV_MODE and cached_rows:
            return {**cached_rows[0], "cnv_cache": "reused"}
    if COVERAGE_CNV_MODE == "metadata":
        write_csv(
            path_from_root(bins_output),
            [],
            columns=[
                "contig",
                "start",
                "end",
                "length",
                "tumor_depth_sum",
                "normal_depth_sum",
                "tumor_mean_depth",
                "normal_mean_depth",
                "log2_tumor_normal",
                "coverage_class",
            ],
        )
        summary = {
            "status": "passed",
            "tool": "metadata_only",
            "coverage_cnv_mode": COVERAGE_CNV_MODE,
            "bin_size": BIN_SIZE,
            "bin_count": 0,
            "median_log2_tumor_normal": "",
            "relative_gain_bins": 0,
            "relative_loss_bins": 0,
            "output_bins": "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
            "scarhrd_input_status": "not_assessable_metadata_only",
            "real_output_status": "metadata_only_cnv_placeholder",
            "caveat": "Metadata-only coverage/CNV mode skips full-BAM samtools bedcov for optimization timing runs.",
        }
        write_csv(path_from_root(summary_output), [summary])
        write_json(
            path_from_root(summary_json),
            {"generatedAt": iso_now(), "status": summary["status"], "coverageCnvMode": COVERAGE_CNV_MODE, "rows": [summary]},
        )
        publish_cached_outputs(final_outputs, final_cache_uris, "pair.coverage_cnv")
        return summary
    if COVERAGE_CNV_MODE == "idxstats":
        rows = build_idxstats_coverage_cnv_rows(tumor, normal)
        write_csv(path_from_root(bins_output), rows)
        log2_values = [float(row["log2_tumor_normal"]) for row in rows if row["log2_tumor_normal"] != ""]
        summary = {
            "status": "passed" if rows else "failed",
            "tool": "samtools idxstats",
            "coverage_cnv_mode": COVERAGE_CNV_MODE,
            "bin_size": "contig",
            "bin_count": len(rows),
            "median_log2_tumor_normal": round_value(median(log2_values), 4),
            "relative_gain_bins": sum(1 for row in rows if row["coverage_class"] == "relative_gain"),
            "relative_loss_bins": sum(1 for row in rows if row["coverage_class"] == "relative_loss"),
            "output_bins": "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
            "scarhrd_input_status": "not_assessable_without_allele_specific_segments",
            "real_output_status": "real_alignment_index_coverage_proxy",
            "caveat": "Alignment-index-derived tumor/normal CNV proxy from samtools idxstats. This avoids full-BAM bedcov scans for optimization runs and is not allele-specific segmentation or scarHRD.",
        }
        write_csv(path_from_root(summary_output), [summary])
        write_json(
            path_from_root(summary_json),
            {"generatedAt": iso_now(), "status": summary["status"], "coverageCnvMode": COVERAGE_CNV_MODE, "rows": [summary]},
        )
        publish_cached_outputs(final_outputs, final_cache_uris, "pair.coverage_cnv")
        return summary
    if FORCE or not existing_output_current([bedcov_output], inputs):
        if not restore_cached_output(
            bedcov_output,
            pair_validation_cache_uri(tumor, normal, cache_group, bedcov_output),
            inputs,
            "pair.coverage_cnv.bedcov",
        ):
            run_sharded_bedcov(tumor, normal, bins_path, bedcov_output)
            publish_cached_output(
                bedcov_output,
                pair_validation_cache_uri(tumor, normal, cache_group, bedcov_output),
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
        "coverage_cnv_mode": COVERAGE_CNV_MODE,
        "bin_size": BIN_SIZE,
        "bin_count": len(rows),
        "median_log2_tumor_normal": round_value(median(log2_values), 4),
        "relative_gain_bins": sum(1 for row in rows if row["coverage_class"] == "relative_gain"),
        "relative_loss_bins": sum(1 for row in rows if row["coverage_class"] == "relative_loss"),
        "output_bins": "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
        "scarhrd_input_status": "not_assessable_without_allele_specific_segments",
        "real_output_status": "real_coverage_cnv_bin_output",
        "caveat": "Real WGS BAM coverage-derived CNV bins from samtools bedcov. This validates CNV feature plumbing but is not allele-specific segmentation or scarHRD.",
    }
    write_csv(path_from_root(summary_output), [summary])
    write_json(
        path_from_root(summary_json),
        {"generatedAt": iso_now(), "status": summary["status"], "coverageCnvMode": COVERAGE_CNV_MODE, "rows": [summary]},
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
    skip_bam_hydration = bool(rows) and downstream_can_skip_bam_hydration(rows[0])
    inputs = [] if skip_bam_hydration else [path for row in rows for path in [row["output_bam"], row.get("output_bai", "")]]
    final_outputs = [candidates_output, summary_output, summary_json]
    final_cache_uris = (
        {output: pair_validation_cache_uri(rows[0], rows[1] if len(rows) > 1 else rows[0], "sv_evidence", output) for output in final_outputs}
        if rows
        else {}
    )
    restore_requires_current = not skip_bam_hydration
    if not FORCE and (
        existing_output_current(final_outputs, inputs)
        or restore_cached_outputs(final_outputs, final_cache_uris, inputs, "pair.sv_evidence", require_current=restore_requires_current)
    ):
        cached_rows = read_json(path_from_root(summary_json)).get("rows", [])
        cached_keys = {(row.get("role", ""), row.get("run_accession", ""), row.get("input_bam", "")) for row in cached_rows}
        if cached_rows and cached_keys == expected_keys and all(row.get("status") == "passed" for row in cached_rows):
            return [{**row, "sv_cache": "reused"} for row in cached_rows]
    if skip_bam_hydration:
        summary_rows = [
            {
                "status": "passed",
                "tool": "metadata_only",
                "sample": row["sample"],
                "role": row["role"],
                "run_accession": row["run_accession"],
                "input_bam": row["output_bam"],
                "total_alignments": "",
                "supplementary_alignments": "",
                "discordant_mapped_pairs": "",
                "interchromosomal_pairs": "",
                "large_insert_pairs": "",
                "sv_candidate_rows_written": 0,
                "chord_input_status": "not_assessable_metadata_only",
                "caveat": "Metadata-only SV evidence mode skips full-BAM samtools view for public-BAM optimization timing runs.",
                "sv_cache": "metadata_only_no_bam_hydration",
            }
            for row in rows
        ]
        write_csv(path_from_root(candidates_output), [], SV_CANDIDATE_COLUMNS)
        write_csv(path_from_root(summary_output), summary_rows, SV_SUMMARY_COLUMNS)
        write_json(path_from_root(summary_json), {"generatedAt": iso_now(), "status": "passed", "rows": summary_rows})
        publish_cached_outputs(final_outputs, final_cache_uris, "pair.sv_evidence")
        return summary_rows
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
    allowed_stages = {"all", "reference_index", "align_sample", "prepare_fastq_shards", "align_shard", "gather_shards", "downstream"}
    if STAGE not in allowed_stages:
        raise RuntimeError(f"Unsupported PHASE3_WGS_STAGE={STAGE!r}; choose one of {sorted(allowed_stages)}.")
    if ALIGN_INPUT_MODE not in {"local_fastq", "cache_stream"}:
        raise RuntimeError("PHASE3_WGS_ALIGN_INPUT_MODE must be local_fastq or cache_stream.")
    if ALIGNER not in {"bwa", "bwa-mem2", "minimap2"}:
        raise RuntimeError("PHASE3_WGS_ALIGNER must be bwa, bwa-mem2, or minimap2.")
    if ALIGN_PROFILE_MODE not in {"pipe", "mem_only", "unsorted_bam"}:
        raise RuntimeError("PHASE3_WGS_ALIGN_PROFILE_MODE must be pipe, mem_only, or unsorted_bam.")
    if SCATTER_OUTPUT_MODE not in {"merged_bam", "shard_manifest"}:
        raise RuntimeError("PHASE3_WGS_SCATTER_OUTPUT_MODE must be merged_bam or shard_manifest.")
    if SHARD_INPUT_MODE not in {"fastq_cache", "sra_spot_range"}:
        raise RuntimeError("PHASE3_WGS_SHARD_INPUT_MODE must be fastq_cache or sra_spot_range.")
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
        required_paths = common_required_paths
        if ALIGN_INPUT_MODE == "local_fastq" and not selected_row.get("source_bam_url"):
            required_paths += [selected_row["fastq_1"], selected_row["fastq_2"]]
    elif STAGE in {"prepare_fastq_shards", "align_shard", "gather_shards"}:
        if SAMPLE_ROLE not in {"tumor", "normal"}:
            raise RuntimeError(f"PHASE3_WGS_STAGE={STAGE} requires PHASE3_WGS_SAMPLE_ROLE=tumor or normal.")
        shard_count = require_shard_count()
        if STAGE == "align_shard":
            require_shard_index(shard_count)
        if STAGE == "gather_shards" and SCATTER_OUTPUT_MODE == "shard_manifest":
            required_paths = []
        else:
            required_paths = common_required_paths
    elif STAGE == "downstream":
        skip_bam_hydration = downstream_can_skip_bam_hydration(tumor)
        if skip_bam_hydration:
            print("[phase3-wgs] Skipping downstream BAM hydration for public-BAM timing mode.", flush=True)
        else:
            for row in (tumor, normal):
                if not bam_satisfies_read_scope(row):
                    restore_cached_alignment(row)
        required_paths = list(common_required_paths)
        if not skip_bam_hydration:
            required_paths += [
                tumor["output_bam"],
                tumor["output_bai"],
                normal["output_bam"],
                normal["output_bai"],
            ]
        if tumor.get("production_caller") != "skipped_for_public_bam_timing":
            required_paths += [
                tumor["gatk_jar_path"],
                tumor["truth_snv_vcf_path"],
                tumor["truth_indel_vcf_path"],
                tumor["truth_high_confidence_bed_path"],
            ]
    else:
        required_paths = []
        for row in rows:
            if not row.get("source_bam_url"):
                required_paths.extend([row["fastq_1"], row["fastq_2"]])
            required_paths.extend(
                [
                    row["reference_path"],
                    row["reference_fai_path"],
                    row["reference_dict_path"],
                ]
            )
            if row.get("gatk_jar_path"):
                required_paths.append(row["gatk_jar_path"])
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
        selected_row = tumor if SAMPLE_ROLE == "tumor" else normal
        if not selected_row.get("source_bam_url"):
            ensure_bwa_index(reference_id, tumor["reference_path"])
        align_and_index_sample(reference_id, selected_row)
        return

    if STAGE == "prepare_fastq_shards":
        selected_row = tumor if SAMPLE_ROLE == "tumor" else normal
        prepare_fastq_shards(selected_row, require_shard_count())
        return

    if STAGE == "align_shard":
        selected_row = tumor if SAMPLE_ROLE == "tumor" else normal
        shard_count = require_shard_count()
        align_and_publish_shard(reference_id, selected_row, require_shard_index(shard_count), shard_count)
        return

    if STAGE == "gather_shards":
        selected_row = tumor if SAMPLE_ROLE == "tumor" else normal
        gather_shards(reference_id, selected_row, require_shard_count())
        return

    align_commands: list[tuple[str, str]] = []
    if alignment_materialization_required_for_stage(STAGE, tumor):
        for row in rows:
            ensure_dir(path_from_root("/".join(row["output_bam"].split("/")[:-1])))
            if not FORCE and bam_satisfies_read_scope(row):
                continue
            if restore_cached_alignment(row):
                continue
            if restore_public_alignment(row):
                continue
            remove_stale_alignment(row)
            command = align_command(row, PER_SAMPLE_BWA_THREADS, PER_SAMPLE_SORT_THREADS)
            align_commands.append((command, f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.align.log"))
    if align_commands:
        ensure_bwa_index(reference_id, tumor["reference_path"])
        if PARALLEL_ALIGN:
            run_commands_parallel(align_commands, len(align_commands))
        else:
            for command, log_path in align_commands:
                run_command(command, log_path)

    bam_summary_outputs = [f"{RESULTS_DIR}/bam_validation_summary.csv", f"{RESULTS_DIR}/bam_validation_summary.json"]
    skip_bam_hydration = downstream_can_skip_bam_hydration(tumor)
    bam_summary_inputs = [] if skip_bam_hydration else [path for row in rows for path in [row["output_bam"], row.get("output_bai", "")]]
    restore_cached_outputs(
        bam_summary_outputs,
        {output: pair_validation_cache_uri(tumor, normal, bam_validation_cache_group(), output) for output in bam_summary_outputs},
        bam_summary_inputs,
        "pair.bam_validation",
        require_current=False,
    )
    reusable_bam_rows = reusable_bam_validation_rows(rows, require_bams=not skip_bam_hydration)
    if reusable_bam_rows is None and skip_bam_hydration:
        raise RuntimeError("Public-BAM timing downstream skip requires cached BAM validation summary outputs.")
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
            if not FORCE and not flagstat_log_has_counts(flagstat_log):
                restore_cached_output(
                    flagstat_log,
                    sample_validation_cache_uri(row, flagstat_log),
                    [row["output_bam"], row["output_bai"]],
                    f"{row['role']}.flagstat",
                    require_current=False,
                )
            if FORCE or not flagstat_log_has_counts(flagstat_log):
                stats_commands.append(
                    (
                        f"samtools flagstat -@ {BAM_SCAN_THREADS} {quote_shell_arg(row['output_bam'])}",
                        flagstat_log,
                        [row["output_bam"], row["output_bai"]],
                        sample_validation_cache_uri(row, flagstat_log),
                        f"{row['role']}.flagstat",
                    )
                )
            if bam_stats_enabled() and (FORCE or not existing_output_current([stats_log], [row["output_bam"]])):
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

    if skip_bam_hydration:
        alignment_cache_rows = []
    else:
        with ThreadPoolExecutor(max_workers=min(ALIGNMENT_CACHE_WORKERS, len(rows))) as pool:
            alignment_cache_rows = list(pool.map(publish_cached_alignment, rows))
    bam_rows = reusable_bam_rows if reusable_bam_rows is not None else validate_bam_rows(rows)
    bam_status = "passed" if all(row["status"] == "passed" for row in bam_rows) else "failed"
    write_csv(path_from_root(f"{RESULTS_DIR}/bam_validation_summary.csv"), bam_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/bam_validation_summary.json"),
        {"generatedAt": iso_now(), "status": bam_status, "bamValidationMode": BAM_VALIDATION_MODE, "rows": bam_rows},
    )
    publish_cached_outputs(
        bam_summary_outputs,
        {output: pair_validation_cache_uri(tumor, normal, bam_validation_cache_group(), output) for output in bam_summary_outputs},
        "pair.bam_validation",
    )
    if bam_status != "passed":
        raise RuntimeError("Phase 3 WGS BAM validation failed.")

    ensure_dir(path_from_root(interval_dir))
    ensure_dir(path_from_root(vcf_dir))
    build_bins(tumor["reference_fai_path"], bins_path)
    cnv_summary = build_coverage_cnv(tumor, normal, bins_path)

    if tumor.get("production_caller") == "skipped_for_public_bam_timing":
        covered_truth: list[dict[str, Any]] = []
        truth_variants: list[dict[str, Any]] = []
        interval_rows: list[dict[str, Any]] = []
        filtered_calls = {"passCount": 0, "totalCount": 0}
        exact_matches: list[str] = []
        normalized_filtered_vcf = ""
        mutect_status = "skipped_public_bam_timing"
        write_csv(path_from_root(f"{RESULTS_DIR}/covered_truth_variants.csv"), [])
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
            "interval_strategy": "skipped_for_public_bam_timing",
            "mutect_interval_bed_path": "",
            "mutect_interval_count": 0,
            "truth_variants_total": 0,
            "truth_variants_depth_eligible": 0,
            "truth_snv_records_in_intervals": 0,
            "truth_indel_records_in_intervals": 0,
            "filtered_vcf": "",
            "filtered_tbi": "",
            "filtered_records_in_intervals": 0,
            "pass_records_in_intervals": 0,
            "exact_pass_truth_matches": 0,
            "comparison_status": "skipped_missing_gatk_and_seqc2_truth_for_public_bam_timing",
            "panel_of_normals_used": "",
            "caveat": "Public-BAM timing mode skips GATK Mutect2 and truth comparison to isolate alignment restore and downstream BAM-processing performance.",
        }
        write_csv(path_from_root(f"{RESULTS_DIR}/mutect2_wgs_summary.csv"), [mutect_row])
        write_json(
            path_from_root(f"{RESULTS_DIR}/mutect2_wgs_summary.json"),
            {"generatedAt": iso_now(), "status": mutect_status, "rows": [mutect_row]},
        )
        matrix_output = f"{RESULTS_DIR}/wgs_sbs96_matrix.csv"
        signature_output = f"{RESULTS_DIR}/signature_assignment_summary.csv"
        signature_json = f"{RESULTS_DIR}/signature_assignment_summary.json"
        write_csv(path_from_root(matrix_output), all_sbs96_rows())
        signature_summary = {
            "status": "skipped_public_bam_timing",
            "tool": "local_sbs96_matrix_builder",
            "source_vcf": "",
            "source_record_policy": "skipped_missing_gatk_and_seqc2_truth_for_public_bam_timing",
            "sbs96_rows": 96,
            "usable_snv_records": 0,
            "skipped_snv_records": 0,
            "total_matrix_count": 0,
            "sigprofiler_assignment_status": "not_assessable_variant_calling_skipped",
            "output_matrix": matrix_output,
            "caveat": "SBS96 matrix is metadata-only in public-BAM timing mode because variant calling is intentionally skipped.",
        }
        write_csv(path_from_root(signature_output), [signature_summary])
        write_json(path_from_root(signature_json), {"generatedAt": iso_now(), "status": signature_summary["status"], "rows": [signature_summary]})
    else:
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
            "real_output_status": cnv_summary.get("real_output_status", "real_coverage_cnv_bin_output"),
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
            "bwa_mem2": {"path": capture_command("command -v bwa-mem2"), "version": tool_version("bwa-mem2")},
            "minimap2": {"path": capture_command("command -v minimap2"), "version": tool_version("minimap2")},
            "samtools": {"path": capture_command("command -v samtools"), "version": tool_version("samtools")},
            "bcftools": {"path": capture_command("command -v bcftools"), "version": tool_version("bcftools")},
            "java": {
                "path": tumor["java_path"],
                "version": capture_command(f"{quote_shell_arg(tumor['java_path'])} -version 2>&1 | head -n 1")
                if tumor.get("java_path")
                else "skipped_public_bam_timing",
            },
            "gatk": {
                "jarPath": tumor["gatk_jar_path"],
                "version": capture_command(
                    f"{quote_shell_arg(tumor['java_path'])} -jar {quote_shell_arg(tumor['gatk_jar_path'])} --version 2>&1 | head -n 1"
                )
                if tumor.get("java_path") and tumor.get("gatk_jar_path")
                else "skipped_public_bam_timing",
            },
            "optionalNativeIntegrations": native_tool_versions(),
        },
    )

    phase3_complete = phase3_completion_status(
        tumor,
        bam_status=bam_status,
        mutect_status=mutect_status,
        cnv_status=cnv_summary["status"],
        signature_status=signature_summary["status"],
        sv_rows=sv_rows,
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
        "aligner": ALIGNER,
        "align_bwa_threads": ALIGN_BWA_THREADS,
        "align_sort_threads": ALIGN_SORT_THREADS,
        "parallel_align": "yes" if PARALLEL_ALIGN else "no",
        "per_sample_threads": PER_SAMPLE_THREADS,
        "per_sample_bwa_threads": PER_SAMPLE_BWA_THREADS,
        "per_sample_sort_threads": PER_SAMPLE_SORT_THREADS,
        "gatk_threads": GATK_THREADS,
        "alignment_cache_workers": ALIGNMENT_CACHE_WORKERS,
        "bam_validation_status": bam_status,
        "bam_validation_mode": BAM_VALIDATION_MODE,
        "mutect2_status": mutect_status,
        "normalized_filtered_vcf": normalized_filtered_vcf,
        "mutect_interval_count": len(interval_rows),
        "truth_variants_depth_eligible": len(covered_truth),
        "pass_records_in_intervals": filtered_calls["passCount"],
        "exact_pass_truth_matches": len(exact_matches),
        "coverage_cnv_status": cnv_summary["status"],
        "coverage_cnv_mode": COVERAGE_CNV_MODE,
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
            "coverageCnvMode": COVERAGE_CNV_MODE,
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
