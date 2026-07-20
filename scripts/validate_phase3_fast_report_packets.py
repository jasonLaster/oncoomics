#!/usr/bin/env python3
"""Validate Phase 3 fast HRD report packets before freeze/review handoff."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from forbidden_text import DEFAULT_FORBIDDEN_TOKENS, normalize_forbidden_tokens_json
from generate_blocked_hrd_crosscheck_reports import (
    BLOCKED_REVIEW_SUMMARY_KEYS,
    METHODS_BY_ID,
    PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE,
    PRE_ROUTE_SOURCE_REPORT_METHOD_IDS,
    render_report as render_blocked_report,
)
from hrd_report_inventory import BLOCKED_CROSSCHECK_METHOD_IDS
from publish_private_report import canonical_packet_digest, require_real_packet_dir
from publish_reviewed_public_report import (
    MAX_FILE_BYTES,
    MAX_PACKET_BYTES,
    METHOD_CONTRACTS,
    checked_final_source_artifact_id,
    load_json,
    scan_no_call_language,
    scan_text,
    sha256,
    validate_report_manifest_support,
)
from runbook_io import (
    load_json_object,
    read_stable_file,
    require_safe_output_path,
    sha256_bytes,
)

FORBIDDEN_TOKENS = DEFAULT_FORBIDDEN_TOKENS

PACKET_ARG_TO_METHOD = (
    ("deterministic_report_dir", "deterministic_full_wgs"),
    ("rosalind_report_dir", "rosalind_diana_wgs"),
    ("facets_scarhrd_report_dir", "facets_scarhrd_blocked"),
    ("oncoanalyser_chord_report_dir", "oncoanalyser_chord_blocked"),
    ("hrdetect_report_dir", "hrdetect_blocked"),
)
PHASE3_FAST_VALIDATED_METHOD_IDS = tuple(method_id for _, method_id in PACKET_ARG_TO_METHOD)
PHASE3_FAST_REPORT_KINDS: dict[str, tuple[str, ...]] = {
    method_id: (METHOD_CONTRACTS[method_id]["report_kind"],)
    for method_id in PHASE3_FAST_VALIDATED_METHOD_IDS
}
PHASE3_FAST_REPORT_KINDS["deterministic_full_wgs"] = (
    "phase3_fast_deterministic_evidence",
    "deterministic_baseline",
)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
SHA256_B64 = re.compile(r"^[A-Za-z0-9+/]{43}=$")
VALIDATION_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "validated_packet_count",
    "static_forbidden_token_count",
    "run_forbidden_token_count",
    "forbidden_token_count",
    "forbidden_tokens_sha256",
    "packets",
}
VALIDATION_RECEIPT_PACKET_KEYS = {
    "method_id",
    "file_count",
    "total_bytes",
    "packet_sha256",
    "files",
}


def serializable_packet_row(row: Mapping[str, Any]) -> dict[str, Any]:
    relative_path = row.get("relative_path")
    size = row.get("bytes")
    sha256 = row.get("sha256")
    checksum = row.get("checksum_sha256")
    if (
        not isinstance(relative_path, str)
        or not relative_path.strip()
        or Path(relative_path).is_absolute()
        or ".." in Path(relative_path).parts
        or type(size) is not int
        or size < 1
        or not isinstance(sha256, str)
        or not SHA256_HEX.fullmatch(sha256)
        or not isinstance(checksum, str)
        or not SHA256_B64.fullmatch(checksum)
        or checksum != checksum_sha256(sha256)
    ):
        raise ValueError("generated report packet file row is malformed")
    return {
        "relative_path": relative_path,
        "bytes": size,
        "sha256": sha256,
        "checksum_sha256": checksum,
    }


def serializable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [serializable_packet_row(row) for row in rows]


def sha256_forbidden_tokens(tokens: tuple[str, ...]) -> str:
    payload = json.dumps(
        list(tokens),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def validate_report_packet(
    paths: dict[str, Path],
    method_id: str,
    expected: tuple[str, ...],
) -> dict[str, Any]:
    manifest = load_json(paths["report_manifest.json"], "report manifest")
    if manifest.get("report_kind") not in PHASE3_FAST_REPORT_KINDS[method_id]:
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


def validate_packet_dir(
    packet_dir: Path,
    method_id: str,
    tokens: tuple[str, ...],
) -> list[dict[str, Any]]:
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


def sha256_file(path: Path) -> str:
    return sha256_bytes(read_stable_file(path, f"{path.name} SHA-256 input"))


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"report packet validation receipt {label} is malformed")
    return value


def exact_schema_version(payload: dict[str, Any], expected: int = 1) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def canonical_forbidden_tokens(forbidden_tokens_json: str) -> tuple[str, ...]:
    run_tokens = tuple(normalize_forbidden_tokens_json(forbidden_tokens_json))
    return tuple(sorted({*FORBIDDEN_TOKENS, *run_tokens}, key=str.casefold))


def expected_forbidden_tokens_sha256(forbidden_tokens_json: str) -> str:
    return sha256_forbidden_tokens(canonical_forbidden_tokens(forbidden_tokens_json))


def validate_forbidden_token_inventory(
    payload: Mapping[str, Any],
    expected_sha256: str | None = None,
) -> None:
    static_count = require_int(payload.get("static_forbidden_token_count"), "static forbidden-token count")
    run_count = require_int(payload.get("run_forbidden_token_count"), "run forbidden-token count")
    total_count = require_int(payload.get("forbidden_token_count"), "forbidden-token count")
    observed_sha256 = payload.get("forbidden_tokens_sha256")

    if static_count != len(FORBIDDEN_TOKENS):
        raise ValueError("report packet validation receipt static forbidden-token count is malformed")
    if run_count < 1:
        raise ValueError("report packet validation receipt must include run forbidden-token coverage")
    if total_count < max(static_count, run_count) or total_count > static_count + run_count:
        raise ValueError("report packet validation receipt forbidden-token union count is malformed")
    if expected_sha256 is not None and observed_sha256 != expected_sha256:
        raise ValueError("report packet validation receipt forbidden-token digest does not match current run")


def validate_file_rows(packet: Mapping[str, Any], packet_sha256: str) -> None:
    file_count = require_int(packet.get("file_count"), "file count")
    total_bytes = require_int(packet.get("total_bytes"), "total bytes")
    files = packet.get("files")
    if file_count < 1 or total_bytes < 1 or not isinstance(files, list) or len(files) != file_count:
        raise ValueError("report packet validation receipt packet file summary is malformed")

    observed_bytes = 0
    observed_paths: set[str] = set()
    for file_row in files:
        if not isinstance(file_row, dict) or set(file_row) != {"relative_path", "bytes", "sha256", "checksum_sha256"}:
            raise ValueError("report packet validation receipt file rows are malformed")
        relative_path = file_row.get("relative_path")
        size = require_int(file_row.get("bytes"), "file bytes")
        sha256 = file_row.get("sha256")
        checksum = file_row.get("checksum_sha256")
        if (
            not isinstance(relative_path, str)
            or not relative_path.strip()
            or Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
        ):
            raise ValueError("report packet validation receipt file rows are malformed")
        if relative_path in observed_paths:
            raise ValueError("report packet validation receipt file rows are malformed")
        observed_paths.add(relative_path)
        if size < 1 or not isinstance(sha256, str) or not SHA256_HEX.fullmatch(sha256):
            raise ValueError("report packet validation receipt file rows are malformed")
        if not isinstance(checksum, str) or not SHA256_B64.fullmatch(checksum) or checksum != checksum_sha256(sha256):
            raise ValueError("report packet validation receipt file rows are malformed")
        observed_bytes += size

    if observed_bytes != total_bytes:
        raise ValueError("report packet validation receipt packet byte summary is malformed")
    if canonical_packet_digest(files) != packet_sha256:
        raise ValueError("report packet validation receipt packet digest summary is malformed")


def require_validation_receipt_packet_sha256s(
    payload: Any,
    expected_forbidden_tokens_sha256: str | None = None,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("report packet validation receipt must be a JSON object")
    packets = payload.get("packets")
    if (
        not exact_schema_version(payload)
        or payload.get("status") != "passed"
        or set(payload) != VALIDATION_RECEIPT_KEYS
        or require_int(
            payload.get("validated_packet_count"),
            "validated packet count",
        ) != len(PHASE3_FAST_VALIDATED_METHOD_IDS)
        or not isinstance(packets, list)
        or len(packets) != len(PHASE3_FAST_VALIDATED_METHOD_IDS)
        or not isinstance(payload.get("forbidden_tokens_sha256"), str)
        or not SHA256_HEX.fullmatch(payload.get("forbidden_tokens_sha256", ""))
    ):
        raise ValueError("report packet validation receipt is malformed")

    validate_forbidden_token_inventory(payload, expected_forbidden_tokens_sha256)

    packet_sha256s: dict[str, str] = {}
    for expected_method_id, packet in zip(PHASE3_FAST_VALIDATED_METHOD_IDS, packets):
        if (
            not isinstance(packet, dict)
            or set(packet) != VALIDATION_RECEIPT_PACKET_KEYS
        ):
            raise ValueError("report packet validation receipt packet rows must be objects")
        method_id = packet.get("method_id")
        digest = packet.get("packet_sha256")
        if method_id != expected_method_id or not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest):
            raise ValueError("report packet validation receipt packet revisions are malformed")
        validate_file_rows(packet, digest)
        packet_sha256s[method_id] = digest
    return packet_sha256s


def load_validation_receipt_packet_sha256s(
    path: Path,
    expected_forbidden_tokens_sha256: str | None = None,
) -> dict[str, str]:
    return require_validation_receipt_packet_sha256s(
        load_json_object(path, "report packet validation receipt"),
        expected_forbidden_tokens_sha256,
    )


def validate_validation_receipt_matches_packets(
    path: Path,
    packet_dirs: Mapping[str, Path],
    forbidden_tokens: tuple[str, ...],
    expected_forbidden_tokens_sha256: str | None = None,
    method_ids: tuple[str, ...] = PHASE3_FAST_VALIDATED_METHOD_IDS,
) -> None:
    observed = load_validation_receipt_packet_sha256s(
        path,
        expected_forbidden_tokens_sha256,
    )
    unexpected = sorted(set(method_ids) - set(PHASE3_FAST_VALIDATED_METHOD_IDS))
    if unexpected:
        raise ValueError(
            "unexpected Phase 3 fast validation methods: " + ", ".join(unexpected)
        )

    expected = {}
    for method_id in method_ids:
        rows = validate_packet_dir(packet_dirs[method_id], method_id, forbidden_tokens)
        expected[method_id] = canonical_packet_digest(rows)
    observed_subset = {method_id: observed.get(method_id, "") for method_id in method_ids}
    if observed_subset != expected:
        raise ValueError("report packet validation receipt does not match current packets")


def load_packet_json(packet_dir: Path, name: str, label: str) -> dict[str, Any]:
    return load_json_object(packet_dir / name, label)


def pre_route_source_report_manifests(
    packet_dirs: Mapping[str, Path],
) -> dict[str, str]:
    manifests: dict[str, str] = {}
    for method_id in PRE_ROUTE_SOURCE_REPORT_METHOD_IDS:
        manifest_path = packet_dirs[method_id] / "report_manifest.json"
        manifests[method_id] = sha256_file(manifest_path)
    return manifests


def validate_pre_route_blocked_packet(
    packet_dir: Path,
    method_id: str,
    expected_source_report_manifests: Mapping[str, str],
) -> None:
    manifest = load_packet_json(
        packet_dir,
        "report_manifest.json",
        f"{method_id} blocked report manifest",
    )
    method_spec = load_packet_json(
        packet_dir,
        "method_spec.json",
        f"{method_id} blocked method spec",
    )
    review_summary = manifest.get("review_summary")
    source_sha256 = manifest.get("source_sha256")
    method_spec_manifests = method_spec.get("source_report_manifests")
    review_summary_manifests = (
        review_summary.get("source_report_manifests")
        if isinstance(review_summary, dict)
        else None
    )
    source_report_manifests_from_sha256 = (
        {
            key.removesuffix("_report_manifest"): value
            for key, value in source_sha256.items()
            if isinstance(key, str) and key.endswith("_report_manifest")
        }
        if isinstance(source_sha256, dict)
        else {}
    )
    expected_source_sha256 = {
        "generator": sha256_file(
            Path(__file__).with_name("generate_blocked_hrd_crosscheck_reports.py")
        ),
        **{
            f"{source_method_id}_report_manifest": digest
            for source_method_id, digest in expected_source_report_manifests.items()
        },
    }
    if (
        method_spec.get("source_report_binding_scope")
        != PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE
        or manifest.get("source_report_binding_scope")
        != PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE
        or not isinstance(review_summary, dict)
        or set(review_summary) != BLOCKED_REVIEW_SUMMARY_KEYS
        or review_summary.get("source_report_binding_scope")
        != PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE
        or not isinstance(method_spec_manifests, dict)
        or tuple(method_spec_manifests) != PRE_ROUTE_SOURCE_REPORT_METHOD_IDS
        or not isinstance(review_summary_manifests, dict)
        or tuple(review_summary_manifests) != PRE_ROUTE_SOURCE_REPORT_METHOD_IDS
        or tuple(source_report_manifests_from_sha256)
        != PRE_ROUTE_SOURCE_REPORT_METHOD_IDS
        or not isinstance(source_sha256, dict)
        or dict(expected_source_report_manifests) != method_spec_manifests
        or source_sha256 != expected_source_sha256
        or source_report_manifests_from_sha256 != method_spec_manifests
        or source_report_manifests_from_sha256 != review_summary_manifests
    ):
        raise ValueError(
            f"{method_id} blocked packet must use "
            f"{PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE} source binding"
        )
    validate_pre_route_blocked_report(
        packet_dir,
        method_id,
        manifest,
        expected_source_report_manifests,
    )


def validate_pre_route_blocked_report(
    packet_dir: Path,
    method_id: str,
    manifest: Mapping[str, Any],
    source_report_manifests: Mapping[str, str],
) -> None:
    method = METHODS_BY_ID.get(method_id)
    generated_at = manifest.get("generated_at")
    run_id = manifest.get("run_id")
    source_report_binding_scope = manifest.get("source_report_binding_scope")
    if (
        method is None
        or not isinstance(generated_at, str)
        or not generated_at
        or not isinstance(run_id, str)
        or source_report_binding_scope != PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE
    ):
        raise ValueError(f"{method_id} blocked report inputs are not exact")

    report_path = packet_dir / "report.md"
    try:
        report_text = read_stable_file(
            report_path,
            f"{method_id} blocked report.md",
        ).decode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"{method_id} blocked report.md is not UTF-8") from error

    expected = render_blocked_report(
        method,
        generated_at,
        run_id=run_id,
        source_report_manifests=source_report_manifests,
        source_report_binding_scope=source_report_binding_scope,
    )
    if report_text != expected:
        raise ValueError(f"{method_id} blocked report is stale")


def validate_packets(
    packet_dirs: Mapping[str, Path],
    forbidden_tokens_json: str,
) -> dict[str, Any]:
    missing = [method_id for _, method_id in PACKET_ARG_TO_METHOD if method_id not in packet_dirs]
    if missing:
        raise ValueError(f"missing required packet dirs: {', '.join(missing)}")

    run_tokens = tuple(normalize_forbidden_tokens_json(forbidden_tokens_json))
    forbidden_tokens = canonical_forbidden_tokens(forbidden_tokens_json)
    expected_pre_route_source_report_manifests: dict[str, str] | None = None

    packets = []
    for _, method_id in PACKET_ARG_TO_METHOD:
        rows = validate_packet_dir(packet_dirs[method_id], method_id, forbidden_tokens)
        serialized_rows = serializable_rows(rows)
        if method_id in BLOCKED_CROSSCHECK_METHOD_IDS:
            if expected_pre_route_source_report_manifests is None:
                expected_pre_route_source_report_manifests = (
                    pre_route_source_report_manifests(packet_dirs)
                )
            validate_pre_route_blocked_packet(
                packet_dirs[method_id],
                method_id,
                expected_pre_route_source_report_manifests,
            )
        packets.append(
            {
                "method_id": method_id,
                "file_count": len(serialized_rows),
                "total_bytes": sum(row["bytes"] for row in serialized_rows),
                "packet_sha256": canonical_packet_digest(serialized_rows),
                "files": serialized_rows,
            }
        )

    return {
        "schema_version": 1,
        "status": "passed",
        "validated_packet_count": len(packets),
        "static_forbidden_token_count": len(FORBIDDEN_TOKENS),
        "run_forbidden_token_count": len(run_tokens),
        "forbidden_token_count": len(forbidden_tokens),
        "forbidden_tokens_sha256": sha256_forbidden_tokens(forbidden_tokens),
        "packets": packets,
    }


def write_json_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "packet validation output", ValueError)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    expected_sha256 = hashlib.sha256(data.encode("utf-8")).hexdigest()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
            require_installed_output(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_installed_output(path: Path, expected_sha256: str) -> None:
    require_safe_output_path(path, "packet validation output", ValueError)
    if path.is_symlink() or not path.is_file():
        raise ValueError("report packet validation output changed during write")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError("report packet validation output mode changed during write")
    if sha256_file(path) != expected_sha256:
        raise ValueError("report packet validation output changed during write")


def run(args: argparse.Namespace) -> dict[str, Any]:
    packet_dirs = {method_id: getattr(args, argument) for argument, method_id in PACKET_ARG_TO_METHOD}
    receipt = validate_packets(packet_dirs, args.forbidden_tokens_json)
    write_json_create_only(args.output, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 3 fast deterministic, Rosalind, and blocked HRD report packets.")
    parser.add_argument("--deterministic-report-dir", required=True, type=Path)
    parser.add_argument("--rosalind-report-dir", required=True, type=Path)
    parser.add_argument("--facets-scarhrd-report-dir", required=True, type=Path)
    parser.add_argument("--oncoanalyser-chord-report-dir", required=True, type=Path)
    parser.add_argument("--hrdetect-report-dir", required=True, type=Path)
    parser.add_argument("--forbidden-tokens-json", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        receipt = run(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "validated_packet_count": receipt["validated_packet_count"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
