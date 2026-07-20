#!/usr/bin/env python3
"""Materialize one cross-check report tree from exact S3 object versions only.

The cross-check Batch routes publish their report trees into the versioned
private results bucket and write a one-shot publication receipt. This helper
replays that receipt locally without trusting current S3 keys: every object is
downloaded by the exact VersionId captured in the passed publication receipt,
the live version history must still match that receipt exactly, and the local
verification receipt is recoverable across a crash between staging and rename.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
)
from check_contract import exact_check_map

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
VERSION_ID = re.compile(r"^\S+$")

EXPECTED_PUBLICATION_RECEIPT_CHECKS = {
    "exact_contract_version_bound": True,
    "route_prefix_initially_empty": True,
    "all_outputs_create_only": True,
    "all_output_versions_exact": True,
    "no_extra_versions_or_delete_markers": True,
}
EXPECTED_PUBLICATION_ANCHOR_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_create_only_version": True,
}
EXPECTED_PUBLICATION_OBJECT_CHECKS = {
    "create_only_put": True,
    "version_exact": True,
    "bytes_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
}
EXPECTED_HISTORY_AUDIT_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "metadata_sha256_exact": True,
    "checksum_sha256_exact": True,
    "exact_kms": True,
}
PUBLICATION_RECEIPT_KEYS = frozenset(
    (
        "schema_version",
        "status",
        "route",
        "submission_id",
        "contract",
        "route_output_uri",
        "route_output_initial_version_history_count",
        "route_output_bucket_versioning",
        "publication_strategy",
        "objects",
        "history_audit",
        "checks",
    )
)
PUBLICATION_CONTRACT_KEYS = frozenset(("uri", "version_id", "sha256"))
PUBLICATION_OBJECT_KEYS = frozenset(
    (
        "relative_path",
        "uri",
        "key",
        "sha256",
        "etag",
        "version_id",
        "content_length",
        "server_side_encryption",
        "ssekms_key_id",
        "checksum_sha256",
        "checks",
    )
)
PUBLICATION_HISTORY_AUDIT_KEYS = frozenset(
    ("key", "version_id", "sha256", "checks")
)
PUBLICATION_ANCHOR_KEYS = frozenset(
    (
        "schema_version",
        "status",
        "receipt_sha256",
        "receipt_bytes",
        "receipt_uri",
        "receipt_version_id",
        "route_output_uri",
        "checks",
    )
)
EXPECTED_LIVE_HISTORY_CHECKS = {
    "version_count_exact": True,
    "all_entries_are_versions": True,
    "key_inventory_exact": True,
    "all_version_ids_exact": True,
    "all_versions_latest": True,
}
EXPECTED_DOWNLOAD_OBJECT_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "checksum_sha256_exact": True,
    "checksum_type_full_object": True,
    "exact_kms": True,
}


def sha256(path: Path) -> str:
    require_real_hash_input(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exact_schema_version(payload: dict[str, Any], expected: int) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and type(expected) is int and value == expected


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_HEX.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def non_null_version_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.lower() not in {"none", "null"}
        and VERSION_ID.fullmatch(value) is not None
    )


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reserve_json(path: Path, value: dict[str, Any]) -> None:
    require_safe_new_output_parent(path, "verification output")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
            require_installed_verification(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    require_safe_new_output_parent(path, "verification output")
    data = canonical_json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
        require_installed_verification(path, expected_sha256)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def require_installed_verification(path: Path, expected_sha256: str) -> None:
    require_real_downloaded_file(path, "verification output")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"verification output mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"verification output changed during write: {path}")


def safe_relative(value: Any) -> str:
    text = str(value)
    path = PurePosixPath(text)
    if (
        not text
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in text
        or path.as_posix() != text
    ):
        raise ValueError(f"unsafe report relative path: {text}")
    return text


def resolve_new_output(path: Path, label: str) -> Path:
    """Fail before resolving a create-only output through path-level symlinks."""
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    require_safe_new_output_parent(path, label)
    return path.resolve()


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_safe_new_output_parent(path: Path, label: str) -> None:
    require_no_symlinked_ancestors(path, label)


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def require_real_hash_input(path: Path) -> None:
    label = f"{path.name} SHA-256 input"
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def require_real_downloaded_file(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def validate_local_tree(root: Path, rows: list[dict[str, Any]]) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("downloaded report tree is missing or is a symlink")

    expected: dict[str, dict[str, Any]] = {}
    for row in rows:
        relative = safe_relative(row.get("relative_path"))
        if relative in expected:
            raise ValueError(f"duplicate downloaded report path: {relative}")
        expected[relative] = row

    local_paths = list(root.rglob("*"))
    if any(
        path.is_symlink() or (not path.is_file() and not path.is_dir())
        for path in local_paths
    ):
        raise ValueError("downloaded report contains a symlink or special file")

    observed = {
        path.relative_to(root).as_posix() for path in local_paths if path.is_file()
    }
    if observed != set(expected):
        raise ValueError("downloaded report inventory differs from its receipt")

    for relative, row in expected.items():
        path = root / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or not exact_int(row.get("bytes"), path.stat().st_size)
            or sha256(path) != row.get("sha256")
        ):
            raise ValueError(f"downloaded report differs from its receipt: {relative}")


def remove_local_tree(path: Path) -> None:
    if path.exists() and path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)


def publish_local_tree(staging: Path, output: Path, rows: list[dict[str, Any]]) -> None:
    validate_local_tree(staging, rows)
    os.replace(staging, output)
    try:
        fsync_directory(output.parent)
        validate_local_tree(output, rows)
    except Exception:
        remove_local_tree(output)
        raise


def recover_local_cutover(
    result: dict[str, Any], staging: Path, output: Path, verification: Path
) -> bool:
    status = result.get("status")
    if status == "passed":
        if staging.exists():
            raise ValueError("passed report replay retains an ambiguous staging tree")
        validate_local_tree(output, result.get("objects", []))
        return True
    if status != "prepared":
        return False

    roots = [path for path in (staging, output) if path.exists()]
    if len(roots) != 1:
        raise ValueError("prepared report replay has an ambiguous local cutover")

    rows = result.get("objects", [])
    if roots[0] == staging:
        publish_local_tree(staging, output, rows)
    else:
        validate_local_tree(output, rows)
    result["status"] = "passed"
    result["object_count"] = len(result.get("objects", []))
    result["recovered_prepared_cutover"] = True
    write_json_atomic(verification, result)
    return True


def load_object(path: Path, label: str) -> dict[str, Any]:
    value, _digest = load_object_with_sha256(path, label)
    return value


def load_object_with_sha256(path: Path, label: str) -> tuple[dict[str, Any], str]:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink: {path}")
    payload = path.read_bytes()
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, sha256_bytes(payload)


def s3_parts(uri: str) -> tuple[str, str]:
    value = urlparse(uri)
    if value.scheme != "s3" or not value.netloc or not value.path.lstrip("/"):
        raise ValueError(f"invalid S3 URI: {uri}")
    return value.netloc, value.path.lstrip("/")


def aws_json(arguments: list[str], region: str) -> dict[str, Any]:
    value = json.loads(
        subprocess.check_output(
            ["aws", *arguments, "--region", region, "--output", "json"],
            text=True,
        )
    )
    if not isinstance(value, dict):
        raise ValueError("AWS command did not return a JSON object")
    return value


def version_history(bucket: str, prefix: str, region: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    key_marker = ""
    version_marker = ""
    seen_markers: set[tuple[str, str]] = set()
    while True:
        arguments = [
            "s3api",
            "list-object-versions",
            "--bucket",
            bucket,
            "--prefix",
            prefix,
        ]
        if key_marker:
            arguments.extend(["--key-marker", key_marker])
        if version_marker:
            arguments.extend(["--version-id-marker", version_marker])

        page = aws_json(arguments, region)
        for field, kind in (("Versions", "version"), ("DeleteMarkers", "delete_marker")):
            values = page.get(field, [])
            if not isinstance(values, list) or any(
                not isinstance(row, dict) for row in values
            ):
                raise ValueError("S3 version history is malformed")
            rows.extend({**row, "history_kind": kind} for row in values)

        if page.get("IsTruncated") is not True:
            return rows

        key_marker, version_marker = require_next_version_history_markers(page)
        marker = (key_marker, version_marker)
        if marker in seen_markers:
            raise ValueError("S3 history pagination did not advance")
        seen_markers.add(marker)


def require_next_version_history_markers(page: dict[str, Any]) -> tuple[str, str]:
    key_marker = page.get("NextKeyMarker")
    version_marker = page.get("NextVersionIdMarker")
    if (
        not isinstance(key_marker, str)
        or not isinstance(version_marker, str)
        or not key_marker
        or not version_marker
    ):
        raise ValueError("truncated S3 history omitted its next key/version markers")
    return key_marker, version_marker


def require_exact_checks(checks: Any, expected: dict[str, bool], error: str) -> None:
    if not exact_check_map(checks, expected):
        raise ValueError(f"{error}: {checks}")


def validate_live_history(
    history: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, bool]:
    expected_by_key = {str(row["key"]): row for row in rows}
    history_by_key = {str(row.get("Key", "")): row for row in history}
    checks = {
        "version_count_exact": len(history) == len(rows),
        "all_entries_are_versions": all(
            row.get("history_kind") == "version" for row in history
        ),
        "key_inventory_exact": set(history_by_key) == set(expected_by_key),
        "all_version_ids_exact": all(
            history_by_key.get(key, {}).get("VersionId") == row.get("version_id")
            for key, row in expected_by_key.items()
        ),
        "all_versions_latest": all(
            history_by_key.get(key, {}).get("IsLatest") is True
            for key in expected_by_key
        ),
    }
    require_exact_checks(
        checks,
        EXPECTED_LIVE_HISTORY_CHECKS,
        "live report version history differs from receipt",
    )
    return checks


def get_exact(
    bucket: str, key: str, version_id: str, destination: Path, region: str
) -> dict[str, Any]:
    require_safe_new_output_parent(destination, "report object")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = aws_json(
            [
                "s3api",
                "get-object",
                "--bucket",
                bucket,
                "--key",
                key,
                "--version-id",
                version_id,
                "--checksum-mode",
                "ENABLED",
                str(destination),
            ],
            region,
        )
        require_real_downloaded_file(destination, "downloaded report object")
        return response
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def validate_publication(
    receipt_path: Path, anchor_path: Path, kms_key_arn: str
) -> tuple[dict[str, Any], list[dict[str, Any]], str, str, str, dict[str, Any]]:
    receipt, receipt_hash = load_object_with_sha256(
        receipt_path, "publication receipt"
    )
    anchor = load_object(anchor_path, "publication anchor")
    anchor_checks = anchor.get("checks")
    receipt_checks = receipt.get("checks")
    rows = receipt.get("objects")
    history_audit = receipt.get("history_audit")
    route_uri = str(receipt.get("route_output_uri", ""))
    bucket, sentinel = s3_parts(route_uri.rstrip("/") + "/sentinel")
    prefix = sentinel.removesuffix("sentinel")

    if set(receipt) != PUBLICATION_RECEIPT_KEYS:
        raise ValueError("publication receipt envelope is not exact")
    contract = receipt.get("contract")
    if (
        not isinstance(contract, dict)
        or set(contract) != PUBLICATION_CONTRACT_KEYS
        or not str(contract.get("uri", "")).startswith("s3://")
        or not non_null_version_id(contract.get("version_id"))
    ):
        raise ValueError("publication receipt contract is not exact")
    require_sha256(contract.get("sha256"), "publication contract SHA-256")
    if (
        not exact_schema_version(receipt, 1)
        or receipt.get("status") != "passed"
        or not exact_int(
            receipt.get("route_output_initial_version_history_count"),
            0,
        )
        or receipt.get("route_output_bucket_versioning") != "Enabled"
        or receipt.get("publication_strategy")
        != "one_shot_create_only_exact_version_history"
        or not isinstance(rows, list)
        or not rows
        or not isinstance(history_audit, list)
        or len(history_audit) != len(rows)
        or not exact_check_map(
            receipt_checks,
            EXPECTED_PUBLICATION_RECEIPT_CHECKS,
        )
    ):
        raise ValueError("publication receipt is incomplete or not passed")

    if set(anchor) != PUBLICATION_ANCHOR_KEYS:
        raise ValueError("publication anchor envelope is not exact")
    if (
        not exact_schema_version(anchor, 1)
        or anchor.get("status") != "passed"
        or anchor.get("receipt_sha256") != receipt_hash
        or not exact_int(anchor.get("receipt_bytes"), receipt_path.stat().st_size)
        or anchor.get("route_output_uri") != route_uri
        or not str(anchor.get("receipt_uri", "")).startswith(
            "s3://diana-omics-private-results-"
        )
        or not non_null_version_id(anchor.get("receipt_version_id"))
        or not exact_check_map(
            anchor_checks,
            EXPECTED_PUBLICATION_ANCHOR_CHECKS,
        )
    ):
        raise ValueError("publication anchor does not bind the exact receipt")

    if not bucket.startswith("diana-omics-private-results-"):
        raise ValueError("report tree is outside the private-results bucket")

    seen: set[str] = set()
    row_bindings: set[tuple[str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("publication receipt has a malformed object row")
        if set(row) != PUBLICATION_OBJECT_KEYS:
            raise ValueError("publication receipt object row is not exact")
        relative = safe_relative(row.get("relative_path"))
        if relative in seen:
            raise ValueError(f"duplicate report relative path: {relative}")
        seen.add(relative)
        row_sha256 = require_sha256(row.get("sha256"), "publication object SHA-256")
        version_id = row.get("version_id")

        expected_uri = f"s3://{bucket}/{prefix}{relative}"
        if row.get("uri") != expected_uri or row.get("key") != prefix + relative:
            raise ValueError(
                f"report row is outside the declared route prefix: {relative}"
            )
        if (
            not non_null_version_id(version_id)
            or type(row.get("content_length")) is not int
            or row.get("content_length") <= 0
            or row.get("server_side_encryption") != "aws:kms"
            or row.get("ssekms_key_id") != kms_key_arn
            or not exact_check_map(
                row.get("checks"),
                EXPECTED_PUBLICATION_OBJECT_CHECKS,
            )
        ):
            raise ValueError(f"report row lacks exact custody: {relative}")
        row_bindings.add((row["key"], version_id, row_sha256))

    audit_bindings: set[tuple[str, str, str]] = set()
    for row in history_audit:
        if not isinstance(row, dict) or set(row) != PUBLICATION_HISTORY_AUDIT_KEYS:
            raise ValueError("publication receipt history audit is not exact")
        history_sha256 = require_sha256(
            row.get("sha256"),
            "publication history SHA-256",
        )
        key = row.get("key")
        version_id = row.get("version_id")
        if (
            not isinstance(key, str)
            or not non_null_version_id(version_id)
            or not exact_check_map(
                row.get("checks"),
                EXPECTED_HISTORY_AUDIT_CHECKS,
            )
        ):
            raise ValueError("publication receipt history audit is not exact")
        binding = (key, version_id, history_sha256)
        if binding in audit_bindings:
            raise ValueError("publication receipt history audit is not exact")
        audit_bindings.add(binding)
    if audit_bindings != row_bindings:
        raise ValueError("publication receipt history audit is not exact")

    return receipt, rows, bucket, prefix, receipt_hash, anchor


def download_exact_report_tree(args: argparse.Namespace) -> dict[str, Any]:
    output = resolve_new_output(args.output_dir, "report output")
    verification = resolve_new_output(
        args.verification_output, "verification output"
    )
    if verification == output or verification.is_relative_to(output):
        raise ValueError("output paths overlap")

    receipt, rows, bucket, prefix, receipt_hash, anchor = validate_publication(
        args.publication_receipt,
        args.publication_anchor,
        args.kms_key_arn,
    )

    history_checks = validate_live_history(
        version_history(bucket, prefix, args.region),
        rows,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.staging")
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "publication_receipt_sha256": receipt_hash,
        "publication_receipt_uri": anchor["receipt_uri"],
        "route_output_uri": receipt["route_output_uri"],
        "expected_kms_key_arn": args.kms_key_arn,
        "live_history_checks": history_checks,
        "output_dir": str(output),
        "objects": [],
    }

    if verification.exists():
        prior, prior_verification_sha256 = load_object_with_sha256(
            verification, "verification receipt"
        )
        identity_matches = (
            exact_schema_version(prior, 1)
            and prior.get("publication_receipt_sha256")
            == result["publication_receipt_sha256"]
            and prior.get("publication_receipt_uri")
            == result["publication_receipt_uri"]
            and prior.get("route_output_uri") == result["route_output_uri"]
            and prior.get("expected_kms_key_arn") == args.kms_key_arn
            and prior.get("output_dir") == str(output)
        )
        if not identity_matches:
            raise ValueError("existing verification receipt belongs to another replay")

        was_prepared = prior.get("status") == "prepared"
        if recover_local_cutover(prior, staging, output, verification):
            return {
                "status": "passed",
                "objects": len(prior.get("objects", [])),
                "output": str(output),
                "recovered": was_prepared,
            }

        if output.exists():
            raise ValueError(
                "incomplete verification exists beside an uncommitted output"
            )
        if staging.exists():
            if staging.is_symlink() or not staging.is_dir():
                raise ValueError("report replay staging path is unsafe")
            shutil.rmtree(staging)
        result["recovered_from_status"] = prior.get("status")
        result["prior_verification_sha256"] = prior_verification_sha256
        if prior.get("error"):
            result["prior_error"] = prior.get("error")
        write_json_atomic(verification, result)
    else:
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("report output directory is not empty")
        try:
            reserve_json(verification, result)
        except FileExistsError as error:
            raise ValueError("verification receipt was concurrently reserved") from error

    if output.exists():
        output.rmdir()
    try:
        staging.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ValueError("report replay staging path already exists") from error

    try:
        for row in rows:
            relative = safe_relative(row["relative_path"])
            local = staging / relative
            response = get_exact(
                bucket,
                row["key"],
                row["version_id"],
                local,
                args.region,
            )
            checks = {
                "version_exact": response.get("VersionId") == row["version_id"],
                "bytes_exact": (
                    local.is_file()
                    and exact_int(
                        response.get("ContentLength"),
                        row["content_length"],
                    )
                    and exact_int(row["content_length"], local.stat().st_size)
                ),
                "sha256_exact": sha256(local) == row["sha256"],
                "checksum_sha256_exact": bool(row.get("checksum_sha256"))
                and response.get("ChecksumSHA256") == row.get("checksum_sha256"),
                "checksum_type_full_object": (
                    response.get("ChecksumType") == "FULL_OBJECT"
                ),
                "exact_kms": (
                    response.get("ServerSideEncryption") == "aws:kms"
                    and response.get("SSEKMSKeyId") == args.kms_key_arn
                ),
            }
            require_exact_checks(
                checks,
                EXPECTED_DOWNLOAD_OBJECT_CHECKS,
                f"exact report download failed for {relative}",
            )

            result["objects"].append(
                {
                    "relative_path": relative,
                    "version_id": row["version_id"],
                    "bytes": local.stat().st_size,
                    "sha256": sha256(local),
                    "checks": checks,
                }
            )
            write_json_atomic(verification, result)

        result["status"] = "prepared"
        result["object_count"] = len(result["objects"])
        write_json_atomic(verification, result)

        publish_local_tree(staging, output, result["objects"])
        result["status"] = "passed"
        write_json_atomic(verification, result)
    except Exception as error:
        if staging.exists():
            shutil.rmtree(staging)
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        write_json_atomic(verification, result)
        raise

    return {
        "status": "passed",
        "objects": len(rows),
        "output": str(output),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-receipt", required=True, type=Path)
    parser.add_argument("--publication-anchor", required=True, type=Path)
    parser.add_argument("--kms-key-arn", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--verification-output", required=True, type=Path)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    try:
        result = download_exact_report_tree(args)
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
