from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError, _require_s3_uri

DEFAULT_INPUT = "manifests/phase3_wgs_fast/input_manifest.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/replication_plan.json"
KMS_KEY_ARN = re.compile(r"^arn:aws:kms:([a-z]{2}-[a-z]+-\d):(\d{12}):key/[A-Za-z0-9-]+$")
REGION = re.compile(r"^[a-z]{2}-[a-z]+-\d$")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


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


def _require_version(value: Any, label: str) -> str:
    if not isinstance(value, str) or value in {"", "null", "None"}:
        raise ManifestError(f"{label} version_id must be a non-null S3 VersionId")
    return value


def _require_region(value: Any, label: str) -> str:
    if not isinstance(value, str) or REGION.fullmatch(value) is None:
        raise ManifestError(f"{label} must be an AWS region")
    return value


def _require_kms_key_arn(value: Any, *, region: str, label: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{label} must be a KMS key ARN in {region}")
    match = KMS_KEY_ARN.fullmatch(value)
    if match is None or match.group(1) != region:
        raise ManifestError(f"{label} must be a KMS key ARN in {region}")
    return value


def _normalize_cache_prefix(prefix: str) -> str:
    normalized = prefix.strip().rstrip("/")
    _require_s3_uri(normalized, "PHASE3_WGS_FAST_CACHE_PREFIX")
    return normalized


def _basename_from_s3_uri(uri: str) -> str:
    basename = uri.rstrip("/").rsplit("/", 1)[-1]
    if not basename:
        raise ManifestError(f"{uri} must include an S3 object basename")
    return basename


def _cache_uri(prefix: str, group: str, artifact: str, source: Mapping[str, Any]) -> str:
    uri = _require_s3_uri(source.get("uri"), f"{artifact} source uri")
    sha256 = _require_hex(source.get("sha256"), f"{artifact} sha256")
    basename = _basename_from_s3_uri(uri)
    return f"{prefix}/{posixpath.join(group, artifact, sha256, basename)}"


def _copy_row(prefix: str, kms_key_arn: str, group: str, artifact: str, source: Mapping[str, Any]) -> dict[str, Any]:
    source_uri = _require_s3_uri(source.get("uri"), f"{artifact} source uri")
    return {
        "artifact": artifact,
        "bytes": _require_positive_int(source.get("bytes"), artifact),
        "destination_kms_key_arn": kms_key_arn,
        "destination_uri": _cache_uri(prefix, group, artifact, source),
        "server_side_encryption": "aws:kms",
        "sha256": _require_hex(source.get("sha256"), f"{artifact} sha256"),
        "source_uri": source_uri,
        "source_version_id": _require_version(source.get("version_id"), artifact),
    }


def _append_bam_pair_rows(rows: list[dict[str, Any]], prefix: str, kms_key_arn: str, manifest: Mapping[str, Any]) -> None:
    bam_pair = _require_mapping(manifest.get("bam_pair"), "bam_pair")
    for role in ("tumor", "normal"):
        sample = _require_mapping(bam_pair.get(role), f"bam_pair {role}")
        for kind in ("bam", "bai"):
            artifact = f"{role}.{kind}"
            rows.append(_copy_row(prefix, kms_key_arn, "inputs", artifact, _require_mapping(sample.get(kind), artifact)))


def _append_reference_rows(rows: list[dict[str, Any]], prefix: str, kms_key_arn: str, manifest: Mapping[str, Any]) -> None:
    reference = _require_mapping(manifest.get("reference"), "reference")
    for artifact, key in (("reference.fa", "fasta"), ("reference.fa.fai", "fai"), ("reference.dict", "sequence_dictionary")):
        rows.append(_copy_row(prefix, kms_key_arn, "references", artifact, _require_mapping(reference.get(key), key)))


def _append_caller_resource_rows(rows: list[dict[str, Any]], prefix: str, kms_key_arn: str, manifest: Mapping[str, Any]) -> None:
    caller_resources = _require_mapping(manifest.get("caller_resources"), "caller_resources")
    for artifact in sorted(caller_resources):
        rows.append(_copy_row(prefix, kms_key_arn, "resources", artifact, _require_mapping(caller_resources.get(artifact), artifact)))


def _manifest_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_phase3_fast_replication_plan(
    input_manifest: Mapping[str, Any],
    *,
    cache_prefix: str,
    cache_kms_key_arn: str,
    cache_region: str,
    input_manifest_sha256: str,
) -> dict[str, Any]:
    if input_manifest.get("manifest_type") != "phase3_wgs_fast_input_manifest":
        raise ManifestError("input manifest_type must be phase3_wgs_fast_input_manifest")
    if input_manifest.get("status") != "ready":
        raise ManifestError("input manifest status must be ready")
    interpretation = _require_mapping(input_manifest.get("interpretation"), "interpretation")
    if interpretation.get("authorized_hrd_state") != "no_call":
        raise ManifestError("input manifest authorized_hrd_state must remain no_call")

    prefix = _normalize_cache_prefix(cache_prefix)
    region = _require_region(cache_region, "cache_region")
    kms_key_arn = _require_kms_key_arn(cache_kms_key_arn, region=region, label="cache_kms_key_arn")
    rows: list[dict[str, Any]] = []
    _append_bam_pair_rows(rows, prefix, kms_key_arn, input_manifest)
    _append_reference_rows(rows, prefix, kms_key_arn, input_manifest)
    _append_caller_resource_rows(rows, prefix, kms_key_arn, input_manifest)

    by_destination = {row["destination_uri"] for row in rows}
    if len(by_destination) != len(rows):
        raise ManifestError("replication plan contains duplicate destination URIs")

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_replication_plan",
        "status": "planned",
        "workflow": dict(_require_mapping(input_manifest.get("workflow"), "workflow")),
        "cache": {
            "kms_key_arn": kms_key_arn,
            "prefix": prefix,
            "region": region,
        },
        "source": {
            "input_manifest_sha256": _require_hex(input_manifest_sha256, "input_manifest_sha256"),
        },
        "copy_plan": rows,
        "object_count": len(rows),
        "total_bytes": sum(int(row["bytes"]) for row in rows),
        "interpretation": {
            "authorized_hrd_state": "no_call",
        },
    }


def write_plan(path: Path, plan: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_plan_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_INPUT_MANIFEST", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_REPLICATION_OUTPUT", DEFAULT_OUTPUT))
    plan = build_phase3_fast_replication_plan(
        read_json(input_path),
        cache_prefix=_require_string(os.environ.get("PHASE3_WGS_FAST_CACHE_PREFIX"), "PHASE3_WGS_FAST_CACHE_PREFIX"),
        cache_kms_key_arn=_require_string(os.environ.get("PHASE3_WGS_FAST_CACHE_KMS_KEY_ARN"), "PHASE3_WGS_FAST_CACHE_KMS_KEY_ARN"),
        cache_region=_require_string(os.environ.get("PHASE3_WGS_FAST_CACHE_REGION", "us-east-2"), "PHASE3_WGS_FAST_CACHE_REGION"),
        input_manifest_sha256=_manifest_sha256(input_path),
    )
    return plan, output_path


def main() -> None:
    plan, output = load_plan_from_environment()
    write_plan(output, plan)
    print(f"Phase 3 WGS fast replication plan written: {output}")


if __name__ == "__main__":
    main()
