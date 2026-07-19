#!/usr/bin/env python3
"""Build a static index for explicitly reviewed public S3 analysis prefixes."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
from typing import Any, Sequence

from hrd_report_inventory import REPORT_METHOD_IDS
from publish_reviewed_public_report import (
    CLASSIFICATION as REVIEWED_PUBLIC_CLASSIFICATION,
)
from publish_reviewed_public_report import (
    MAX_FILE_BYTES,
    METHOD_CONTRACTS,
    PRIVATE_BUCKET,
    PUBLIC_BUCKET,
    PUBLIC_DESTINATION_OBJECT_CHECKS,
    PUBLIC_ROOT,
    REVIEWED_PUBLIC_PREFLIGHT_CHECKS,
    RUN_ID,
    SHA256_HEX,
    SOURCE_PREFLIGHT_CHECKS,
    SUBJECT_ALIAS,
    checksum_sha256,
    non_null_version_id,
    private_report_prefix,
)

REGION = "us-east-1"
BUCKET = PUBLIC_BUCKET
DIANA_HRD_PUBLIC_PREFIXES = tuple(
    PUBLIC_ROOT + str(contract["destination"])
    for contract in METHOD_CONTRACTS.values()
)
PUBLIC_PREFIXES = (
    *DIANA_HRD_PUBLIC_PREFIXES,
    "runs/known_answer_bounded_non_dry/",
    "runs/known_answer_expanded_cohort/",
    "runs/known_answer_public_findings/",
    "runs/phase3_fastpath_forcealign_minimap2_scatter8_normal_shardmanifest_20260614T2117Z/",
    "runs/phase3_fastpath_forcealign_minimap2_scatter8_tumor_shardmanifest_20260614T2040Z/",
    "runs/phase3_sra_benchmark/",
    "runs/phase3_wgs/",
    "runs/phase3_wgs_scatter/",
    "runs/rosalind_hrd/cloud-colo829-guardrail-20260617/",
    "runs/rosalind_hrd/cloud-hcc1395-wes-20260617/",
    "runs/rosalind_hrd/cloud-helper-selective5-20260617/",
    "runs/rosalind_hrd/cloud-hg008-depth-20260617/",
    "runs/rosalind_hrd/cloud-selective5-20260617/",
)
FORBIDDEN_PREFIXES = (
    "runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/",
    "runs/diana-raw-intake/",
    "runs/rosalind_hrd/cloud-diana-raw-intake-20260617/",
    "runs/rosalind_hrd/cloud-diana-raw-intake-handoff-20260617/",
    "version-history/",
)
REVIEWED_PUBLIC_APPLY_CHECKS = {
    **{check_id: True for check_id in REVIEWED_PUBLIC_PREFLIGHT_CHECKS},
    "all_destination_writes_create_only": True,
    "destination_sse_s3": True,
    "destination_full_object_sha256": True,
    "destination_non_null_versions": True,
    "destination_exact_one_version_no_delete_history": True,
}


def list_prefix(prefix: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    continuation_token = ""
    seen_tokens: set[str] = set()

    while True:
        command = [
            "aws",
            "s3api",
            "list-objects-v2",
            "--region",
            REGION,
            "--bucket",
            BUCKET,
            "--prefix",
            prefix,
            "--output",
            "json",
        ]
        if continuation_token:
            command.extend(["--continuation-token", continuation_token])
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        response = json.loads(result.stdout)
        contents = response.get("Contents", [])
        if not isinstance(contents, list) or any(
            not isinstance(item, dict) for item in contents
        ):
            raise RuntimeError(f"S3 returned malformed objects for {prefix}")
        for item in contents:
            key = item["Key"]
            if not key.startswith(prefix):
                raise RuntimeError(f"S3 returned an object outside {prefix}: {key}")
            if any(key.startswith(blocked) for blocked in FORBIDDEN_PREFIXES):
                raise RuntimeError(f"Refusing to index private object: {key}")
            if key.endswith("/"):
                continue
            objects.append(
                {
                    "key": key,
                    "size": item["Size"],
                    "last_modified": item["LastModified"],
                }
            )

        if response.get("IsTruncated") is not True:
            return objects
        next_token = str(response.get("NextContinuationToken", ""))
        if not next_token or next_token in seen_tokens:
            raise RuntimeError(f"S3 pagination did not advance for {prefix}")
        seen_tokens.add(next_token)
        continuation_token = next_token


def write_index(path: pathlib.Path, payload: dict[str, Any]) -> None:
    """Atomically create the local public index without following symlinks."""

    require_new_index_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(payload)
    expected_sha256 = sha256_bytes(data)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = pathlib.Path(raw)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        linked = True
        fsync_directory(path.parent)
        require_installed_index(path, expected_sha256)
    except Exception:
        if linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def fsync_directory(path: pathlib.Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_installed_index(path: pathlib.Path, expected_sha256: str) -> None:
    require_real_input_file(path, "public index output")
    if sha256(path) != expected_sha256:
        raise RuntimeError(f"public index output changed during write: {path}")


def load_json_object(path: pathlib.Path, label: str) -> dict[str, Any]:
    require_real_input_file(path, label)
    if path.stat().st_size <= 0:
        raise RuntimeError(f"{label} must be a real non-empty file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object: {path}")
    return value


def validate_reviewed_public_receipts(
    paths: Sequence[pathlib.Path],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if len(paths) != len(REPORT_METHOD_IDS):
        raise RuntimeError(
            "reviewed-public index build requires exactly ten public publication receipts"
        )

    receipt_objects: dict[str, int] = {}
    receipt_binding: list[dict[str, Any]] = []
    for method_id, path in zip(REPORT_METHOD_IDS, paths):
        receipt = load_json_object(path, f"{method_id} reviewed-public receipt")
        contract = METHOD_CONTRACTS[method_id]
        expected_files = tuple(sorted(contract["files"]))
        expected_prefix = f"s3://{BUCKET}/{PUBLIC_ROOT}{contract['destination']}"
        if (
            receipt.get("schema_version") != 1
            or receipt.get("status") != "passed"
            or receipt.get("apply") is not True
            or receipt.get("method_id") != method_id
            or receipt.get("subject_alias") != SUBJECT_ALIAS
            or receipt.get("run_id") != RUN_ID
            or receipt.get("classification") != REVIEWED_PUBLIC_CLASSIFICATION
            or receipt.get("destination_prefix") != expected_prefix
            or tuple(receipt.get("expected_files", ())) != expected_files
        ):
            raise RuntimeError(f"{method_id} reviewed-public receipt is not exact")

        checks = receipt.get("checks")
        private_publication_receipt = receipt.get("private_publication_receipt")
        source_objects = receipt.get("source_objects")
        destination_objects = receipt.get("destination_objects")
        if (
            not isinstance(checks, dict)
            or not isinstance(private_publication_receipt, dict)
            or not isinstance(source_objects, list)
            or not isinstance(destination_objects, list)
        ):
            raise RuntimeError(f"{method_id} reviewed-public receipt is incomplete")
        if checks != REVIEWED_PUBLIC_APPLY_CHECKS:
            raise RuntimeError(f"{method_id} reviewed-public receipt failed required checks")
        if len(source_objects) != len(expected_files) or len(destination_objects) != len(expected_files):
            raise RuntimeError(f"{method_id} reviewed-public receipt has the wrong object count")
        try:
            private_bucket, private_prefix = private_report_prefix(
                method_id,
                str(private_publication_receipt.get("destination_prefix", "")),
            )
        except ValueError as error:
            raise RuntimeError(
                f"{method_id} reviewed-public private receipt is not exact"
            ) from error
        private_receipt_sha256 = str(private_publication_receipt.get("sha256", ""))
        if private_bucket != PRIVATE_BUCKET or not SHA256_HEX.fullmatch(
            private_receipt_sha256
        ):
            raise RuntimeError(f"{method_id} reviewed-public private receipt is not exact")

        expected_private_key_by_relative = {
            relative: f"{private_prefix}{relative}"
            for relative in expected_files
        }
        expected_key_by_relative = {
            relative: f"{PUBLIC_ROOT}{contract['destination']}{relative}"
            for relative in expected_files
        }
        expected_keys = set(expected_key_by_relative.values())
        source_by_relative: dict[str, dict[str, int | str]] = {}
        for row in source_objects:
            if not isinstance(row, dict) or row.get("status") != "passed":
                raise RuntimeError(f"{method_id} reviewed-public source object is incomplete")
            relative = str(row.get("relative_path", ""))
            key = str(row.get("key", ""))
            digest = str(row.get("sha256", ""))
            version_id = str(row.get("version_id", ""))
            checks = row.get("checks")
            try:
                size = int(row.get("bytes", -1))
            except (TypeError, ValueError):
                size = -1
            if (
                relative in source_by_relative
                or row.get("bucket") != PRIVATE_BUCKET
                or relative not in expected_private_key_by_relative
                or key != expected_private_key_by_relative[relative]
                or not non_null_version_id(version_id)
                or not SHA256_HEX.fullmatch(digest)
                or row.get("checksum_sha256") != checksum_sha256(digest)
                or size <= 0
                or size > MAX_FILE_BYTES
                or checks != SOURCE_PREFLIGHT_CHECKS
            ):
                raise RuntimeError(
                    f"{method_id} reviewed-public source object is not exact: {relative}"
                )
            source_by_relative[relative] = {
                "bytes": size,
                "sha256": digest,
                "checksum_sha256": str(row.get("checksum_sha256", "")),
            }
        if set(source_by_relative) != set(expected_files):
            raise RuntimeError(f"{method_id} reviewed-public source objects do not match the public contract")

        observed_relative_paths = set()
        observed_keys = set()
        for row in destination_objects:
            if not isinstance(row, dict) or row.get("status") != "passed":
                raise RuntimeError(f"{method_id} reviewed-public destination object is incomplete")
            relative = str(row.get("relative_path", ""))
            key = str(row.get("key", ""))
            digest = str(row.get("sha256", ""))
            version_id = str(row.get("version_id", ""))
            checks = row.get("checks")
            try:
                size = int(row.get("bytes", -1))
            except (TypeError, ValueError):
                size = -1
            observed_relative_paths.add(relative)
            observed_keys.add(key)
            if (
                row.get("bucket") != BUCKET
                or relative not in expected_key_by_relative
                or key != expected_key_by_relative[relative]
                or row.get("uri") != f"s3://{BUCKET}/{key}"
                or not non_null_version_id(version_id)
                or not SHA256_HEX.fullmatch(digest)
                or row.get("checksum_sha256") != checksum_sha256(digest)
                or row.get("server_side_encryption") != "AES256"
                or size <= 0
                or size > MAX_FILE_BYTES
                or checks != PUBLIC_DESTINATION_OBJECT_CHECKS
            ):
                raise RuntimeError(
                    f"{method_id} reviewed-public destination object is not exact: {relative}"
                )
            source = source_by_relative[relative]
            if (
                size != source["bytes"]
                or digest != source["sha256"]
                or row.get("checksum_sha256") != source["checksum_sha256"]
            ):
                raise RuntimeError(
                    f"{method_id} reviewed-public destination object is not source-bound: {relative}"
                )
            if key in receipt_objects:
                raise RuntimeError(f"{method_id} reviewed-public destination key is duplicated: {key}")
            receipt_objects[key] = size
        if observed_keys != expected_keys or observed_relative_paths != set(expected_files):
            raise RuntimeError(f"{method_id} reviewed-public receipt objects do not match the public contract")

        receipt_binding.append(
            {
                "method_id": method_id,
                "sha256": sha256(path),
                "destination_prefix": expected_prefix,
                "object_count": len(expected_files),
            }
        )

    return receipt_objects, receipt_binding


def validate_reviewed_public_s3_state(
    objects: Sequence[dict[str, Any]],
    expected_objects: dict[str, int],
) -> None:
    observed_objects = {
        str(item["key"]): int(item["size"])
        for item in objects
        if any(str(item["key"]).startswith(prefix) for prefix in DIANA_HRD_PUBLIC_PREFIXES)
    }
    missing = sorted(set(expected_objects) - set(observed_objects))
    unexpected = sorted(set(observed_objects) - set(expected_objects))
    size_mismatches = sorted(
        key
        for key, expected_size in expected_objects.items()
        if key in observed_objects and observed_objects[key] != expected_size
    )
    if missing or unexpected or size_mismatches:
        details = {
            "missing": missing,
            "unexpected": unexpected,
            "size_mismatches": size_mismatches,
        }
        raise RuntimeError(
            "reviewed-public S3 state does not match publication receipts: "
            + json.dumps(details, sort_keys=True)
        )


def is_platform_root_alias(path: pathlib.Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_safe_index_parent(path: pathlib.Path) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise RuntimeError(
                f"Refusing to write public index through symlinked parent: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise RuntimeError(f"Public index parent is not a directory: {parent}")


def require_new_index_output(path: pathlib.Path) -> None:
    if path.is_symlink() or path.exists():
        raise FileExistsError(f"public index output already exists: {path}")
    require_safe_index_parent(path)


def require_real_input_file(path: pathlib.Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise RuntimeError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise RuntimeError(f"{label} parent is not a directory: {parent}")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a real file: {path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument(
        "--reviewed-public-receipt",
        action="append",
        required=True,
        type=pathlib.Path,
        help=(
            "repeat once for each passed reviewed-public publication receipt, "
            "in canonical report-method order"
        ),
    )
    args = parser.parse_args(argv)

    require_new_index_output(args.output)

    expected_reviewed_public_objects, reviewed_public_receipts = validate_reviewed_public_receipts(
        args.reviewed_public_receipt
    )

    objects: list[dict[str, Any]] = []
    for prefix in PUBLIC_PREFIXES:
        objects.extend(list_prefix(prefix))
    objects.sort(key=lambda item: item["key"])

    keys = [item["key"] for item in objects]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Public prefix overlap produced duplicate keys")
    validate_reviewed_public_s3_state(objects, expected_reviewed_public_objects)

    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bucket": BUCKET,
        "classification": "reviewed_public_validation_and_alias_only_analysis_outputs",
        "prefixes": list(PUBLIC_PREFIXES),
        "object_count": len(objects),
        "total_size": sum(item["size"] for item in objects),
        "reviewed_public_receipts": reviewed_public_receipts,
        "objects": objects,
    }
    write_index(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "object_count": payload["object_count"],
                "total_size": payload["total_size"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
