#!/usr/bin/env python3
"""Stage exact two-file model input directories from an AI review bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROLES = ("A", "B")
ROLE_DIRS = {"A": "reviewer-a-input", "B": "reviewer-b-input"}
ROLE_PROMPTS = {"A": "reviewer-a.prompt.md", "B": "reviewer-b.prompt.md"}
HEX64 = set("0123456789abcdef")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def write_once(path: Path, data: bytes) -> None:
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
            require_installed_file(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_installed_file(path: Path, expected_sha256: str) -> None:
    require_no_symlink_ancestors(path, "staged AI review input")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"staged AI review input changed during write: {path}")
    require_mode(path, 0o600, "staged AI review input")
    if sha256(path) != expected_sha256:
        raise ValueError(f"staged AI review input changed during write: {path}")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def remove_destination_tree(path: Path) -> None:
    if path.exists() and path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlink_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_or_new_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    require_no_symlink_ancestors(path, label)
    if path.exists() and not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return path.resolve()


def require_new_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"{label} already exists: {path}")
    require_no_symlink_ancestors(path, label)
    return path.resolve()


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    path = require_new_file(path, "receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_once(
        path,
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def require_file(path: Path, expected_sha256: str, label: str) -> None:
    require_no_symlink_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} is not a non-empty real file")
    observed = sha256(path)
    if observed != expected_sha256:
        raise ValueError(f"{label} SHA-256 mismatch")


def require_real_file(path: Path, label: str) -> None:
    require_no_symlink_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} is not a non-empty real file")


def resolve_real_bundle_dir(path: Path) -> Path:
    require_no_symlink_ancestors(path, "bundle directory")
    if path.is_symlink() or not path.is_dir():
        raise ValueError("bundle directory is missing or a symlink")
    return path.resolve()


def require_sha(value: Any, label: str) -> str:
    digest = str(value).lower()
    if len(digest) != 64 or set(digest) - HEX64:
        raise ValueError(f"{label} is malformed")
    return digest


def require_mode(path: Path, expected: int, label: str) -> None:
    observed = path.stat().st_mode & 0o777
    if observed != expected:
        raise ValueError(f"{label} mode is not {expected:04o}: {path}")


def validate_bundle(bundle_dir: Path) -> dict[str, str]:
    require_real_file(
        bundle_dir / "bundle_manifest.json",
        "bundle_manifest.json",
    )
    bundle_manifest = load_object(
        bundle_dir / "bundle_manifest.json",
        "bundle_manifest.json",
    )
    if bundle_manifest.get("schema_version") != 2:
        raise ValueError("unsupported bundle_manifest.json schema")

    prompt_hashes = bundle_manifest.get("prompt_sha256")
    if not isinstance(prompt_hashes, dict) or set(prompt_hashes) != set(ROLES):
        raise ValueError("bundle manifest lacks exact prompt hashes")

    bundle_hash = require_sha(
        bundle_manifest.get("review_bundle_sha256", ""),
        "review_bundle.json SHA-256",
    )
    require_file(bundle_dir / "review_bundle.json", bundle_hash, "review_bundle.json")

    output = {"review_bundle.json": bundle_hash}
    for role in ROLES:
        prompt = ROLE_PROMPTS[role]
        prompt_hash = require_sha(
            prompt_hashes[role],
            f"{prompt} SHA-256",
        )
        require_file(bundle_dir / prompt, prompt_hash, prompt)
        output[prompt] = prompt_hash

    return output


def reviewer_inventory(
    directory: Path,
    role: str,
    hashes: dict[str, str],
) -> dict[str, Any]:
    label = f"reviewer {role} input directory"
    require_no_symlink_ancestors(directory, label)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"{label} is not a real directory")
    require_mode(directory, 0o700, label)

    prompt = ROLE_PROMPTS[role]
    bundle_path = directory / "review_bundle.json"
    prompt_path = directory / prompt
    require_file(
        bundle_path,
        hashes["review_bundle.json"],
        f"reviewer {role} review_bundle.json",
    )
    require_file(
        prompt_path,
        hashes[prompt],
        f"reviewer {role} {prompt}",
    )
    require_mode(bundle_path, 0o600, f"reviewer {role} review_bundle.json")
    require_mode(prompt_path, 0o600, f"reviewer {role} {prompt}")
    observed = sorted(path.name for path in directory.iterdir())
    expected = sorted(("review_bundle.json", prompt))
    if observed != expected:
        raise ValueError(f"reviewer {role} staged inventory is not exact")

    return {
        "directory": str(directory),
        "files": {
            "review_bundle.json": {
                "sha256": hashes["review_bundle.json"],
                "mode_0600": True,
            },
            prompt: {
                "sha256": hashes[prompt],
                "mode_0600": True,
            },
        },
        "exact_two_file_inventory": observed,
        "mode_0700": True,
    }


def stage(bundle_dir: Path, output_root: Path, receipt_output: Path) -> dict[str, Any]:
    bundle_dir = resolve_real_bundle_dir(bundle_dir)
    output_root = require_real_or_new_directory(output_root, "output root")
    receipt_output = require_new_file(receipt_output, "receipt output")
    if (
        bundle_dir == output_root
        or bundle_dir.is_relative_to(output_root)
        or output_root.is_relative_to(bundle_dir)
    ):
        raise ValueError("output root must be separate from the review bundle")
    if receipt_output in (bundle_dir, output_root) or (
        receipt_output.is_relative_to(bundle_dir)
        or receipt_output.is_relative_to(output_root)
    ):
        raise ValueError(
            "receipt output must be separate from the review bundle and output root"
        )

    hashes = validate_bundle(bundle_dir)

    destinations = {role: output_root / ROLE_DIRS[role] for role in ROLES}
    for destination in destinations.values():
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"reviewer input directory exists: {destination}")

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".ai-review-inputs.",
        dir=output_root,
    ) as temporary:
        temporary_root = Path(temporary)
        for role in ROLES:
            role_dir = temporary_root / ROLE_DIRS[role]
            role_dir.mkdir(mode=0o700)
            write_once(
                role_dir / "review_bundle.json",
                (bundle_dir / "review_bundle.json").read_bytes(),
            )
            write_once(
                role_dir / ROLE_PROMPTS[role],
                (bundle_dir / ROLE_PROMPTS[role]).read_bytes(),
            )
            reviewer_inventory(role_dir, role, hashes)

        try:
            for role in ROLES:
                os.rename(temporary_root / ROLE_DIRS[role], destinations[role])
            fsync_directory(output_root)
            published = {
                role: reviewer_inventory(destinations[role], role, hashes)
                for role in ROLES
            }
        except Exception:
            for destination in destinations.values():
                remove_destination_tree(destination)
            raise

    receipt = {
        "schema_version": 1,
        "status": "passed",
        "generated_at": now(),
        "bundle_dir": str(bundle_dir),
        "output_root": str(output_root),
        "reviewers": published,
        "checks": {
            "bundle_manifest_bound": True,
            "reviewer_a_two_file_inventory": True,
            "reviewer_b_two_file_inventory": True,
            "no_cross_prompt": True,
        },
    }
    write_json_once(receipt_output, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        receipt = stage(args.bundle_dir, args.output_root, args.receipt_output)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "reviewer_a_input": receipt["reviewers"]["A"]["directory"],
                "reviewer_b_input": receipt["reviewers"]["B"]["directory"],
                "receipt_output": str(args.receipt_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
