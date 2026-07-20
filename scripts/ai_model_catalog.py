#!/usr/bin/env python3
"""Pinned AI-review model catalog constants."""

from __future__ import annotations

from datetime import datetime
from typing import Any

MODEL_CATALOG_RECEIPT = "model-catalog-receipt.20260717T115311Z.json"
MODEL_CATALOG_VERIFIED_AT = "2026-07-17T11:53:11+00:00"
MODEL_CATALOG_SOURCE = "Active Codex collaboration model override catalog exposed to this task on 2026-07-17"
PROVIDER_CATALOG = "Codex collaboration available model overrides"
REVIEWER_A = ("openai-codex", "gpt-5.6-sol")
REVIEWER_B = ("openai-codex", "gpt-5.6-terra")
MODEL_CATALOG_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "provider_catalog",
        "catalog_source",
        "catalog_verified_at",
        "models",
    }
)
MODEL_CATALOG_MODEL_KEYS = frozenset(
    {
        "provider",
        "model_id",
        "available",
        "latest_available",
    }
)


def has_ascii_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def require_exact_catalog_string(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or has_ascii_control(value)
    ):
        raise ValueError(f"model catalog {label} is not exact")
    return value


def require_catalog_timestamp(value: Any) -> str:
    timestamp = require_exact_catalog_string(value, "verification timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("model catalog verification timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("model catalog verification timestamp must include timezone")
    return timestamp


def require_reviewer_model(value: Any, reviewer: str) -> tuple[str, str]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(
            f"model catalog reviewer {reviewer} must be an exact provider/model tuple"
        )
    return (
        require_exact_catalog_string(value[0], f"reviewer {reviewer} provider"),
        require_exact_catalog_string(value[1], f"reviewer {reviewer} model ID"),
    )


def reviewer_models() -> tuple[tuple[str, str], tuple[str, str]]:
    models = (
        require_reviewer_model(REVIEWER_A, "A"),
        require_reviewer_model(REVIEWER_B, "B"),
    )
    if len(set(models)) != len(models):
        raise ValueError(
            "model catalog receipt requires distinct reviewer model identities"
        )
    return models


def model_catalog_receipt() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider_catalog": require_exact_catalog_string(
            PROVIDER_CATALOG,
            "provider catalog",
        ),
        "catalog_source": require_exact_catalog_string(
            MODEL_CATALOG_SOURCE,
            "source",
        ),
        "catalog_verified_at": require_catalog_timestamp(MODEL_CATALOG_VERIFIED_AT),
        "models": [
            {
                "provider": provider,
                "model_id": model_id,
                "available": True,
                "latest_available": True,
            }
            for provider, model_id in reviewer_models()
        ],
    }
