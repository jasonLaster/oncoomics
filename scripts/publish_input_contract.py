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

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
)
from check_contract import validate

S3_PREFIX = re.compile(
    r"^s3://(diana-omics-private-results-[^/]+)/"
    r"(runs/(subject[0-9]{2,})/([^/]+)/deterministic/contracts)/?$"
)

EXPECTED_CONTRACT_ANCHOR_CHECKS: dict[str, bool] = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_create_only_version": True,
}
EXPECTED_CONTRACT_PREFLIGHT_CHECKS: dict[str, bool] = {
    "contract_ready": True,
    "finalized_custody_exact": True,
    "publication_prefix_matches_contract": True,
    "bucket_versioning_enabled": True,
    "destination_history_empty": True,
}
EXPECTED_DRY_RUN_ANCHOR_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "receipt_sha256",
        "receipt_bytes",
        "receipt_uri",
        "receipt_version_id",
        "bucket_versioning",
        "initial_version_history_count",
        "publication_strategy",
        "kms_key_arn",
        "checks",
    }
)
EXPECTED_FINALIZED_CUSTODY_CHECKS: dict[str, bool] = {
    "successful_execution_freeze_bound": True,
    "full_freeze_exactly_materialized": True,
    "crosscheck_sources_match_exact_freeze": True,
    "alias_only_outputs_have_single_create_only_versions": True,
    "sbs96_independently_rederived_from_final_pass_vcf": True,
}


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_hash_input(path: Path) -> None:
    label = f"{path.name} SHA-256 input"
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def sha256(path: Path) -> str:
    require_real_hash_input(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and type(expected) is int and value == expected


def require_version_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.lower() in {"none", "null"}
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} omitted an exact VersionId")
    return value


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
        key_marker, version_marker = require_next_version_history_markers(page)
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
    require_safe_download_destination(destination, "downloaded input contract")
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
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in contract: {error}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid JSON in contract") from error
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
            require_installed_anchor(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    require_anchor_output(path)
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
        require_installed_anchor(path, expected_sha256)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def require_installed_anchor(path: Path, expected_sha256: str) -> None:
    require_real_downloaded_file(path, "contract publication anchor")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"contract publication anchor mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"contract publication anchor changed during write: {path}")


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


def require_safe_download_destination(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, label)


def require_real_downloaded_file(path: Path, label: str) -> None:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def load_real_json(path: Path, label: str) -> dict[str, Any]:
    require_real_downloaded_file(path, label)
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def require_exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise ValueError(
            f"{label} has stale or missing metadata: "
            f"missing={missing} unexpected={unexpected}"
        )


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
        require_real_downloaded_file(downloaded, "downloaded input contract")
        expected_checksum = base64.b64encode(
            bytes.fromhex(contract_sha)
        ).decode("ascii")
        history = version_history(bucket, prefix, region)
        contract_bytes = contract.stat().st_size
        return {
            "version_exact": metadata.get("VersionId")
            == fetched.get("VersionId")
            == version_id,
            "bytes_exact": exact_int(metadata.get("ContentLength"), contract_bytes)
            and exact_int(fetched.get("ContentLength"), contract_bytes)
            and exact_int(downloaded.stat().st_size, contract_bytes),
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
            and history[0].get("IsLatest") is True
            and exact_int(history[0].get("Size"), contract_bytes),
        }


def require_contract_anchor_checks(checks: dict[str, bool]) -> None:
    if checks != EXPECTED_CONTRACT_ANCHOR_CHECKS:
        raise ValueError(f"contract publication verification failed: {checks}")


def validate_dry_run_anchor(path: Path, expected: dict[str, Any]) -> None:
    observed = load_real_json(path, "contract publication dry-run receipt")
    require_exact_keys(
        observed,
        EXPECTED_DRY_RUN_ANCHOR_KEYS,
        "contract publication dry-run receipt",
    )
    if (
        observed.get("status") != "dry_run"
        or observed.get("receipt_version_id") != ""
        or not publication_identity_matches(observed, expected)
    ):
        raise ValueError(
            "contract publication dry-run receipt differs from requested publication"
        )
    if observed.get("checks") != EXPECTED_CONTRACT_PREFLIGHT_CHECKS:
        raise ValueError(
            "contract publication dry-run receipt preflight checks failed: "
            f"{observed.get('checks')}"
        )


def require_finalized_custody(custody: Any) -> None:
    if (
        not isinstance(custody, dict)
        or custody.get("status") != "passed"
        or custody.get("checks") != EXPECTED_FINALIZED_CUSTODY_CHECKS
    ):
        raise SystemExit("Fail-closed: finalized contract lacks passed custody evidence")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--destination-prefix", required=True)
    parser.add_argument("--kms-key-arn", required=True)
    parser.add_argument("--anchor-output", required=True, type=Path)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run-receipt", type=Path)
    args = parser.parse_args()

    if args.dry_run_receipt and not args.apply:
        raise SystemExit("Fail-closed: --dry-run-receipt is only valid with --apply")
    if args.apply and not args.dry_run_receipt:
        raise SystemExit(
            "Fail-closed: --apply requires the matching --dry-run-receipt"
        )

    try:
        contract = load_contract(args.contract)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    checked = validate(contract)
    if checked.get("overall_status") != "ready":
        raise SystemExit("Fail-closed: finalized contract is not ready")
    require_finalized_custody(contract.get("custody"))
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
    dry_run_anchor = dict(anchor)
    dry_run_anchor["status"] = "dry_run"
    dry_run_anchor["checks"] = dict(EXPECTED_CONTRACT_PREFLIGHT_CHECKS)
    if args.dry_run_receipt:
        try:
            validate_dry_run_anchor(args.dry_run_receipt, dry_run_anchor)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise SystemExit(f"Fail-closed: {error}") from error
    recovering = False
    if not args.apply:
        observed_history = version_history(bucket, prefix, args.region)
        if observed_history:
            raise SystemExit(
                "Fail-closed: contract publication prefix has prior history"
            )
        anchor["checks"] = dict(EXPECTED_CONTRACT_PREFLIGHT_CHECKS)
    if args.anchor_output.exists():
        try:
            existing = load_real_json(
                args.anchor_output,
                "existing contract publication anchor",
            )
        except (OSError, ValueError) as error:
            raise SystemExit(f"Fail-closed: {error}") from error
        if not publication_identity_matches(existing, anchor):
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
            ):
                raise ValueError(
                    "recovery history is not the single expected contract version"
                )
            version_id = require_version_id(
                observed_history[0].get("VersionId"),
                "recovery history",
            )
            anchored_raw = anchor.get("receipt_version_id", "")
            anchored_version = (
                require_version_id(anchored_raw, "reserved contract anchor")
                if anchored_raw
                else ""
            )
            if anchored_version != "" and anchored_version != version_id:
                raise ValueError("recovery history differs from reserved contract VersionId")
            anchor["receipt_version_id"] = version_id
            anchor["recovered_existing_version"] = True
            write_json_atomic(args.anchor_output, anchor)
        else:
            response = put_create_only(
                args.contract, bucket, key, args.kms_key_arn, args.region
            )
            version_id = require_version_id(
                response.get("VersionId"),
                "create-only put response",
            )
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
        require_contract_anchor_checks(anchor["checks"])
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
