from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from . import verify_parabricks_mirror_receipt as mirror_receipt
from . import verify_phase3_fast_gpu_smoke as gpu_smoke
from .safe_json_output import read_real_json, require_no_symlinked_ancestors

GPU_SMOKE_RESULT_ENV = "PHASE3_FAST_GPU_SMOKE_RESULT"
MIRROR_RECEIPT_ENV = "PARABRICKS_MIRROR_RECEIPT"
REQUIRED_GPU_COUNT = 8
REQUIRED_GPU_NAME = "H200"
REQUIRED_PARABRICKS_VERSION_COMMAND = "pbrun version"
REQUIRED_JAVA_VERSION_COMMAND = "java -version"
REQUIRED_BCFTOOLS_VERSION_COMMAND = "bcftools --version"


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
    require_no_symlinked_ancestors(path, label, Phase3FastExecuteError)
    if not path.is_file():
        raise Phase3FastExecuteError(f"{label} must be an existing file: {path}")


def _require_nonempty_text_file(path: Path, label: str) -> str:
    _require_existing_file(path, label)
    text = path.read_bytes().decode("utf-8", errors="replace")
    if not text.strip():
        raise Phase3FastExecuteError(f"{label} must be non-empty")
    return text


def _require_csv_basename(value: Any) -> str:
    name = _require_string(value, "nvidiaSmiCsv")
    if Path(name).name != name:
        raise Phase3FastExecuteError("nvidiaSmiCsv must be a sibling basename")
    return name


def _require_parabricks_version_basename(value: Any) -> str:
    name = _require_string(value, "parabricksVersionTxt")
    if Path(name).name != name:
        raise Phase3FastExecuteError("parabricksVersionTxt must be a sibling basename")
    return name


def _require_aws_cli_version_basename(value: Any) -> str:
    name = _require_string(value, "awsCliVersionTxt")
    if Path(name).name != name:
        raise Phase3FastExecuteError("awsCliVersionTxt must be a sibling basename")
    return name


def _require_bcftools_version_basename(value: Any) -> str:
    name = _require_string(value, "bcftoolsVersionTxt")
    if Path(name).name != name:
        raise Phase3FastExecuteError("bcftoolsVersionTxt must be a sibling basename")
    return name


def _require_diana_omics_cli_basename(value: Any) -> str:
    name = _require_string(value, "dianaOmicsCliTxt")
    if Path(name).name != name:
        raise Phase3FastExecuteError("dianaOmicsCliTxt must be a sibling basename")
    return name


def _require_java_version_basename(value: Any) -> str:
    name = _require_string(value, "javaVersionTxt")
    if Path(name).name != name:
        raise Phase3FastExecuteError("javaVersionTxt must be a sibling basename")
    return name


def _require_matching_string(value: Any, label: str, expected: Any) -> str:
    observed = _require_string(value, label)
    expected_value = _require_string(expected, f"expected {label}")
    if observed != expected_value:
        raise Phase3FastExecuteError(f"GPU smoke {label} must match the current Nextflow params")
    return observed


def _parse_nvidia_smi_csv(path: Path) -> list[dict[str, str]]:
    rows = []
    for line_number, line in enumerate(_require_nonempty_text_file(path, "nvidia-smi CSV").splitlines(), start=1):
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
    aws_gpu_queue = _require_matching_string(payload.get("awsGpuQueue"), "awsGpuQueue", expected_params.get("aws_gpu_queue"))
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
    if payload.get("parabricksVersionCommand") != REQUIRED_PARABRICKS_VERSION_COMMAND:
        raise Phase3FastExecuteError(f"GPU smoke result must include {REQUIRED_PARABRICKS_VERSION_COMMAND}")
    if payload.get("javaVersionCommand") != REQUIRED_JAVA_VERSION_COMMAND:
        raise Phase3FastExecuteError(f"GPU smoke result must include {REQUIRED_JAVA_VERSION_COMMAND}")
    if payload.get("bcftoolsVersionCommand") != REQUIRED_BCFTOOLS_VERSION_COMMAND:
        raise Phase3FastExecuteError(f"GPU smoke result must include {REQUIRED_BCFTOOLS_VERSION_COMMAND}")

    csv_path = csv_root / _require_csv_basename(payload.get("nvidiaSmiCsv"))
    csv_rows = _parse_nvidia_smi_csv(csv_path)
    if len(csv_rows) != observed_count:
        raise Phase3FastExecuteError("nvidia-smi CSV GPU count must match observedGpuCount")
    observed_indexes: set[int] = set()
    observed_uuids: set[str] = set()
    for row in csv_rows:
        try:
            observed_indexes.add(int(row["index"]))
        except ValueError as error:
            raise Phase3FastExecuteError(f"nvidia-smi GPU index must be numeric: {row['index']}") from error
        uuid = row["uuid"]
        if not uuid.startswith("GPU-"):
            raise Phase3FastExecuteError(f"nvidia-smi GPU UUID must start with GPU-: {uuid}")
        observed_uuids.add(uuid)
        if required_name not in row["name"]:
            raise Phase3FastExecuteError(f"nvidia-smi GPU {row['index']} was not an {required_name}: {row['name']}")
    if sorted(observed_indexes) != list(range(REQUIRED_GPU_COUNT)):
        raise Phase3FastExecuteError(f"nvidia-smi CSV must prove distinct GPU indexes 0-{REQUIRED_GPU_COUNT - 1}")
    if len(observed_uuids) != observed_count:
        raise Phase3FastExecuteError("nvidia-smi CSV must prove unique GPU UUIDs")

    parabricks_version_path = csv_root / _require_parabricks_version_basename(payload.get("parabricksVersionTxt"))
    parabricks_version = _require_nonempty_text_file(
        parabricks_version_path,
        "Parabricks version output",
    ).casefold()
    if "parabricks" not in parabricks_version and "pbrun" not in parabricks_version:
        raise Phase3FastExecuteError("Parabricks version output must identify Parabricks or pbrun")

    java_version_path = csv_root / _require_java_version_basename(payload.get("javaVersionTxt"))
    java_version = _require_nonempty_text_file(java_version_path, "Java version output")
    match = re.search(r'version "(\d+)', java_version)
    if match is None or int(match.group(1)) < 17:
        raise Phase3FastExecuteError("Java version output must prove Java 17+")

    bcftools_version_path = csv_root / _require_bcftools_version_basename(payload.get("bcftoolsVersionTxt"))
    bcftools_version = _require_nonempty_text_file(
        bcftools_version_path,
        "bcftools version output",
    ).casefold()
    if "bcftools" not in bcftools_version:
        raise Phase3FastExecuteError("bcftools version output must identify bcftools")

    aws_cli_version_path = csv_root / _require_aws_cli_version_basename(payload.get("awsCliVersionTxt"))
    aws_cli_version = _require_nonempty_text_file(
        aws_cli_version_path,
        "AWS CLI version output",
    ).casefold()
    if "aws-cli/" not in aws_cli_version:
        raise Phase3FastExecuteError("AWS CLI version output must identify aws-cli")

    diana_omics_cli_path = csv_root / _require_diana_omics_cli_basename(payload.get("dianaOmicsCliTxt"))
    diana_omics_cli = _require_nonempty_text_file(diana_omics_cli_path, "Diana omics CLI output")
    if "verify:phase3-fast-gpu-smoke" not in diana_omics_cli:
        raise Phase3FastExecuteError("Diana omics CLI output must include verify:phase3-fast-gpu-smoke")

    return {
        "aws_cli_version_txt": aws_cli_version_path.name,
        "aws_gpu_queue": aws_gpu_queue,
        "aws_region": aws_region,
        "bcftools_version_command": REQUIRED_BCFTOOLS_VERSION_COMMAND,
        "bcftools_version_txt": bcftools_version_path.name,
        "diana_omics_cli_txt": diana_omics_cli_path.name,
        "expected_gpu_count": expected_count,
        "java_version_command": REQUIRED_JAVA_VERSION_COMMAND,
        "java_version_txt": java_version_path.name,
        "observed_gpu_count": observed_count,
        "parabricks_container": parabricks_container,
        "parabricks_version_command": REQUIRED_PARABRICKS_VERSION_COMMAND,
        "parabricks_version_txt": parabricks_version_path.name,
        "required_gpu_name": required_name,
        "status": "passed",
    }


def load_gpu_smoke_result_from_environment(*, expected_params: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    path_value = os.environ.get(GPU_SMOKE_RESULT_ENV)
    if not path_value:
        raise Phase3FastExecuteError(f"{GPU_SMOKE_RESULT_ENV} must point at the reviewed gpu_smoke.json")

    path = path_from_root(path_value)
    payload = read_real_json(path, "GPU smoke result", Phase3FastExecuteError)
    if not isinstance(payload, dict):
        raise Phase3FastExecuteError("GPU smoke result must be a JSON object")
    return validate_gpu_smoke_result(payload, csv_root=path.parent, expected_params=expected_params), path


def load_mirror_receipt_from_environment(*, expected_params: Mapping[str, Any]) -> tuple[dict[str, str], Path]:
    if not os.environ.get(MIRROR_RECEIPT_ENV):
        raise Phase3FastExecuteError(f"{MIRROR_RECEIPT_ENV} must point at the reviewed parabricks_mirror_receipt.json")

    try:
        receipt, path = mirror_receipt.load_receipt_from_environment()
        summary = mirror_receipt.validate_mirror_receipt(receipt)
        mirror_receipt.validate_current_diana_source_binding(summary)
    except mirror_receipt.MirrorReceiptError as error:
        raise Phase3FastExecuteError(f"Parabricks mirror receipt is not safe: {error}") from error

    expected_container = _require_string(expected_params.get("parabricks_container"), "expected parabricks_container")
    if summary["parabricks_container"] != expected_container:
        raise Phase3FastExecuteError("Parabricks mirror receipt parabricks_container must match the current Nextflow params")
    return summary, path


def main() -> None:
    try:
        params, params_path = gpu_smoke.load_params_from_environment()
        params_summary = gpu_smoke.validate_gpu_smoke_params(params)
        queue = gpu_smoke.load_gpu_batch_job_queue(
            queue=params_summary["aws_gpu_queue"],
            region=params_summary["aws_region"],
        )
        queue_summary = gpu_smoke.validate_gpu_batch_job_queue(
            queue,
            expected_queue=params_summary["aws_gpu_queue"],
        )
        compute_environment = gpu_smoke.load_gpu_batch_compute_environment(
            compute_environment=queue_summary["compute_environment"],
            region=params_summary["aws_region"],
        )
        compute_environment_summary = gpu_smoke.validate_gpu_batch_compute_environment(
            compute_environment,
            expected_compute_environment=queue_summary["compute_environment"],
        )
        mirror_summary, mirror_path = load_mirror_receipt_from_environment(expected_params=params_summary)
        running_on_demand_p_vcpus = gpu_smoke.load_running_on_demand_p_vcpus(params_summary["aws_region"])
        gpu_smoke.validate_running_on_demand_p_quota(running_on_demand_p_vcpus)
        image_digest = gpu_smoke.load_parabricks_mirror_image_digest(
            parabricks_container=mirror_summary["parabricks_container"],
            region=params_summary["aws_region"],
            expected_tag=mirror_summary["tag"],
        )
        smoke_summary, smoke_path = load_gpu_smoke_result_from_environment(expected_params=params_summary)
    except (gpu_smoke.GpuSmokeConfigError, Phase3FastExecuteError) as error:
        raise SystemExit(str(error)) from error

    print(
        f"Phase 3 WGS fast AWS execute preflight passed: {params_path} "
        f"queue={params_summary['aws_gpu_queue']} "
        f"compute_environment={queue_summary['compute_environment']} "
        f"compute_max_vcpus={compute_environment_summary['max_vcpus']} "
        f"running_on_demand_p_vcpus={running_on_demand_p_vcpus:g} "
        f"parabricks_mirror_receipt={mirror_path} "
        f"parabricks_image_digest={image_digest} "
        f"gpu_smoke={smoke_path} "
        f"observed_gpus={smoke_summary['observed_gpu_count']}"
    )


if __name__ == "__main__":
    main()
