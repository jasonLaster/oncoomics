#!/usr/bin/env python3
"""Materialize the pinned AI-review model catalog receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"output changed during write: {path}")


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
