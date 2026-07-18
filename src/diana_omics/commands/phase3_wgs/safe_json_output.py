from __future__ import annotations

from pathlib import Path


def require_safe_output_path(path: Path, label: str, error_type: type[Exception]) -> None:
    if path.is_symlink():
        raise error_type(f"{label} may not be a symlink: {path}")

    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        next_parent = parent.parent
        if next_parent == parent:
            raise error_type(f"{label} parent does not exist: {path.parent}")
        parent = next_parent

    if parent.is_symlink():
        raise error_type(f"{label} parent may not be a symlink: {parent}")
    if not parent.is_dir():
        raise error_type(f"{label} parent is not a directory: {parent}")
    if path.exists() and not path.is_file():
        raise error_type(f"{label} already exists and is not a file: {path}")
