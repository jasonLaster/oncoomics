#!/usr/bin/env python3
"""Disable Diana Batch queues when the daily AWS Budget guard trips."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterable

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

CANCELABLE_JOB_STATUSES = ("SUBMITTED", "PENDING", "RUNNABLE")
TERMINABLE_JOB_STATUSES = ("STARTING", "RUNNING")
TERMINAL_RACE_ERROR_CODES = {"ClientException"}


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
    reason = os.environ.get(
        "BATCH_STOP_REASON",
        "Diana daily AWS Budget cost guard tripped",
    )
    job_queues = env_string_list("BATCH_JOB_QUEUES")
    compute_environments = env_string_list("BATCH_COMPUTE_ENVIRONMENTS")

    import boto3

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
