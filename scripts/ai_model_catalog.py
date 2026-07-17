#!/usr/bin/env python3
"""Pinned AI-review model catalog constants."""

from __future__ import annotations

from typing import Any

MODEL_CATALOG_RECEIPT = "model-catalog-receipt.20260717T115311Z.json"
MODEL_CATALOG_VERIFIED_AT = "2026-07-17T11:53:11+00:00"
MODEL_CATALOG_SOURCE = "Active Codex collaboration model override catalog exposed to this task on 2026-07-17"
PROVIDER_CATALOG = "Codex collaboration available model overrides"
REVIEWER_A = ("openai-codex", "gpt-5.6-sol")
REVIEWER_B = ("openai-codex", "gpt-5.6-terra")


def model_catalog_receipt() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider_catalog": PROVIDER_CATALOG,
        "catalog_source": MODEL_CATALOG_SOURCE,
        "catalog_verified_at": MODEL_CATALOG_VERIFIED_AT,
        "models": [
            {
                "provider": provider,
                "model_id": model_id,
                "available": True,
                "latest_available": True,
            }
            for provider, model_id in (REVIEWER_A, REVIEWER_B)
        ],
    }
