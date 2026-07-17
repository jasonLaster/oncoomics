#!/usr/bin/env python3
"""Materialize the pinned AI-review model catalog receipt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ai_model_catalog import MODEL_CATALOG_VERIFIED_AT, model_catalog_receipt


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
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit(f"Fail-closed: output already exists: {args.output}")

    payload = json.dumps(model_catalog_receipt(), indent=2, sort_keys=True) + "\n"
    write_once(args.output, payload)
    print(json.dumps({"status": "written", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
