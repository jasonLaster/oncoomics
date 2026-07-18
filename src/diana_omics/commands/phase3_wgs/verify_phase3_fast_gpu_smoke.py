from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import read_json

DEFAULT_PARAMS = "infra/aws/nextflow.aws.use2.json"
REQUIRED_AWS_REGION = "us-east-2"
REQUIRED_GPU_QUEUE_SUFFIX = "-gpu-p5en"
REQUIRED_INSTANCE_TYPES = ("p5en.48xlarge",)
P5EN_VCPUS = 192
PINNED_IMAGE = re.compile(r"^\S+@sha256:[0-9a-fA-F]{64}$")


class GpuSmokeConfigError(ValueError):
    """Raised when the P5en smoke task is not safe to submit."""


def _require_non_empty_string(params: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key} must be set")
        return ""
    return value.strip()


def _require_use2_s3_uri(params: Mapping[str, Any], key: str, errors: list[str]) -> None:
    value = _require_non_empty_string(params, key, errors)
    if not value:
        return
    if not value.startswith("s3://") or "/" not in value[5:]:
        errors.append(f"{key} must be an S3 URI")
        return
    bucket = value[5:].split("/", 1)[0]
    if REQUIRED_AWS_REGION not in bucket:
        errors.append(f"{key} bucket must be region-local to {REQUIRED_AWS_REGION}")


def _require_int_at_least(params: Mapping[str, Any], key: str, minimum: int, errors: list[str]) -> int:
    value = params.get(key)
    if not isinstance(value, int):
        errors.append(f"{key} must be an integer")
        return 0
    if value < minimum:
        errors.append(f"{key} must be at least {minimum} vCPUs")
    return value


def validate_gpu_smoke_params(params: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []

    region = params.get("aws_region")
    if region != REQUIRED_AWS_REGION:
        errors.append(f"aws_region must be {REQUIRED_AWS_REGION}")

    queue = _require_non_empty_string(params, "aws_gpu_queue", errors)
    if queue and not queue.endswith(REQUIRED_GPU_QUEUE_SUFFIX):
        errors.append(f"aws_gpu_queue must target the isolated {REQUIRED_GPU_QUEUE_SUFFIX} queue")
    if queue and "-use2-" not in queue:
        errors.append("aws_gpu_queue must target the prod-use2 stack")

    _require_non_empty_string(params, "aws_job_role", errors)
    _require_non_empty_string(params, "aws_logs_group", errors)
    _require_use2_s3_uri(params, "aws_workdir", errors)
    _require_use2_s3_uri(params, "aws_private_results_dir", errors)

    image = _require_non_empty_string(params, "parabricks_container", errors)
    if image and PINNED_IMAGE.fullmatch(image) is None:
        errors.append("parabricks_container must be pinned as <image>@sha256:<64 hex>")

    instance_types = params.get("batch_gpu_p5en_instance_types")
    if instance_types != list(REQUIRED_INSTANCE_TYPES):
        errors.append("batch_gpu_p5en_instance_types must be exactly ['p5en.48xlarge']")

    max_vcpus = _require_int_at_least(params, "gpu_p5en_max_vcpus", P5EN_VCPUS, errors)
    if max_vcpus and max_vcpus % P5EN_VCPUS != 0:
        errors.append(f"gpu_p5en_max_vcpus must be a multiple of {P5EN_VCPUS}")

    if errors:
        raise GpuSmokeConfigError("P5en GPU smoke is not ready:\n- " + "\n- ".join(errors))

    return {
        "aws_gpu_queue": queue,
        "aws_region": REQUIRED_AWS_REGION,
        "gpu_p5en_max_vcpus": max_vcpus,
        "instance_types": list(REQUIRED_INSTANCE_TYPES),
        "status": "ready",
    }


def load_params_from_environment() -> tuple[dict[str, Any], Path]:
    path = path_from_root(os.environ.get("PHASE3_FAST_GPU_NEXTFLOW_PARAMS", DEFAULT_PARAMS))
    if not path.exists():
        raise GpuSmokeConfigError(
            f"Missing generated {REQUIRED_AWS_REGION} GPU params file: {path}. "
            "Run infra:aws:apply:use2 after the P5en quota and pinned Parabricks image are ready."
        )
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise GpuSmokeConfigError(f"{path} must contain a JSON object")
    return payload, path


def main() -> None:
    try:
        params, path = load_params_from_environment()
        summary = validate_gpu_smoke_params(params)
    except GpuSmokeConfigError as error:
        raise SystemExit(str(error)) from error
    print(f"Phase 3 WGS fast GPU smoke config passed: {path} queue={summary['aws_gpu_queue']} max_vcpus={summary['gpu_p5en_max_vcpus']}")


if __name__ == "__main__":
    main()
