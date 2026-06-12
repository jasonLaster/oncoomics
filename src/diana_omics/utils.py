from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, TypeVar, Union, cast

from .paths import path_from_root

T = TypeVar("T")


def ensure_dir(path: Union[str, Path]) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Union[str, Path]) -> None:
    ensure_dir(Path(path).parent)


def read_text(path: Union[str, Path]) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Union[str, Path], value: str) -> None:
    ensure_parent(path)
    Path(path).write_text(value if value.endswith("\n") else f"{value}\n", encoding="utf-8")


def read_json(path: Union[str, Path]) -> Any:
    return json.loads(read_text(path))


def write_json(path: Union[str, Path], value: Any) -> None:
    write_text(path, json.dumps(value, indent=2) + "\n")


def parse_csv(text: str) -> list[dict[str, str]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def parse_delimited(text: str, delimiter: str = "\t") -> list[dict[str, str]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text), delimiter=delimiter)]


def write_csv(path: Union[str, Path], rows: Sequence[Mapping[str, Any]], columns: Optional[Sequence[str]] = None) -> None:
    resolved_columns = list(columns or dict.fromkeys(key for row in rows for key in row.keys()))
    ensure_parent(path)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=resolved_columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: "" if row.get(column) is None else row.get(column) for column in resolved_columns})


def fetch_text(url: str, method: str = "GET", timeout: int = 60, headers: Optional[Mapping[str, str]] = None) -> str:
    request = urllib.request.Request(url, method=method, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return cast(str, response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {url} returned {error.code}") from error


def fetch_json(url: str, method: str = "GET", body: Optional[Any] = None, timeout: int = 60) -> Any:
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {url} returned {error.code}") from error


def post_json(url: str, body: Any, timeout: int = 60) -> Any:
    return fetch_json(url, method="POST", body=body, timeout=timeout)


def group_by(rows: Iterable[T], key_fn: Callable[[T], str]) -> dict[str, list[T]]:
    groups: dict[str, list[T]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)
    return dict(groups)


def pivot_clinical(records: Iterable[Mapping[str, Any]], id_field: str) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for record in records:
        record_id = record.get(id_field)
        if not record_id:
            continue
        row = by_id.setdefault(str(record_id), {id_field: str(record_id)})
        row[str(record["clinicalAttributeId"])] = str(record.get("value", ""))
    return sorted(by_id.values(), key=lambda row: row.get(id_field, ""))


def to_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [value for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    return sum(clean) / len(clean) if clean else None


def standard_deviation(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [value for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    if len(clean) < 2:
        return None
    avg = sum(clean) / len(clean)
    return math.sqrt(sum((value - avg) ** 2 for value in clean) / (len(clean) - 1))


def quantile(values: Iterable[float], q: float) -> Optional[float]:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    pos = (len(clean) - 1) * q
    base = math.floor(pos)
    rest = pos - base
    if base + 1 >= len(clean):
        return clean[base]
    return clean[base] + rest * (clean[base + 1] - clean[base])


def round_value(value: Optional[float], digits: int = 4) -> Union[float, str]:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return ""
    return round(value, digits)


def sha256_file(relative_path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with path_from_root(relative_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(relative_path: Union[str, Path]) -> str:
    digest = hashlib.md5()
    with path_from_root(relative_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_path(tool: str) -> str:
    return shutil.which(tool) or ""


def file_non_empty(relative_path: Union[str, Path]) -> bool:
    path = path_from_root(relative_path)
    return path.is_file() and path.stat().st_size > 0


def existing_output_current(outputs: Sequence[Union[str, Path]], inputs: Sequence[Union[str, Path]]) -> bool:
    output_paths = [path_from_root(output) for output in outputs]
    input_paths = [path_from_root(input_path) for input_path in inputs if str(input_path)]
    if not output_paths or any(not output.exists() for output in output_paths):
        return False
    if not input_paths or any(not input_path.exists() for input_path in input_paths):
        return False
    newest_input = max(input_path.stat().st_mtime for input_path in input_paths)
    return all(output.stat().st_mtime >= newest_input for output in output_paths)


def run_command(command: str, log_path: Optional[str] = None, max_buffer: Optional[int] = None) -> str:
    heartbeat_seconds = int(os.environ.get("DIANA_OMICS_COMMAND_HEARTBEAT_SECONDS", "300"))
    started_at = time.monotonic()
    next_heartbeat = started_at + max(1, heartbeat_seconds)
    with tempfile.TemporaryDirectory(prefix="diana-omics-command-") as tmpdir:
        stdout_path = Path(tmpdir) / "stdout.txt"
        stderr_path = Path(tmpdir) / "stderr.txt"
        with stdout_path.open("w+", encoding="utf-8") as stdout_handle, stderr_path.open("w+", encoding="utf-8") as stderr_handle:
            process = subprocess.Popen(
                ["bash", "-lc", command],
                cwd=path_from_root(""),
                text=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
            )
            while True:
                exit_status = process.poll()
                if exit_status is not None:
                    break
                now = time.monotonic()
                if heartbeat_seconds > 0 and now >= next_heartbeat:
                    elapsed = int(now - started_at)
                    log_suffix = f" log={log_path}" if log_path else ""
                    print(f"[heartbeat] command still running elapsed={elapsed}s{log_suffix}: {command}", flush=True)
                    next_heartbeat = now + heartbeat_seconds
                time.sleep(1)

            stdout_handle.seek(0)
            stderr_handle.seek(0)
            stdout = stdout_handle.read()
            stderr = stderr_handle.read()
    if max_buffer is not None and max_buffer > 0:
        stdout = stdout[-max_buffer:]
        stderr = stderr[-max_buffer:]
    if log_path:
        write_text(
            path_from_root(log_path),
            "\n".join(
                [
                    f"$ {command}",
                    "",
                    "## stdout",
                    stdout or "",
                    "",
                    "## stderr",
                    stderr or "",
                    "",
                    f"exit_status={exit_status}",
                ]
            ),
        )
    if exit_status != 0:
        suffix = f". See {log_path}." if log_path else f"\n{stderr}"
        raise RuntimeError(f"Command failed ({exit_status}): {command}{suffix}")
    return stdout


def run_commands_parallel(commands: Sequence[tuple[str, str]], workers: int) -> list[str]:
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda item: run_command(item[0], item[1]), commands))


def capture_command(command: str) -> str:
    return run_command(command).strip()


def capture_allow_empty(command: str) -> str:
    return run_command(command).strip()


def quote_shell_arg(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def normalize_read_id(header: str) -> str:
    return re.sub(r"/[12]$", "", header.lstrip("@").split()[0])


def validate_fastq_record(lines: Sequence[str], source: str, record_number: int) -> dict[str, str]:
    if len(lines) < 4:
        raise ValueError(f"{source} record {record_number} is incomplete")
    header, sequence, plus, quality = lines[:4]
    if not header.startswith("@"):
        raise ValueError(f"{source} record {record_number} does not start with @")
    if not plus.startswith("+"):
        raise ValueError(f"{source} record {record_number} plus line does not start with +")
    if len(sequence) != len(quality):
        raise ValueError(f"{source} record {record_number} sequence/quality length mismatch")
    return {"id": normalize_read_id(header), "sequence": sequence, "quality": quality}


def read_fastq(path: Union[str, Path]) -> list[dict[str, str]]:
    lines = read_text(path).rstrip("\n").splitlines()
    if len(lines) % 4 != 0:
        raise ValueError(f"{path} does not contain complete FASTQ records.")
    return [validate_fastq_record(lines[index : index + 4], str(path), index // 4 + 1) for index in range(0, len(lines), 4)]


def stream_gzip_text(url: str):
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=120) as response:
        with gzip.GzipFile(fileobj=response) as gzip_handle:
            for raw_line in gzip_handle:
                yield raw_line.decode("utf-8").rstrip("\n")


def iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def detect_cpu_count(default: int = 8) -> int:
    return os.cpu_count() or default


def quickcheck_bam(relative_bam: str) -> bool:
    path = path_from_root(relative_bam)
    if not path.exists():
        return False
    result = subprocess.run(
        ["samtools", "quickcheck", "-v", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return result.returncode == 0


def standard_contig(contig: str) -> bool:
    return re.match(r"^chr([1-9]|1[0-9]|2[0-2]|X|Y)$", contig) is not None


def median(values: Iterable[float]) -> Optional[float]:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    middle = len(clean) // 2
    if len(clean) % 2:
        return clean[middle]
    return (clean[middle - 1] + clean[middle]) / 2


def tool_version(tool: str) -> str:
    result = subprocess.run(
        ["bash", "-lc", f"{tool} 2>&1 | head -n 8"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return f"{result.stdout}{result.stderr}".strip()


def parse_bcftools_norm_summary(log_text: str) -> dict[str, int]:
    """Parse the ``Lines   total/split/.../skipped:	a/b/.../z`` summary that
    ``bcftools norm`` prints to stderr.

    The field set changed across bcftools versions (newer builds add
    ``joined``/``mismatch_removed``/``dup_removed``), so labels are zipped to their
    counts positionally rather than read by a fixed index. Returns an empty dict
    when no summary line is present (e.g. a cached run that skipped normalization).
    """
    for line in log_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("Lines") or ":" not in stripped:
            continue
        label_part, _, number_part = stripped.partition(":")
        tokens = label_part.split()
        if len(tokens) < 2:
            continue
        labels = tokens[-1].split("/")
        numbers = number_part.strip().split("/")
        if len(labels) != len(numbers):
            continue
        summary: dict[str, int] = {}
        for label, number in zip(labels, numbers):
            try:
                summary[label] = int(number)
            except ValueError:
                continue
        return summary
    return {}


def bcftools_norm_ref_mismatch_count(log_text: str) -> int:
    """Number of records ``bcftools norm`` dropped because their REF allele did not
    match the reference (i.e. records excluded by ``--check-ref x``).

    Reads ``mismatch_removed`` on modern bcftools; older builds fold these into
    ``skipped``, so fall back to that. Returns 0 when no summary is found.
    """
    summary = parse_bcftools_norm_summary(log_text)
    if "mismatch_removed" in summary:
        return summary["mismatch_removed"]
    return summary.get("skipped", 0)
