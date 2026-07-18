from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Protocol, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent, read_json, round_value, write_csv
from .render_phase3_fast_input_manifest import HEX64, ManifestError, normalize_method_parameters
from .safe_json_output import require_safe_output_path

DEFAULT_INPUT = "manifests/phase3_wgs_fast/cnv_evidence_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/cnv_evidence_receipt.json"

COVERAGE_BIN_COLUMNS = (
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
)
SUMMARY_COLUMNS = (
    "status",
    "tool",
    "coverage_cnv_mode",
    "bin_size",
    "bin_count",
    "median_log2_tumor_normal",
    "relative_gain_bins",
    "relative_loss_bins",
    "output_bins",
    "scarhrd_input_status",
    "real_output_status",
    "caveat",
)
MATERIALIZED_OUTPUTS = ("combined_bedcov", "coverage_bins", "summary_csv", "summary_json")


class BedcovRunner(Protocol):
    def run(self, argv: Sequence[str], *, stdout_path: Path) -> None: ...


class SubprocessBedcovRunner:
    def run(self, argv: Sequence[str], *, stdout_path: Path) -> None:
        ensure_parent(stdout_path)
        temporary = stdout_path.with_name(f".{stdout_path.name}.tmp")
        temporary.unlink(missing_ok=True)
        try:
            with temporary.open("wb") as handle:
                subprocess.check_call(list(argv), stdout=handle)
            temporary.replace(stdout_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_list(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{label} must be a non-empty list")
    return [_require_mapping(row, f"{label} row") for row in value]


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    return value


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} must be 64 hex characters")
    return value.lower()


def _require_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ManifestError(f"{label} must be an integer") from error
    if parsed < 0:
        raise ManifestError(f"{label} must be non-negative")
    return parsed


def _require_absolute_path(value: Any, label: str) -> Path:
    path = Path(_require_string(value, label))
    if not path.is_absolute():
        raise ManifestError(f"{label} must be an absolute path")
    return path


def _input_bam_path(plan: Mapping[str, Any], role: str) -> str:
    inputs = _require_mapping(plan.get("inputs"), "inputs")
    role_inputs = _require_mapping(inputs.get(role), f"inputs.{role}")
    bam = _require_mapping(role_inputs.get("bam"), f"inputs.{role}.bam")
    return str(_require_absolute_path(bam.get("local_path"), f"inputs.{role}.bam.local_path"))


def _require_argv(value: Any, expected: list[str], label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{label} argv must be a non-empty string list")
    argv = list(value)
    if argv != expected:
        raise ManifestError(f"{label} argv must match the planned samtools bedcov command")
    return argv


def _require_output_paths(plan: Mapping[str, Any]) -> dict[str, Path]:
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    paths = {
        key: _require_absolute_path(outputs.get(key), f"outputs.{key}")
        for key in MATERIALIZED_OUTPUTS
    }
    if len(set(paths.values())) != len(paths):
        raise ManifestError("CNV evidence materialized output paths must be unique")
    return paths


def _planned_shards(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    runtime = _require_mapping(plan.get("runtime"), "runtime")
    bin_size = _require_positive_int(runtime.get("bin_size"), "runtime.bin_size")
    tumor_bam = _input_bam_path(plan, "tumor")
    normal_bam = _input_bam_path(plan, "normal")
    commands = _require_mapping(
        _require_mapping(plan.get("commands"), "commands").get("bedcov_by_contig"),
        "commands.bedcov_by_contig",
    )

    shard_rows = _require_list(plan.get("interval_shards"), "interval_shards")
    shard_contigs = [
        _require_string(row.get("contig"), f"interval_shards[{index}].contig")
        for index, row in enumerate(shard_rows, start=1)
    ]
    if len(set(shard_contigs)) != len(shard_contigs):
        duplicate = next(contig for contig in shard_contigs if shard_contigs.count(contig) > 1)
        raise ManifestError(f"interval_shards contains duplicate contig {duplicate}")
    if set(commands) != set(shard_contigs):
        raise ManifestError("commands.bedcov_by_contig must contain exactly one command per interval shard")

    shards: list[dict[str, Any]] = []
    for index, row in enumerate(shard_rows, start=1):
        contig = shard_contigs[index - 1]
        length = _require_positive_int(row.get("length"), f"interval_shards[{index}].length")
        row_bin_size = _require_positive_int(row.get("bin_size"), f"interval_shards[{index}].bin_size")
        if row_bin_size != bin_size:
            raise ManifestError(f"interval_shards[{index}].bin_size must match runtime.bin_size")
        expected_bin_count = (length + bin_size - 1) // bin_size
        bin_count = _require_positive_int(row.get("bin_count"), f"interval_shards[{index}].bin_count")
        if bin_count != expected_bin_count:
            raise ManifestError(f"interval_shards[{index}].bin_count must match contig length and bin size")

        intervals_bed = _require_absolute_path(
            row.get("intervals_bed"),
            f"interval_shards[{index}].intervals_bed",
        )
        bedcov_tsv = _require_absolute_path(row.get("bedcov_tsv"), f"interval_shards[{index}].bedcov_tsv")
        command = _require_mapping(commands.get(contig), f"commands.bedcov_by_contig.{contig}")
        argv = _require_argv(
            command.get("argv"),
            ["samtools", "bedcov", str(intervals_bed), tumor_bam, normal_bam],
            f"commands.bedcov_by_contig.{contig}",
        )
        stdout_path = _require_absolute_path(
            command.get("stdout_path"),
            f"commands.bedcov_by_contig.{contig}.stdout_path",
        )
        if stdout_path != bedcov_tsv:
            raise ManifestError(
                f"commands.bedcov_by_contig.{contig}.stdout_path must match interval_shards bedcov_tsv"
            )
        shards.append(
            {
                "argv": argv,
                "bedcov_tsv": bedcov_tsv,
                "bin_count": bin_count,
                "bin_size": bin_size,
                "contig": contig,
                "intervals_bed": intervals_bed,
                "length": length,
            }
        )

    paths = {path for shard in shards for path in (shard["intervals_bed"], shard["bedcov_tsv"])}
    if len(paths) != len(shards) * 2:
        raise ManifestError("CNV evidence shard paths must be unique")
    return shards


def _validate_plan(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    if plan.get("manifest_type") != "phase3_wgs_fast_cnv_evidence_plan":
        raise ManifestError("CNV evidence plan manifest_type must be phase3_wgs_fast_cnv_evidence_plan")
    if plan.get("status") != "planned":
        raise ManifestError("CNV evidence plan status must be planned")
    if _require_mapping(plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("CNV evidence receipt authorized_hrd_state must remain no_call")
    return _planned_shards(plan)


def _require_safe_output_path(path: Path) -> None:
    if path.is_symlink():
        raise ManifestError(f"CNV evidence output path may not be a symlink: {path}")

    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        next_parent = parent.parent
        if next_parent == parent:
            raise ManifestError(f"CNV evidence output parent does not exist: {path.parent}")
        parent = next_parent

    if parent.is_symlink():
        raise ManifestError(f"CNV evidence output parent may not be a symlink: {parent}")
    if not parent.is_dir():
        raise ManifestError(f"CNV evidence output parent is not a directory: {parent}")


def _prepare_outputs(output_paths: Mapping[str, Path], shards: Sequence[Mapping[str, Any]]) -> None:
    paths = {
        *output_paths.values(),
        *(shard["intervals_bed"] for shard in shards),
        *(shard["bedcov_tsv"] for shard in shards),
    }
    if len(paths) != len(output_paths) + 2 * len(shards):
        raise ManifestError("CNV evidence output paths must be unique")

    for path in paths:
        _require_safe_output_path(path)
        if path.exists() and not path.is_file():
            raise ManifestError(f"CNV evidence output path already exists and is not a file: {path}")
        ensure_parent(path)
        path.unlink(missing_ok=True)


def _write_intervals(shard: Mapping[str, Any]) -> None:
    length = int(shard["length"])
    bin_size = int(shard["bin_size"])
    lines = [
        f"{shard['contig']}\t{start}\t{min(length, start + bin_size)}"
        for start in range(0, length, bin_size)
    ]
    if len(lines) != int(shard["bin_count"]):
        raise ManifestError(f"{shard['contig']} generated interval count must match the plan")
    Path(shard["intervals_bed"]).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_bedcov_commands(
    shards: Sequence[Mapping[str, Any]],
    runner: BedcovRunner,
    *,
    max_workers: int,
) -> None:
    with ThreadPoolExecutor(max_workers=min(max_workers, len(shards))) as executor:
        futures = [
            executor.submit(runner.run, shard["argv"], stdout_path=shard["bedcov_tsv"])
            for shard in shards
        ]
        for future in futures:
            future.result()


def _coverage_class(log2_ratio: float) -> str:
    if log2_ratio >= 0.5:
        return "relative_gain"
    if log2_ratio <= -0.5:
        return "relative_loss"
    return "neutral_or_low_signal"


def _parse_bedcov_rows(shards: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    combined_lines: list[str] = []
    for shard in shards:
        path = Path(shard["bedcov_tsv"])
        if not path.is_file():
            raise ManifestError(f"{shard['contig']} bedcov output must exist after execution: {path}")
        shard_count = 0
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                raise ManifestError(f"{path} line {line_number} must contain 3 BED columns and 2 depth sums")
            contig, start_text, end_text, tumor_sum_text, normal_sum_text = fields
            if contig != shard["contig"]:
                raise ManifestError(f"{path} line {line_number} contig must be {shard['contig']}")
            start = _require_nonnegative_int(start_text, f"{path} line {line_number} start")
            end = _require_nonnegative_int(end_text, f"{path} line {line_number} end")
            if end <= start:
                raise ManifestError(f"{path} line {line_number} end must be greater than start")
            tumor_sum = _require_nonnegative_int(tumor_sum_text, f"{path} line {line_number} tumor sum")
            normal_sum = _require_nonnegative_int(normal_sum_text, f"{path} line {line_number} normal sum")
            length = end - start
            tumor_depth = tumor_sum / length
            normal_depth = normal_sum / length
            log2_ratio = math.log2((tumor_depth + 0.0001) / (normal_depth + 0.0001))
            combined_lines.append("\t".join(fields))
            rows.append(
                {
                    "contig": contig,
                    "start": start,
                    "end": end,
                    "length": length,
                    "tumor_depth_sum": tumor_sum,
                    "normal_depth_sum": normal_sum,
                    "tumor_mean_depth": round_value(tumor_depth, 6),
                    "normal_mean_depth": round_value(normal_depth, 6),
                    "log2_tumor_normal": round_value(log2_ratio, 4),
                    "coverage_class": _coverage_class(log2_ratio),
                }
            )
            shard_count += 1
        if shard_count != shard["bin_count"]:
            raise ManifestError(f"{shard['contig']} bedcov output row count must match the interval shard bin_count")
    if not rows:
        raise ManifestError("CNV evidence bedcov execution did not produce any bins")
    return rows, combined_lines


def _summary_row(
    output_paths: Mapping[str, Path],
    plan: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    log2_values = [float(row["log2_tumor_normal"]) for row in rows if row["log2_tumor_normal"] != ""]
    return {
        "status": "completed",
        "tool": "samtools bedcov",
        "coverage_cnv_mode": "full_depth_bedcov",
        "bin_size": _require_positive_int(
            _require_mapping(plan.get("runtime"), "runtime").get("bin_size"),
            "runtime.bin_size",
        ),
        "bin_count": len(rows),
        "median_log2_tumor_normal": round_value(median(log2_values), 4),
        "relative_gain_bins": sum(1 for row in rows if row["coverage_class"] == "relative_gain"),
        "relative_loss_bins": sum(1 for row in rows if row["coverage_class"] == "relative_loss"),
        "output_bins": str(output_paths["coverage_bins"]),
        "scarhrd_input_status": "not_assessable_without_allele_specific_segments",
        "real_output_status": "real_coverage_cnv_bin_output",
        "caveat": (
            "Real WGS BAM coverage-derived CNV bins from samtools bedcov. "
            "This validates CNV feature plumbing but is not allele-specific segmentation or scarHRD."
        ),
    }


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_materialized(path: Path, key: str) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"{key} must exist after CNV evidence execution: {path}")
    bytes_ = path.stat().st_size
    if bytes_ <= 0:
        raise ManifestError(f"{key} must be non-empty after CNV evidence execution: {path}")
    return {
        "local_path": str(path),
        "bytes": bytes_,
        "sha256": _sha256_path(path),
    }


def _materialized_outputs(
    output_paths: Mapping[str, Path],
    shards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        **{
            key: _hash_materialized(path, key)
            for key, path in output_paths.items()
        },
        "interval_shards": {
            str(shard["contig"]): {
                "intervals_bed": _hash_materialized(
                    Path(shard["intervals_bed"]),
                    f"{shard['contig']} intervals_bed",
                ),
                "bedcov_tsv": _hash_materialized(
                    Path(shard["bedcov_tsv"]),
                    f"{shard['contig']} bedcov_tsv",
                ),
            }
            for shard in shards
        },
    }


def run_phase3_fast_cnv_evidence(
    plan: Mapping[str, Any],
    *,
    runner: BedcovRunner,
    cnv_evidence_plan_sha256: str,
) -> dict[str, Any]:
    plan_sha = _require_hex(cnv_evidence_plan_sha256, "cnv_evidence_plan_sha256")
    shards = _validate_plan(plan)
    output_paths = _require_output_paths(plan)
    _prepare_outputs(output_paths, shards)
    for shard in shards:
        _write_intervals(shard)
    _run_bedcov_commands(
        shards,
        runner,
        max_workers=_require_positive_int(
            _require_mapping(plan.get("runtime"), "runtime").get("bedcov_workers"),
            "runtime.bedcov_workers",
        ),
    )
    rows, combined_lines = _parse_bedcov_rows(shards)
    summary = _summary_row(output_paths, plan, rows)

    output_paths["combined_bedcov"].write_text("\n".join(combined_lines) + "\n", encoding="utf-8")
    write_csv(output_paths["coverage_bins"], rows, COVERAGE_BIN_COLUMNS)
    write_csv(output_paths["summary_csv"], [summary], SUMMARY_COLUMNS)
    output_paths["summary_json"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manifest_type": "phase3_wgs_fast_cnv_evidence_summary",
                "status": "completed",
                "coverage_cnv_mode": "full_depth_bedcov",
                "rows": [summary],
                "interpretation": {
                    "authorized_hrd_state": "no_call",
                    "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_cnv_evidence_receipt",
        "status": "completed",
        "workflow": dict(_require_mapping(plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(plan.get("run"), "run")),
        "runtime": dict(_require_mapping(plan.get("runtime"), "runtime")),
        "method_parameters": normalize_method_parameters(plan.get("method_parameters")),
        "source": {
            **dict(_require_mapping(plan.get("source"), "source")),
            "cnv_evidence_plan_sha256": plan_sha,
        },
        "inputs": dict(_require_mapping(plan.get("inputs"), "inputs")),
        "interval_shards": [
            {
                "contig": shard["contig"],
                "length": shard["length"],
                "bin_size": shard["bin_size"],
                "bin_count": shard["bin_count"],
                "intervals_bed": str(shard["intervals_bed"]),
                "bedcov_tsv": str(shard["bedcov_tsv"]),
            }
            for shard in shards
        ],
        "outputs": {key: str(path) for key, path in output_paths.items()},
        "materialized_outputs": _materialized_outputs(output_paths, shards),
        "commands": {
            str(shard["contig"]): {
                "argv": list(shard["argv"]),
                "stdout_path": str(shard["bedcov_tsv"]),
                "status": "completed",
            }
            for shard in shards
        },
        "interpretation": {
            "authorized_hrd_state": "no_call",
            "hrd_use": "coverage_cnv_evidence_not_allele_specific",
            "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
        },
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast CNV evidence receipt output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_receipt_from_environment(
    runner: BedcovRunner | None = None,
) -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT_OUTPUT", DEFAULT_OUTPUT))
    receipt = run_phase3_fast_cnv_evidence(
        read_json(input_path),
        runner=runner if runner is not None else SubprocessBedcovRunner(),
        cnv_evidence_plan_sha256=_sha256_path(input_path),
    )
    return receipt, output_path


def main() -> None:
    receipt, output = load_receipt_from_environment()
    write_receipt(output, receipt)
    print(f"Phase 3 WGS fast CNV evidence receipt written: {output}")


if __name__ == "__main__":
    main()
