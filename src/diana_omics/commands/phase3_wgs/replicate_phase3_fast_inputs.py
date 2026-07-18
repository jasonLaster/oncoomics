from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError, _require_s3_uri
from .render_phase3_fast_replication_plan import KMS_KEY_ARN, REGION

DEFAULT_INPUT = "manifests/phase3_wgs_fast/replication_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/replication_receipt.json"
DEFAULT_MULTIPART_PART_SIZE_BYTES = 512 * 1024 * 1024
EXPECTED_REPLICATION_OBJECTS = 15
S3_MAX_MULTIPART_PARTS = 10_000
S3_MAX_MULTIPART_PART_SIZE_BYTES = 5 * 1024 * 1024 * 1024
S3_MIN_MULTIPART_PART_SIZE_BYTES = 5 * 1024 * 1024
S3_SINGLE_COPY_LIMIT_BYTES = 5 * 1024 * 1024 * 1024


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
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


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} must be 64 hex characters")
    return value.lower()


def _require_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{label} bytes must be a positive integer")
    return value


def _require_part_size(value: str | None) -> int:
    if value is None or value == "":
        return DEFAULT_MULTIPART_PART_SIZE_BYTES
    try:
        parsed = int(value)
    except ValueError as error:
        raise ManifestError("PHASE3_WGS_FAST_REPLICATION_PART_SIZE_BYTES must be an integer") from error
    return _require_part_size_bytes(parsed, "PHASE3_WGS_FAST_REPLICATION_PART_SIZE_BYTES")


def _require_part_size_bytes(value: Any, label: str) -> int:
    if not isinstance(value, int):
        raise ManifestError(f"{label} must be an integer")
    if value < S3_MIN_MULTIPART_PART_SIZE_BYTES:
        raise ManifestError(f"{label} must be at least {S3_MIN_MULTIPART_PART_SIZE_BYTES} bytes")
    if value > S3_MAX_MULTIPART_PART_SIZE_BYTES:
        raise ManifestError(f"{label} must be at most {S3_MAX_MULTIPART_PART_SIZE_BYTES} bytes")
    return value


def _copy_plan_rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ManifestError("copy_plan must be a list")
    rows = [_require_mapping(row, "copy_plan row") for row in value]
    if len(rows) != EXPECTED_REPLICATION_OBJECTS:
        raise ManifestError(f"copy_plan must contain {EXPECTED_REPLICATION_OBJECTS} objects")
    return rows


def _require_version(value: Any, label: str) -> str:
    if not isinstance(value, str) or value in {"", "null", "None"}:
        raise ManifestError(f"{label} source_version_id must be a non-null S3 VersionId")
    return value


def _validate_cache_member(uri: str, prefix: str, artifact: str, sha256: str) -> None:
    if not uri.startswith(f"{prefix}/"):
        raise ManifestError(f"{artifact} destination_uri must be under the cache prefix")
    if f"/{sha256}/" not in uri:
        raise ManifestError(f"{artifact} destination_uri must be content-addressed by sha256")


def _split_s3_uri(uri: str, label: str) -> tuple[str, str]:
    bucket_and_key = uri.removeprefix("s3://")
    bucket, _, key = bucket_and_key.partition("/")
    if not bucket or not key:
        raise ManifestError(f"{label} must include an S3 bucket and key")
    return bucket, key


def _copy_source(bucket: str, key: str, version_id: str) -> str:
    return f"{bucket}/{quote(key, safe='/')}?versionId={quote(version_id, safe='')}"


def _upload_part_copy_ranges(artifact: str, bytes_: int, part_size_bytes: int) -> list[dict[str, Any]]:
    part_count = (bytes_ + part_size_bytes - 1) // part_size_bytes
    if part_count > S3_MAX_MULTIPART_PARTS:
        raise ManifestError(
            f"{artifact} multipart_copy would require {part_count} parts; "
            f"increase part_size_bytes to stay at or below {S3_MAX_MULTIPART_PARTS}"
        )

    return [
        {
            "copy_source_range": f"bytes={first_byte}-{min(bytes_ - 1, first_byte + part_size_bytes - 1)}",
            "first_byte": first_byte,
            "last_byte": min(bytes_ - 1, first_byte + part_size_bytes - 1),
            "part_number": index + 1,
        }
        for index, first_byte in enumerate(range(0, bytes_, part_size_bytes))
    ]


def _copy_strategy(
    artifact: str,
    bytes_: int,
    part_size_bytes: int,
    *,
    destination_uri: str,
    source_uri: str,
    source_version_id: str,
) -> dict[str, Any]:
    part_size_bytes = _require_part_size_bytes(part_size_bytes, "part_size_bytes")
    source_bucket, source_key = _split_s3_uri(source_uri, f"{artifact} source_uri")
    destination_bucket, destination_key = _split_s3_uri(destination_uri, f"{artifact} destination_uri")
    common = {
        "destination": {
            "bucket": destination_bucket,
            "key": destination_key,
        },
        "source": {
            "bucket": source_bucket,
            "copy_source": _copy_source(source_bucket, source_key, source_version_id),
            "key": source_key,
            "version_id": source_version_id,
        },
    }
    if bytes_ <= S3_SINGLE_COPY_LIMIT_BYTES:
        return {
            **common,
            "method": "copy_object",
            "part_count": 1,
            "part_size_bytes": None,
            "single_copy_limit_bytes": S3_SINGLE_COPY_LIMIT_BYTES,
        }

    parts = _upload_part_copy_ranges(artifact, bytes_, part_size_bytes)
    last_part = parts[-1]
    return {
        **common,
        "method": "upload_part_copy",
        "part_count": len(parts),
        "part_size_bytes": part_size_bytes,
        "parts": parts,
        "last_part_size_bytes": int(last_part["last_byte"]) - int(last_part["first_byte"]) + 1,
        "single_copy_limit_bytes": S3_SINGLE_COPY_LIMIT_BYTES,
    }


def _copy_result(row: Mapping[str, Any], prefix: str, kms_key_arn: str, part_size_bytes: int) -> dict[str, Any]:
    artifact = _require_string(row.get("artifact"), "copy_plan artifact")
    sha256 = _require_hex(row.get("sha256"), f"{artifact} sha256")
    bytes_ = _require_positive_int(row.get("bytes"), artifact)
    source_version_id = _require_version(row.get("source_version_id"), artifact)
    source_uri = _require_s3_uri(row.get("source_uri"), f"{artifact} source")
    destination_uri = _require_s3_uri(row.get("destination_uri"), f"{artifact} destination")
    _validate_cache_member(destination_uri, prefix, artifact, sha256)
    if row.get("server_side_encryption") != "aws:kms":
        raise ManifestError(f"{artifact} server_side_encryption must be aws:kms")
    if row.get("destination_kms_key_arn") != kms_key_arn:
        raise ManifestError(f"{artifact} destination_kms_key_arn must match the cache KMS key")

    return {
        "artifact": artifact,
        "bytes": bytes_,
        "checks": {
            "destination_kms_key_bound": True,
            "destination_uri_content_addressed": True,
            "dry_run_no_s3_write": True,
            "source_copy_version_bound": True,
            "source_version_id_bound": True,
        },
        "copy_strategy": _copy_strategy(
            artifact,
            bytes_,
            part_size_bytes,
            destination_uri=destination_uri,
            source_uri=source_uri,
            source_version_id=source_version_id,
        ),
        "destination_kms_key_arn": kms_key_arn,
        "destination_uri": destination_uri,
        "server_side_encryption": "aws:kms",
        "sha256": sha256,
        "source_uri": source_uri,
        "source_version_id": source_version_id,
        "status": "dry_run",
    }


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().lower().replace("-", "_")
    if normalized != "dry_run":
        raise ManifestError("FAST_REPLICATE_INPUTS only supports dry_run until multipart apply is implemented")
    return normalized


def build_phase3_fast_replication_receipt(
    replication_plan: Mapping[str, Any],
    *,
    mode: str,
    part_size_bytes: int = DEFAULT_MULTIPART_PART_SIZE_BYTES,
    replication_plan_sha256: str,
) -> dict[str, Any]:
    if replication_plan.get("manifest_type") != "phase3_wgs_fast_replication_plan":
        raise ManifestError("replication manifest_type must be phase3_wgs_fast_replication_plan")
    if replication_plan.get("status") != "planned":
        raise ManifestError("replication plan status must be planned")
    if _require_mapping(replication_plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("replication plan authorized_hrd_state must remain no_call")

    normalized_mode = _normalize_mode(mode)
    cache = _require_mapping(replication_plan.get("cache"), "cache")
    prefix = _require_s3_uri(cache.get("prefix"), "cache prefix").rstrip("/")
    region = _require_region(cache.get("region"), "cache region")
    kms_key_arn = _require_kms_key_arn(cache.get("kms_key_arn"), region=region, label="cache kms_key_arn")

    rows = [
        _copy_result(row, prefix, kms_key_arn, part_size_bytes)
        for row in _copy_plan_rows(replication_plan.get("copy_plan"))
    ]
    destination_uris = {row["destination_uri"] for row in rows}
    if len(destination_uris) != len(rows):
        raise ManifestError("replication receipt contains duplicate destination URIs")

    total_bytes = sum(int(row["bytes"]) for row in rows)
    if replication_plan.get("object_count") != len(rows):
        raise ManifestError("replication plan object_count does not match copy_plan")
    if replication_plan.get("total_bytes") != total_bytes:
        raise ManifestError("replication plan total_bytes does not match copy_plan")

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_replication_receipt",
        "status": "dry_run",
        "mode": normalized_mode,
        "workflow": dict(_require_mapping(replication_plan.get("workflow"), "workflow")),
        "cache": {
            "kms_key_arn": kms_key_arn,
            "prefix": prefix,
            "region": region,
        },
        "copy_strategy": {
            "s3_max_multipart_part_size_bytes": S3_MAX_MULTIPART_PART_SIZE_BYTES,
            "multipart_part_size_bytes": part_size_bytes,
            "s3_max_multipart_parts": S3_MAX_MULTIPART_PARTS,
            "s3_min_multipart_part_size_bytes": S3_MIN_MULTIPART_PART_SIZE_BYTES,
            "s3_single_copy_limit_bytes": S3_SINGLE_COPY_LIMIT_BYTES,
        },
        "source": {
            "input_manifest_sha256": _require_hex(
                _require_mapping(replication_plan.get("source"), "source").get("input_manifest_sha256"),
                "input_manifest_sha256",
            ),
            "replication_plan_sha256": _require_hex(replication_plan_sha256, "replication_plan_sha256"),
        },
        "copy_results": rows,
        "object_count": len(rows),
        "total_bytes": total_bytes,
        "interpretation": {
            "authorized_hrd_state": "no_call",
        },
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_receipt_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_REPLICATION_PLAN", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_REPLICATION_RECEIPT_OUTPUT", DEFAULT_OUTPUT))
    receipt = build_phase3_fast_replication_receipt(
        read_json(input_path),
        mode=os.environ.get("PHASE3_WGS_FAST_REPLICATION_MODE", "dry_run"),
        part_size_bytes=_require_part_size(os.environ.get("PHASE3_WGS_FAST_REPLICATION_PART_SIZE_BYTES")),
        replication_plan_sha256=_sha256_path(input_path),
    )
    return receipt, output_path


def main() -> None:
    receipt, output = load_receipt_from_environment()
    write_receipt(output, receipt)
    print(f"Phase 3 WGS fast replication receipt written: {output}")


if __name__ == "__main__":
    main()
