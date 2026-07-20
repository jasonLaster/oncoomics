from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from ...paths import path_from_root
from ...utils import read_json
from .crosscheck_contracts import EXPECTED_CROSSCHECK_BLOCKED_ROUTES, sequenza_alias_input_contract
from .render_phase3_fast_input_manifest import HEX64, ManifestError, normalize_method_parameters
from .safe_json_output import (
    read_real_json,
    read_real_json_with_sha256_and_size,
    require_no_symlinked_ancestors,
    sha256_real_file,
)

DEFAULT_FINAL_EVIDENCE_MANIFEST = "manifests/phase3_wgs_fast/final_evidence_manifest.json"
DEFAULT_FINAL_EVIDENCE_ROOT = "workspace/results/phase3_wgs_fast/final"
DEFAULT_OUTPUT_ROOT = "workspace/results/phase3_wgs_fast/deterministic_report"
OUTPUT_NAMES = frozenset(
    {
        "report.md",
        "report_manifest.json",
        "readiness.csv",
        "evidence_checks.json",
        "input_sha256.csv",
        "crosscheck_input_plans.json",
    }
)
SUPPORT_NAMES = frozenset({"readiness.csv", "evidence_checks.json", "input_sha256.csv", "crosscheck_input_plans.json"})
EXPECTED_ARTIFACT_GROUPS = frozenset({"small_variants", "bam_qc", "cnv_evidence", "sv_evidence"})
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class FinalArtifact:
    input_id: str
    relative_path: str
    bytes: int
    sha256: str
    path: Path


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} must be 64 hex characters")
    return value


def _require_non_negative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ManifestError(f"{label} must be a non-negative integer")
    return value


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ManifestError(f"{label} must be a positive integer")
    return value


def _is_exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    return value


def _require_s3_uri(value: Any, label: str) -> str:
    uri = _require_string(value, label)
    if not uri.startswith("s3://") or uri == "s3://":
        raise ManifestError(f"{label} must be an s3:// URI")
    return uri


def _require_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    if "\\" in value:
        raise ManifestError(f"{label} must be a POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError(f"{label} must be a safe relative path")
    return path.as_posix()


def _sha256_path(path: Path) -> str:
    return sha256_real_file(path, ManifestError)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_manifest_file(path: Path, label: str) -> Mapping[str, Any]:
    value, _digest, _size = _read_manifest_file_with_sha256_and_size(path, label)
    return value


def _read_manifest_file_with_sha256_and_size(
    path: Path, label: str
) -> tuple[Mapping[str, Any], str, int]:
    value, digest, size = read_real_json_with_sha256_and_size(
        path, label, ManifestError
    )
    return _require_mapping(value, label), digest, size


def _require_unsymlinked_path(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ManifestError(f"{label} may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, label, ManifestError)


def _flatten_artifacts(
    value: Mapping[str, Any],
    *,
    final_root: Path,
    prefix: Sequence[str] = (),
) -> list[FinalArtifact]:
    if {"relative_path", "bytes", "sha256"}.issubset(value):
        if not prefix:
            raise ManifestError("artifact leaves must have a non-empty input ID")
        relative = _require_relative_path(value.get("relative_path"), ".".join((*prefix, "relative_path")))
        return [
            FinalArtifact(
                input_id=".".join(prefix),
                relative_path=relative,
                bytes=_require_non_negative_int(value.get("bytes"), ".".join((*prefix, "bytes"))),
                sha256=_require_hex(value.get("sha256"), ".".join((*prefix, "sha256"))),
                path=final_root / relative,
            )
        ]

    artifacts: list[FinalArtifact] = []
    for key, child in sorted(value.items()):
        if not isinstance(key, str) or not key or "/" in key or key in {".", ".."}:
            raise ManifestError("artifact keys must be safe path segments")
        artifacts.extend(
            _flatten_artifacts(
                _require_mapping(child, ".".join((*prefix, key))),
                final_root=final_root,
                prefix=(*prefix, key),
            )
        )
    return artifacts


def _validate_final_manifest(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    if not _is_exact_int(manifest.get("schema_version"), 1):
        raise ManifestError("final evidence schema_version must be 1")
    if manifest.get("manifest_type") != "phase3_wgs_fast_final_evidence_manifest":
        raise ManifestError("final evidence manifest_type must be phase3_wgs_fast_final_evidence_manifest")
    if manifest.get("status") != "completed":
        raise ManifestError("final evidence status must be completed")

    workflow = _require_mapping(manifest.get("workflow"), "workflow")
    if workflow.get("name") != "phase3_wgs_fast":
        raise ManifestError("final evidence workflow.name must be phase3_wgs_fast")

    interpretation = _require_mapping(manifest.get("interpretation"), "interpretation")
    expected_interpretation = {
        "authorized_hrd_state": "no_call",
        "small_variants_use": "deterministic_sample_evidence_not_scalar_hrd",
        "bam_qc_use": "qc_only_not_hrd_evidence",
        "sbs96_use": "input_matrix_not_validated_sbs3_assignment",
        "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
        "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
        "hrdetect_use": "no_call_requires_validated_structural_variant_features",
    }
    for key, expected in expected_interpretation.items():
        if interpretation.get(key) != expected:
            raise ManifestError(f"final evidence {key} must remain {expected}")

    artifacts = _require_mapping(manifest.get("artifacts"), "artifacts")
    if set(artifacts) != EXPECTED_ARTIFACT_GROUPS:
        raise ManifestError("final evidence artifacts must contain small_variants, bam_qc, cnv_evidence, and sv_evidence")
    return artifacts


def _validate_artifacts(final_root: Path, artifacts: Sequence[FinalArtifact]) -> None:
    if final_root.is_symlink() or not final_root.is_dir():
        raise ManifestError("final evidence root must be a real directory")

    expected_paths = {artifact.path for artifact in artifacts}
    if len(expected_paths) != len(artifacts):
        raise ManifestError("final evidence manifest artifact paths must be unique")

    input_ids = {artifact.input_id for artifact in artifacts}
    if len(input_ids) != len(artifacts):
        raise ManifestError("final evidence manifest artifact input IDs must be unique")

    expected_empty_paths = {artifact.path for artifact in artifacts if artifact.sha256 == EMPTY_SHA256}
    for artifact in artifacts:
        _require_unsymlinked_path(artifact.path, f"{artifact.input_id} final artifact")
        if not artifact.path.is_file():
            raise ManifestError(f"{artifact.input_id} final artifact is missing: {artifact.relative_path}")
        if artifact.path.stat().st_size != artifact.bytes:
            raise ManifestError(f"{artifact.input_id} final artifact byte count changed: {artifact.relative_path}")
        if _sha256_path(artifact.path) != artifact.sha256:
            raise ManifestError(f"{artifact.input_id} final artifact SHA-256 changed: {artifact.relative_path}")
        if artifact.bytes == 0 and artifact.path not in expected_empty_paths:
            raise ManifestError(f"{artifact.input_id} zero-byte artifact is not explicitly hash-bound")

    unexpected = sorted(
        path.relative_to(final_root).as_posix()
        for path in final_root.rglob("*")
        if path.is_file() and path not in expected_paths
    )
    symlinked = next((path for path in final_root.rglob("*") if path.is_symlink()), None)
    if symlinked is not None:
        raise ManifestError(f"final evidence root contains a symlink: {symlinked.relative_to(final_root).as_posix()}")
    if unexpected:
        raise ManifestError(f"final evidence root contains an unmanifested file: {unexpected[0]}")


def _artifact_counts(artifacts: Sequence[FinalArtifact]) -> dict[str, int]:
    counts = {group: 0 for group in sorted(EXPECTED_ARTIFACT_GROUPS)}
    for artifact in artifacts:
        counts[artifact.input_id.split(".", 1)[0]] += 1
    return counts


def _read_json_artifact(final_root: Path, artifact_map: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    row = _artifact_row(artifact_map, *path)
    label = ".".join(path)
    relative = _require_relative_path(row.get("relative_path"), f"{label}.relative_path")
    return _require_mapping(read_json(final_root / relative), label)


def _read_text_artifact(final_root: Path, artifact_map: Mapping[str, Any], *path: str) -> str:
    row = _artifact_row(artifact_map, *path)
    label = ".".join(path)
    relative = _require_relative_path(row.get("relative_path"), f"{label}.relative_path")
    return (final_root / relative).read_text(encoding="utf-8", errors="replace")


def _artifact_row(artifact_map: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    current: Any = artifact_map
    label = ".".join(path)
    for part in path:
        current = _require_mapping(current, label).get(part)
    return _require_mapping(current, label)


def _planned_artifact(artifact_map: Mapping[str, Any], input_id: str, *path: str) -> dict[str, Any]:
    row = _artifact_row(artifact_map, *path)
    return {
        "input_id": input_id,
        "path": f"final/{_require_relative_path(row.get('relative_path'), f'{input_id}.relative_path')}",
        "bytes": _require_non_negative_int(row.get("bytes"), f"{input_id}.bytes"),
        "sha256": _require_hex(row.get("sha256"), f"{input_id}.sha256"),
    }


def _source_identity(input_sources: Mapping[str, Any], label: str, *path: str) -> dict[str, Any]:
    current: Any = input_sources
    for part in path:
        current = _require_mapping(current, label).get(part)
    source = _require_mapping(current, label)
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{label}.uri"),
        "version_id": _require_string(source.get("version_id"), f"{label}.version_id"),
        "bytes": _require_positive_int(source.get("bytes"), f"{label}.bytes"),
        "sha256": _require_hex(source.get("sha256"), f"{label}.sha256"),
    }


def _planned_sigprofiler_source(
    crosscheck_materialization_plan: Mapping[str, Any],
    artifact_map: Mapping[str, Any],
    materializer_role: str,
    input_id: str,
    *artifact_path: str,
) -> dict[str, Any]:
    sigprofiler = _require_mapping(
        crosscheck_materialization_plan.get("sigprofiler_sbs3"),
        "crosscheck_materialization_plan.sigprofiler_sbs3",
    )
    final_sources = _require_mapping(
        sigprofiler.get("final_sources"),
        "crosscheck_materialization_plan.sigprofiler_sbs3.final_sources",
    )
    planned = _require_mapping(
        final_sources.get(materializer_role),
        f"crosscheck_materialization_plan.sigprofiler_sbs3.final_sources.{materializer_role}",
    )
    expected = _planned_artifact(artifact_map, input_id, *artifact_path)
    actual = {
        "input_id": input_id,
        "path": f"final/{_require_relative_path(planned.get('final_relative_path'), f'{materializer_role}.final_relative_path')}",
        "bytes": _require_non_negative_int(planned.get("bytes"), f"{materializer_role}.bytes"),
        "sha256": _require_hex(planned.get("sha256"), f"{materializer_role}.sha256"),
    }
    if actual != expected:
        raise ManifestError(f"{materializer_role} cross-check plan source differs from the final evidence manifest")
    return actual


def _planned_sigprofiler_reference(
    crosscheck_materialization_plan: Mapping[str, Any],
    input_sources: Mapping[str, Any],
    materializer_role: str,
    final_role: str,
) -> dict[str, Any]:
    sigprofiler = _require_mapping(
        crosscheck_materialization_plan.get("sigprofiler_sbs3"),
        "crosscheck_materialization_plan.sigprofiler_sbs3",
    )
    reference_sources = _require_mapping(
        sigprofiler.get("reference_sources"),
        "crosscheck_materialization_plan.sigprofiler_sbs3.reference_sources",
    )
    planned = _source_identity(
        reference_sources,
        f"crosscheck_materialization_plan.sigprofiler_sbs3.reference_sources.{materializer_role}",
        materializer_role,
    )
    expected = _source_identity(
        input_sources,
        f"input_sources.reference.{final_role}",
        "reference",
        final_role,
    )
    if planned != expected:
        raise ManifestError(f"{materializer_role} cross-check reference differs from the final evidence manifest")
    return planned


def _validate_crosscheck_materialization_plan(
    crosscheck_materialization_plan: Mapping[str, Any],
    *,
    final_manifest_sha256: str,
    final_manifest: Mapping[str, Any],
) -> None:
    if not _is_exact_int(crosscheck_materialization_plan.get("schema_version"), 1):
        raise ManifestError("cross-check materialization plan schema_version must be 1")
    if (
        crosscheck_materialization_plan.get("manifest_type")
        != "phase3_wgs_fast_crosscheck_materialization_plan"
    ):
        raise ManifestError(
            "cross-check materialization plan manifest_type must be "
            "phase3_wgs_fast_crosscheck_materialization_plan"
        )
    if crosscheck_materialization_plan.get("status") != "awaiting_private_results_freeze":
        raise ManifestError("cross-check materialization plan must await the private results freeze")
    if crosscheck_materialization_plan.get("blocked_routes") != EXPECTED_CROSSCHECK_BLOCKED_ROUTES:
        raise ManifestError("cross-check materialization plan blocked routes are not exact")

    source = _require_mapping(crosscheck_materialization_plan.get("source"), "crosscheck_materialization_plan.source")
    if _require_hex(source.get("final_evidence_manifest_sha256"), "source.final_evidence_manifest_sha256") != final_manifest_sha256:
        raise ManifestError("cross-check materialization plan is not bound to this final evidence manifest")

    run = _require_mapping(crosscheck_materialization_plan.get("run"), "crosscheck_materialization_plan.run")
    expected_run = _require_mapping(final_manifest.get("run"), "run")
    for key in ("run_id", "subject_alias", "pair_id"):
        if run.get(key) != expected_run.get(key):
            raise ManifestError(f"cross-check materialization plan run.{key} differs from the final evidence manifest")

    interpretation = _require_mapping(
        crosscheck_materialization_plan.get("interpretation"),
        "crosscheck_materialization_plan.interpretation",
    )
    if interpretation != _require_mapping(final_manifest.get("interpretation"), "interpretation"):
        raise ManifestError("cross-check materialization plan interpretation differs from the final evidence manifest")

    sigprofiler = _require_mapping(
        crosscheck_materialization_plan.get("sigprofiler_sbs3"),
        "crosscheck_materialization_plan.sigprofiler_sbs3",
    )
    if sigprofiler.get("status") != "awaiting_private_results_freeze":
        raise ManifestError("SigProfiler/SBS3 must still await the private results freeze")
    if sigprofiler.get("materializer_script") != "scripts/materialize_crosscheck_inputs.py":
        raise ManifestError("SigProfiler/SBS3 must use the reviewed materializer")
    if _require_string(sigprofiler.get("run_alias"), "sigprofiler_sbs3.run_alias") != expected_run.get("subject_alias"):
        raise ManifestError("SigProfiler/SBS3 run_alias differs from the final evidence manifest")
    outputs = _require_mapping(
        sigprofiler.get("outputs"),
        "crosscheck_materialization_plan.sigprofiler_sbs3.outputs",
    )
    if outputs != {
        "somatic_vcf": "somatic.pass.vcf.gz",
        "somatic_vcf_index": "somatic.pass.vcf.gz.tbi",
        "sbs96_matrix": "sbs96.csv",
        "staged_input_validation": "staged_input_validation.json",
    }:
        raise ManifestError("SigProfiler/SBS3 planned alias outputs are not exact")

    sequenza = _require_mapping(
        crosscheck_materialization_plan.get("sequenza_scarhrd"),
        "crosscheck_materialization_plan.sequenza_scarhrd",
    )
    if sequenza.get("status") != "blocked" or sequenza.get("interpretation_status") != "no_call":
        raise ManifestError("Sequenza/scarHRD must remain blocked and no_call")
    alias_contract = _require_mapping(
        sequenza.get("alias_input_contract"),
        "crosscheck_materialization_plan.sequenza_scarhrd.alias_input_contract",
    )
    if alias_contract.get("status") != "blocked":
        raise ManifestError("Sequenza/scarHRD alias input contract must stay blocked")
    input_sources = _require_mapping(final_manifest.get("input_sources"), "input_sources")
    method_parameters = normalize_method_parameters(final_manifest.get("method_parameters"))
    bam_pair = _require_mapping(input_sources.get("bam_pair"), "input_sources.bam_pair")
    expected_alias_contract = sequenza_alias_input_contract(
        run_alias=expected_run.get("subject_alias"),
        reference=_require_mapping(input_sources.get("reference"), "input_sources.reference"),
        tumor=_require_mapping(bam_pair.get("tumor"), "input_sources.bam_pair.tumor"),
        normal=_require_mapping(bam_pair.get("normal"), "input_sources.bam_pair.normal"),
        method_parameters=method_parameters,
    )
    if alias_contract != expected_alias_contract:
        raise ManifestError("Sequenza/scarHRD alias input contract differs from the final evidence manifest")


def _cnv_metric(cnv_summary: Mapping[str, Any], key: str) -> Any:
    if key in cnv_summary:
        return cnv_summary[key]
    rows = cnv_summary.get("rows")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0].get(key, "unknown")
    return "unknown"


def _summary_metric(summary: Mapping[str, Any], key: str) -> Any:
    if key in summary:
        return summary[key]
    rows = summary.get("rows")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0].get(key, "unknown")
    return "unknown"


def _build_input_rows(
    *,
    final_manifest_sha256: str,
    final_manifest_bytes: int,
    artifacts: Sequence[FinalArtifact],
) -> list[dict[str, Any]]:
    return [
        {
            "input_id": "final_evidence_manifest",
            "path": "manifest/final_evidence_manifest.json",
            "bytes": _require_positive_int(final_manifest_bytes, "final_manifest_bytes"),
            "sha256": final_manifest_sha256,
        },
        *[
            {
                "input_id": artifact.input_id,
                "path": f"final/{artifact.relative_path}",
                "bytes": artifact.bytes,
                "sha256": artifact.sha256,
            }
            for artifact in sorted(artifacts, key=lambda artifact: artifact.input_id)
        ],
    ]


def _readiness_rows(
    *,
    artifact_counts: Mapping[str, int],
    cnv_summary: Mapping[str, Any],
    sbs96_summary: Mapping[str, Any],
    sv_supplementary_total: int,
) -> list[dict[str, str]]:
    return [
        {
            "evidence_surface": "source_sha256",
            "state": "ready",
            "reason": "The final evidence manifest and every materialized final artifact matched its SHA-256 and byte count.",
        },
        {
            "evidence_surface": "small_variants",
            "state": "ready",
            "reason": f"{artifact_counts['small_variants']} Parabricks/FilterMutect small-variant artifacts were materialized.",
        },
        {
            "evidence_surface": "bam_qc",
            "state": "ready",
            "reason": f"{artifact_counts['bam_qc']} tumor/normal quickcheck, flagstat, and idxstats outputs were materialized.",
        },
        {
            "evidence_surface": "coverage_cnv",
            "state": "partial_evidence",
            "reason": (
                f"{_cnv_metric(cnv_summary, 'bin_count')} coverage bins were materialized; "
                "they are depth-only and not allele-specific CNV/LOH segments."
            ),
        },
        {
            "evidence_surface": "sv",
            "state": "partial_evidence",
            "reason": (
                f"BAM-derived evidence counted {sv_supplementary_total} supplementary alignments across tumor and normal; "
                "no production SV VCF/BEDPE exists."
            ),
        },
        {
            "evidence_surface": "sbs96",
            "state": "partial_evidence",
            "reason": (
                f"{_summary_metric(sbs96_summary, 'usable_snv_records')} usable PASS SNV alleles were "
                "materialized into an SBS96 matrix; SBS3 assignment is not validated."
            ),
        },
        {
            "evidence_surface": "scarHRD",
            "state": "no_call",
            "reason": "Validated allele-specific total/minor copy-number segments and a purity/ploidy solution are absent.",
        },
        {
            "evidence_surface": "CHORD",
            "state": "no_call",
            "reason": "A validated production structural-variant callset is absent.",
        },
        {
            "evidence_surface": "HRDetect",
            "state": "no_call",
            "reason": "The SBS3, indel, CNV/LOH, SV, and calibrated integration policy inputs are not all present.",
        },
        {
            "evidence_surface": "overall_hrd",
            "state": "no_call",
            "reason": "The deterministic evidence is partial and cannot support a scalar HRD classification.",
        },
    ]


def _build_crosscheck_input_plans(
    manifest: Mapping[str, Any],
    artifact_map: Mapping[str, Any],
    crosscheck_materialization_plan: Mapping[str, Any],
    *,
    final_manifest_sha256: str,
) -> dict[str, Any]:
    _validate_crosscheck_materialization_plan(
        crosscheck_materialization_plan,
        final_manifest_sha256=final_manifest_sha256,
        final_manifest=manifest,
    )
    input_sources = _require_mapping(manifest.get("input_sources"), "input_sources")
    sigprofiler = _require_mapping(
        crosscheck_materialization_plan.get("sigprofiler_sbs3"),
        "crosscheck_materialization_plan.sigprofiler_sbs3",
    )
    outputs = _require_mapping(
        sigprofiler.get("outputs"),
        "crosscheck_materialization_plan.sigprofiler_sbs3.outputs",
    )
    sequenza = _require_mapping(
        crosscheck_materialization_plan.get("sequenza_scarhrd"),
        "crosscheck_materialization_plan.sequenza_scarhrd",
    )
    sigprofiler_sources = {
        "source_vcf": _planned_sigprofiler_source(
            crosscheck_materialization_plan,
            artifact_map,
            "source_vcf",
            "small_variants.filter_mutect.filtered_vcf",
            "small_variants",
            "filter_mutect",
            "filtered_vcf",
        ),
        "source_vcf_index": _planned_sigprofiler_source(
            crosscheck_materialization_plan,
            artifact_map,
            "source_vcf_index",
            "small_variants.filter_mutect.filtered_vcf_index",
            "small_variants",
            "filter_mutect",
            "filtered_vcf_index",
        ),
        "source_sbs96_matrix": _planned_sigprofiler_source(
            crosscheck_materialization_plan,
            artifact_map,
            "source_matrix",
            "small_variants.filter_mutect.sbs96_matrix",
            "small_variants",
            "filter_mutect",
            "sbs96_matrix",
        ),
    }
    alias_contract = _require_mapping(
        sequenza.get("alias_input_contract"),
        "crosscheck_materialization_plan.sequenza_scarhrd.alias_input_contract",
    )
    return {
        "schema_version": 1,
        "plan_type": "phase3_fast_crosscheck_input_materialization_plan",
        "status": "awaiting_private_results_freeze",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "routes": {
            "sigprofiler_sbs3": {
                "status": "awaiting_private_results_freeze",
                "execution_status": "not_run",
                "interpretation_status": "no_call",
                "materializer": _require_string(sigprofiler.get("materializer_script"), "sigprofiler_sbs3.materializer_script"),
                "source_artifacts": sigprofiler_sources,
                "reference": {
                    "fasta": _planned_sigprofiler_reference(
                        crosscheck_materialization_plan,
                        input_sources,
                        "reference_fasta",
                        "fasta",
                    ),
                    "fai": _planned_sigprofiler_reference(
                        crosscheck_materialization_plan,
                        input_sources,
                        "reference_fai",
                        "fai",
                    ),
                    "sequence_dictionary": _source_identity(
                        input_sources,
                        "reference.sequence_dictionary",
                        "reference",
                        "sequence_dictionary",
                    ),
                },
                "planned_alias_outputs": {
                    "somatic_vcf": _require_string(outputs.get("somatic_vcf"), "sigprofiler_sbs3.outputs.somatic_vcf"),
                    "somatic_vcf_index": _require_string(outputs.get("somatic_vcf_index"), "sigprofiler_sbs3.outputs.somatic_vcf_index"),
                    "sbs96_matrix": _require_string(outputs.get("sbs96_matrix"), "sigprofiler_sbs3.outputs.sbs96_matrix"),
                    "staged_validation": _require_string(outputs.get("staged_input_validation"), "sigprofiler_sbs3.outputs.staged_input_validation"),
                },
                "blockers": [
                    "The final evidence artifacts have not been frozen to private-results with exact S3 VersionIds.",
                    "Alias-only cross-check inputs have not been materialized.",
                    "SBS3 assignment and threshold policy are not validated.",
                ],
            },
            "sequenza_scarhrd": {
                "status": "blocked",
                "execution_status": "not_run",
                "interpretation_status": "no_call",
                "method_parameters": dict(
                    _require_mapping(sequenza.get("method_parameters"), "sequenza_scarhrd.method_parameters")
                ),
                "source_artifacts": dict(
                    _require_mapping(sequenza.get("source_artifacts"), "sequenza_scarhrd.source_artifacts")
                ),
                "alias_input_contract": dict(alias_contract),
                "blockers": [
                    "A finalized alias-only BAM/BAM-index contract has not been published for the Sequenza route.",
                    "Sequenza execution, purity/ploidy, and scarHRD interpretation thresholds are not validated.",
                ],
            },
        },
    }


def _markdown_table(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "_None._"
    headers = list(rows[0])
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(str(row.get(header, "")).replace("\n", " ") for header in headers) + " |")
    return "\n".join(output)


def _report_markdown(
    manifest: Mapping[str, Any],
    *,
    artifact_counts: Mapping[str, int],
    crosscheck_input_plans: Mapping[str, Any],
    readiness_rows: Sequence[Mapping[str, str]],
    cnv_summary: Mapping[str, Any],
    sbs96_summary: Mapping[str, Any],
    sv_supplementary_total: int,
) -> str:
    run = _require_mapping(manifest.get("run"), "run")
    workflow = _require_mapping(manifest.get("workflow"), "workflow")
    routes = _require_mapping(crosscheck_input_plans.get("routes"), "crosscheck_input_plans.routes")
    sigprofiler = _require_mapping(routes.get("sigprofiler_sbs3"), "sigprofiler_sbs3 route")
    sequenza = _require_mapping(routes.get("sequenza_scarhrd"), "sequenza_scarhrd route")
    total = sum(artifact_counts.values())
    return "\n".join(
        [
            "# Phase 3 fast deterministic WGS evidence report",
            "",
            f"Run ID: `{run.get('run_id', 'unknown')}`",
            f"Workflow: `{workflow.get('name', 'unknown')}`",
            f"Source commit: `{workflow.get('source_commit', 'unknown')}`",
            "",
            "## Result",
            "",
            (
                "This no-compute staging step verified the Phase 3 fast final evidence manifest and "
                f"{total} manifest-bound artifacts. It authorizes deterministic sample-evidence review only; "
                "overall HRD remains `no_call`."
            ),
            "",
            "## Evidence surfaces",
            "",
            _markdown_table(readiness_rows),
            "",
            "## Materialized artifact groups",
            "",
            _markdown_table(
                [
                    {"group": group, "artifact_count": count}
                    for group, count in sorted(artifact_counts.items())
                ]
            ),
            "",
            "## Coverage CNV",
            "",
            (
                f"The final tree includes `{_cnv_metric(cnv_summary, 'bin_count')}` depth bins "
                f"with `{_cnv_metric(cnv_summary, 'relative_gain_bins')}` relative-gain bins and "
                f"`{_cnv_metric(cnv_summary, 'relative_loss_bins')}` relative-loss bins. "
                "This is coverage evidence, not allele-specific total/minor CNV, LOH, or scarHRD input."
            ),
            "",
            "## Structural-variant evidence",
            "",
            (
                f"The final tree includes BAM-derived split/discordant-read counters with `{sv_supplementary_total}` "
                "supplementary alignments across tumor and normal. These counters are not a production SV VCF/BEDPE "
                "and do not unlock CHORD or HRDetect-style scoring."
            ),
            "",
            "## SBS96 input",
            "",
            (
            "The final tree includes a 96-channel SBS matrix with "
                f"`{_summary_metric(sbs96_summary, 'usable_snv_records')}` usable PASS SNV alleles. "
                "This is signature input evidence, not a validated SBS3 assignment."
            ),
            "",
            "## Cross-check materialization plans",
            "",
            _markdown_table(
                [
                    {
                        "route": "sigprofiler_sbs3",
                        "state": sigprofiler.get("status", "missing"),
                        "execution": sigprofiler.get("execution_status", "missing"),
                        "boundary": sigprofiler.get("interpretation_status", "missing"),
                    },
                    {
                        "route": "sequenza_scarhrd",
                        "state": sequenza.get("status", "missing"),
                        "execution": sequenza.get("execution_status", "missing"),
                        "boundary": sequenza.get("interpretation_status", "missing"),
                    },
                ]
            ),
            "",
            (
                "The SigProfiler/SBS3 route has a plan-ready alias materialization recipe for the filtered "
                "PASS VCF, VCF index, SBS96 matrix, and exact reference FASTA/FAI identities, but the "
                "materializer has not run and no SBS3 assignment or threshold policy is authorized. "
                "Sequenza/scarHRD has the BAM/BAM-index identities needed to start its materialization "
                "contract plus an explicit sex-model parameter, but it stays blocked until a finalized "
                "alias-only BAM contract and validated runtime exist."
            ),
            "",
            "## Blocked model routes",
            "",
            "- `scarHRD`: no allele-specific CNV/LOH segments and no purity/ploidy solution.",
            "- `CHORD`: no validated production SV callset.",
            "- `HRDetect`: no locked SBS3, indel, CNV/LOH, SV, and calibration policy.",
            "- `SBS3`: no validated signature assignment or threshold policy.",
            "",
            "## Next steps",
            "",
            "1. Keep this packet as the terminal manifest for the current fast-evidence seam.",
            "2. Run a validated signature-assignment adapter from the SBS96 matrix.",
            "3. Add allele-specific CNV/LOH and production SV callers to unlock scarHRD, CHORD, and HRDetect-style routes.",
            "4. Preserve `no_call` until every route-specific input and validation gate is present.",
            "",
        ]
    )


def _prepare_output_dir(output: Path) -> None:
    _require_unsymlinked_path(output, "deterministic report output")
    if output.is_symlink():
        raise ManifestError("deterministic report output may not be a symlink")
    if output.exists() and not output.is_dir():
        raise ManifestError(f"deterministic report output is not a directory: {output}")

    output.mkdir(parents=True, exist_ok=True)
    existing = sorted(path.name for path in output.iterdir())
    if existing:
        raise ManifestError("deterministic report output already contains files: " + ", ".join(existing))


def _write_support_files(
    staging: Path,
    *,
    report: str,
    crosscheck_input_plans: Mapping[str, Any],
    readiness_rows: Sequence[Mapping[str, str]],
    checks: Mapping[str, Any],
    input_rows: Sequence[Mapping[str, Any]],
) -> None:
    _write_staged_json(staging / "crosscheck_input_plans.json", crosscheck_input_plans)
    _write_staged_csv(
        staging / "readiness.csv",
        readiness_rows,
        ["evidence_surface", "state", "reason"],
    )
    _write_staged_json(staging / "evidence_checks.json", checks)
    _write_staged_csv(
        staging / "input_sha256.csv",
        input_rows,
        ["input_id", "path", "bytes", "sha256"],
    )
    _write_staged_text(staging / "report.md", report)


def _support_sha256(staging: Path) -> Mapping[str, str]:
    return {
        name: _sha256_path(staging / name)
        for name in sorted(SUPPORT_NAMES)
    }


def _require_real_file(path: Path, label: str) -> None:
    _require_unsymlinked_path(path, label)
    if not path.is_file():
        raise ManifestError(f"{label} must be a real file: {path}")


def _require_safe_new_staged_file(path: Path) -> Path:
    _require_unsymlinked_path(path, "staged deterministic report packet")
    if path.exists():
        raise ManifestError(f"staged deterministic report packet already exists: {path.name}")
    return path.resolve()


def _require_staged_packet(path: Path, expected_sha256: str | None = None) -> None:
    _require_real_file(path, "staged deterministic report packet")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ManifestError(f"staged deterministic report packet mode is not 0600: {path}")
    if expected_sha256 is not None and _sha256_path(path) != expected_sha256:
        raise ManifestError(f"staged deterministic report packet changed during write: {path.name}")


def _require_installed_packet(path: Path, expected_sha256: str) -> None:
    _require_real_file(path, "deterministic report packet")
    if _sha256_path(path) != expected_sha256:
        raise ManifestError(f"deterministic report packet changed during copy: {path.name}")


def _write_staged_bytes(path: Path, value: bytes) -> None:
    expected_sha256 = _sha256_bytes(value)
    path = _require_safe_new_staged_file(path)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
        _require_staged_packet(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_staged_text(path: Path, value: str) -> None:
    _write_staged_bytes(path, value.encode("utf-8"))


def _write_staged_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_staged_bytes(path, _json_bytes(value))


def _write_staged_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    _write_staged_text(path, handle.getvalue())


def _require_staged_report_manifest(staging: Path) -> None:
    manifest = _require_mapping(
        read_real_json(staging / "report_manifest.json", "staged report_manifest", ManifestError),
        "report_manifest",
    )
    support_sha256 = _require_mapping(
        manifest.get("support_sha256"),
        "report_manifest.support_sha256",
    )
    expected = [("report.md", _require_hex(manifest.get("report_sha256"), "report_sha256"))]
    for name in sorted(SUPPORT_NAMES):
        expected.append(
            (
                name,
                _require_hex(
                    support_sha256.get(name),
                    f"report_manifest.support_sha256.{name}",
                ),
            )
        )

    for name, digest in expected:
        _require_staged_packet(staging / name)
        if _sha256_path(staging / name) != digest:
            raise ManifestError(f"deterministic report manifest is stale for {name}")


def _install_packet(
    output: Path,
    *,
    staging: Path,
) -> None:
    installed: list[Path] = []
    try:
        for name in sorted(OUTPUT_NAMES):
            source = staging / name
            _require_staged_packet(source)
            expected_sha256 = _sha256_path(source)
            destination = output / name
            destination_preexisted = destination.exists() or destination.is_symlink()
            descriptor = -1
            try:
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                with source.open("rb") as source_handle:
                    with os.fdopen(descriptor, "wb") as destination_handle:
                        descriptor = -1
                        shutil.copyfileobj(source_handle, destination_handle)
                        destination_handle.flush()
                        os.fsync(destination_handle.fileno())
                _fsync_directory(output)
                _require_installed_packet(destination, expected_sha256)
                if _sha256_path(source) != expected_sha256:
                    raise ManifestError(f"staged deterministic report packet changed during copy: {name}")
            except Exception:
                if descriptor >= 0:
                    os.close(descriptor)
                if not destination_preexisted:
                    installed.append(destination)
                raise
            installed.append(destination)
        _fsync_directory(output)
    except Exception:
        for path in reversed(installed):
            path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def stage_phase3_fast_deterministic_report(
    final_manifest: Mapping[str, Any],
    crosscheck_materialization_plan: Mapping[str, Any],
    *,
    final_manifest_sha256: str,
    final_manifest_bytes: int,
    final_root: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    output = Path(output_dir)
    final = Path(final_root)
    _prepare_output_dir(output)

    artifact_map = _validate_final_manifest(final_manifest)
    artifacts = _flatten_artifacts(artifact_map, final_root=final)
    expected_artifact_count = _require_non_negative_int(final_manifest.get("artifact_count"), "artifact_count")
    if len(artifacts) != expected_artifact_count:
        raise ManifestError("final evidence artifact_count must match the recursive artifact inventory")
    _validate_artifacts(final, artifacts)

    cnv_summary = _read_json_artifact(final, artifact_map, "cnv_evidence", "summary_json")
    sbs96_summary = _read_json_artifact(
        final,
        artifact_map,
        "small_variants",
        "filter_mutect",
        "signature_summary_json",
    )
    sv_supplementary_total = sum(
        int(_read_text_artifact(final, artifact_map, "sv_evidence", role, "supplementary_alignments").strip())
        for role in ("tumor", "normal")
    )
    artifact_counts = _artifact_counts(artifacts)
    input_rows = _build_input_rows(
        final_manifest_sha256=_require_hex(final_manifest_sha256, "final_manifest_sha256"),
        final_manifest_bytes=final_manifest_bytes,
        artifacts=artifacts,
    )
    readiness_rows = _readiness_rows(
        artifact_counts=artifact_counts,
        cnv_summary=cnv_summary,
        sbs96_summary=sbs96_summary,
        sv_supplementary_total=sv_supplementary_total,
    )
    crosscheck_input_plans = _build_crosscheck_input_plans(
        final_manifest,
        artifact_map,
        crosscheck_materialization_plan,
        final_manifest_sha256=final_manifest_sha256,
    )
    checks = {
        "schema_version": 1,
        "status": "passed",
        "report_status": "partial_evidence",
        "overall_hrd_status": "no_call",
        "checks": [
            {
                "check_id": "final_manifest_contract",
                "status": "passed",
                "detail": "The final evidence manifest is completed, no-call, and emitted by phase3_wgs_fast.",
            },
            {
                "check_id": "final_artifact_sha256",
                "status": "passed",
                "detail": f"{len(artifacts)} materialized final artifacts matched their manifest byte counts and SHA-256 values.",
            },
            {
                "check_id": "model_boundaries",
                "status": "passed",
                "detail": "scarHRD, CHORD, HRDetect-style, SBS3, and scalar HRD states remain no_call or blocked.",
            },
            {
                "check_id": "crosscheck_input_materialization_plan",
                "status": "passed",
                "detail": (
                    "SigProfiler/SBS3 input materialization is bound to the "
                    "post-freeze plan; Sequenza/scarHRD has an explicit sex-model "
                    "parameter but remains blocked on a finalized BAM contract and "
                    "validated runtime."
                ),
            },
        ],
        "input_sha256": input_rows,
    }
    report = _report_markdown(
        final_manifest,
        artifact_counts=artifact_counts,
        crosscheck_input_plans=crosscheck_input_plans,
        readiness_rows=readiness_rows,
        cnv_summary=cnv_summary,
        sbs96_summary=sbs96_summary,
        sv_supplementary_total=sv_supplementary_total,
    )

    with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=str(output.parent)) as temporary:
        staging = Path(temporary)
        _write_support_files(
            staging,
            report=report,
            crosscheck_input_plans=crosscheck_input_plans,
            readiness_rows=readiness_rows,
            checks=checks,
            input_rows=input_rows,
        )
        report_sha256 = hashlib.sha256(report.encode("utf-8")).hexdigest()
        source_sha256 = {
            str(row["input_id"]): str(row["sha256"])
            for row in input_rows
        }
        report_manifest = {
            "schema_version": 1,
            "method_id": "deterministic_full_wgs",
            "report_kind": "phase3_fast_deterministic_evidence",
            "evidence_status": "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "support_sha256": dict(sorted(_support_sha256(staging).items())),
            "source_sha256": source_sha256,
            "report_sha256": report_sha256,
            "review_summary": {
                "overall": {
                    "evidence_status": "partial_evidence",
                    "authorized_hrd_state": "no_call",
                },
                "workflow": dict(_require_mapping(final_manifest.get("workflow"), "workflow")),
                "run": dict(_require_mapping(final_manifest.get("run"), "run")),
                "artifact_count": len(artifacts),
                "artifact_groups": dict(sorted(artifact_counts.items())),
                "blocked_routes": {
                    "SBS3": "no_call_requires_validated_signature_assignment_policy",
                    "scarHRD": "no_call_requires_allele_specific_cnv_loh_segments",
                    "CHORD": "no_call_requires_validated_production_sv_caller_vcf",
                    "HRDetect": "no_call_requires_validated_structural_variant_features",
                },
                "crosscheck_input_plans": {
                    "sigprofiler_sbs3": "awaiting_private_results_freeze",
                    "sequenza_scarhrd": "blocked",
                },
            },
        }
        _write_staged_json(staging / "report_manifest.json", report_manifest)
        _require_staged_report_manifest(staging)
        _install_packet(output, staging=staging)

    manifest_path = output / "report_manifest.json"
    written_manifest = _require_mapping(read_json(manifest_path), "report_manifest")
    if written_manifest != report_manifest:
        raise ManifestError("written report manifest differs from the generated manifest")
    if _parse_csv(output / "input_sha256.csv") != [
        {key: str(row[key]) for key in ("input_id", "path", "bytes", "sha256")}
        for row in input_rows
    ]:
        raise ManifestError("written input_sha256.csv differs from the generated input rows")

    return dict(report_manifest)


def load_report_from_environment() -> tuple[dict[str, Any], Path]:
    manifest_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST", DEFAULT_FINAL_EVIDENCE_MANIFEST))
    crosscheck_plan_path = path_from_root(
        os.environ.get(
            "PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN",
            "manifests/phase3_wgs_fast/crosscheck_materialization_plan.json",
        )
    )
    final_root = path_from_root(os.environ.get("PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT", DEFAULT_FINAL_EVIDENCE_ROOT))
    output = path_from_root(os.environ.get("PHASE3_WGS_FAST_DETERMINISTIC_REPORT_OUTPUT", DEFAULT_OUTPUT_ROOT))
    final_manifest, final_manifest_sha256, final_manifest_bytes = (
        _read_manifest_file_with_sha256_and_size(
            manifest_path, "final_evidence_manifest"
        )
    )
    crosscheck_plan = _read_manifest_file(
        crosscheck_plan_path, "crosscheck_materialization_plan"
    )

    manifest = stage_phase3_fast_deterministic_report(
        final_manifest,
        crosscheck_plan,
        final_manifest_sha256=final_manifest_sha256,
        final_manifest_bytes=final_manifest_bytes,
        final_root=final_root,
        output_dir=output,
    )
    return manifest, output


def main() -> None:
    _, output = load_report_from_environment()
    print(f"Phase 3 WGS fast deterministic report written: {output}")


if __name__ == "__main__":
    main()
