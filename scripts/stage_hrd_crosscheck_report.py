#!/usr/bin/env python3
"""Stage a compact HRD cross-check packet from an exact route replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Sequence

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
)
from hrd_report_inventory import EXECUTABLE_CROSSCHECK_METHOD_IDS

SUPPORTED_ROUTES = set(EXECUTABLE_CROSSCHECK_METHOD_IDS)
ALLOWED_EVIDENCE_STATES = {"partial_evidence", "no_call", "blocked"}
SHA256_HEX = set("0123456789abcdef")
CORE_REPORT_FILES = {"report.md", "report_manifest.json"}
METHOD_SPEC_KEYS = {
    "schema_version",
    "method_id",
    "route",
    "report_kind",
    "evidence_status",
    "authorized_hrd_state",
    "classification_authorized",
    "classification_qc_status",
    "source_object_count",
    "source_report_manifest_sha256",
    "source_report_sha256",
    "download_verification_sha256",
    "source_review_summary",
}
REPORT_MANIFEST_KEYS = {
    "schema_version",
    "method_id",
    "report_kind",
    "route",
    "evidence_status",
    "authorized_hrd_state",
    "classification_authorized",
    "classification_qc_status",
    "review_summary",
    "source_sha256",
    "support_sha256",
    "report_sha256",
}
EXPECTED_DOWNLOAD_LIVE_HISTORY_CHECKS = {
    "version_count_exact": True,
    "all_entries_are_versions": True,
    "key_inventory_exact": True,
    "all_version_ids_exact": True,
    "all_versions_latest": True,
}
EXPECTED_DOWNLOAD_OBJECT_CHECKS = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "checksum_sha256_exact": True,
    "checksum_type_full_object": True,
    "exact_kms": True,
}
DOWNLOAD_VERIFICATION_REQUIRED_KEYS = {
    "schema_version",
    "status",
    "publication_receipt_sha256",
    "publication_receipt_uri",
    "route_output_uri",
    "expected_kms_key_arn",
    "live_history_checks",
    "output_dir",
    "objects",
    "object_count",
}
DOWNLOAD_VERIFICATION_OPTIONAL_KEYS = {
    "recovered_from_status",
    "prior_verification_sha256",
    "prior_error",
    "recovered_prepared_cutover",
}
DOWNLOAD_VERIFICATION_OBJECT_KEYS = {
    "relative_path",
    "version_id",
    "bytes",
    "sha256",
    "checks",
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
    return read_stable_file_with_sha256(path, f"{path.name} SHA-256 input")[1]


def sha256_file_once(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value, _digest = load_json_with_sha256(path, label)
    return value


def load_json_with_sha256(path: Path, label: str) -> tuple[dict[str, Any], str]:
    payload, payload_sha256 = read_stable_file_with_sha256(path, label)
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
    return value, payload_sha256


def read_stable_file_with_sha256(path: Path, label: str) -> tuple[bytes, str]:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink")
    payload = read_real_file_once(path, label)
    payload_sha256 = sha256_bytes(payload)
    if sha256_bytes(read_real_file_once(path, label)) != payload_sha256:
        raise ValueError(f"{label} changed during read")
    return payload, payload_sha256


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_real_file_once(path: Path, label: str) -> bytes:
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
            raise ValueError(f"{label} is missing or a symlink")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            payload = handle.read()
            after_read = os.fstat(handle.fileno())
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ValueError(f"{label} changed during read") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if (
        stat_identity(opened) != stat_identity(after_read)
        or stat_identity(after_read) != stat_identity(current)
    ):
        raise ValueError(f"{label} changed during read")
    return payload


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - SHA256_HEX:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def require_exact_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} is not exact")
    return value


def require_evidence_status(value: Any, label: str) -> str:
    if not isinstance(value, str) or value not in ALLOWED_EVIDENCE_STATES:
        raise ValueError(f"{label} is unsupported")
    return value


def is_supported_route(value: Any) -> bool:
    return isinstance(value, str) and value in SUPPORTED_ROUTES


def require_safe_relative_path(relative: str, label: str) -> Path:
    path = Path(relative)
    if not path.parts or path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError(f"{label} must be a safe relative file path")
    return path


def require_source_file(root: Path, relative: str) -> Path:
    relative_path = require_safe_relative_path(relative, "route support path")
    root = root.resolve(strict=True)
    parent = root
    for part in relative_path.parts[:-1]:
        parent = parent / part
        try:
            value = os.lstat(parent)
        except FileNotFoundError as error:
            raise ValueError(
                f"exact route replay lacks a real non-empty {relative}"
            ) from error
        if stat.S_ISLNK(value.st_mode):
            raise ValueError(f"exact route replay contains a symlink in {relative}")
        if not stat.S_ISDIR(value.st_mode):
            raise ValueError(f"exact route replay lacks a real non-empty {relative}")

    path = parent / relative_path.name
    try:
        value = os.lstat(path)
    except FileNotFoundError as error:
        raise ValueError(f"exact route replay lacks a real non-empty {relative}") from error
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISREG(value.st_mode)
        or path.stat().st_size <= 0
        or not path.resolve(strict=True).is_relative_to(root)
    ):
        raise ValueError(f"exact route replay lacks a real non-empty {relative}")
    return path


def require_exact_check_map(
    value: Any, expected: dict[str, bool], label: str
) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != set(expected)
        or any(
            value.get(name) is not expected_value
            for name, expected_value in expected.items()
        )
    ):
        raise ValueError(f"{label} check map is not exact")


def require_positive_exact_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} is not an exact positive integer")
    return value


def valid_version_id(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and value.lower() not in {"none", "null"}
        and not any(character.isspace() for character in value)
    )


def exact_schema_version(payload: dict[str, Any], expected: int = 1) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def require_real_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a real non-empty file")
    return path.resolve(strict=True)


def require_download_verification(
    verification_path: Path, source_dir: Path, route: str
) -> dict[str, Any]:
    verification, verification_sha256 = load_json_with_sha256(
        verification_path, "download verification"
    )
    rows = verification.get("objects")
    keys = set(verification)
    if (
        not DOWNLOAD_VERIFICATION_REQUIRED_KEYS.issubset(keys)
        or keys - DOWNLOAD_VERIFICATION_REQUIRED_KEYS - DOWNLOAD_VERIFICATION_OPTIONAL_KEYS
    ):
        raise ValueError("download verification envelope is not exact")
    if "recovered_prepared_cutover" in verification and verification.get(
        "recovered_prepared_cutover"
    ) is not True:
        raise ValueError("download verification envelope is not exact")
    if "prior_verification_sha256" in verification:
        require_sha(
            verification.get("prior_verification_sha256"),
            "download verification prior_verification_sha256",
        )
    if "prior_error" in verification:
        require_exact_string(
            verification.get("prior_error"),
            "download verification prior_error",
        )
    publication_receipt_uri = require_exact_string(
        verification.get("publication_receipt_uri"),
        "download verification publication_receipt_uri",
    )
    route_output_uri = require_exact_string(
        verification.get("route_output_uri"),
        "download verification route_output_uri",
    )
    expected_kms_key_arn = require_exact_string(
        verification.get("expected_kms_key_arn"),
        "download verification expected_kms_key_arn",
    )
    require_exact_string(
        verification.get("output_dir"),
        "download verification output_dir",
    )
    if (
        not exact_schema_version(verification)
        or verification.get("status") != "passed"
        or not require_sha(
            verification.get("publication_receipt_sha256"),
            "download verification publication receipt SHA-256",
        )
        or not publication_receipt_uri.startswith("s3://")
        or not route_output_uri.startswith("s3://")
        or not expected_kms_key_arn.startswith("arn:aws:kms:")
        or not isinstance(rows, list)
        or not rows
        or require_positive_exact_int(
            verification.get("object_count"),
            "download verification object_count",
        )
        != len(rows)
    ):
        raise ValueError("download verification is not passed and exact")
    require_exact_check_map(
        verification.get("live_history_checks"),
        EXPECTED_DOWNLOAD_LIVE_HISTORY_CHECKS,
        "download verification live history",
    )

    expected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("download verification contains a malformed row")
        if set(row) != DOWNLOAD_VERIFICATION_OBJECT_KEYS:
            raise ValueError("download verification object row is not exact")
        relative = require_exact_string(
            row.get("relative_path"),
            "download verification relative_path",
        )
        require_safe_relative_path(relative, "download verification path")
        if relative in expected:
            raise ValueError(f"download verification repeats {relative}")
        if not valid_version_id(row.get("version_id")):
            raise ValueError(f"download verification lacks a VersionId for {relative}")
        require_exact_check_map(
            row.get("checks"),
            EXPECTED_DOWNLOAD_OBJECT_CHECKS,
            f"download verification object {relative}",
        )
        expected[relative] = row

    for relative in ("report.md", "report_manifest.json"):
        row = expected.get(relative)
        local = require_source_file(source_dir, relative)
        if (
            row is None
            or type(row.get("bytes")) is not int
            or row.get("bytes") != local.stat().st_size
            or require_sha(
                row.get("sha256"),
                f"download verification {relative} SHA-256",
            )
            != sha256(local)
        ):
            raise ValueError(f"download verification is stale for {relative}")

    manifest, source_report_manifest_sha256 = load_json_with_sha256(
        source_dir / "report_manifest.json", "route report manifest"
    )
    if set(manifest) != REPORT_MANIFEST_KEYS:
        raise ValueError("route report manifest envelope is not exact")
    if (
        not exact_schema_version(manifest)
        or manifest.get("method_id") != route
        or manifest.get("report_kind") != "executable_crosscheck_method"
        or manifest.get("route") != route
        or manifest.get("authorized_hrd_state") != "no_call"
        or manifest.get("classification_authorized") is not False
        or manifest.get("classification_qc_status") != "not_applicable"
        or not isinstance(manifest.get("review_summary"), dict)
        or not manifest["review_summary"]
    ):
        raise ValueError("route report manifest is not an approved no-call cross-check")

    evidence_status = require_evidence_status(
        manifest.get("evidence_status"),
        "route report evidence_status",
    )

    source_report_sha256 = sha256(source_dir / "report.md")
    if (
        require_sha(manifest.get("report_sha256"), "route report_sha256")
        != source_report_sha256
    ):
        raise ValueError("route report manifest hash differs from report.md")

    support = manifest.get("support_sha256")
    source = manifest.get("source_sha256")
    if not isinstance(support, dict) or not support:
        raise ValueError("route report manifest lacks support SHA-256 evidence")
    if not isinstance(source, dict) or not source:
        raise ValueError("route report manifest lacks source SHA-256 evidence")
    for field, values in {"support_sha256": support, "source_sha256": source}.items():
        for key, digest in values.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"route report manifest has a malformed {field} key")
            require_sha(digest, f"{field}.{key}")
    for relative, expected_sha256 in support.items():
        local = require_source_file(source_dir, relative)
        row = expected.get(relative)
        observed_sha256 = sha256(local)
        if (
            row is None
            or type(row.get("bytes")) is not int
            or row.get("bytes") != local.stat().st_size
            or require_sha(
                row.get("sha256"),
                f"download verification support {relative} SHA-256",
            )
            != observed_sha256
        ):
            raise ValueError(f"download verification is stale for support {relative}")
        if expected_sha256 != observed_sha256:
            raise ValueError(
                f"route report manifest support hash differs for {relative}"
            )

    if set(expected) != CORE_REPORT_FILES | set(support):
        raise ValueError(
            "download verification inventory is not exact for the route report packet"
        )

    return {
        "route": route,
        "evidence_status": evidence_status,
        "source_review_summary": manifest["review_summary"],
        "source_object_count": len(rows),
        "download_verification_sha256": verification_sha256,
        "source_report_manifest_sha256": source_report_manifest_sha256,
        "source_report_sha256": source_report_sha256,
    }


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_installed_json(path: Path, expected_sha256: str) -> None:
    path = require_real_file(path, "staged cross-check JSON")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"staged cross-check JSON mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"staged cross-check JSON changed during write: {path}")


def write_json(path: Path, value: dict[str, Any], *, create: bool = False) -> None:
    require_no_symlinked_ancestors(path, "staged cross-check JSON")
    if path.is_symlink():
        raise ValueError(f"staged cross-check JSON may not be a symlink: {path}")
    if create and path.exists():
        raise FileExistsError(f"staged cross-check JSON already exists: {path}")
    if not create:
        require_real_file(path, "staged cross-check JSON")

    data = canonical_json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        os.fchmod(descriptor, 0o600)
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
        require_installed_json(path, expected_sha256)
    except Exception:
        if create and linked:
            path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def copy_file_create_only(source: Path, destination: Path, label: str) -> None:
    source = require_real_file(source, label)
    expected_sha256 = sha256(source)
    destination = require_safe_new_packet(destination, label)
    with source.open("rb") as source_handle:
        try:
            file_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError as error:
            raise ValueError(label + " already exists: " + destination.name) from error

        try:
            destination_handle = os.fdopen(file_descriptor, "wb")
        except Exception:
            os.close(file_descriptor)
            destination.unlink(missing_ok=True)
            raise

        try:
            with destination_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            fsync_directory(destination.parent)
            if (
                sha256(source) != expected_sha256
                or sha256(destination) != expected_sha256
            ):
                raise ValueError(label + " changed during copy: " + source.name)
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def copy_create_only(source: Path, destination: Path) -> None:
    copy_file_create_only(source, destination, "staged cross-check packet")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy_route_file(source_dir: Path, staging: Path, relative: str) -> None:
    destination = staging / require_safe_relative_path(
        relative,
        "route support path",
    )
    require_no_symlinked_ancestors(destination, "exact route replay staging file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    require_no_symlinked_ancestors(destination, "exact route replay staging file")
    copy_file_create_only(
        require_source_file(source_dir, relative),
        destination,
        "exact route replay staging file",
    )


def copy_route_support_files(source_dir: Path, staging: Path) -> None:
    manifest = load_json(staging / "report_manifest.json", "route report manifest")
    support = manifest.get("support_sha256")
    if not isinstance(support, dict):
        return

    for relative in sorted(support):
        if not isinstance(relative, str) or not relative:
            continue
        if relative in CORE_REPORT_FILES:
            raise ValueError(f"route support overlaps a core report file: {relative}")
        copy_route_file(source_dir, staging, relative)


def require_staged_report_manifest(packet_dir: Path) -> None:
    manifest = load_json(
        packet_dir / "report_manifest.json",
        "staged cross-check report manifest",
    )
    method_spec = load_json(
        packet_dir / "method_spec.json",
        "staged cross-check method spec",
    )
    report = require_real_file(packet_dir / "report.md", "staged cross-check report")

    route = manifest.get("route")
    if set(manifest) != REPORT_MANIFEST_KEYS:
        raise ValueError("staged cross-check report manifest envelope is not exact")
    if set(method_spec) != METHOD_SPEC_KEYS:
        raise ValueError("staged cross-check method spec envelope is not exact")
    if (
        not exact_schema_version(manifest)
        or manifest.get("method_id") != route
        or manifest.get("report_kind") != "executable_crosscheck_method"
        or not is_supported_route(route)
        or manifest.get("authorized_hrd_state") != "no_call"
        or manifest.get("classification_authorized") is not False
        or manifest.get("classification_qc_status") != "not_applicable"
        or not isinstance(manifest.get("evidence_status"), str)
        or manifest.get("evidence_status") not in ALLOWED_EVIDENCE_STATES
        or not isinstance(manifest.get("review_summary"), dict)
        or not manifest["review_summary"]
    ):
        raise ValueError("staged cross-check report manifest is not approved")

    if (
        not exact_schema_version(method_spec)
        or method_spec.get("method_id") != route
        or method_spec.get("route") != route
        or method_spec.get("report_kind") != "executable_crosscheck_method"
        or method_spec.get("evidence_status") != manifest.get("evidence_status")
        or method_spec.get("authorized_hrd_state") != "no_call"
        or method_spec.get("classification_authorized") is not False
        or method_spec.get("classification_qc_status") != "not_applicable"
        or not require_positive_exact_int(
            method_spec.get("source_object_count"),
            "staged cross-check method spec source_object_count",
        )
        or method_spec.get("source_review_summary") != manifest.get("review_summary")
    ):
        raise ValueError("staged cross-check method spec differs from the manifest")

    support = manifest.get("support_sha256")
    if not isinstance(support, dict) or set(support) != {"method_spec.json"}:
        raise ValueError("staged cross-check report manifest support is not exact")

    expected_method_spec_sha256 = require_sha(
        support.get("method_spec.json"),
        "staged cross-check method_spec.json SHA-256",
    )
    if sha256(packet_dir / "method_spec.json") != expected_method_spec_sha256:
        raise ValueError(
            "staged cross-check report manifest hash differs for method_spec.json"
        )

    expected_report_sha256 = require_sha(
        manifest.get("report_sha256"),
        "staged cross-check report SHA-256",
    )
    if sha256(report) != expected_report_sha256:
        raise ValueError("staged cross-check report manifest hash differs for report.md")

    source = manifest.get("source_sha256")
    if (
        not isinstance(source, dict)
        or set(source)
        != {"download_verification", "source_report", "source_report_manifest"}
    ):
        raise ValueError("staged cross-check report manifest source hashes are not exact")
    for key, digest in source.items():
        require_sha(digest, f"staged cross-check source SHA-256 {key}")
    expected_source = {
        "download_verification": require_sha(
            method_spec.get("download_verification_sha256"),
            "staged cross-check method spec download verification SHA-256",
        ),
        "source_report": require_sha(
            method_spec.get("source_report_sha256"),
            "staged cross-check method spec source report SHA-256",
        ),
        "source_report_manifest": require_sha(
            method_spec.get("source_report_manifest_sha256"),
            "staged cross-check method spec source report manifest SHA-256",
        ),
    }
    if source != expected_source:
        raise ValueError(
            "staged cross-check method spec source hashes differ from the manifest"
        )


def install_staged_packet(staging: Path, output_dir: Path) -> None:
    try:
        output_dir.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ValueError(f"output already exists: {output_dir}") from error

    expected_hashes: dict[Path, str] = {}
    installed: list[Path] = []
    try:
        for name in ("method_spec.json", "report.md", "report_manifest.json"):
            staged = staging / name
            destination = output_dir / name
            expected_hashes[destination] = sha256(
                require_real_file(staged, "staged cross-check packet")
            )
            destination_preexisted = destination.exists() or destination.is_symlink()
            try:
                copy_create_only(staged, destination)
            except Exception:
                if not destination_preexisted:
                    installed.append(destination)
                raise
            installed.append(destination)
        fsync_directory(output_dir)
        for path, expected_sha256 in expected_hashes.items():
            if (
                sha256(require_real_file(path, "installed cross-check packet"))
                != expected_sha256
            ):
                raise ValueError(
                    "staged cross-check packet changed during install: " + path.name
                )
        require_staged_report_manifest(output_dir)
    except Exception:
        for path in reversed(installed):
            path.unlink(missing_ok=True)
        with suppress(OSError):
            output_dir.rmdir()
        raise


def resolve_real_source_dir(source_dir: Path) -> Path:
    require_no_symlinked_ancestors(source_dir, "exact route replay")
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("exact route replay must be a real directory")
    return source_dir.resolve()


def resolve_new_output_dir(output_dir: Path) -> Path:
    if output_dir.is_symlink():
        raise ValueError("output may not be a symlink")
    require_no_symlinked_ancestors(output_dir, "output")
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise ValueError(f"output already exists: {output_dir}")
    return output_dir


def require_safe_new_packet(path: Path, label: str = "staged cross-check packet") -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink():
        raise ValueError(label + " may not be a symlink: " + path.name)
    if path.exists():
        raise ValueError(label + " already exists: " + path.name)
    return path.resolve()


def stage(source_dir: Path, verification_path: Path, output_dir: Path, route: str) -> None:
    if route not in SUPPORTED_ROUTES:
        raise ValueError(f"unsupported executable cross-check route: {route}")
    source_dir = resolve_real_source_dir(source_dir)
    output_dir = resolve_new_output_dir(output_dir)
    if (
        source_dir == output_dir
        or source_dir.is_relative_to(output_dir)
        or output_dir.is_relative_to(source_dir)
    ):
        raise ValueError("output must be separate from the exact route replay")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary:
        staging = Path(temporary)
        copy_route_file(source_dir, staging, "report.md")
        copy_route_file(source_dir, staging, "report_manifest.json")
        copy_route_support_files(source_dir, staging)
        summary = require_download_verification(verification_path, staging, route)
        method_spec = {
            "schema_version": 1,
            "method_id": route,
            "route": route,
            "report_kind": "executable_crosscheck_method",
            "evidence_status": summary["evidence_status"],
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "source_object_count": summary["source_object_count"],
            "source_report_manifest_sha256": summary[
                "source_report_manifest_sha256"
            ],
            "source_report_sha256": summary["source_report_sha256"],
            "download_verification_sha256": summary[
                "download_verification_sha256"
            ],
            "source_review_summary": summary["source_review_summary"],
        }
        write_json(staging / "method_spec.json", method_spec, create=True)

        manifest = {
            "schema_version": 1,
            "method_id": route,
            "report_kind": "executable_crosscheck_method",
            "route": route,
            "evidence_status": summary["evidence_status"],
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "review_summary": summary["source_review_summary"],
            "source_sha256": {
                "download_verification": summary["download_verification_sha256"],
                "source_report": summary["source_report_sha256"],
                "source_report_manifest": summary[
                    "source_report_manifest_sha256"
                ],
            },
            "support_sha256": {
                "method_spec.json": sha256(staging / "method_spec.json"),
            },
            "report_sha256": sha256(staging / "report.md"),
        }
        write_json(staging / "report_manifest.json", manifest)
        install_staged_packet(staging, output_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--download-verification", required=True, type=Path)
    parser.add_argument("--route", required=True, choices=sorted(SUPPORTED_ROUTES))
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    stage(args.source_dir, args.download_verification, args.output_dir, args.route)
    print(json.dumps({"status": "passed", "output": str(args.output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
