#!/usr/bin/env python3
"""Canonical Diana WGS HRD report inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

INVENTORY_SCHEMA_VERSION = 1
INVENTORY_ID = "diana_wgs_hrd_report_set_v1"
REQUIRED_METHOD_IDS = (
    "deterministic_full_wgs",
    "rosalind_diana_wgs",
    "sequenza_scarhrd",
    "sigprofiler_sbs3",
    "facets_scarhrd_blocked",
    "oncoanalyser_chord_blocked",
    "hrdetect_blocked",
)
HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID = "hcc1395_wgs_known_answer_v1"
HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS = (
    "deterministic_full_wgs",
    "rosalind_hcc1395_wgs",
    *REQUIRED_METHOD_IDS[2:],
)
INVENTORY_METHODS = {
    INVENTORY_ID: REQUIRED_METHOD_IDS,
    HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID: HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS,
}
EXECUTABLE_CROSSCHECK_METHOD_IDS = REQUIRED_METHOD_IDS[2:4]
BLOCKED_CROSSCHECK_METHOD_IDS = REQUIRED_METHOD_IDS[4:]
BLOCKED_CROSSCHECK_REPORT_DIRS = {method_id: method_id for method_id in BLOCKED_CROSSCHECK_METHOD_IDS}
AI_REVIEW_METHOD_IDS = (
    "ai_review_reviewer_a",
    "ai_review_reviewer_b",
)
COMPARATIVE_METHOD_IDS = ("comparative_hrd_synthesis",)
REPORT_METHOD_IDS = REQUIRED_METHOD_IDS + AI_REVIEW_METHOD_IDS + COMPARATIVE_METHOD_IDS


def required_method_ids(inventory_id: str = INVENTORY_ID) -> tuple[str, ...]:
    try:
        return INVENTORY_METHODS[inventory_id]
    except KeyError as error:
        raise ValueError(f"unknown HRD report inventory: {inventory_id}") from error


def inventory_payload(inventory_id: str = INVENTORY_ID) -> dict[str, Any]:
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "inventory_id": inventory_id,
        "ordered_method_ids": list(required_method_ids(inventory_id)),
    }


def inventory_sha256(inventory_id: str = INVENTORY_ID) -> str:
    encoded = json.dumps(
        inventory_payload(inventory_id),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_pinned_methods(
    values: Sequence[str],
    label: str,
    inventory_id: str = INVENTORY_ID,
) -> list[str]:
    observed = [str(value) for value in values]
    expected = list(required_method_ids(inventory_id))
    if observed != expected:
        raise ValueError(
            f"{label} must equal the pinned seven-method inventory {inventory_id} "
            f"in exact order; expected={expected!r} observed={observed!r}"
        )
    return observed


def require_report_methods(values: Sequence[str], label: str) -> list[str]:
    observed = [str(value) for value in values]
    expected = list(REPORT_METHOD_IDS)
    if observed != expected:
        raise ValueError(f"{label} must equal the pinned report inventory in exact order; expected={expected!r} observed={observed!r}")
    return observed


def require_inventory_binding(
    payload: Any,
    digest: Any,
    label: str,
    inventory_id: str | None = INVENTORY_ID,
) -> str:
    if inventory_id is None:
        if not isinstance(payload, dict):
            raise ValueError(f"{label} is not a report inventory object")
        inventory_id = str(payload.get("inventory_id", ""))
        required_method_ids(inventory_id)
    if (
        payload != inventory_payload(inventory_id)
        or str(digest).lower() != inventory_sha256(inventory_id)
    ):
        raise ValueError(
            f"{label} differs from the pinned seven-method inventory {inventory_id}"
        )
    return inventory_id


def source_report_packet_dirs(
    root: Path,
    run_id: str,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    *,
    deterministic_report_dir: Path | None = None,
    rosalind_report_dir: Path | None = None,
    blocked_crosscheck_root: Path | None = None,
) -> dict[str, Path]:
    """Return the canonical source report packet directories in method order."""

    reports = root / ".codex-tmp/hrd-reports"
    crosschecks = reports / "crosschecks"
    blocked = blocked_crosscheck_root or reports / "blocked-crosschecks"
    paths = {
        "deterministic_full_wgs": deterministic_report_dir or reports / "deterministic-full/report",
        "rosalind_diana_wgs": rosalind_report_dir or root / "results/rosalind_hrd/diana_wgs" / run_id,
        "sequenza_scarhrd": (sequenza_report_dir or crosschecks / "sequenza_scarhrd"),
        "sigprofiler_sbs3": (sigprofiler_report_dir or crosschecks / "sigprofiler_sbs3"),
    }
    for method_id, directory in BLOCKED_CROSSCHECK_REPORT_DIRS.items():
        paths[method_id] = blocked / directory
    require_pinned_methods(tuple(paths), "source report packet directories")
    return paths


def source_report_manifest_paths(
    root: Path,
    run_id: str,
    sigprofiler_report_dir: Path | None = None,
    sequenza_report_dir: Path | None = None,
    *,
    deterministic_report_dir: Path | None = None,
    rosalind_report_dir: Path | None = None,
    blocked_crosscheck_root: Path | None = None,
) -> dict[str, Path]:
    """Return each canonical source report packet's manifest path."""

    return {
        method_id: path / "report_manifest.json"
        for method_id, path in source_report_packet_dirs(
            root,
            run_id,
            sigprofiler_report_dir,
            sequenza_report_dir,
            deterministic_report_dir=deterministic_report_dir,
            rosalind_report_dir=rosalind_report_dir,
            blocked_crosscheck_root=blocked_crosscheck_root,
        ).items()
    }
