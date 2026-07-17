#!/usr/bin/env python3
"""Stage a compact HRD cross-check packet from an exact route replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Sequence

from hrd_report_inventory import EXECUTABLE_CROSSCHECK_METHOD_IDS

SUPPORTED_ROUTES = set(EXECUTABLE_CROSSCHECK_METHOD_IDS)
SHA256_HEX = set("0123456789abcdef")


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


def require_source_file(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
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
        local = source_dir / relative
        if (
            row is None
            or not local.is_file()
            or local.is_symlink()
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

    return {
        "route": route,
        "evidence_status": evidence_status,
        "source_object_count": len(rows),
        "download_verification_sha256": sha256(verification_path),
        "source_report_manifest_sha256": sha256(source_dir / "report_manifest.json"),
        "source_report_sha256": sha256(source_dir / "report.md"),
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stage(source_dir: Path, verification_path: Path, output_dir: Path, route: str) -> None:
    if route not in SUPPORTED_ROUTES:
        raise ValueError(f"unsupported executable cross-check route: {route}")
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    if (
        source_dir == output_dir
        or source_dir.is_relative_to(output_dir)
        or output_dir.is_relative_to(source_dir)
    ):
        raise ValueError("output must be separate from the exact route replay")
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError(f"output already exists: {output_dir}")
    if not source_dir.is_dir() or source_dir.is_symlink():
        raise ValueError("exact route replay must be a real directory")

    source_manifest = load_json(
        source_dir / "report_manifest.json", "route report manifest"
    )
    summary = require_download_verification(verification_path, source_dir, route)

    staging = output_dir.parent / f".{output_dir.name}.staging"
    if staging.exists() or staging.is_symlink():
        raise ValueError(f"staging path already exists: {staging}")
    staging.mkdir(parents=True, mode=0o700)
    try:
        shutil.copyfile(require_source_file(source_dir, "report.md"), staging / "report.md")
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
        os.replace(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


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
