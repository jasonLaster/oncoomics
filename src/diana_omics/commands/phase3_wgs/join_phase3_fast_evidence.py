from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError, normalize_method_parameters

DEFAULT_SMALL_VARIANT_EXPORT = "manifests/phase3_wgs_fast/small_variant_artifact_export.json"
DEFAULT_BAM_QC_RECEIPT = "manifests/phase3_wgs_fast/bam_qc_receipt.json"
DEFAULT_CNV_EVIDENCE_RECEIPT = "manifests/phase3_wgs_fast/cnv_evidence_receipt.json"
DEFAULT_SV_EVIDENCE_RECEIPT = "manifests/phase3_wgs_fast/sv_evidence_receipt.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/evidence_join_manifest.json"

RECEIPT_MANIFEST_TYPES = {
    "small_variant_artifact_export": "phase3_wgs_fast_small_variant_artifact_export",
    "bam_qc": "phase3_wgs_fast_bam_qc_receipt",
    "cnv_evidence": "phase3_wgs_fast_cnv_evidence_receipt",
    "sv_evidence": "phase3_wgs_fast_sv_evidence_receipt",
}


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} must be 64 hex characters")
    return value.lower()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_receipt(
    receipt: Mapping[str, Any],
    key: str,
    *,
    manifest_type: str,
) -> None:
    if receipt.get("manifest_type") != manifest_type:
        raise ManifestError(f"{key} manifest_type must be {manifest_type}")
    if receipt.get("status") != "completed":
        raise ManifestError(f"{key} status must be completed")
    if _require_mapping(receipt.get("interpretation"), f"{key}.interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError(f"{key} authorized_hrd_state must remain no_call")


def _require_workflow_and_run_match(receipts: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    first_key = "small_variant_artifact_export"
    workflow = dict(_require_mapping(receipts[first_key].get("workflow"), f"{first_key}.workflow"))
    run = dict(_require_mapping(receipts[first_key].get("run"), f"{first_key}.run"))
    for key, receipt in receipts.items():
        if dict(_require_mapping(receipt.get("workflow"), f"{key}.workflow")) != workflow:
            raise ManifestError(f"{key} workflow must match small_variant_artifact_export workflow")
        if dict(_require_mapping(receipt.get("run"), f"{key}.run")) != run:
            raise ManifestError(f"{key} run must match small_variant_artifact_export run")
    return workflow, run


def _require_evidence_boundaries(receipts: Mapping[str, Mapping[str, Any]]) -> None:
    bam_qc = _require_mapping(receipts["bam_qc"].get("interpretation"), "bam_qc.interpretation")
    if bam_qc.get("hrd_use") != "qc_only_not_hrd_evidence":
        raise ManifestError("bam_qc hrd_use must remain qc_only_not_hrd_evidence")

    cnv = _require_mapping(receipts["cnv_evidence"].get("interpretation"), "cnv_evidence.interpretation")
    if cnv.get("scarhrd_use") != "no_call_requires_allele_specific_cnv_loh_segments":
        raise ManifestError("cnv_evidence scarhrd_use must remain no_call_requires_allele_specific_cnv_loh_segments")

    sv = _require_mapping(receipts["sv_evidence"].get("interpretation"), "sv_evidence.interpretation")
    if sv.get("chord_use") != "no_call_requires_validated_production_sv_caller_vcf":
        raise ManifestError("sv_evidence chord_use must remain no_call_requires_validated_production_sv_caller_vcf")
    if sv.get("hrdetect_use") != "no_call_requires_validated_structural_variant_features":
        raise ManifestError("sv_evidence hrdetect_use must remain no_call_requires_validated_structural_variant_features")


def _require_small_variant_exports(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    exports = _require_mapping(receipt.get("exports"), "small_variant_artifact_export.exports")
    _require_mapping(exports.get("parabricks_mutect"), "small_variant_artifact_export.exports.parabricks_mutect")
    _require_mapping(exports.get("filter_mutect"), "small_variant_artifact_export.exports.filter_mutect")
    return exports


def _require_materialized(receipt: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    materialized = _require_mapping(receipt.get("materialized_outputs"), f"{key}.materialized_outputs")
    if not materialized:
        raise ManifestError(f"{key} materialized_outputs must be non-empty")
    return materialized


def _require_input_sources(receipt: Mapping[str, Any]) -> dict[str, Any]:
    sources = _require_mapping(receipt.get("input_sources"), "small_variant_artifact_export.input_sources")
    for key in ("reference", "bam_pair", "caller_resources"):
        _require_mapping(sources.get(key), f"small_variant_artifact_export.input_sources.{key}")
    return dict(sources)


def _require_method_parameters_match(receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    method_parameters = normalize_method_parameters(receipts["small_variant_artifact_export"].get("method_parameters"))
    for key, receipt in receipts.items():
        if normalize_method_parameters(receipt.get("method_parameters")) != method_parameters:
            raise ManifestError(f"{key} method_parameters must match small_variant_artifact_export")
    return method_parameters


def build_phase3_fast_evidence_join_manifest(
    small_variant_artifact_export: Mapping[str, Any],
    bam_qc_receipt: Mapping[str, Any],
    cnv_evidence_receipt: Mapping[str, Any],
    sv_evidence_receipt: Mapping[str, Any],
    *,
    small_variant_artifact_export_sha256: str,
    bam_qc_receipt_sha256: str,
    cnv_evidence_receipt_sha256: str,
    sv_evidence_receipt_sha256: str,
) -> dict[str, Any]:
    receipt_hashes = {
        "small_variant_artifact_export": _require_hex(
            small_variant_artifact_export_sha256,
            "small_variant_artifact_export_sha256",
        ),
        "bam_qc": _require_hex(bam_qc_receipt_sha256, "bam_qc_receipt_sha256"),
        "cnv_evidence": _require_hex(cnv_evidence_receipt_sha256, "cnv_evidence_receipt_sha256"),
        "sv_evidence": _require_hex(sv_evidence_receipt_sha256, "sv_evidence_receipt_sha256"),
    }
    receipts = {
        "small_variant_artifact_export": small_variant_artifact_export,
        "bam_qc": bam_qc_receipt,
        "cnv_evidence": cnv_evidence_receipt,
        "sv_evidence": sv_evidence_receipt,
    }
    for key, manifest_type in RECEIPT_MANIFEST_TYPES.items():
        _require_receipt(receipts[key], key, manifest_type=manifest_type)
    workflow, run = _require_workflow_and_run_match(receipts)
    method_parameters = _require_method_parameters_match(receipts)
    _require_evidence_boundaries(receipts)

    small_variant_source = _require_mapping(
        small_variant_artifact_export.get("source"),
        "small_variant_artifact_export.source",
    )
    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_evidence_join_manifest",
        "status": "completed",
        "workflow": workflow,
        "run": run,
        "method_parameters": method_parameters,
        "source": {
            "parabricks_mutect_plan_sha256": _require_hex(
                small_variant_source.get("parabricks_mutect_plan_sha256"),
                "parabricks_mutect_plan_sha256",
            ),
            "filter_mutect_plan_sha256": _require_hex(
                small_variant_source.get("filter_mutect_plan_sha256"),
                "filter_mutect_plan_sha256",
            ),
            "receipt_sha256": receipt_hashes,
        },
        "evidence": {
            "small_variants": {
                "exports": dict(_require_small_variant_exports(small_variant_artifact_export)),
            },
            "bam_qc": {
                "materialized_outputs": dict(_require_materialized(bam_qc_receipt, "bam_qc")),
            },
            "cnv_evidence": {
                "materialized_outputs": dict(_require_materialized(cnv_evidence_receipt, "cnv_evidence")),
            },
            "sv_evidence": {
                "materialized_outputs": dict(_require_materialized(sv_evidence_receipt, "sv_evidence")),
                "metrics": dict(_require_mapping(sv_evidence_receipt.get("metrics"), "sv_evidence.metrics")),
            },
        },
        "input_sources": _require_input_sources(small_variant_artifact_export),
        "interpretation": {
            "authorized_hrd_state": "no_call",
            "small_variants_use": "deterministic_sample_evidence_not_scalar_hrd",
            "bam_qc_use": "qc_only_not_hrd_evidence",
            "sbs96_use": "input_matrix_not_validated_sbs3_assignment",
            "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
            "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
            "hrdetect_use": "no_call_requires_validated_structural_variant_features",
        },
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest_from_environment() -> tuple[dict[str, Any], Path]:
    small_variant_path = path_from_root(
        os.environ.get("PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT", DEFAULT_SMALL_VARIANT_EXPORT)
    )
    bam_qc_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_BAM_QC_RECEIPT", DEFAULT_BAM_QC_RECEIPT))
    cnv_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT", DEFAULT_CNV_EVIDENCE_RECEIPT))
    sv_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT", DEFAULT_SV_EVIDENCE_RECEIPT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_EVIDENCE_JOIN_OUTPUT", DEFAULT_OUTPUT))
    manifest = build_phase3_fast_evidence_join_manifest(
        read_json(small_variant_path),
        read_json(bam_qc_path),
        read_json(cnv_path),
        read_json(sv_path),
        small_variant_artifact_export_sha256=_sha256_path(small_variant_path),
        bam_qc_receipt_sha256=_sha256_path(bam_qc_path),
        cnv_evidence_receipt_sha256=_sha256_path(cnv_path),
        sv_evidence_receipt_sha256=_sha256_path(sv_path),
    )
    return manifest, output_path


def main() -> None:
    manifest, output = load_manifest_from_environment()
    write_manifest(output, manifest)
    print(f"Phase 3 WGS fast evidence join manifest written: {output}")


if __name__ == "__main__":
    main()
