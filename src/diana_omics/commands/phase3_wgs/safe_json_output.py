from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


class DuplicateJsonObjectName(ValueError):
    """Raised when a JSON object repeats a name."""


def reject_duplicate_json_object_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonObjectName(key)
        result[key] = value
    return result


def require_no_symlinked_ancestors(
    path: Path,
    label: str,
    error_type: type[Exception],
) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise error_type(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise error_type(f"{label} parent is not a directory: {parent}")


def require_safe_output_path(path: Path, label: str, error_type: type[Exception]) -> None:
    if path.is_symlink():
        raise error_type(f"{label} may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, label, error_type)
    if path.exists() and not path.is_file():
        raise error_type(f"{label} already exists and is not a file: {path}")


def require_real_input_file(
    path: Path,
    label: str,
    error_type: type[Exception],
) -> Path:
    require_no_symlinked_ancestors(path, label, error_type)
    if path.is_symlink() or not path.is_file():
        raise error_type(f"{label} is missing or a symlink: {path}")
    return path


def require_real_hash_input(path: Path, error_type: type[Exception]) -> Path:
    return require_real_input_file(path, f"{path.name} SHA-256 input", error_type)


def sha256_real_file(path: Path, error_type: type[Exception]) -> str:
    path = require_real_hash_input(path, error_type)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_real_json(path: Path, label: str, error_type: type[Exception]) -> Any:
    if path.is_symlink() or not path.is_file():
        raise error_type(f"{label} must be a real JSON file: {path}")
    require_no_symlinked_ancestors(path, label, error_type)
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonObjectName as error:
        raise error_type(f"duplicate JSON object name in {label}: {error}") from error
