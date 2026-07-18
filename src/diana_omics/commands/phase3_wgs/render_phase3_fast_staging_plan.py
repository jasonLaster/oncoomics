from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_cache_manifest import BAM_CACHE_ARTIFACTS, REFERENCE_CACHE_ARTIFACTS
from .render_phase3_fast_input_manifest import (
    CALLER_RESOURCES,
    HEX64,
    ManifestError,
    _require_s3_uri,
    normalize_method_parameters,
)

DEFAULT_INPUT = "manifests/phase3_wgs_fast/cache_manifest.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/staging_plan.json"
DEFAULT_STAGING_ROOT = "/scratch/diana/phase3_wgs_fast"
EXPECTED_STAGED_OBJECTS = 15
CALLER_RESOURCE_DIRECTORIES = {
    "common_sites_index": "common_sites",
    "common_sites_vcf": "common_sites",
    "gatk_jar": "gatk",
    "germline_resource_index": "germline_resource",
    "germline_resource_vcf": "germline_resource",
    "mutect2_interval_set": "intervals",
    "panel_of_normals_index": "panel_of_normals",
    "panel_of_normals_vcf": "panel_of_normals",
}


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


def _require_version_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or value in {"", "null", "None"}:
        raise ManifestError(f"{label} must be a durable VersionId")
    return value


def _require_staging_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ManifestError("staging_root must be an absolute path")
    return root


def _split_s3_uri(uri: Any, label: str) -> tuple[str, str]:
    value = _require_s3_uri(uri, label)
    bucket, key = value[5:].split("/", 1)
    if not bucket or not key:
        raise ManifestError(f"{label} uri must include an S3 bucket and key")
    return bucket, key


def _s3_basename(uri: str, artifact: str) -> str:
    _, key = _split_s3_uri(uri, f"{artifact} uri")
    filename = key.rstrip("/").rsplit("/", 1)[-1]
    if filename in {"", ".", ".."}:
        raise ManifestError(f"{artifact} uri must end with a filename")
    return filename


def _local_path(root: Path, artifact: str, uri: str) -> Path:
    filename = _s3_basename(uri, artifact)
    if artifact in {"normal.bam", "normal.bai"}:
        return root / "inputs" / "normal" / filename
    if artifact in {"tumor.bam", "tumor.bai"}:
        return root / "inputs" / "tumor" / filename
    if artifact in REFERENCE_CACHE_ARTIFACTS:
        return root / "reference" / filename
    return root / "caller_resources" / CALLER_RESOURCE_DIRECTORIES[artifact] / filename


def _cache_entry(entry: Mapping[str, Any], artifact: str, root: Path, region: str) -> dict[str, Any]:
    if entry.get("artifact") != artifact:
        raise ManifestError(f"{artifact} cache entry artifact must match its key")

    uri = _require_s3_uri(entry.get("uri"), f"{artifact} uri")
    bucket, key = _split_s3_uri(uri, f"{artifact} uri")
    version_id = _require_version_id(entry.get("version_id"), f"{artifact} version_id")
    local_path = str(_local_path(root, artifact, uri))

    result = {
        "artifact": artifact,
        "bytes": _require_positive_int(entry.get("bytes"), artifact),
        "sha256": _require_hex(entry.get("sha256"), f"{artifact} sha256"),
        "source": {
            "bucket": bucket,
            "key": key,
            "uri": uri,
            "version_id": version_id,
        },
        "original_source": {
            "uri": _require_s3_uri(entry.get("source_uri"), f"{artifact} source_uri"),
            "version_id": _require_version_id(entry.get("source_version_id"), f"{artifact} source_version_id"),
        },
        "local_path": local_path,
        "get_object_command": [
            "aws",
            "s3api",
            "get-object",
            "--region",
            region,
            "--bucket",
            bucket,
            "--key",
            key,
            "--version-id",
            version_id,
            local_path,
        ],
    }
    for key in ("role", "sample_id"):
        if key in entry:
            result[key] = _require_string(entry.get(key), f"{artifact} {key}")
    return result


def _flatten_cache_entries(cache_manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    bam_pair = _require_mapping(cache_manifest.get("bam_pair"), "bam_pair")
    normal = _require_mapping(bam_pair.get("normal"), "bam_pair.normal")
    tumor = _require_mapping(bam_pair.get("tumor"), "bam_pair.tumor")
    reference = _require_mapping(cache_manifest.get("reference"), "reference")
    caller_resources = _require_mapping(cache_manifest.get("caller_resources"), "caller_resources")
    if set(caller_resources) != set(CALLER_RESOURCES):
        raise ManifestError("caller_resources must contain the exact expected resources")

    entries = {
        "normal.bai": _require_mapping(normal.get("bai"), "normal.bai"),
        "normal.bam": _require_mapping(normal.get("bam"), "normal.bam"),
        "tumor.bai": _require_mapping(tumor.get("bai"), "tumor.bai"),
        "tumor.bam": _require_mapping(tumor.get("bam"), "tumor.bam"),
        "reference.dict": _require_mapping(reference.get("sequence_dictionary"), "reference.dict"),
        "reference.fa": _require_mapping(reference.get("fasta"), "reference.fa"),
        "reference.fa.fai": _require_mapping(reference.get("fai"), "reference.fa.fai"),
    }
    entries.update({artifact: _require_mapping(caller_resources.get(artifact), artifact) for artifact in CALLER_RESOURCES})

    expected = set(BAM_CACHE_ARTIFACTS) | set(REFERENCE_CACHE_ARTIFACTS) | set(CALLER_RESOURCES)
    if set(entries) != expected:
        raise ManifestError("cache manifest must contain the exact expected staged objects")
    return entries


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _index_by_artifact(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    by_artifact: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        artifact = _require_string(row.get("artifact"), "staged artifact")
        if artifact in by_artifact:
            raise ManifestError(f"staging plan contains duplicate artifact {artifact}")
        by_artifact[artifact] = row
    return by_artifact


def build_phase3_fast_staging_plan(
    cache_manifest: Mapping[str, Any],
    *,
    cache_manifest_sha256: str,
    staging_root: str | os.PathLike[str] = DEFAULT_STAGING_ROOT,
) -> dict[str, Any]:
    if cache_manifest.get("manifest_type") != "phase3_wgs_fast_cache_manifest":
        raise ManifestError("cache manifest manifest_type must be phase3_wgs_fast_cache_manifest")
    if cache_manifest.get("status") != "ready":
        raise ManifestError("cache manifest status must be ready")
    if _require_mapping(cache_manifest.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("staging plan authorized_hrd_state must remain no_call")

    root = _require_staging_root(staging_root)
    region = _require_string(_require_mapping(cache_manifest.get("cache"), "cache").get("region"), "cache region")
    entries = _flatten_cache_entries(cache_manifest)
    staged_objects = [
        _cache_entry(entries[artifact], artifact, root, region)
        for artifact in sorted(entries)
    ]

    local_paths = {row["local_path"] for row in staged_objects}
    if len(local_paths) != len(staged_objects):
        raise ManifestError("staging plan contains duplicate local paths")

    object_count = len(staged_objects)
    total_bytes = sum(int(row["bytes"]) for row in staged_objects)
    if object_count != EXPECTED_STAGED_OBJECTS:
        raise ManifestError(f"staging plan must contain {EXPECTED_STAGED_OBJECTS} objects")
    if cache_manifest.get("object_count") != object_count:
        raise ManifestError("cache manifest object_count does not match staged objects")
    if cache_manifest.get("total_bytes") != total_bytes:
        raise ManifestError("cache manifest total_bytes does not match staged objects")

    by_artifact = _index_by_artifact(staged_objects)
    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_staging_plan",
        "status": "planned",
        "workflow": dict(_require_mapping(cache_manifest.get("workflow"), "workflow")),
        "run": dict(_require_mapping(cache_manifest.get("run"), "run")),
        "runtime": dict(_require_mapping(cache_manifest.get("runtime"), "runtime")),
        "method_parameters": normalize_method_parameters(cache_manifest.get("method_parameters")),
        "cache": dict(_require_mapping(cache_manifest.get("cache"), "cache")),
        "source": {
            "input_manifest_sha256": _require_hex(
                _require_mapping(cache_manifest.get("source"), "source").get("input_manifest_sha256"),
                "input_manifest_sha256",
            ),
            "replication_plan_sha256": _require_hex(
                _require_mapping(cache_manifest.get("source"), "source").get("replication_plan_sha256"),
                "replication_plan_sha256",
            ),
            "replication_receipt_sha256": _require_hex(
                _require_mapping(cache_manifest.get("source"), "source").get("replication_receipt_sha256"),
                "replication_receipt_sha256",
            ),
            "cache_manifest_sha256": _require_hex(cache_manifest_sha256, "cache_manifest_sha256"),
        },
        "staging_root": str(root),
        "staged_objects": staged_objects,
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


def write_plan(path: Path, plan: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_plan_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_CACHE_MANIFEST", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGING_PLAN_OUTPUT", DEFAULT_OUTPUT))
    plan = build_phase3_fast_staging_plan(
        read_json(input_path),
        cache_manifest_sha256=_sha256_path(input_path),
        staging_root=os.environ.get("PHASE3_WGS_FAST_STAGING_ROOT", DEFAULT_STAGING_ROOT),
    )
    return plan, output_path


def main() -> None:
    plan, output = load_plan_from_environment()
    write_plan(output, plan)
    print(f"Phase 3 WGS fast staging plan written: {output}")


if __name__ == "__main__":
    main()
