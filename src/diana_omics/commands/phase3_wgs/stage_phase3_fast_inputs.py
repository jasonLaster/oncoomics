from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Protocol

from ...paths import path_from_root
from ...utils import ensure_parent
from .render_phase3_fast_cache_manifest import BAM_CACHE_ARTIFACTS, REFERENCE_CACHE_ARTIFACTS
from .render_phase3_fast_input_manifest import CALLER_RESOURCES, ManifestError, _require_s3_uri
from .render_phase3_fast_staging_plan import EXPECTED_STAGED_OBJECTS
from .safe_json_output import read_real_json, require_safe_output_path
from .verify_phase3_fast_staged_inputs import build_phase3_fast_staged_inputs_manifest

DEFAULT_INPUT = "manifests/phase3_wgs_fast/staging_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/staged_inputs_manifest.json"
EXPECTED_STAGED_ARTIFACTS = set(BAM_CACHE_ARTIFACTS) | set(REFERENCE_CACHE_ARTIFACTS) | set(CALLER_RESOURCES)


class S3GetObjectClient(Protocol):
    def get_object(self, row: Mapping[str, Any]) -> None: ...


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    return value


def _require_list(value: Any, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be a list")
    return [_require_mapping(row, f"{label} row") for row in value]


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{label} must be a non-empty string list")
    return list(value)


def _require_absolute_path(value: Any, label: str) -> Path:
    path = Path(_require_string(value, label))
    if not path.is_absolute():
        raise ManifestError(f"{label} must be an absolute path")
    return path


def _source_parts(row: Mapping[str, Any], artifact: str) -> tuple[str, str, str]:
    source = _require_mapping(row.get("source"), f"{artifact} source")
    uri = _require_s3_uri(source.get("uri"), f"{artifact} source uri")
    bucket = _require_string(source.get("bucket"), f"{artifact} source bucket")
    key = _require_string(source.get("key"), f"{artifact} source key")
    version_id = _require_string(source.get("version_id"), f"{artifact} source version_id")
    if uri != f"s3://{bucket}/{key}":
        raise ManifestError(f"{artifact} source uri must match bucket/key")
    if version_id in {"null", "None"}:
        raise ManifestError(f"{artifact} source version_id must be a durable VersionId")
    return bucket, key, version_id


def expected_get_object_command(row: Mapping[str, Any], *, region: str) -> list[str]:
    artifact = _require_string(row.get("artifact"), "staged artifact")
    bucket, key, version_id = _source_parts(row, artifact)
    local_path = _require_absolute_path(row.get("local_path"), f"{artifact} local_path")
    return [
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
        str(local_path),
    ]


def _verify_get_object_command(row: Mapping[str, Any], *, region: str) -> None:
    artifact = _require_string(row.get("artifact"), "staged artifact")
    command = _require_string_list(row.get("get_object_command"), f"{artifact} get_object_command")
    expected = expected_get_object_command(row, region=region)
    if command != expected:
        raise ManifestError(f"{artifact} get_object_command must match source VersionId and local path")


def _verify_exact_artifacts(rows: list[Mapping[str, Any]]) -> None:
    by_artifact: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        artifact = _require_string(row.get("artifact"), "staged artifact")
        if artifact in by_artifact:
            raise ManifestError(f"staging plan contains duplicate artifact {artifact}")
        by_artifact[artifact] = row

    actual = set(by_artifact)
    if actual != EXPECTED_STAGED_ARTIFACTS:
        raise ManifestError(
            f"staging plan expected exact artifacts {sorted(EXPECTED_STAGED_ARTIFACTS)}, "
            f"found missing={sorted(EXPECTED_STAGED_ARTIFACTS - actual)} "
            f"extra={sorted(actual - EXPECTED_STAGED_ARTIFACTS)}"
        )


def _preflight_staging_plan(staging_plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if staging_plan.get("manifest_type") != "phase3_wgs_fast_staging_plan":
        raise ManifestError("staging plan manifest_type must be phase3_wgs_fast_staging_plan")
    if staging_plan.get("status") != "planned":
        raise ManifestError("staging plan status must be planned")
    if _require_mapping(staging_plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("stage inputs authorized_hrd_state must remain no_call")

    region = _require_string(_require_mapping(staging_plan.get("cache"), "cache").get("region"), "cache region")
    rows = _require_list(staging_plan.get("staged_objects"), "staged_objects")
    if len(rows) != EXPECTED_STAGED_OBJECTS:
        raise ManifestError(f"staging plan must contain {EXPECTED_STAGED_OBJECTS} staged objects")
    _verify_exact_artifacts(rows)
    for row in rows:
        _verify_get_object_command(row, region=region)
    destinations = [
        _require_absolute_path(row.get("local_path"), f"{_require_string(row.get('artifact'), 'staged artifact')} local_path")
        for row in rows
    ]
    if len(set(destinations)) != len(destinations):
        raise ManifestError("staging plan contains duplicate local paths")
    return rows


class AwsCliS3GetObjectClient:
    def get_object(self, row: Mapping[str, Any]) -> None:
        artifact = _require_string(row.get("artifact"), "staged artifact")
        command = _require_string_list(row.get("get_object_command"), f"{artifact} get_object_command")
        subprocess.check_call(command)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_safe_output_path(path: Path, label: str) -> None:
    require_safe_output_path(path, label, ManifestError)


def materialize_phase3_fast_staged_inputs(
    staging_plan: Mapping[str, Any],
    client: S3GetObjectClient,
) -> None:
    rows = _preflight_staging_plan(staging_plan)
    for row in rows:
        artifact = _require_string(row.get("artifact"), "staged artifact")
        local_path = _require_absolute_path(row.get("local_path"), f"{artifact} local_path")
        _require_safe_output_path(local_path, f"{artifact} local_path")
        ensure_parent(local_path)
        fd, tmp_name = tempfile.mkstemp(
            dir=local_path.parent,
            prefix=f".{local_path.name}.",
            suffix=".tmp",
        )
        os.close(fd)
        temp_path = Path(tmp_name)
        temp_path.unlink(missing_ok=True)
        command = _require_string_list(row.get("get_object_command"), f"{artifact} get_object_command")
        temp_row = dict(row)
        temp_row["local_path"] = str(temp_path)
        temp_row["get_object_command"] = [*command[:-1], str(temp_path)]
        try:
            client.get_object(temp_row)
            _require_safe_output_path(temp_path, f"{artifact} temporary local_path")
            if not temp_path.is_file():
                raise ManifestError(f"{artifact} temporary local_path must exist after get-object: {temp_path}")
            temp_path.replace(local_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


def stage_phase3_fast_inputs(
    staging_plan: Mapping[str, Any],
    *,
    client: S3GetObjectClient,
    staging_plan_sha256: str,
) -> dict[str, Any]:
    materialize_phase3_fast_staged_inputs(staging_plan, client)
    return build_phase3_fast_staged_inputs_manifest(
        staging_plan,
        staging_plan_sha256=staging_plan_sha256,
    )


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    _require_safe_output_path(path, "staged inputs manifest output")
    ensure_parent(path)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest_from_environment(
    client: S3GetObjectClient | None = None,
) -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGING_PLAN", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT", DEFAULT_OUTPUT))
    manifest = stage_phase3_fast_inputs(
        read_real_json(input_path, "staging_plan", ManifestError),
        client=client if client is not None else AwsCliS3GetObjectClient(),
        staging_plan_sha256=_sha256_path(input_path),
    )
    return manifest, output_path


def main() -> None:
    manifest, output = load_manifest_from_environment()
    write_manifest(output, manifest)
    print(f"Phase 3 WGS fast staged inputs materialized and verified: {output}")


if __name__ == "__main__":
    main()
