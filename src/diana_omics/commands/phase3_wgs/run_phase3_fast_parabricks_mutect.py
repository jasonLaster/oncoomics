from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError, normalize_method_parameters

DEFAULT_INPUT = "manifests/phase3_wgs_fast/parabricks_mutect_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"
EXPECTED_COMMANDS = ("prepon", "mutectcaller", "postpon")
MATERIALIZED_OUTPUTS = ("raw_vcf", "raw_vcf_stats", "pon_annotated_vcf", "f1r2_tar_gz")


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> None: ...


class SubprocessCommandRunner:
    def run(self, argv: Sequence[str]) -> None:
        subprocess.check_call(list(argv))


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    return value


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} must be 64 hex characters")
    return value.lower()


def _require_argv(value: Any, name: str, plan: Mapping[str, Any]) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{name} argv must be a non-empty string list")
    argv = list(value)
    if len(argv) < 2 or argv[0] != "pbrun" or argv[1] != name:
        raise ManifestError(f"{name} argv must start with pbrun {name}")
    _require_flags(argv, name, _expected_flag_values(plan, name))
    return argv


def _require_absolute_path(value: Any, label: str) -> Path:
    path = Path(_require_string(value, label))
    if not path.is_absolute():
        raise ManifestError(f"{label} must be an absolute path")
    return path


def _require_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{label} must be a positive integer")
    return value


def _require_input_path(inputs: Mapping[str, Any], key: str) -> str:
    return str(
        _require_absolute_path(
            _require_mapping(inputs.get(key), f"inputs.{key}").get("local_path"),
            f"inputs.{key}",
        )
    )


def _require_input_sample_id(inputs: Mapping[str, Any], key: str) -> str:
    return _require_string(
        _require_mapping(inputs.get(key), f"inputs.{key}").get("sample_id"),
        f"inputs.{key}.sample_id",
    )


def _require_output_path(outputs: Mapping[str, Any], key: str) -> str:
    return str(_require_absolute_path(outputs.get(key), f"outputs.{key}"))


def _runtime_flags(plan: Mapping[str, Any], name: str) -> dict[str, str]:
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    runtime = _require_mapping(plan.get("runtime"), "runtime")
    return {
        "--tmp-dir": str(_require_absolute_path(outputs.get("tmp_dir"), "outputs.tmp_dir") / name),
        "--logfile": str(_require_absolute_path(outputs.get("logs_dir"), "outputs.logs_dir") / f"{name}.log"),
        "--num-gpus": str(_require_positive_int(runtime.get("num_gpus"), "runtime.num_gpus")),
    }


def _expected_flag_values(plan: Mapping[str, Any], name: str) -> dict[str, str]:
    inputs = _require_mapping(plan.get("inputs"), "inputs")
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    if name == "prepon":
        return {
            "--in-pon-file": _require_input_path(inputs, "panel_of_normals_vcf"),
            **_runtime_flags(plan, name),
        }
    if name == "mutectcaller":
        return {
            "--ref": _require_input_path(inputs, "reference_fasta"),
            "--tumor-name": _require_input_sample_id(inputs, "tumor_bam"),
            "--in-tumor-bam": _require_input_path(inputs, "tumor_bam"),
            "--in-normal-bam": _require_input_path(inputs, "normal_bam"),
            "--normal-name": _require_input_sample_id(inputs, "normal_bam"),
            "--pon": _require_input_path(inputs, "panel_of_normals_vcf"),
            "--mutect-germline-resource": _require_input_path(inputs, "germline_resource_vcf"),
            "--interval-file": _require_input_path(inputs, "mutect2_interval_set"),
            "--mutect-f1r2-tar-gz": _require_output_path(outputs, "f1r2_tar_gz"),
            "--out-vcf": _require_output_path(outputs, "raw_vcf"),
            **_runtime_flags(plan, name),
        }
    if name == "postpon":
        return {
            "--in-vcf": _require_output_path(outputs, "raw_vcf"),
            "--in-pon-file": _require_input_path(inputs, "panel_of_normals_vcf"),
            "--out-vcf": _require_output_path(outputs, "pon_annotated_vcf"),
            **_runtime_flags(plan, name),
        }
    raise ManifestError(f"Unexpected Parabricks command: {name}")


def _require_flags(argv: list[str], name: str, expected: Mapping[str, str]) -> None:
    tail = argv[2:]
    if len(tail) % 2:
        raise ManifestError(f"{name} argv flags must be --flag value pairs")

    observed: dict[str, str] = {}
    for flag, value in zip(tail[::2], tail[1::2]):
        if not flag.startswith("--"):
            raise ManifestError(f"{name} argv flag must start with --: {flag}")
        if flag in observed:
            raise ManifestError(f"{name} argv must not repeat {flag}")
        observed[flag] = value

    missing = [flag for flag in expected if flag not in observed]
    unexpected = [flag for flag in observed if flag not in expected]
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise ManifestError(f"{name} argv flags must match the plan: {'; '.join(details)}")

    for flag, expected_value in expected.items():
        if observed[flag] != expected_value:
            raise ManifestError(f"{name} argv {flag} must match the plan")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_safe_output_path(path: Path, key: str) -> None:
    if path.is_symlink():
        raise ManifestError(f"{key} materialized output path may not be a symlink: {path}")

    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        next_parent = parent.parent
        if next_parent == parent:
            raise ManifestError(f"{key} materialized output parent does not exist: {path.parent}")
        parent = next_parent

    if parent.is_symlink():
        raise ManifestError(f"{key} materialized output parent may not be a symlink: {parent}")
    if not parent.is_dir():
        raise ManifestError(f"{key} materialized output parent is not a directory: {parent}")


def _materialized_outputs(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    materialized: dict[str, dict[str, Any]] = {}
    for key in MATERIALIZED_OUTPUTS:
        path = _require_absolute_path(outputs.get(key), key)
        if not path.is_file():
            raise ManifestError(f"{key} must exist after Parabricks Mutect execution: {path}")
        bytes_ = path.stat().st_size
        if bytes_ <= 0:
            raise ManifestError(f"{key} must be non-empty after Parabricks Mutect execution: {path}")
        materialized[key] = {
            "local_path": str(path),
            "bytes": bytes_,
            "sha256": _sha256_path(path),
        }
    return materialized


def _prepare_materialized_outputs(plan: Mapping[str, Any]) -> None:
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    paths = {
        key: _require_absolute_path(outputs.get(key), key)
        for key in MATERIALIZED_OUTPUTS
    }
    path_values = list(paths.values())
    if len(set(path_values)) != len(path_values):
        raise ManifestError("materialized output paths must be unique")

    for key, path in paths.items():
        _require_safe_output_path(path, key)
        if path.exists() and not path.is_file():
            raise ManifestError(f"{key} materialized output path already exists and is not a file: {path}")
        ensure_parent(path)
        path.unlink(missing_ok=True)

    for key in ("logs_dir", "tmp_dir"):
        path = Path(_require_absolute_path(outputs.get(key), key))
        _require_safe_output_path(path, key)
        path.mkdir(parents=True, exist_ok=True)


def _planned_commands(plan: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    commands = _require_mapping(plan.get("commands"), "commands")
    command_names = tuple(commands)
    if command_names != EXPECTED_COMMANDS:
        raise ManifestError(f"commands must be exactly {', '.join(EXPECTED_COMMANDS)} in execution order")

    return [
        (
            name,
            _require_argv(_require_mapping(commands.get(name), f"{name} command").get("argv"), name, plan),
        )
        for name in EXPECTED_COMMANDS
    ]


def _validate_plan(plan: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    if plan.get("manifest_type") != "phase3_wgs_fast_parabricks_mutect_plan":
        raise ManifestError("Parabricks Mutect plan manifest_type must be phase3_wgs_fast_parabricks_mutect_plan")
    if plan.get("status") != "planned":
        raise ManifestError("Parabricks Mutect plan status must be planned")
    if _require_mapping(plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("Parabricks Mutect receipt authorized_hrd_state must remain no_call")

    return _planned_commands(plan)


def run_phase3_fast_parabricks_mutect(
    plan: Mapping[str, Any],
    *,
    runner: CommandRunner,
    parabricks_mutect_plan_sha256: str,
) -> dict[str, Any]:
    mutect_plan_sha = _require_hex(parabricks_mutect_plan_sha256, "parabricks_mutect_plan_sha256")
    commands = _validate_plan(plan)
    _prepare_materialized_outputs(plan)
    for _, argv in commands:
        runner.run(argv)
    materialized_outputs = _materialized_outputs(plan)

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_parabricks_mutect_receipt",
        "status": "completed",
        "workflow": dict(_require_mapping(plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(plan.get("run"), "run")),
        "runtime": dict(_require_mapping(plan.get("runtime"), "runtime")),
        "method_parameters": normalize_method_parameters(plan.get("method_parameters")),
        "source": {
            **dict(_require_mapping(plan.get("source"), "source")),
            "parabricks_mutect_plan_sha256": mutect_plan_sha,
        },
        "inputs": dict(_require_mapping(plan.get("inputs"), "inputs")),
        "outputs": dict(_require_mapping(plan.get("outputs"), "outputs")),
        "materialized_outputs": materialized_outputs,
        "commands": {
            name: {
                "argv": argv,
                "status": "completed",
            }
            for name, argv in commands
        },
        "interpretation": {
            "authorized_hrd_state": "no_call",
        },
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_receipt_from_environment(
    runner: CommandRunner | None = None,
) -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT_OUTPUT", DEFAULT_OUTPUT))
    receipt = run_phase3_fast_parabricks_mutect(
        read_json(input_path),
        runner=runner if runner is not None else SubprocessCommandRunner(),
        parabricks_mutect_plan_sha256=_sha256_path(input_path),
    )
    return receipt, output_path


def main() -> None:
    receipt, output = load_receipt_from_environment()
    write_receipt(output, receipt)
    print(f"Phase 3 WGS fast Parabricks Mutect receipt written: {output}")


if __name__ == "__main__":
    main()
