#!/usr/bin/env python3
"""Download staged_input_validation.json from an exact materializer receipt."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
)
from capture_materializer_terminal import (
    EXPECTED_MATERIALIZER_RECEIPT_KEYS,
    EXPECTED_OUTPUT_CUSTODY_KEYS,
)
from check_contract import exact_check_map

OUTPUT_NAME = "staged_input_validation.json"
CHECKSUM_FIELDS = (
    "ChecksumSHA256",
    "ChecksumCRC64NVME",
    "ChecksumSHA1",
    "ChecksumCRC32C",
    "ChecksumCRC32",
)
EXPECTED_RECEIPT_CHECKS = {
    "all_sources_exact_version_and_sha256": True,
    "alias_only_pass_snv_vcf": True,
    "sbs96_matches_independent_pass_vcf_derivation": True,
    "destination_prefix_initially_empty": True,
    "all_outputs_create_only": True,
    "destination_exact_single_version_history": True,
}
EXPECTED_OUTPUT_CHECKS = {
    "create_only_put": True,
    "version_exact": True,
    "bytes_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_version_history": True,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    _payload, digest = read_stable_file_with_sha256(
        path,
        f"{path.name} SHA-256 input",
    )
    return digest


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def load_json_with_sha256(path: Path, label: str) -> tuple[dict[str, Any], str]:
    path = resolve_real_file(path, label)
    payload, digest = read_stable_file_with_sha256(path, label)
    try:
        value = json.loads(
            payload,
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value, digest


def read_stable_file(path: Path, label: str) -> bytes:
    payload, _digest = read_stable_file_with_sha256(path, label)
    return payload


def read_stable_file_with_sha256(path: Path, label: str) -> tuple[bytes, str]:
    payload, identity = read_real_hash_input_once(path, label)
    digest = sha256_bytes(payload)
    stable_payload, stable_identity = read_real_hash_input_once(path, label)
    if stable_identity != identity or sha256_bytes(stable_payload) != digest:
        raise ValueError(f"{label} changed during read: {path}")
    return payload, digest


def read_real_hash_input_once(
    path: Path,
    label: str,
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{label} must be a real file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            payload = handle.read()
            after_read = os.fstat(handle.fileno())
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ValueError(f"{label} changed during read: {path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if (
        stat_identity(opened) != stat_identity(after_read)
        or stat_identity(after_read) != stat_identity(current)
    ):
        raise ValueError(f"{label} changed during read: {path}")
    return payload, stat_identity(opened)


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def load_json(path: Path, label: str) -> dict[str, Any]:
    value, _digest = load_json_with_sha256(path, label)
    return value


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def exact_schema_version(payload: dict[str, Any], expected: int) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and type(expected) is int and value == expected


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    require_safe_new_output_parent(path, "JSON output")
    path.parent.mkdir(parents=True, exist_ok=True)
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
        require_installed_file(path, "JSON output", expected_sha256)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def reserve_json(path: Path, value: dict[str, Any]) -> None:
    require_safe_new_output_parent(path, "JSON output")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
            require_installed_file(path, "JSON output", expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def install_file_create_only(source: Path, destination: Path) -> None:
    source = resolve_real_file(source, "staged materializer output")
    destination = resolve_new_output(destination, "materializer output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_sha256 = sha256_path(source)

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
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        fsync_directory(destination.parent)
        require_installed_file(
            source,
            "staged materializer output",
            source_sha256,
            require_mode_0600=False,
        )
        require_installed_file(destination, "materializer output", source_sha256)
        source.unlink()
        fsync_directory(source.parent)
    except Exception:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        destination.unlink(missing_ok=True)
        raise


def require_installed_file(
    path: Path,
    label: str,
    expected_sha256: str,
    *,
    require_mode_0600: bool = True,
) -> None:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} changed during write")
    if require_mode_0600 and (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"{label} mode is not 0600")
    if sha256_path(path) != expected_sha256:
        raise ValueError(f"{label} changed during write")


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
    require_no_symlinked_ancestors(path, label)
    if not path.is_file():
        raise ValueError(f"{label} must be a real file")
    return path.resolve()


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")


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
    if destination.is_symlink():
        raise ValueError(f"{OUTPUT_NAME} download may not be a symlink")
    require_safe_new_output_parent(destination, OUTPUT_NAME)
    destination.parent.mkdir(parents=True, exist_ok=True)
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
    resolve_real_file(destination, f"downloaded {OUTPUT_NAME}")
    return response


def checksums(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key in CHECKSUM_FIELDS:
        if key not in value:
            continue
        raw = value[key]
        if not isinstance(raw, str) or not raw.strip():
            return {}
        result[key] = raw
    return result


def validate_receipt(receipt: dict[str, Any], expected_kms: str) -> dict[str, Any]:
    outputs = receipt.get("outputs")
    checks = receipt.get("checks")
    if set(receipt) != EXPECTED_MATERIALIZER_RECEIPT_KEYS:
        raise ValueError("materializer receipt envelope is not exact")
    if (
        not exact_schema_version(receipt, 2)
        or receipt.get("status") != "passed"
        or not isinstance(outputs, dict)
        or not outputs
        or not exact_check_map(checks, EXPECTED_RECEIPT_CHECKS)
    ):
        raise ValueError("materializer receipt is incomplete or not passed")
    row = outputs.get(OUTPUT_NAME)
    if not isinstance(row, dict):
        raise ValueError(f"materializer receipt does not contain {OUTPUT_NAME}")
    if set(row) != EXPECTED_OUTPUT_CUSTODY_KEYS:
        raise ValueError(f"{OUTPUT_NAME} lacks exact materializer custody")
    uri = row.get("uri")
    version_id = row.get("version_id")
    digest = row.get("sha256")
    size = row.get("bytes")
    row_checks = row.get("checks")
    row_checksums = checksums(row.get("checksums"))
    if (
        not isinstance(uri, str)
        or not uri
        or not isinstance(version_id, str)
        or not version_id
        or version_id.lower() in {"none", "null"}
        or not exact_check_map(row_checks, EXPECTED_OUTPUT_CHECKS)
        or row.get("kms_key_arn") != expected_kms
        or type(size) is not int
        or size <= 0
        or not row_checksums
        or not isinstance(digest, str)
        or not all(character in "0123456789abcdef" for character in digest)
        or len(digest) != 64
    ):
        raise ValueError(f"{OUTPUT_NAME} lacks exact materializer custody")
    bucket, key = parse_s3(uri)
    if not key.endswith("/" + OUTPUT_NAME):
        raise ValueError(f"{OUTPUT_NAME} URI has an unexpected key: {uri}")
    expected_checksum = checksum_sha256(digest)
    if (
        row["checksums"].get("ChecksumType") != "FULL_OBJECT"
        or row["checksums"].get("ChecksumSHA256") != expected_checksum
    ):
        raise ValueError(f"{OUTPUT_NAME} lacks exact materializer custody")
    return {**row, "bucket": bucket, "key": key}


def validate_download(
    row: dict[str, Any],
    head: dict[str, Any],
    get: dict[str, Any],
    local_path: Path,
    expected_kms: str,
) -> dict[str, bool]:
    resolve_real_file(local_path, f"downloaded {OUTPUT_NAME}")
    local_sha = sha256_path(local_path)
    expected_checksum = checksum_sha256(row["sha256"])
    get_checksums = checksums(get)
    head_checksums = checksums(head)
    return {
        "version_exact": (
            get.get("VersionId")
            == head.get("VersionId")
            == row["version_id"]
        ),
        "bytes_exact": (
            exact_int(get.get("ContentLength"), row["bytes"])
            and exact_int(head.get("ContentLength"), row["bytes"])
            and exact_int(local_path.stat().st_size, row["bytes"])
        ),
        "sha256_exact": local_sha == row["sha256"],
        "get_checksum_present": bool(get_checksums),
        "head_checksum_present": bool(head_checksums),
        "full_object_sha256_exact": (
            row["checksums"].get("ChecksumType")
            == get.get("ChecksumType")
            == head.get("ChecksumType")
            == "FULL_OBJECT"
            and row["checksums"].get("ChecksumSHA256")
            == get.get("ChecksumSHA256")
            == head.get("ChecksumSHA256")
            == expected_checksum
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

    receipt, receipt_sha256 = load_json_with_sha256(
        receipt_path,
        "materializer receipt",
    )
    row = validate_receipt(receipt, args.expected_kms_key_arn)
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "generated_at_utc": now(),
        "materializer_receipt_sha256": receipt_sha256,
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
        resolve_real_file(staging, f"downloaded {OUTPUT_NAME}")
        local_sha = sha256_path(staging)
        downloaded = load_json(staging, OUTPUT_NAME)
        if not isinstance(downloaded, dict) or not exact_schema_version(downloaded, 1):
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
