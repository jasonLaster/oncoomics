from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
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
NOT_FOUND_MARKERS = (
    "(404)",
    "404",
    "Not Found",
    "NoSuchKey",
)


class S3CopyClient(Protocol):
    def head_destination(self, row: Mapping[str, Any], *, version_id: str = "") -> dict[str, Any] | None:
        ...

    def copy_object(self, row: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def create_multipart_upload(self, row: Mapping[str, Any]) -> str:
        ...

    def upload_part_copy(self, row: Mapping[str, Any], part: Mapping[str, Any], *, upload_id: str) -> dict[str, Any]:
        ...

    def complete_multipart_upload(
        self,
        row: Mapping[str, Any],
        *,
        upload_id: str,
        parts: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        ...

    def abort_multipart_upload(self, row: Mapping[str, Any], *, upload_id: str) -> None:
        ...


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


def _copy_result(row: Mapping[str, Any], prefix: str, kms_key_arn: str, part_size_bytes: int, *, mode: str) -> dict[str, Any]:
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
            "dry_run_no_s3_write": mode == "dry_run",
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
        "status": "dry_run" if mode == "dry_run" else "planned",
    }


def _copy_results(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ManifestError("copy_results must be a list")
    return [_require_mapping(row, "copy_result row") for row in value]


def _row_copy_strategy(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _require_mapping(row.get("copy_strategy"), "copy_strategy")


def _row_destination(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _require_mapping(_row_copy_strategy(row).get("destination"), "copy_strategy destination")


def _require_version_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or value in {"", "null", "None"}:
        raise ManifestError(f"{label} must return a durable destination VersionId")
    return value


def _destination_metadata(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "diana-artifact": _require_string(row.get("artifact"), "artifact"),
        "diana-source-sha256": _require_hex(row.get("sha256"), "sha256"),
        "diana-source-version-id": _require_version(row.get("source_version_id"), "source"),
    }


def _destination_matches(row: Mapping[str, Any], head: Mapping[str, Any] | None) -> bool:
    if head is None:
        return False
    metadata = _require_mapping(head.get("Metadata", {}), "destination Metadata")
    expected_metadata = _destination_metadata(row)
    return (
        int(head.get("ContentLength", -1)) == int(row.get("bytes", -2))
        and head.get("ServerSideEncryption") == "aws:kms"
        and head.get("SSEKMSKeyId") == row.get("destination_kms_key_arn")
        and str(head.get("VersionId", "")) not in {"", "null", "None"}
        and all(str(metadata.get(key, "")) == value for key, value in expected_metadata.items())
    )


def _copy_response_version(response: Mapping[str, Any]) -> str:
    return _require_version_id(response.get("VersionId"), "copy response")


def _part_etag(response: Mapping[str, Any], part_number: int) -> str:
    copy_part_result = _require_mapping(response.get("CopyPartResult"), f"part {part_number} CopyPartResult")
    return _require_string(copy_part_result.get("ETag"), f"part {part_number} ETag")


def _verify_copied_destination(
    row: Mapping[str, Any],
    client: S3CopyClient,
    *,
    version_id: str,
) -> Mapping[str, Any]:
    destination = client.head_destination(row, version_id=version_id)
    if not _destination_matches(row, destination):
        artifact = _require_string(row.get("artifact"), "artifact")
        raise ManifestError(f"{artifact} destination object did not match the planned copy")
    assert destination is not None
    if str(destination.get("VersionId", "")) != version_id:
        artifact = _require_string(row.get("artifact"), "artifact")
        raise ManifestError(f"{artifact} destination VersionId did not match the copy response")
    return destination


def _apply_copy_object(row: Mapping[str, Any], client: S3CopyClient) -> tuple[str, Mapping[str, Any]]:
    response = client.copy_object(row)
    version_id = _copy_response_version(response)
    destination = _verify_copied_destination(row, client, version_id=version_id)
    return version_id, destination


def _apply_upload_part_copy(row: Mapping[str, Any], client: S3CopyClient) -> tuple[str, Mapping[str, Any]]:
    strategy = _row_copy_strategy(row)
    parts = _copy_results(strategy.get("parts"))
    upload_id = ""
    completed_upload = False
    completed: list[dict[str, Any]] = []
    try:
        upload_id = client.create_multipart_upload(row)
        _require_string(upload_id, "multipart upload_id")
        for part in parts:
            part_number = _require_positive_int(part.get("part_number"), "multipart part_number")
            response = client.upload_part_copy(row, part, upload_id=upload_id)
            completed.append(
                {
                    "ETag": _part_etag(response, part_number),
                    "PartNumber": part_number,
                }
            )
        response = client.complete_multipart_upload(row, upload_id=upload_id, parts=completed)
        completed_upload = True
        version_id = _copy_response_version(response)
        destination = _verify_copied_destination(row, client, version_id=version_id)
        return version_id, destination
    except Exception:
        if upload_id and not completed_upload:
            client.abort_multipart_upload(row, upload_id=upload_id)
        raise


def _apply_copy_result(row: Mapping[str, Any], client: S3CopyClient) -> dict[str, Any]:
    existing = client.head_destination(row)
    if _destination_matches(row, existing):
        assert existing is not None
        updated = dict(row)
        updated["status"] = "already_present"
        updated["destination_version_id"] = str(existing.get("VersionId"))
        updated["checks"] = {
            **_require_mapping(row.get("checks"), "checks"),
            "destination_kms_key_matches": True,
            "destination_metadata_matches": True,
            "destination_size_matches": True,
            "destination_versioned": True,
        }
        return updated
    if existing is not None:
        artifact = _require_string(row.get("artifact"), "artifact")
        raise ManifestError(f"{artifact} destination object already exists but does not match the planned copy")

    method = _require_string(_row_copy_strategy(row).get("method"), "copy_strategy method")
    if method == "copy_object":
        version_id, _destination = _apply_copy_object(row, client)
    elif method == "upload_part_copy":
        version_id, _destination = _apply_upload_part_copy(row, client)
    else:
        raise ManifestError(f"unsupported copy_strategy method: {method}")

    updated = dict(row)
    updated["status"] = "copied"
    updated["destination_version_id"] = version_id
    updated["checks"] = {
        **_require_mapping(row.get("checks"), "checks"),
        "copy_response_version_matches": True,
        "destination_kms_key_matches": True,
        "destination_metadata_matches": True,
        "destination_size_matches": True,
        "destination_versioned": True,
    }
    return updated


class AwsCliS3CopyClient:
    def __init__(self, *, region: str):
        self.region = region

    def _aws_json(self, arguments: list[str]) -> dict[str, Any]:
        command = ["aws", *arguments, "--region", self.region, "--output", "json"]
        output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
        if not output:
            return {}
        payload = json.loads(output)
        if not isinstance(payload, dict):
            raise RuntimeError(f"AWS command did not return a JSON object: {' '.join(command)}")
        return payload

    def _destination_arguments(self, row: Mapping[str, Any]) -> list[str]:
        destination = _row_destination(row)
        return [
            "--bucket",
            _require_string(destination.get("bucket"), "destination bucket"),
            "--key",
            _require_string(destination.get("key"), "destination key"),
        ]

    def head_destination(self, row: Mapping[str, Any], *, version_id: str = "") -> dict[str, Any] | None:
        arguments = ["s3api", "head-object", *self._destination_arguments(row)]
        if version_id:
            arguments.extend(["--version-id", version_id])
        try:
            return self._aws_json(arguments)
        except subprocess.CalledProcessError as error:
            output = str(error.output)
            if any(marker in output for marker in NOT_FOUND_MARKERS):
                return None
            raise

    def copy_object(self, row: Mapping[str, Any]) -> dict[str, Any]:
        strategy = _row_copy_strategy(row)
        source = _require_mapping(strategy.get("source"), "copy_strategy source")
        return self._aws_json(
            [
                "s3api",
                "copy-object",
                "--copy-source",
                _require_string(source.get("copy_source"), "copy_source"),
                *self._destination_arguments(row),
                "--if-none-match",
                "*",
                "--server-side-encryption",
                "aws:kms",
                "--sse-kms-key-id",
                _require_string(row.get("destination_kms_key_arn"), "destination_kms_key_arn"),
                "--metadata-directive",
                "REPLACE",
                "--metadata",
                json.dumps(_destination_metadata(row), sort_keys=True),
            ]
        )

    def create_multipart_upload(self, row: Mapping[str, Any]) -> str:
        response = self._aws_json(
            [
                "s3api",
                "create-multipart-upload",
                *self._destination_arguments(row),
                "--server-side-encryption",
                "aws:kms",
                "--sse-kms-key-id",
                _require_string(row.get("destination_kms_key_arn"), "destination_kms_key_arn"),
                "--metadata",
                json.dumps(_destination_metadata(row), sort_keys=True),
            ]
        )
        return _require_string(response.get("UploadId"), "UploadId")

    def upload_part_copy(self, row: Mapping[str, Any], part: Mapping[str, Any], *, upload_id: str) -> dict[str, Any]:
        strategy = _row_copy_strategy(row)
        source = _require_mapping(strategy.get("source"), "copy_strategy source")
        return self._aws_json(
            [
                "s3api",
                "upload-part-copy",
                *self._destination_arguments(row),
                "--copy-source",
                _require_string(source.get("copy_source"), "copy_source"),
                "--copy-source-range",
                _require_string(part.get("copy_source_range"), "copy_source_range"),
                "--part-number",
                str(_require_positive_int(part.get("part_number"), "multipart part_number")),
                "--upload-id",
                upload_id,
            ]
        )

    def complete_multipart_upload(
        self,
        row: Mapping[str, Any],
        *,
        upload_id: str,
        parts: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        multipart_upload = {"Parts": parts}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(multipart_upload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            return self._aws_json(
                [
                    "s3api",
                    "complete-multipart-upload",
                    *self._destination_arguments(row),
                    "--upload-id",
                    upload_id,
                    "--multipart-upload",
                    f"file://{handle.name}",
                    "--if-none-match",
                    "*",
                ]
            )

    def abort_multipart_upload(self, row: Mapping[str, Any], *, upload_id: str) -> None:
        self._aws_json(
            [
                "s3api",
                "abort-multipart-upload",
                *self._destination_arguments(row),
                "--upload-id",
                upload_id,
            ]
        )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_mode(mode: str) -> str:
    normalized = mode.strip().lower().replace("-", "_")
    if normalized not in {"dry_run", "apply"}:
        raise ManifestError("FAST_REPLICATE_INPUTS mode must be dry_run or apply")
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
        _copy_result(row, prefix, kms_key_arn, part_size_bytes, mode=normalized_mode)
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
        "status": "dry_run" if normalized_mode == "dry_run" else "planned",
        "mode": normalized_mode,
        "workflow": dict(_require_mapping(replication_plan.get("workflow"), "workflow")),
        "run": dict(_require_mapping(replication_plan.get("run"), "run")),
        "runtime": dict(_require_mapping(replication_plan.get("runtime"), "runtime")),
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


def apply_phase3_fast_replication_receipt(receipt: Mapping[str, Any], client: S3CopyClient) -> dict[str, Any]:
    if receipt.get("manifest_type") != "phase3_wgs_fast_replication_receipt":
        raise ManifestError("replication receipt manifest_type must be phase3_wgs_fast_replication_receipt")
    if receipt.get("mode") != "apply":
        raise ManifestError("replication receipt mode must be apply")
    if receipt.get("status") != "planned":
        raise ManifestError("replication receipt status must be planned before apply")
    if _require_mapping(receipt.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("replication receipt authorized_hrd_state must remain no_call")

    applied_rows = [_apply_copy_result(row, client) for row in _copy_results(receipt.get("copy_results"))]
    copied_count = sum(1 for row in applied_rows if row.get("status") == "copied")
    already_present_count = sum(1 for row in applied_rows if row.get("status") == "already_present")
    applied = dict(receipt)
    applied["status"] = "applied"
    applied["copy_results"] = applied_rows
    applied["copied_count"] = copied_count
    applied["already_present_count"] = already_present_count
    return applied


def main() -> None:
    receipt, output = load_receipt_from_environment()
    if receipt["mode"] == "apply":
        region = _require_string(_require_mapping(receipt.get("cache"), "cache").get("region"), "cache region")
        receipt = apply_phase3_fast_replication_receipt(receipt, AwsCliS3CopyClient(region=region))
    write_receipt(output, receipt)
    print(f"Phase 3 WGS fast replication receipt written: {output}")


if __name__ == "__main__":
    main()
