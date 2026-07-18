from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from . import verify_parabricks_mirror_receipt as mirror_receipt
from .safe_json_output import read_real_json

DEFAULT_PARAMS = "infra/aws/nextflow.aws.use2.json"
REQUIRED_AWS_REGION = "us-east-2"
REQUIRED_GPU_QUEUE_SUFFIX = "-gpu-p5en"
REQUIRED_INSTANCE_TYPES = ("p5en.48xlarge",)
P5EN_VCPUS = 192
EC2_SERVICE_CODE = "ec2"
ON_DEMAND_P_QUOTA_CODE = "L-417A185B"
BATCH_GPU_COMPUTE_ENVIRONMENT_SUFFIX = "-ondemand"
KMS_KEY_ARN = re.compile(r"^arn:aws:kms:([a-z]{2}-[a-z]+-\d):(\d{12}):key/[A-Za-z0-9-]+$")
ECR_REPOSITORY = re.compile(r"^\d{12}\.dkr\.ecr\.([a-z]{2}-[a-z]+-\d)\.amazonaws\.com/[a-z0-9][a-z0-9._/-]*$")
PINNED_IMAGE = re.compile(r"^\S+@sha256:[0-9a-fA-F]{64}$")


class GpuSmokeConfigError(ValueError):
    """Raised when the P5en smoke task is not safe to submit."""


def _require_non_empty_string(params: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key} must be set")
        return ""
    return value.strip()


def _require_use2_s3_uri(params: Mapping[str, Any], key: str, errors: list[str]) -> str | None:
    value = _require_non_empty_string(params, key, errors)
    if not value:
        return None
    if not value.startswith("s3://") or "/" not in value[5:]:
        errors.append(f"{key} must be an S3 URI")
        return None
    bucket = value[5:].split("/", 1)[0]
    if not bucket.endswith(f"-{REQUIRED_AWS_REGION}"):
        errors.append(f"{key} bucket must end with -{REQUIRED_AWS_REGION}")
    return value.rstrip("/")


def _require_use2_kms_key_arn(params: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = _require_non_empty_string(params, key, errors)
    if not value:
        return ""
    match = KMS_KEY_ARN.fullmatch(value)
    if match is None or match.group(1) != REQUIRED_AWS_REGION:
        errors.append(f"{key} must be a KMS key ARN in {REQUIRED_AWS_REGION}")
    return value


def _require_use2_ecr_repository(params: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = _require_non_empty_string(params, key, errors)
    if not value:
        return ""
    match = ECR_REPOSITORY.fullmatch(value.rstrip("/"))
    if match is None or match.group(1) != REQUIRED_AWS_REGION:
        errors.append(f"{key} must be an ECR repository URI in {REQUIRED_AWS_REGION}")
    return value.rstrip("/")


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

    cache_region = params.get("phase3_fast_cache_region")
    if cache_region != REQUIRED_AWS_REGION:
        errors.append(f"phase3_fast_cache_region must be {REQUIRED_AWS_REGION}")

    queue = _require_non_empty_string(params, "aws_gpu_queue", errors)
    if queue and not queue.endswith(REQUIRED_GPU_QUEUE_SUFFIX):
        errors.append(f"aws_gpu_queue must target the isolated {REQUIRED_GPU_QUEUE_SUFFIX} queue")
    if queue and "-use2-" not in queue:
        errors.append("aws_gpu_queue must target the prod-use2 stack")

    _require_non_empty_string(params, "aws_job_role", errors)
    _require_non_empty_string(params, "aws_logs_group", errors)
    _require_use2_s3_uri(params, "aws_workdir", errors)
    private_results_dir = _require_use2_s3_uri(params, "aws_private_results_dir", errors)
    cache_prefix = _require_use2_s3_uri(params, "phase3_fast_cache_prefix", errors)
    cache_kms_key_arn = _require_use2_kms_key_arn(params, "phase3_fast_cache_kms_key_arn", errors)
    if private_results_dir and cache_prefix:
        private_results_bucket = private_results_dir[5:].split("/", 1)[0]
        cache_bucket = cache_prefix[5:].split("/", 1)[0]
        if cache_bucket != private_results_bucket:
            errors.append("phase3_fast_cache_prefix must use the private results bucket")
        if not cache_prefix.endswith("/phase3-fast-cache/wgs-v2"):
            errors.append("phase3_fast_cache_prefix must end with /phase3-fast-cache/wgs-v2")

    mirror = _require_use2_ecr_repository(params, "parabricks_mirror_repository", errors)

    image = _require_non_empty_string(params, "parabricks_container", errors)
    if image and PINNED_IMAGE.fullmatch(image) is None:
        errors.append("parabricks_container must be pinned as <image>@sha256:<64 hex>")
    if image and mirror and not image.startswith(f"{mirror}@sha256:"):
        errors.append("parabricks_container must be pinned to parabricks_mirror_repository")

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
        "parabricks_container": image,
        "parabricks_mirror_repository": mirror,
        "phase3_fast_cache_kms_key_arn": cache_kms_key_arn,
        "phase3_fast_cache_region": REQUIRED_AWS_REGION,
        "gpu_p5en_max_vcpus": max_vcpus,
        "instance_types": list(REQUIRED_INSTANCE_TYPES),
        "status": "ready",
    }


def load_params_from_environment() -> tuple[dict[str, Any], Path]:
    path = path_from_root(os.environ.get("PHASE3_FAST_GPU_NEXTFLOW_PARAMS", DEFAULT_PARAMS))
    payload = read_real_json(
        path,
        f"Generated {REQUIRED_AWS_REGION} GPU params file",
        GpuSmokeConfigError,
    )
    if not isinstance(payload, dict):
        raise GpuSmokeConfigError(f"{path} must contain a JSON object")
    return payload, path


def load_gpu_batch_job_queue(
    *,
    queue: str,
    region: str,
    aws_cli: str = "aws",
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                aws_cli,
                "batch",
                "describe-job-queues",
                "--region",
                region,
                "--job-queues",
                queue,
                "--output",
                "json",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as error:
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify the live P5en Batch queue") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(f"Unable to read the live {region} P5en Batch queue {queue}{detail}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GpuSmokeConfigError("AWS Batch did not return JSON") from error

    if not isinstance(payload, dict):
        raise GpuSmokeConfigError("AWS Batch response must be a JSON object")
    queues = payload.get("jobQueues")
    if not isinstance(queues, list):
        raise GpuSmokeConfigError("AWS Batch response must include a jobQueues array")
    if len(queues) != 1:
        raise GpuSmokeConfigError(f"AWS Batch must return exactly one P5en queue for {queue}")
    observed = queues[0]
    if not isinstance(observed, dict):
        raise GpuSmokeConfigError("AWS Batch P5en queue must be a JSON object")
    return observed


def validate_gpu_batch_job_queue(
    payload: Mapping[str, Any],
    *,
    expected_queue: str,
) -> dict[str, str]:
    errors: list[str] = []

    queue_name = payload.get("jobQueueName")
    if queue_name != expected_queue:
        errors.append(f"jobQueueName must be {expected_queue}")

    if payload.get("state") != "ENABLED":
        errors.append("P5en Batch queue must be ENABLED")
    if payload.get("status") != "VALID":
        errors.append("P5en Batch queue must be VALID")

    compute_environments = payload.get("computeEnvironmentOrder")
    compute_environment = ""
    if not isinstance(compute_environments, list) or len(compute_environments) != 1:
        errors.append("P5en Batch queue must route to exactly one compute environment")
    else:
        entry = compute_environments[0]
        if not isinstance(entry, dict):
            errors.append("P5en Batch compute environment order entry must be a JSON object")
        else:
            order = entry.get("order")
            if type(order) is not int:
                errors.append("P5en Batch compute environment order must be an integer")
            elif order != 1:
                errors.append("P5en Batch compute environment order must be 1")

            value = entry.get("computeEnvironment")
            if not isinstance(value, str) or not value:
                errors.append("P5en Batch compute environment ARN must be set")
            elif not value.endswith(f":compute-environment/{expected_queue}{BATCH_GPU_COMPUTE_ENVIRONMENT_SUFFIX}"):
                errors.append("P5en Batch queue must route only to its isolated P5en compute environment")
            else:
                compute_environment = value

    if errors:
        raise GpuSmokeConfigError("P5en Batch queue is not ready:\n- " + "\n- ".join(errors))

    return {
        "compute_environment": compute_environment,
        "job_queue": expected_queue,
        "status": "ready",
    }


def load_gpu_batch_compute_environment(
    *,
    compute_environment: str,
    region: str,
    aws_cli: str = "aws",
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                aws_cli,
                "batch",
                "describe-compute-environments",
                "--region",
                region,
                "--compute-environments",
                compute_environment,
                "--output",
                "json",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as error:
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify the live P5en compute environment") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(f"Unable to read the live {region} P5en compute environment {compute_environment}{detail}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GpuSmokeConfigError("AWS Batch did not return compute-environment JSON") from error

    if not isinstance(payload, dict):
        raise GpuSmokeConfigError("AWS Batch compute-environment response must be a JSON object")
    compute_environments = payload.get("computeEnvironments")
    if not isinstance(compute_environments, list):
        raise GpuSmokeConfigError("AWS Batch response must include a computeEnvironments array")
    if len(compute_environments) != 1:
        raise GpuSmokeConfigError(f"AWS Batch must return exactly one P5en compute environment for {compute_environment}")
    observed = compute_environments[0]
    if not isinstance(observed, dict):
        raise GpuSmokeConfigError("AWS Batch P5en compute environment must be a JSON object")
    return observed


def validate_gpu_batch_compute_environment(
    payload: Mapping[str, Any],
    *,
    expected_compute_environment: str,
) -> dict[str, Any]:
    errors: list[str] = []

    if payload.get("computeEnvironmentArn") != expected_compute_environment:
        errors.append("P5en compute environment ARN must match the GPU queue")
    if payload.get("type") != "MANAGED":
        errors.append("P5en compute environment must be MANAGED")
    if payload.get("state") != "ENABLED":
        errors.append("P5en compute environment must be ENABLED")
    if payload.get("status") != "VALID":
        errors.append("P5en compute environment must be VALID")

    resources = payload.get("computeResources")
    max_vcpus = 0
    instance_types: list[str] = []
    if not isinstance(resources, dict):
        errors.append("P5en computeResources must be a JSON object")
    else:
        if resources.get("type") != "EC2":
            errors.append("P5en computeResources type must be EC2")

        observed_min_vcpus = resources.get("minvCpus")
        if type(observed_min_vcpus) is not int:
            errors.append("P5en computeResources minvCpus must be an integer")
        elif observed_min_vcpus != 0:
            errors.append("P5en computeResources minvCpus must be 0")

        observed_instance_types = resources.get("instanceTypes")
        if observed_instance_types != list(REQUIRED_INSTANCE_TYPES):
            errors.append("P5en computeResources instanceTypes must be exactly ['p5en.48xlarge']")
        else:
            instance_types = observed_instance_types

        observed_max_vcpus = resources.get("maxvCpus")
        if type(observed_max_vcpus) is not int:
            errors.append("P5en computeResources maxvCpus must be an integer")
        elif observed_max_vcpus < P5EN_VCPUS:
            errors.append(f"P5en computeResources maxvCpus must be at least {P5EN_VCPUS}")
        elif observed_max_vcpus % P5EN_VCPUS:
            errors.append(f"P5en computeResources maxvCpus must be a multiple of {P5EN_VCPUS}")
        else:
            max_vcpus = observed_max_vcpus

        ec2_configuration = resources.get("ec2Configuration")
        if ec2_configuration != [{"imageType": "ECS_AL2023_NVIDIA"}]:
            errors.append("P5en computeResources ec2Configuration must be exactly ECS_AL2023_NVIDIA")

        allocation_strategy = resources.get("allocationStrategy")
        if allocation_strategy != "BEST_FIT_PROGRESSIVE":
            errors.append("P5en computeResources allocationStrategy must be BEST_FIT_PROGRESSIVE")

        launch_template = resources.get("launchTemplate")
        if not isinstance(launch_template, dict):
            errors.append("P5en computeResources launchTemplate must be configured")
        else:
            launch_template_identity = (
                launch_template.get("launchTemplateId"),
                launch_template.get("launchTemplateName"),
            )
            if not any(isinstance(value, str) and value for value in launch_template_identity):
                errors.append("P5en computeResources launchTemplate must include an id or name")
            version = launch_template.get("version")
            if not isinstance(version, str) or not re.fullmatch(r"[1-9]\d*", version):
                errors.append("P5en computeResources launchTemplate version must be pinned to a numeric version")

    if errors:
        raise GpuSmokeConfigError("P5en compute environment is not ready:\n- " + "\n- ".join(errors))

    return {
        "compute_environment": expected_compute_environment,
        "instance_types": instance_types,
        "max_vcpus": max_vcpus,
        "status": "ready",
    }


def load_running_on_demand_p_vcpus(region: str, *, aws_cli: str = "aws") -> float:
    try:
        result = subprocess.run(
            [
                aws_cli,
                "service-quotas",
                "get-service-quota",
                "--region",
                region,
                "--service-code",
                EC2_SERVICE_CODE,
                "--quota-code",
                ON_DEMAND_P_QUOTA_CODE,
                "--output",
                "json",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as error:
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify the live On-Demand P quota") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(f"Unable to read the live {region} Running On-Demand P instances quota{detail}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GpuSmokeConfigError("Service Quotas did not return JSON") from error

    if not isinstance(payload, dict):
        raise GpuSmokeConfigError("Service Quotas response must be a JSON object")
    quota = payload.get("Quota")
    if not isinstance(quota, dict):
        raise GpuSmokeConfigError("Service Quotas response must include a Quota object")
    value = quota.get("Value")
    if not isinstance(value, (float, int)) or isinstance(value, bool):
        raise GpuSmokeConfigError("Running On-Demand P instances quota Value must be numeric")
    return float(value)


def validate_running_on_demand_p_quota(value: float, *, minimum: int = P5EN_VCPUS) -> None:
    if value < minimum:
        raise GpuSmokeConfigError(
            f"Running On-Demand P instances quota is {value:g} vCPUs; phase3_wgs_fast needs at least {minimum} vCPUs for one p5en.48xlarge"
        )


def load_parabricks_mirror_image_digest(
    *,
    parabricks_container: str,
    region: str,
    expected_tag: str | None = None,
    aws_cli: str = "aws",
) -> str:
    repository, digest = parabricks_container.split("@", 1)
    repository_name = repository.split("/", 1)[1]

    try:
        result = subprocess.run(
            [
                aws_cli,
                "ecr",
                "describe-images",
                "--region",
                region,
                "--repository-name",
                repository_name,
                "--image-ids",
                f"imageDigest={digest}",
                "--output",
                "json",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as error:
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify the mirrored Parabricks image") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(f"Unable to find mirrored Parabricks image {parabricks_container}{detail}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GpuSmokeConfigError("ECR did not return JSON") from error

    try:
        return mirror_receipt.validate_ecr_image_details(
            payload,
            parabricks_container=parabricks_container,
            expected_digest=digest,
            expected_tag=expected_tag,
        )
    except mirror_receipt.MirrorReceiptError as error:
        raise GpuSmokeConfigError(str(error)) from error


def load_mirror_receipt_for_smoke(*, expected_params: Mapping[str, Any]) -> tuple[dict[str, str], Path]:
    try:
        receipt, path = mirror_receipt.load_receipt_from_environment()
        summary = mirror_receipt.validate_mirror_receipt(receipt)
        mirror_receipt.validate_current_diana_source_binding(summary)
    except mirror_receipt.MirrorReceiptError as error:
        raise GpuSmokeConfigError(f"Parabricks mirror receipt is not safe: {error}") from error

    if summary["parabricks_container"] != expected_params.get("parabricks_container"):
        raise GpuSmokeConfigError("Parabricks mirror receipt parabricks_container must match the current Nextflow params")
    return summary, path


def main() -> None:
    try:
        params, path = load_params_from_environment()
        summary = validate_gpu_smoke_params(params)
        queue = load_gpu_batch_job_queue(queue=summary["aws_gpu_queue"], region=summary["aws_region"])
        queue_summary = validate_gpu_batch_job_queue(queue, expected_queue=summary["aws_gpu_queue"])
        compute_environment = load_gpu_batch_compute_environment(
            compute_environment=queue_summary["compute_environment"],
            region=summary["aws_region"],
        )
        compute_environment_summary = validate_gpu_batch_compute_environment(
            compute_environment,
            expected_compute_environment=queue_summary["compute_environment"],
        )
        mirror_summary, mirror_path = load_mirror_receipt_for_smoke(expected_params=summary)
        running_on_demand_p_vcpus = load_running_on_demand_p_vcpus(summary["aws_region"])
        validate_running_on_demand_p_quota(running_on_demand_p_vcpus)
        image_digest = load_parabricks_mirror_image_digest(
            parabricks_container=mirror_summary["parabricks_container"],
            region=summary["aws_region"],
            expected_tag=mirror_summary["tag"],
        )
    except GpuSmokeConfigError as error:
        raise SystemExit(str(error)) from error
    print(
        f"Phase 3 WGS fast GPU smoke config passed: {path} "
        f"queue={summary['aws_gpu_queue']} "
        f"compute_environment={queue_summary['compute_environment']} "
        f"compute_max_vcpus={compute_environment_summary['max_vcpus']} "
        f"max_vcpus={summary['gpu_p5en_max_vcpus']} "
        f"running_on_demand_p_vcpus={running_on_demand_p_vcpus:g} "
        f"parabricks_mirror_receipt={mirror_path} "
        f"parabricks_image_digest={image_digest}"
    )


if __name__ == "__main__":
    main()
