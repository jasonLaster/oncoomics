#!/usr/bin/env python3
"""Prepare a seven-method Diana WGS HRD bundle for two independent AI reviews."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from forbidden_text import merge_forbidden_tokens
from hrd_report_inventory import (
    REQUIRED_METHOD_IDS,
    inventory_payload,
    inventory_sha256,
    require_inventory_binding,
)

METHOD_ARGUMENTS = (
    ("deterministic_full_wgs", "deterministic_manifest"),
    ("rosalind_diana_wgs", "rosalind_manifest"),
    ("sequenza_scarhrd", "sequenza_manifest"),
    ("sigprofiler_sbs3", "sigprofiler_manifest"),
    ("facets_scarhrd_blocked", "facets_blocked_manifest"),
    ("oncoanalyser_chord_blocked", "oncoanalyser_blocked_manifest"),
    ("hrdetect_blocked", "hrdetect_blocked_manifest"),
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_real_file(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ValueError(f"{label} must be a real non-empty file")
    return resolved


def require_manifest(path: Path, expected_method: str) -> dict[str, Any]:
    manifest_path = require_real_file(path, f"{expected_method} manifest")
    report_path = require_real_file(
        manifest_path.parent / "report.md",
        f"{expected_method} report",
    )
    manifest = load_object(manifest_path)
    source_sha256 = manifest.get("source_sha256")
    review_summary = manifest.get("review_summary")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("method_id") != expected_method
        or manifest.get("report_sha256") != sha256(report_path)
        or not isinstance(source_sha256, dict)
        or not source_sha256
        or not isinstance(review_summary, dict)
        or not review_summary
    ):
        raise ValueError(f"{expected_method} report manifest is not exact")
    return manifest


def method_manifest_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {method_id: Path(getattr(args, argument)) for method_id, argument in METHOD_ARGUMENTS}


def parse_expected_source_manifest_sha256(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        method_id, separator, digest = value.partition("=")
        if not separator:
            raise ValueError("expected source manifest SHA-256 values must use method_id=sha256")
        if method_id not in REQUIRED_METHOD_IDS:
            raise ValueError(f"unexpected source manifest method: {method_id}")
        if method_id in result:
            raise ValueError(f"duplicate source manifest SHA-256 for {method_id}")
        if SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError(f"source manifest SHA-256 for {method_id} is not lowercase hex")
        result[method_id] = digest

    if set(result) != set(REQUIRED_METHOD_IDS):
        raise ValueError("expected source manifest SHA-256 values must cover exactly the seven required methods")
    return {method_id: result[method_id] for method_id in REQUIRED_METHOD_IDS}


def validate_sources(
    output: Path,
    manifest_paths: dict[str, Path],
    expected_sha256: dict[str, str],
) -> dict[str, dict[str, str]]:
    source_manifests: dict[str, dict[str, str]] = {}
    seen_paths: set[Path] = set()
    seen_dirs: set[Path] = set()
    for method_id in REQUIRED_METHOD_IDS:
        path = require_real_file(manifest_paths[method_id], f"{method_id} manifest")
        directory = path.parent.resolve()
        if path in seen_paths:
            raise ValueError(f"duplicate source manifest path for {method_id}")
        if directory in seen_dirs:
            raise ValueError(f"duplicate source packet directory for {method_id}")
        if path.is_relative_to(output) or directory.is_relative_to(output):
            raise ValueError(f"source manifest for {method_id} is inside output")
        require_manifest(path, method_id)
        actual_sha256 = sha256(path)
        if actual_sha256 != expected_sha256.get(method_id):
            raise ValueError(f"{method_id} source manifest SHA-256 is not receipt-bound")
        source_manifests[method_id] = {
            "path": str(path),
            "sha256": actual_sha256,
        }
        seen_paths.add(path)
        seen_dirs.add(directory)
    return source_manifests


def script_path(name: str) -> Path:
    return Path(__file__).resolve().parent / name


def run_checked(command: list[str]) -> None:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        detail = "\n".join(item for item in (result.stdout.strip(), result.stderr.strip()) if item)
        raise RuntimeError(detail or f"command failed: {command[0]}")


def build_bundle(
    args: argparse.Namespace,
    manifest_paths: dict[str, Path],
    bundle_dir: Path,
) -> None:
    command = [
        sys.executable,
        str(script_path("build_ai_review_bundle.py")),
    ]
    for method_id in REQUIRED_METHOD_IDS:
        command.extend(["--manifest", str(manifest_paths[method_id])])
    for method_id in REQUIRED_METHOD_IDS:
        command.extend(["--require-method", method_id])
    command.extend(
        [
            "--output-dir",
            str(bundle_dir),
            "--subject-alias",
            args.subject_alias,
            "--reviewer-a-provider",
            args.reviewer_a_provider,
            "--reviewer-a-model-id",
            args.reviewer_a_model_id,
            "--reviewer-b-provider",
            args.reviewer_b_provider,
            "--reviewer-b-model-id",
            args.reviewer_b_model_id,
            "--model-catalog-verified-at",
            args.model_catalog_verified_at,
            "--model-catalog-receipt",
            str(args.model_catalog_receipt),
            "--attest-models-latest",
        ]
    )
    for token in merge_forbidden_tokens(
        args.forbidden_token,
        files=args.forbidden_tokens_file,
    ):
        command.extend(["--forbidden-token", token])
    run_checked(command)


def stage_inputs(bundle_dir: Path, output_root: Path, receipt_output: Path) -> None:
    run_checked(
        [
            sys.executable,
            str(script_path("stage_ai_review_inputs.py")),
            "--bundle-dir",
            str(bundle_dir),
            "--output-root",
            str(output_root),
            "--receipt-output",
            str(receipt_output),
        ]
    )


def rebase_stage_receipt(stage_receipt: Path, staging_root: Path, final_root: Path) -> dict[str, Any]:
    payload = load_object(stage_receipt)

    def rebase(value: str) -> str:
        prefix = str(staging_root)
        if value == prefix:
            return str(final_root)
        if value.startswith(prefix + os.sep):
            return str(final_root) + value[len(prefix) :]
        return value

    payload["bundle_dir"] = rebase(str(payload.get("bundle_dir", "")))
    payload["output_root"] = rebase(str(payload.get("output_root", "")))
    reviewers = payload.get("reviewers")
    if isinstance(reviewers, dict):
        for reviewer in reviewers.values():
            if isinstance(reviewer, dict):
                reviewer["directory"] = rebase(str(reviewer.get("directory", "")))
    write_json(stage_receipt, payload)
    return payload


def validate_postconditions(
    bundle_dir: Path,
    reviewer_root: Path,
    stage_receipt_path: Path,
    source_manifests: dict[str, dict[str, str]],
) -> dict[str, Any]:
    bundle_manifest_path = bundle_dir / "bundle_manifest.json"
    bundle_manifest = load_object(bundle_manifest_path)
    stage_receipt = load_object(stage_receipt_path)
    require_inventory_binding(
        bundle_manifest.get("method_inventory"),
        bundle_manifest.get("method_inventory_sha256"),
        "AI review bundle",
    )
    expected_inputs = {f"E{index:03d}": source_manifests[method]["sha256"] for index, method in enumerate(REQUIRED_METHOD_IDS, 1)}
    checks = {
        "pinned_seven_method_inventory": bundle_manifest.get("required_method_ids") == list(REQUIRED_METHOD_IDS),
        "source_report_hashes_match": bundle_manifest.get("input_manifest_sha256") == expected_inputs,
        "bundle_manifest_bound": bundle_manifest.get("review_bundle_sha256") == sha256(bundle_dir / "review_bundle.json"),
        "reviewer_a_two_file_inventory": sorted(path.name for path in (reviewer_root / "reviewer-a-input").iterdir())
        == ["review_bundle.json", "reviewer-a.prompt.md"],
        "reviewer_b_two_file_inventory": sorted(path.name for path in (reviewer_root / "reviewer-b-input").iterdir())
        == ["review_bundle.json", "reviewer-b.prompt.md"],
        "no_cross_prompt": not (reviewer_root / "reviewer-a-input" / "reviewer-b.prompt.md").exists()
        and not (reviewer_root / "reviewer-b-input" / "reviewer-a.prompt.md").exists(),
        "stage_receipt_passed": stage_receipt.get("status") == "passed",
        "no_model_invoked": True,
    }
    expected_prompt_hashes = bundle_manifest.get("prompt_sha256", {})
    if isinstance(expected_prompt_hashes, dict):
        checks["reviewer_a_prompt_bound"] = expected_prompt_hashes.get("A") == sha256(bundle_dir / "reviewer-a.prompt.md")
        checks["reviewer_b_prompt_bound"] = expected_prompt_hashes.get("B") == sha256(bundle_dir / "reviewer-b.prompt.md")
    if not all(checks.values()):
        failed = ", ".join(key for key, value in checks.items() if not value)
        raise ValueError(f"AI review prep postcondition failed: {failed}")
    return {
        "bundle_manifest": bundle_manifest,
        "stage_receipt": stage_receipt,
        "checks": checks,
    }


def move_staged_entry(source: Path, destination: Path) -> None:
    source.rename(destination)


def resolve_new_output(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"output may not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError(f"output parent may not be a symlink: {parent}")
        if parent.exists():
            if not parent.is_dir():
                raise ValueError(f"output parent is not a directory: {parent}")
            return path.resolve()
    return path.resolve()


def install_staged_run(staging: Path, output: Path) -> None:
    try:
        output.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ValueError(f"output already exists: {output}") from error

    try:
        for child in sorted(staging.iterdir(), key=lambda path: path.name):
            move_staged_entry(child, output / child.name)
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    output = resolve_new_output(args.output_dir)

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_paths = method_manifest_paths(args)
    expected_source_sha256 = parse_expected_source_manifest_sha256(args.expected_source_manifest_sha256)
    source_manifests = validate_sources(
        output,
        manifest_paths,
        expected_source_sha256,
    )

    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent)))
    keep_staging = False
    try:
        bundle_dir = staging / "bundle"
        reviewer_root = staging / "reviewer-inputs"
        stage_receipt = staging / "stage_ai_review_inputs_receipt.json"

        build_bundle(args, manifest_paths, bundle_dir)
        stage_inputs(bundle_dir, reviewer_root, stage_receipt)
        stage_receipt_payload = rebase_stage_receipt(stage_receipt, staging, output)
        postconditions = validate_postconditions(
            bundle_dir,
            reviewer_root,
            stage_receipt,
            source_manifests,
        )

        bundle_manifest = postconditions["bundle_manifest"]
        receipt = {
            "schema_version": 1,
            "status": "passed",
            "generated_at": now(),
            "subject_alias": args.subject_alias,
            "method_inventory": inventory_payload(),
            "method_inventory_sha256": inventory_sha256(),
            "source_manifests": source_manifests,
            "model_catalog_receipt_sha256": sha256(require_real_file(args.model_catalog_receipt, "model catalog receipt")),
            "bundle_dir": str(output / "bundle"),
            "bundle_manifest_sha256": sha256(bundle_dir / "bundle_manifest.json"),
            "review_bundle_sha256": bundle_manifest["review_bundle_sha256"],
            "prompt_sha256": bundle_manifest["prompt_sha256"],
            "stage_receipt_sha256": sha256(stage_receipt),
            "reviewer_inputs": {
                role: {
                    "directory": details["directory"],
                    "exact_two_file_inventory": details["exact_two_file_inventory"],
                }
                for role, details in sorted(stage_receipt_payload["reviewers"].items())
            },
            "checks": postconditions["checks"],
        }
        write_json(staging / "prepare_ai_review_run_receipt.json", receipt)

        install_staged_run(staging, output)
        keep_staging = True
        return receipt
    finally:
        if not keep_staging and staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for _, argument in METHOD_ARGUMENTS:
        parser.add_argument(
            "--" + argument.replace("_", "-"),
            required=True,
            type=Path,
        )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--subject-alias", required=True)
    parser.add_argument("--model-catalog-receipt", required=True, type=Path)
    parser.add_argument("--model-catalog-verified-at", required=True)
    parser.add_argument("--reviewer-a-provider", required=True)
    parser.add_argument("--reviewer-a-model-id", required=True)
    parser.add_argument("--reviewer-b-provider", required=True)
    parser.add_argument("--reviewer-b-model-id", required=True)
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument("--forbidden-tokens-file", action="append", default=[], type=Path)
    parser.add_argument(
        "--expected-source-manifest-sha256",
        required=True,
        action="append",
        help=("repeat as method_id=sha256 once for each source manifest in the canonical seven-method order"),
    )
    args = parser.parse_args(argv)

    try:
        receipt = prepare(args)
    except (
        FileExistsError,
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "bundle_dir": receipt["bundle_dir"],
                "reviewer_a_input": receipt["reviewer_inputs"]["A"]["directory"],
                "reviewer_b_input": receipt["reviewer_inputs"]["B"]["directory"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
