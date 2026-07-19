from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent
from .render_phase3_fast_input_manifest import HEX64, ManifestError, normalize_method_parameters
from .safe_json_output import (
    read_real_json,
    require_no_symlinked_ancestors,
    require_safe_output_path,
    sha256_real_file,
)

DEFAULT_INPUT = "manifests/phase3_wgs_fast/bam_qc_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/bam_qc_receipt.json"

ROLES = ("tumor", "normal")
EXPECTED_COMMANDS = ("quickcheck", "flagstat", "idxstats")
OUTPUT_BY_COMMAND = {
    "quickcheck": "quickcheck_log",
    "flagstat": "flagstat",
    "idxstats": "idxstats",
}
EXPECTED_OUTPUTS = tuple(OUTPUT_BY_COMMAND.values())


class SamtoolsRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> None: ...


class SubprocessSamtoolsRunner:
    def run(
        self,
        argv: Sequence[str],
        *,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> None:
        output_paths = [path for path in (stdout_path, stderr_path) if path is not None]
        temporary_paths = [(path.with_name(f".{path.name}.tmp"), path) for path in output_paths]
        for temporary_path, path in temporary_paths:
            ensure_parent(path)
            temporary_path.unlink(missing_ok=True)

        try:
            with ExitStack() as stack:
                stdout = (
                    stack.enter_context(temporary_paths[0][0].open("wb"))
                    if stdout_path is not None
                    else subprocess.DEVNULL
                )
                stderr_index = 1 if stdout_path is not None else 0
                stderr = (
                    stack.enter_context(temporary_paths[stderr_index][0].open("wb"))
                    if stderr_path is not None
                    else subprocess.DEVNULL
                )
                subprocess.check_call(list(argv), stdout=stdout, stderr=stderr)

            for temporary_path, path in temporary_paths:
                temporary_path.replace(path)
        except Exception:
            for temporary_path, _ in temporary_paths:
                temporary_path.unlink(missing_ok=True)
            raise


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


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ManifestError(f"{label} must be a positive integer")
    return value


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


def _expected_argv(plan: Mapping[str, Any], role: str, name: str) -> list[str]:
    bam = _input_bam_path(plan, role)
    threads = str(_require_positive_int(_require_mapping(plan.get("runtime"), "runtime").get("samtools_threads"), "runtime.samtools_threads"))
    if name == "quickcheck":
        return ["samtools", "quickcheck", "-v", bam]
    if name == "flagstat":
        return ["samtools", "flagstat", "-@", threads, bam]
    if name == "idxstats":
        return ["samtools", "idxstats", bam]
    raise ManifestError(f"Unexpected BAM QC command: {name}")


def _require_argv(value: Any, expected: Sequence[str], label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{label} argv must be a non-empty string list")
    argv = list(value)
    if argv != list(expected):
        raise ManifestError(f"{label} argv must match the planned {' '.join(expected[:2])} command")
    return argv


def _role_output_paths(plan: Mapping[str, Any], role: str) -> dict[str, Path]:
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    role_outputs = _require_mapping(outputs.get(role), f"outputs.{role}")
    if set(role_outputs) != set(EXPECTED_OUTPUTS):
        raise ManifestError(f"outputs.{role} must contain exactly {', '.join(EXPECTED_OUTPUTS)}")
    return {
        name: _require_absolute_path(role_outputs.get(name), f"outputs.{role}.{name}")
        for name in EXPECTED_OUTPUTS
    }


def _planned_role_commands(
    plan: Mapping[str, Any],
    role: str,
    output_paths: Mapping[str, Path],
) -> list[tuple[str, list[str], Path | None, Path | None]]:
    commands = _require_mapping(plan.get("commands"), "commands")
    role_commands = _require_mapping(commands.get(role), f"commands.{role}")
    if set(role_commands) != set(EXPECTED_COMMANDS):
        raise ManifestError(f"commands.{role} must contain exactly {', '.join(EXPECTED_COMMANDS)}")

    planned: list[tuple[str, list[str], Path | None, Path | None]] = []
    for name in EXPECTED_COMMANDS:
        command = _require_mapping(role_commands.get(name), f"commands.{role}.{name}")
        argv = _require_argv(command.get("argv"), _expected_argv(plan, role, name), f"commands.{role}.{name}")
        expected_output = output_paths[OUTPUT_BY_COMMAND[name]]
        if name == "quickcheck":
            stderr_path = _require_absolute_path(
                command.get("stderr_path"),
                f"commands.{role}.{name}.stderr_path",
            )
            if stderr_path != expected_output:
                raise ManifestError(f"commands.{role}.{name}.stderr_path must match outputs.{role}.quickcheck_log")
            planned.append((name, argv, None, stderr_path))
        else:
            stdout_path = _require_absolute_path(
                command.get("stdout_path"),
                f"commands.{role}.{name}.stdout_path",
            )
            if stdout_path != expected_output:
                raise ManifestError(f"commands.{role}.{name}.stdout_path must match outputs.{role}.{name}")
            planned.append((name, argv, stdout_path, None))
    return planned


def _planned_commands(plan: Mapping[str, Any]) -> dict[str, list[tuple[str, list[str], Path | None, Path | None]]]:
    commands = _require_mapping(plan.get("commands"), "commands")
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    if set(commands) != set(ROLES):
        raise ManifestError("commands must contain exactly tumor and normal BAM QC commands")
    if set(outputs) != set(ROLES):
        raise ManifestError("outputs must contain exactly tumor and normal BAM QC outputs")

    output_paths = {role: _role_output_paths(plan, role) for role in ROLES}
    flattened = [path for role_paths in output_paths.values() for path in role_paths.values()]
    if len(set(flattened)) != len(flattened):
        raise ManifestError("BAM QC output paths must be unique")

    return {
        role: _planned_role_commands(plan, role, output_paths[role])
        for role in ROLES
    }


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, list[tuple[str, list[str], Path | None, Path | None]]]:
    if plan.get("manifest_type") != "phase3_wgs_fast_bam_qc_plan":
        raise ManifestError("BAM QC plan manifest_type must be phase3_wgs_fast_bam_qc_plan")
    if plan.get("status") != "planned":
        raise ManifestError("BAM QC plan status must be planned")
    if _require_mapping(plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("BAM QC receipt authorized_hrd_state must remain no_call")
    return _planned_commands(plan)


def _command_output_path(command: tuple[str, Sequence[str], Path | None, Path | None]) -> Path:
    name, _, stdout_path, stderr_path = command
    path = stderr_path if name == "quickcheck" else stdout_path
    if path is None:
        raise ManifestError(f"{name} must declare an output path")
    return path


def _require_safe_output_path(path: Path) -> None:
    if path.is_symlink():
        raise ManifestError(f"BAM QC output path may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, "BAM QC output", ManifestError)


def _prepare_outputs(commands: Mapping[str, Sequence[tuple[str, Sequence[str], Path | None, Path | None]]]) -> None:
    paths = {
        _command_output_path(command)
        for role_commands in commands.values()
        for command in role_commands
    }
    if len(paths) != len(ROLES) * len(EXPECTED_COMMANDS):
        raise ManifestError("BAM QC output paths must be unique")

    for path in paths:
        _require_safe_output_path(path)
        if path.exists() and not path.is_file():
            raise ManifestError(f"BAM QC output path already exists and is not a file: {path}")
        ensure_parent(path)
        path.unlink(missing_ok=True)


def _run_commands(
    commands: Mapping[str, Sequence[tuple[str, Sequence[str], Path | None, Path | None]]],
    runner: SamtoolsRunner,
) -> None:
    planned = [
        command
        for role in ROLES
        for command in commands[role]
    ]
    with ThreadPoolExecutor(max_workers=len(planned)) as executor:
        futures = [
            executor.submit(runner.run, argv, stdout_path=stdout_path, stderr_path=stderr_path)
            for _, argv, stdout_path, stderr_path in planned
        ]
        for future in futures:
            future.result()


def _sha256_path(path: Path) -> str:
    return sha256_real_file(path, ManifestError)


def _hash_materialized(path: Path, key: str, *, allow_empty: bool) -> dict[str, Any]:
    _require_safe_output_path(path)
    if not path.is_file():
        raise ManifestError(f"{key} must exist after BAM QC execution: {path}")
    bytes_ = path.stat().st_size
    if bytes_ <= 0 and not allow_empty:
        raise ManifestError(f"{key} must be non-empty after BAM QC execution: {path}")
    return {
        "local_path": str(path),
        "bytes": bytes_,
        "sha256": _sha256_path(path),
    }


def _materialized_outputs(
    commands: Mapping[str, Sequence[tuple[str, Sequence[str], Path | None, Path | None]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        role: {
            OUTPUT_BY_COMMAND[name]: _hash_materialized(
                _command_output_path(command),
                f"{role} {OUTPUT_BY_COMMAND[name]}",
                allow_empty=name == "quickcheck",
            )
            for command in commands[role]
            for name in [command[0]]
        }
        for role in ROLES
    }


def run_phase3_fast_bam_qc(
    plan: Mapping[str, Any],
    *,
    runner: SamtoolsRunner,
    bam_qc_plan_sha256: str,
) -> dict[str, Any]:
    plan_sha = _require_hex(bam_qc_plan_sha256, "bam_qc_plan_sha256")
    commands = _validate_plan(plan)
    _prepare_outputs(commands)
    _run_commands(commands, runner)

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_bam_qc_receipt",
        "status": "completed",
        "workflow": dict(_require_mapping(plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(plan.get("run"), "run")),
        "runtime": dict(_require_mapping(plan.get("runtime"), "runtime")),
        "method_parameters": normalize_method_parameters(plan.get("method_parameters")),
        "source": {
            **dict(_require_mapping(plan.get("source"), "source")),
            "bam_qc_plan_sha256": plan_sha,
        },
        "inputs": dict(_require_mapping(plan.get("inputs"), "inputs")),
        "outputs": dict(_require_mapping(plan.get("outputs"), "outputs")),
        "materialized_outputs": _materialized_outputs(commands),
        "commands": {
            role: {
                name: {
                    "argv": list(argv),
                    "stdout_path": str(stdout_path) if stdout_path is not None else None,
                    "stderr_path": str(stderr_path) if stderr_path is not None else None,
                    "status": "completed",
                }
                for name, argv, stdout_path, stderr_path in commands[role]
            }
            for role in ROLES
        },
        "interpretation": {
            "authorized_hrd_state": "no_call",
            "hrd_use": "qc_only_not_hrd_evidence",
        },
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast BAM QC receipt output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_receipt_from_environment(
    runner: SamtoolsRunner | None = None,
) -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_BAM_QC_PLAN", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_BAM_QC_RECEIPT_OUTPUT", DEFAULT_OUTPUT))
    receipt = run_phase3_fast_bam_qc(
        read_real_json(input_path, "BAM QC plan", ManifestError),
        runner=runner if runner is not None else SubprocessSamtoolsRunner(),
        bam_qc_plan_sha256=_sha256_path(input_path),
    )
    return receipt, output_path


def main() -> None:
    receipt, output = load_receipt_from_environment()
    write_receipt(output, receipt)
    print(f"Phase 3 WGS fast BAM QC receipt written: {output}")


if __name__ == "__main__":
    main()
