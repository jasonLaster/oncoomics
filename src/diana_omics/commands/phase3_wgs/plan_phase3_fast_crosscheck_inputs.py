from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError, _require_s3_uri, normalize_method_parameters

DEFAULT_FINAL_EVIDENCE = "manifests/phase3_wgs_fast/final_evidence_manifest.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/crosscheck_materialization_plan.json"

FINAL_ARTIFACT_ROLES = {
    "source_vcf": "filtered_vcf",
    "source_vcf_index": "filtered_vcf_index",
    "source_matrix": "sbs96_matrix",
}
REFERENCE_ROLES = {
    "reference_fasta": "fasta",
    "reference_fai": "fai",
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
        raise ManifestError(f"{label} must be a positive integer")
    return value


def _require_relative_path(value: Any, label: str) -> str:
    text = _require_string(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != text:
        raise ManifestError(f"{label} must be a safe relative POSIX path")
    return text


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_blob(value: Any, label: str) -> dict[str, Any]:
    source = _require_mapping(value, label)
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{label}.uri"),
        "version_id": _require_string(source.get("version_id"), f"{label}.version_id"),
        "bytes": _require_positive_int(source.get("bytes"), f"{label}.bytes"),
        "sha256": _require_hex(source.get("sha256"), f"{label}.sha256"),
    }


def _sample_source_blob(value: Any, label: str) -> dict[str, Any]:
    source = _source_blob(value, label)
    return {
        **source,
        "sample_id": _require_string(
            _require_mapping(value, label).get("sample_id"),
            f"{label}.sample_id",
        ),
    }


def _sequenza_alias_input_contract(
    *,
    run: Mapping[str, Any],
    reference: Mapping[str, Any],
    tumor: Mapping[str, Any],
    normal: Mapping[str, Any],
    method_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    run_alias = _require_string(run.get("subject_alias"), "run.subject_alias")
    return {
        "schema_version": 1,
        "route": "sequenza_scarhrd",
        "status": "blocked",
        "run_alias": run_alias,
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
            "tumor_bam": _sample_source_blob(tumor.get("bam"), "input_sources.bam_pair.tumor.bam"),
            "tumor_bai": _sample_source_blob(tumor.get("bai"), "input_sources.bam_pair.tumor.bai"),
            "normal_bam": _sample_source_blob(normal.get("bam"), "input_sources.bam_pair.normal.bam"),
            "normal_bai": _sample_source_blob(normal.get("bai"), "input_sources.bam_pair.normal.bai"),
        },
        "method_parameters": {
            "sequenza": {
                "female": method_parameters["sequenza"]["female"],
            },
        },
        "planned_aliases": {
            "tumor_sample": f"{run_alias}_tumor",
            "normal_sample": f"{run_alias}_normal",
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


def _final_artifact(value: Any, role: str) -> dict[str, Any]:
    row = _require_mapping(value, f"artifacts.small_variants.filter_mutect.{role}")
    return {
        "final_relative_path": _require_relative_path(
            row.get("relative_path"),
            f"artifacts.small_variants.filter_mutect.{role}.relative_path",
        ),
        "bytes": _require_positive_int(row.get("bytes"), f"artifacts.small_variants.filter_mutect.{role}.bytes"),
        "sha256": _require_hex(row.get("sha256"), f"artifacts.small_variants.filter_mutect.{role}.sha256"),
    }


def _require_final_evidence(final_evidence: Mapping[str, Any]) -> None:
    if final_evidence.get("manifest_type") != "phase3_wgs_fast_final_evidence_manifest":
        raise ManifestError("final evidence manifest_type must be phase3_wgs_fast_final_evidence_manifest")
    if final_evidence.get("status") != "completed":
        raise ManifestError("final evidence status must be completed")

    interpretation = _require_mapping(final_evidence.get("interpretation"), "interpretation")
    expected = {
        "authorized_hrd_state": "no_call",
        "sbs96_use": "input_matrix_not_validated_sbs3_assignment",
        "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
        "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
        "hrdetect_use": "no_call_requires_validated_structural_variant_features",
    }
    for key, value in expected.items():
        if interpretation.get(key) != value:
            raise ManifestError(f"final evidence {key} must remain {value}")


def build_phase3_fast_crosscheck_materialization_plan(
    final_evidence: Mapping[str, Any],
    *,
    final_evidence_sha256: str,
) -> dict[str, Any]:
    _require_final_evidence(final_evidence)
    artifacts = _require_mapping(final_evidence.get("artifacts"), "artifacts")
    small_variants = _require_mapping(artifacts.get("small_variants"), "artifacts.small_variants")
    filter_mutect = _require_mapping(small_variants.get("filter_mutect"), "artifacts.small_variants.filter_mutect")
    input_sources = _require_mapping(final_evidence.get("input_sources"), "input_sources")
    reference = _require_mapping(input_sources.get("reference"), "input_sources.reference")
    bam_pair = _require_mapping(input_sources.get("bam_pair"), "input_sources.bam_pair")
    tumor = _require_mapping(bam_pair.get("tumor"), "input_sources.bam_pair.tumor")
    normal = _require_mapping(bam_pair.get("normal"), "input_sources.bam_pair.normal")
    method_parameters = normalize_method_parameters(final_evidence.get("method_parameters"))

    final_sources = {
        materializer_role: {
            **_final_artifact(filter_mutect.get(final_role), final_role),
            "materializer_sha256_parameter": f"{materializer_role}_sha256",
            "materializer_version_parameter": f"{materializer_role}_version_id",
        }
        for materializer_role, final_role in FINAL_ARTIFACT_ROLES.items()
    }
    reference_sources = {
        materializer_role: {
            **_source_blob(reference.get(reference_role), f"input_sources.reference.{reference_role}"),
            "materializer_uri_parameter": f"{materializer_role}_uri",
            "materializer_sha256_parameter": f"{materializer_role}_sha256",
            "materializer_version_parameter": f"{materializer_role}_version_id",
        }
        for materializer_role, reference_role in REFERENCE_ROLES.items()
    }
    run = dict(_require_mapping(final_evidence.get("run"), "run"))
    sequenza_alias_contract = _sequenza_alias_input_contract(
        run=run,
        reference=reference,
        tumor=tumor,
        normal=normal,
        method_parameters=method_parameters,
    )

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_crosscheck_materialization_plan",
        "status": "awaiting_private_results_freeze",
        "workflow": dict(_require_mapping(final_evidence.get("workflow"), "workflow")),
        "run": run,
        "source": {
            "final_evidence_manifest_sha256": _require_hex(final_evidence_sha256, "final_evidence_sha256"),
        },
        "sigprofiler_sbs3": {
            "status": "awaiting_private_results_freeze",
            "materializer_script": "scripts/materialize_crosscheck_inputs.py",
            "run_alias": _require_string(run.get("subject_alias"), "run.subject_alias"),
            "final_sources": final_sources,
            "reference_sources": reference_sources,
            "outputs": {
                "somatic_vcf": "somatic.pass.vcf.gz",
                "somatic_vcf_index": "somatic.pass.vcf.gz.tbi",
                "sbs96_matrix": "sbs96.csv",
                "staged_input_validation": "staged_input_validation.json",
            },
        },
        "sequenza_scarhrd": {
            "status": "blocked",
            "execution_status": "not_run",
            "interpretation_status": "no_call",
            "method_parameters": {
                "sequenza": {
                    "female": method_parameters["sequenza"]["female"],
                },
            },
            "source_artifacts": {
                "tumor_bam": _sample_source_blob(tumor.get("bam"), "input_sources.bam_pair.tumor.bam"),
                "tumor_bai": _sample_source_blob(tumor.get("bai"), "input_sources.bam_pair.tumor.bai"),
                "normal_bam": _sample_source_blob(normal.get("bam"), "input_sources.bam_pair.normal.bam"),
                "normal_bai": _sample_source_blob(normal.get("bai"), "input_sources.bam_pair.normal.bai"),
            },
            "alias_input_contract": sequenza_alias_contract,
            "required_method_parameters": [],
            "blockers": [
                "awaiting_final_bam_contract",
                "awaiting_validated_sequenza_scarhrd_runtime",
            ],
        },
        "blocked_routes": {
            "sequenza_scarhrd": "awaiting_final_bam_contract_and_validated_runtime",
            "facets_scarhrd": "awaiting_allele_specific_cnv_loh_segments",
            "oncoanalyser_chord": "awaiting_validated_production_sv_caller_vcf",
            "hrdetect": "awaiting_validated_structural_variant_features",
        },
        "interpretation": dict(_require_mapping(final_evidence.get("interpretation"), "interpretation")),
    }


def write_plan(path: Path, plan: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_plan_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST", DEFAULT_FINAL_EVIDENCE))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN", DEFAULT_OUTPUT))
    plan = build_phase3_fast_crosscheck_materialization_plan(
        read_json(input_path),
        final_evidence_sha256=_sha256_path(input_path),
    )
    return plan, output_path


def main() -> None:
    plan, output = load_plan_from_environment()
    write_plan(output, plan)
    print(f"Phase 3 WGS fast cross-check materialization plan written: {output}")


if __name__ == "__main__":
    main()
