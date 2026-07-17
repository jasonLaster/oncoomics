"""Shared helpers for generated HRD handoff runbooks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return paths in first-seen order without duplicate preflight noise."""

    return tuple(dict.fromkeys(paths))


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
