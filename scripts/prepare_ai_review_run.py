#!/usr/bin/env python3
"""Prepare a seven-method WGS HRD bundle for two independent AI reviews."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    checked_source_artifact_id,
    reject_duplicate_json_object_names,
)
from forbidden_text import merge_forbidden_tokens
from hrd_report_inventory import (
    INVENTORY_ID,
    inventory_payload,
    inventory_sha256,
    require_inventory_binding,
    required_method_ids,
)

MANIFEST_ARGUMENTS = (
    "deterministic_manifest",
    "rosalind_manifest",
    "sequenza_manifest",
    "sigprofiler_manifest",
    "facets_blocked_manifest",
    "oncoanalyser_blocked_manifest",
    "hrdetect_blocked_manifest",
)
STAGED_RUN_ENTRIES = (
    "bundle",
    "prepare_ai_review_run_receipt.json",
    "reviewer-inputs",
    "stage_ai_review_inputs_receipt.json",
)
STAGE_RECEIPT_CHECKS = {
    "bundle_manifest_bound": True,
    "reviewer_a_two_file_inventory": True,
    "reviewer_b_two_file_inventory": True,
    "no_cross_prompt": True,
}
STAGE_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "generated_at",
    "bundle_dir",
    "output_root",
    "reviewers",
    "checks",
}
EXPECTED_PREPARE_POSTCONDITION_CHECKS = {
    "pinned_seven_method_inventory": True,
    "source_report_hashes_match": True,
    "bundle_manifest_bound": True,
    "reviewer_a_two_file_inventory": True,
    "reviewer_b_two_file_inventory": True,
    "no_cross_prompt": True,
    "stage_receipt_exact": True,
    "no_model_invoked": True,
    "reviewer_a_prompt_bound": True,
    "reviewer_b_prompt_bound": True,
}
REVIEWER_INPUTS = {
    "A": ("reviewer-a-input", "reviewer-a.prompt.md"),
    "B": ("reviewer-b-input", "reviewer-b.prompt.md"),
}
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
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(
            f"duplicate JSON object name in {path.name}: {error}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def require_installed_json(path: Path, expected_sha256: str) -> None:
    require_real_file(path, "staged AI review JSON")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"staged AI review JSON mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"staged AI review JSON changed during write: {path}")


def write_json(path: Path, value: dict[str, Any], *, create: bool = False) -> None:
    require_no_symlinked_ancestors(path, "staged AI review JSON")
    if path.is_symlink():
        raise ValueError(f"staged AI review JSON may not be a symlink: {path}")
    if create and path.exists():
        raise FileExistsError(f"staged AI review JSON already exists: {path}")
    if not create:
        require_real_file(path, "staged AI review JSON")

    data = canonical_json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if create:
            os.link(temporary, path)
            linked = True
        else:
            os.replace(temporary, path)
        fsync_directory(path.parent)
        require_installed_json(path, expected_sha256)
    except Exception:
        if create and linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def require_real_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink():
        raise ValueError(f"{label} must be a real non-empty file")
    resolved = path.resolve()
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ValueError(f"{label} must be a real non-empty file")
    return resolved


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")


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
        not is_exact_int(manifest.get("schema_version"), 1)
        or manifest.get("method_id") != expected_method
        or manifest.get("report_sha256") != sha256(report_path)
        or not isinstance(source_sha256, dict)
        or not source_sha256
        or not isinstance(review_summary, dict)
        or not review_summary
    ):
        raise ValueError(f"{expected_method} report manifest is not exact")
    for key, digest in source_sha256.items():
        checked_source_artifact_id(key, expected_method)
        require_sha256(digest, f"{expected_method} source_sha256.{key}")
    return manifest


def required_methods(args: argparse.Namespace) -> tuple[str, ...]:
    return required_method_ids(args.inventory_id)


def manifest_arguments_for_methods(methods: tuple[str, ...]) -> dict[str, str]:
    if len(methods) != len(MANIFEST_ARGUMENTS):
        raise ValueError(
            "HRD report inventory must have exactly one manifest argument per "
            f"required method; methods={len(methods)} arguments={len(MANIFEST_ARGUMENTS)}"
        )
    return dict(zip(methods, MANIFEST_ARGUMENTS))


def method_manifest_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        method_id: Path(getattr(args, argument))
        for method_id, argument in manifest_arguments_for_methods(
            required_methods(args)
        ).items()
    }


def parse_expected_source_manifest_sha256(
    values: Sequence[str],
    inventory_id: str,
) -> dict[str, str]:
    methods = required_method_ids(inventory_id)
    result: dict[str, str] = {}
    for value in values:
        method_id, separator, digest = value.partition("=")
        if not separator:
            raise ValueError("expected source manifest SHA-256 values must use method_id=sha256")
        if method_id not in methods:
            raise ValueError(f"unexpected source manifest method: {method_id}")
        if method_id in result:
            raise ValueError(f"duplicate source manifest SHA-256 for {method_id}")
        if SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError(f"source manifest SHA-256 for {method_id} is not lowercase hex")
        result[method_id] = digest

    if set(result) != set(methods):
        raise ValueError("expected source manifest SHA-256 values must cover exactly the seven required methods")
    return {method_id: result[method_id] for method_id in methods}


def validate_sources(
    output: Path,
    manifest_paths: dict[str, Path],
    expected_sha256: dict[str, str],
    methods: tuple[str, ...],
) -> dict[str, dict[str, str]]:
    source_manifests: dict[str, dict[str, str]] = {}
    seen_paths: set[Path] = set()
    seen_dirs: set[Path] = set()
    for method_id in methods:
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
    methods = required_methods(args)
    command = [
        sys.executable,
        str(script_path("build_ai_review_bundle.py")),
        "--inventory-id",
        args.inventory_id,
    ]
    for method_id in methods:
        command.extend(["--manifest", str(manifest_paths[method_id])])
    for method_id in methods:
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
    output: Path,
    inventory_id: str,
) -> dict[str, Any]:
    methods = required_method_ids(inventory_id)
    bundle_manifest_path = bundle_dir / "bundle_manifest.json"
    bundle_manifest = load_object(bundle_manifest_path)
    stage_receipt = load_object(stage_receipt_path)
    require_inventory_binding(
        bundle_manifest.get("method_inventory"),
        bundle_manifest.get("method_inventory_sha256"),
        "AI review bundle",
        inventory_id,
    )
    expected_inputs = {
        f"E{index:03d}": source_manifests[method]["sha256"]
        for index, method in enumerate(methods, 1)
    }
    stage_receipt_reviewers = require_rebased_stage_receipt(
        stage_receipt,
        output,
        bundle_manifest,
    )
    expected_prompt_hashes = bundle_manifest["prompt_sha256"]
    checks = {
        "pinned_seven_method_inventory": bundle_manifest.get("required_method_ids") == list(methods),
        "source_report_hashes_match": bundle_manifest.get("input_manifest_sha256") == expected_inputs,
        "bundle_manifest_bound": bundle_manifest.get("review_bundle_sha256") == sha256(bundle_dir / "review_bundle.json"),
        "reviewer_a_two_file_inventory": sorted(path.name for path in (reviewer_root / "reviewer-a-input").iterdir())
        == ["review_bundle.json", "reviewer-a.prompt.md"],
        "reviewer_b_two_file_inventory": sorted(path.name for path in (reviewer_root / "reviewer-b-input").iterdir())
        == ["review_bundle.json", "reviewer-b.prompt.md"],
        "no_cross_prompt": not (reviewer_root / "reviewer-a-input" / "reviewer-b.prompt.md").exists()
        and not (reviewer_root / "reviewer-b-input" / "reviewer-a.prompt.md").exists(),
        "stage_receipt_exact": True,
        "no_model_invoked": True,
        "reviewer_a_prompt_bound": expected_prompt_hashes.get("A") == sha256(bundle_dir / "reviewer-a.prompt.md"),
        "reviewer_b_prompt_bound": expected_prompt_hashes.get("B") == sha256(bundle_dir / "reviewer-b.prompt.md"),
    }
    require_exact_postcondition_checks(checks)
    return {
        "bundle_manifest": bundle_manifest,
        "stage_receipt_reviewers": stage_receipt_reviewers,
        "stage_receipt": stage_receipt,
        "checks": checks,
    }


def require_exact_postcondition_checks(checks: dict[str, Any]) -> None:
    missing = sorted(set(EXPECTED_PREPARE_POSTCONDITION_CHECKS) - set(checks))
    unexpected = sorted(set(checks) - set(EXPECTED_PREPARE_POSTCONDITION_CHECKS))
    failed = sorted(
        key
        for key in set(EXPECTED_PREPARE_POSTCONDITION_CHECKS) & set(checks)
        if checks[key] is not True
    )
    if missing or unexpected or failed:
        details = []
        if missing:
            details.append("missing " + ",".join(missing))
        if unexpected:
            details.append("unexpected " + ",".join(unexpected))
        if failed:
            details.append("failed " + ",".join(failed))
        raise ValueError(
            "AI review prep postcondition map is not exact: " + "; ".join(details)
        )


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} is malformed")
    return value


def require_rebased_stage_receipt(
    receipt: dict[str, Any],
    output: Path,
    bundle_manifest: dict[str, Any],
) -> dict[str, Any]:
    review_bundle_sha256 = require_sha256(
        bundle_manifest.get("review_bundle_sha256"),
        "review_bundle.json SHA-256",
    )
    prompt_sha256 = bundle_manifest.get("prompt_sha256")
    if not isinstance(prompt_sha256, dict) or set(prompt_sha256) != set(REVIEWER_INPUTS):
        raise ValueError("AI review bundle manifest lacks exact prompt hashes")

    expected_reviewers: dict[str, Any] = {}
    for role, (directory, prompt) in REVIEWER_INPUTS.items():
        expected_reviewers[role] = {
            "directory": str(output / "reviewer-inputs" / directory),
            "exact_two_file_inventory": ["review_bundle.json", prompt],
            "files": {
                "review_bundle.json": {
                    "mode_0600": True,
                    "sha256": review_bundle_sha256,
                },
                prompt: {
                    "mode_0600": True,
                    "sha256": require_sha256(
                        prompt_sha256.get(role),
                        f"{prompt} SHA-256",
                    ),
                },
            },
            "mode_0700": True,
        }

    if (
        set(receipt) != STAGE_RECEIPT_KEYS
        or not is_exact_int(receipt.get("schema_version"), 1)
        or receipt.get("status") != "passed"
        or not isinstance(receipt.get("generated_at"), str)
        or not receipt.get("generated_at")
        or receipt.get("bundle_dir") != str(output / "bundle")
        or receipt.get("output_root") != str(output / "reviewer-inputs")
        or receipt.get("reviewers") != expected_reviewers
        or receipt.get("checks") != STAGE_RECEIPT_CHECKS
    ):
        raise ValueError("stage AI review input receipt is not exact")

    return expected_reviewers


def move_staged_entry(source: Path, destination: Path) -> None:
    source.rename(destination)


def fingerprint_staged_entry(path: Path) -> str:
    rows: list[dict[str, Any]] = []

    def add_path(child: Path, relative_path: str) -> None:
        require_no_symlinked_ancestors(child, "staged AI review entry")
        try:
            metadata = os.lstat(child)
        except FileNotFoundError as error:
            raise ValueError(f"staged AI review entry is missing: {child}") from error
        mode = metadata.st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"staged AI review entry may not be a symlink: {child}")
        if stat.S_ISDIR(mode):
            rows.append(
                {
                    "kind": "directory",
                    "mode": stat.S_IMODE(mode),
                    "path": relative_path,
                }
            )
            return
        if stat.S_ISREG(mode):
            rows.append(
                {
                    "bytes": metadata.st_size,
                    "kind": "file",
                    "mode": stat.S_IMODE(mode),
                    "path": relative_path,
                    "sha256": sha256(child),
                }
            )
            return
        raise ValueError(
            "staged AI review entry is not a regular file or directory: "
            + str(child)
        )

    add_path(path, ".")
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            add_path(child, child.relative_to(path).as_posix())

    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def require_new_output_entry(path: Path) -> Path:
    require_no_symlinked_ancestors(path, "output")
    if path.is_symlink():
        raise ValueError(f"output may not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    return path.resolve()


def require_staged_run_inventory(path: Path) -> None:
    observed = tuple(sorted(child.name for child in path.iterdir()))
    if observed != STAGED_RUN_ENTRIES:
        raise ValueError(
            "staged AI review run inventory is not exact; "
            f"expected={STAGED_RUN_ENTRIES!r} observed={observed!r}"
        )


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def resolve_new_output(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"output may not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    require_no_symlinked_ancestors(path, "output")
    for parent in path.parents:
        if parent.exists():
            if not parent.is_dir():
                raise ValueError(f"output parent is not a directory: {parent}")
            return path.resolve()
    return path.resolve()


def install_staged_run(staging: Path, output: Path) -> None:
    if output.is_symlink():
        raise ValueError(f"output may not be a symlink: {output}")
    require_no_symlinked_ancestors(output, "output")
    try:
        output.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ValueError(f"output already exists: {output}") from error

    installed: list[Path] = []
    expected_fingerprints: dict[Path, str] = {}
    try:
        fsync_directory(output.parent)
        require_staged_run_inventory(staging)
        for child in sorted(staging.iterdir(), key=lambda path: path.name):
            destination = output / child.name
            require_new_output_entry(destination)
            expected_fingerprint = fingerprint_staged_entry(child)
            expected_fingerprints[destination] = expected_fingerprint
            destination_preexisted = destination.exists() or destination.is_symlink()
            try:
                move_staged_entry(child, destination)
                installed.append(destination)
                if fingerprint_staged_entry(destination) != expected_fingerprint:
                    raise ValueError(
                        "staged AI review entry changed during install: "
                        + child.name
                    )
            except Exception:
                if (
                    not destination_preexisted
                    and destination.exists()
                    and destination not in installed
                ):
                    installed.append(destination)
                raise
        fsync_directory(output)
        for destination, expected_fingerprint in expected_fingerprints.items():
            if fingerprint_staged_entry(destination) != expected_fingerprint:
                raise ValueError(
                    "staged AI review entry changed during install: "
                    + destination.name
                )
        require_staged_run_inventory(output)
    except Exception:
        for path in reversed(installed):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        with suppress(OSError):
            output.rmdir()
        raise


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    output = resolve_new_output(args.output_dir)
    methods = required_methods(args)

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_paths = method_manifest_paths(args)
    expected_source_sha256 = parse_expected_source_manifest_sha256(
        args.expected_source_manifest_sha256,
        args.inventory_id,
    )
    source_manifests = validate_sources(
        output,
        manifest_paths,
        expected_source_sha256,
        methods,
    )

    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent)))
    keep_staging = False
    try:
        bundle_dir = staging / "bundle"
        reviewer_root = staging / "reviewer-inputs"
        stage_receipt = staging / "stage_ai_review_inputs_receipt.json"

        build_bundle(args, manifest_paths, bundle_dir)
        stage_inputs(bundle_dir, reviewer_root, stage_receipt)
        rebase_stage_receipt(stage_receipt, staging, output)
        postconditions = validate_postconditions(
            bundle_dir,
            reviewer_root,
            stage_receipt,
            source_manifests,
            output,
            args.inventory_id,
        )

        bundle_manifest = postconditions["bundle_manifest"]
        receipt = {
            "schema_version": 1,
            "status": "passed",
            "generated_at": now(),
            "subject_alias": args.subject_alias,
            "method_inventory": inventory_payload(args.inventory_id),
            "method_inventory_sha256": inventory_sha256(args.inventory_id),
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
                for role, details in sorted(postconditions["stage_receipt_reviewers"].items())
            },
            "checks": postconditions["checks"],
        }
        write_json(staging / "prepare_ai_review_run_receipt.json", receipt, create=True)

        install_staged_run(staging, output)
        keep_staging = True
        return receipt
    finally:
        if not keep_staging and staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in MANIFEST_ARGUMENTS:
        parser.add_argument(
            "--" + argument.replace("_", "-"),
            required=True,
            type=Path,
        )
    parser.add_argument(
        "--inventory-id",
        default=INVENTORY_ID,
        help="Pinned HRD report inventory ID. Defaults to the Diana WGS inventory.",
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
