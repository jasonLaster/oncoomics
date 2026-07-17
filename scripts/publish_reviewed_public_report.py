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
import subprocess
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

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
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PACKET_BYTES = 100 * 1024 * 1024

DETERMINISTIC_FILES = (
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
    "report_manifest.json",
)
METHOD_CONTRACTS: dict[str, dict[str, Any]] = {
    "deterministic_full_wgs": {
        "files": DETERMINISTIC_FILES,
        "destination": "deterministic/",
    },
    "rosalind_diana_wgs": {
        "files": ROSALIND_FILES,
        "destination": "rosalind/",
    },
    "sequenza_scarhrd": {
        "files": CROSSCHECK_FILES,
        "destination": "crosschecks/sequenza_scarhrd/",
    },
    "sigprofiler_sbs3": {
        "files": CROSSCHECK_FILES,
        "destination": "crosschecks/sigprofiler_sbs3/",
    },
    "facets_scarhrd_blocked": {
        "files": CROSSCHECK_FILES,
        "destination": "crosschecks/facets_scarhrd_blocked/",
    },
    "oncoanalyser_chord_blocked": {
        "files": CROSSCHECK_FILES,
        "destination": "crosschecks/oncoanalyser_chord_blocked/",
    },
    "hrdetect_blocked": {
        "files": CROSSCHECK_FILES,
        "destination": "crosschecks/hrdetect_blocked/",
    },
    "ai_review_reviewer_a": {
        "files": AI_REVIEW_FILES,
        "destination": "ai-review/reviewer-a/",
    },
    "ai_review_reviewer_b": {
        "files": AI_REVIEW_FILES,
        "destination": "ai-review/reviewer-b/",
    },
    "comparative_hrd_synthesis": {
        "files": SYNTHESIS_FILES,
        "destination": "ai-review/comparative-synthesis/",
    },
}
require_report_methods(tuple(METHOD_CONTRACTS), "reviewed public report method contracts")
DEFAULT_FORBIDDEN_TOKENS = (
    "DRF-PSN49561",
    "E019_S01",
    "echo-personalis",
    "personalis",
)


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


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def non_null_version_id(value: str) -> bool:
    return value != "null" and VERSION_ID.fullmatch(value) is not None


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def write_private_atomic(path: Path, value: dict[str, Any], *, create: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("receipt output may not be a symlink")
    if create:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        temporary: Path | None = None
    else:
        if not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
            raise ValueError("reserved receipt output is missing or not mode 0600")
        descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.fchmod(descriptor, 0o600)
        temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        if temporary is not None:
            os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
            rows.extend({"history_kind": kind, **row} for row in values)
        if page.get("IsTruncated") is not True:
            break
        next_key = str(page.get("NextKeyMarker", ""))
        next_version = str(page.get("NextVersionIdMarker", ""))
        if not next_key or (next_key, next_version) == (key_marker, version_marker):
            raise ValueError("destination version history pagination did not advance")
        key_marker, version_marker = next_key, next_version
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("Key", "")),
            str(row.get("VersionId", "")),
            str(row.get("history_kind", "")),
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
    if prefix == expected:
        return bucket, prefix
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
    if path.is_symlink() or not path.is_file():
        raise ValueError("private publication receipt must be a real file")
    receipt = load_json(path, "private publication receipt")
    contract = METHOD_CONTRACTS[method_id]
    expected = tuple(sorted(contract["files"]))
    bucket, prefix = private_report_prefix(
        method_id, str(receipt.get("destination_prefix", ""))
    )
    rows = receipt.get("objects")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("status") != "passed"
        or receipt.get("subject_alias") != SUBJECT_ALIAS
        or receipt.get("run_id") != RUN_ID
        or receipt.get("method_id") != method_id
        or receipt.get("kms_key_arn") != PRIVATE_KMS_KEY_ARN
        or receipt.get("expected_files") != list(expected)
        or receipt.get("object_count") != len(expected)
        or receipt.get("passed_count") != len(expected)
        or not isinstance(rows, list)
        or len(rows) != len(expected)
    ):
        raise ValueError("private publication receipt contract is not exact and passed")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("private publication receipt object is not an object")
        relative = safe_relative(raw.get("relative_path"))
        if relative in seen:
            raise ValueError(f"private publication receipt repeats {relative}")
        seen.add(relative)
        digest = str(raw.get("sha256", ""))
        version_id = str(raw.get("version_id", ""))
        size = int(raw.get("bytes", -1))
        checks = raw.get("checks")
        expected_key = prefix + relative
        if (
            raw.get("status") != "passed"
            or raw.get("bucket") != bucket
            or raw.get("key") != expected_key
            or raw.get("uri") != f"s3://{bucket}/{expected_key}"
            or not non_null_version_id(version_id)
            or not SHA256_HEX.fullmatch(digest)
            or size <= 0
            or size > MAX_FILE_BYTES
            or raw.get("server_side_encryption") != "aws:kms"
            or raw.get("kms_key_id") != PRIVATE_KMS_KEY_ARN
            or raw.get("checksum_type") != "FULL_OBJECT"
            or raw.get("checksum_sha256") != checksum_sha256(digest)
            or not isinstance(checks, dict)
            or not checks
            or not all(value is True for value in checks.values())
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
    return receipt, expected, sorted(normalized, key=lambda row: row["relative_path"])


def exact_source_checks(
    metadata: dict[str, Any], row: dict[str, Any]
) -> dict[str, bool]:
    return {
        "version_id": metadata.get("VersionId") == row["version_id"],
        "bytes": int(metadata.get("ContentLength", -1)) == row["bytes"],
        "checksum_type": metadata.get("ChecksumType") == "FULL_OBJECT",
        "checksum_sha256": metadata.get("ChecksumSHA256") == row["checksum_sha256"],
        "sse_kms": metadata.get("ServerSideEncryption") == "aws:kms",
        "exact_kms": metadata.get("SSEKMSKeyId") == PRIVATE_KMS_KEY_ARN,
        "metadata_sha256": metadata.get("Metadata", {}).get("sha256") == row["sha256"],
    }


def scan_text(path: Path, tokens: tuple[str, ...]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"report packet contains a non-UTF-8 file: {path.name}") from error
    haystacks = [text]
    if path.suffix == ".json":
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"report packet contains malformed JSON: {path.name}") from error
        haystacks.append(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    if any(
        token.casefold() in haystack.casefold()
        for token in tokens
        for haystack in haystacks
    ):
        raise ValueError(f"forbidden identifier token remains in {path.name}")


def validate_report_packet(
    paths: dict[str, Path], method_id: str, expected: tuple[str, ...]
) -> dict[str, Any]:
    manifest = load_json(paths["report_manifest.json"], "report manifest")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("method_id") != method_id
        or manifest.get("evidence_status") not in {"partial_evidence", "no_call", "blocked"}
        or manifest.get("authorized_hrd_state") != "no_call"
        or manifest.get("classification_authorized") is not False
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
            not isinstance(name, str)
            or not name
            or not isinstance(digest, str)
            or not SHA256_HEX.fullmatch(digest)
            for name, digest in sources.items()
        )
    ):
        raise ValueError("report manifest source SHA-256 inventory is malformed")
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
        raise ValueError(f"public put omitted a non-null VersionId: {row['relative_path']}")
    expected_checksum = row["checksum_sha256"]
    exact = head_object(PUBLIC_BUCKET, destination_key, region, version_id)
    current = head_object(PUBLIC_BUCKET, destination_key, region)
    checks = {
        "version_exact": exact.get("VersionId") == current.get("VersionId") == version_id,
        "bytes_exact": int(exact.get("ContentLength", -1))
        == int(current.get("ContentLength", -2))
        == row["bytes"],
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
    if not all(checks.values()):
        raise ValueError(
            f"public destination verification failed for {row['relative_path']}: {checks}"
        )
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
            or int(row.get("Size", -1)) != published["bytes"]
        ):
            return False
    return True


def run(args: argparse.Namespace) -> dict[str, Any]:
    method_id = args.method_id
    contract = METHOD_CONTRACTS[method_id]
    expected_destination = PUBLIC_ROOT + str(contract["destination"])
    bucket, destination_prefix = parse_s3_prefix(args.destination_prefix)
    if bucket != PUBLIC_BUCKET or destination_prefix != expected_destination:
        raise ValueError(
            "destination is not the exact reviewed public child for this method"
        )
    private_receipt, expected, source_rows = validate_private_receipt(
        args.private_publication_receipt, method_id
    )
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
            "sha256": sha256(args.private_publication_receipt),
            "destination_prefix": private_receipt["destination_prefix"],
        },
        "destination_prefix": f"s3://{bucket}/{destination_prefix}",
        "expected_files": list(expected),
        "forbidden_token_count": len(tokens),
        "source_objects": [],
        "destination_objects": [],
    }
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
                if not all(before_checks.values()):
                    raise ValueError(
                        f"private exact-version head failed for {relative}: {before_checks}"
                    )
                local = staging / relative
                downloaded = download_exact(
                    row["bucket"],
                    row["key"],
                    row["version_id"],
                    local,
                    args.region,
                )
                get_checks = exact_source_checks(downloaded, row)
                local_checks = {
                    "bytes": local.is_file() and local.stat().st_size == row["bytes"],
                    "sha256": local.is_file() and sha256(local) == row["sha256"],
                }
                if not all(get_checks.values()) or not all(local_checks.values()):
                    raise ValueError(
                        f"private exact-version GET failed for {relative}: "
                        f"get={get_checks}, local={local_checks}"
                    )
                scan_text(local, tokens)
                local_paths[relative] = local
                receipt["source_objects"].append(
                    {
                        **row,
                        "status": "passed",
                        "checks": {
                            "exact_version_head": True,
                            "exact_version_get": True,
                            "bytes": True,
                            "sha256": True,
                            "exact_kms": True,
                            "forbidden_token_scan": True,
                        },
                    }
                )
                write_private_atomic(args.receipt_output, receipt, create=False)
            validate_report_packet(local_paths, method_id, expected)
            receipt["checks"] = {
                "private_receipt_exact_and_passed": True,
                "source_exact_versions": True,
                "source_sha256_and_bytes": True,
                "source_exact_kms": True,
                "second_forbidden_token_scan": True,
                "manifest_no_call_boundary": True,
                "destination_initially_empty": True,
                "packet_size_bounded": True,
            }
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
    parser.add_argument("--method-id", required=True, choices=tuple(METHOD_CONTRACTS))
    parser.add_argument("--destination-prefix", required=True)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
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
