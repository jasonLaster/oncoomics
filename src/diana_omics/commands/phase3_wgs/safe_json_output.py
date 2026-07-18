from __future__ import annotations

from pathlib import Path


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


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
