from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from . import verify_parabricks_mirror_receipt as mirror_receipt
from .safe_json_output import read_real_json

DEFAULT_PARAMS = "infra/aws/nextflow.aws.use2.json"
REQUIRED_AWS_REGION = "us-east-2"
REQUIRED_GPU_QUEUE_SUFFIX = "-gpu-p5en"
REQUIRED_INSTANCE_TYPES = ("p5en.48xlarge", "p5e.48xlarge", "p5.48xlarge")
REQUIRED_DAILY_COST_GUARD_REGIONS = ("us-east-1", "us-east-2", "us-west-2")
P5_HOPPER_48XLARGE_VCPUS = 192
EC2_SERVICE_CODE = "ec2"
ON_DEMAND_P_QUOTA_CODE = "L-417A185B"
BATCH_GPU_COMPUTE_ENVIRONMENT_SUFFIX = "-ondemand"
MAX_DAILY_COST_GUARD_LIMIT_USD = Decimal("200")
MAX_DAILY_COST_GUARD_LIVE_STOP_PERCENT = Decimal("80")
COST_GUARD_TAG_KEY = "DianaBatchCostGuard"
COST_GUARD_TAG_VALUE = "diana-omics"
KMS_KEY_ARN = re.compile(r"^arn:aws:kms:([a-z]{2}-[a-z]+-\d):(\d{12}):key/[A-Za-z0-9-]+$")
ECR_REPOSITORY = re.compile(r"^\d{12}\.dkr\.ecr\.([a-z]{2}-[a-z]+-\d)\.amazonaws\.com/[a-z0-9][a-z0-9._/-]*$")
PINNED_IMAGE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")


class GpuSmokeConfigError(ValueError):
    """Raised when the P5 Hopper smoke task is not safe to submit."""


def _require_non_empty_string(params: Mapping[str, Any], key: str, errors: list[str]) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key} must be set")
        return ""
    if value != value.strip():
        errors.append(f"{key} must not include surrounding whitespace")
    return value


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
    if type(value) is not int:
        errors.append(f"{key} must be an integer")
        return 0
    if value < minimum:
        errors.append(f"{key} must be at least {minimum} vCPUs")
    return value


def _require_decimal_at_most(
    params: Mapping[str, Any],
    key: str,
    maximum: Decimal,
    errors: list[str],
) -> Decimal:
    value = params.get(key)
    if isinstance(value, bool):
        errors.append(f"{key} must be a positive decimal")
        return Decimal(0)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        errors.append(f"{key} must be a positive decimal")
        return Decimal(0)
    if parsed <= 0:
        errors.append(f"{key} must be a positive decimal")
    if parsed > maximum:
        errors.append(f"{key} must be no more than {maximum}")
    return parsed


def _require_cost_guard_list(
    params: Mapping[str, Any],
    key: str,
    required: str,
    errors: list[str],
) -> None:
    values = params.get(key)
    if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
        errors.append(f"{key} must be a list of non-empty strings")
        return
    if required not in values:
        errors.append(f"{key} must include {required}")


def _require_daily_cost_guard_regions(params: Mapping[str, Any], errors: list[str]) -> None:
    regions = params.get("daily_cost_guard_regions")
    if regions != list(REQUIRED_DAILY_COST_GUARD_REGIONS):
        errors.append(f"daily_cost_guard_regions must be exactly {list(REQUIRED_DAILY_COST_GUARD_REGIONS)!r}")


def _require_daily_cost_guard_ledger(params: Mapping[str, Any], errors: list[str]) -> str:
    ledger = _require_non_empty_string(params, "daily_cost_guard_ledger", errors)
    if ledger and not ledger.startswith("diana-omics-prod-use2-"):
        errors.append("daily_cost_guard_ledger must target the prod-use2 daily cost guard ledger")
    if ledger and not ledger.endswith("-daily-cost-guard-ledger"):
        errors.append("daily_cost_guard_ledger must name the Terraform-managed daily cost guard ledger")
    return ledger


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

    cost_guard_limit = _require_decimal_at_most(
        params,
        "daily_cost_guard_limit_usd",
        MAX_DAILY_COST_GUARD_LIMIT_USD,
        errors,
    )
    live_stop_threshold = _require_decimal_at_most(
        params,
        "daily_cost_guard_live_stop_threshold_percent",
        MAX_DAILY_COST_GUARD_LIVE_STOP_PERCENT,
        errors,
    )
    live_stop_usd = _require_decimal_at_most(
        params,
        "daily_cost_guard_live_stop_usd",
        MAX_DAILY_COST_GUARD_LIMIT_USD * MAX_DAILY_COST_GUARD_LIVE_STOP_PERCENT / Decimal(100),
        errors,
    )
    if live_stop_usd != cost_guard_limit * live_stop_threshold / Decimal(100):
        errors.append("daily_cost_guard_live_stop_usd must match the live stop threshold")
    _require_daily_cost_guard_regions(params, errors)
    ledger = _require_daily_cost_guard_ledger(params, errors)
    if queue:
        _require_cost_guard_list(
            params,
            "daily_cost_guard_batch_job_queues",
            queue,
            errors,
        )
        _require_cost_guard_list(
            params,
            "daily_cost_guard_batch_compute_environments",
            f"{queue}{BATCH_GPU_COMPUTE_ENVIRONMENT_SUFFIX}",
            errors,
        )

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
        errors.append(f"batch_gpu_p5en_instance_types must be exactly {list(REQUIRED_INSTANCE_TYPES)!r}")

    max_vcpus = _require_int_at_least(params, "gpu_p5en_max_vcpus", P5_HOPPER_48XLARGE_VCPUS, errors)
    if max_vcpus and max_vcpus % P5_HOPPER_48XLARGE_VCPUS != 0:
        errors.append(f"gpu_p5en_max_vcpus must be a multiple of {P5_HOPPER_48XLARGE_VCPUS}")

    if errors:
        raise GpuSmokeConfigError("P5 Hopper GPU smoke is not ready:\n- " + "\n- ".join(errors))

    return {
        "aws_gpu_queue": queue,
        "aws_region": REQUIRED_AWS_REGION,
        "parabricks_container": image,
        "parabricks_mirror_repository": mirror,
        "phase3_fast_cache_kms_key_arn": cache_kms_key_arn,
        "phase3_fast_cache_region": REQUIRED_AWS_REGION,
        "gpu_p5en_max_vcpus": max_vcpus,
        "daily_cost_guard_ledger": ledger,
        "daily_cost_guard_limit_usd": str(cost_guard_limit),
        "daily_cost_guard_live_stop_usd": str(live_stop_usd),
        "daily_cost_guard_live_stop_threshold_percent": str(live_stop_threshold),
        "daily_cost_guard_regions": list(REQUIRED_DAILY_COST_GUARD_REGIONS),
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


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _parse_dynamodb_number(value: Any, label: str) -> Decimal:
    if not isinstance(value, dict) or set(value) != {"N"}:
        raise GpuSmokeConfigError(f"DynamoDB {label} must be a number attribute")
    raw = value.get("N")
    if not isinstance(raw, str) or not raw:
        raise GpuSmokeConfigError(f"DynamoDB {label} must be a number string")
    try:
        parsed = Decimal(raw)
    except InvalidOperation as error:
        raise GpuSmokeConfigError(f"DynamoDB {label} must be a decimal number") from error
    if parsed < 0:
        raise GpuSmokeConfigError(f"DynamoDB {label} must be non-negative")
    return parsed


def parse_daily_cost_guard_ledger_item(payload: Mapping[str, Any]) -> Decimal:
    item = payload.get("Item")
    if item is None:
        return Decimal(0)
    if not isinstance(item, dict):
        raise GpuSmokeConfigError("DynamoDB daily cost guard Item must be a JSON object")
    return _parse_dynamodb_number(item.get("estimated_daily_ec2_usd"), "estimated_daily_ec2_usd")


def load_daily_cost_guard_estimated_spend(
    *,
    ledger: str,
    region: str,
    guard_day: str | None = None,
    aws_cli: str = "aws",
) -> Decimal:
    day = guard_day or _today_utc()
    try:
        result = subprocess.run(
            [
                aws_cli,
                "dynamodb",
                "get-item",
                "--region",
                region,
                "--table-name",
                ledger,
                "--key",
                json.dumps({"guard_day": {"S": day}}, sort_keys=True),
                "--consistent-read",
                "--output",
                "json",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as error:
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify today's Diana Batch EC2 spend") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(
            f"Unable to read the {region} daily cost guard ledger {ledger}{detail}"
        ) from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GpuSmokeConfigError("DynamoDB daily cost guard ledger did not return JSON") from error

    if not isinstance(payload, dict):
        raise GpuSmokeConfigError("DynamoDB daily cost guard response must be a JSON object")
    return parse_daily_cost_guard_ledger_item(payload)


def validate_daily_cost_guard_estimated_spend(
    estimated_daily_ec2_usd: Decimal,
    *,
    live_stop_usd: str,
) -> None:
    try:
        stop = Decimal(live_stop_usd)
    except InvalidOperation as error:
        raise GpuSmokeConfigError("daily_cost_guard_live_stop_usd must be a decimal") from error
    if stop <= 0:
        raise GpuSmokeConfigError("daily_cost_guard_live_stop_usd must be positive")
    if estimated_daily_ec2_usd >= stop:
        raise GpuSmokeConfigError(
            f"Daily Batch EC2 cost guard is already at ${estimated_daily_ec2_usd:.6f}; "
            f"refusing P5 Hopper submission at the ${stop:.6f} live stop"
        )


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
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify the live P5 Hopper Batch queue") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(f"Unable to read the live {region} P5 Hopper Batch queue {queue}{detail}") from error

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
        raise GpuSmokeConfigError(f"AWS Batch must return exactly one P5 Hopper queue for {queue}")
    observed = queues[0]
    if not isinstance(observed, dict):
        raise GpuSmokeConfigError("AWS Batch P5 Hopper queue must be a JSON object")
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
        errors.append("P5 Hopper Batch queue must be ENABLED")
    if payload.get("status") != "VALID":
        errors.append("P5 Hopper Batch queue must be VALID")

    compute_environments = payload.get("computeEnvironmentOrder")
    compute_environment = ""
    if not isinstance(compute_environments, list) or len(compute_environments) != 1:
        errors.append("P5 Hopper Batch queue must route to exactly one compute environment")
    else:
        entry = compute_environments[0]
        if not isinstance(entry, dict):
            errors.append("P5 Hopper Batch compute environment order entry must be a JSON object")
        else:
            order = entry.get("order")
            if type(order) is not int:
                errors.append("P5 Hopper Batch compute environment order must be an integer")
            elif order != 1:
                errors.append("P5 Hopper Batch compute environment order must be 1")

            value = entry.get("computeEnvironment")
            if not isinstance(value, str) or not value:
                errors.append("P5 Hopper Batch compute environment ARN must be set")
            elif not value.endswith(f":compute-environment/{expected_queue}{BATCH_GPU_COMPUTE_ENVIRONMENT_SUFFIX}"):
                errors.append("P5 Hopper Batch queue must route only to its isolated P5 compute environment")
            else:
                compute_environment = value

    if errors:
        raise GpuSmokeConfigError("P5 Hopper Batch queue is not ready:\n- " + "\n- ".join(errors))

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
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify the live P5 Hopper compute environment") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(f"Unable to read the live {region} P5 Hopper compute environment {compute_environment}{detail}") from error

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
        raise GpuSmokeConfigError(f"AWS Batch must return exactly one P5 Hopper compute environment for {compute_environment}")
    observed = compute_environments[0]
    if not isinstance(observed, dict):
        raise GpuSmokeConfigError("AWS Batch P5 Hopper compute environment must be a JSON object")
    return observed


def validate_gpu_batch_compute_environment(
    payload: Mapping[str, Any],
    *,
    expected_compute_environment: str,
) -> dict[str, Any]:
    errors: list[str] = []

    if payload.get("computeEnvironmentArn") != expected_compute_environment:
        errors.append("P5 Hopper compute environment ARN must match the GPU queue")
    if payload.get("type") != "MANAGED":
        errors.append("P5 Hopper compute environment must be MANAGED")
    if payload.get("state") != "ENABLED":
        errors.append("P5 Hopper compute environment must be ENABLED")
    if payload.get("status") != "VALID":
        errors.append("P5 Hopper compute environment must be VALID")

    resources = payload.get("computeResources")
    max_vcpus = 0
    instance_types: list[str] = []
    pinned_launch_template: dict[str, str] = {}
    if not isinstance(resources, dict):
        errors.append("P5 Hopper computeResources must be a JSON object")
    else:
        if resources.get("type") != "EC2":
            errors.append("P5 Hopper computeResources type must be EC2")

        observed_min_vcpus = resources.get("minvCpus")
        if type(observed_min_vcpus) is not int:
            errors.append("P5 Hopper computeResources minvCpus must be an integer")
        elif observed_min_vcpus != 0:
            errors.append("P5 Hopper computeResources minvCpus must be 0")

        observed_instance_types = resources.get("instanceTypes")
        if observed_instance_types != list(REQUIRED_INSTANCE_TYPES):
            errors.append(f"P5 Hopper computeResources instanceTypes must be exactly {list(REQUIRED_INSTANCE_TYPES)!r}")
        else:
            instance_types = observed_instance_types

        observed_max_vcpus = resources.get("maxvCpus")
        if type(observed_max_vcpus) is not int:
            errors.append("P5 Hopper computeResources maxvCpus must be an integer")
        elif observed_max_vcpus < P5_HOPPER_48XLARGE_VCPUS:
            errors.append(f"P5 Hopper computeResources maxvCpus must be at least {P5_HOPPER_48XLARGE_VCPUS}")
        elif observed_max_vcpus % P5_HOPPER_48XLARGE_VCPUS:
            errors.append(f"P5 Hopper computeResources maxvCpus must be a multiple of {P5_HOPPER_48XLARGE_VCPUS}")
        else:
            max_vcpus = observed_max_vcpus

        ec2_configuration = resources.get("ec2Configuration")
        if ec2_configuration != [{"imageType": "ECS_AL2023_NVIDIA"}]:
            errors.append("P5 Hopper computeResources ec2Configuration must be exactly ECS_AL2023_NVIDIA")

        allocation_strategy = resources.get("allocationStrategy")
        if allocation_strategy != "BEST_FIT_PROGRESSIVE":
            errors.append("P5 Hopper computeResources allocationStrategy must be BEST_FIT_PROGRESSIVE")

        launch_template = resources.get("launchTemplate")
        if not isinstance(launch_template, dict):
            errors.append("P5 Hopper computeResources launchTemplate must be configured")
        else:
            launch_template_id = launch_template.get("launchTemplateId")
            launch_template_name = launch_template.get("launchTemplateName")
            if isinstance(launch_template_id, str) and launch_template_id:
                pinned_launch_template["launchTemplateId"] = launch_template_id
            elif isinstance(launch_template_name, str) and launch_template_name:
                pinned_launch_template["launchTemplateName"] = launch_template_name
            else:
                errors.append("P5 Hopper computeResources launchTemplate must include an id or name")
            version = launch_template.get("version")
            if not isinstance(version, str) or not re.fullmatch(r"[1-9]\d*", version):
                errors.append("P5 Hopper computeResources launchTemplate version must be pinned to a numeric version")
            else:
                pinned_launch_template["version"] = version

    if errors:
        raise GpuSmokeConfigError("P5 Hopper compute environment is not ready:\n- " + "\n- ".join(errors))

    return {
        "compute_environment": expected_compute_environment,
        "instance_types": instance_types,
        "launch_template": pinned_launch_template,
        "max_vcpus": max_vcpus,
        "status": "ready",
    }


def load_batch_launch_template_version(
    *,
    launch_template: Mapping[str, Any],
    region: str,
    aws_cli: str = "aws",
) -> dict[str, Any]:
    errors: list[str] = []
    version = _require_non_empty_string(launch_template, "version", errors)
    if errors:
        raise GpuSmokeConfigError("P5 Hopper launch template is not ready:\n- " + "\n- ".join(errors))
    command = [
        aws_cli,
        "ec2",
        "describe-launch-template-versions",
        "--region",
        region,
        "--versions",
        version,
        "--output",
        "json",
    ]
    launch_template_id = launch_template.get("launchTemplateId")
    launch_template_name = launch_template.get("launchTemplateName")
    if isinstance(launch_template_id, str) and launch_template_id:
        command.extend(["--launch-template-id", launch_template_id])
    elif isinstance(launch_template_name, str) and launch_template_name:
        command.extend(["--launch-template-name", launch_template_name])
    else:
        raise GpuSmokeConfigError("P5 Hopper launch template must include an id or name")

    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as error:
        raise GpuSmokeConfigError(f"{aws_cli} is required to verify the P5 Hopper launch template") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise GpuSmokeConfigError(f"Unable to read the live {region} P5 Hopper launch template{detail}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GpuSmokeConfigError("EC2 did not return launch-template JSON") from error

    if not isinstance(payload, dict):
        raise GpuSmokeConfigError("EC2 launch-template response must be a JSON object")
    versions = payload.get("LaunchTemplateVersions")
    if not isinstance(versions, list):
        raise GpuSmokeConfigError("EC2 launch-template response must include a LaunchTemplateVersions array")
    if len(versions) != 1:
        raise GpuSmokeConfigError("EC2 must return exactly one P5 Hopper launch-template version")
    observed = versions[0]
    if not isinstance(observed, dict):
        raise GpuSmokeConfigError("EC2 P5 Hopper launch-template version must be a JSON object")
    return observed


def _tag_specification_has_cost_guard_tag(specification: Any, resource_type: str) -> bool:
    if not isinstance(specification, dict) or specification.get("ResourceType") != resource_type:
        return False
    tags = specification.get("Tags")
    return isinstance(tags, list) and any(
        isinstance(tag, dict)
        and tag.get("Key") == COST_GUARD_TAG_KEY
        and tag.get("Value") == COST_GUARD_TAG_VALUE
        for tag in tags
    )


def validate_batch_launch_template_cost_guard_tags(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = payload.get("LaunchTemplateData")
    if not isinstance(data, dict):
        raise GpuSmokeConfigError("P5 Hopper launch template must include LaunchTemplateData")
    tag_specifications = data.get("TagSpecifications")
    if not isinstance(tag_specifications, list):
        raise GpuSmokeConfigError("P5 Hopper launch template must include TagSpecifications")

    required_resource_types = ("instance", "volume")
    tagged_resource_types = [
        resource_type
        for resource_type in required_resource_types
        if any(
            _tag_specification_has_cost_guard_tag(specification, resource_type)
            for specification in tag_specifications
        )
    ]
    missing = sorted(set(required_resource_types) - set(tagged_resource_types))
    if missing:
        raise GpuSmokeConfigError(
            "P5 Hopper launch template must tag Batch EC2 resources for the daily cost guard: "
            + ", ".join(missing)
        )

    return {
        "cost_guard_tag": f"{COST_GUARD_TAG_KEY}={COST_GUARD_TAG_VALUE}",
        "status": "ready",
        "tagged_resource_types": tagged_resource_types,
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


def validate_running_on_demand_p_quota(value: float, *, minimum: int = P5_HOPPER_48XLARGE_VCPUS) -> None:
    if value < minimum:
        raise GpuSmokeConfigError(
            f"Running On-Demand P instances quota is {value:g} vCPUs; phase3_wgs_fast needs at least {minimum} vCPUs for one P5 48xlarge"
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
        estimated_daily_ec2_usd = load_daily_cost_guard_estimated_spend(
            ledger=summary["daily_cost_guard_ledger"],
            region=summary["aws_region"],
        )
        validate_daily_cost_guard_estimated_spend(
            estimated_daily_ec2_usd,
            live_stop_usd=summary["daily_cost_guard_live_stop_usd"],
        )
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
        f"estimated_daily_batch_ec2_usd={estimated_daily_ec2_usd:.6f} "
        f"compute_environment={queue_summary['compute_environment']} "
        f"compute_max_vcpus={compute_environment_summary['max_vcpus']} "
        f"max_vcpus={summary['gpu_p5en_max_vcpus']} "
        f"running_on_demand_p_vcpus={running_on_demand_p_vcpus:g} "
        f"parabricks_mirror_receipt={mirror_path} "
        f"parabricks_image_digest={image_digest}"
    )


if __name__ == "__main__":
    main()
