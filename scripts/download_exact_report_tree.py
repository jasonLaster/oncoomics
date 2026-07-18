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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse


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
    require_safe_new_output_parent(path, "verification output")
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
    require_safe_new_output_parent(path, "verification output")
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
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


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
            or path.stat().st_size != int(row.get("bytes", -1))
            or sha256(path) != row.get("sha256")
        ):
            raise ValueError(f"downloaded report differs from its receipt: {relative}")


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

    validate_local_tree(roots[0], result.get("objects", []))
    if roots[0] == staging:
        os.replace(staging, output)
        fsync_directory(output.parent)
    result["status"] = "passed"
    result["object_count"] = len(result.get("objects", []))
    result["recovered_prepared_cutover"] = True
    write_json_atomic(verification, result)
    return True


def load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


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

        key_marker = str(page.get("NextKeyMarker", ""))
        version_marker = str(page.get("NextVersionIdMarker", ""))
        if not key_marker or not version_marker:
            raise ValueError("truncated S3 history omitted its next key/version markers")
        marker = (key_marker, version_marker)
        if marker in seen_markers:
            raise ValueError("S3 history pagination did not advance")
        seen_markers.add(marker)


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
) -> tuple[dict[str, Any], list[dict[str, Any]], str, str]:
    receipt = load_object(receipt_path, "publication receipt")
    anchor = load_object(anchor_path, "publication anchor")
    receipt_hash = sha256(receipt_path)
    anchor_checks = anchor.get("checks")
    receipt_checks = receipt.get("checks")
    rows = receipt.get("objects")
    route_uri = str(receipt.get("route_output_uri", ""))
    bucket, sentinel = s3_parts(route_uri.rstrip("/") + "/sentinel")
    prefix = sentinel.removesuffix("sentinel")

    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "passed"
        or receipt.get("route_output_initial_version_history_count") != 0
        or receipt.get("route_output_bucket_versioning") != "Enabled"
        or receipt.get("publication_strategy")
        != "one_shot_create_only_exact_version_history"
        or not isinstance(rows, list)
        or not rows
        or not isinstance(receipt_checks, dict)
        or not receipt_checks
        or any(value is not True for value in receipt_checks.values())
    ):
        raise ValueError("publication receipt is incomplete or not passed")

    if (
        anchor.get("schema_version") != 1
        or anchor.get("status") != "passed"
        or anchor.get("receipt_sha256") != receipt_hash
        or int(anchor.get("receipt_bytes", -1)) != receipt_path.stat().st_size
        or anchor.get("route_output_uri") != route_uri
        or not str(anchor.get("receipt_uri", "")).startswith(
            "s3://diana-omics-private-results-"
        )
        or not str(anchor.get("receipt_version_id", ""))
        or not isinstance(anchor_checks, dict)
        or not anchor_checks
        or any(value is not True for value in anchor_checks.values())
    ):
        raise ValueError("publication anchor does not bind the exact receipt")

    if not bucket.startswith("diana-omics-private-results-"):
        raise ValueError("report tree is outside the private-results bucket")

    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("publication receipt has a malformed object row")
        relative = safe_relative(row.get("relative_path"))
        if relative in seen:
            raise ValueError(f"duplicate report relative path: {relative}")
        seen.add(relative)

        expected_uri = f"s3://{bucket}/{prefix}{relative}"
        if row.get("uri") != expected_uri or row.get("key") != prefix + relative:
            raise ValueError(
                f"report row is outside the declared route prefix: {relative}"
            )
        if (
            not str(row.get("version_id", ""))
            or str(row.get("version_id", "")).lower() in {"none", "null"}
            or not str(row.get("sha256", ""))
            or int(row.get("content_length", -1)) <= 0
            or row.get("ssekms_key_id") != kms_key_arn
        ):
            raise ValueError(f"report row lacks exact custody: {relative}")

    return receipt, rows, bucket, prefix


def download_exact_report_tree(args: argparse.Namespace) -> dict[str, Any]:
    output = resolve_new_output(args.output_dir, "report output")
    verification = resolve_new_output(
        args.verification_output, "verification output"
    )
    if verification == output or verification.is_relative_to(output):
        raise ValueError("output paths overlap")

    receipt, rows, bucket, prefix = validate_publication(
        args.publication_receipt,
        args.publication_anchor,
        args.kms_key_arn,
    )

    history = version_history(bucket, prefix, args.region)
    expected_by_key = {str(row["key"]): row for row in rows}
    history_by_key = {str(row.get("Key", "")): row for row in history}
    if (
        len(history) != len(rows)
        or any(row.get("history_kind") != "version" for row in history)
        or set(history_by_key) != set(expected_by_key)
        or any(
            history_by_key[key].get("VersionId") != row.get("version_id")
            or history_by_key[key].get("IsLatest") is not True
            for key, row in expected_by_key.items()
        )
    ):
        raise ValueError("live report version history differs from receipt")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.staging")
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "in_progress",
        "publication_receipt_sha256": sha256(args.publication_receipt),
        "publication_receipt_uri": load_object(
            args.publication_anchor, "publication anchor"
        )["receipt_uri"],
        "route_output_uri": receipt["route_output_uri"],
        "expected_kms_key_arn": args.kms_key_arn,
        "output_dir": str(output),
        "objects": [],
    }

    if verification.exists():
        prior = load_object(verification, "verification receipt")
        identity_matches = (
            prior.get("schema_version") == 1
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
        result["prior_verification_sha256"] = sha256(verification)
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
                    response.get("ContentLength")
                    == row["content_length"]
                    == local.stat().st_size
                    and local.is_file()
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
            if not all(checks.values()):
                raise ValueError(
                    f"exact report download failed for {relative}: {checks}"
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

        os.replace(staging, output)
        fsync_directory(output.parent)
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
