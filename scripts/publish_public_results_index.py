#!/usr/bin/env python3
"""Publish the reviewed public object index after report publication."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from build_public_results_index import (
    BUCKET,
    FORBIDDEN_PREFIXES,
    PUBLIC_PREFIXES,
    validate_reviewed_public_current_versions,
    validate_reviewed_public_receipts,
    validate_reviewed_public_s3_state,
)

REGION = "us-east-1"
INDEX_KEY = "public-index/objects.json"
CLASSIFICATION = "reviewed-public-index"
CHECKSUM_TYPE = "FULL_OBJECT"
SERVER_SIDE_ENCRYPTION = "AES256"
CACHE_CONTROL = "max-age=300"
CONTENT_TYPE = "application/json"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
VERSION_ID = re.compile(r"^\S+$")
PUBLIC_INDEX_DESTINATION_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "checksum_type": True,
    "checksum_sha256": True,
    "sse_s3": True,
    "metadata": True,
    "cache_control": True,
    "content_type": True,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def non_null_version_id(value: str) -> bool:
    return value != "null" and VERSION_ID.fullmatch(value) is not None


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("public index must be a JSON object")
    return value


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_input_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file")
    return path.resolve()


def require_safe_receipt_output_parent(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("receipt output may not be a symlink")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"receipt output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"receipt output parent is not a directory: {parent}")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_private_atomic(path: Path, value: dict[str, Any], *, create: bool) -> None:
    require_safe_receipt_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(value)
    expected_sha256 = sha256_bytes(data)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.fchmod(descriptor, 0o600)
    temporary = Path(raw)
    linked = False
    try:
        if not create and (
            not path.is_file()
            or path.is_symlink()
            or (path.stat().st_mode & 0o777) != 0o600
        ):
            raise ValueError("reserved receipt output is missing or not mode 0600")
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
        require_installed_private_output(path, expected_sha256)
    except Exception:
        if create and linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def require_installed_private_output(path: Path, expected_sha256: str) -> None:
    require_safe_receipt_output_parent(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"private output changed during write: {path}")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"private output mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"private output changed during write: {path}")


def public_index_object(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("public index contains a malformed object row")
    key = row.get("key")
    size = row.get("size")
    last_modified = row.get("last_modified")
    if (
        not isinstance(key, str)
        or not key
        or key.endswith("/")
        or any(key.startswith(blocked) for blocked in FORBIDDEN_PREFIXES)
        or not any(key.startswith(prefix) for prefix in PUBLIC_PREFIXES)
        or not isinstance(size, int)
        or size < 0
        or not isinstance(last_modified, str)
        or not last_modified
    ):
        raise ValueError(f"public index object is not allowlisted: {row}")
    return {"key": key, "size": size, "last_modified": last_modified}


def validate_public_index(
    path: Path,
    reviewed_public_receipts: Sequence[Path],
) -> dict[str, Any]:
    path = require_real_input_file(path, "public index")
    reviewed_public_objects, reviewed_public_binding = validate_reviewed_public_receipts(
        reviewed_public_receipts
    )
    digest = sha256(path)
    if not SHA256_HEX.fullmatch(digest):
        raise ValueError("public index SHA-256 is malformed")
    payload = load_json(path)
    objects = payload.get("objects")
    if (
        payload.get("schema_version") != 1
        or payload.get("bucket") != BUCKET
        or payload.get("classification")
        != "reviewed_public_validation_and_alias_only_analysis_outputs"
        or payload.get("prefixes") != list(PUBLIC_PREFIXES)
        or not isinstance(objects, list)
    ):
        raise ValueError("public index contract is malformed")
    normalized = [public_index_object(row) for row in objects]
    keys = [row["key"] for row in normalized]
    if (
        len(keys) != len(set(keys))
        or keys != sorted(keys)
        or payload.get("object_count") != len(normalized)
        or payload.get("total_size") != sum(row["size"] for row in normalized)
    ):
        raise ValueError("public index inventory is not exact")
    if payload.get("reviewed_public_receipts") != reviewed_public_binding:
        raise ValueError("public index reviewed-public receipt binding is not exact")
    validate_reviewed_public_s3_state(normalized, reviewed_public_objects)
    return {
        "sha256": digest,
        "bytes": path.stat().st_size,
        "object_count": len(normalized),
        "total_size": sum(row["size"] for row in normalized),
        "reviewed_public_receipt_count": len(reviewed_public_binding),
    }


def aws_json(arguments: list[str], region: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["aws", *arguments, "--region", region, "--output", "json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    value = json.loads(completed.stdout) if completed.stdout.strip() else {}
    if not isinstance(value, dict):
        raise ValueError("AWS command returned a non-object")
    return value


def head_object(bucket: str, key: str, region: str, version_id: str = "") -> dict[str, Any]:
    arguments = [
        "s3api",
        "head-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--checksum-mode",
        "ENABLED",
    ]
    if version_id:
        arguments.extend(["--version-id", version_id])
    return aws_json(arguments, region)


def require_public_index_destination_checks_exact(checks: dict[str, bool]) -> None:
    if checks != PUBLIC_INDEX_DESTINATION_CHECKS:
        raise ValueError(f"public index destination verification failed: {checks}")


def upload_index(path: Path, custody: dict[str, Any], region: str) -> dict[str, Any]:
    expected_checksum = checksum_sha256(custody["sha256"])
    metadata = {
        "classification": CLASSIFICATION,
        "sha256": custody["sha256"],
    }
    response = aws_json(
        [
            "s3api",
            "put-object",
            "--bucket",
            BUCKET,
            "--key",
            INDEX_KEY,
            "--body",
            str(path),
            "--content-type",
            CONTENT_TYPE,
            "--cache-control",
            CACHE_CONTROL,
            "--server-side-encryption",
            SERVER_SIDE_ENCRYPTION,
            "--checksum-algorithm",
            "SHA256",
            "--checksum-sha256",
            expected_checksum,
            "--metadata",
            json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        ],
        region,
    )
    version_id = str(response.get("VersionId", ""))
    if not non_null_version_id(version_id):
        raise ValueError("public index put omitted a non-null VersionId")
    exact = head_object(BUCKET, INDEX_KEY, region, version_id)
    current = head_object(BUCKET, INDEX_KEY, region)
    checks = {
        "version_exact": exact.get("VersionId") == current.get("VersionId") == version_id,
        "bytes_exact": int(exact.get("ContentLength", -1))
        == int(current.get("ContentLength", -2))
        == custody["bytes"],
        "checksum_type": exact.get("ChecksumType")
        == current.get("ChecksumType")
        == CHECKSUM_TYPE,
        "checksum_sha256": exact.get("ChecksumSHA256")
        == current.get("ChecksumSHA256")
        == expected_checksum,
        "sse_s3": exact.get("ServerSideEncryption")
        == current.get("ServerSideEncryption")
        == SERVER_SIDE_ENCRYPTION,
        "metadata": exact.get("Metadata") == current.get("Metadata") == metadata,
        "cache_control": exact.get("CacheControl")
        == current.get("CacheControl")
        == CACHE_CONTROL,
        "content_type": exact.get("ContentType") == current.get("ContentType") == CONTENT_TYPE,
    }
    require_public_index_destination_checks_exact(checks)
    return {
        "bucket": BUCKET,
        "key": INDEX_KEY,
        "uri": f"s3://{BUCKET}/{INDEX_KEY}",
        "version_id": version_id,
        "bytes": custody["bytes"],
        "sha256": custody["sha256"],
        "checksum_sha256": expected_checksum,
        "server_side_encryption": SERVER_SIDE_ENCRYPTION,
        "status": "passed",
        "checks": checks,
    }


def validate_dry_run_receipt(path: Path, custody: dict[str, Any]) -> dict[str, Any]:
    path = require_real_input_file(path, "public index dry-run receipt")
    receipt = load_json(path)
    index = receipt.get("index")
    destination = receipt.get("destination")
    checks = receipt.get("checks")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "dry_run"
        or receipt.get("apply") is not False
        or not isinstance(index, dict)
        or not isinstance(destination, dict)
        or not isinstance(checks, dict)
    ):
        raise ValueError("public index dry-run receipt contract is malformed")
    expected_index = {
        "sha256": custody["sha256"],
        "bytes": custody["bytes"],
        "object_count": custody["object_count"],
        "total_size": custody["total_size"],
        "reviewed_public_receipt_count": custody["reviewed_public_receipt_count"],
    }
    if {field: index.get(field) for field in expected_index} != expected_index:
        raise ValueError("public index dry-run receipt does not match the index")
    expected_destination = {
        "bucket": BUCKET,
        "key": INDEX_KEY,
        "uri": f"s3://{BUCKET}/{INDEX_KEY}",
    }
    if {field: destination.get(field) for field in expected_destination} != expected_destination:
        raise ValueError("public index dry-run receipt does not match the destination")
    required_checks = {
        "index_allowlisted_prefixes": True,
        "index_schema": True,
        "index_sorted_unique_keys": True,
        "index_reviewed_public_receipts": True,
    }
    if checks != required_checks:
        raise ValueError("public index dry-run receipt did not pass preflight checks")
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "index_sha256": custody["sha256"],
        "status": "dry_run",
    }


def validate_reviewed_public_apply_state(
    reviewed_public_receipts: Sequence[Path],
    region: str,
) -> None:
    reviewed_public_objects, _ = validate_reviewed_public_receipts(
        reviewed_public_receipts
    )
    validate_reviewed_public_current_versions(
        reviewed_public_objects,
        head_current=lambda key: head_object(BUCKET, key, region),
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    custody = validate_public_index(args.index, args.reviewed_public_receipt)
    dry_run_receipt = None
    if args.apply:
        if args.dry_run_receipt is None:
            raise ValueError("public index apply requires --dry-run-receipt")
        dry_run_receipt = validate_dry_run_receipt(args.dry_run_receipt, custody)
        validate_reviewed_public_apply_state(
            args.reviewed_public_receipt,
            args.region,
        )
    elif args.dry_run_receipt is not None:
        raise ValueError("--dry-run-receipt is only valid with --apply")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "preflighting",
        "generated_at_utc": now(),
        "apply": bool(args.apply),
        "index": {
            "path": str(args.index.resolve()),
            **custody,
        },
        "destination": {
            "bucket": BUCKET,
            "key": INDEX_KEY,
            "uri": f"s3://{BUCKET}/{INDEX_KEY}",
        },
        "checks": {
            "index_schema": True,
            "index_allowlisted_prefixes": True,
            "index_sorted_unique_keys": True,
            "index_reviewed_public_receipts": True,
        },
    }
    if dry_run_receipt is not None:
        receipt["dry_run_receipt"] = dry_run_receipt
        receipt["checks"]["dry_run_receipt"] = True
        receipt["checks"]["reviewed_public_current_versions"] = True
    write_private_atomic(args.receipt_output, receipt, create=True)
    try:
        if args.apply:
            versioning = aws_json(
                ["s3api", "get-bucket-versioning", "--bucket", BUCKET],
                args.region,
            )
            if versioning.get("Status") != "Enabled":
                raise ValueError(f"bucket versioning is not enabled: {BUCKET}")
            receipt["checks"]["destination_bucket_versioning"] = True
            receipt["status"] = "in_progress"
            write_private_atomic(args.receipt_output, receipt, create=False)
            receipt["destination_object"] = upload_index(args.index, custody, args.region)
            receipt["checks"].update(
                {
                    "destination_sse_s3": True,
                    "destination_full_object_sha256": True,
                    "destination_current_version_exact": True,
                }
            )
            receipt["status"] = "passed"
        else:
            receipt["status"] = "dry_run"
        receipt["completed_at_utc"] = now()
        write_private_atomic(args.receipt_output, receipt, create=False)
        return receipt
    except Exception as error:
        receipt["status"] = "failed"
        receipt["failed_at_utc"] = now()
        receipt["error"] = f"{type(error).__name__}: {error}"
        write_private_atomic(args.receipt_output, receipt, create=False)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish public-index/objects.json after reviewed report publication."
    )
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument(
        "--reviewed-public-receipt",
        action="append",
        required=True,
        type=Path,
        help=(
            "repeat once for each passed reviewed-public publication receipt, "
            "in canonical report-method order"
        ),
    )
    parser.add_argument("--dry-run-receipt", type=Path)
    parser.add_argument("--region", default=REGION, choices=(REGION,))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (
        FileExistsError,
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    print(
        json.dumps(
            {
                "status": result["status"],
                "object_count": result["index"]["object_count"],
                "total_size": result["index"]["total_size"],
                "receipt_output": str(args.receipt_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
