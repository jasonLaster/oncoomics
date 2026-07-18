"""Shared helpers for generated HRD handoff runbooks."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Iterable


def timestamped_runbook_assignment(variable: str, directory: Path, stem: str) -> str:
    prefix = shlex.quote(str(directory / f"{stem}."))
    return f"{variable}={prefix}$(date -u +%Y%m%dT%H%M%SZ).md"


def unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return paths in first-seen order without duplicate preflight noise."""

    return tuple(dict.fromkeys(paths))


def source_private_receipt_path(
    root: Path, receipt_stem: str, method_id: str
) -> Path:
    """Return a source HRD packet's private-freeze receipt path."""

    return (
        root
        / ".codex-tmp/hrd-reports/deterministic-full"
        / f"{receipt_stem}.{method_id}.private.json"
    )


def source_private_receipt_paths(
    root: Path, receipt_stem: str, method_ids: Iterable[str]
) -> tuple[Path, ...]:
    """Return source HRD private-freeze receipt paths in method order."""

    return tuple(
        source_private_receipt_path(root, receipt_stem, method_id)
        for method_id in method_ids
    )


def write_once(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
