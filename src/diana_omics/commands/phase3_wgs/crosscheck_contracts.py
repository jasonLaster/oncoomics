from __future__ import annotations

from typing import Any, Mapping

from .render_phase3_fast_input_manifest import HEX64, ManifestError, _require_s3_uri, normalize_method_parameters


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
        raise ManifestError(f"{label} must be a positive integer")
    return value


def _source_blob(value: Any, label: str) -> dict[str, Any]:
    source = _require_mapping(value, label)
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{label}.uri"),
        "version_id": _require_string(source.get("version_id"), f"{label}.version_id"),
        "bytes": _require_positive_int(source.get("bytes"), f"{label}.bytes"),
        "sha256": _require_hex(source.get("sha256"), f"{label}.sha256"),
    }


def _sample_source_blob(value: Any, label: str, *, expected_sample_id: str) -> dict[str, Any]:
    source = _require_mapping(value, label)
    sample_id = _require_string(source.get("sample_id"), f"{label}.sample_id")
    if sample_id != expected_sample_id:
        raise ManifestError(f"{label}.sample_id must be {expected_sample_id}")
    return _source_blob(source, label)


def sequenza_alias_input_contract(
    *,
    run_alias: Any,
    reference: Mapping[str, Any],
    tumor: Mapping[str, Any],
    normal: Mapping[str, Any],
    method_parameters: Any,
) -> dict[str, Any]:
    subject_alias = _require_string(run_alias, "run.subject_alias")
    normalized_method_parameters = normalize_method_parameters(method_parameters)
    tumor_alias = f"{subject_alias}_tumor"
    normal_alias = f"{subject_alias}_normal"

    return {
        "schema_version": 1,
        "route": "sequenza_scarhrd",
        "status": "blocked",
        "run_alias": subject_alias,
        "reference": {
            "build": "GRCh38",
            "fasta": _source_blob(reference.get("fasta"), "input_sources.reference.fasta"),
            "fai": _source_blob(reference.get("fai"), "input_sources.reference.fai"),
            "sequence_dictionary": _source_blob(
                reference.get("sequence_dictionary"),
                "input_sources.reference.sequence_dictionary",
            ),
        },
        "artifacts": {
            "tumor_bam": _sample_source_blob(
                tumor.get("bam"),
                "input_sources.bam_pair.tumor.bam",
                expected_sample_id=tumor_alias,
            ),
            "tumor_bai": _sample_source_blob(
                tumor.get("bai"),
                "input_sources.bam_pair.tumor.bai",
                expected_sample_id=tumor_alias,
            ),
            "normal_bam": _sample_source_blob(
                normal.get("bam"),
                "input_sources.bam_pair.normal.bam",
                expected_sample_id=normal_alias,
            ),
            "normal_bai": _sample_source_blob(
                normal.get("bai"),
                "input_sources.bam_pair.normal.bai",
                expected_sample_id=normal_alias,
            ),
        },
        "method_parameters": normalized_method_parameters,
        "planned_aliases": {
            "tumor_sample": tumor_alias,
            "normal_sample": normal_alias,
        },
        "planned_alias_outputs": {
            "tumor_bam": "tumor.bam",
            "tumor_bai": "tumor.bam.bai",
            "normal_bam": "normal.bam",
            "normal_bai": "normal.bam.bai",
            "staged_validation": "staged_input_validation.json",
        },
        "attestations": {
            "input_sha256_verified": True,
            "bam_quickcheck_passed": True,
            "bam_reference_digest_matched": True,
            "no_direct_identifiers_in_aliases": True,
            "final_bam_contract_published": False,
            "validated_sequenza_scarhrd_runtime": False,
        },
    }
