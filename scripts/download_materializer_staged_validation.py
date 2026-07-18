#!/usr/bin/env python3
"""Download staged_input_validation.json from an exact materializer receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

OUTPUT_NAME = "staged_input_validation.json"
CHECKSUM_FIELDS = (
    "ChecksumSHA256",
    "ChecksumCRC64NVME",
    "ChecksumSHA1",
    "ChecksumCRC32C",
    "ChecksumCRC32",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} is not a JSON object")
    return payload


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    require_safe_new_output_parent(path, "JSON output")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def reserve_json(path: Path, value: dict[str, Any]) -> None:
    require_safe_new_output_parent(path, "JSON output")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    fsync_directory(path.parent)


def install_file_create_only(source: Path, destination: Path) -> None:
    try:
        file_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise FileExistsError(
            "refusing to replace local materializer output"
        ) from error

    try:
        with source.open("rb") as source_handle, os.fdopen(
            file_descriptor, "wb"
        ) as destination_handle:
            file_descriptor = -1
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                destination_handle.write(chunk)
    except Exception:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        destination.unlink(missing_ok=True)
        raise
    source.unlink()


def parse_s3(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if parsed.scheme != "s3" or not parsed.netloc or not key:
        raise ValueError(f"invalid S3 URI: {uri}")
    if not parsed.netloc.startswith("diana-omics-private-results-"):
        raise ValueError("materializer output is outside private-results")
    return parsed.netloc, key


def resolve_real_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    if path.parent.is_symlink():
        raise ValueError(f"{label} parent may not be a symlink: {path.parent}")
    if not path.is_file():
        raise ValueError(f"{label} must be a real file")
    return path.resolve()


def resolve_new_output(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    require_safe_new_output_parent(path, label)
    return path.resolve()


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_safe_new_output_parent(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def aws_json(arguments: list[str], region: str) -> dict[str, Any]:
    command = ["aws", *arguments, "--region", region, "--output", "json"]
    value = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
    payload = json.loads(value) if value.strip() else {}
    if not isinstance(payload, dict):
        raise RuntimeError("AWS command did not return a JSON object")
    return payload


def head_object(
    bucket: str, key: str, version_id: str, region: str
) -> dict[str, Any]:
    return aws_json(
        [
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--version-id",
            version_id,
            "--checksum-mode",
            "ENABLED",
        ],
        region,
    )


def get_object(
    bucket: str, key: str, version_id: str, destination: Path, region: str
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return aws_json(
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


def checksums(value: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value[key])
        for key in CHECKSUM_FIELDS
        if str(value.get(key, "")).strip()
    }


def validate_receipt(receipt: dict[str, Any], expected_kms: str) -> dict[str, Any]:
    outputs = receipt.get("outputs")
    checks = receipt.get("checks")
    if (
        receipt.get("schema_version") != 2
        or receipt.get("status") != "passed"
        or not isinstance(outputs, dict)
        or not outputs
        or not isinstance(checks, dict)
        or not checks
        or any(value is not True for value in checks.values())
    ):
        raise ValueError("materializer receipt is incomplete or not passed")
    row = outputs.get(OUTPUT_NAME)
    if not isinstance(row, dict):
        raise ValueError(f"materializer receipt does not contain {OUTPUT_NAME}")
    uri = str(row.get("uri", ""))
    version_id = str(row.get("version_id", ""))
    digest = str(row.get("sha256", ""))
    row_checks = row.get("checks")
    if (
        not uri
        or not version_id
        or version_id.lower() in {"none", "null"}
        or not isinstance(row_checks, dict)
        or any(value is not True for value in row_checks.values())
        or row.get("kms_key_arn") != expected_kms
        or not isinstance(row.get("bytes"), int)
        or int(row.get("bytes", 0)) <= 0
        or not isinstance(row.get("checksums"), dict)
        or not any(str(row["checksums"].get(key, "")).strip() for key in CHECKSUM_FIELDS)
        or not all(character in "0123456789abcdef" for character in digest)
        or len(digest) != 64
    ):
        raise ValueError(f"{OUTPUT_NAME} lacks exact materializer custody")
    bucket, key = parse_s3(uri)
    if not key.endswith("/" + OUTPUT_NAME):
        raise ValueError(f"{OUTPUT_NAME} URI has an unexpected key: {uri}")
    return {**row, "bucket": bucket, "key": key}


def validate_download(
    row: dict[str, Any],
    head: dict[str, Any],
    get: dict[str, Any],
    local_path: Path,
    expected_kms: str,
) -> dict[str, bool]:
    local_sha = sha256_path(local_path)
    expected_checksums = {
        key: str(value)
        for key, value in row.get("checksums", {}).items()
        if key in CHECKSUM_FIELDS and str(value)
    }
    get_checksums = checksums(get)
    head_checksums = checksums(head)
    return {
        "version_exact": (
            get.get("VersionId")
            == head.get("VersionId")
            == row["version_id"]
        ),
        "bytes_exact": (
            get.get("ContentLength")
            == head.get("ContentLength")
            == row["bytes"]
            == local_path.stat().st_size
        ),
        "sha256_exact": local_sha == row["sha256"],
        "get_checksum_present": bool(get_checksums),
        "head_checksum_present": bool(head_checksums),
        "receipt_checksum_observed": bool(
            set(expected_checksums.items())
            & set(get_checksums.items())
            & set(head_checksums.items())
        ),
        "exact_kms": (
            get.get("ServerSideEncryption")
            == head.get("ServerSideEncryption")
            == "aws:kms"
            and get.get("SSEKMSKeyId")
            == head.get("SSEKMSKeyId")
            == expected_kms
        ),
    }


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    receipt_path = resolve_real_file(args.materializer_receipt, "materializer receipt")
    output_path = resolve_new_output(args.output, "materializer output")
    verify_path = resolve_new_output(
        args.verification_output, "verification output"
    )
    if len({receipt_path, output_path, verify_path}) != 3:
        raise ValueError("receipt, output, and verification paths must be distinct")
    if args.output.exists() or args.verification_output.exists():
        raise FileExistsError("refusing to replace local materializer outputs")
    staging = output_path.with_name(f".{output_path.name}.staging")
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(f"staging output already exists: {staging}")

    receipt = load_json(receipt_path, "materializer receipt")
    row = validate_receipt(receipt, args.expected_kms_key_arn)
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "generated_at_utc": now(),
        "materializer_receipt_sha256": sha256_path(receipt_path),
        "output": str(output_path),
        "expected_kms_key_arn": args.expected_kms_key_arn,
        "object": {
            "uri": row["uri"],
            "bucket": row["bucket"],
            "key": row["key"],
            "version_id": row["version_id"],
            "expected_sha256": row["sha256"],
            "expected_bytes": row["bytes"],
        },
    }
    reserve_json(verify_path, result)

    try:
        head = head_object(row["bucket"], row["key"], row["version_id"], args.region)
        get = get_object(row["bucket"], row["key"], row["version_id"], staging, args.region)
        local_sha = sha256_path(staging)
        downloaded = json.loads(staging.read_text(encoding="utf-8"))
        if not isinstance(downloaded, dict) or downloaded.get("schema_version") != 1:
            raise ValueError(f"{OUTPUT_NAME} is not a schema-1 JSON object")
        checks = validate_download(
            row, head, get, staging, args.expected_kms_key_arn
        )
        result.update(
            {
                "status": "passed" if all(checks.values()) else "failed",
                "completed_at_utc": now(),
                "checks": checks,
                "object": {
                    **result["object"],
                    "sha256": local_sha,
                    "bytes": staging.stat().st_size,
                    "head_checksums": checksums(head),
                    "get_checksums": checksums(get),
                },
            }
        )
        if result["status"] != "passed":
            raise ValueError(f"download validation failed: {checks}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        install_file_create_only(staging, output_path)
        fsync_directory(output_path.parent)
        write_json_atomic(verify_path, result)
        return result
    except Exception as error:
        staging.unlink(missing_ok=True)
        result["status"] = "failed"
        result["completed_at_utc"] = now()
        result["error"] = f"{type(error).__name__}: {error}"
        write_json_atomic(verify_path, result)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materializer-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verification-output", required=True, type=Path)
    parser.add_argument("--expected-kms-key-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    try:
        result = materialize(args)
    except (
        FileExistsError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": result["output"],
                "sha256": result["object"]["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
