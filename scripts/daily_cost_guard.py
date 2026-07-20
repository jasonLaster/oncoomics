#!/usr/bin/env python3
"""Fail closed when today's Diana Batch EC2 estimate is at the live stop."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


class DailyCostGuardError(ValueError):
    """Raised when an expensive Batch submission is not cost-safe."""


def today_utc(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()


def parse_dynamodb_number(value: Any, label: str) -> Decimal:
    if not isinstance(value, dict) or set(value) != {"N"}:
        raise DailyCostGuardError(f"DynamoDB {label} must be a number attribute")
    raw = value.get("N")
    if not isinstance(raw, str) or not raw:
        raise DailyCostGuardError(f"DynamoDB {label} must be a number string")
    try:
        parsed = Decimal(raw)
    except InvalidOperation as error:
        raise DailyCostGuardError(f"DynamoDB {label} must be a decimal number") from error
    if parsed < 0:
        raise DailyCostGuardError(f"DynamoDB {label} must be non-negative")
    return parsed


def parse_daily_cost_guard_ledger_item(payload: Mapping[str, Any]) -> Decimal:
    item = payload.get("Item")
    if item is None:
        return Decimal(0)
    if not isinstance(item, dict):
        raise DailyCostGuardError("DynamoDB daily cost guard Item must be a JSON object")
    return parse_dynamodb_number(item.get("estimated_daily_ec2_usd"), "estimated_daily_ec2_usd")


def load_daily_cost_guard_estimated_spend(
    *,
    ledger: str,
    region: str,
    guard_day: str | None = None,
    aws_cli: str = "aws",
) -> Decimal:
    day = guard_day or today_utc()
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
        raise DailyCostGuardError(f"{aws_cli} is required to verify today's Diana Batch EC2 spend") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise DailyCostGuardError(f"Unable to read the {region} daily cost guard ledger {ledger}{detail}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DailyCostGuardError("DynamoDB daily cost guard ledger did not return JSON") from error

    if not isinstance(payload, dict):
        raise DailyCostGuardError("DynamoDB daily cost guard response must be a JSON object")
    return parse_daily_cost_guard_ledger_item(payload)


def parse_guard_usd(value: str, label: str, *, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise DailyCostGuardError(f"{label} must be a decimal") from error
    if parsed < 0 or (parsed == 0 and not allow_zero):
        raise DailyCostGuardError(f"{label} must be {'non-negative' if allow_zero else 'positive'}")
    return parsed


def validate_daily_cost_guard_estimated_spend(
    estimated_daily_ec2_usd: Decimal,
    *,
    live_stop_usd: str,
    daily_limit_usd: str | None = None,
    reservation_usd: str = "0",
) -> dict[str, str]:
    stop = parse_guard_usd(live_stop_usd, "daily_cost_guard_live_stop_usd")
    limit = parse_guard_usd(
        daily_limit_usd or live_stop_usd,
        "daily_cost_guard_limit_usd",
    )
    reservation = parse_guard_usd(
        reservation_usd,
        "daily_cost_guard_reservation_usd",
        allow_zero=True,
    )
    if estimated_daily_ec2_usd >= stop:
        raise DailyCostGuardError(
            f"Daily Batch EC2 cost guard is already at ${estimated_daily_ec2_usd:.6f}; "
            f"refusing AWS Batch submission at the ${stop:.6f} live stop"
        )
    reserved_daily_ec2_usd = estimated_daily_ec2_usd + reservation
    if reserved_daily_ec2_usd > limit:
        raise DailyCostGuardError(
            f"Daily Batch EC2 cost guard is already at ${estimated_daily_ec2_usd:.6f}; "
            f"refusing AWS Batch submission because its ${reservation:.6f} reservation "
            f"would exceed the ${limit:.6f} daily limit"
        )
    return {
        "daily_limit_usd": str(limit),
        "reservation_usd": str(reservation),
        "reserved_daily_ec2_usd": str(reserved_daily_ec2_usd),
    }


def check_daily_cost_guard(
    *,
    ledger: str,
    region: str,
    live_stop_usd: str,
    daily_limit_usd: str | None = None,
    reservation_usd: str = "0",
    aws_cli: str = "aws",
    guard_day: str | None = None,
) -> dict[str, str]:
    day = guard_day or today_utc()
    spend = load_daily_cost_guard_estimated_spend(
        ledger=ledger,
        region=region,
        guard_day=day,
        aws_cli=aws_cli,
    )
    reservation = validate_daily_cost_guard_estimated_spend(
        spend,
        live_stop_usd=live_stop_usd,
        daily_limit_usd=daily_limit_usd,
        reservation_usd=reservation_usd,
    )
    return {
        **reservation,
        "estimated_daily_ec2_usd": str(spend),
        "guard_day": day,
        "ledger": ledger,
        "live_stop_usd": live_stop_usd,
        "region": region,
        "status": "passed",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, help="DynamoDB daily cost guard ledger table name")
    parser.add_argument("--region", required=True, help="AWS region that owns the ledger")
    parser.add_argument("--live-stop-usd", required=True, help="USD threshold that must not be reached")
    parser.add_argument("--limit-usd", help="Harder daily USD ceiling checked after any reservation")
    parser.add_argument("--reservation-usd", default="0", help="Conservative USD reserved for the submission about to start")
    parser.add_argument("--guard-day", help="UTC guard day; defaults to today")
    args = parser.parse_args(argv)

    try:
        result = check_daily_cost_guard(
            ledger=args.ledger,
            region=args.region,
            live_stop_usd=args.live_stop_usd,
            daily_limit_usd=args.limit_usd,
            reservation_usd=args.reservation_usd,
            guard_day=args.guard_day,
        )
    except DailyCostGuardError as error:
        print(f"Fail-closed: {error}", file=sys.stderr)
        return 64

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
