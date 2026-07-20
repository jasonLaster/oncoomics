#!/usr/bin/env python3
"""Publish an exact private report packet into the reviewed public alias tree.

This is deliberately not a generic S3 copier.  A supported method ID pins the
only accepted report-file inventory and the only accepted public destination.
Every source object is downloaded by its private VersionId and revalidated
before a second identifier scan and a create-only public upload.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
    validate_report_manifest_support,
)
from forbidden_text import (
    DEFAULT_FORBIDDEN_TOKENS,
    forbidden_token_fingerprints,
    has_unauthorized_hrd_classification,
    merge_forbidden_tokens,
    normalized_scan_text,
)
from hrd_report_inventory import require_report_methods

REGION = "us-east-1"
ACCOUNT_ID = "172630973301"
RUN_ID = "diana-wgs-hrd-20260716T033101Z"
SUBJECT_ALIAS = "subject01"
PRIVATE_BUCKET = f"diana-omics-private-results-{ACCOUNT_ID}-{REGION}"
PUBLIC_BUCKET = f"diana-omics-results-{ACCOUNT_ID}-{REGION}"
PRIVATE_KMS_KEY_ARN = (
    f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
    "45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
)
PUBLIC_ROOT = f"runs/diana-hrd-public/{SUBJECT_ALIAS}/{RUN_ID}/"
CLASSIFICATION = "reviewed-public-pseudonymous-analysis"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
VERSION_ID = re.compile(r"^\S+$")
REVISION = re.compile(r"^[0-9a-f]{64}$")
FINAL_SOURCE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
RESERVED_SOURCE_ARTIFACT_IDS = {"false", "null", "true"}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PACKET_BYTES = 100 * 1024 * 1024


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_HEX.fullmatch(value) is not None


def checked_final_source_artifact_id(value: Any, method_id: str) -> str:
    if (
        not isinstance(value, str)
        or not FINAL_SOURCE_ARTIFACT_ID.fullmatch(value)
        or value in RESERVED_SOURCE_ARTIFACT_IDS
    ):
        raise ValueError(f"malformed source-artifact ID for {method_id}")
    return value


DETERMINISTIC_FILES = (
    "crosscheck_input_plans.json",
    "evidence_checks.json",
    "input_sha256.csv",
    "readiness.csv",
    "report.md",
    "report_manifest.json",
)
ROSALIND_FILES = (
    "hrd_adapter_status.csv",
    "input_evidence_index.json",
    "next_actions.md",
    "report.md",
    "report_manifest.json",
    "research_context_sources.json",
    "reviewer_packet.md",
    "sample_validation_summary.csv",
)
CROSSCHECK_FILES = (
    "method_spec.json",
    "report.md",
    "report_manifest.json",
)
AI_REVIEW_FILES = (
    "claims.csv",
    "report.md",
    "report_manifest.json",
    "review_manifest.json",
    "validation.json",
)
SYNTHESIS_FILES = (
    "agreement_disagreement.csv",
    "report.md",
    "review_evidence.json",
    "report_manifest.json",
)
METHOD_CONTRACTS: dict[str, dict[str, Any]] = {
    "deterministic_full_wgs": {
        "files": DETERMINISTIC_FILES,
        "report_kind": "deterministic_baseline",
        "destination": "deterministic/",
    },
    "rosalind_diana_wgs": {
        "files": ROSALIND_FILES,
        "report_kind": "rosalind_hrd_reviewer_packet",
        "destination": "rosalind/",
    },
    "sequenza_scarhrd": {
        "files": CROSSCHECK_FILES,
        "report_kind": "executable_crosscheck_method",
        "destination": "crosschecks/sequenza_scarhrd/",
    },
    "sigprofiler_sbs3": {
        "files": CROSSCHECK_FILES,
        "report_kind": "executable_crosscheck_method",
        "destination": "crosschecks/sigprofiler_sbs3/",
    },
    "facets_scarhrd_blocked": {
        "files": CROSSCHECK_FILES,
        "report_kind": "blocked_method",
        "destination": "crosschecks/facets_scarhrd_blocked/",
    },
    "oncoanalyser_chord_blocked": {
        "files": CROSSCHECK_FILES,
        "report_kind": "blocked_method",
        "destination": "crosschecks/oncoanalyser_chord_blocked/",
    },
    "hrdetect_blocked": {
        "files": CROSSCHECK_FILES,
        "report_kind": "blocked_method",
        "destination": "crosschecks/hrdetect_blocked/",
    },
    "ai_review_reviewer_a": {
        "files": AI_REVIEW_FILES,
        "report_kind": "independent_ai_hrd_evidence_review",
        "destination": "ai-review/reviewer-a/",
    },
    "ai_review_reviewer_b": {
        "files": AI_REVIEW_FILES,
        "report_kind": "independent_ai_hrd_evidence_review",
        "destination": "ai-review/reviewer-b/",
    },
    "comparative_hrd_synthesis": {
        "files": SYNTHESIS_FILES,
        "report_kind": "comparative_synthesis",
        "destination": "ai-review/comparative-synthesis/",
    },
}
require_report_methods(tuple(METHOD_CONTRACTS), "reviewed public report method contracts")
SOURCE_PREFLIGHT_CHECKS = {
    "exact_version_head": True,
    "exact_version_get": True,
    "bytes": True,
    "sha256": True,
    "exact_kms": True,
    "forbidden_token_scan": True,
}
SOURCE_VERSION_CHECKS = {
    "version_id": True,
    "bytes": True,
    "checksum_type": True,
    "checksum_sha256": True,
    "sse_kms": True,
    "exact_kms": True,
    "metadata_sha256": True,
}
SOURCE_LOCAL_CHECKS = {
    "bytes": True,
    "sha256": True,
}
PRIVATE_RECEIPT_OBJECT_CHECKS = {
    "version_id": True,
    "bytes": True,
    "checksum_type": True,
    "checksum_sha256": True,
    "sse": True,
    "kms": True,
    "metadata_sha256": True,
}
PRIVATE_RECEIPT_APPLY_CHECKS = {
    "packet_inventory_exact": True,
    "packet_manifest_no_call_boundary": True,
    "packet_report_kind_exact": True,
    "packet_forbidden_token_scan": True,
    "dry_run_receipt": True,
    "destination_initially_empty": True,
    "destination_sse_kms": True,
    "destination_full_object_sha256": True,
    "destination_non_null_versions": True,
    "destination_exact_one_version_no_delete_history": True,
}
PRIVATE_RECEIPT_APPLY_KEYS = {
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
    "dry_run_receipt",
    "destination_final_history_count",
    "completed_at_utc",
}
PRIVATE_RECEIPT_OBJECT_KEYS = {
    "relative_path",
    "bucket",
    "key",
    "uri",
    "version_id",
    "bytes",
    "sha256",
    "checksum_sha256",
    "checksum_type",
    "server_side_encryption",
    "kms_key_id",
    "status",
    "checks",
}
PRIVATE_DRY_RUN_SUMMARY_KEYS = {
    "path",
    "sha256",
    "packet_revision",
    "status",
}
PUBLIC_DESTINATION_OBJECT_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "checksum_type": True,
    "checksum_sha256": True,
    "sse_s3": True,
    "metadata": True,
    "content_type": True,
}
REVIEWED_PUBLIC_PREFLIGHT_CHECKS = (
    "private_receipt_exact_and_passed",
    "source_exact_versions",
    "source_sha256_and_bytes",
    "source_exact_kms",
    "second_forbidden_token_scan",
    "manifest_no_call_boundary",
    "source_report_kind_exact",
    "destination_initially_empty",
    "packet_size_bounded",
)
REVIEWED_PUBLIC_DRY_RUN_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "generated_at_utc",
    "apply",
    "method_id",
    "subject_alias",
    "run_id",
    "classification",
    "script_sha256",
    "private_publication_receipt",
    "destination_prefix",
    "expected_files",
    "forbidden_token_count",
    "forbidden_token_sha256",
    "source_objects",
    "destination_objects",
    "destination_initial_history_count",
    "checks",
    "completed_at_utc",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return read_stable_file_with_sha256(
        path,
        f"{path.name} SHA-256 input",
    )[1]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def canonical_packet_digest(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [
            {
                "relative_path": row["relative_path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in sorted(rows, key=lambda item: str(item["relative_path"]))
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def non_null_version_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.lower() not in {"null", "none"}
        and VERSION_ID.fullmatch(value) is not None
    )


def exact_non_null_version_id(value: Any, label: str) -> str:
    if not non_null_version_id(value):
        raise ValueError(f"{label} omitted a non-null VersionId")
    return value


def exact_history_key(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is malformed")
    return value


def exact_version_history_row(row: dict[str, Any], kind: str) -> dict[str, Any]:
    exact_history_key(row.get("Key"), "destination version history Key")
    exact_non_null_version_id(
        row.get("VersionId"), "destination version history row"
    )
    return {**row, "history_kind": kind}


def is_positive_exact_int(value: Any) -> bool:
    return type(value) is int and value > 0


def exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and type(expected) is int and value == expected


def exact_schema_version(payload: dict[str, Any], expected: int = 1) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def read_stable_file_with_sha256(path: Path, label: str) -> tuple[bytes, str]:
    payload, identity = read_real_input_file_once(path, label)
    digest = sha256_bytes(payload)
    stable_payload, stable_identity = read_real_input_file_once(path, label)
    if stable_identity != identity or sha256_bytes(stable_payload) != digest:
        raise ValueError(f"{label} changed during read")
    return payload, digest


def read_real_input_file_once(
    path: Path,
    label: str,
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    require_real_input_file(path, label)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{label} must be a real file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            payload = handle.read()
            after_read = os.fstat(handle.fileno())
        current = path.lstat()
    except OSError as error:
        raise ValueError(f"{label} changed during read") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    require_real_input_file(path, label)
    if (
        stat_identity(opened) != stat_identity(after_read)
        or stat_identity(after_read) != stat_identity(current)
    ):
        raise ValueError(f"{label} changed during read")
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


def read_stable_text(path: Path, label: str) -> str:
    payload, _digest = read_stable_file_with_sha256(path, label)
    try:
        return payload.decode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"report packet contains a non-UTF-8 file: {path.name}") from error


def load_json_with_sha256(path: Path, label: str) -> tuple[dict[str, Any], str]:
    payload, digest = read_stable_file_with_sha256(path, label)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, digest


def load_json(path: Path, label: str) -> dict[str, Any]:
    value, _ = load_json_with_sha256(path, label)
    return value


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_real_input_file(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file")


def require_real_hash_input(path: Path) -> None:
    require_real_input_file(path, f"{path.name} SHA-256 input")


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
            not path.is_file() or (path.stat().st_mode & 0o777) != 0o600
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


def download_exact(
    bucket: str, key: str, version_id: str, destination: Path, region: str
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
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
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    value = json.loads(completed.stdout) if completed.stdout.strip() else {}
    if not isinstance(value, dict):
        raise ValueError("S3 get-object returned a non-object")
    return value


def head_object(
    bucket: str, key: str, region: str, version_id: str = ""
) -> dict[str, Any]:
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
            if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
                raise ValueError("destination version history is malformed")
            rows.extend(exact_version_history_row(row, kind) for row in values)
        if page.get("IsTruncated") is not True:
            break
        next_key = page.get("NextKeyMarker")
        next_version = page.get("NextVersionIdMarker")
        if (
            not isinstance(next_key, str)
            or not isinstance(next_version, str)
            or not next_key
            or not next_version
        ):
            raise ValueError(
                "truncated destination history omitted its next key/version markers"
            )
        marker = (next_key, next_version)
        if marker in seen_markers:
            raise ValueError("destination version history pagination did not advance")
        seen_markers.add(marker)
        key_marker, version_marker = next_key, next_version
    return sorted(
        rows,
        key=lambda row: (
            row["Key"],
            row["VersionId"],
            row["history_kind"],
        ),
    )


def parse_s3_prefix(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"s3://([^/]+)/(.+?)/?", value)
    if not match:
        raise ValueError("destination must be an S3 prefix")
    return match.group(1), match.group(2).rstrip("/") + "/"


def safe_relative(value: Any) -> str:
    text = str(value or "")
    path = PurePosixPath(text)
    if (
        not text
        or path.is_absolute()
        or path.as_posix() != text
        or ".." in path.parts
        or "_publication" in path.parts
        or len(path.parts) != 1
    ):
        raise ValueError(f"private receipt contains an unsafe report path: {text}")
    return text


def private_report_prefix(method_id: str, value: str) -> tuple[str, str]:
    bucket, prefix = parse_s3_prefix(value)
    expected = f"runs/{SUBJECT_ALIAS}/{RUN_ID}/reports/{method_id}/"
    if bucket != PRIVATE_BUCKET:
        raise ValueError("private publication receipt uses the wrong bucket")
    revision_prefix = expected + "revisions/"
    if not prefix.startswith(revision_prefix):
        raise ValueError("private publication receipt uses an unapproved report prefix")
    suffix = prefix.removeprefix(revision_prefix).rstrip("/")
    if not REVISION.fullmatch(suffix):
        raise ValueError("private publication receipt revision is not content-addressed")
    return bucket, prefix


def validate_private_receipt(
    path: Path, method_id: str
) -> tuple[dict[str, Any], tuple[str, ...], list[dict[str, Any]]]:
    require_real_input_file(path, "private publication receipt")
    if path.is_symlink() or not path.is_file():
        raise ValueError("private publication receipt must be a real file")
    receipt = load_json(path, "private publication receipt")
    expected, rows = validate_private_receipt_payload(receipt, method_id)
    return receipt, expected, rows


def validate_private_receipt_payload(
    receipt: dict[str, Any],
    method_id: str,
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    contract = METHOD_CONTRACTS[method_id]
    expected = tuple(sorted(contract["files"]))
    bucket, prefix = private_report_prefix(
        method_id, str(receipt.get("destination_prefix", ""))
    )
    rows = receipt.get("objects")
    checks = receipt.get("checks")
    forbidden_hashes = receipt.get("forbidden_token_sha256")
    if (
        set(receipt) != PRIVATE_RECEIPT_APPLY_KEYS
        or not exact_schema_version(receipt)
        or receipt.get("status") != "passed"
        or receipt.get("apply") is not True
        or receipt.get("subject_alias") != SUBJECT_ALIAS
        or receipt.get("run_id") != RUN_ID
        or receipt.get("method_id") != method_id
        or receipt.get("kms_key_arn") != PRIVATE_KMS_KEY_ARN
        or receipt.get("expected_files") != list(expected)
        or not exact_int(receipt.get("object_count"), len(expected))
        or not exact_int(receipt.get("passed_count"), len(expected))
        or not exact_int(
            receipt.get("destination_final_history_count"),
            len(expected),
        )
        or not isinstance(receipt.get("generated_at_utc"), str)
        or not receipt.get("generated_at_utc")
        or not isinstance(receipt.get("completed_at_utc"), str)
        or not receipt.get("completed_at_utc")
        or not isinstance(receipt.get("source_packet_dir"), str)
        or not receipt.get("source_packet_dir")
        or not is_positive_exact_int(receipt.get("forbidden_token_count"))
        or not isinstance(forbidden_hashes, list)
        or not forbidden_hashes
        or any(
            not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest)
            for digest in forbidden_hashes
        )
        or not exact_int(receipt.get("forbidden_token_count"), len(forbidden_hashes))
        or len(set(forbidden_hashes)) != len(forbidden_hashes)
        or forbidden_hashes != sorted(forbidden_hashes)
        or not isinstance(rows, list)
        or len(rows) != len(expected)
        or not exact_check_map(checks, PRIVATE_RECEIPT_APPLY_CHECKS)
    ):
        raise ValueError("private publication receipt contract is not exact and passed")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("private publication receipt object is not an object")
        if set(raw) != PRIVATE_RECEIPT_OBJECT_KEYS:
            raise ValueError("private publication receipt object envelope is not exact")
        relative = safe_relative(raw.get("relative_path"))
        if relative in seen:
            raise ValueError(f"private publication receipt repeats {relative}")
        seen.add(relative)
        digest = raw.get("sha256")
        version_id = raw.get("version_id")
        size = raw.get("bytes")
        checks = raw.get("checks")
        expected_key = prefix + relative
        if (
            raw.get("status") != "passed"
            or raw.get("bucket") != bucket
            or raw.get("key") != expected_key
            or raw.get("uri") != f"s3://{bucket}/{expected_key}"
            or not non_null_version_id(version_id)
            or not is_sha256(digest)
            or not is_positive_exact_int(size)
            or size > MAX_FILE_BYTES
            or raw.get("server_side_encryption") != "aws:kms"
            or raw.get("kms_key_id") != PRIVATE_KMS_KEY_ARN
            or raw.get("checksum_type") != "FULL_OBJECT"
            or raw.get("checksum_sha256") != checksum_sha256(digest)
            or not exact_check_map(checks, PRIVATE_RECEIPT_OBJECT_CHECKS)
        ):
            raise ValueError(f"private publication receipt object is not exact: {relative}")
        total_bytes += size
        normalized.append(
            {
                "relative_path": relative,
                "bucket": bucket,
                "key": expected_key,
                "version_id": version_id,
                "bytes": size,
                "sha256": digest,
                "checksum_sha256": checksum_sha256(digest),
            }
        )
    if tuple(sorted(seen)) != expected or total_bytes > MAX_PACKET_BYTES:
        raise ValueError("private publication receipt inventory is not allowlisted")
    packet_revision = canonical_packet_digest(normalized)
    expected_revision_prefix = (
        f"runs/{SUBJECT_ALIAS}/{RUN_ID}/reports/{method_id}/"
        f"revisions/{packet_revision}/"
    )
    if (
        receipt.get("packet_revision") != packet_revision
        or prefix != expected_revision_prefix
    ):
        raise ValueError("private publication receipt packet revision is not content addressed")
    dry_run = receipt.get("dry_run_receipt")
    if (
        not isinstance(dry_run, dict)
        or set(dry_run) != PRIVATE_DRY_RUN_SUMMARY_KEYS
        or dry_run.get("status") != "dry_run"
        or dry_run.get("packet_revision") != packet_revision
        or not isinstance(dry_run.get("path"), str)
        or not dry_run.get("path")
        or not isinstance(dry_run.get("sha256"), str)
        or not SHA256_HEX.fullmatch(dry_run.get("sha256", ""))
    ):
        raise ValueError("private publication dry-run receipt summary is not exact")
    return expected, sorted(normalized, key=lambda row: row["relative_path"])


def exact_source_checks(
    metadata: dict[str, Any], row: dict[str, Any]
) -> dict[str, bool]:
    return {
        "version_id": metadata.get("VersionId") == row["version_id"],
        "bytes": exact_int(metadata.get("ContentLength"), row["bytes"]),
        "checksum_type": metadata.get("ChecksumType") == "FULL_OBJECT",
        "checksum_sha256": metadata.get("ChecksumSHA256") == row["checksum_sha256"],
        "sse_kms": metadata.get("ServerSideEncryption") == "aws:kms",
        "exact_kms": metadata.get("SSEKMSKeyId") == PRIVATE_KMS_KEY_ARN,
        "metadata_sha256": metadata.get("Metadata", {}).get("sha256") == row["sha256"],
    }


def exact_local_source_checks(path: Path, row: dict[str, Any]) -> dict[str, bool]:
    return {
        "bytes": path.is_file() and path.stat().st_size == row["bytes"],
        "sha256": path.is_file() and sha256(path) == row["sha256"],
    }


def exact_check_map(value: Any, expected: dict[str, bool]) -> bool:
    if not isinstance(value, dict) or set(value) != set(expected):
        return False
    return all(
        value.get(name) is expected_value
        for name, expected_value in expected.items()
    )


def require_source_version_checks_exact(
    checks: dict[str, bool],
    relative_path: str,
    phase: str,
) -> None:
    if not exact_check_map(checks, SOURCE_VERSION_CHECKS):
        raise ValueError(
            f"private exact-version {phase} failed for {relative_path}: {checks}"
        )


def require_source_local_checks_exact(
    checks: dict[str, bool],
    relative_path: str,
) -> None:
    if not exact_check_map(checks, SOURCE_LOCAL_CHECKS):
        raise ValueError(
            f"private exact-version GET failed for {relative_path}: local={checks}"
        )


def require_public_destination_checks_exact(
    checks: dict[str, bool],
    relative_path: str,
) -> None:
    if not exact_check_map(checks, PUBLIC_DESTINATION_OBJECT_CHECKS):
        raise ValueError(
            f"public destination verification failed for {relative_path}: {checks}"
        )


def scan_text(path: Path, tokens: tuple[str, ...]) -> None:
    text = read_stable_text(path, f"{path.name} scan input")
    haystacks = [text]
    if path.suffix == ".json":
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"report packet contains malformed JSON: {path.name}") from error
        haystacks.append(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    normalized_tokens = tuple(
        normalized
        for normalized in (
            normalized_scan_text(token).casefold() for token in tokens
        )
        if normalized
    )
    normalized_haystacks = tuple(
        normalized_scan_text(haystack).casefold() for haystack in haystacks
    )
    if any(
        token in haystack
        for token in normalized_tokens
        for haystack in normalized_haystacks
    ):
        raise ValueError(f"forbidden identifier token remains in {path.name}")


def scan_no_call_language(path: Path) -> None:
    text = read_stable_text(path, f"{path.name} no-call scan input")

    haystacks = [text]
    if path.suffix == ".json":
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"report packet contains malformed JSON: {path.name}") from error
        haystacks.append(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    if any(has_unauthorized_hrd_classification(haystack) for haystack in haystacks):
        raise ValueError(f"unauthorized HRD classification remains in {path.name}")


def validate_report_packet(
    paths: dict[str, Path], method_id: str, expected: tuple[str, ...]
) -> dict[str, Any]:
    manifest = load_json(paths["report_manifest.json"], "report manifest")
    if manifest.get("report_kind") != METHOD_CONTRACTS[method_id]["report_kind"]:
        raise ValueError("report manifest report_kind is not exact")
    validate_report_manifest_support(
        paths["report_manifest.json"].parent,
        manifest,
        method_id,
    )
    if (
        not exact_schema_version(manifest)
        or manifest.get("method_id") != method_id
        or manifest.get("evidence_status") not in {"partial_evidence", "no_call", "blocked"}
        or manifest.get("authorized_hrd_state") != "no_call"
        or manifest.get("classification_authorized") is not False
        or manifest.get("classification_qc_status") != "not_applicable"
        or manifest.get("report_sha256") != sha256(paths["report.md"])
        or not isinstance(manifest.get("review_summary"), dict)
        or not manifest.get("review_summary")
    ):
        raise ValueError("report manifest does not preserve the reviewed no-call contract")
    support = manifest.get("support_sha256")
    expected_support = set(expected) - {"report.md", "report_manifest.json"}
    if not isinstance(support, dict) or set(support) != expected_support:
        raise ValueError("report manifest support inventory is not exact")
    for name in expected_support:
        if support.get(name) != sha256(paths[name]):
            raise ValueError(f"report manifest support hash differs for {name}")
    sources = manifest.get("source_sha256")
    if (
        not isinstance(sources, dict)
        or not sources
        or any(
            checked_final_source_artifact_id(name, method_id) != name
            or not isinstance(digest, str)
            or not SHA256_HEX.fullmatch(digest)
            for name, digest in sources.items()
        )
    ):
        raise ValueError("report manifest source SHA-256 inventory is malformed")
    for name in sorted(set(sources) & expected_support):
        if sources[name] != sha256(paths[name]):
            raise ValueError(f"report manifest source hash differs for {name}")
    for name in sorted(expected):
        scan_no_call_language(paths[name])
    return manifest


def content_type(relative: str) -> str:
    if relative.endswith(".json"):
        return "application/json"
    if relative.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if relative.endswith(".csv"):
        return "text/csv; charset=utf-8"
    raise ValueError(f"report packet has no approved content type: {relative}")


def upload_public(
    path: Path,
    row: dict[str, Any],
    destination_key: str,
    region: str,
) -> dict[str, Any]:
    response = aws_json(
        [
            "s3api",
            "put-object",
            "--bucket",
            PUBLIC_BUCKET,
            "--key",
            destination_key,
            "--body",
            str(path),
            "--if-none-match",
            "*",
            "--content-type",
            content_type(row["relative_path"]),
            "--server-side-encryption",
            "AES256",
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
        f"public put {row['relative_path']}",
    )
    expected_checksum = row["checksum_sha256"]
    exact = head_object(PUBLIC_BUCKET, destination_key, region, version_id)
    current = head_object(PUBLIC_BUCKET, destination_key, region)
    checks = {
        "version_exact": exact.get("VersionId") == current.get("VersionId") == version_id,
        "bytes_exact": exact_int(exact.get("ContentLength"), row["bytes"])
        and exact_int(current.get("ContentLength"), row["bytes"]),
        "checksum_type": exact.get("ChecksumType")
        == current.get("ChecksumType")
        == "FULL_OBJECT",
        "checksum_sha256": exact.get("ChecksumSHA256")
        == current.get("ChecksumSHA256")
        == expected_checksum,
        "sse_s3": exact.get("ServerSideEncryption")
        == current.get("ServerSideEncryption")
        == "AES256",
        "metadata": exact.get("Metadata")
        == current.get("Metadata")
        == {"classification": CLASSIFICATION, "sha256": row["sha256"]},
        "content_type": exact.get("ContentType")
        == current.get("ContentType")
        == content_type(row["relative_path"]),
    }
    require_public_destination_checks_exact(checks, str(row["relative_path"]))
    return {
        "relative_path": row["relative_path"],
        "bucket": PUBLIC_BUCKET,
        "key": destination_key,
        "uri": f"s3://{PUBLIC_BUCKET}/{destination_key}",
        "version_id": version_id,
        "bytes": row["bytes"],
        "sha256": row["sha256"],
        "checksum_sha256": expected_checksum,
        "server_side_encryption": "AES256",
        "status": "passed",
        "checks": checks,
    }


def exact_final_history(
    history: list[dict[str, Any]], destination_prefix: str, objects: list[dict[str, Any]]
) -> bool:
    if len(history) != len(objects) or any(
        row.get("history_kind") != "version" for row in history
    ):
        return False
    expected = {row["key"]: row for row in objects}
    if set(str(row.get("Key", "")) for row in history) != set(expected):
        return False
    for row in history:
        key = str(row.get("Key", ""))
        published = expected[key]
        if (
            not key.startswith(destination_prefix)
            or row.get("VersionId") != published["version_id"]
            or row.get("IsLatest") is not True
            or not exact_int(row.get("Size"), published["bytes"])
        ):
            return False
    return True


def source_preflight_object(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "status": "passed", "checks": dict(SOURCE_PREFLIGHT_CHECKS)}


def validate_dry_run_receipt(
    path: Path, receipt: dict[str, Any], source_rows: list[dict[str, Any]]
) -> dict[str, str]:
    require_real_input_file(path, "reviewed-public report dry-run receipt")
    if path.is_symlink() or not path.is_file():
        raise ValueError("reviewed-public report dry-run receipt must be a real file")
    dry_run, dry_run_sha256 = load_json_with_sha256(
        path, "reviewed-public report dry-run receipt"
    )
    source_objects = dry_run.get("source_objects")
    checks = dry_run.get("checks")
    private_publication_receipt = dry_run.get("private_publication_receipt")
    if (
        not exact_schema_version(dry_run)
        or dry_run.get("status") != "dry_run"
        or dry_run.get("apply") is not False
        or set(dry_run) != REVIEWED_PUBLIC_DRY_RUN_RECEIPT_KEYS
        or not isinstance(dry_run.get("generated_at_utc"), str)
        or not dry_run.get("generated_at_utc")
        or not isinstance(dry_run.get("completed_at_utc"), str)
        or not dry_run.get("completed_at_utc")
        or dry_run.get("destination_objects") != []
        or not exact_int(dry_run.get("destination_initial_history_count"), 0)
        or not isinstance(source_objects, list)
        or not source_objects
        or not isinstance(checks, dict)
        or not isinstance(private_publication_receipt, dict)
    ):
        raise ValueError("reviewed-public report dry-run receipt contract is malformed")

    expected_fields = (
        "method_id",
        "subject_alias",
        "run_id",
        "classification",
        "script_sha256",
        "destination_prefix",
        "expected_files",
        "forbidden_token_count",
        "forbidden_token_sha256",
    )
    if any(dry_run.get(field) != receipt.get(field) for field in expected_fields):
        raise ValueError("reviewed-public report dry-run receipt does not match this apply")

    current_private = receipt["private_publication_receipt"]
    if private_publication_receipt != current_private:
        raise ValueError(
            "reviewed-public report dry-run private receipt does not match this apply"
        )

    if not exact_check_map(
        checks,
        dict.fromkeys(REVIEWED_PUBLIC_PREFLIGHT_CHECKS, True),
    ):
        raise ValueError(
            "reviewed-public report dry-run receipt did not pass preflight checks"
        )

    if source_objects != [source_preflight_object(row) for row in source_rows]:
        raise ValueError(
            "reviewed-public report dry-run source objects do not match this apply"
        )

    return {
        "path": str(path.resolve()),
        "sha256": dry_run_sha256,
        "method_id": str(receipt["method_id"]),
        "status": "dry_run",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    method_id = args.method_id
    contract = METHOD_CONTRACTS[method_id]
    expected_destination = PUBLIC_ROOT + str(contract["destination"])
    bucket, destination_prefix = parse_s3_prefix(args.destination_prefix)
    if bucket != PUBLIC_BUCKET or destination_prefix != expected_destination:
        raise ValueError(
            "destination is not the exact reviewed public child for this method"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", args.private_publication_receipt_sha256):
        raise ValueError("expected private publication receipt SHA-256 is malformed")
    private_receipt, actual_receipt_sha256 = load_json_with_sha256(
        args.private_publication_receipt,
        "private publication receipt",
    )
    if actual_receipt_sha256 != args.private_publication_receipt_sha256:
        raise ValueError("private publication receipt SHA-256 does not match expected")
    expected, source_rows = validate_private_receipt_payload(private_receipt, method_id)
    tokens = merge_forbidden_tokens(
        (*DEFAULT_FORBIDDEN_TOKENS, *args.forbidden_token),
        files=args.forbidden_tokens_file,
    )
    if not tokens:
        raise ValueError("at least one forbidden token is required")

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "preflighting",
        "generated_at_utc": now(),
        "apply": bool(args.apply),
        "method_id": method_id,
        "subject_alias": SUBJECT_ALIAS,
        "run_id": RUN_ID,
        "classification": CLASSIFICATION,
        "script_sha256": sha256(Path(__file__)),
        "private_publication_receipt": {
            "path": str(args.private_publication_receipt.resolve()),
            "sha256": actual_receipt_sha256,
            "destination_prefix": private_receipt["destination_prefix"],
        },
        "destination_prefix": f"s3://{bucket}/{destination_prefix}",
        "expected_files": list(expected),
        "forbidden_token_count": len(tokens),
        "forbidden_token_sha256": forbidden_token_fingerprints(tokens),
        "source_objects": [],
        "destination_objects": [],
    }
    dry_run_receipt = None
    if args.apply:
        if args.dry_run_receipt is None:
            raise ValueError("reviewed-public report apply requires --dry-run-receipt")
        dry_run_receipt = validate_dry_run_receipt(
            args.dry_run_receipt, receipt, source_rows
        )
        receipt["dry_run_receipt"] = dry_run_receipt
        receipt["checks"] = {"dry_run_receipt": True}
    elif args.dry_run_receipt is not None:
        raise ValueError("--dry-run-receipt is only valid with --apply")
    write_private_atomic(args.receipt_output, receipt, create=True)
    try:
        for required_bucket in (PRIVATE_BUCKET, PUBLIC_BUCKET):
            versioning = aws_json(
                ["s3api", "get-bucket-versioning", "--bucket", required_bucket],
                args.region,
            )
            if versioning.get("Status") != "Enabled":
                raise ValueError(f"bucket versioning is not enabled: {required_bucket}")
        initial_history = version_history(bucket, destination_prefix, args.region)
        if initial_history:
            raise ValueError("public destination prefix has prior version or delete-marker history")
        receipt["destination_initial_history_count"] = 0

        with tempfile.TemporaryDirectory(prefix="reviewed-public-report-") as temporary:
            staging = Path(temporary)
            local_paths: dict[str, Path] = {}
            for row in source_rows:
                relative = row["relative_path"]
                before = head_object(
                    row["bucket"], row["key"], args.region, row["version_id"]
                )
                before_checks = exact_source_checks(before, row)
                require_source_version_checks_exact(
                    before_checks,
                    relative,
                    "head",
                )
                local = staging / relative
                downloaded = download_exact(
                    row["bucket"],
                    row["key"],
                    row["version_id"],
                    local,
                    args.region,
                )
                require_real_input_file(
                    local,
                    f"downloaded reviewed-public report file {relative}",
                )
                get_checks = exact_source_checks(downloaded, row)
                require_source_version_checks_exact(get_checks, relative, "GET")
                local_checks = exact_local_source_checks(local, row)
                require_source_local_checks_exact(local_checks, relative)
                scan_text(local, tokens)
                local_paths[relative] = local
                receipt["source_objects"].append(source_preflight_object(row))
                write_private_atomic(args.receipt_output, receipt, create=False)
            validate_report_packet(local_paths, method_id, expected)
            receipt["checks"] = {
                "private_receipt_exact_and_passed": True,
                "source_exact_versions": True,
                "source_sha256_and_bytes": True,
                "source_exact_kms": True,
                "second_forbidden_token_scan": True,
                "manifest_no_call_boundary": True,
                "source_report_kind_exact": True,
                "destination_initially_empty": True,
                "packet_size_bounded": True,
            }
            if dry_run_receipt is not None:
                receipt["checks"]["dry_run_receipt"] = True
            if not args.apply:
                receipt["status"] = "dry_run"
                receipt["completed_at_utc"] = now()
                write_private_atomic(args.receipt_output, receipt, create=False)
                return receipt

            receipt["status"] = "in_progress"
            write_private_atomic(args.receipt_output, receipt, create=False)
            for row in source_rows:
                destination_key = destination_prefix + row["relative_path"]
                published = upload_public(
                    local_paths[row["relative_path"]], row, destination_key, args.region
                )
                receipt["destination_objects"].append(published)
                write_private_atomic(args.receipt_output, receipt, create=False)

        final_history = version_history(bucket, destination_prefix, args.region)
        if not exact_final_history(
            final_history, destination_prefix, receipt["destination_objects"]
        ):
            raise ValueError(
                "public destination does not have exactly one expected version per file and no delete markers"
            )
        receipt["checks"].update(
            {
                "all_destination_writes_create_only": True,
                "destination_sse_s3": True,
                "destination_full_object_sha256": True,
                "destination_non_null_versions": True,
                "destination_exact_one_version_no_delete_history": True,
            }
        )
        receipt["destination_final_history_count"] = len(final_history)
        receipt["status"] = "passed"
        receipt["completed_at_utc"] = now()
        write_private_atomic(args.receipt_output, receipt, create=False)
        return receipt
    except Exception as error:
        receipt["status"] = "failed"
        receipt["failed_at_utc"] = now()
        receipt["error"] = f"{type(error).__name__}: {error}"
        with suppress(Exception):
            write_private_atomic(args.receipt_output, receipt, create=False)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish one allowlisted report packet to the reviewed Diana public alias tree."
    )
    parser.add_argument("--private-publication-receipt", required=True, type=Path)
    parser.add_argument("--private-publication-receipt-sha256", required=True)
    parser.add_argument("--method-id", required=True, choices=tuple(METHOD_CONTRACTS))
    parser.add_argument("--destination-prefix", required=True)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument(
        "--forbidden-tokens-file",
        action="append",
        default=[],
        type=Path,
    )
    parser.add_argument("--dry-run-receipt", type=Path)
    parser.add_argument("--region", default=REGION, choices=(REGION,))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
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
                "source_objects": len(result["source_objects"]),
                "destination_objects": len(result["destination_objects"]),
                "receipt_output": str(args.receipt_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
