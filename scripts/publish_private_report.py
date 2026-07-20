#!/usr/bin/env python3
"""Freeze one allowlisted HRD report packet in the private results bucket."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from forbidden_text import (
    DEFAULT_FORBIDDEN_TOKENS,
    forbidden_token_fingerprints,
    merge_forbidden_tokens,
)
from publish_reviewed_public_report import (
    MAX_FILE_BYTES,
    MAX_PACKET_BYTES,
    METHOD_CONTRACTS,
    PRIVATE_BUCKET,
    PRIVATE_KMS_KEY_ARN,
    PRIVATE_RECEIPT_OBJECT_CHECKS,
    REGION,
    RUN_ID,
    SUBJECT_ALIAS,
    aws_json,
    canonical_packet_digest,
    checksum_sha256,
    content_type,
    exact_final_history,
    exact_int,
    exact_check_map,
    exact_non_null_version_id,
    exact_schema_version,
    head_object,
    load_json_with_sha256,
    now,
    private_report_prefix,
    scan_text,
    sha256,
    validate_report_packet,
    version_history,
    write_private_atomic,
)

CLASSIFICATION = "private-reviewed-hrd-report"
PRIVATE_DRY_RUN_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "generated_at_utc",
    "apply",
    "subject_alias",
    "run_id",
    "method_id",
    "packet_revision",
    "source_packet_dir",
    "destination_prefix",
    "kms_key_arn",
    "expected_files",
    "object_count",
    "passed_count",
    "forbidden_token_count",
    "forbidden_token_sha256",
    "objects",
    "checks",
    "completed_at_utc",
}


def require_private_object_checks_exact(
    checks: Any,
    relative_path: str,
) -> None:
    if not exact_check_map(checks, PRIVATE_RECEIPT_OBJECT_CHECKS):
        raise ValueError(
            f"private destination verification failed for {relative_path}: {checks}"
        )


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_packet_dir(packet_dir: Path) -> Path:
    require_no_symlinked_ancestors(packet_dir, "packet directory")
    if packet_dir.is_symlink() or not packet_dir.is_dir():
        raise ValueError("packet directory must be a real directory")
    return packet_dir.resolve()


def require_real_input_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file")
    return path.resolve()


def forbidden_tokens(args: argparse.Namespace) -> tuple[str, ...]:
    return merge_forbidden_tokens(
        (*DEFAULT_FORBIDDEN_TOKENS, *args.forbidden_token),
        files=args.forbidden_tokens_file,
    )


def validate_packet_dir(packet_dir: Path, method_id: str, tokens: tuple[str, ...]) -> list[dict[str, Any]]:
    packet_dir = require_real_packet_dir(packet_dir)
    expected = tuple(sorted(METHOD_CONTRACTS[method_id]["files"]))
    present = sorted(child.name for child in packet_dir.iterdir())
    if present != list(expected):
        raise ValueError("packet directory inventory is not exact")

    paths: dict[str, Path] = {}
    rows: list[dict[str, Any]] = []
    total_bytes = 0
    for relative in expected:
        path = packet_dir / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"packet file must be a real file: {relative}")
        size = path.stat().st_size
        if size <= 0 or size > MAX_FILE_BYTES:
            raise ValueError(f"packet file size is out of bounds: {relative}")
        scanned_digest = sha256(path)
        scan_text(path, tokens)
        digest = sha256(path)
        if digest != scanned_digest:
            raise ValueError(
                f"packet file changed after forbidden-token scan: {relative}"
            )
        paths[relative] = path
        rows.append(
            {
                "relative_path": relative,
                "path": path,
                "bytes": size,
                "sha256": digest,
                "checksum_sha256": checksum_sha256(digest),
            }
        )
        total_bytes += size

    if total_bytes > MAX_PACKET_BYTES:
        raise ValueError("packet directory is too large")
    validate_report_packet(paths, method_id, expected)
    return rows


def default_destination_prefix(method_id: str, revision: str) -> str:
    return f"s3://{PRIVATE_BUCKET}/runs/{SUBJECT_ALIAS}/{RUN_ID}/reports/{method_id}/revisions/{revision}/"


def upload_private(
    row: dict[str, Any],
    bucket: str,
    destination_key: str,
    region: str,
) -> dict[str, Any]:
    response = aws_json(
        [
            "s3api",
            "put-object",
            "--bucket",
            bucket,
            "--key",
            destination_key,
            "--body",
            str(row["path"]),
            "--if-none-match",
            "*",
            "--content-type",
            content_type(str(row["relative_path"])),
            "--server-side-encryption",
            "aws:kms",
            "--ssekms-key-id",
            PRIVATE_KMS_KEY_ARN,
            "--checksum-algorithm",
            "SHA256",
            "--checksum-sha256",
            row["checksum_sha256"],
            "--metadata",
            json.dumps(
                {"classification": CLASSIFICATION, "sha256": row["sha256"]},
                sort_keys=True,
                separators=(",", ":"),
            ),
        ],
        region,
    )
    version_id = exact_non_null_version_id(
        response.get("VersionId"),
        f"private put {row['relative_path']}",
    )
    exact = head_object(bucket, destination_key, region, version_id)
    current = head_object(bucket, destination_key, region)
    checks = {
        "version_id": exact.get("VersionId") == current.get("VersionId") == version_id,
        "bytes": exact_int(exact.get("ContentLength"), row["bytes"])
        and exact_int(current.get("ContentLength"), row["bytes"]),
        "checksum_type": exact.get("ChecksumType") == current.get("ChecksumType") == "FULL_OBJECT",
        "checksum_sha256": exact.get("ChecksumSHA256") == current.get("ChecksumSHA256") == row["checksum_sha256"],
        "sse": exact.get("ServerSideEncryption") == current.get("ServerSideEncryption") == "aws:kms",
        "kms": exact.get("SSEKMSKeyId") == current.get("SSEKMSKeyId") == PRIVATE_KMS_KEY_ARN,
        "metadata_sha256": exact.get("Metadata") == current.get("Metadata") == {"classification": CLASSIFICATION, "sha256": row["sha256"]},
    }
    require_private_object_checks_exact(checks, str(row["relative_path"]))
    return {
        "relative_path": row["relative_path"],
        "bucket": bucket,
        "key": destination_key,
        "uri": f"s3://{bucket}/{destination_key}",
        "version_id": version_id,
        "bytes": row["bytes"],
        "sha256": row["sha256"],
        "checksum_sha256": row["checksum_sha256"],
        "checksum_type": "FULL_OBJECT",
        "server_side_encryption": "aws:kms",
        "kms_key_id": PRIVATE_KMS_KEY_ARN,
        "status": "passed",
        "checks": checks,
    }


def validate_dry_run_receipt(
    path: Path, receipt: dict[str, Any]
) -> dict[str, str]:
    path = require_real_input_file(path, "private report dry-run receipt")
    dry_run, dry_run_sha256 = load_json_with_sha256(
        path, "private report dry-run receipt"
    )
    if (
        not exact_schema_version(dry_run)
        or dry_run.get("status") != "dry_run"
        or dry_run.get("apply") is not False
        or set(dry_run) != PRIVATE_DRY_RUN_RECEIPT_KEYS
        or not isinstance(dry_run.get("generated_at_utc"), str)
        or not dry_run.get("generated_at_utc")
        or not isinstance(dry_run.get("completed_at_utc"), str)
        or not dry_run.get("completed_at_utc")
        or not exact_int(dry_run.get("object_count"), receipt["object_count"])
        or not exact_int(dry_run.get("passed_count"), 0)
        or not exact_int(
            dry_run.get("forbidden_token_count"),
            receipt["forbidden_token_count"],
        )
        or dry_run.get("objects") != []
    ):
        raise ValueError("private report dry-run receipt contract is malformed")

    expected_fields = (
        "subject_alias",
        "run_id",
        "method_id",
        "packet_revision",
        "source_packet_dir",
        "destination_prefix",
        "kms_key_arn",
        "expected_files",
        "forbidden_token_sha256",
    )
    if any(dry_run.get(field) != receipt.get(field) for field in expected_fields):
        raise ValueError("private report dry-run receipt does not match this apply")

    checks = dry_run.get("checks")
    required_checks = {
        "packet_inventory_exact": True,
        "packet_manifest_no_call_boundary": True,
        "packet_report_kind_exact": True,
        "packet_forbidden_token_scan": True,
    }
    if not exact_check_map(checks, required_checks):
        raise ValueError("private report dry-run receipt did not pass packet checks")

    return {
        "path": str(path.resolve()),
        "sha256": dry_run_sha256,
        "packet_revision": str(receipt["packet_revision"]),
        "status": "dry_run",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    method_id = args.method_id
    expected = tuple(sorted(METHOD_CONTRACTS[method_id]["files"]))
    tokens = forbidden_tokens(args)
    if not tokens:
        raise ValueError("at least one forbidden token is required")

    rows = validate_packet_dir(args.packet_dir, method_id, tokens)
    revision = canonical_packet_digest(rows)
    destination_prefix = args.destination_prefix or default_destination_prefix(method_id, revision)
    bucket, prefix = private_report_prefix(method_id, destination_prefix)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "preflighting",
        "generated_at_utc": now(),
        "apply": bool(args.apply),
        "subject_alias": SUBJECT_ALIAS,
        "run_id": RUN_ID,
        "method_id": method_id,
        "packet_revision": revision,
        "source_packet_dir": str(args.packet_dir.resolve()),
        "destination_prefix": f"s3://{bucket}/{prefix}",
        "kms_key_arn": PRIVATE_KMS_KEY_ARN,
        "expected_files": list(expected),
        "object_count": len(expected),
        "passed_count": 0,
        "forbidden_token_count": len(tokens),
        "forbidden_token_sha256": forbidden_token_fingerprints(tokens),
        "objects": [],
        "checks": {
            "packet_inventory_exact": True,
            "packet_manifest_no_call_boundary": True,
            "packet_report_kind_exact": True,
            "packet_forbidden_token_scan": True,
        },
    }
    dry_run_receipt = None
    if args.apply:
        if args.dry_run_receipt is None:
            raise ValueError("private report apply requires --dry-run-receipt")
        dry_run_receipt = validate_dry_run_receipt(args.dry_run_receipt, receipt)
        receipt["dry_run_receipt"] = dry_run_receipt
        receipt["checks"]["dry_run_receipt"] = True
    elif args.dry_run_receipt is not None:
        raise ValueError("--dry-run-receipt is only valid with --apply")
    write_private_atomic(args.receipt_output, receipt, create=True)

    try:
        if args.apply:
            versioning = aws_json(
                ["s3api", "get-bucket-versioning", "--bucket", bucket],
                args.region,
            )
            if versioning.get("Status") != "Enabled":
                raise ValueError(f"bucket versioning is not enabled: {bucket}")
            if version_history(bucket, prefix, args.region):
                raise ValueError("private destination prefix has prior history")
            receipt["checks"]["destination_initially_empty"] = True
            receipt["status"] = "in_progress"
            write_private_atomic(args.receipt_output, receipt, create=False)

            for row in rows:
                published = upload_private(
                    row,
                    bucket,
                    prefix + str(row["relative_path"]),
                    args.region,
                )
                receipt["objects"].append(published)
                receipt["passed_count"] = len(receipt["objects"])
                write_private_atomic(args.receipt_output, receipt, create=False)

            final_history = version_history(bucket, prefix, args.region)
            if not exact_final_history(final_history, prefix, receipt["objects"]):
                raise ValueError("private destination does not have exactly one expected version per file and no delete markers")
            receipt["checks"].update(
                {
                    "destination_sse_kms": True,
                    "destination_full_object_sha256": True,
                    "destination_non_null_versions": True,
                    "destination_exact_one_version_no_delete_history": True,
                }
            )
            receipt["destination_final_history_count"] = len(final_history)
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
    parser = argparse.ArgumentParser(description="Freeze one allowlisted HRD report packet in the private results bucket.")
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--method-id", required=True, choices=tuple(METHOD_CONTRACTS))
    parser.add_argument("--destination-prefix")
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument("--forbidden-tokens-file", action="append", default=[], type=Path)
    parser.add_argument("--dry-run-receipt", type=Path)
    parser.add_argument("--region", default=REGION, choices=(REGION,))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args)
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
                "method_id": result["method_id"],
                "object_count": result["object_count"],
                "passed_count": result["passed_count"],
                "receipt_output": str(args.receipt_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
