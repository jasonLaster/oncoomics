#!/usr/bin/env python3
"""Publish one finalized input contract as a create-only content-addressed object."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from check_contract import validate

S3_PREFIX = re.compile(
    r"^s3://(diana-omics-private-results-[^/]+)/"
    r"(runs/(subject[0-9]{2,})/([^/]+)/deterministic/contracts)/?$"
)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


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
            "s3api", "list-object-versions", "--bucket", bucket, "--prefix", prefix
        ]
        if key_marker:
            arguments.extend(["--key-marker", key_marker])
        if version_marker:
            arguments.extend(["--version-id-marker", version_marker])
        page = aws_json(arguments, region)
        for field, kind in (("Versions", "version"), ("DeleteMarkers", "delete_marker")):
            values = page.get(field, [])
            if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
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
            raise ValueError("S3 version history pagination did not advance")
        seen_markers.add(marker)


def head(bucket: str, key: str, version_id: str, region: str) -> dict[str, Any]:
    return aws_json(
        [
            "s3api", "head-object", "--bucket", bucket, "--key", key,
            "--version-id", version_id, "--checksum-mode", "ENABLED",
        ],
        region,
    )


def get_exact(
    bucket: str, key: str, version_id: str, destination: Path, region: str
) -> dict[str, Any]:
    return aws_json(
        [
            "s3api", "get-object", "--bucket", bucket, "--key", key,
            "--version-id", version_id, "--checksum-mode", "ENABLED",
            str(destination),
        ],
        region,
    )


def put_create_only(
    path: Path, bucket: str, key: str, kms_key_arn: str, region: str
) -> dict[str, Any]:
    return aws_json(
        [
            "s3api", "put-object", "--bucket", bucket, "--key", key,
            "--body", str(path), "--if-none-match", "*",
            "--server-side-encryption", "aws:kms", "--sse-kms-key-id", kms_key_arn,
            "--checksum-algorithm", "SHA256",
            "--checksum-sha256", checksum_sha256(sha256(path)),
            "--content-type", "application/json",
            "--metadata", f"sha256={sha256(path)}",
        ],
        region,
    )


def load_contract(path: Path) -> dict[str, Any]:
    require_no_symlinked_ancestors(path, "contract")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"contract must be a real JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("contract is not a JSON object")
    return value


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def reserve_json(path: Path, value: dict[str, Any]) -> None:
    require_anchor_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                json.dump(value, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    require_anchor_output(path)
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


def require_anchor_output(path: Path) -> None:
    if path.is_symlink():
        raise FileExistsError(f"contract publication anchor may not be a symlink: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(
                f"contract publication anchor parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def publication_identity_matches(
    observed: dict[str, Any], expected: dict[str, Any]
) -> bool:
    fields = (
        "schema_version",
        "receipt_sha256",
        "receipt_bytes",
        "receipt_uri",
        "bucket_versioning",
        "initial_version_history_count",
        "publication_strategy",
        "kms_key_arn",
    )
    return all(observed.get(field) == expected.get(field) for field in fields)


def verify_publication(
    contract: Path,
    bucket: str,
    prefix: str,
    key: str,
    version_id: str,
    kms_key_arn: str,
    region: str,
) -> dict[str, bool]:
    metadata = head(bucket, key, version_id, region)
    contract_sha = sha256(contract)
    with tempfile.TemporaryDirectory(prefix="diana-contract-verify-") as temporary:
        downloaded = Path(temporary) / "contract.json"
        fetched = get_exact(bucket, key, version_id, downloaded, region)
        expected_checksum = base64.b64encode(
            bytes.fromhex(contract_sha)
        ).decode("ascii")
        history = version_history(bucket, prefix, region)
        return {
            "version_exact": metadata.get("VersionId")
            == fetched.get("VersionId")
            == version_id,
            "bytes_exact": metadata.get("ContentLength")
            == fetched.get("ContentLength")
            == contract.stat().st_size
            == downloaded.stat().st_size,
            "sha256_exact": sha256(downloaded) == contract_sha,
            "sha256_checksum_exact": metadata.get("ChecksumType")
            == fetched.get("ChecksumType")
            == "FULL_OBJECT"
            and metadata.get("ChecksumSHA256")
            == fetched.get("ChecksumSHA256")
            == expected_checksum,
            "metadata_sha256_exact": metadata.get("Metadata", {}).get("sha256")
            == contract_sha,
            "exact_kms": metadata.get("ServerSideEncryption")
            == fetched.get("ServerSideEncryption")
            == "aws:kms"
            and metadata.get("SSEKMSKeyId")
            == fetched.get("SSEKMSKeyId")
            == kms_key_arn,
            "single_create_only_version": len(history) == 1
            and history[0].get("history_kind") == "version"
            and history[0].get("Key") == key
            and history[0].get("VersionId") == version_id
            and history[0].get("IsLatest") is True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--destination-prefix", required=True)
    parser.add_argument("--kms-key-arn", required=True)
    parser.add_argument("--anchor-output", required=True, type=Path)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    try:
        contract = load_contract(args.contract)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    checked = validate(contract)
    if checked.get("overall_status") != "ready":
        raise SystemExit("Fail-closed: finalized contract is not ready")
    custody = contract.get("custody")
    if (
        not isinstance(custody, dict)
        or custody.get("status") != "passed"
        or not isinstance(custody.get("checks"), dict)
        or not custody["checks"]
        or any(value is not True for value in custody["checks"].values())
    ):
        raise SystemExit("Fail-closed: finalized contract lacks passed custody evidence")
    if contract.get("kms_key_arn") != args.kms_key_arn:
        raise SystemExit("Fail-closed: publication KMS key differs from contract")

    match = S3_PREFIX.fullmatch(args.destination_prefix)
    if not match:
        raise SystemExit("Fail-closed: invalid private contract publication prefix")
    bucket, prefix, alias, run_id = match.groups()
    prefix = prefix.rstrip("/") + "/"
    if contract.get("run_alias") != alias or f"/runs/{alias}/{run_id}/" not in str(contract.get("output_uri", "")):
        raise SystemExit("Fail-closed: publication prefix differs from contract run")
    try:
        require_anchor_output(args.anchor_output)
    except (FileExistsError, NotADirectoryError, ValueError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    versioning = aws_json(
        ["s3api", "get-bucket-versioning", "--bucket", bucket], args.region
    )
    if versioning.get("Status") != "Enabled":
        raise SystemExit("Fail-closed: contract bucket versioning is not Enabled")
    contract_sha = sha256(args.contract)
    key = f"{prefix}{contract_sha}.json"
    uri = f"s3://{bucket}/{key}"
    anchor: dict[str, Any] = {
        "schema_version": 1,
        "status": "dry_run" if not args.apply else "in_progress",
        "receipt_sha256": contract_sha,
        "receipt_bytes": args.contract.stat().st_size,
        "receipt_uri": uri,
        "receipt_version_id": "",
        "bucket_versioning": "Enabled",
        "initial_version_history_count": 0,
        "publication_strategy": "sha256_content_addressed_create_only",
        "kms_key_arn": args.kms_key_arn,
        "checks": {},
    }
    recovering = False
    if args.anchor_output.exists():
        existing = json.loads(args.anchor_output.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or not publication_identity_matches(
            existing, anchor
        ):
            raise SystemExit(
                "Fail-closed: existing contract anchor belongs to another publication"
            )
        if not args.apply or existing.get("status") == "dry_run":
            raise SystemExit(
                "Fail-closed: contract publication anchor already exists; use a new path"
            )
        anchor = existing
        recovering = True
    else:
        try:
            reserve_json(args.anchor_output, anchor)
        except FileExistsError as error:
            raise SystemExit(
                "Fail-closed: contract publication anchor was concurrently reserved"
            ) from error
        except (NotADirectoryError, ValueError) as error:
            raise SystemExit(f"Fail-closed: {error}") from error
    if not args.apply:
        print(json.dumps({"status": "dry_run", "contract_uri": uri}, sort_keys=True))
        return 0

    try:
        observed_history = version_history(bucket, prefix, args.region)
        if observed_history:
            if not recovering:
                raise ValueError("contract publication prefix has prior history")
            if (
                len(observed_history) != 1
                or observed_history[0].get("history_kind") != "version"
                or observed_history[0].get("Key") != key
                or observed_history[0].get("IsLatest") is not True
                or not str(observed_history[0].get("VersionId", ""))
            ):
                raise ValueError(
                    "recovery history is not the single expected contract version"
                )
            version_id = str(observed_history[0]["VersionId"])
            anchored_version = str(anchor.get("receipt_version_id", ""))
            if anchored_version and anchored_version != version_id:
                raise ValueError("recovery history differs from reserved contract VersionId")
            anchor["receipt_version_id"] = version_id
            anchor["recovered_existing_version"] = True
            write_json_atomic(args.anchor_output, anchor)
        else:
            response = put_create_only(
                args.contract, bucket, key, args.kms_key_arn, args.region
            )
            version_id = str(response.get("VersionId", ""))
            if not version_id or version_id.lower() in {"none", "null"}:
                raise ValueError("create-only put response omitted VersionId")
            anchor["receipt_version_id"] = version_id
            write_json_atomic(args.anchor_output, anchor)
        anchor["checks"] = verify_publication(
            args.contract,
            bucket,
            prefix,
            key,
            version_id,
            args.kms_key_arn,
            args.region,
        )
        if not all(anchor["checks"].values()):
            raise ValueError(f"contract publication verification failed: {anchor['checks']}")
        anchor["status"] = "passed"
        anchor.pop("error", None)
        anchor.pop("observed_version_history", None)
    except Exception as error:
        anchor["status"] = "failed"
        anchor["error"] = f"{type(error).__name__}: {error}"
        try:
            anchor["observed_version_history"] = version_history(
                bucket, prefix, args.region
            )
        except Exception as history_error:
            anchor["observed_version_history_error"] = (
                f"{type(history_error).__name__}: {history_error}"
            )
        write_json_atomic(args.anchor_output, anchor)
        raise
    write_json_atomic(args.anchor_output, anchor)
    print(json.dumps({"status": "passed", "contract_uri": uri, "contract_version_id": anchor["receipt_version_id"], "anchor": str(args.anchor_output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
