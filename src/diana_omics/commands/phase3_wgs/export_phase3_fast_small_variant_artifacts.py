from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent
from .render_phase3_fast_input_manifest import HEX64, ManifestError, _require_s3_uri, normalize_method_parameters
from .run_phase3_fast_filter_mutect import MATERIALIZED_OUTPUTS as FILTER_MUTECT_OUTPUTS
from .run_phase3_fast_parabricks_mutect import MATERIALIZED_OUTPUTS as PARABRICKS_MUTECT_OUTPUTS
from .safe_json_output import read_real_json, require_no_symlinked_ancestors, require_safe_output_path

DEFAULT_PARABRICKS_RECEIPT = "manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"
DEFAULT_FILTER_RECEIPT = "manifests/phase3_wgs_fast/filter_mutect_receipt.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/small_variant_artifact_export.json"
DEFAULT_OUTPUT_ROOT = "workspace/results/phase3_wgs_fast/small_variant_execution/artifacts"

SHARED_INPUTS = (
    "reference_fasta",
    "reference_fai",
    "reference_sequence_dictionary",
    "tumor_bam",
    "tumor_bai",
    "normal_bam",
    "normal_bai",
)


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


def _require_source(entry: Mapping[str, Any], label: str) -> dict[str, Any]:
    source = _require_mapping(entry.get("source"), f"{label} source")
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{label} source uri"),
        "version_id": _require_string(source.get("version_id"), f"{label} source version_id"),
        "bytes": _require_positive_int(source.get("bytes"), f"{label} source bytes"),
        "sha256": _require_hex(source.get("sha256"), f"{label} source sha256"),
    }


def _input_source(receipt: Mapping[str, Any], receipt_label: str, key: str) -> dict[str, Any]:
    inputs = _require_mapping(receipt.get("inputs"), f"{receipt_label} inputs")
    entry = _require_mapping(inputs.get(key), f"{receipt_label} inputs.{key}")
    return _require_source(entry, f"{receipt_label} inputs.{key}")


def _sample_input_source(receipt: Mapping[str, Any], receipt_label: str, key: str) -> dict[str, Any]:
    inputs = _require_mapping(receipt.get("inputs"), f"{receipt_label} inputs")
    entry = _require_mapping(inputs.get(key), f"{receipt_label} inputs.{key}")
    return {
        "sample_id": _require_string(entry.get("sample_id"), f"{receipt_label} inputs.{key} sample_id"),
        **_require_source(entry, f"{receipt_label} inputs.{key}"),
    }


def _require_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ManifestError(f"{label} must be a positive integer")
    return value


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_receipt(
    receipt: Mapping[str, Any],
    *,
    manifest_type: str,
    label: str,
) -> None:
    if receipt.get("manifest_type") != manifest_type:
        raise ManifestError(f"{label} manifest_type must be {manifest_type}")
    if receipt.get("status") != "completed":
        raise ManifestError(f"{label} status must be completed")
    if _require_mapping(receipt.get("interpretation"), f"{label} interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError(f"{label} authorized_hrd_state must remain no_call")


def _materialized(
    receipt: Mapping[str, Any],
    *,
    producer: str,
    expected_keys: tuple[str, ...],
) -> Mapping[str, Mapping[str, Any]]:
    materialized = _require_mapping(receipt.get("materialized_outputs"), f"{producer} materialized_outputs")
    observed = tuple(materialized)
    if observed != expected_keys:
        raise ManifestError(f"{producer} materialized_outputs must be exactly {', '.join(expected_keys)} in order")
    return {
        key: _require_mapping(materialized.get(key), f"{producer}.{key}")
        for key in expected_keys
    }


def _source_path(source: Mapping[str, Any], producer: str, key: str) -> Path:
    return Path(_require_string(source.get("local_path"), f"{producer}.{key}.local_path"))


def _destination_path(source: Mapping[str, Any], output_root: Path, producer: str, key: str) -> Path:
    return output_root / producer / key / _source_path(source, producer, key).name


def _require_safe_destination_path(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ManifestError(f"{label} may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, label, ManifestError)


def _require_safe_source_path(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ManifestError(f"{label} source may not be a symlink: {path}")
    require_no_symlinked_ancestors(path, f"{label} source", ManifestError)


def _prepare_output_root(output_root: Path, destinations: set[Path]) -> None:
    _require_safe_destination_path(output_root, "output_root")
    if not output_root.exists():
        return
    if not output_root.is_dir():
        raise ManifestError(f"output_root already exists and is not a directory: {output_root}")

    symlink = next((path for path in output_root.rglob("*") if path.is_symlink()), None)
    if symlink is not None:
        raise ManifestError(f"output_root contains a symlink: {symlink}")

    unexpected = sorted(
        path
        for path in output_root.rglob("*")
        if path.is_file() and path not in destinations
    )
    if unexpected:
        raise ManifestError(f"output_root contains unexpected existing export files: {unexpected[0]}")

    for destination in destinations:
        _require_safe_destination_path(destination, "export destination")
        if destination.exists() and not destination.is_file():
            raise ManifestError(f"export destination exists and is not a file: {destination}")
        destination.unlink(missing_ok=True)


def _copy_verified(
    source: Mapping[str, Any],
    output_root: Path,
    producer: str,
    key: str,
) -> dict[str, Any]:
    source_path = _source_path(source, producer, key)
    expected_bytes = _require_positive_int(source.get("bytes"), f"{producer}.{key}.bytes")
    expected_sha = _require_hex(source.get("sha256"), f"{producer}.{key}.sha256")
    _require_safe_source_path(source_path, f"{producer}.{key}")
    if not source_path.is_file():
        raise ManifestError(f"{producer}.{key} source must exist before export: {source_path}")
    if source_path.stat().st_size != expected_bytes or _sha256_path(source_path) != expected_sha:
        raise ManifestError(f"{producer}.{key} source bytes and sha256 must still match the receipt")

    destination = _destination_path(source, output_root, producer, key)
    _require_safe_destination_path(destination, f"{producer}.{key} export destination")
    if destination.exists() and not destination.is_file():
        raise ManifestError(f"{producer}.{key} export destination exists and is not a file: {destination}")

    ensure_parent(destination)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.unlink(missing_ok=True)
    installed = False
    try:
        shutil.copyfile(source_path, temporary)
        _require_safe_destination_path(temporary, f"{producer}.{key} temporary export")
        copied_bytes = temporary.stat().st_size
        copied_sha = _sha256_path(temporary)
        if copied_bytes != expected_bytes or copied_sha != expected_sha:
            raise ManifestError(f"{producer}.{key} export copy bytes and sha256 must match the receipt")
        temporary.replace(destination)
        installed = True
        _require_safe_destination_path(destination, f"{producer}.{key} export destination")
        copied_bytes = destination.stat().st_size
        copied_sha = _sha256_path(destination)
        if copied_bytes != expected_bytes or copied_sha != expected_sha:
            raise ManifestError(f"{producer}.{key} exported bytes and sha256 must match the receipt")
    except Exception:
        temporary.unlink(missing_ok=True)
        if installed:
            destination.unlink(missing_ok=True)
        raise
    return {
        "source_local_path": str(source_path),
        "exported_path": str(destination),
        "bytes": copied_bytes,
        "sha256": copied_sha,
    }


def _source_inputs(parabricks_receipt: Mapping[str, Any], filter_receipt: Mapping[str, Any]) -> dict[str, Any]:
    for key in SHARED_INPUTS:
        if _input_source(parabricks_receipt, "Parabricks receipt", key) != _input_source(
            filter_receipt,
            "FilterMutect receipt",
            key,
        ):
            raise ManifestError(f"FilterMutect {key} source must match the Parabricks receipt")

    return {
        "reference": {
            "fasta": _input_source(parabricks_receipt, "Parabricks receipt", "reference_fasta"),
            "fai": _input_source(parabricks_receipt, "Parabricks receipt", "reference_fai"),
            "sequence_dictionary": _input_source(
                parabricks_receipt,
                "Parabricks receipt",
                "reference_sequence_dictionary",
            ),
        },
        "bam_pair": {
            "tumor": {
                "bam": _sample_input_source(parabricks_receipt, "Parabricks receipt", "tumor_bam"),
                "bai": _sample_input_source(parabricks_receipt, "Parabricks receipt", "tumor_bai"),
            },
            "normal": {
                "bam": _sample_input_source(parabricks_receipt, "Parabricks receipt", "normal_bam"),
                "bai": _sample_input_source(parabricks_receipt, "Parabricks receipt", "normal_bai"),
            },
        },
        "caller_resources": {
            "gatk_jar": _input_source(filter_receipt, "FilterMutect receipt", "gatk_jar"),
            "common_sites_vcf": _input_source(filter_receipt, "FilterMutect receipt", "common_sites_vcf"),
            "common_sites_index": _input_source(filter_receipt, "FilterMutect receipt", "common_sites_index"),
            "germline_resource_vcf": _input_source(
                parabricks_receipt,
                "Parabricks receipt",
                "germline_resource_vcf",
            ),
            "germline_resource_index": _input_source(
                parabricks_receipt,
                "Parabricks receipt",
                "germline_resource_index",
            ),
            "panel_of_normals_vcf": _input_source(
                parabricks_receipt,
                "Parabricks receipt",
                "panel_of_normals_vcf",
            ),
            "panel_of_normals_index": _input_source(
                parabricks_receipt,
                "Parabricks receipt",
                "panel_of_normals_index",
            ),
            "mutect2_interval_set": _input_source(
                parabricks_receipt,
                "Parabricks receipt",
                "mutect2_interval_set",
            ),
        },
    }


def export_phase3_fast_small_variant_artifacts(
    parabricks_receipt: Mapping[str, Any],
    filter_receipt: Mapping[str, Any],
    *,
    parabricks_mutect_receipt_sha256: str,
    filter_mutect_receipt_sha256: str,
    output_root: str | os.PathLike[str],
) -> dict[str, Any]:
    parabricks_receipt_sha = _require_hex(
        parabricks_mutect_receipt_sha256,
        "parabricks_mutect_receipt_sha256",
    )
    filter_receipt_sha = _require_hex(
        filter_mutect_receipt_sha256,
        "filter_mutect_receipt_sha256",
    )
    _require_receipt(
        parabricks_receipt,
        manifest_type="phase3_wgs_fast_parabricks_mutect_receipt",
        label="Parabricks receipt",
    )
    _require_receipt(
        filter_receipt,
        manifest_type="phase3_wgs_fast_filter_mutect_receipt",
        label="FilterMutect receipt",
    )

    parabricks_source = _require_mapping(parabricks_receipt.get("source"), "Parabricks source")
    filter_source = _require_mapping(filter_receipt.get("source"), "FilterMutect source")
    if filter_source.get("parabricks_mutect_receipt_sha256") != parabricks_receipt_sha:
        raise ManifestError("FilterMutect receipt must reference the exported Parabricks receipt SHA-256")
    if filter_source.get("parabricks_mutect_plan_sha256") != parabricks_source.get("parabricks_mutect_plan_sha256"):
        raise ManifestError("FilterMutect receipt must share the Parabricks plan SHA-256")
    method_parameters = normalize_method_parameters(filter_receipt.get("method_parameters"))
    if normalize_method_parameters(parabricks_receipt.get("method_parameters")) != method_parameters:
        raise ManifestError("FilterMutect method_parameters must match the Parabricks receipt")
    input_sources = _source_inputs(parabricks_receipt, filter_receipt)

    root = Path(output_root)
    parabricks_outputs = _materialized(
        parabricks_receipt,
        producer="parabricks_mutect",
        expected_keys=PARABRICKS_MUTECT_OUTPUTS,
    )
    filter_outputs = _materialized(
        filter_receipt,
        producer="filter_mutect",
        expected_keys=FILTER_MUTECT_OUTPUTS,
    )
    expected_destinations = {
        *(
            _destination_path(row, root, "parabricks_mutect", key)
            for key, row in parabricks_outputs.items()
        ),
        *(
            _destination_path(row, root, "filter_mutect", key)
            for key, row in filter_outputs.items()
        ),
    }
    expected_count = len(PARABRICKS_MUTECT_OUTPUTS) + len(FILTER_MUTECT_OUTPUTS)
    if len(expected_destinations) != expected_count:
        raise ManifestError("exported artifact paths must be unique")
    _prepare_output_root(root, expected_destinations)

    exports = {
        "parabricks_mutect": {
            key: _copy_verified(row, root, "parabricks_mutect", key)
            for key, row in parabricks_outputs.items()
        },
        "filter_mutect": {
            key: _copy_verified(row, root, "filter_mutect", key)
            for key, row in filter_outputs.items()
        },
    }

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_small_variant_artifact_export",
        "status": "completed",
        "workflow": dict(_require_mapping(filter_receipt.get("workflow"), "FilterMutect workflow")),
        "run": dict(_require_mapping(filter_receipt.get("run"), "FilterMutect run")),
        "runtime": dict(_require_mapping(filter_receipt.get("runtime"), "FilterMutect runtime")),
        "method_parameters": method_parameters,
        "source": {
            "parabricks_mutect_plan_sha256": _require_hex(
                parabricks_source.get("parabricks_mutect_plan_sha256"),
                "parabricks_mutect_plan_sha256",
            ),
            "filter_mutect_plan_sha256": _require_hex(
                filter_source.get("filter_mutect_plan_sha256"),
                "filter_mutect_plan_sha256",
            ),
            "parabricks_mutect_receipt_sha256": parabricks_receipt_sha,
            "filter_mutect_receipt_sha256": filter_receipt_sha,
        },
        "input_sources": input_sources,
        "output_root": str(root),
        "exports": exports,
        "interpretation": {
            "authorized_hrd_state": "no_call",
        },
    }


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast small-variant export receipt output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_export_from_environment() -> tuple[dict[str, Any], Path]:
    parabricks_path = path_from_root(
        os.environ.get("PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT", DEFAULT_PARABRICKS_RECEIPT)
    )
    filter_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT", DEFAULT_FILTER_RECEIPT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_OUTPUT", DEFAULT_OUTPUT))
    output_root = path_from_root(os.environ.get("PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_ROOT", DEFAULT_OUTPUT_ROOT))
    export = export_phase3_fast_small_variant_artifacts(
        read_real_json(parabricks_path, "Parabricks receipt", ManifestError),
        read_real_json(filter_path, "FilterMutect receipt", ManifestError),
        parabricks_mutect_receipt_sha256=_sha256_path(parabricks_path),
        filter_mutect_receipt_sha256=_sha256_path(filter_path),
        output_root=output_root,
    )
    return export, output_path


def main() -> None:
    export, output = load_export_from_environment()
    write_receipt(output, export)
    print(f"Phase 3 WGS fast small-variant artifact export written: {output}")


if __name__ == "__main__":
    main()
