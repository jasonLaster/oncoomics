#!/usr/bin/env python3
"""Stage a compact HRD cross-check packet from an exact route replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Sequence

from hrd_report_inventory import EXECUTABLE_CROSSCHECK_METHOD_IDS

SUPPORTED_ROUTES = set(EXECUTABLE_CROSSCHECK_METHOD_IDS)
SHA256_HEX = set("0123456789abcdef")
CORE_REPORT_FILES = {"report.md", "report_manifest.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def require_sha(value: Any, label: str) -> str:
    digest = str(value)
    if len(digest) != 64 or set(digest) - SHA256_HEX:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return digest


def require_safe_relative_path(relative: str, label: str) -> Path:
    path = Path(relative)
    if not path.parts or path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(f"{label} must be a safe relative file path")
    return path


def require_source_file(root: Path, relative: str) -> Path:
    relative_path = require_safe_relative_path(relative, "route support path")
    root = root.resolve(strict=True)
    parent = root
    for part in relative_path.parts[:-1]:
        parent = parent / part
        try:
            value = os.lstat(parent)
        except FileNotFoundError as error:
            raise ValueError(
                f"exact route replay lacks a real non-empty {relative}"
            ) from error
        if stat.S_ISLNK(value.st_mode):
            raise ValueError(f"exact route replay contains a symlink in {relative}")
        if not stat.S_ISDIR(value.st_mode):
            raise ValueError(f"exact route replay lacks a real non-empty {relative}")

    path = parent / relative_path.name
    try:
        value = os.lstat(path)
    except FileNotFoundError as error:
        raise ValueError(f"exact route replay lacks a real non-empty {relative}") from error
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISREG(value.st_mode)
        or path.stat().st_size <= 0
        or not path.resolve(strict=True).is_relative_to(root)
    ):
        raise ValueError(f"exact route replay lacks a real non-empty {relative}")
    return path


def require_download_verification(
    verification_path: Path, source_dir: Path, route: str
) -> dict[str, str | int]:
    verification = load_json(verification_path, "download verification")
    rows = verification.get("objects")
    if (
        verification.get("schema_version") != 1
        or verification.get("status") != "passed"
        or not isinstance(rows, list)
        or not rows
        or int(verification.get("object_count", -1)) != len(rows)
    ):
        raise ValueError("download verification is not passed and exact")

    expected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("download verification contains a malformed row")
        relative = str(row.get("relative_path", ""))
        if relative in expected:
            raise ValueError(f"download verification repeats {relative}")
        expected[relative] = row

    for relative in ("report.md", "report_manifest.json"):
        row = expected.get(relative)
        local = require_source_file(source_dir, relative)
        if (
            row is None
            or int(row.get("bytes", -1)) != local.stat().st_size
            or str(row.get("sha256", "")) != sha256(local)
        ):
            raise ValueError(f"download verification is stale for {relative}")

    manifest = load_json(source_dir / "report_manifest.json", "route report manifest")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("method_id") != route
        or manifest.get("route") != route
        or manifest.get("authorized_hrd_state") != "no_call"
        or manifest.get("classification_authorized") is not False
        or manifest.get("classification_qc_status") != "not_applicable"
        or not isinstance(manifest.get("review_summary"), dict)
        or not manifest["review_summary"]
    ):
        raise ValueError("route report manifest is not an approved no-call cross-check")

    evidence_status = str(manifest.get("evidence_status", ""))
    if evidence_status not in {"partial_evidence", "no_call", "blocked"}:
        raise ValueError("route report evidence_status is unsupported")

    source_report_sha256 = sha256(source_dir / "report.md")
    if (
        require_sha(manifest.get("report_sha256"), "route report_sha256")
        != source_report_sha256
    ):
        raise ValueError("route report manifest hash differs from report.md")

    support = manifest.get("support_sha256")
    source = manifest.get("source_sha256")
    if not isinstance(support, dict) or not support:
        raise ValueError("route report manifest lacks support SHA-256 evidence")
    if not isinstance(source, dict) or not source:
        raise ValueError("route report manifest lacks source SHA-256 evidence")
    for field, values in {"support_sha256": support, "source_sha256": source}.items():
        for key, digest in values.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"route report manifest has a malformed {field} key")
            require_sha(digest, f"{field}.{key}")
    for relative, expected_sha256 in support.items():
        local = require_source_file(source_dir, relative)
        row = expected.get(relative)
        observed_sha256 = sha256(local)
        if (
            row is None
            or int(row.get("bytes", -1)) != local.stat().st_size
            or str(row.get("sha256", "")) != observed_sha256
        ):
            raise ValueError(f"download verification is stale for support {relative}")
        if expected_sha256 != observed_sha256:
            raise ValueError(
                f"route report manifest support hash differs for {relative}"
            )

    return {
        "route": route,
        "evidence_status": evidence_status,
        "source_object_count": len(rows),
        "download_verification_sha256": sha256(verification_path),
        "source_report_manifest_sha256": sha256(source_dir / "report_manifest.json"),
        "source_report_sha256": source_report_sha256,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_create_only(source: Path, destination: Path) -> None:
    try:
        file_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
    except FileExistsError as error:
        raise ValueError(
            "staged cross-check packet already exists: " + destination.name
        ) from error

    try:
        with source.open("rb") as source_handle, os.fdopen(
            file_descriptor, "wb"
        ) as destination_handle:
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                destination_handle.write(chunk)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def copy_route_support_files(source_dir: Path, staging: Path) -> None:
    manifest = load_json(staging / "report_manifest.json", "route report manifest")
    support = manifest.get("support_sha256")
    if not isinstance(support, dict):
        return

    for relative in sorted(support):
        if not isinstance(relative, str) or not relative:
            continue
        if relative in CORE_REPORT_FILES:
            raise ValueError(f"route support overlaps a core report file: {relative}")
        source = require_source_file(source_dir, relative)
        destination = staging / require_safe_relative_path(
            relative,
            "route support path",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def install_staged_packet(staging: Path, output_dir: Path) -> None:
    try:
        output_dir.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ValueError(f"output already exists: {output_dir}") from error

    installed: list[Path] = []
    try:
        for name in ("method_spec.json", "report.md", "report_manifest.json"):
            destination = output_dir / name
            copy_create_only(staging / name, destination)
            installed.append(destination)
    except Exception:
        for path in installed:
            path.unlink(missing_ok=True)
        try:
            output_dir.rmdir()
        except OSError:
            pass
        raise


def resolve_real_source_dir(source_dir: Path) -> Path:
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("exact route replay must be a real directory")
    return source_dir.resolve()


def resolve_new_output_dir(output_dir: Path) -> Path:
    if output_dir.is_symlink():
        raise ValueError("output may not be a symlink")
    parent = output_dir.parent
    while not parent.exists() and not parent.is_symlink():
        if parent == parent.parent:
            break
        parent = parent.parent
    if parent.is_symlink():
        raise ValueError(f"output parent may not be a symlink: {parent}")
    if parent.exists() and not parent.is_dir():
        raise ValueError(f"output parent is not a directory: {parent}")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise ValueError(f"output already exists: {output_dir}")
    return output_dir


def stage(source_dir: Path, verification_path: Path, output_dir: Path, route: str) -> None:
    if route not in SUPPORTED_ROUTES:
        raise ValueError(f"unsupported executable cross-check route: {route}")
    source_dir = resolve_real_source_dir(source_dir)
    output_dir = resolve_new_output_dir(output_dir)
    if (
        source_dir == output_dir
        or source_dir.is_relative_to(output_dir)
        or output_dir.is_relative_to(source_dir)
    ):
        raise ValueError("output must be separate from the exact route replay")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary:
        staging = Path(temporary)
        shutil.copyfile(require_source_file(source_dir, "report.md"), staging / "report.md")
        shutil.copyfile(
            require_source_file(source_dir, "report_manifest.json"),
            staging / "report_manifest.json",
        )
        copy_route_support_files(source_dir, staging)
        summary = require_download_verification(verification_path, staging, route)
        source_manifest = load_json(
            staging / "report_manifest.json", "route report manifest"
        )
        method_spec = {
            "schema_version": 1,
            "method_id": route,
            "route": route,
            "report_kind": "executable_crosscheck_method",
            "evidence_status": summary["evidence_status"],
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "source_object_count": summary["source_object_count"],
            "source_report_manifest_sha256": summary[
                "source_report_manifest_sha256"
            ],
            "source_report_sha256": summary["source_report_sha256"],
            "download_verification_sha256": summary[
                "download_verification_sha256"
            ],
            "source_review_summary": source_manifest["review_summary"],
        }
        write_json(staging / "method_spec.json", method_spec)

        manifest = {
            "schema_version": 1,
            "method_id": route,
            "report_kind": "executable_crosscheck_method",
            "route": route,
            "evidence_status": summary["evidence_status"],
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "review_summary": source_manifest["review_summary"],
            "source_sha256": {
                "download_verification": summary["download_verification_sha256"],
                "source_report": summary["source_report_sha256"],
                "source_report_manifest": summary[
                    "source_report_manifest_sha256"
                ],
            },
            "support_sha256": {
                "method_spec.json": sha256(staging / "method_spec.json"),
            },
            "report_sha256": sha256(staging / "report.md"),
        }
        write_json(staging / "report_manifest.json", manifest)
        install_staged_packet(staging, output_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--download-verification", required=True, type=Path)
    parser.add_argument("--route", required=True, choices=sorted(SUPPORTED_ROUTES))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    stage(args.source_dir, args.download_verification, args.output_dir, args.route)
    print(json.dumps({"status": "passed", "output": str(args.output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
