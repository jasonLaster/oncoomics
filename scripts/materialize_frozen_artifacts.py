#!/usr/bin/env python3
"""Download a passed private freeze by exact S3 VersionId.

The resulting local SHA-256 receipt binds every report input to the immutable
destination object recorded by the final artifact freeze. Current-key S3 syncs
are intentionally not accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

CHECKSUM_FIELDS = (
    "ChecksumCRC64NVME",
    "ChecksumSHA256",
    "ChecksumSHA1",
    "ChecksumCRC32C",
    "ChecksumCRC32",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reserve_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
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


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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


def safe_relative(value: Any) -> str:
    text = str(value)
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or path.as_posix() != text:
        raise ValueError(f"unsafe frozen relative key: {text}")
    return text


def resolve_new_output(path: Path, label: str) -> Path:
    """Fail before resolving a create-only output through path-level symlinks."""
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    if path.parent.is_symlink():
        raise ValueError(f"{label} parent may not be a symlink: {path.parent}")
    return path.resolve()


def validate_local_tree(root: Path, rows: list[dict[str, Any]]) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("materialized tree is missing or is a symlink")
    expected: dict[str, dict[str, Any]] = {}
    for row in rows:
        relative = safe_relative(row.get("relative_key"))
        if relative in expected:
            raise ValueError(f"duplicate materialized relative key: {relative}")
        expected[relative] = row
    local_paths = list(root.rglob("*"))
    if any(
        path.is_symlink() or (not path.is_file() and not path.is_dir())
        for path in local_paths
    ):
        raise ValueError("materialized tree contains a symlink or special file")
    observed = {
        path.relative_to(root).as_posix() for path in local_paths if path.is_file()
    }
    if observed != set(expected):
        raise ValueError("materialized tree inventory differs from its receipt")
    for relative, row in expected.items():
        path = root / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != int(row.get("bytes", -1))
            or sha256(path) != row.get("sha256")
        ):
            raise ValueError(f"materialized tree differs from its receipt: {relative}")


def recover_local_cutover(
    result: dict[str, Any], staging: Path, output: Path, receipt_output: Path
) -> bool:
    status = result.get("status")
    if status == "passed":
        if staging.exists():
            raise ValueError("passed materialization retains an ambiguous staging tree")
        validate_local_tree(output, result.get("objects", []))
        return True
    if status != "prepared":
        return False
    roots = [path for path in (staging, output) if path.exists()]
    if len(roots) != 1:
        raise ValueError("prepared materialization has an ambiguous local cutover")
    validate_local_tree(roots[0], result.get("objects", []))
    if roots[0] == staging:
        os.replace(staging, output)
        fsync_directory(output.parent)
    result["status"] = "passed"
    result["passed_count"] = len(result.get("objects", []))
    result["recovered_prepared_cutover"] = True
    write_json_atomic(receipt_output, result)
    return True


def load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def exact_checksums(value: dict[str, Any]) -> dict[str, str]:
    return {
        field: str(value[field])
        for field in CHECKSUM_FIELDS
        if str(value.get(field, "")).strip()
    }


def get_exact_object(
    bucket: str,
    key: str,
    version_id: str,
    destination: Path,
    region: str,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "aws",
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
        "--region",
        region,
        "--output",
        "json",
        str(destination),
    ]
    try:
        value = json.loads(subprocess.check_output(command, text=True))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if not isinstance(value, dict):
        destination.unlink(missing_ok=True)
        raise ValueError("S3 get-object response is not a JSON object")
    return value


def validate_materialized(
    expected: dict[str, Any],
    response: dict[str, Any],
    path: Path,
    expected_kms_key_arn: str,
) -> dict[str, Any]:
    version_id = str(expected.get("version_id", ""))
    expected_bytes = int(expected.get("bytes", -1))
    expected_checksums = expected.get("checksums")
    if not version_id or version_id in {"null", "None"}:
        raise ValueError("frozen destination lacks an exact VersionId")
    if expected_bytes <= 0:
        raise ValueError("frozen destination lacks a positive byte count")
    if not isinstance(expected_checksums, dict) or not exact_checksums(expected_checksums):
        raise ValueError("frozen destination lacks an exact S3 checksum")
    if expected.get("checksum_type") != "FULL_OBJECT":
        raise ValueError("frozen destination checksum is not full-object")
    checks = {
        "version_id": str(response.get("VersionId", "")) == version_id,
        "content_length": int(response.get("ContentLength", -1)) == expected_bytes,
        "local_bytes": path.is_file() and path.stat().st_size == expected_bytes,
        "checksums": exact_checksums(response) == exact_checksums(expected_checksums),
        "checksum_type": response.get("ChecksumType") == "FULL_OBJECT",
        "sse": response.get("ServerSideEncryption") == "aws:kms",
        "kms": response.get("SSEKMSKeyId") == expected_kms_key_arn,
    }
    if not all(checks.values()):
        raise ValueError(f"exact-version materialization checks failed: {checks}")
    return {
        "bytes": expected_bytes,
        "version_id": version_id,
        "checksums": exact_checksums(response),
        "checksum_type": "FULL_OBJECT",
        "server_side_encryption": "aws:kms",
        "kms_key_id": expected_kms_key_arn,
        "sha256": sha256(path),
        "checks": checks,
    }


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    output = resolve_new_output(args.output_dir, "materialization output")
    receipt_output = resolve_new_output(args.receipt_output, "materialization receipt")
    if receipt_output == output or receipt_output.is_relative_to(output):
        raise ValueError("materialization receipt must be outside the artifact tree")

    freeze = load_object(args.freeze_receipt, "freeze receipt")
    rows = freeze.get("objects")
    if (
        freeze.get("schema_version") != 1
        or freeze.get("status") != "passed"
        or freeze.get("kms_key_arn") != args.expected_kms_key_arn
        or not isinstance(rows, list)
        or not rows
        or len(rows) != int(freeze.get("object_count", -1))
    ):
        raise ValueError("private freeze receipt is incomplete or not passed")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.staging")
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "run_id": freeze.get("run_id"),
        "batch_job_id": freeze.get("batch_job_id"),
        "script_sha256": sha256(Path(__file__)),
        "freeze_receipt_sha256": sha256(args.freeze_receipt),
        "expected_kms_key_arn": args.expected_kms_key_arn,
        "materialization_dir": str(output),
        "object_count": len(rows),
        "objects": [],
    }

    if receipt_output.exists():
        prior = load_object(receipt_output, "materialization receipt")
        identity_matches = (
            prior.get("schema_version") == 1
            and prior.get("run_id") == result["run_id"]
            and prior.get("batch_job_id") == result["batch_job_id"]
            and prior.get("script_sha256") == result["script_sha256"]
            and prior.get("freeze_receipt_sha256") == result["freeze_receipt_sha256"]
            and prior.get("expected_kms_key_arn") == args.expected_kms_key_arn
            and prior.get("materialization_dir") == str(output)
            and int(prior.get("object_count", -1)) == len(rows)
        )
        if not identity_matches:
            raise ValueError(
                "existing materialization receipt belongs to another operation"
            )
        was_prepared = prior.get("status") == "prepared"
        if recover_local_cutover(prior, staging, output, receipt_output):
            return {
                "status": "passed",
                "objects": len(prior.get("objects", [])),
                "receipt": str(receipt_output),
                "recovered": was_prepared,
            }
        if output.exists():
            raise ValueError(
                "incomplete receipt exists alongside an uncommitted output tree"
            )
        if staging.exists():
            if staging.is_symlink() or not staging.is_dir():
                raise ValueError("recovery staging path is unsafe")
            shutil.rmtree(staging)
        result["recovered_from_status"] = prior.get("status")
        result["prior_receipt_sha256"] = sha256(receipt_output)
        if prior.get("error"):
            result["prior_error"] = prior.get("error")
        write_json_atomic(receipt_output, result)
    else:
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("exact-version materialization output is not empty")
        try:
            reserve_json(receipt_output, result)
        except FileExistsError as error:
            raise ValueError(
                "materialization receipt was concurrently reserved"
            ) from error

    if output.exists():
        output.rmdir()
    try:
        staging.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ValueError("materialization staging path already exists") from error

    try:
        seen: set[str] = set()
        for raw_row in rows:
            if not isinstance(raw_row, dict) or raw_row.get("status") != "passed":
                raise ValueError("freeze receipt contains a non-passed object row")
            relative = safe_relative(raw_row.get("relative_key"))
            if relative in seen:
                raise ValueError(f"duplicate frozen relative key: {relative}")
            seen.add(relative)
            destination = raw_row.get("destination")
            if not isinstance(destination, dict):
                raise ValueError(f"missing frozen destination: {relative}")
            bucket = str(destination.get("bucket", ""))
            key = str(destination.get("key", ""))
            version_id = str(destination.get("version_id", ""))
            if not bucket.startswith("diana-omics-private-results-") or not key:
                raise ValueError(f"unapproved frozen destination: {relative}")
            destination_prefix = str(freeze.get("destination_prefix", "")).rstrip("/") + "/"
            expected_uri_prefix = f"s3://{bucket}/"
            if not destination_prefix.startswith(expected_uri_prefix):
                raise ValueError("freeze destination prefix and object bucket differ")
            expected_key_prefix = destination_prefix.removeprefix(expected_uri_prefix)
            if key != expected_key_prefix + relative:
                raise ValueError(
                    f"frozen destination key differs from relative key: {relative}"
                )

            local_path = staging / relative
            response = get_exact_object(
                bucket, key, version_id, local_path, args.region
            )
            verified = validate_materialized(
                destination, response, local_path, args.expected_kms_key_arn
            )
            result["objects"].append(
                {
                    "relative_key": relative,
                    "bucket": bucket,
                    "key": key,
                    **verified,
                }
            )
            write_json_atomic(receipt_output, result)

        result["status"] = "prepared"
        result["passed_count"] = len(result["objects"])
        write_json_atomic(receipt_output, result)
        if output.exists():
            if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
                raise ValueError("materialization output changed during staging")
            output.rmdir()
        os.replace(staging, output)
        fsync_directory(output.parent)
        result["status"] = "passed"
    except Exception as error:
        if staging.exists():
            shutil.rmtree(staging)
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        write_json_atomic(receipt_output, result)
        raise

    write_json_atomic(receipt_output, result)
    return {
        "status": "passed",
        "objects": len(result["objects"]),
        "receipt": str(args.receipt_output),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-receipt", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--expected-kms-key-arn", required=True)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)

    try:
        result = materialize(args)
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
