from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent
from .render_phase3_fast_input_manifest import HEX64, ManifestError, normalize_method_parameters
from .safe_json_output import read_real_json, require_no_symlinked_ancestors, require_safe_output_path

DEFAULT_INPUT = "manifests/phase3_wgs_fast/sv_evidence_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/sv_evidence_receipt.json"

ROLES = ("tumor", "normal")
EXPECTED_COMMANDS = ("idxstats", "supplementary_alignments", "discordant_mapped_pairs")


class SamtoolsRunner(Protocol):
    def run(self, argv: Sequence[str], *, stdout_path: Path) -> None: ...


class SubprocessSamtoolsRunner:
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


def _expected_argv(plan: Mapping[str, Any], role: str, name: str) -> list[str]:
    bam = _input_bam_path(plan, role)
    threads = str(_require_positive_int(_require_mapping(plan.get("runtime"), "runtime").get("samtools_threads"), "runtime.samtools_threads"))
    if name == "idxstats":
        return ["samtools", "idxstats", bam]
    if name == "supplementary_alignments":
        return ["samtools", "view", "-@", threads, "-c", "-f", "2048", bam]
    if name == "discordant_mapped_pairs":
        return ["samtools", "view", "-@", threads, "-f", "1", "-F", "14", bam]
    raise ManifestError(f"Unexpected SV evidence command: {name}")


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
    if set(role_outputs) != set(EXPECTED_COMMANDS):
        raise ManifestError(f"outputs.{role} must contain exactly {', '.join(EXPECTED_COMMANDS)}")
    return {
        name: _require_absolute_path(role_outputs.get(name), f"outputs.{role}.{name}")
        for name in EXPECTED_COMMANDS
    }


def _planned_role_commands(
    plan: Mapping[str, Any],
    role: str,
    output_paths: Mapping[str, Path],
) -> list[tuple[str, list[str], Path]]:
    commands = _require_mapping(plan.get("commands"), "commands")
    role_commands = _require_mapping(commands.get(role), f"commands.{role}")
    if set(role_commands) != set(EXPECTED_COMMANDS):
        raise ManifestError(f"commands.{role} must contain exactly {', '.join(EXPECTED_COMMANDS)}")

    planned: list[tuple[str, list[str], Path]] = []
    for name in EXPECTED_COMMANDS:
        command = _require_mapping(role_commands.get(name), f"commands.{role}.{name}")
        argv = _require_argv(command.get("argv"), _expected_argv(plan, role, name), f"commands.{role}.{name}")
        stdout_path = _require_absolute_path(
            command.get("stdout_path"),
            f"commands.{role}.{name}.stdout_path",
        )
        if stdout_path != output_paths[name]:
            raise ManifestError(f"commands.{role}.{name}.stdout_path must match outputs.{role}.{name}")
        planned.append((name, argv, stdout_path))
    return planned


def _planned_commands(plan: Mapping[str, Any]) -> dict[str, list[tuple[str, list[str], Path]]]:
    commands = _require_mapping(plan.get("commands"), "commands")
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    if set(commands) != set(ROLES):
        raise ManifestError("commands must contain exactly tumor and normal SV evidence commands")
    if set(outputs) != set(ROLES):
        raise ManifestError("outputs must contain exactly tumor and normal SV evidence outputs")

    output_paths = {role: _role_output_paths(plan, role) for role in ROLES}
    flattened = [path for role_paths in output_paths.values() for path in role_paths.values()]
    if len(set(flattened)) != len(flattened):
        raise ManifestError("SV evidence output paths must be unique")

    return {
        role: _planned_role_commands(plan, role, output_paths[role])
        for role in ROLES
    }


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, list[tuple[str, list[str], Path]]]:
    if plan.get("manifest_type") != "phase3_wgs_fast_sv_evidence_plan":
        raise ManifestError("SV evidence plan manifest_type must be phase3_wgs_fast_sv_evidence_plan")
    if plan.get("status") != "planned":
        raise ManifestError("SV evidence plan status must be planned")
    if _require_mapping(plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("SV evidence receipt authorized_hrd_state must remain no_call")
    return _planned_commands(plan)


def _require_safe_output_path(path: Path) -> None:
    if path.is_symlink():
        raise ManifestError(f"SV evidence output path may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, "SV evidence output", ManifestError)


def _prepare_outputs(commands: Mapping[str, Sequence[tuple[str, Sequence[str], Path]]]) -> None:
    paths = {stdout_path for role_commands in commands.values() for _, _, stdout_path in role_commands}
    if len(paths) != len(ROLES) * len(EXPECTED_COMMANDS):
        raise ManifestError("SV evidence output paths must be unique")

    for path in paths:
        _require_safe_output_path(path)
        if path.exists() and not path.is_file():
            raise ManifestError(f"SV evidence output path already exists and is not a file: {path}")
        ensure_parent(path)
        path.unlink(missing_ok=True)


def _run_commands(
    commands: Mapping[str, Sequence[tuple[str, Sequence[str], Path]]],
    runner: SamtoolsRunner,
) -> None:
    for role in ROLES:
        for _, argv, stdout_path in commands[role]:
            runner.run(argv, stdout_path=stdout_path)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_supplementary_count(path: Path, role: str) -> int:
    if not path.is_file():
        raise ManifestError(f"{role} supplementary_alignments must exist after SV evidence execution: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ManifestError(f"{role} supplementary_alignments count must be non-empty")
    return _require_nonnegative_int(text, f"{role} supplementary_alignments count")


def _hash_materialized(path: Path, key: str, *, allow_empty: bool) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"{key} must exist after SV evidence execution: {path}")
    bytes_ = path.stat().st_size
    if bytes_ <= 0 and not allow_empty:
        raise ManifestError(f"{key} must be non-empty after SV evidence execution: {path}")
    return {
        "local_path": str(path),
        "bytes": bytes_,
        "sha256": _sha256_path(path),
    }


def _materialized_outputs(
    commands: Mapping[str, Sequence[tuple[str, Sequence[str], Path]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        role: {
            name: _hash_materialized(
                path,
                f"{role} {name}",
                allow_empty=name == "discordant_mapped_pairs",
            )
            for name, _, path in commands[role]
        }
        for role in ROLES
    }


def run_phase3_fast_sv_evidence(
    plan: Mapping[str, Any],
    *,
    runner: SamtoolsRunner,
    sv_evidence_plan_sha256: str,
) -> dict[str, Any]:
    plan_sha = _require_hex(sv_evidence_plan_sha256, "sv_evidence_plan_sha256")
    commands = _validate_plan(plan)
    _prepare_outputs(commands)
    _run_commands(commands, runner)
    supplementary_counts = {
        role: _read_supplementary_count(commands[role][1][2], role)
        for role in ROLES
    }

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_sv_evidence_receipt",
        "status": "completed",
        "workflow": dict(_require_mapping(plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(plan.get("run"), "run")),
        "runtime": dict(_require_mapping(plan.get("runtime"), "runtime")),
        "method_parameters": normalize_method_parameters(plan.get("method_parameters")),
        "source": {
            **dict(_require_mapping(plan.get("source"), "source")),
            "sv_evidence_plan_sha256": plan_sha,
        },
        "inputs": dict(_require_mapping(plan.get("inputs"), "inputs")),
        "outputs": dict(_require_mapping(plan.get("outputs"), "outputs")),
        "materialized_outputs": _materialized_outputs(commands),
        "metrics": {
            role: {
                "supplementary_alignments": supplementary_counts[role],
            }
            for role in ROLES
        },
        "commands": {
            role: {
                name: {
                    "argv": list(argv),
                    "stdout_path": str(stdout_path),
                    "status": "completed",
                }
                for name, argv, stdout_path in commands[role]
            }
            for role in ROLES
        },
        "interpretation": {
            "authorized_hrd_state": "no_call",
            "hrd_use": "mechanical_sv_evidence_not_validated_sv_callset",
            "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
            "hrdetect_use": "no_call_requires_validated_structural_variant_features",
        },
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast SV evidence receipt output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_receipt_from_environment(
    runner: SamtoolsRunner | None = None,
) -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_SV_EVIDENCE_PLAN", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT_OUTPUT", DEFAULT_OUTPUT))
    receipt = run_phase3_fast_sv_evidence(
        read_real_json(input_path, "SV evidence plan", ManifestError),
        runner=runner if runner is not None else SubprocessSamtoolsRunner(),
        sv_evidence_plan_sha256=_sha256_path(input_path),
    )
    return receipt, output_path


def main() -> None:
    receipt, output = load_receipt_from_environment()
    write_receipt(output, receipt)
    print(f"Phase 3 WGS fast SV evidence receipt written: {output}")


if __name__ == "__main__":
    main()
