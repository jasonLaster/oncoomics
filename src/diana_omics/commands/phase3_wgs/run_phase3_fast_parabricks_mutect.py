from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError

DEFAULT_INPUT = "manifests/phase3_wgs_fast/parabricks_mutect_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"
EXPECTED_COMMANDS = ("prepon", "mutectcaller", "postpon")


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


def _require_argv(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{name} argv must be a non-empty string list")
    argv = list(value)
    if len(argv) < 2 or argv[0] != "pbrun" or argv[1] != name:
        raise ManifestError(f"{name} argv must start with pbrun {name}")
    return argv


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _planned_commands(plan: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    commands = _require_mapping(plan.get("commands"), "commands")
    command_names = tuple(commands)
    if command_names != EXPECTED_COMMANDS:
        raise ManifestError(f"commands must be exactly {', '.join(EXPECTED_COMMANDS)} in execution order")

    return [
        (
            name,
            _require_argv(_require_mapping(commands.get(name), f"{name} command").get("argv"), name),
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
    commands = _validate_plan(plan)
    for _, argv in commands:
        runner.run(argv)

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_parabricks_mutect_receipt",
        "status": "completed",
        "workflow": dict(_require_mapping(plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(plan.get("run"), "run")),
        "runtime": dict(_require_mapping(plan.get("runtime"), "runtime")),
        "source": {
            **dict(_require_mapping(plan.get("source"), "source")),
            "parabricks_mutect_plan_sha256": _require_hex(
                parabricks_mutect_plan_sha256,
                "parabricks_mutect_plan_sha256",
            ),
        },
        "inputs": dict(_require_mapping(plan.get("inputs"), "inputs")),
        "outputs": dict(_require_mapping(plan.get("outputs"), "outputs")),
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
