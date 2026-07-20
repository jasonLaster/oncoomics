from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...paths import path_from_root
from ...utils import ensure_parent, standard_contig
from .render_phase3_fast_cache_manifest import BAM_CACHE_ARTIFACTS, REFERENCE_CACHE_ARTIFACTS
from .render_phase3_fast_input_manifest import (
    CALLER_RESOURCES,
    HEX64,
    ManifestError,
    _require_s3_uri,
    normalize_method_parameters,
)
from .render_phase3_fast_staging_plan import EXPECTED_STAGED_OBJECTS
from .safe_json_output import read_real_json_with_sha256, require_safe_output_path, sha256_real_file

DEFAULT_INPUT = "manifests/phase3_wgs_fast/staging_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/staged_inputs_manifest.json"


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
    if type(value) is not int or value <= 0:
        raise ManifestError(f"{label} bytes must be a positive integer")
    return value


def _require_safe_local_path(path: Path, label: str) -> None:
    require_safe_output_path(path, label, ManifestError)


def _require_absolute_file(value: Any, label: str) -> Path:
    path = Path(_require_string(value, label))
    if not path.is_absolute():
        raise ManifestError(f"{label} must be an absolute path")
    _require_safe_local_path(path, label)
    if not path.is_file():
        raise ManifestError(f"{label} does not exist as a file: {path}")
    return path


def _sha256_path(path: Path) -> str:
    return sha256_real_file(path, ManifestError)


def _require_source(value: Any, artifact: str) -> dict[str, str]:
    source = _require_mapping(value, f"{artifact} source")
    uri = _require_s3_uri(source.get("uri"), f"{artifact} source uri")
    bucket = _require_string(source.get("bucket"), f"{artifact} source bucket")
    key = _require_string(source.get("key"), f"{artifact} source key")
    if uri != f"s3://{bucket}/{key}":
        raise ManifestError(f"{artifact} source uri must match bucket/key")
    return {
        "bucket": bucket,
        "key": key,
        "uri": uri,
        "version_id": _require_string(source.get("version_id"), f"{artifact} source version_id"),
    }


def _require_original_source(value: Any, artifact: str) -> dict[str, str]:
    source = _require_mapping(value, f"{artifact} original_source")
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{artifact} original_source uri"),
        "version_id": _require_string(source.get("version_id"), f"{artifact} original_source version_id"),
    }


def _verify_staged_object(row: Mapping[str, Any]) -> dict[str, Any]:
    artifact = _require_string(row.get("artifact"), "staged artifact")
    local_path = _require_absolute_file(row.get("local_path"), f"{artifact} local_path")
    expected_bytes = _require_positive_int(row.get("bytes"), artifact)
    observed_bytes = local_path.stat().st_size
    if observed_bytes != expected_bytes:
        raise ManifestError(f"{artifact} local size {observed_bytes} does not match expected {expected_bytes}")

    expected_sha256 = _require_hex(row.get("sha256"), f"{artifact} sha256")
    observed_sha256 = _sha256_path(local_path)
    if observed_sha256 != expected_sha256:
        raise ManifestError(f"{artifact} local sha256 does not match expected {expected_sha256}")

    result = {
        "artifact": artifact,
        "bytes": expected_bytes,
        "local_path": str(local_path),
        "sha256": expected_sha256,
        "source": _require_source(row.get("source"), artifact),
        "original_source": _require_original_source(row.get("original_source"), artifact),
        "checks": {
            "local_path_absolute": True,
            "local_path_exists": True,
            "local_size_matches": True,
            "local_sha256_matches": True,
        },
    }
    for key in ("role", "sample_id"):
        if key in row:
            result[key] = _require_string(row.get(key), f"{artifact} {key}")
    return result


def _index_by_artifact(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    by_artifact: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        artifact = _require_string(row.get("artifact"), "staged artifact")
        if artifact in by_artifact:
            raise ManifestError(f"staged inputs contain duplicate artifact {artifact}")
        by_artifact[artifact] = row

    expected = set(BAM_CACHE_ARTIFACTS) | set(REFERENCE_CACHE_ARTIFACTS) | set(CALLER_RESOURCES)
    actual = set(by_artifact)
    if actual != expected:
        raise ManifestError(
            f"staged inputs expected exact artifacts {sorted(expected)}, "
            f"found missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    return by_artifact


def _read_standard_contigs(fai_path: str) -> list[dict[str, int | str]]:
    contigs: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(Path(fai_path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            raise ManifestError(f"reference.fa.fai line {line_number} must include contig and length")
        contig = fields[0]
        if not standard_contig(contig):
            continue
        if contig in seen:
            raise ManifestError(f"reference.fa.fai contains duplicate contig {contig}")
        seen.add(contig)
        try:
            length = int(fields[1])
        except ValueError as error:
            raise ManifestError(f"reference.fa.fai {contig} length must be an integer") from error
        if length <= 0:
            raise ManifestError(f"reference.fa.fai {contig} length must be positive")
        contigs.append({"contig": contig, "length": length})
    if not contigs:
        raise ManifestError("reference.fa.fai must include at least one standard chr1-chr22/chrX/chrY contig")
    return contigs


def build_phase3_fast_staged_inputs_manifest(
    staging_plan: Mapping[str, Any],
    *,
    staging_plan_sha256: str,
) -> dict[str, Any]:
    if staging_plan.get("manifest_type") != "phase3_wgs_fast_staging_plan":
        raise ManifestError("staging plan manifest_type must be phase3_wgs_fast_staging_plan")
    if staging_plan.get("status") != "planned":
        raise ManifestError("staging plan status must be planned")
    if _require_mapping(staging_plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("staged inputs authorized_hrd_state must remain no_call")

    staged_objects = [
        _verify_staged_object(row)
        for row in _require_list(staging_plan.get("staged_objects"), "staged_objects")
    ]
    by_artifact = _index_by_artifact(staged_objects)

    local_paths = {row["local_path"] for row in staged_objects}
    if len(local_paths) != len(staged_objects):
        raise ManifestError("staged inputs contain duplicate local paths")

    object_count = len(staged_objects)
    total_bytes = sum(int(row["bytes"]) for row in staged_objects)
    if object_count != EXPECTED_STAGED_OBJECTS:
        raise ManifestError(f"staged inputs must contain {EXPECTED_STAGED_OBJECTS} objects")
    if type(staging_plan.get("object_count")) is not int or staging_plan.get("object_count") != object_count:
        raise ManifestError("staging plan object_count does not match staged objects")
    if type(staging_plan.get("total_bytes")) is not int or staging_plan.get("total_bytes") != total_bytes:
        raise ManifestError("staging plan total_bytes does not match staged objects")

    source = _require_mapping(staging_plan.get("source"), "source")
    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_staged_inputs_manifest",
        "status": "ready",
        "workflow": dict(_require_mapping(staging_plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(staging_plan.get("run"), "run")),
        "runtime": dict(_require_mapping(staging_plan.get("runtime"), "runtime")),
        "cache": dict(_require_mapping(staging_plan.get("cache"), "cache")),
        "method_parameters": normalize_method_parameters(staging_plan.get("method_parameters")),
        "source": {
            "input_manifest_sha256": _require_hex(source.get("input_manifest_sha256"), "input_manifest_sha256"),
            "replication_plan_sha256": _require_hex(source.get("replication_plan_sha256"), "replication_plan_sha256"),
            "replication_receipt_sha256": _require_hex(source.get("replication_receipt_sha256"), "replication_receipt_sha256"),
            "cache_manifest_sha256": _require_hex(source.get("cache_manifest_sha256"), "cache_manifest_sha256"),
            "staging_plan_sha256": _require_hex(staging_plan_sha256, "staging_plan_sha256"),
        },
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
            "standard_contigs": _read_standard_contigs(str(by_artifact["reference.fa.fai"]["local_path"])),
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
    _require_safe_local_path(path, "staged inputs manifest output")
    ensure_parent(path)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGING_PLAN", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT", DEFAULT_OUTPUT))
    staging_plan, staging_plan_sha256 = read_real_json_with_sha256(
        input_path, "staging_plan", ManifestError
    )
    manifest = build_phase3_fast_staged_inputs_manifest(
        staging_plan,
        staging_plan_sha256=staging_plan_sha256,
    )
    return manifest, output_path


def main() -> None:
    manifest, output = load_manifest_from_environment()
    write_manifest(output, manifest)
    print(f"Phase 3 WGS fast staged inputs verified: {output}")


if __name__ == "__main__":
    main()
