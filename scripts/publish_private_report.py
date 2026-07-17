#!/usr/bin/env python3
"""Freeze one allowlisted HRD report packet in the private results bucket."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from publish_reviewed_public_report import (
    DEFAULT_FORBIDDEN_TOKENS,
    MAX_FILE_BYTES,
    MAX_PACKET_BYTES,
    METHOD_CONTRACTS,
    PRIVATE_BUCKET,
    PRIVATE_KMS_KEY_ARN,
    REGION,
    RUN_ID,
    SUBJECT_ALIAS,
    aws_json,
    checksum_sha256,
    content_type,
    exact_final_history,
    head_object,
    non_null_version_id,
    now,
    private_report_prefix,
    scan_text,
    sha256,
    validate_report_packet,
    version_history,
    write_private_atomic,
)

CLASSIFICATION = "private-reviewed-hrd-report"


def canonical_packet_digest(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [
            {
                "relative_path": row["relative_path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in rows
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def validate_packet_dir(
    packet_dir: Path, method_id: str, tokens: tuple[str, ...]
) -> list[dict[str, Any]]:
    if packet_dir.is_symlink() or not packet_dir.is_dir():
        raise ValueError("packet directory must be a real directory")
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
        scan_text(path, tokens)
        digest = sha256(path)
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
    return (
        f"s3://{PRIVATE_BUCKET}/runs/{SUBJECT_ALIAS}/{RUN_ID}/reports/"
        f"{method_id}/revisions/{revision}/"
    )


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
            "--metadata",
            json.dumps(
                {"classification": CLASSIFICATION, "sha256": row["sha256"]},
                sort_keys=True,
                separators=(",", ":"),
            ),
        ],
        region,
    )
    version_id = str(response.get("VersionId", ""))
    if not non_null_version_id(version_id):
        raise ValueError(f"private put omitted a non-null VersionId: {row['relative_path']}")
    exact = head_object(bucket, destination_key, region, version_id)
    current = head_object(bucket, destination_key, region)
    checks = {
        "version_id": exact.get("VersionId") == current.get("VersionId") == version_id,
        "bytes": int(exact.get("ContentLength", -1))
        == int(current.get("ContentLength", -2))
        == row["bytes"],
        "checksum_type": exact.get("ChecksumType")
        == current.get("ChecksumType")
        == "FULL_OBJECT",
        "checksum_sha256": exact.get("ChecksumSHA256")
        == current.get("ChecksumSHA256")
        == row["checksum_sha256"],
        "sse": exact.get("ServerSideEncryption")
        == current.get("ServerSideEncryption")
        == "aws:kms",
        "kms": exact.get("SSEKMSKeyId")
        == current.get("SSEKMSKeyId")
        == PRIVATE_KMS_KEY_ARN,
        "metadata_sha256": exact.get("Metadata")
        == current.get("Metadata")
        == {"classification": CLASSIFICATION, "sha256": row["sha256"]},
    }
    if not all(checks.values()):
        raise ValueError(
            f"private destination verification failed for {row['relative_path']}: {checks}"
        )
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


def run(args: argparse.Namespace) -> dict[str, Any]:
    method_id = args.method_id
    expected = tuple(sorted(METHOD_CONTRACTS[method_id]["files"]))
    tokens = tuple(
        sorted(
            {
                token.strip()
                for token in (*DEFAULT_FORBIDDEN_TOKENS, *args.forbidden_token)
                if token.strip()
            },
            key=str.casefold,
        )
    )
    if not tokens:
        raise ValueError("at least one forbidden token is required")

    rows = validate_packet_dir(args.packet_dir, method_id, tokens)
    revision = canonical_packet_digest(rows)
    destination_prefix = args.destination_prefix or default_destination_prefix(
        method_id, revision
    )
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
        "objects": [],
        "checks": {
            "packet_inventory_exact": True,
            "packet_manifest_no_call_boundary": True,
            "packet_forbidden_token_scan": True,
        },
    }
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
                raise ValueError(
                    "private destination does not have exactly one expected version per file and no delete markers"
                )
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
    parser = argparse.ArgumentParser(
        description="Freeze one allowlisted HRD report packet in the private results bucket."
    )
    parser.add_argument("--packet-dir", required=True, type=Path)
    parser.add_argument("--method-id", required=True, choices=tuple(METHOD_CONTRACTS))
    parser.add_argument("--destination-prefix")
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
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
