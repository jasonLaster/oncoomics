from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import (
    CALLER_RESOURCES,
    HEX64,
    ManifestError,
    _require_s3_uri,
    normalize_method_parameters,
)
from .replicate_phase3_fast_inputs import EXPECTED_REPLICATION_OBJECTS

DEFAULT_INPUT = "manifests/phase3_wgs_fast/replication_receipt.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/cache_manifest.json"

BAM_CACHE_ARTIFACTS = ("normal.bai", "normal.bam", "tumor.bai", "tumor.bam")
REFERENCE_CACHE_ARTIFACTS = ("reference.dict", "reference.fa", "reference.fa.fai")
REQUIRED_DESTINATION_CHECKS = (
    "destination_kms_key_bound",
    "destination_kms_key_matches",
    "destination_metadata_matches",
    "destination_size_matches",
    "destination_uri_content_addressed",
    "destination_versioned",
    "source_copy_version_bound",
    "source_version_id_bound",
)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_list(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be a list")
    return [_require_mapping(row, f"{label} row") for row in value]


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    return value


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} must be 64 hex characters")
    return value.lower()


def _require_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{label} bytes must be a positive integer")
    return value


def _require_version_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or value in {"", "null", "None"}:
        raise ManifestError(f"{label} must be a durable VersionId")
    return value


def _receipt_rows(value: Any) -> list[Mapping[str, Any]]:
    rows = _require_list(value, "copy_results")
    if len(rows) != EXPECTED_REPLICATION_OBJECTS:
        raise ManifestError(f"copy_results must contain {EXPECTED_REPLICATION_OBJECTS} objects")
    return rows


def _require_ready_copy(row: Mapping[str, Any]) -> dict[str, Any]:
    artifact = _require_string(row.get("artifact"), "copy result artifact")
    if row.get("status") not in {"already_present", "copied"}:
        raise ManifestError(f"{artifact} must be copied or already_present")

    checks = _require_mapping(row.get("checks"), f"{artifact} checks")
    for check in REQUIRED_DESTINATION_CHECKS:
        if checks.get(check) is not True:
            raise ManifestError(f"{artifact} check {check} must be true")
    if row.get("status") == "copied" and checks.get("copy_response_version_matches") is not True:
        raise ManifestError(f"{artifact} copied row must bind the copy response VersionId")

    destination = _require_mapping(
        _require_mapping(row.get("copy_strategy"), f"{artifact} copy_strategy").get("destination"),
        f"{artifact} destination",
    )
    bucket = _require_string(destination.get("bucket"), f"{artifact} destination bucket")
    key = _require_string(destination.get("key"), f"{artifact} destination key")
    uri = f"s3://{bucket}/{key}"
    if _require_s3_uri(row.get("destination_uri"), f"{artifact} destination_uri") != uri:
        raise ManifestError(f"{artifact} destination_uri must match copy_strategy destination")

    result = {
        "artifact": artifact,
        "bytes": _require_positive_int(row.get("bytes"), artifact),
        "copy_method": _require_string(
            _require_mapping(row.get("copy_strategy"), f"{artifact} copy_strategy").get("method"),
            f"{artifact} copy method",
        ),
        "sha256": _require_hex(row.get("sha256"), f"{artifact} sha256"),
        "source_uri": _require_s3_uri(row.get("source_uri"), f"{artifact} source_uri"),
        "source_version_id": _require_version_id(row.get("source_version_id"), f"{artifact} source_version_id"),
        "status": str(row["status"]),
        "uri": uri,
        "version_id": _require_version_id(row.get("destination_version_id"), f"{artifact} destination_version_id"),
    }
    for key in ("role", "sample_id"):
        if key in row:
            result[key] = _require_string(row.get(key), f"{artifact} {key}")
    return result


def _index_by_artifact(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    by_artifact: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        artifact = _require_string(row.get("artifact"), "cache artifact")
        if artifact in by_artifact:
            raise ManifestError(f"cache manifest contains duplicate artifact {artifact}")
        by_artifact[artifact] = row

    expected = set(BAM_CACHE_ARTIFACTS) | set(REFERENCE_CACHE_ARTIFACTS) | set(CALLER_RESOURCES)
    actual = set(by_artifact)
    if actual != expected:
        raise ManifestError(
            f"cache manifest expected exact artifacts {sorted(expected)}, "
            f"found missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    return by_artifact


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_phase3_fast_cache_manifest(
    replication_receipt: Mapping[str, Any],
    *,
    replication_receipt_sha256: str,
) -> dict[str, Any]:
    if replication_receipt.get("manifest_type") != "phase3_wgs_fast_replication_receipt":
        raise ManifestError("replication receipt manifest_type must be phase3_wgs_fast_replication_receipt")
    if replication_receipt.get("status") != "applied":
        raise ManifestError("replication receipt status must be applied")
    if replication_receipt.get("mode") != "apply":
        raise ManifestError("replication receipt mode must be apply")
    if _require_mapping(replication_receipt.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("cache manifest authorized_hrd_state must remain no_call")

    rows = [_require_ready_copy(row) for row in _receipt_rows(replication_receipt.get("copy_results"))]
    by_artifact = _index_by_artifact(rows)

    object_count = len(rows)
    total_bytes = sum(int(row["bytes"]) for row in rows)
    if replication_receipt.get("object_count") != object_count:
        raise ManifestError("replication receipt object_count does not match copy_results")
    if replication_receipt.get("total_bytes") != total_bytes:
        raise ManifestError("replication receipt total_bytes does not match copy_results")

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_cache_manifest",
        "status": "ready",
        "workflow": dict(_require_mapping(replication_receipt.get("workflow"), "workflow")),
        "run": dict(_require_mapping(replication_receipt.get("run"), "run")),
        "runtime": dict(_require_mapping(replication_receipt.get("runtime"), "runtime")),
        "method_parameters": normalize_method_parameters(replication_receipt.get("method_parameters")),
        "cache": dict(_require_mapping(replication_receipt.get("cache"), "cache")),
        "source": {
            "input_manifest_sha256": _require_hex(
                _require_mapping(replication_receipt.get("source"), "source").get("input_manifest_sha256"),
                "input_manifest_sha256",
            ),
            "replication_plan_sha256": _require_hex(
                _require_mapping(replication_receipt.get("source"), "source").get("replication_plan_sha256"),
                "replication_plan_sha256",
            ),
            "replication_receipt_sha256": _require_hex(replication_receipt_sha256, "replication_receipt_sha256"),
        },
        "bam_pair": {
            "tumor": {
                "bam": by_artifact["tumor.bam"],
                "bai": by_artifact["tumor.bai"],
            },
            "normal": {
                "bam": by_artifact["normal.bam"],
                "bai": by_artifact["normal.bai"],
            },
        },
        "reference": {
            "fasta": by_artifact["reference.fa"],
            "fai": by_artifact["reference.fa.fai"],
            "sequence_dictionary": by_artifact["reference.dict"],
        },
        "caller_resources": {
            artifact: by_artifact[artifact]
            for artifact in sorted(CALLER_RESOURCES)
        },
        "object_count": object_count,
        "total_bytes": total_bytes,
        "interpretation": {
            "authorized_hrd_state": "no_call",
        },
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest_from_environment() -> tuple[dict[str, Any], Path]:
    receipt_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_REPLICATION_RECEIPT", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_CACHE_MANIFEST_OUTPUT", DEFAULT_OUTPUT))
    manifest = build_phase3_fast_cache_manifest(
        read_json(receipt_path),
        replication_receipt_sha256=_sha256_path(receipt_path),
    )
    return manifest, output_path


def main() -> None:
    manifest, output = load_manifest_from_environment()
    write_manifest(output, manifest)
    print(f"Phase 3 WGS fast cache manifest written: {output}")


if __name__ == "__main__":
    main()
