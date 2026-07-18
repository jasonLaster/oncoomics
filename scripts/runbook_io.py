"""Shared helpers for generated HRD handoff runbooks."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any, Iterable


class Raw(str):
    """Shell token that should be emitted without shell quoting."""


def shell_join(values: Iterable[str | os.PathLike[str]]) -> str:
    return " ".join(
        str(value) if isinstance(value, Raw) else shlex.quote(os.fspath(value))
        for value in values
    )


def block(command: Iterable[str | os.PathLike[str]]) -> str:
    return "```bash\n" + shell_join(command) + "\n```\n"


def bash_block(lines: Iterable[str]) -> str:
    return "```bash\n" + "\n".join(lines) + "\n```\n"


def timestamped_runbook_assignment(variable: str, directory: Path, stem: str) -> str:
    prefix = shlex.quote(str(directory / f"{stem}."))
    return f"{variable}={prefix}$(date -u +%Y%m%dT%H%M%SZ).md"


def unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return paths in first-seen order without duplicate preflight noise."""

    return tuple(dict.fromkeys(paths))


def missing_required_files(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return prerequisite paths that are absent, symlinked, or not regular files."""

    return tuple(path for path in paths if path.is_symlink() or not path.is_file())


def preexisting_create_only_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return create-only outputs that already exist or would be redirected."""

    return tuple(
        path
        for path in paths
        if path.exists()
        or path.is_symlink()
        or any(
            parent.is_symlink() and not is_platform_root_alias(parent)
            for parent in path.parents
        )
    )


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load a required JSON object while rejecting symlinked receipts."""

    require_real_input_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object: {path}")
    return value


def require_real_input_file(path: Path, label: str) -> None:
    """Reject input files with redirected leaf or parent path components."""

    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink: {path}")


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


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_once(path: Path, text: str) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"output parent is a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
