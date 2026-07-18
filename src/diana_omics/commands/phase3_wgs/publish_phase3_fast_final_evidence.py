from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError, normalize_method_parameters
from .safe_json_output import require_safe_output_path

DEFAULT_EVIDENCE_JOIN = "manifests/phase3_wgs_fast/evidence_join_manifest.json"
DEFAULT_SMALL_VARIANT_ARTIFACT_ROOT = "workspace/results/phase3_wgs_fast/small_variant_execution/artifacts"
DEFAULT_BAM_QC_ARTIFACT_ROOT = "workspace/results/phase3_wgs_fast/bam_qc"
DEFAULT_CNV_EVIDENCE_ARTIFACT_ROOT = "workspace/results/phase3_wgs_fast/cnv_evidence"
DEFAULT_SV_EVIDENCE_ARTIFACT_ROOT = "workspace/results/phase3_wgs_fast/sv_evidence"
DEFAULT_OUTPUT_ROOT = "workspace/results/phase3_wgs_fast/final"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/final_evidence_manifest.json"


@dataclass(frozen=True)
class CopySpec:
    source: Path
    relative_path: Path
    bytes: int
    sha256: str
    label: str


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} is required")
    return value


def _require_non_negative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ManifestError(f"{label} must be a non-negative integer")
    return value


def _require_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ManifestError(f"{label} must be 64 hex characters")
    return value.lower()


def _safe_segment(value: str, label: str) -> str:
    if not value or "/" in value or value in {".", ".."}:
        raise ManifestError(f"{label} must be a safe relative path segment")
    return value


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_safe_destination_path(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ManifestError(f"{label} may not be a symlink: {path}")

    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        next_parent = parent.parent
        if next_parent == parent:
            raise ManifestError(f"{label} parent does not exist: {path.parent}")
        parent = next_parent

    if parent.is_symlink():
        raise ManifestError(f"{label} parent may not be a symlink: {parent}")
    if not parent.is_dir():
        raise ManifestError(f"{label} parent is not a directory: {parent}")


def _require_completed_join(manifest: Mapping[str, Any]) -> None:
    if manifest.get("manifest_type") != "phase3_wgs_fast_evidence_join_manifest":
        raise ManifestError("evidence_join manifest_type must be phase3_wgs_fast_evidence_join_manifest")
    if manifest.get("status") != "completed":
        raise ManifestError("evidence_join status must be completed")

    interpretation = _require_mapping(manifest.get("interpretation"), "interpretation")
    if interpretation.get("authorized_hrd_state") != "no_call":
        raise ManifestError("evidence_join authorized_hrd_state must remain no_call")
    if interpretation.get("sbs96_use") != "input_matrix_not_validated_sbs3_assignment":
        raise ManifestError("evidence_join sbs96_use must remain no_call")
    if interpretation.get("scarhrd_use") != "no_call_requires_allele_specific_cnv_loh_segments":
        raise ManifestError("evidence_join scarhrd_use must remain no_call")
    if interpretation.get("chord_use") != "no_call_requires_validated_production_sv_caller_vcf":
        raise ManifestError("evidence_join chord_use must remain no_call")
    if interpretation.get("hrdetect_use") != "no_call_requires_validated_structural_variant_features":
        raise ManifestError("evidence_join hrdetect_use must remain no_call")


def _basename(row: Mapping[str, Any], label: str) -> str:
    path = Path(_require_string(row.get("exported_path") or row.get("local_path"), f"{label}.path"))
    return _safe_segment(path.name, f"{label}.filename")


def _copy_spec(
    row: Mapping[str, Any],
    *,
    source: Path,
    relative_path: Path,
    label: str,
) -> tuple[CopySpec, dict[str, Any]]:
    spec = CopySpec(
        source=source,
        relative_path=relative_path,
        bytes=_require_non_negative_int(row.get("bytes"), f"{label}.bytes"),
        sha256=_require_hex(row.get("sha256"), f"{label}.sha256"),
        label=label,
    )
    return spec, {
        "relative_path": relative_path.as_posix(),
        "bytes": spec.bytes,
        "sha256": spec.sha256,
    }


def _small_variant_specs(
    exports: Mapping[str, Any],
    source_root: Path,
) -> tuple[list[CopySpec], dict[str, Any]]:
    specs: list[CopySpec] = []
    final: dict[str, Any] = {}
    for producer, producer_exports in exports.items():
        producer_name = _safe_segment(str(producer), f"small_variants.{producer}")
        final[producer_name] = {}
        for key, value in _require_mapping(producer_exports, f"small_variants.{producer}").items():
            artifact_key = _safe_segment(str(key), f"small_variants.{producer}.{key}")
            row = _require_mapping(value, f"small_variants.{producer}.{key}")
            filename = _basename(row, f"small_variants.{producer}.{key}")
            spec, final_row = _copy_spec(
                row,
                source=source_root / producer_name / artifact_key / filename,
                relative_path=Path("artifacts") / "small_variants" / producer_name / artifact_key / filename,
                label=f"small_variants.{producer}.{key}",
            )
            specs.append(spec)
            final[producer_name][artifact_key] = final_row
    return specs, final


def _role_output_specs(
    materialized_outputs: Mapping[str, Any],
    source_root: Path,
    final_group: str,
) -> tuple[list[CopySpec], dict[str, Any]]:
    specs: list[CopySpec] = []
    final: dict[str, Any] = {}
    for role, role_outputs in materialized_outputs.items():
        role_name = _safe_segment(str(role), f"{final_group}.{role}")
        final[role_name] = {}
        for key, value in _require_mapping(role_outputs, f"{final_group}.{role}").items():
            artifact_key = _safe_segment(str(key), f"{final_group}.{role}.{key}")
            row = _require_mapping(value, f"{final_group}.{role}.{key}")
            filename = _basename(row, f"{final_group}.{role}.{key}")
            spec, final_row = _copy_spec(
                row,
                source=source_root / role_name / filename,
                relative_path=Path("artifacts") / final_group / role_name / artifact_key / filename,
                label=f"{final_group}.{role}.{key}",
            )
            specs.append(spec)
            final[role_name][artifact_key] = final_row
    return specs, final


def _cnv_specs(
    materialized_outputs: Mapping[str, Any],
    source_root: Path,
) -> tuple[list[CopySpec], dict[str, Any]]:
    specs: list[CopySpec] = []
    final: dict[str, Any] = {}
    for key, value in materialized_outputs.items():
        if key == "interval_shards":
            continue
        artifact_key = _safe_segment(str(key), f"cnv_evidence.{key}")
        row = _require_mapping(value, f"cnv_evidence.{key}")
        filename = _basename(row, f"cnv_evidence.{key}")
        spec, final_row = _copy_spec(
            row,
            source=source_root / filename,
            relative_path=Path("artifacts") / "cnv_evidence" / artifact_key / filename,
            label=f"cnv_evidence.{key}",
        )
        specs.append(spec)
        final[artifact_key] = final_row

    final["interval_shards"] = {}
    interval_shards = _require_mapping(materialized_outputs.get("interval_shards"), "cnv_evidence.interval_shards")
    for contig, contig_outputs in interval_shards.items():
        contig_name = _safe_segment(str(contig), f"cnv_evidence.interval_shards.{contig}")
        final["interval_shards"][contig_name] = {}
        for key, value in _require_mapping(contig_outputs, f"cnv_evidence.interval_shards.{contig}").items():
            artifact_key = _safe_segment(str(key), f"cnv_evidence.interval_shards.{contig}.{key}")
            row = _require_mapping(value, f"cnv_evidence.interval_shards.{contig}.{key}")
            filename = _basename(row, f"cnv_evidence.interval_shards.{contig}.{key}")
            source_dir = "intervals" if artifact_key == "intervals_bed" else "bedcov_shards"
            spec, final_row = _copy_spec(
                row,
                source=source_root / source_dir / filename,
                relative_path=Path("artifacts")
                / "cnv_evidence"
                / "interval_shards"
                / contig_name
                / artifact_key
                / filename,
                label=f"cnv_evidence.interval_shards.{contig}.{key}",
            )
            specs.append(spec)
            final["interval_shards"][contig_name][artifact_key] = final_row
    return specs, final


def _prepare_output_root(output_root: Path, destinations: set[Path]) -> None:
    _require_safe_destination_path(output_root, "output_root")
    if not output_root.exists():
        return
    if not output_root.is_dir():
        raise ManifestError(f"output_root already exists and is not a directory: {output_root}")

    unexpected = sorted(path for path in output_root.rglob("*") if path.is_file() and path not in destinations)
    if unexpected:
        raise ManifestError(f"output_root contains unexpected existing final artifact: {unexpected[0]}")

    for destination in destinations:
        _require_safe_destination_path(destination, "final artifact destination")
        if destination.exists() and not destination.is_file():
            raise ManifestError(f"final artifact destination exists and is not a file: {destination}")
        destination.unlink(missing_ok=True)


def _copy_verified(spec: CopySpec, output_root: Path) -> None:
    if not spec.source.is_file():
        raise ManifestError(f"{spec.label} source artifact is missing: {spec.source}")
    if spec.source.stat().st_size != spec.bytes or _sha256_path(spec.source) != spec.sha256:
        raise ManifestError(f"{spec.label} source bytes and sha256 must match the evidence join")

    destination = output_root / spec.relative_path
    ensure_parent(destination)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copyfile(spec.source, temporary)
    if temporary.stat().st_size != spec.bytes or _sha256_path(temporary) != spec.sha256:
        temporary.unlink(missing_ok=True)
        raise ManifestError(f"{spec.label} copied bytes and sha256 must match the evidence join")
    temporary.replace(destination)


def build_phase3_fast_final_evidence_manifest(
    evidence_join: Mapping[str, Any],
    *,
    evidence_join_sha256: str,
    small_variant_artifact_root: str | os.PathLike[str],
    bam_qc_artifact_root: str | os.PathLike[str],
    cnv_evidence_artifact_root: str | os.PathLike[str],
    sv_evidence_artifact_root: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
) -> dict[str, Any]:
    _require_completed_join(evidence_join)
    evidence = _require_mapping(evidence_join.get("evidence"), "evidence")

    small_variant_specs, small_variants = _small_variant_specs(
        _require_mapping(
            _require_mapping(evidence.get("small_variants"), "evidence.small_variants").get("exports"),
            "evidence.small_variants.exports",
        ),
        Path(small_variant_artifact_root),
    )
    bam_qc_specs, bam_qc = _role_output_specs(
        _require_mapping(
            _require_mapping(evidence.get("bam_qc"), "evidence.bam_qc").get("materialized_outputs"),
            "evidence.bam_qc.materialized_outputs",
        ),
        Path(bam_qc_artifact_root),
        "bam_qc",
    )
    cnv_specs, cnv_evidence = _cnv_specs(
        _require_mapping(
            _require_mapping(evidence.get("cnv_evidence"), "evidence.cnv_evidence").get("materialized_outputs"),
            "evidence.cnv_evidence.materialized_outputs",
        ),
        Path(cnv_evidence_artifact_root),
    )
    sv_specs, sv_evidence = _role_output_specs(
        _require_mapping(
            _require_mapping(evidence.get("sv_evidence"), "evidence.sv_evidence").get("materialized_outputs"),
            "evidence.sv_evidence.materialized_outputs",
        ),
        Path(sv_evidence_artifact_root),
        "sv_evidence",
    )

    specs = [*small_variant_specs, *bam_qc_specs, *cnv_specs, *sv_specs]
    destinations = {Path(output_root) / spec.relative_path for spec in specs}
    if len(destinations) != len(specs):
        raise ManifestError("final artifact destinations must be unique")
    _prepare_output_root(Path(output_root), destinations)
    for spec in specs:
        _copy_verified(spec, Path(output_root))

    source = _require_mapping(evidence_join.get("source"), "source")
    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_final_evidence_manifest",
        "status": "completed",
        "workflow": dict(_require_mapping(evidence_join.get("workflow"), "workflow")),
        "run": dict(_require_mapping(evidence_join.get("run"), "run")),
        "method_parameters": normalize_method_parameters(evidence_join.get("method_parameters")),
        "source": {
            "evidence_join_manifest_sha256": _require_hex(evidence_join_sha256, "evidence_join_sha256"),
            "receipt_sha256": dict(_require_mapping(source.get("receipt_sha256"), "source.receipt_sha256")),
        },
        "artifact_count": len(specs),
        "artifacts": {
            "small_variants": small_variants,
            "bam_qc": bam_qc,
            "cnv_evidence": cnv_evidence,
            "sv_evidence": sv_evidence,
        },
        "metrics": {
            "sv_evidence": dict(
                _require_mapping(
                    _require_mapping(evidence.get("sv_evidence"), "evidence.sv_evidence").get("metrics"),
                    "evidence.sv_evidence.metrics",
                )
            ),
        },
        "input_sources": dict(_require_mapping(evidence_join.get("input_sources"), "input_sources")),
        "interpretation": dict(_require_mapping(evidence_join.get("interpretation"), "interpretation")),
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast final evidence manifest output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest_from_environment() -> tuple[dict[str, Any], Path]:
    join_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_EVIDENCE_JOIN", DEFAULT_EVIDENCE_JOIN))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_FINAL_EVIDENCE_OUTPUT", DEFAULT_OUTPUT))
    manifest = build_phase3_fast_final_evidence_manifest(
        read_json(join_path),
        evidence_join_sha256=_sha256_path(join_path),
        small_variant_artifact_root=path_from_root(
            os.environ.get("PHASE3_WGS_FAST_SMALL_VARIANT_ARTIFACT_ROOT", DEFAULT_SMALL_VARIANT_ARTIFACT_ROOT)
        ),
        bam_qc_artifact_root=path_from_root(
            os.environ.get("PHASE3_WGS_FAST_BAM_QC_ARTIFACT_ROOT", DEFAULT_BAM_QC_ARTIFACT_ROOT)
        ),
        cnv_evidence_artifact_root=path_from_root(
            os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_ARTIFACT_ROOT", DEFAULT_CNV_EVIDENCE_ARTIFACT_ROOT)
        ),
        sv_evidence_artifact_root=path_from_root(
            os.environ.get("PHASE3_WGS_FAST_SV_EVIDENCE_ARTIFACT_ROOT", DEFAULT_SV_EVIDENCE_ARTIFACT_ROOT)
        ),
        output_root=path_from_root(os.environ.get("PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT", DEFAULT_OUTPUT_ROOT)),
    )
    return manifest, output_path


def main() -> None:
    manifest, output = load_manifest_from_environment()
    write_manifest(output, manifest)
    print(f"Phase 3 WGS fast final evidence manifest written: {output}")


if __name__ == "__main__":
    main()
