from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...paths import ROOT, path_from_root
from ...utils import ensure_parent
from .safe_json_output import read_real_json, require_safe_output_path

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
IMAGE_DIGEST = re.compile(r"^(?:.+@)?sha256:[0-9a-fA-F]{64}$")
VERSION_ID = re.compile(r"^\S+$")

DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/input_manifest.json"

PRIVATE_ARTIFACTS = ("normal.markdup.bam", "normal.markdup.bam.bai", "tumor.markdup.bam", "tumor.markdup.bam.bai")
ROLE_ARTIFACTS = {
    "normal": ("normal.markdup.bam", "normal.markdup.bam.bai"),
    "tumor": ("tumor.markdup.bam", "tumor.markdup.bam.bai"),
}
REFERENCE_ARTIFACTS = ("reference.dict", "reference.fa", "reference.fa.fai")
CALLER_RESOURCES = (
    "common_sites_index",
    "common_sites_vcf",
    "gatk_jar",
    "germline_resource_index",
    "germline_resource_vcf",
    "mutect2_interval_set",
    "panel_of_normals_index",
    "panel_of_normals_vcf",
)


class ManifestError(ValueError):
    """Raised when a Phase 3 WGS fast-run manifest input is not exactly bound."""


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _object_rows(payload: Mapping[str, Any], label: str) -> list[Mapping[str, Any]]:
    rows = payload.get("objects", payload.get("resources"))
    if not isinstance(rows, list):
        raise ManifestError(f"{label} must contain an objects list")
    result = [_require_mapping(row, f"{label} object") for row in rows]
    object_count = payload.get("object_count")
    if object_count is not None and (type(object_count) is not int or object_count != len(result)):
        raise ManifestError(f"{label} object_count does not match objects")
    if payload.get("status") != "passed":
        raise ManifestError(f"{label} status must be passed")
    return result


def _artifact_from_destination(row: Mapping[str, Any], label: str) -> str:
    destination = _require_mapping(row.get("destination"), f"{label} destination")
    uri = destination.get("uri")
    if not isinstance(uri, str) or not uri.startswith("s3://") or "/" not in uri[5:]:
        raise ManifestError(f"{label} destination uri must be an S3 object URI")
    return uri.rstrip("/").rsplit("/", 1)[-1]


def _artifact_from_row(row: Mapping[str, Any], label: str) -> str:
    artifact = row.get("artifact")
    if not isinstance(artifact, str) or not artifact:
        raise ManifestError(f"{label} artifact is required")
    return artifact


def _index_by_artifact(
    rows: Sequence[Mapping[str, Any]], artifacts: Sequence[str], label: str, *, freeze: bool
) -> dict[str, Mapping[str, Any]]:
    by_artifact: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        artifact = _artifact_from_destination(row, label) if freeze else _artifact_from_row(row, label)
        if artifact in by_artifact:
            raise ManifestError(f"{label} contains duplicate artifact {artifact}")
        by_artifact[artifact] = row

    expected = set(artifacts)
    actual = set(by_artifact)
    if actual != expected:
        raise ManifestError(
            f"{label} expected exact artifacts {sorted(expected)}, found missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    return by_artifact


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} sha256 must be 64 hex characters")
    return value.lower()


def _require_image_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or IMAGE_DIGEST.fullmatch(value) is None:
        raise ManifestError(f"{label} must be pinned by sha256 digest")
    return value


def _image_digest(value: Any, label: str) -> str:
    return _require_image_digest(value, label).rsplit("@", 1)[-1].lower()


def _require_matching_image_digest(metadata: Mapping[str, str]) -> str:
    digest = _image_digest(_metadata_value(metadata, "parabricks_container_digest"), "parabricks_container_digest")
    container = metadata.get("parabricks_container")
    if container and container not in {"null", "None"} and _image_digest(container, "parabricks_container") != digest:
        raise ManifestError("parabricks_container_digest must match parabricks_container")
    return digest


def _require_version(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.lower() in {"none", "null"}
        or VERSION_ID.fullmatch(value) is None
    ):
        raise ManifestError(f"{label} version_id must be a non-null S3 VersionId")
    return value


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ManifestError(f"{label} bytes must be a positive integer")
    return value


def _require_kms(value: Any, label: str) -> str:
    if value != "aws:kms":
        raise ManifestError(f"{label} server_side_encryption must be aws:kms")
    return "aws:kms"


def _require_s3_uri(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("s3://") or "/" not in value[5:]:
        raise ManifestError(f"{label} uri must be an S3 object URI")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    return value


def _require_passed_status(value: Any, label: str) -> None:
    if value != "passed":
        raise ManifestError(f"{label} status must be passed")


def _require_matching(value: Any, expected: str, label: str) -> None:
    if value != expected:
        raise ManifestError(f"{label} must match {expected}")


def _require_freeze_checks(row: Mapping[str, Any], artifact: str, label: str) -> None:
    _require_passed_status(row.get("status"), f"{label} {artifact}")
    checks = _require_mapping(row.get("checks"), f"{label} {artifact} checks")
    for check in (
        "content_length_matches",
        "crc64nvme_matches",
        "crc64nvme_present",
        "destination_bucket_matches",
        "destination_kms_key_matches",
        "destination_sse_kms",
        "destination_versioned",
    ):
        if checks.get(check) is not True:
            raise ManifestError(f"{label} {artifact} check {check} must be true")


def normalize_frozen_artifacts(
    freeze_receipt: Mapping[str, Any],
    sha256_receipt: Mapping[str, Any],
    artifacts: Sequence[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    freeze_rows = _index_by_artifact(_object_rows(freeze_receipt, f"{label} freeze receipt"), artifacts, label, freeze=True)
    sha_rows = _index_by_artifact(_object_rows(sha256_receipt, f"{label} sha256 receipt"), artifacts, label, freeze=False)

    normalized: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        freeze_row = freeze_rows[artifact]
        sha_row = sha_rows[artifact]
        _require_freeze_checks(freeze_row, artifact, label)
        _require_passed_status(sha_row.get("status"), f"{label} {artifact}")

        destination = _require_mapping(freeze_row.get("destination"), f"{label} {artifact} destination")
        sha256 = _require_hex(sha_row.get("sha256"), f"{label} {artifact}")
        version_id = _require_version(sha_row.get("version_id"), f"{label} {artifact}")
        bytes_ = _require_positive_int(sha_row.get("bytes"), f"{label} {artifact}")
        destination_bytes = _require_positive_int(
            destination.get("bytes"),
            f"{label} {artifact} destination",
        )
        crc64nvme = sha_row.get("crc64nvme")
        if not isinstance(crc64nvme, str) or not crc64nvme:
            raise ManifestError(f"{label} {artifact} crc64nvme is required")
        if destination_bytes != bytes_:
            raise ManifestError(f"{label} {artifact} freeze and sha256 byte counts differ")
        if destination.get("version_id") != version_id:
            raise ManifestError(f"{label} {artifact} freeze and sha256 version_id values differ")
        if destination.get("crc64nvme") != crc64nvme:
            raise ManifestError(f"{label} {artifact} freeze and sha256 crc64nvme values differ")

        normalized[artifact] = {
            "artifact": artifact,
            "bytes": bytes_,
            "crc64nvme": crc64nvme,
            "etag": destination.get("etag", ""),
            "kms_key_id": sha_row.get("kms_key_id", destination.get("kms_key_id", "")),
            "server_side_encryption": _require_kms(sha_row.get("server_side_encryption"), f"{label} {artifact}"),
            "sha256": sha256,
            "uri": _require_s3_uri(destination.get("uri"), f"{label} {artifact}"),
            "version_id": version_id,
        }
    return normalized


def normalize_caller_resources(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = _index_by_artifact(_object_rows(receipt, "caller resource receipt"), CALLER_RESOURCES, "caller resource receipt", freeze=False)
    checks = _require_mapping(receipt.get("checks"), "caller resource receipt checks")
    for check in (
        "common_sites_index_matches_vcf",
        "germline_resource_index_matches_vcf",
        "panel_of_normals_index_matches_vcf",
    ):
        if checks.get(check) is not True:
            raise ManifestError(f"caller resource receipt check {check} must be true")

    normalized: dict[str, dict[str, Any]] = {}
    for artifact in CALLER_RESOURCES:
        row = rows[artifact]
        _require_passed_status(row.get("status"), f"caller resource {artifact}")
        normalized[artifact] = {
            "artifact": artifact,
            "bytes": _require_positive_int(row.get("bytes"), f"caller resource {artifact}"),
            "server_side_encryption": _require_kms(row.get("server_side_encryption"), f"caller resource {artifact}"),
            "sha256": _require_hex(row.get("sha256"), f"caller resource {artifact}"),
            "uri": _require_s3_uri(row.get("uri"), f"caller resource {artifact}"),
            "version_id": _require_version(row.get("version_id"), f"caller resource {artifact}"),
        }
    return normalized


def _require_validated_object_identity(
    sample: Mapping[str, Any],
    object_name: str,
    artifact: str,
    private_inputs: Mapping[str, Mapping[str, Any]],
    label: str,
) -> dict[str, str]:
    validated = _require_mapping(sample.get(object_name), f"{label} {object_name}")
    expected = private_inputs[artifact]
    _require_matching(validated.get("artifact"), artifact, f"{label} {object_name} artifact")
    _require_matching(validated.get("sha256"), expected["sha256"], f"{label} {object_name} sha256")
    _require_matching(validated.get("version_id"), expected["version_id"], f"{label} {object_name} version_id")
    return {
        "artifact": artifact,
        "sha256": expected["sha256"],
        "version_id": expected["version_id"],
    }


def normalize_bam_validation_receipt(
    receipt: Mapping[str, Any], private_inputs: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    _require_passed_status(receipt.get("status"), "BAM validation receipt")
    checks = _require_mapping(receipt.get("checks"), "BAM validation checks")
    for check in (
        "bam_bai_pairing",
        "reference_contigs_match",
        "sample_names_match_manifest",
        "samtools_quickcheck",
    ):
        if checks.get(check) is not True:
            raise ManifestError(f"BAM validation check {check} must be true")

    samples = _require_mapping(receipt.get("samples"), "BAM validation samples")
    expected_roles = set(ROLE_ARTIFACTS)
    actual_roles = set(samples)
    if actual_roles != expected_roles:
        raise ManifestError(
            f"BAM validation samples expected exact roles {sorted(expected_roles)}, "
            f"found missing={sorted(expected_roles - actual_roles)} extra={sorted(actual_roles - expected_roles)}"
        )

    normalized_samples: dict[str, dict[str, Any]] = {}
    for role, (bam_artifact, bai_artifact) in sorted(ROLE_ARTIFACTS.items()):
        sample = _require_mapping(samples.get(role), f"BAM validation {role}")
        if sample.get("role") != role:
            raise ManifestError(f"BAM validation {role} role must be {role}")
        if sample.get("bam_artifact") != bam_artifact:
            raise ManifestError(f"BAM validation {role} must bind {bam_artifact}")
        if sample.get("bai_artifact") != bai_artifact:
            raise ManifestError(f"BAM validation {role} must bind {bai_artifact}")

        quickcheck = _require_mapping(sample.get("samtools_quickcheck"), f"BAM validation {role} quickcheck")
        _require_passed_status(quickcheck.get("status"), f"BAM validation {role} quickcheck")
        normalized_samples[role] = {
            "bai": _require_validated_object_identity(sample, "bai", bai_artifact, private_inputs, f"BAM validation {role}"),
            "bam": _require_validated_object_identity(sample, "bam", bam_artifact, private_inputs, f"BAM validation {role}"),
            "bam_artifact": bam_artifact,
            "bai_artifact": bai_artifact,
            "role": role,
            "sample_id": _require_string(sample.get("sample_id"), f"BAM validation {role} sample_id"),
            "samtools_quickcheck": dict(sorted(quickcheck.items())),
        }
    return {"checks": dict(sorted(checks.items())), "samples": normalized_samples}


def normalize_contig_compatibility_receipt(
    receipt: Mapping[str, Any], reference: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    _require_passed_status(receipt.get("status"), "contig compatibility receipt")
    _require_matching(
        receipt.get("reference_sequence_dictionary_sha256"),
        reference["reference.dict"]["sha256"],
        "contig compatibility reference_sequence_dictionary_sha256",
    )
    checks = _require_mapping(receipt.get("checks"), "contig compatibility checks")
    for check in (
        "bam_fasta_contigs_compatible",
        "common_sites_contigs_compatible",
        "germline_resource_contigs_compatible",
        "intervals_on_reference",
        "panel_of_normals_contigs_compatible",
    ):
        if checks.get(check) is not True:
            raise ManifestError(f"contig compatibility check {check} must be true")
    return {
        "checks": {check: checks[check] for check in sorted(checks)},
        "reference_sequence_dictionary_sha256": reference["reference.dict"]["sha256"],
    }


def role_validation(validation: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    return _require_mapping(_require_mapping(validation.get("samples"), "BAM validation samples").get(role), role)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ManifestError("PHASE3_WGS_FAST_SOURCE_COMMIT is required when git rev-parse HEAD is unavailable") from error


def _source_receipt_entry(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256_file(path)}


def _metadata_value(metadata: Mapping[str, str], key: str, default: str = "") -> str:
    value = metadata.get(key, default)
    if not value:
        raise ManifestError(f"{key} is required")
    return value


def _metadata_bool(metadata: Mapping[str, str], key: str) -> bool:
    value = _metadata_value(metadata, key).lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ManifestError(f"{key} must be explicitly true or false")


def _matching_metadata_value(metadata: Mapping[str, str], key: str, receipt_value: str) -> str:
    value = metadata.get(key, receipt_value)
    if value != receipt_value:
        raise ManifestError(f"{key} must match the BAM validation receipt")
    return value


def normalize_method_parameters(value: Any) -> dict[str, Any]:
    method_parameters = _require_mapping(value, "method_parameters")
    if set(method_parameters) != {"sequenza"}:
        raise ManifestError("method_parameters must contain exactly sequenza")

    sequenza = _require_mapping(method_parameters.get("sequenza"), "method_parameters.sequenza")
    if set(sequenza) != {"female"}:
        raise ManifestError("method_parameters.sequenza must contain exactly female")
    if not isinstance(sequenza.get("female"), bool):
        raise ManifestError("method_parameters.sequenza.female must be a boolean")

    return {
        "sequenza": {
            "female": bool(sequenza["female"]),
        },
    }


def build_phase3_wgs_fast_input_manifest(
    *,
    private_freeze_receipt: Mapping[str, Any],
    private_sha256_receipt: Mapping[str, Any],
    reference_freeze_receipt: Mapping[str, Any],
    reference_sha256_receipt: Mapping[str, Any],
    bam_validation_receipt: Mapping[str, Any],
    contig_compatibility_receipt: Mapping[str, Any],
    caller_resource_receipt: Mapping[str, Any],
    metadata: Mapping[str, str],
    source_receipts: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    private_inputs = normalize_frozen_artifacts(private_freeze_receipt, private_sha256_receipt, PRIVATE_ARTIFACTS, "private input")
    reference = normalize_frozen_artifacts(reference_freeze_receipt, reference_sha256_receipt, REFERENCE_ARTIFACTS, "reference")
    bam_validation = normalize_bam_validation_receipt(bam_validation_receipt, private_inputs)
    contig_compatibility = normalize_contig_compatibility_receipt(contig_compatibility_receipt, reference)
    caller_resources = normalize_caller_resources(caller_resource_receipt)
    parameter_digest = _require_hex(_metadata_value(metadata, "parameter_sha256"), "parameter digest")
    tumor_validation = role_validation(bam_validation, "tumor")
    normal_validation = role_validation(bam_validation, "normal")

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_input_manifest",
        "status": "ready",
        "workflow": {
            "name": "phase3_wgs_fast",
            "source_commit": _metadata_value(metadata, "source_commit"),
            "parameter_sha256": parameter_digest,
        },
        "run": {
            "run_id": _metadata_value(metadata, "run_id", "diana-wgs-hrd-20260716T033101Z"),
            "subject_alias": _metadata_value(metadata, "subject_alias", "subject01"),
            "pair_id": _metadata_value(metadata, "pair_id", "subject01_tumor_normal"),
        },
        "bam_pair": {
            "tumor": {
                "role": "tumor",
                "sample_id": _matching_metadata_value(metadata, "tumor_sample_id", str(tumor_validation["sample_id"])),
                "bam": private_inputs["tumor.markdup.bam"],
                "bai": private_inputs["tumor.markdup.bam.bai"],
                "samtools_quickcheck": tumor_validation["samtools_quickcheck"],
            },
            "normal": {
                "role": "normal",
                "sample_id": _matching_metadata_value(metadata, "normal_sample_id", str(normal_validation["sample_id"])),
                "bam": private_inputs["normal.markdup.bam"],
                "bai": private_inputs["normal.markdup.bam.bai"],
                "samtools_quickcheck": normal_validation["samtools_quickcheck"],
            },
        },
        "reference": {
            "reference_id": _metadata_value(metadata, "reference_id", "ucsc_hg38_analysis_set_full"),
            "fasta": reference["reference.fa"],
            "fai": reference["reference.fa.fai"],
            "sequence_dictionary": reference["reference.dict"],
            "sequence_dictionary_sha256": reference["reference.dict"]["sha256"],
        },
        "caller_resources": caller_resources,
        "runtime": {
            "caller": "parabricks_mutectcaller",
            "parabricks_container_digest": _require_matching_image_digest(metadata),
            "parabricks_version": _metadata_value(metadata, "parabricks_version"),
            "gatk_version": _metadata_value(metadata, "gatk_version", "4.6.2.0"),
        },
        "method_parameters": normalize_method_parameters(
            {
                "sequenza": {
                    "female": _metadata_bool(metadata, "sequenza_female"),
                },
            }
        ),
        "validation": {
            "bam": bam_validation,
            "contig_compatibility": contig_compatibility,
        },
        "interpretation": {
            "allowed_interpretation_level": "research_no_call",
            "authorized_hrd_state": "no_call",
            "required_no_call_policy": (
                "This manifest only authorizes recomputation. scarHRD, CHORD, HRDetect, SBS3, "
                "allele-specific LOH, and categorical HRD interpretation remain no_call until "
                "validated inputs, thresholds, known-answer performance, and review policy are locked."
            ),
        },
        "source_receipts": dict(sorted((source_receipts or {}).items())),
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast input manifest output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest_from_environment() -> tuple[dict[str, Any], Path]:
    private_freeze = path_from_root(_metadata_value(os.environ, "PHASE3_WGS_FAST_PRIVATE_FREEZE_RECEIPT"))
    private_sha256 = path_from_root(_metadata_value(os.environ, "PHASE3_WGS_FAST_PRIVATE_SHA256_RECEIPT"))
    reference_freeze = path_from_root(_metadata_value(os.environ, "PHASE3_WGS_FAST_REFERENCE_FREEZE_RECEIPT"))
    reference_sha256 = path_from_root(_metadata_value(os.environ, "PHASE3_WGS_FAST_REFERENCE_SHA256_RECEIPT"))
    bam_validation = path_from_root(_metadata_value(os.environ, "PHASE3_WGS_FAST_BAM_VALIDATION_RECEIPT"))
    contig_compatibility = path_from_root(_metadata_value(os.environ, "PHASE3_WGS_FAST_CONTIG_COMPATIBILITY_RECEIPT"))
    caller_resources = path_from_root(_metadata_value(os.environ, "PHASE3_WGS_FAST_CALLER_RESOURCE_RECEIPT"))

    metadata = {
        "gatk_version": os.environ.get("PHASE3_WGS_FAST_GATK_VERSION", "4.6.2.0"),
        "normal_sample_id": os.environ.get("PHASE3_WGS_FAST_NORMAL_SAMPLE_ID", "subject01_normal"),
        "pair_id": os.environ.get("PHASE3_WGS_FAST_PAIR_ID", "subject01_tumor_normal"),
        "parabricks_container": os.environ.get("PHASE3_WGS_FAST_PARABRICKS_CONTAINER", ""),
        "parabricks_container_digest": os.environ.get("PHASE3_WGS_FAST_PARABRICKS_CONTAINER_DIGEST", ""),
        "parabricks_version": os.environ.get("PHASE3_WGS_FAST_PARABRICKS_VERSION", ""),
        "parameter_sha256": os.environ.get("PHASE3_WGS_FAST_PARAMETER_SHA256", ""),
        "reference_id": os.environ.get("PHASE3_WGS_FAST_REFERENCE_ID", "ucsc_hg38_analysis_set_full"),
        "run_id": os.environ.get("PHASE3_WGS_FAST_RUN_ID", "diana-wgs-hrd-20260716T033101Z"),
        "sequenza_female": os.environ.get("PHASE3_WGS_FAST_SEQUENZA_FEMALE", ""),
        "source_commit": os.environ.get("PHASE3_WGS_FAST_SOURCE_COMMIT") or git_head(),
        "subject_alias": os.environ.get("PHASE3_WGS_FAST_SUBJECT_ALIAS", "subject01"),
        "tumor_sample_id": os.environ.get("PHASE3_WGS_FAST_TUMOR_SAMPLE_ID", "subject01_tumor"),
    }

    manifest = build_phase3_wgs_fast_input_manifest(
        private_freeze_receipt=read_real_json(private_freeze, "private_freeze receipt", ManifestError),
        private_sha256_receipt=read_real_json(private_sha256, "private_sha256 receipt", ManifestError),
        reference_freeze_receipt=read_real_json(reference_freeze, "reference_freeze receipt", ManifestError),
        reference_sha256_receipt=read_real_json(reference_sha256, "reference_sha256 receipt", ManifestError),
        bam_validation_receipt=read_real_json(bam_validation, "bam_validation receipt", ManifestError),
        contig_compatibility_receipt=read_real_json(contig_compatibility, "contig_compatibility receipt", ManifestError),
        caller_resource_receipt=read_real_json(caller_resources, "caller_resources receipt", ManifestError),
        metadata=metadata,
        source_receipts={
            "bam_validation": _source_receipt_entry(bam_validation),
            "caller_resources": _source_receipt_entry(caller_resources),
            "contig_compatibility": _source_receipt_entry(contig_compatibility),
            "private_freeze": _source_receipt_entry(private_freeze),
            "private_sha256": _source_receipt_entry(private_sha256),
            "reference_freeze": _source_receipt_entry(reference_freeze),
            "reference_sha256": _source_receipt_entry(reference_sha256),
        },
    )
    output = path_from_root(os.environ.get("PHASE3_WGS_FAST_OUTPUT", DEFAULT_OUTPUT))
    return manifest, output


def main() -> None:
    manifest, output = load_manifest_from_environment()
    write_manifest(output, manifest)
    print(f"Phase 3 WGS fast input manifest written: {output}")


if __name__ == "__main__":
    main()
