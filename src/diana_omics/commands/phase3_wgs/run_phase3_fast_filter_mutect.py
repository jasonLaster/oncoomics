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

DEFAULT_INPUT = "manifests/phase3_wgs_fast/filter_mutect_plan.json"
DEFAULT_PARABRICKS_RECEIPT = "manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/filter_mutect_receipt.json"

EXPECTED_COMMANDS = (
    "get_tumor_pileups",
    "get_normal_pileups",
    "learn_read_orientation_model",
    "calculate_contamination",
    "index_pon_annotated_vcf",
    "filter_mutect_calls",
    "index_filtered_vcf",
)
EXPECTED_GATK_TOOLS = {
    "get_tumor_pileups": ("GetPileupSummaries", "12g"),
    "get_normal_pileups": ("GetPileupSummaries", "12g"),
    "learn_read_orientation_model": ("LearnReadOrientationModel", "8g"),
    "calculate_contamination": ("CalculateContamination", "8g"),
    "filter_mutect_calls": ("FilterMutectCalls", "12g"),
}
EXPECTED_BCFTOOLS_INDEX_COMMANDS = {"index_pon_annotated_vcf", "index_filtered_vcf"}
PARABRICKS_INPUTS = ("raw_vcf", "raw_vcf_stats", "pon_annotated_vcf", "f1r2_tar_gz")
MATERIALIZED_OUTPUTS = (
    "tumor_pileups",
    "normal_pileups",
    "contamination",
    "tumor_segments",
    "read_orientation_model",
    "pon_annotated_vcf_index",
    "filtered_vcf",
    "filtered_vcf_index",
)


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


def _require_absolute_path(value: Any, label: str) -> Path:
    path = Path(_require_string(value, label))
    if not path.is_absolute():
        raise ManifestError(f"{label} must be an absolute path")
    return path


def _require_input_path(inputs: Mapping[str, Any], key: str) -> str:
    return str(
        _require_absolute_path(
            _require_mapping(inputs.get(key), f"inputs.{key}").get("local_path"),
            f"inputs.{key}",
        )
    )


def _require_output_path(outputs: Mapping[str, Any], key: str) -> str:
    return str(_require_absolute_path(outputs.get(key), f"outputs.{key}"))


def _gatk_flag_values(plan: Mapping[str, Any], name: str) -> dict[str, str]:
    inputs = _require_mapping(plan.get("inputs"), "inputs")
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    if name == "get_tumor_pileups":
        return {
            "-R": _require_input_path(inputs, "reference_fasta"),
            "-I": _require_input_path(inputs, "tumor_bam"),
            "-V": _require_input_path(inputs, "common_sites_vcf"),
            "-L": _require_input_path(inputs, "common_sites_vcf"),
            "-O": _require_output_path(outputs, "tumor_pileups"),
        }
    if name == "get_normal_pileups":
        return {
            "-R": _require_input_path(inputs, "reference_fasta"),
            "-I": _require_input_path(inputs, "normal_bam"),
            "-V": _require_input_path(inputs, "common_sites_vcf"),
            "-L": _require_input_path(inputs, "common_sites_vcf"),
            "-O": _require_output_path(outputs, "normal_pileups"),
        }
    if name == "learn_read_orientation_model":
        return {
            "-I": _require_input_path(inputs, "f1r2_tar_gz"),
            "-O": _require_output_path(outputs, "read_orientation_model"),
        }
    if name == "calculate_contamination":
        return {
            "-I": _require_output_path(outputs, "tumor_pileups"),
            "-matched": _require_output_path(outputs, "normal_pileups"),
            "-O": _require_output_path(outputs, "contamination"),
            "--tumor-segmentation": _require_output_path(outputs, "tumor_segments"),
        }
    if name == "filter_mutect_calls":
        return {
            "-R": _require_input_path(inputs, "reference_fasta"),
            "-V": _require_input_path(inputs, "pon_annotated_vcf"),
            "--stats": _require_input_path(inputs, "raw_vcf_stats"),
            "--contamination-table": _require_output_path(outputs, "contamination"),
            "--tumor-segmentation": _require_output_path(outputs, "tumor_segments"),
            "--orientation-bias-artifact-priors": _require_output_path(outputs, "read_orientation_model"),
            "-O": _require_output_path(outputs, "filtered_vcf"),
        }
    raise ManifestError(f"Unexpected GATK command: {name}")


def _require_paired_flags(tail: list[str], name: str, expected: Mapping[str, str]) -> None:
    if len(tail) % 2:
        raise ManifestError(f"{name} argv flags must be flag value pairs")

    observed: dict[str, str] = {}
    for flag, value in zip(tail[::2], tail[1::2]):
        if not flag.startswith("-"):
            raise ManifestError(f"{name} argv flag must start with -: {flag}")
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


def _require_gatk_argv(argv: list[str], name: str, plan: Mapping[str, Any]) -> None:
    gatk_tool = EXPECTED_GATK_TOOLS.get(name)
    if gatk_tool is None:
        return

    tool, memory = gatk_tool
    inputs = _require_mapping(plan.get("inputs"), "inputs")
    expected_prefix = [
        "java",
        f"-Xmx{memory}",
        "-jar",
        _require_input_path(inputs, "gatk_jar"),
        tool,
    ]
    if argv[:5] != expected_prefix:
        raise ManifestError(f"{name} argv must run GATK {tool}")
    _require_paired_flags(argv[5:], name, _gatk_flag_values(plan, name))


def _bcftools_index_target(plan: Mapping[str, Any], name: str) -> str:
    inputs = _require_mapping(plan.get("inputs"), "inputs")
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    if name == "index_pon_annotated_vcf":
        input_vcf = _require_input_path(inputs, "pon_annotated_vcf")
        output_index = _require_output_path(outputs, "pon_annotated_vcf_index")
        if output_index != f"{input_vcf}.tbi":
            raise ManifestError("outputs.pon_annotated_vcf_index must be the pon_annotated_vcf .tbi sidecar")
        return input_vcf
    if name == "index_filtered_vcf":
        output_vcf = _require_output_path(outputs, "filtered_vcf")
        output_index = _require_output_path(outputs, "filtered_vcf_index")
        if output_index != f"{output_vcf}.tbi":
            raise ManifestError("outputs.filtered_vcf_index must be the filtered_vcf .tbi sidecar")
        return output_vcf
    raise ManifestError(f"Unexpected bcftools command: {name}")


def _require_bcftools_argv(argv: list[str], name: str, plan: Mapping[str, Any]) -> None:
    if name not in EXPECTED_BCFTOOLS_INDEX_COMMANDS:
        return

    if argv != ["bcftools", "index", "-t", "-f", _bcftools_index_target(plan, name)]:
        raise ManifestError(f"{name} argv must match the planned bcftools index -t -f input")


def _require_argv(value: Any, name: str, plan: Mapping[str, Any]) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{name} argv must be a non-empty string list")
    argv = list(value)
    _require_gatk_argv(argv, name, plan)
    _require_bcftools_argv(argv, name, plan)
    return argv


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_materialized(path: Path, key: str, *, producer: str) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"{key} must exist after {producer} execution: {path}")
    bytes_ = path.stat().st_size
    if bytes_ <= 0:
        raise ManifestError(f"{key} must be non-empty after {producer} execution: {path}")
    return {
        "local_path": str(path),
        "bytes": bytes_,
        "sha256": _sha256_path(path),
    }


def _materialized_outputs(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    outputs = _require_mapping(plan.get("outputs"), "outputs")
    return {
        key: _hash_materialized(_require_absolute_path(outputs.get(key), key), key, producer="FilterMutect")
        for key in MATERIALIZED_OUTPUTS
    }


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
        if path.exists() and not path.is_file():
            raise ManifestError(f"{key} materialized output path already exists and is not a file: {path}")
        ensure_parent(path)
        path.unlink(missing_ok=True)


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


def _verify_parabricks_receipt(
    plan: Mapping[str, Any],
    parabricks_receipt: Mapping[str, Any],
) -> None:
    if parabricks_receipt.get("manifest_type") != "phase3_wgs_fast_parabricks_mutect_receipt":
        raise ManifestError("Parabricks receipt manifest_type must be phase3_wgs_fast_parabricks_mutect_receipt")
    if parabricks_receipt.get("status") != "completed":
        raise ManifestError("Parabricks receipt status must be completed")
    if _require_mapping(parabricks_receipt.get("interpretation"), "Parabricks receipt interpretation").get(
        "authorized_hrd_state"
    ) != "no_call":
        raise ManifestError("FilterMutect runner authorized_hrd_state must remain no_call")

    plan_source = _require_mapping(plan.get("source"), "source")
    receipt_source = _require_mapping(parabricks_receipt.get("source"), "Parabricks receipt source")
    if receipt_source.get("parabricks_mutect_plan_sha256") != _require_hex(
        plan_source.get("parabricks_mutect_plan_sha256"),
        "parabricks_mutect_plan_sha256",
    ):
        raise ManifestError("Parabricks receipt must match the FilterMutect plan source")

    plan_inputs = _require_mapping(plan.get("inputs"), "inputs")
    materialized = _require_mapping(parabricks_receipt.get("materialized_outputs"), "Parabricks materialized_outputs")
    for key in PARABRICKS_INPUTS:
        expected_path = _require_absolute_path(_require_mapping(plan_inputs.get(key), f"{key} input").get("local_path"), key)
        observed = _require_mapping(materialized.get(key), f"{key} materialized output")
        observed_path = _require_absolute_path(observed.get("local_path"), f"{key} materialized local_path")
        if observed_path != expected_path:
            raise ManifestError(f"Parabricks receipt {key} local_path must match the FilterMutect input")
        if _hash_materialized(observed_path, key, producer="Parabricks Mutect") != {
            "local_path": str(observed_path),
            "bytes": observed.get("bytes"),
            "sha256": observed.get("sha256"),
        }:
            raise ManifestError(f"Parabricks receipt {key} bytes and sha256 must match the local file")


def _validate_plan(plan: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    if plan.get("manifest_type") != "phase3_wgs_fast_filter_mutect_plan":
        raise ManifestError("FilterMutect plan manifest_type must be phase3_wgs_fast_filter_mutect_plan")
    if plan.get("status") != "planned":
        raise ManifestError("FilterMutect plan status must be planned")
    if _require_mapping(plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("FilterMutect receipt authorized_hrd_state must remain no_call")

    return _planned_commands(plan)


def run_phase3_fast_filter_mutect(
    plan: Mapping[str, Any],
    parabricks_receipt: Mapping[str, Any],
    *,
    runner: CommandRunner,
    filter_mutect_plan_sha256: str,
    parabricks_mutect_receipt_sha256: str,
) -> dict[str, Any]:
    filter_sha = _require_hex(filter_mutect_plan_sha256, "filter_mutect_plan_sha256")
    parabricks_receipt_sha = _require_hex(parabricks_mutect_receipt_sha256, "parabricks_mutect_receipt_sha256")
    commands = _validate_plan(plan)
    _verify_parabricks_receipt(plan, parabricks_receipt)
    _prepare_materialized_outputs(plan)
    for _, argv in commands:
        runner.run(argv)
    materialized_outputs = _materialized_outputs(plan)

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_filter_mutect_receipt",
        "status": "completed",
        "workflow": dict(_require_mapping(plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(plan.get("run"), "run")),
        "runtime": dict(_require_mapping(plan.get("runtime"), "runtime")),
        "source": {
            **dict(_require_mapping(plan.get("source"), "source")),
            "filter_mutect_plan_sha256": filter_sha,
            "parabricks_mutect_receipt_sha256": parabricks_receipt_sha,
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
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_FILTER_MUTECT_PLAN", DEFAULT_INPUT))
    parabricks_receipt_path = path_from_root(
        os.environ.get("PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT", DEFAULT_PARABRICKS_RECEIPT)
    )
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT_OUTPUT", DEFAULT_OUTPUT))
    receipt = run_phase3_fast_filter_mutect(
        read_json(input_path),
        read_json(parabricks_receipt_path),
        runner=runner if runner is not None else SubprocessCommandRunner(),
        filter_mutect_plan_sha256=_sha256_path(input_path),
        parabricks_mutect_receipt_sha256=_sha256_path(parabricks_receipt_path),
    )
    return receipt, output_path


def main() -> None:
    receipt, output = load_receipt_from_environment()
    write_receipt(output, receipt)
    print(f"Phase 3 WGS fast FilterMutect receipt written: {output}")


if __name__ == "__main__":
    main()
