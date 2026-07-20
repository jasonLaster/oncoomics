#!/usr/bin/env python3
"""Disable Diana Batch queues when the daily AWS Budget guard trips."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

CANCELABLE_JOB_STATUSES = ("SUBMITTED", "PENDING", "RUNNABLE")
TERMINABLE_JOB_STATUSES = ("STARTING", "RUNNING")
ACTIVE_EC2_STATES = ("pending", "running", "stopping", "shutting-down")
MICRO_USD = Decimal("0.000001")
ZERO_USD = Decimal("0")
TERMINAL_RACE_ERROR_CODES = {"ClientException"}
COST_GUARD_REGION_FIELD = "_diana_batch_cost_guard_region"


def unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def env_string_list(name: str) -> list[str]:
    raw = os.environ.get(name, "[]")
    value = json.loads(raw)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError(f"{name} must be a JSON array of non-empty strings")
    return unique(value)


def require_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} must be a positive decimal") from error
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive decimal")
    return parsed


def env_decimal(name: str) -> Decimal:
    return require_decimal(os.environ.get(name), name)


def env_decimal_map(name: str) -> dict[str, Decimal]:
    value = json.loads(os.environ.get(name, "{}"))
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{name} must be a JSON object of positive decimal rates")
    parsed: dict[str, Decimal] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} must use non-empty string instance types")
        parsed[key] = require_decimal(raw, f"{name}.{key}")
    return parsed


def instance_hourly_rate(
    instance_type: str,
    hourly_rates: dict[str, Decimal],
    unknown_hourly_rate: Decimal,
) -> Decimal:
    family = instance_type.split(".", 1)[0]
    return hourly_rates.get(
        instance_type,
        hourly_rates.get(family, unknown_hourly_rate),
    )


def require_utc_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def today_utc(now: datetime) -> tuple[str, int]:
    current = now.astimezone(timezone.utc)
    midnight = datetime(
        current.year,
        current.month,
        current.day,
        tzinfo=timezone.utc,
    )
    return midnight.date().isoformat(), int(midnight.timestamp())


def describe_guarded_instances(
    ec2: Any,
    *,
    tag_key: str,
    tag_value: str,
    region: str | None = None,
) -> list[dict[str, Any]]:
    instances: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        request: dict[str, Any] = {
            "Filters": [
                {"Name": f"tag:{tag_key}", "Values": [tag_value]},
                {"Name": "instance-state-name", "Values": list(ACTIVE_EC2_STATES)},
            ],
        }
        if token:
            request["NextToken"] = token
        response = ec2.describe_instances(**request)
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                if region:
                    instance = {**instance, COST_GUARD_REGION_FIELD: region}
                instances.append(instance)
        token = response.get("NextToken")
        if not token:
            return instances


def describe_guarded_instances_by_region(
    ec2_clients: Mapping[str, Any],
    *,
    tag_key: str,
    tag_value: str,
) -> list[dict[str, Any]]:
    if not ec2_clients:
        raise ValueError("guarded EC2 regions must not be empty")

    instances: list[dict[str, Any]] = []
    for region, ec2 in ec2_clients.items():
        if not isinstance(region, str) or not region:
            raise ValueError("guarded EC2 regions must be non-empty strings")
        instances.extend(
            describe_guarded_instances(
                ec2,
                tag_key=tag_key,
                tag_value=tag_value,
                region=region,
            )
        )
    return instances


def decimal_or_zero(value: Any) -> Decimal:
    if value in (None, ""):
        return ZERO_USD
    return Decimal(str(value))


def int_or_zero(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, Decimal) and value >= 0 and value == value.to_integral_value():
        return int(value)
    if type(value) is not int or value < 0:
        raise ValueError("stored Batch EC2 runtime seconds must be a non-negative integer")
    return value


def update_estimated_ec2_ledger(
    ledger: dict[str, Any],
    *,
    instances: Iterable[dict[str, Any]],
    now: datetime,
    hourly_rates: dict[str, Decimal],
    unknown_hourly_rate: Decimal,
) -> dict[str, Any]:
    current = now.astimezone(timezone.utc)
    guard_day, day_start_epoch = today_utc(current)
    now_epoch = int(current.timestamp())
    observed = ledger.setdefault("instances", {})
    if not isinstance(observed, dict):
        raise ValueError("stored Batch EC2 ledger instances must be an object")

    added_usd = ZERO_USD
    active_instance_count = 0
    for instance in instances:
        instance_id = instance.get("InstanceId")
        instance_type = instance.get("InstanceType")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("guarded Batch EC2 instance omitted InstanceId")
        if not isinstance(instance_type, str) or not instance_type:
            raise ValueError(f"guarded Batch EC2 instance {instance_id} omitted InstanceType")
        guard_region = instance.get(COST_GUARD_REGION_FIELD)
        if guard_region is not None and (not isinstance(guard_region, str) or not guard_region):
            raise ValueError(f"guarded Batch EC2 instance {instance_id} has an invalid region")

        launch_time = require_utc_datetime(
            instance.get("LaunchTime"),
            f"guarded Batch EC2 instance {instance_id} LaunchTime",
        )
        ledger_key = f"{guard_region}:{instance_id}" if guard_region else instance_id
        state = observed.get(ledger_key, {})
        if not isinstance(state, dict):
            raise ValueError(f"stored Batch EC2 ledger state for {instance_id} must be an object")

        previous_epoch = int_or_zero(state.get("last_seen_epoch"))
        start_epoch = max(day_start_epoch, int(launch_time.timestamp()), previous_epoch)
        elapsed_seconds = max(0, now_epoch - start_epoch)
        rate = instance_hourly_rate(
            instance_type,
            hourly_rates,
            unknown_hourly_rate,
        )
        instance_added_usd = (
            rate * Decimal(elapsed_seconds) / Decimal(3600)
        ).quantize(MICRO_USD)
        total_seconds = int_or_zero(state.get("billable_seconds")) + elapsed_seconds
        total_usd = decimal_or_zero(state.get("estimated_usd")) + instance_added_usd

        instance_state: dict[str, Any] = {
            "billable_seconds": total_seconds,
            "estimated_usd": total_usd.quantize(MICRO_USD),
            "hourly_rate_usd": rate.quantize(MICRO_USD),
            "instance_type": instance_type,
            "last_seen_epoch": now_epoch,
        }
        if guard_region:
            instance_state["region"] = guard_region
        observed[ledger_key] = instance_state
        added_usd += instance_added_usd
        active_instance_count += 1

    estimated_daily_ec2_usd = (
        decimal_or_zero(ledger.get("estimated_daily_ec2_usd")) + added_usd
    ).quantize(MICRO_USD)
    ledger.update(
        {
            "active_instance_count": active_instance_count,
            "estimated_daily_ec2_usd": estimated_daily_ec2_usd,
            "guard_day": guard_day,
            "last_seen_epoch": now_epoch,
        }
    )
    return ledger


def load_ledger(table: Any, guard_day: str) -> dict[str, Any]:
    response = table.get_item(
        Key={"guard_day": guard_day},
        ConsistentRead=True,
    )
    return dict(
        response.get(
            "Item",
            {
                "guard_day": guard_day,
                "estimated_daily_ec2_usd": ZERO_USD,
                "instances": {},
            },
        )
    )


def save_ledger(table: Any, ledger: dict[str, Any]) -> None:
    table.put_item(Item=ledger)


def monitor_estimated_ec2_spend(
    batch: Any,
    ec2: Any | Mapping[str, Any],
    table: Any,
    *,
    job_queues: Iterable[str],
    compute_environments: Iterable[str],
    reason: str,
    tag_key: str,
    tag_value: str,
    daily_limit_usd: Decimal,
    hourly_rates: dict[str, Decimal],
    unknown_hourly_rate: Decimal,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    guard_day, _ = today_utc(current)
    if isinstance(ec2, Mapping):
        instances = describe_guarded_instances_by_region(
            ec2,
            tag_key=tag_key,
            tag_value=tag_value,
        )
    else:
        instances = describe_guarded_instances(
            ec2,
            tag_key=tag_key,
            tag_value=tag_value,
        )
    ledger = update_estimated_ec2_ledger(
        load_ledger(table, guard_day),
        instances=instances,
        now=current,
        hourly_rates=hourly_rates,
        unknown_hourly_rate=unknown_hourly_rate,
    )
    save_ledger(table, ledger)

    estimated_daily_ec2_usd = ledger["estimated_daily_ec2_usd"]
    result: dict[str, Any] = {
        "active_instance_count": ledger["active_instance_count"],
        "estimated_daily_ec2_usd": str(estimated_daily_ec2_usd),
        "guard_day": guard_day,
        "limit_usd": str(daily_limit_usd),
        "status": "monitored",
    }
    if estimated_daily_ec2_usd < daily_limit_usd:
        return result

    stop_result = stop_batch(
        batch,
        job_queues=job_queues,
        compute_environments=compute_environments,
        reason=reason,
    )
    return {**result, **stop_result}


def is_budget_sns_event(event: dict[str, Any]) -> bool:
    records = event.get("Records")
    return isinstance(records, list) and any(
        isinstance(record, dict)
        and record.get("EventSource", record.get("eventSource")) == "aws:sns"
        for record in records
    )


def list_jobs(batch: Any, queue: str, status: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        request: dict[str, str] = {"jobQueue": queue, "jobStatus": status}
        if token:
            request["nextToken"] = token
        response = batch.list_jobs(**request)
        jobs.extend(response.get("jobSummaryList", []))
        token = response.get("nextToken")
        if not token:
            return jobs


def is_terminal_race(error: Exception) -> bool:
    code = (
        getattr(error, "response", {})
        .get("Error", {})
        .get("Code")
    )
    return code in TERMINAL_RACE_ERROR_CODES


def cancel_or_terminate(
    batch: Any,
    *,
    queue: str,
    status: str,
    job: dict[str, Any],
    reason: str,
) -> str:
    job_id = str(job.get("jobId", ""))
    if not job_id:
        raise ValueError(f"Batch job in {queue} {status} omitted jobId")
    try:
        if status in TERMINABLE_JOB_STATUSES:
            batch.terminate_job(jobId=job_id, reason=reason)
            return "terminated"
        batch.cancel_job(jobId=job_id, reason=reason)
        return "cancelled"
    except Exception as error:
        if is_terminal_race(error):
            LOGGER.info("Ignoring Batch terminal-state race for %s", job_id)
            return "already_terminal"
        raise


def stop_batch(
    batch: Any,
    *,
    job_queues: Iterable[str],
    compute_environments: Iterable[str],
    reason: str,
) -> dict[str, Any]:
    queues = unique(job_queues)
    environments = unique(compute_environments)
    stopped_jobs: dict[str, int] = {
        "cancelled": 0,
        "terminated": 0,
        "already_terminal": 0,
    }

    for queue in queues:
        batch.update_job_queue(jobQueue=queue, state="DISABLED")

    for environment in environments:
        batch.update_compute_environment(
            computeEnvironment=environment,
            state="DISABLED",
        )

    for queue in queues:
        for status in CANCELABLE_JOB_STATUSES + TERMINABLE_JOB_STATUSES:
            for job in list_jobs(batch, queue, status):
                result = cancel_or_terminate(
                    batch,
                    queue=queue,
                    status=status,
                    job=job,
                    reason=reason,
                )
                stopped_jobs[result] += 1

    return {
        "status": "stopped",
        "job_queues_disabled": len(queues),
        "compute_environments_disabled": len(environments),
        "jobs": stopped_jobs,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    job_queues = env_string_list("BATCH_JOB_QUEUES")
    compute_environments = env_string_list("BATCH_COMPUTE_ENVIRONMENTS")

    import boto3

    if is_budget_sns_event(event):
        reason = os.environ.get(
            "BATCH_BUDGET_STOP_REASON",
            "Diana daily AWS Budget cost guard tripped",
        )
        result = stop_batch(
            boto3.client("batch"),
            job_queues=job_queues,
            compute_environments=compute_environments,
            reason=reason,
        )
        LOGGER.warning(
            "Diana daily cost guard stopped Batch after budget event: %s",
            json.dumps(result, sort_keys=True),
        )
        return result

    reason = os.environ.get(
        "BATCH_ESTIMATED_STOP_REASON",
        "Diana estimated daily Batch EC2 spend guard tripped",
    )
    result = monitor_estimated_ec2_spend(
        boto3.client("batch"),
        {
            region: boto3.client("ec2", region_name=region)
            for region in env_string_list("BATCH_COST_GUARD_REGIONS")
        },
        boto3.resource("dynamodb").Table(os.environ["BATCH_COST_LEDGER_TABLE"]),
        job_queues=job_queues,
        compute_environments=compute_environments,
        reason=reason,
        tag_key=os.environ["BATCH_COST_GUARD_TAG_KEY"],
        tag_value=os.environ["BATCH_COST_GUARD_TAG_VALUE"],
        daily_limit_usd=env_decimal("BATCH_DAILY_EC2_LIMIT_USD"),
        hourly_rates=env_decimal_map("BATCH_INSTANCE_HOURLY_RATES_USD"),
        unknown_hourly_rate=env_decimal("BATCH_UNKNOWN_INSTANCE_HOURLY_RATE_USD"),
    )
    LOGGER.warning(
        "Diana daily cost guard checked estimated Batch EC2 spend: %s",
        json.dumps(result, sort_keys=True),
    )
    return result
