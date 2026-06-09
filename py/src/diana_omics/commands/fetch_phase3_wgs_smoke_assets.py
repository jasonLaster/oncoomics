from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from ..paths import path_from_root
from ..utils import (
    command_path,
    ensure_dir,
    iso_now,
    parse_csv,
    quote_shell_arg,
    read_text,
    round_value,
    run_command,
    validate_fastq_record,
    write_csv,
    write_json,
    write_text,
)

PAIR_ID = os.environ.get("PHASE3_WGS_PAIR_ID", "seqc2_hcc1395_wgs_hiseqx_full")
READS_REQUEST = os.environ.get("PHASE3_WGS_READS", "full")
READ_PAIRS_LIMIT = None if READS_REQUEST.lower() in {"all", "full", "0"} else int(READS_REQUEST)
FETCH_CONCURRENCY = max(1, int(os.environ.get("PHASE3_WGS_FETCH_CONCURRENCY", "2")))
ARIA2_SPLIT = max(1, int(os.environ.get("PHASE3_WGS_ARIA2_SPLIT", "1")))
SOURCE_MODE = os.environ.get("PHASE3_WGS_SOURCE_MODE", "ena_fastq").lower().replace("-", "_")
SRA_AWS_BUCKET = os.environ.get("PHASE3_WGS_SRA_AWS_BUCKET", "sra-pub-run-odp")
SRA_THREADS = max(1, int(os.environ.get("PHASE3_WGS_SRA_THREADS", str(FETCH_CONCURRENCY))))
S3_MAX_CONCURRENT_REQUESTS = max(1, int(os.environ.get("PHASE3_WGS_S3_MAX_CONCURRENT_REQUESTS", str(max(16, SRA_THREADS * 2)))))
S3_RANGE_CONCURRENCY = max(1, int(os.environ.get("PHASE3_WGS_S3_RANGE_CONCURRENCY", str(max(8, SRA_THREADS * 2)))))
S3_RANGE_BYTES = max(8 * 1024 * 1024, int(os.environ.get("PHASE3_WGS_S3_RANGE_BYTES", str(256 * 1024 * 1024))))
RESULTS_DIR = "results/phase3_wgs_smoke"
SMOKE_ROOT = "data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full"
SEQC2_TRUTH_ROOT = "data/raw/reference/seqc2_hcc1395_truth/latest"
STORE_IDS_LIMIT = 1_000_000


def sra_aws_uri(run: str) -> str:
    return f"s3://{SRA_AWS_BUCKET}/sra/{run}/{run}"


def reference_dict_path(fasta_path: str) -> str:
    for suffix in (".fasta", ".fa"):
        if fasta_path.lower().endswith(suffix):
            return f"{fasta_path[: -len(suffix)]}.dict"
    return f"{fasta_path}.dict"


def java_works(candidate: str) -> bool:
    if not candidate or not Path(candidate).exists():
        return False
    import subprocess

    result = subprocess.run([candidate, "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    output = f"{result.stdout}{result.stderr}"
    import re

    match = re.search(r'version "(\d+)', output)
    return result.returncode == 0 and int(match.group(1) if match else "0") >= 17


def find_java(fallback: str = "") -> str:
    candidates = [
        os.environ.get("GATK_JAVA", ""),
        fallback,
        "/opt/homebrew/opt/openjdk@17/bin/java",
        "/opt/homebrew/bin/java",
        command_path("java"),
    ]
    for candidate in candidates:
        if java_works(candidate):
            return candidate
    raise RuntimeError("Phase 3 WGS validation requires Java 17+ for GATK. Install openjdk@17 or set GATK_JAVA.")


def expected_read_pairs(row: dict[str, str]) -> int:
    return int(row["spots"]) if READ_PAIRS_LIMIT is None else READ_PAIRS_LIMIT


def read_count_label(read_pairs: int) -> str:
    return "full" if READ_PAIRS_LIMIT is None else f"{read_pairs}reads"


def open_fastq_text(path: Path) -> Any:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def summarize_fastq(run: str, read: str, source_url: str, output_path: Path, source: str, expected_records: int) -> dict[str, Any]:
    current: list[str] = []
    ids: list[str] = []
    keep_ids = expected_records <= STORE_IDS_LIMIT
    records = total_length = gc = n = bases = 0
    min_length = 10**9
    max_length = 0
    q_min = 10**9
    q_max = 0
    first_read_id = ""
    last_read_id = ""

    with open_fastq_text(output_path) as handle:
        for raw_line in handle:
            current.append(raw_line.rstrip("\n"))
            if len(current) != 4:
                continue
            records += 1
            record = validate_fastq_record(current, f"{run} {read}", records)
            first_read_id = first_read_id or record["id"]
            last_read_id = record["id"]
            if keep_ids:
                ids.append(record["id"])
            sequence = record["sequence"].upper()
            quality = record["quality"]
            length = len(sequence)
            total_length += length
            min_length = min(min_length, length)
            max_length = max(max_length, length)
            gc += sequence.count("G") + sequence.count("C")
            n += sequence.count("N")
            bases += length
            for char in quality:
                code = ord(char)
                q_min = min(q_min, code)
                q_max = max(q_max, code)
            current = []

    if current:
        raise RuntimeError(f"{run} {read} ended mid-record")
    if records != expected_records:
        raise RuntimeError(f"{run} {read} has {records} records; expected {expected_records}")

    return {
        "run": run,
        "read": read,
        "sourceUrl": source_url,
        "outputPath": str(output_path),
        "records": records,
        "minLength": min_length,
        "maxLength": max_length,
        "meanLength": total_length / records,
        "gcFraction": gc / bases,
        "nFraction": n / bases,
        "qualityAsciiMin": q_min,
        "qualityAsciiMax": q_max,
        "firstReadId": first_read_id,
        "lastReadId": last_read_id,
        "ids": ids,
        "idsStored": keep_ids,
        "source": source,
    }


def new_fastq_metric() -> dict[str, Any]:
    return {
        "records": 0,
        "totalLength": 0,
        "gc": 0,
        "n": 0,
        "bases": 0,
        "minLength": 10**9,
        "maxLength": 0,
        "qualityAsciiMin": 10**9,
        "qualityAsciiMax": 0,
        "firstReadId": "",
        "lastReadId": "",
    }


def update_fastq_metric(metric: dict[str, Any], record: dict[str, str]) -> None:
    metric["records"] = int(metric["records"]) + 1
    metric["firstReadId"] = metric["firstReadId"] or record["id"]
    metric["lastReadId"] = record["id"]
    sequence = record["sequence"].upper()
    quality = record["quality"]
    length = len(sequence)
    metric["totalLength"] = int(metric["totalLength"]) + length
    metric["minLength"] = min(int(metric["minLength"]), length)
    metric["maxLength"] = max(int(metric["maxLength"]), length)
    metric["gc"] = int(metric["gc"]) + sequence.count("G") + sequence.count("C")
    metric["n"] = int(metric["n"]) + sequence.count("N")
    metric["bases"] = int(metric["bases"]) + length
    for char in quality:
        code = ord(char)
        metric["qualityAsciiMin"] = min(int(metric["qualityAsciiMin"]), code)
        metric["qualityAsciiMax"] = max(int(metric["qualityAsciiMax"]), code)


def final_fastq_summary(
    metric: dict[str, Any], run: str, read: str, source_url: str, output_path: str, source: str, expected_records: int
) -> dict[str, Any]:
    records = int(metric["records"])
    if records != expected_records:
        raise RuntimeError(f"{run} {read} has {records} records; expected {expected_records}")
    bases = int(metric["bases"])
    return {
        "run": run,
        "read": read,
        "sourceUrl": source_url,
        "outputPath": str(path_from_root(output_path)),
        "records": records,
        "minLength": int(metric["minLength"]),
        "maxLength": int(metric["maxLength"]),
        "meanLength": int(metric["totalLength"]) / records,
        "gcFraction": int(metric["gc"]) / bases,
        "nFraction": int(metric["n"]) / bases,
        "qualityAsciiMin": int(metric["qualityAsciiMin"]),
        "qualityAsciiMax": int(metric["qualityAsciiMax"]),
        "firstReadId": metric["firstReadId"],
        "lastReadId": metric["lastReadId"],
        "ids": [],
        "idsStored": False,
        "source": source,
    }


def parse_seqkit_stats(output: str) -> dict[str, dict[str, str]]:
    rows = parse_csv(output.replace("\t", ","))
    return {row["file"]: row for row in rows}


def first_fastq_id(path: str, label: str) -> str:
    seqkit = command_path("seqkit")
    if not seqkit:
        return ""
    result = subprocess.run(
        [seqkit, "head", "-n", "1", str(path_from_root(path))],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"seqkit head failed for {label}: {result.stderr}")
    lines = result.stdout.splitlines()
    if len(lines) < 4:
        raise RuntimeError(f"seqkit head returned an incomplete FASTQ record for {label}.")
    return validate_fastq_record(lines[:4], label, 1)["id"]


def summarize_paired_fastqs_with_seqkit(row: dict[str, Any], source: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    seqkit = command_path("seqkit")
    if not seqkit:
        raise RuntimeError("seqkit is not available.")
    r1_path = path_from_root(row["fastq_1"])
    r2_path = path_from_root(row["fastq_2"])
    result = subprocess.run(
        [seqkit, "stats", "-T", "-a", "-j", str(min(FETCH_CONCURRENCY, 4)), str(r1_path), str(r2_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"seqkit stats failed for {row['run_accession']}: {result.stderr}")
    stats_by_path = parse_seqkit_stats(result.stdout)
    expected_records = int(row["read_pairs_per_end"])

    def summary_for(read: str, path: str, source_url: str) -> dict[str, Any]:
        stats = stats_by_path.get(str(path_from_root(path)))
        if not stats:
            raise RuntimeError(f"seqkit stats did not return metrics for {path}.")
        records = int(stats["num_seqs"])
        bases = int(stats["sum_len"])
        if records != expected_records:
            raise RuntimeError(f"{row['run_accession']} {read} has {records} records; expected {expected_records}")
        return {
            "run": row["run_accession"],
            "read": read,
            "sourceUrl": source_url,
            "outputPath": str(path_from_root(path)),
            "records": records,
            "minLength": int(float(stats["min_len"])),
            "maxLength": int(float(stats["max_len"])),
            "meanLength": float(stats["avg_len"]),
            "gcFraction": float(stats["GC(%)"]) / 100,
            "nFraction": int(stats["sum_n"]) / bases if bases else 0,
            "qualityAsciiMin": "",
            "qualityAsciiMax": "",
            "firstReadId": first_fastq_id(path, f"{row['run_accession']} {read}"),
            "lastReadId": "not_collected_seqkit_full_scan",
            "ids": [],
            "idsStored": False,
            "source": source,
            "validationMethod": "seqkit_stats_full_scan",
        }

    r1_summary = summary_for("R1", row["fastq_1"], row["source_fastq_1"])
    r2_summary = summary_for("R2", row["fastq_2"], row["source_fastq_2"])
    if r1_summary["firstReadId"] != r2_summary["firstReadId"]:
        raise RuntimeError(
            f"{row['run_accession']} R1/R2 first read-id mismatch: {r1_summary['firstReadId']} vs {r2_summary['firstReadId']}"
        )
    paired_summary = {
        "run": row["run_accession"],
        "records": expected_records,
        "firstReadId": r1_summary["firstReadId"],
        "lastReadId": "not_collected_seqkit_full_scan",
        "pairedIdCheck": "passed",
        "validationMethod": "seqkit_stats_full_scan_with_exact_provider_md5",
    }
    return r1_summary, r2_summary, paired_summary


def summarize_paired_fastqs(row: dict[str, Any], source: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if READ_PAIRS_LIMIT is None and command_path("seqkit"):
        return summarize_paired_fastqs_with_seqkit(row, source)

    run = row["run_accession"]
    expected_records = int(row["read_pairs_per_end"])
    r1_metric = new_fastq_metric()
    r2_metric = new_fastq_metric()
    r1_current: list[str] = []
    r2_current: list[str] = []
    first_read_id = ""
    last_read_id = ""
    with open_fastq_text(path_from_root(row["fastq_1"])) as r1_handle:
        with open_fastq_text(path_from_root(row["fastq_2"])) as r2_handle:
            while True:
                r1_line = r1_handle.readline()
                r2_line = r2_handle.readline()
                if not r1_line and not r2_line:
                    break
                if not r1_line or not r2_line:
                    raise RuntimeError(f"{run} R1/R2 ended at different positions during paired validation.")
                r1_current.append(r1_line.rstrip("\n"))
                r2_current.append(r2_line.rstrip("\n"))
                if len(r1_current) != 4:
                    continue
                record_number = int(r1_metric["records"]) + 1
                r1_record = validate_fastq_record(r1_current, f"{run} R1", record_number)
                r2_record = validate_fastq_record(r2_current, f"{run} R2", record_number)
                if r1_record["id"] != r2_record["id"]:
                    raise RuntimeError(f"{run} R1/R2 read-id mismatch at {record_number}: {r1_record['id']} vs {r2_record['id']}")
                update_fastq_metric(r1_metric, r1_record)
                update_fastq_metric(r2_metric, r2_record)
                first_read_id = first_read_id or r1_record["id"]
                last_read_id = r1_record["id"]
                r1_current = []
                r2_current = []
    if r1_current or r2_current:
        raise RuntimeError(f"{run} R1/R2 ended mid-record during paired validation.")
    r1_summary = final_fastq_summary(r1_metric, run, "R1", row["source_fastq_1"], row["fastq_1"], source, expected_records)
    r2_summary = final_fastq_summary(r2_metric, run, "R2", row["source_fastq_2"], row["fastq_2"], source, expected_records)
    paired_summary = {
        "run": run,
        "records": expected_records,
        "firstReadId": first_read_id,
        "lastReadId": last_read_id,
        "pairedIdCheck": "passed",
    }
    return r1_summary, r2_summary, paired_summary


def download_full_fastq(
    run: str,
    read: str,
    source_url: str,
    output_relative_path: str,
    expected_records: int,
    expected_bytes: int,
    expected_md5: str,
    summarize: bool = True,
) -> dict[str, Any]:
    output_path = path_from_root(output_relative_path)
    ensure_dir(output_path.parent)
    source = "existing"
    current_bytes = output_path.stat().st_size if output_path.exists() else 0
    aria2_control_path = output_path.with_name(output_path.name + ".aria2")

    if current_bytes == expected_bytes and expected_md5 and not aria2_control_path.exists():
        md5 = hashlib.md5()
        with output_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                md5.update(chunk)
        digest = md5.hexdigest()
        if digest.lower() != expected_md5.lower():
            output_path.unlink()
            current_bytes = 0

    if current_bytes != expected_bytes or aria2_control_path.exists():
        source = "downloaded" if current_bytes == 0 else "resumed"
        aria2 = command_path("aria2c")
        if aria2:
            subprocess.run(
                [
                    aria2,
                    "--continue=true",
                    f"--max-connection-per-server={ARIA2_SPLIT}",
                    f"--split={ARIA2_SPLIT}",
                    "--min-split-size=64M",
                    "--file-allocation=none",
                    "--auto-file-renaming=false",
                    "--allow-overwrite=true",
                    "--retry-wait=10",
                    "--max-tries=20",
                    "--summary-interval=0",
                    "--console-log-level=error",
                    "--show-console-readout=false",
                    "--quiet=true",
                    "--dir",
                    str(output_path.parent),
                    "--out",
                    output_path.name,
                    source_url,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
            if tmp_path.exists():
                tmp_path.unlink()
            request = urllib.request.Request(source_url)
            md5 = hashlib.md5()
            bytes_written = 0
            with urllib.request.urlopen(request, timeout=300) as response:
                with tmp_path.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        md5.update(chunk)
                        output.write(chunk)
                        bytes_written += len(chunk)
            if bytes_written != expected_bytes:
                raise RuntimeError(f"{run} {read} downloaded {bytes_written} bytes; expected {expected_bytes}")
            digest = md5.hexdigest()
            if expected_md5 and digest.lower() != expected_md5.lower():
                raise RuntimeError(f"{run} {read} MD5 mismatch: {digest} != {expected_md5}")
            shutil.move(str(tmp_path), output_path)

    actual_bytes = output_path.stat().st_size
    if actual_bytes != expected_bytes:
        raise RuntimeError(f"{run} {read} has {actual_bytes} compressed bytes; expected {expected_bytes}")
    if expected_md5:
        md5 = hashlib.md5()
        with output_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                md5.update(chunk)
        digest = md5.hexdigest()
        if digest.lower() != expected_md5.lower():
            raise RuntimeError(f"{run} {read} existing MD5 mismatch: {digest} != {expected_md5}")

    if summarize:
        return summarize_fastq(run, read, source_url, output_path, source, expected_records)
    return {
        "run": run,
        "read": read,
        "sourceUrl": source_url,
        "outputPath": str(output_path),
        "records": expected_records,
        "ids": [],
        "idsStored": False,
        "source": source,
    }


def download_full_fastq_without_summary(task: tuple[str, str, str, str, int, int, str]) -> dict[str, Any]:
    run, read, source_url, output_relative_path, expected_records, expected_bytes, expected_md5 = task
    return download_full_fastq(run, read, source_url, output_relative_path, expected_records, expected_bytes, expected_md5, False)


def gzip_fastq(input_path: Path, output_path: Path, threads: int) -> None:
    ensure_dir(output_path.parent)
    pigz = command_path("pigz")
    if pigz:
        run_command(
            f"{quote_shell_arg(pigz)} -p {max(1, threads)} -c {quote_shell_arg(str(input_path))} > {quote_shell_arg(str(output_path))}",
            f"{RESULTS_DIR}/logs/gzip.{output_path.name}.log",
        )
    else:
        with input_path.open("rb") as source:
            with gzip.open(output_path, "wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


def write_aws_s3_transfer_config(max_concurrent_requests: int) -> Path:
    config_path = path_from_root(f"{RESULTS_DIR}/logs/aws_s3_config")
    write_text(
        config_path,
        "\n".join(
            [
                "[default]",
                "s3 =",
                f"    max_concurrent_requests = {max(1, max_concurrent_requests)}",
                "    multipart_threshold = 64MB",
                "    multipart_chunksize = 64MB",
            ]
        ),
    )
    return config_path


def aws_sra_object_size(aws: str, run: str, log_path: Path) -> int:
    command = [
        aws,
        "s3api",
        "head-object",
        "--no-sign-request",
        "--bucket",
        SRA_AWS_BUCKET,
        "--key",
        f"sra/{run}/{run}",
        "--query",
        "ContentLength",
        "--output",
        "text",
    ]
    started = iso_now()
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"[{started}] head-object {sra_aws_uri(run)}\n")
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        log.write(result.stdout)
        if not result.stdout.endswith("\n"):
            log.write("\n")
    if result.returncode != 0:
        raise RuntimeError(f"Unable to inspect SRA object for {run}. See {log_path}.")
    return int(result.stdout.strip().splitlines()[-1])


def download_aws_sra_object_with_ranges(aws: str, run: str, target_path: Path, concurrency: int, range_bytes: int) -> dict[str, Any]:
    ensure_dir(target_path.parent)
    log_path = path_from_root(f"{RESULTS_DIR}/logs/aws_sra_range_cp.{run}.log")
    ensure_dir(log_path.parent)
    object_size = aws_sra_object_size(aws, run, log_path)
    if target_path.exists() and target_path.stat().st_size == object_size:
        return {
            "run": run,
            "sourceUrl": sra_aws_uri(run),
            "outputPath": str(target_path),
            "bytes": object_size,
            "rangeConcurrency": concurrency,
            "rangeBytes": range_bytes,
            "source": "existing_aws_sra_range",
        }

    partial_path = target_path.with_suffix(f"{target_path.suffix}.partial")
    if partial_path.exists():
        partial_path.unlink()
    ensure_dir(partial_path.parent)
    with partial_path.open("wb") as handle:
        handle.truncate(object_size)

    ranges = [(start, min(start + range_bytes - 1, object_size - 1)) for start in range(0, object_size, range_bytes)]
    temp_dir = target_path.parent / f".{run}.ranges"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    ensure_dir(temp_dir)
    write_lock = Lock()

    with log_path.open("a", encoding="utf-8") as log:
        log.write(
            f"[{iso_now()}] range-download start run={run} bytes={object_size} "
            f"range_bytes={range_bytes} ranges={len(ranges)} concurrency={concurrency}\n"
        )

    def download_range(index_and_range: tuple[int, tuple[int, int]]) -> dict[str, Any]:
        index, (start, end) = index_and_range
        part_path = temp_dir / f"{run}.{index:06d}.part"
        command = [
            aws,
            "s3api",
            "get-object",
            "--no-sign-request",
            "--bucket",
            SRA_AWS_BUCKET,
            "--key",
            f"sra/{run}/{run}",
            "--range",
            f"bytes={start}-{end}",
            str(part_path),
        ]
        part_started = iso_now()
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"[{part_started}] range failed index={index} bytes={start}-{end}\n{result.stdout}\n")
            raise RuntimeError(f"SRA range download failed for {run} bytes={start}-{end}. See {log_path}.")
        size = part_path.stat().st_size
        expected = end - start + 1
        if size != expected:
            raise RuntimeError(f"SRA range download for {run} bytes={start}-{end} wrote {size} bytes, expected {expected}.")
        with write_lock:
            with partial_path.open("r+b") as target, part_path.open("rb") as part:
                target.seek(start)
                shutil.copyfileobj(part, target, length=8 * 1024 * 1024)
        part_path.unlink()
        if index == 0 or (index + 1) % 25 == 0 or index + 1 == len(ranges):
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"[{iso_now()}] range complete {index + 1}/{len(ranges)} bytes={start}-{end}\n")
        return {"index": index, "bytes": size}

    with ThreadPoolExecutor(max_workers=min(concurrency, len(ranges))) as pool:
        list(pool.map(download_range, enumerate(ranges)))

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    if partial_path.stat().st_size != object_size:
        raise RuntimeError(f"SRA range download for {run} has unexpected final size {partial_path.stat().st_size}; expected {object_size}.")
    partial_path.replace(target_path)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"[{iso_now()}] range-download complete run={run} bytes={object_size} output={target_path}\n")
    return {
        "run": run,
        "sourceUrl": sra_aws_uri(run),
        "outputPath": str(target_path),
        "bytes": object_size,
        "rangeConcurrency": concurrency,
        "rangeBytes": range_bytes,
        "source": "aws_sra_range",
    }


def download_aws_sra_run(row: dict[str, Any], threads: int) -> list[dict[str, Any]]:
    run = row["run_accession"]
    r1_path = path_from_root(row["fastq_1"])
    r2_path = path_from_root(row["fastq_2"])
    if r1_path.exists() and r1_path.stat().st_size > 0 and r2_path.exists() and r2_path.stat().st_size > 0:
        return [
            {"run": run, "read": "R1", "sourceUrl": sra_aws_uri(run), "outputPath": str(r1_path), "records": row["read_pairs_per_end"], "ids": [], "idsStored": False, "source": "existing_aws_sra"},
            {"run": run, "read": "R2", "sourceUrl": sra_aws_uri(run), "outputPath": str(r2_path), "records": row["read_pairs_per_end"], "ids": [], "idsStored": False, "source": "existing_aws_sra"},
        ]

    aws = command_path("aws") or "/opt/diana-aws/bin/aws"
    if not Path(aws).exists():
        raise RuntimeError("PHASE3_WGS_SOURCE_MODE=aws_sra requires the AWS CLI.")
    fasterq = command_path("fasterq-dump")
    if not fasterq:
        raise RuntimeError("PHASE3_WGS_SOURCE_MODE=aws_sra requires fasterq-dump from sra-tools.")
    write_aws_s3_transfer_config(S3_MAX_CONCURRENT_REQUESTS)
    sra_dir = path_from_root(f"{SMOKE_ROOT}/sra")
    tmp_dir = path_from_root(f"{SMOKE_ROOT}/tmp/{run}")
    ensure_dir(sra_dir)
    ensure_dir(tmp_dir)
    sra_path = sra_dir / f"{run}.sra"
    if not sra_path.exists() or sra_path.stat().st_size == 0:
        download_aws_sra_object_with_ranges(aws, run, sra_path, S3_RANGE_CONCURRENCY, S3_RANGE_BYTES)

    for path in [r1_path, r2_path]:
        if path.exists():
            path.unlink()
    run_command(
        " ".join(
            [
                quote_shell_arg(fasterq),
                "--split-files",
                "--threads",
                str(max(1, threads)),
                "--outdir",
                quote_shell_arg(str(tmp_dir)),
                "--temp",
                quote_shell_arg(str(tmp_dir)),
                quote_shell_arg(str(sra_path)),
            ]
        ),
        f"{RESULTS_DIR}/logs/fasterq_dump.{run}.log",
    )
    produced_r1 = tmp_dir / f"{run}_1.fastq"
    produced_r2 = tmp_dir / f"{run}_2.fastq"
    if not produced_r1.exists() or not produced_r2.exists():
        raise RuntimeError(f"fasterq-dump did not produce split FASTQs for {run}.")
    gzip_threads = max(1, threads // 2)
    gzip_fastq(produced_r1, r1_path, gzip_threads)
    gzip_fastq(produced_r2, r2_path, gzip_threads)
    produced_r1.unlink()
    produced_r2.unlink()
    return [
        {"run": run, "read": "R1", "sourceUrl": sra_aws_uri(run), "outputPath": str(r1_path), "records": row["read_pairs_per_end"], "ids": [], "idsStored": False, "source": "aws_sra"},
        {"run": run, "read": "R2", "sourceUrl": sra_aws_uri(run), "outputPath": str(r2_path), "records": row["read_pairs_per_end"], "ids": [], "idsStored": False, "source": "aws_sra"},
    ]


def stream_fastq_subset(run: str, read: str, source_url: str, output_relative_path: str, expected_records: int) -> dict[str, Any]:
    output_path = path_from_root(output_relative_path)
    ensure_dir(output_path.parent)
    if output_path.exists() and output_path.stat().st_size > 0:
        return summarize_fastq(run, read, source_url, output_path, "existing", expected_records)

    request = urllib.request.Request(source_url)
    current: list[str] = []
    records = 0
    with urllib.request.urlopen(request, timeout=300) as response:
        with gzip.GzipFile(fileobj=response) as gzip_handle:
            with output_path.open("w", encoding="utf-8") as output:
                for raw_line in gzip_handle:
                    line = raw_line.decode("utf-8").rstrip("\n")
                    output.write(f"{line}\n")
                    current.append(line)
                    if len(current) != 4:
                        continue
                    records += 1
                    validate_fastq_record(current, f"{run} {read}", records)
                    current = []
                    if records >= expected_records:
                        break

    return summarize_fastq(run, read, source_url, output_path, "streamed", expected_records)


def assert_paired(r1: dict[str, Any], r2: dict[str, Any]) -> None:
    if r1["records"] != r2["records"]:
        raise RuntimeError(f"{r1['run']} R1/R2 record-count mismatch")
    if not r1.get("idsStored") or not r2.get("idsStored"):
        return
    for index, (left, right) in enumerate(zip(r1["ids"], r2["ids"])):
        if left != right:
            raise RuntimeError(f"{r1['run']} R1/R2 read-id mismatch at {index}: {left} vs {right}")


def assert_paired_files(run: str, r1_path: str, r2_path: str, expected_records: int) -> dict[str, Any]:
    records = 0
    r1_current: list[str] = []
    r2_current: list[str] = []
    first_read_id = ""
    last_read_id = ""
    with open_fastq_text(path_from_root(r1_path)) as r1_handle:
        with open_fastq_text(path_from_root(r2_path)) as r2_handle:
            while True:
                r1_line = r1_handle.readline()
                r2_line = r2_handle.readline()
                if not r1_line and not r2_line:
                    break
                if not r1_line or not r2_line:
                    raise RuntimeError(f"{run} R1/R2 ended at different positions during paired validation.")
                r1_current.append(r1_line.rstrip("\n"))
                r2_current.append(r2_line.rstrip("\n"))
                if len(r1_current) != 4:
                    continue
                records += 1
                r1_record = validate_fastq_record(r1_current, f"{run} R1 pairing", records)
                r2_record = validate_fastq_record(r2_current, f"{run} R2 pairing", records)
                if r1_record["id"] != r2_record["id"]:
                    raise RuntimeError(f"{run} R1/R2 read-id mismatch at {records}: {r1_record['id']} vs {r2_record['id']}")
                first_read_id = first_read_id or r1_record["id"]
                last_read_id = r1_record["id"]
                r1_current = []
                r2_current = []
    if r1_current or r2_current:
        raise RuntimeError(f"{run} R1/R2 ended mid-record during paired validation.")
    if records != expected_records:
        raise RuntimeError(f"{run} paired validation saw {records} records; expected {expected_records}")
    return {
        "run": run,
        "records": records,
        "firstReadId": first_read_id,
        "lastReadId": last_read_id,
        "pairedIdCheck": "passed",
    }


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))

    raw_panel = parse_csv(read_text(path_from_root("manifests/raw_representative_panel.csv")))
    selected = sorted([row for row in raw_panel if row["pair_id"] == PAIR_ID], key=lambda row: 0 if row["role"] == "tumor" else 1)
    if len(selected) != 2 or {row["role"] for row in selected} != {"tumor", "normal"}:
        raise RuntimeError(f"Expected tumor and normal raw panel rows for {PAIR_ID}.")

    references = parse_csv(read_text(path_from_root("manifests/full_reference_smoke_references.csv")))
    reference = next((row for row in references if row["reference_id"] == "ucsc_hg38_analysis_set_full"), None)
    if not reference:
        raise RuntimeError("Expected ucsc_hg38_analysis_set_full in manifests/full_reference_smoke_references.csv.")
    for relative_path in [reference["fasta_path"], reference["fasta_fai_path"], reference["interval_bed_path"]]:
        if not path_from_root(relative_path).exists():
            raise RuntimeError(f"Required Phase 3 WGS reference asset is missing: {relative_path}")

    full_wes_rows = (
        parse_csv(read_text(path_from_root("manifests/full_wes_benchmark_samplesheet.csv")))
        if path_from_root("manifests/full_wes_benchmark_samplesheet.csv").exists()
        else []
    )
    full_wes_resource = full_wes_rows[0] if full_wes_rows else {}
    java_path = find_java(full_wes_resource.get("java_path", ""))
    gatk_jar = full_wes_resource.get("gatk_jar_path") or "data/raw/tools/gatk/gatk-4.6.2.0/gatk-package-4.6.2.0-local.jar"
    if not path_from_root(gatk_jar).exists():
        raise RuntimeError(f"GATK jar is missing: {gatk_jar}. Run fetch:production-somatic or fetch:full-wes first.")

    truth_snv_path = f"{SEQC2_TRUTH_ROOT}/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz"
    truth_indel_path = f"{SEQC2_TRUTH_ROOT}/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz"
    truth_high_confidence_bed_path = f"{SEQC2_TRUTH_ROOT}/High-Confidence_Regions_v1.2.bed"
    for relative_path in [truth_snv_path, truth_indel_path, truth_high_confidence_bed_path]:
        if not path_from_root(relative_path).exists():
            raise RuntimeError(f"SEQC2 truth asset is missing: {relative_path}. Run fetch:production-somatic first.")

    sample_rows: list[dict[str, Any]] = []
    for row in selected:
        sample_name = "HCC1395" if row["role"] == "tumor" else "HCC1395BL"
        row_read_pairs = expected_read_pairs(row)
        row_read_label = read_count_label(row_read_pairs)
        sample_rows.append(
            {
                "pair_id": row["pair_id"],
                "patient": "HCC1395",
                "sample": sample_name,
                "role": row["role"],
                "status": "tumor" if row["role"] == "tumor" else "matched_normal",
                "run_accession": row["run"],
                "assay": row["assay"],
                "library_strategy": row["library_strategy"],
                "library_layout": row["library_layout"],
                "platform": row["platform"],
                "model": row["model"],
                "source_read_pairs": row["spots"],
                "source_bases": row["bases"],
                "source_fastq_1": row["fastq_1_url"],
                "source_fastq_2": row["fastq_2_url"],
                "source_fastq_1_md5": row["fastq_1_md5"],
                "source_fastq_2_md5": row["fastq_2_md5"],
                "source_fastq_1_bytes": row["fastq_1_bytes"],
                "source_fastq_2_bytes": row["fastq_2_bytes"],
                "read_pairs_per_end": row_read_pairs,
                "fastq_1": f"{SMOKE_ROOT}/fastq/{row['run']}_R1.{row_read_label}.fastq.gz"
                if READ_PAIRS_LIMIT is None
                else f"{SMOKE_ROOT}/fastq/{row['run']}_R1.{row_read_label}.fastq",
                "fastq_2": f"{SMOKE_ROOT}/fastq/{row['run']}_R2.{row_read_label}.fastq.gz"
                if READ_PAIRS_LIMIT is None
                else f"{SMOKE_ROOT}/fastq/{row['run']}_R2.{row_read_label}.fastq",
                "reference_id": reference["reference_id"],
                "assembly": reference["assembly"],
                "genome_build": reference["genome_build"],
                "reference_path": reference["fasta_path"],
                "reference_fai_path": reference["fasta_fai_path"],
                "reference_dict_path": reference_dict_path(reference["fasta_path"]),
                "reference_sha256": reference["fasta_sha256"],
                "brca_interval_bed_path": reference["interval_bed_path"],
                "brca_interval_regions": reference["interval_regions"],
                "brca_interval_genes": reference["interval_genes"],
                "truth_snv_vcf_path": truth_snv_path,
                "truth_indel_vcf_path": truth_indel_path,
                "truth_high_confidence_bed_path": truth_high_confidence_bed_path,
                "gatk_jar_path": gatk_jar,
                "java_path": java_path,
                "mutect2_panel_of_normals_path": full_wes_resource.get("mutect2_panel_of_normals_path", ""),
                "production_caller": "GATK Mutect2 + FilterMutectCalls",
                "read_group_id": f"{row['run']}.{row['role']}.phase3wgs",
                "read_group_sample": sample_name,
                "read_group_library": row["run"],
                "read_group_platform": "ILLUMINA",
                "read_group_platform_unit": row["run"],
                "output_bam": f"{SMOKE_ROOT}/{reference['reference_id']}/{row_read_label}/bam/{row['run']}.{row['role']}.bam",
                "output_bai": f"{SMOKE_ROOT}/{reference['reference_id']}/{row_read_label}/bam/{row['run']}.{row['role']}.bam.bai",
                "caller_interval_strategy": "covered SEQC2 WGS truth loci from tumor and normal full-source BAM depth, fallback to mapped-read intervals if needed",
                "cnv_strategy": "samtools bedcov over fixed-width standard-contig bins with tumor/normal log2 coverage ratios",
                "sv_strategy": "samtools split-read, supplementary-read, discordant-pair, and interchromosomal-pair evidence counts",
                "signature_strategy": "local SBS96 mutation matrix from actual filtered WGS VCF records; signature classification deferred unless mutation count is sufficient",
                "caveat": "Phase 3 WGS uses real public WGS FASTQs from the full SEQC2/HCC1395 HiSeq X pair. Full-source validation is the acceptance gate; bounded subsets are only optional developer checks.",
            }
        )

    fastq_stats: list[dict[str, Any]]
    if READ_PAIRS_LIMIT is None and SOURCE_MODE == "aws_sra":
        with ThreadPoolExecutor(max_workers=min(FETCH_CONCURRENCY, len(sample_rows))) as pool:
            nested_stats = list(pool.map(lambda row: download_aws_sra_run(row, SRA_THREADS), sample_rows))
        download_stats = [stat for run_stats in nested_stats for stat in run_stats]
        fastq_stats = []
        paired_stats = {}
        source_by_run_read = {(stat["run"], stat["read"]): stat["source"] for stat in download_stats}

        def summarize_full_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            source = "/".join(
                [
                    str(source_by_run_read.get((row["run_accession"], "R1"), "existing")),
                    str(source_by_run_read.get((row["run_accession"], "R2"), "existing")),
                ]
            )
            return summarize_paired_fastqs(row, source)

        with ThreadPoolExecutor(max_workers=min(FETCH_CONCURRENCY, len(sample_rows))) as pool:
            paired_results = list(pool.map(summarize_full_row, sample_rows))
        for r1_summary, r2_summary, paired_summary in paired_results:
            fastq_stats.extend([r1_summary, r2_summary])
            paired_stats[r1_summary["run"]] = paired_summary
    elif READ_PAIRS_LIMIT is None:
        full_tasks: list[tuple[str, str, str, str, int, int, str]] = []
        for row in sample_rows:
            full_tasks.append(
                (
                    row["run_accession"],
                    "R1",
                    row["source_fastq_1"],
                    row["fastq_1"],
                    int(row["read_pairs_per_end"]),
                    int(row["source_fastq_1_bytes"]),
                    row["source_fastq_1_md5"],
                )
            )
            full_tasks.append(
                (
                    row["run_accession"],
                    "R2",
                    row["source_fastq_2"],
                    row["fastq_2"],
                    int(row["read_pairs_per_end"]),
                    int(row["source_fastq_2_bytes"]),
                    row["source_fastq_2_md5"],
                )
            )
        with ThreadPoolExecutor(max_workers=min(FETCH_CONCURRENCY, len(full_tasks))) as pool:
            download_stats = list(pool.map(download_full_fastq_without_summary, full_tasks))
        fastq_stats = []
        paired_stats: dict[str, dict[str, Any]] = {}
        source_by_run_read = {(stat["run"], stat["read"]): stat["source"] for stat in download_stats}

        def summarize_full_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            source = "/".join(
                [
                    str(source_by_run_read.get((row["run_accession"], "R1"), "existing")),
                    str(source_by_run_read.get((row["run_accession"], "R2"), "existing")),
                ]
            )
            return summarize_paired_fastqs(row, source)

        with ThreadPoolExecutor(max_workers=min(FETCH_CONCURRENCY, len(sample_rows))) as pool:
            paired_results = list(pool.map(summarize_full_row, sample_rows))
        for r1_summary, r2_summary, paired_summary in paired_results:
            fastq_stats.extend([r1_summary, r2_summary])
            paired_stats[r1_summary["run"]] = paired_summary
    else:
        subset_tasks: list[tuple[str, str, str, str, int]] = []
        for row in sample_rows:
            subset_tasks.append((row["run_accession"], "R1", row["source_fastq_1"], row["fastq_1"], int(row["read_pairs_per_end"])))
            subset_tasks.append((row["run_accession"], "R2", row["source_fastq_2"], row["fastq_2"], int(row["read_pairs_per_end"])))
        with ThreadPoolExecutor(max_workers=min(FETCH_CONCURRENCY, len(subset_tasks))) as pool:
            fastq_stats = list(pool.map(lambda task: stream_fastq_subset(*task), subset_tasks))

        paired_stats = {}
        for row in sample_rows:
            r1 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R1")
            r2 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R2")
            assert_paired(r1, r2)

    fastq_rows: list[dict[str, Any]] = []
    for row in sample_rows:
        r1 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R1")
        r2 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R2")
        fastq_rows.append(
            {
                "pair_id": row["pair_id"],
                "sample": row["sample"],
                "role": row["role"],
                "run_accession": row["run_accession"],
                "assay": row["assay"],
                "source_read_pairs": row["source_read_pairs"],
                "source_read_pairs_available": row["source_read_pairs"],
                "reads_per_end": r1["records"],
                "read_scope": "full_source_fastq" if READ_PAIRS_LIMIT is None else "bounded_public_fastq_subset",
                "local_fastq_1": row["fastq_1"],
                "local_fastq_2": row["fastq_2"],
                "compressed_fastq_1_bytes": path_from_root(row["fastq_1"]).stat().st_size if row["fastq_1"].endswith(".gz") else "",
                "compressed_fastq_2_bytes": path_from_root(row["fastq_2"]).stat().st_size if row["fastq_2"].endswith(".gz") else "",
                "r1_mean_length": round_value(r1["meanLength"], 2),
                "r2_mean_length": round_value(r2["meanLength"], 2),
                "r1_gc_fraction": round_value(r1["gcFraction"], 4),
                "r2_gc_fraction": round_value(r2["gcFraction"], 4),
                "r1_n_fraction": round_value(r1["nFraction"], 6),
                "r2_n_fraction": round_value(r2["nFraction"], 6),
                "first_read_id": r1["firstReadId"],
                "last_read_id": r1["lastReadId"],
                "paired_id_check": paired_stats.get(row["run_accession"], {}).get("pairedIdCheck", "passed"),
                "fetch_state": f"{r1['source']}/{r2['source']}",
                "caveat": "Real WGS FASTQ validation from the public SEQC2/HCC1395 source pair. Full-source validation checks complete compressed FASTQs, expected MD5/bytes, FASTQ records, and paired read IDs.",
            }
        )

    write_csv(path_from_root("manifests/phase3_wgs_smoke_samplesheet.csv"), sample_rows)
    write_csv(path_from_root(f"{RESULTS_DIR}/fastq_summary.csv"), fastq_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/fastq_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "passed",
            "pairId": PAIR_ID,
            "readRequest": READS_REQUEST,
            "readPairsMode": "full" if READ_PAIRS_LIMIT is None else "bounded",
            "fetchConcurrency": FETCH_CONCURRENCY,
            "sourceMode": SOURCE_MODE,
            "rows": fastq_rows,
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/asset_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "ready",
            "phase": "3",
            "pairId": PAIR_ID,
            "readRequest": READS_REQUEST,
            "readPairsMode": "full" if READ_PAIRS_LIMIT is None else "bounded",
            "sourceMode": SOURCE_MODE,
            "sampleRows": len(sample_rows),
            "source": "SEQC2/HCC1395 public HiSeq X Ten WGS tumor-normal FASTQ pair",
            "reference": {
                "referenceId": reference["reference_id"],
                "assembly": reference["assembly"],
                "genomeBuild": reference["genome_build"],
                "fastaPath": reference["fasta_path"],
                "faiPath": reference["fasta_fai_path"],
                "dictPath": reference_dict_path(reference["fasta_path"]),
            },
            "gatk": {"jarPath": gatk_jar, "javaPath": java_path},
            "seqc2Truth": {
                "snvVcfPath": truth_snv_path,
                "indelVcfPath": truth_indel_path,
                "highConfidenceBedPath": truth_high_confidence_bed_path,
            },
            "parallelism": {
                "fetchConcurrency": FETCH_CONCURRENCY,
                "note": "FASTQ end streams can be fetched concurrently; alignment/runtime thread controls live in validate:phase3-wgs.",
            },
            "completionModes": {
                "default": "Full-source public WGS validation.",
                "bounded_developer_check": "Set PHASE3_WGS_READS to an integer only for developer plumbing checks; bounded mode does not satisfy the Phase 3 acceptance gate.",
            },
            "boundary": "Full-source runs prepare complete SEQC2/HCC1395 public WGS FASTQs for Phase 3 validation. Bounded subsets are optional developer checks and are not accepted as completed orthogonal validation.",
        },
    )
    write_text(
        path_from_root(f"{RESULTS_DIR}/README.md"),
        f"""# Phase 3 WGS Validation Assets

Status: **ready**.

Representative pair: `{PAIR_ID}`

Read request: `{READS_REQUEST}`

This stage streams real reads from the full public SEQC2/HCC1395 HiSeq X Ten WGS tumor-normal FASTQ pair. The default is full-source validation. Set `PHASE3_WGS_READS` to an integer only for bounded developer plumbing checks.

Boundary: this validates WGS-capable mechanics on full-source public data. It is not a clinical HRD result.
""",
    )
    mode_label = "full source FASTQs" if READ_PAIRS_LIMIT is None else f"{READ_PAIRS_LIMIT} read pairs/end developer subset"
    print(f"Phase 3 WGS validation assets ready: {len(sample_rows)} samples, {mode_label}.")


if __name__ == "__main__":
    main()
