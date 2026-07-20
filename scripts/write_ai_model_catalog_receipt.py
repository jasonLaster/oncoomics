#!/usr/bin/env python3
"""Materialize the pinned AI-review model catalog receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

from ai_model_catalog import MODEL_CATALOG_VERIFIED_AT, model_catalog_receipt


def prepare_create_only_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {path}")
    for parent in path.parents:
        if parent.is_symlink():
            raise SystemExit(f"Fail-closed: output parent is a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise SystemExit(f"Fail-closed: output parent is not a directory: {parent}")
    path.parent.mkdir(parents=True, exist_ok=True)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_once(path: Path, text: str) -> None:
    prepare_create_only_output(path)
    data = text.encode("utf-8")
    expected_sha256 = hashlib.sha256(data).hexdigest()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
            require_installed_output(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_installed_output(path: Path, expected_sha256: str) -> None:
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError(f"output parent became a symlink: {parent}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"output changed during write: {path}")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"output mode changed during write: {path}")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"output changed during write: {path}")


def sha256_file(path: Path) -> str:
    require_real_file(path, f"{path.name} SHA-256 input")
    digest, identity = sha256_file_once(path)
    stable_digest, stable_identity = sha256_file_once(path)
    if stable_identity != identity or stable_digest != digest:
        raise ValueError(f"{path.name} SHA-256 input changed during read")
    return digest


def sha256_file_once(path: Path) -> tuple[str, tuple[int, int, int, int, int, int]]:
    require_real_file(path, f"{path.name} SHA-256 input")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{path.name} SHA-256 input is missing or a symlink")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read()
            after_read = os.fstat(handle.fileno())
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ValueError(f"{path.name} SHA-256 input changed during read") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if (
        stat_identity(opened) != stat_identity(after_read)
        or stat_identity(after_read) != stat_identity(current)
    ):
        raise ValueError(f"{path.name} SHA-256 input changed during read")
    return hashlib.sha256(data).hexdigest(), stat_identity(opened)


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def require_real_file(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--attest-models-latest",
        action="store_true",
        help=(
            "Assert both pinned reviewer models were available and latest in "
            "the active Codex model catalog at the pinned verification time."
        ),
    )
    args = parser.parse_args()

    if not args.attest_models_latest:
        raise SystemExit(
            "Fail-closed: --attest-models-latest is required for "
            f"{MODEL_CATALOG_VERIFIED_AT}"
        )
    prepare_create_only_output(args.output)

    payload = json.dumps(model_catalog_receipt(), indent=2, sort_keys=True) + "\n"
    write_once(args.output, payload)
    print(json.dumps({"status": "written", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
