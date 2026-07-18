#!/usr/bin/env python3
"""Validate Phase 3 fast HRD report packets before freeze/review handoff."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from publish_private_report import canonical_packet_digest, validate_packet_dir
from render_ai_synthesis_runbook import FORBIDDEN_TOKENS

from diana_omics.commands.phase3_wgs.validate_phase3_fast_forbidden_tokens import (
    normalize_forbidden_tokens,
)

PACKET_ARG_TO_METHOD = (
    ("deterministic_report_dir", "deterministic_full_wgs"),
    ("rosalind_report_dir", "rosalind_diana_wgs"),
    ("facets_scarhrd_report_dir", "facets_scarhrd_blocked"),
    ("oncoanalyser_chord_report_dir", "oncoanalyser_chord_blocked"),
    ("hrdetect_report_dir", "hrdetect_blocked"),
)
PHASE3_FAST_VALIDATED_METHOD_IDS = tuple(method_id for _, method_id in PACKET_ARG_TO_METHOD)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
SHA256_B64 = re.compile(r"^[A-Za-z0-9+/]{43}=$")


def serializable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": str(row["relative_path"]),
            "bytes": int(row["bytes"]),
            "sha256": str(row["sha256"]),
            "checksum_sha256": str(row["checksum_sha256"]),
        }
        for row in rows
    ]


def sha256_forbidden_tokens(tokens: tuple[str, ...]) -> str:
    payload = json.dumps(
        list(tokens),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def require_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"report packet validation receipt {label} is malformed")
    return value


def canonical_forbidden_tokens(forbidden_tokens_json: str) -> tuple[str, ...]:
    run_tokens = tuple(normalize_forbidden_tokens(forbidden_tokens_json))
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
        payload.get("schema_version") != 1
        or payload.get("status") != "passed"
        or payload.get("validated_packet_count") != len(PHASE3_FAST_VALIDATED_METHOD_IDS)
        or not isinstance(packets, list)
        or len(packets) != len(PHASE3_FAST_VALIDATED_METHOD_IDS)
        or not isinstance(payload.get("forbidden_tokens_sha256"), str)
        or not SHA256_HEX.fullmatch(payload.get("forbidden_tokens_sha256", ""))
    ):
        raise ValueError("report packet validation receipt is malformed")

    validate_forbidden_token_inventory(payload, expected_forbidden_tokens_sha256)

    packet_sha256s: dict[str, str] = {}
    for expected_method_id, packet in zip(PHASE3_FAST_VALIDATED_METHOD_IDS, packets):
        if not isinstance(packet, dict):
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
    if path.is_symlink() or not path.is_file():
        raise ValueError("report packet validation receipt must be a real file")
    return require_validation_receipt_packet_sha256s(
        json.loads(path.read_text(encoding="utf-8")),
        expected_forbidden_tokens_sha256,
    )


def validate_validation_receipt_matches_packets(
    path: Path,
    packet_dirs: Mapping[str, Path],
    forbidden_tokens: tuple[str, ...],
    expected_forbidden_tokens_sha256: str | None = None,
) -> None:
    observed = load_validation_receipt_packet_sha256s(
        path,
        expected_forbidden_tokens_sha256,
    )
    expected = {}
    for method_id in PHASE3_FAST_VALIDATED_METHOD_IDS:
        rows = validate_packet_dir(packet_dirs[method_id], method_id, forbidden_tokens)
        expected[method_id] = canonical_packet_digest(rows)
    if observed != expected:
        raise ValueError("report packet validation receipt does not match current packets")


def validate_packets(
    packet_dirs: Mapping[str, Path],
    forbidden_tokens_json: str,
) -> dict[str, Any]:
    missing = [method_id for _, method_id in PACKET_ARG_TO_METHOD if method_id not in packet_dirs]
    if missing:
        raise ValueError(f"missing required packet dirs: {', '.join(missing)}")

    run_tokens = tuple(normalize_forbidden_tokens(forbidden_tokens_json))
    forbidden_tokens = canonical_forbidden_tokens(forbidden_tokens_json)

    packets = []
    for _, method_id in PACKET_ARG_TO_METHOD:
        rows = validate_packet_dir(packet_dirs[method_id], method_id, forbidden_tokens)
        packets.append(
            {
                "method_id": method_id,
                "file_count": len(rows),
                "total_bytes": sum(int(row["bytes"]) for row in rows),
                "packet_sha256": canonical_packet_digest(rows),
                "files": serializable_rows(rows),
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
    if path.is_symlink():
        raise ValueError("packet validation output must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


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
