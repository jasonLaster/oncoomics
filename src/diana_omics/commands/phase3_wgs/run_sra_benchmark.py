from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ...paths import path_from_root
from ...utils import command_path, ensure_dir, write_text

RESULTS_DIR = "results/phase3_wgs_smoke"


def parse_matrix(
    matrix: str,
    default_strategy: str,
    default_concurrency: int,
    default_bytes: int,
    default_parts: int,
) -> list[dict[str, Any]]:
    if not matrix.strip():
        return [
            {
                "label": "single",
                "strategy": default_strategy,
                "bytes": default_bytes,
                "parts": max(1, default_parts),
                "concurrency": max(1, default_concurrency),
            }
        ]
    configs: list[dict[str, Any]] = []
    for raw_entry in matrix.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        pieces = entry.split(":")
        if len(pieces) not in {4, 5}:
            raise ValueError(f"Invalid sra_benchmark_matrix entry '{entry}'. Expected strategy:concurrency:bytes:parts[:label].")
        strategy, concurrency, bytes_text, parts_text = pieces[:4]
        label = pieces[4] if len(pieces) == 5 else f"{strategy}-c{concurrency}-p{parts_text}-b{bytes_text}"
        configs.append(
            {
                "label": label,
                "strategy": strategy,
                "bytes": int(bytes_text),
                "parts": max(1, int(parts_text)),
                "concurrency": max(1, int(concurrency)),
            }
        )
    if not configs:
        raise ValueError("sra_benchmark_matrix did not contain any benchmark configs.")
    return configs


def sra_key(run: str) -> str:
    return f"sra/{run}/{run}"


def range_for_part(part_index: int, requested_bytes: int) -> tuple[int, int, str]:
    start_byte = part_index * requested_bytes
    end_byte = start_byte + requested_bytes - 1
    return start_byte, end_byte, f"bytes={start_byte}-{end_byte}"


def run_aws_range(aws: str, bucket: str, run: str, part_index: int, requested_bytes: int) -> tuple[int, str, str]:
    start_byte, end_byte, byte_range = range_for_part(part_index, requested_bytes)
    key = sra_key(run)
    target = Path("/tmp") / f"{run}.{start_byte}-{end_byte}.sra.part"
    target.unlink(missing_ok=True)
    subprocess.run(
        [
            aws,
            "s3api",
            "get-object",
            "--no-sign-request",
            "--bucket",
            bucket,
            "--key",
            key,
            "--range",
            byte_range,
            str(target),
        ],
        check=True,
    )
    size = target.stat().st_size
    target.unlink(missing_ok=True)
    return size, byte_range, key


def run_s5cmd_cat(s5cmd: str, bucket: str, run: str, requested_bytes: int) -> tuple[int, str, str]:
    if not s5cmd:
        raise RuntimeError("s5cmd is required for s5cmd_cat benchmarks.")
    key = sra_key(run)
    object_uri = f"s3://{bucket}/{key}"
    count = max(1, (requested_bytes + (8 * 1024 * 1024) - 1) // (8 * 1024 * 1024))
    command = (
        f"set -eu; "
        f"{subprocess.list2cmdline([s5cmd, '--no-sign-request', 'cat', object_uri])} "
        f"| dd of=/dev/null bs=8M count={count} iflag=fullblock status=none"
    )
    subprocess.run(["bash", "-lc", command], check=True)
    return count * 8 * 1024 * 1024, f"stream-prefix:{requested_bytes}", key


def benchmark_part(aws: str, s5cmd: str, bucket: str, config: dict[str, Any], part: tuple[str, int]) -> dict[str, Any]:
    run, part_index = part
    started = time.monotonic()
    if config["strategy"] == "aws_s3api_range":
        size, byte_range, key = run_aws_range(aws, bucket, run, part_index, int(config["bytes"]))
    elif config["strategy"] == "s5cmd_cat":
        size, byte_range, key = run_s5cmd_cat(s5cmd, bucket, run, int(config["bytes"]))
    else:
        raise RuntimeError(f"Unsupported sra benchmark strategy: {config['strategy']}")
    elapsed = max(0.001, time.monotonic() - started)
    return {
        "label": config["label"],
        "strategy": config["strategy"],
        "run": run,
        "bucket": bucket,
        "key": key,
        "part": part_index,
        "range": byte_range,
        "bytes": size,
        "elapsedSeconds": round(elapsed, 3),
        "mbPerSecond": round(size / 1_000_000 / elapsed, 2),
    }


def summarize_rows(config: dict[str, Any], rows: list[dict[str, Any]], elapsed_seconds: float) -> dict[str, Any]:
    total_bytes = sum(int(row["bytes"]) for row in rows)
    elapsed = max(0.001, elapsed_seconds)
    return {
        "label": config["label"],
        "strategy": config["strategy"],
        "requestedBytesPerPart": config["bytes"],
        "partsPerRun": config["parts"],
        "concurrency": config["concurrency"],
        "totalBytes": total_bytes,
        "wallSeconds": round(elapsed, 3),
        "aggregateMbPerSecond": round(total_bytes / 1_000_000 / elapsed, 2),
    }


def resolve_aws_cli() -> str:
    aws = os.environ.get("AWS_CLI") or command_path("aws") or "/opt/diana-aws/bin/aws"
    if not Path(aws).exists():
        raise RuntimeError("AWS CLI is required for phase3_sra_benchmark.")
    return aws


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    aws = resolve_aws_cli()
    s5cmd = os.environ.get("S5CMD") or command_path("s5cmd")
    bucket = os.environ.get("BUCKET", os.environ.get("PHASE3_WGS_SRA_AWS_BUCKET", "sra-pub-run-odp"))
    bytes_requested = int(os.environ.get("BYTES", os.environ.get("SRA_BENCHMARK_BYTES", "1073741824")))
    parts_per_run = max(1, int(os.environ.get("PARTS", os.environ.get("SRA_BENCHMARK_PARTS", "1"))))
    runs = [
        run.strip()
        for run in os.environ.get("RUNS", os.environ.get("SRA_BENCHMARK_RUNS", "SRR7890824,SRR7890827")).split(",")
        if run.strip()
    ]
    concurrency = max(1, int(os.environ.get("CONCURRENCY", os.environ.get("PHASE3_WGS_FETCH_CONCURRENCY", "2"))))
    strategy = os.environ.get("STRATEGY", os.environ.get("SRA_BENCHMARK_STRATEGY", "aws_s3api_range"))
    matrix = os.environ.get("MATRIX", os.environ.get("SRA_BENCHMARK_MATRIX", "")).strip()

    summaries: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for config in parse_matrix(matrix, strategy, concurrency, bytes_requested, parts_per_run):
        print(
            f"[sra-benchmark] starting {config['label']} strategy={config['strategy']} "
            f"concurrency={config['concurrency']} bytes={config['bytes']} parts={config['parts']}",
            flush=True,
        )
        parts = [(run, part_index) for run in runs for part_index in range(int(config["parts"]))]
        started = time.monotonic()

        def run_part(part: tuple[str, int], current_config: dict[str, Any] = config) -> dict[str, Any]:
            return benchmark_part(aws, s5cmd, bucket, current_config, part)

        with ThreadPoolExecutor(max_workers=min(int(config["concurrency"]), len(parts))) as pool:
            rows = list(pool.map(run_part, parts))
        summary_row = summarize_rows(config, rows, time.monotonic() - started)
        summaries.append(summary_row)
        all_rows.extend(rows)
        print(f"[sra-benchmark] finished {config['label']} aggregateMbPerSecond={summary_row['aggregateMbPerSecond']}", flush=True)

    summary = {
        "sourceMode": "aws_sra",
        "bucket": bucket,
        "benchmarkMode": "matrix" if matrix else "single",
        "summaries": summaries,
        "runs": all_rows,
    }
    output_dir = path_from_root(RESULTS_DIR)
    write_text(output_dir / "sra_benchmark.json", json.dumps(summary, indent=2) + "\n")
    with (output_dir / "sra_benchmark.tsv").open("w", encoding="utf-8") as handle:
        handle.write("label\tstrategy\trun\tpart\trange\tbytes\telapsedSeconds\tmbPerSecond\n")
        for row in all_rows:
            handle.write(
                f"{row['label']}\t{row['strategy']}\t{row['run']}\t{row['part']}\t{row['range']}\t"
                f"{row['bytes']}\t{row['elapsedSeconds']}\t{row['mbPerSecond']}\n"
            )
    print(json.dumps(summary, indent=2))
