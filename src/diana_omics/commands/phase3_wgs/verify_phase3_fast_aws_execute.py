from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import read_json
from . import verify_phase3_fast_gpu_smoke as gpu_smoke

GPU_SMOKE_RESULT_ENV = "PHASE3_FAST_GPU_SMOKE_RESULT"
REQUIRED_GPU_COUNT = 8
REQUIRED_GPU_NAME = "H200"


class Phase3FastExecuteError(ValueError):
    """Raised when the full P5en execute lane is not safe to submit."""


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Phase3FastExecuteError(f"{label} must be set")
    return value.strip()


def _require_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise Phase3FastExecuteError(f"{label} must be an integer")
    return value


def _require_existing_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise Phase3FastExecuteError(f"{label} may not be a symlink: {path}")
    if not path.is_file():
        raise Phase3FastExecuteError(f"{label} must be an existing file: {path}")


def _require_csv_basename(value: Any) -> str:
    name = _require_string(value, "nvidiaSmiCsv")
    if Path(name).name != name:
        raise Phase3FastExecuteError("nvidiaSmiCsv must be a sibling basename")
    return name


def _require_matching_string(value: Any, label: str, expected: Any) -> str:
    observed = _require_string(value, label)
    expected_value = _require_string(expected, f"expected {label}")
    if observed != expected_value:
        raise Phase3FastExecuteError(f"GPU smoke {label} must match the current Nextflow params")
    return observed


def _parse_nvidia_smi_csv(path: Path) -> list[dict[str, str]]:
    _require_existing_file(path, "nvidia-smi CSV")
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        columns = [column.strip() for column in line.split(",", 2)]
        if len(columns) != 3:
            raise Phase3FastExecuteError(f"nvidia-smi CSV line {line_number} must have index,name,uuid")
        rows.append(
            {
                "index": columns[0],
                "name": columns[1],
                "uuid": columns[2],
            }
        )
    return rows


def validate_gpu_smoke_result(
    payload: Mapping[str, Any],
    *,
    csv_root: Path,
    expected_params: Mapping[str, Any],
) -> dict[str, Any]:
    if payload.get("schema") != "phase3_wgs_fast_gpu_smoke.v1":
        raise Phase3FastExecuteError("GPU smoke result schema must be phase3_wgs_fast_gpu_smoke.v1")
    if payload.get("status") != "passed":
        raise Phase3FastExecuteError("GPU smoke result status must be passed")

    aws_region = _require_matching_string(payload.get("awsRegion"), "awsRegion", expected_params.get("aws_region"))
    aws_gpu_queue = _require_matching_string(
        payload.get("awsGpuQueue"), "awsGpuQueue", expected_params.get("aws_gpu_queue")
    )
    parabricks_container = _require_matching_string(
        payload.get("parabricksContainer"),
        "parabricksContainer",
        expected_params.get("parabricks_container"),
    )
    expected_count = _require_int(payload.get("expectedGpuCount"), "expectedGpuCount")
    observed_count = _require_int(payload.get("observedGpuCount"), "observedGpuCount")
    required_name = _require_string(payload.get("requiredGpuName"), "requiredGpuName")

    if expected_count != REQUIRED_GPU_COUNT or observed_count != REQUIRED_GPU_COUNT:
        raise Phase3FastExecuteError(f"GPU smoke result must prove exactly {REQUIRED_GPU_COUNT} visible GPUs")
    if required_name != REQUIRED_GPU_NAME:
        raise Phase3FastExecuteError(f"GPU smoke result must require {REQUIRED_GPU_NAME}")

    csv_path = csv_root / _require_csv_basename(payload.get("nvidiaSmiCsv"))
    csv_rows = _parse_nvidia_smi_csv(csv_path)
    if len(csv_rows) != observed_count:
        raise Phase3FastExecuteError("nvidia-smi CSV GPU count must match observedGpuCount")
    for row in csv_rows:
        if required_name not in row["name"]:
            raise Phase3FastExecuteError(f"nvidia-smi GPU {row['index']} was not an {required_name}: {row['name']}")

    return {
        "aws_gpu_queue": aws_gpu_queue,
        "aws_region": aws_region,
        "expected_gpu_count": expected_count,
        "observed_gpu_count": observed_count,
        "parabricks_container": parabricks_container,
        "required_gpu_name": required_name,
        "status": "passed",
    }


def load_gpu_smoke_result_from_environment(*, expected_params: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    path_value = os.environ.get(GPU_SMOKE_RESULT_ENV)
    if not path_value:
        raise Phase3FastExecuteError(f"{GPU_SMOKE_RESULT_ENV} must point at the reviewed gpu_smoke.json")

    path = path_from_root(path_value)
    _require_existing_file(path, "GPU smoke result")
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise Phase3FastExecuteError("GPU smoke result must be a JSON object")
    return validate_gpu_smoke_result(payload, csv_root=path.parent, expected_params=expected_params), path


def main() -> None:
    try:
        params, params_path = gpu_smoke.load_params_from_environment()
        params_summary = gpu_smoke.validate_gpu_smoke_params(params)
        running_on_demand_p_vcpus = gpu_smoke.load_running_on_demand_p_vcpus(params_summary["aws_region"])
        gpu_smoke.validate_running_on_demand_p_quota(running_on_demand_p_vcpus)
        smoke_summary, smoke_path = load_gpu_smoke_result_from_environment(expected_params=params_summary)
    except (gpu_smoke.GpuSmokeConfigError, Phase3FastExecuteError) as error:
        raise SystemExit(str(error)) from error

    print(
        f"Phase 3 WGS fast AWS execute preflight passed: {params_path} "
        f"queue={params_summary['aws_gpu_queue']} "
        f"running_on_demand_p_vcpus={running_on_demand_p_vcpus:g} "
        f"gpu_smoke={smoke_path} "
        f"observed_gpus={smoke_summary['observed_gpu_count']}"
    )


if __name__ == "__main__":
    main()
