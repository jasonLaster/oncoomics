from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent
from .render_phase3_fast_input_manifest import HEX64, ManifestError, _require_s3_uri, normalize_method_parameters
from .safe_json_output import read_real_json, require_safe_output_path

DEFAULT_INPUT = "manifests/phase3_wgs_fast/staged_inputs_manifest.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/parabricks_mutect_plan.json"
DEFAULT_OUTPUT_ROOT = "/scratch/diana/phase3_wgs_fast/parabricks_mutect"
DEFAULT_NUM_GPUS = 8


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


def _require_absolute_path(value: Any, label: str) -> str:
    path = Path(_require_string(value, label))
    if not path.is_absolute():
        raise ManifestError(f"{label} must be an absolute path")
    return str(path)


def _require_output_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ManifestError("output_root must be an absolute path")
    return root


def _require_num_gpus(value: str | int | None) -> int:
    if value is None or value == "":
        return DEFAULT_NUM_GPUS
    try:
        parsed = int(value)
    except ValueError as error:
        raise ManifestError("PHASE3_WGS_FAST_PARABRICKS_NUM_GPUS must be an integer") from error
    return _require_positive_int(parsed, "num_gpus")


def _entry(container: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _require_mapping(container.get(key), key)


def _artifact_path(entry: Mapping[str, Any], artifact: str) -> str:
    if entry.get("artifact") != artifact:
        raise ManifestError(f"{artifact} entry artifact must match")
    return _require_absolute_path(entry.get("local_path"), f"{artifact} local_path")


def _require_tabix_sidecar(vcf: str, index: str, label: str) -> None:
    if not vcf.endswith(".vcf.gz"):
        raise ManifestError(f"{label} VCF must be staged as .vcf.gz")
    if index != f"{vcf}.tbi":
        raise ManifestError(f"{label} index must be the .vcf.gz.tbi sidecar")


def _require_sample_id(entry: Mapping[str, Any], artifact: str) -> str:
    return _require_string(entry.get("sample_id"), f"{artifact} sample_id")


def _require_source(entry: Mapping[str, Any], artifact: str) -> dict[str, Any]:
    source = _require_mapping(entry.get("source"), f"{artifact} source")
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{artifact} source uri"),
        "version_id": _require_string(source.get("version_id"), f"{artifact} source version_id"),
        "bytes": _require_positive_int(entry.get("bytes"), f"{artifact} bytes"),
        "sha256": _require_hex(entry.get("sha256"), f"{artifact} sha256"),
    }


def _with_runtime(command: list[str], tmp_dir: str, log_file: str, num_gpus: int) -> list[str]:
    return [
        *command,
        "--tmp-dir",
        tmp_dir,
        "--logfile",
        log_file,
        "--num-gpus",
        str(num_gpus),
    ]


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_phase3_fast_parabricks_mutect_plan(
    staged_inputs_manifest: Mapping[str, Any],
    *,
    staged_inputs_manifest_sha256: str,
    output_root: str | os.PathLike[str] = DEFAULT_OUTPUT_ROOT,
    num_gpus: int = DEFAULT_NUM_GPUS,
) -> dict[str, Any]:
    if staged_inputs_manifest.get("manifest_type") != "phase3_wgs_fast_staged_inputs_manifest":
        raise ManifestError("staged inputs manifest_type must be phase3_wgs_fast_staged_inputs_manifest")
    if staged_inputs_manifest.get("status") != "ready":
        raise ManifestError("staged inputs status must be ready")
    if _require_mapping(staged_inputs_manifest.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("Parabricks Mutect plan authorized_hrd_state must remain no_call")

    runtime = _require_mapping(staged_inputs_manifest.get("runtime"), "runtime")
    if runtime.get("caller") != "parabricks_mutectcaller":
        raise ManifestError("runtime caller must be parabricks_mutectcaller")

    root = _require_output_root(output_root)
    gpu_count = _require_positive_int(num_gpus, "num_gpus")
    logs = root / "logs"
    tmp = root / "tmp"
    variants = root / "variants"

    bam_pair = _require_mapping(staged_inputs_manifest.get("bam_pair"), "bam_pair")
    tumor = _require_mapping(bam_pair.get("tumor"), "bam_pair.tumor")
    normal = _require_mapping(bam_pair.get("normal"), "bam_pair.normal")
    tumor_bam = _entry(tumor, "bam")
    tumor_bai = _entry(tumor, "bai")
    normal_bam = _entry(normal, "bam")
    normal_bai = _entry(normal, "bai")
    reference = _require_mapping(staged_inputs_manifest.get("reference"), "reference")
    caller_resources = _require_mapping(staged_inputs_manifest.get("caller_resources"), "caller_resources")

    reference_fasta_entry = _entry(reference, "fasta")
    reference_fai_entry = _entry(reference, "fai")
    reference_sequence_dictionary_entry = _entry(reference, "sequence_dictionary")
    germline_resource_vcf_entry = _entry(caller_resources, "germline_resource_vcf")
    germline_resource_index_entry = _entry(caller_resources, "germline_resource_index")
    panel_of_normals_vcf_entry = _entry(caller_resources, "panel_of_normals_vcf")
    panel_of_normals_index_entry = _entry(caller_resources, "panel_of_normals_index")
    mutect2_interval_set_entry = _entry(caller_resources, "mutect2_interval_set")

    reference_fasta = _artifact_path(reference_fasta_entry, "reference.fa")
    reference_fai = _artifact_path(reference_fai_entry, "reference.fa.fai")
    reference_sequence_dictionary = _artifact_path(reference_sequence_dictionary_entry, "reference.dict")
    tumor_bam_path = _artifact_path(tumor_bam, "tumor.bam")
    tumor_bai_path = _artifact_path(tumor_bai, "tumor.bai")
    normal_bam_path = _artifact_path(normal_bam, "normal.bam")
    normal_bai_path = _artifact_path(normal_bai, "normal.bai")
    germline_resource_vcf = _artifact_path(germline_resource_vcf_entry, "germline_resource_vcf")
    germline_resource_index = _artifact_path(germline_resource_index_entry, "germline_resource_index")
    panel_of_normals_vcf = _artifact_path(panel_of_normals_vcf_entry, "panel_of_normals_vcf")
    panel_of_normals_index = _artifact_path(panel_of_normals_index_entry, "panel_of_normals_index")
    mutect2_interval_set = _artifact_path(mutect2_interval_set_entry, "mutect2_interval_set")

    if Path(tumor_bam_path).parent != Path(tumor_bai_path).parent:
        raise ManifestError("tumor.bam and tumor.bai must be staged together")
    if Path(normal_bam_path).parent != Path(normal_bai_path).parent:
        raise ManifestError("normal.bam and normal.bai must be staged together")
    if Path(reference_fasta).parent != Path(reference_fai).parent:
        raise ManifestError("reference.fa and reference.fa.fai must be staged together")
    if Path(reference_fasta).parent != Path(reference_sequence_dictionary).parent:
        raise ManifestError("reference.fa and reference.dict must be staged together")
    _require_tabix_sidecar(panel_of_normals_vcf, panel_of_normals_index, "panel_of_normals")
    _require_tabix_sidecar(germline_resource_vcf, germline_resource_index, "germline_resource")

    tumor_name = _require_sample_id(tumor_bam, "tumor.bam")
    if _require_sample_id(tumor_bai, "tumor.bai") != tumor_name:
        raise ManifestError("tumor.bam and tumor.bai sample_id values must match")
    normal_name = _require_sample_id(normal_bam, "normal.bam")
    if _require_sample_id(normal_bai, "normal.bai") != normal_name:
        raise ManifestError("normal.bam and normal.bai sample_id values must match")
    if tumor_name == normal_name:
        raise ManifestError("tumor and normal sample names must differ")

    raw_vcf = str(variants / "diana.wgs.mutect2.parabricks.raw.vcf.gz")
    raw_vcf_stats = f"{raw_vcf}.stats"
    pon_annotated_vcf = str(variants / "diana.wgs.mutect2.parabricks.pon.vcf.gz")
    f1r2 = str(variants / "diana.wgs.mutect2.parabricks.f1r2.tar.gz")

    commands = {
        "prepon": {
            "argv": _with_runtime(
                [
                    "pbrun",
                    "prepon",
                    "--in-pon-file",
                    panel_of_normals_vcf,
                ],
                str(tmp / "prepon"),
                str(logs / "prepon.log"),
                gpu_count,
            ),
        },
        "mutectcaller": {
            "argv": _with_runtime(
                [
                    "pbrun",
                    "mutectcaller",
                    "--ref",
                    reference_fasta,
                    "--tumor-name",
                    tumor_name,
                    "--in-tumor-bam",
                    tumor_bam_path,
                    "--in-normal-bam",
                    normal_bam_path,
                    "--normal-name",
                    normal_name,
                    "--pon",
                    panel_of_normals_vcf,
                    "--mutect-germline-resource",
                    germline_resource_vcf,
                    "--interval-file",
                    mutect2_interval_set,
                    "--mutect-f1r2-tar-gz",
                    f1r2,
                    "--out-vcf",
                    raw_vcf,
                ],
                str(tmp / "mutectcaller"),
                str(logs / "mutectcaller.log"),
                gpu_count,
            ),
        },
        "postpon": {
            "argv": _with_runtime(
                [
                    "pbrun",
                    "postpon",
                    "--in-vcf",
                    raw_vcf,
                    "--in-pon-file",
                    panel_of_normals_vcf,
                    "--out-vcf",
                    pon_annotated_vcf,
                ],
                str(tmp / "postpon"),
                str(logs / "postpon.log"),
                gpu_count,
            ),
        },
    }

    source = _require_mapping(staged_inputs_manifest.get("source"), "source")
    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_parabricks_mutect_plan",
        "status": "planned",
        "workflow": dict(_require_mapping(staged_inputs_manifest.get("workflow"), "workflow")),
        "run": dict(_require_mapping(staged_inputs_manifest.get("run"), "run")),
        "runtime": {
            **dict(runtime),
            "num_gpus": gpu_count,
        },
        "method_parameters": normalize_method_parameters(staged_inputs_manifest.get("method_parameters")),
        "source": {
            "input_manifest_sha256": _require_hex(source.get("input_manifest_sha256"), "input_manifest_sha256"),
            "replication_plan_sha256": _require_hex(source.get("replication_plan_sha256"), "replication_plan_sha256"),
            "replication_receipt_sha256": _require_hex(source.get("replication_receipt_sha256"), "replication_receipt_sha256"),
            "cache_manifest_sha256": _require_hex(source.get("cache_manifest_sha256"), "cache_manifest_sha256"),
            "staging_plan_sha256": _require_hex(source.get("staging_plan_sha256"), "staging_plan_sha256"),
            "staged_inputs_manifest_sha256": _require_hex(
                staged_inputs_manifest_sha256,
                "staged_inputs_manifest_sha256",
            ),
        },
        "inputs": {
            "reference_fasta": {
                "local_path": reference_fasta,
                "source": _require_source(reference_fasta_entry, "reference.fa"),
            },
            "reference_fai": {
                "local_path": reference_fai,
                "source": _require_source(reference_fai_entry, "reference.fa.fai"),
            },
            "reference_sequence_dictionary": {
                "local_path": reference_sequence_dictionary,
                "source": _require_source(reference_sequence_dictionary_entry, "reference.dict"),
            },
            "tumor_bam": {
                "local_path": tumor_bam_path,
                "sample_id": tumor_name,
                "source": _require_source(tumor_bam, "tumor.bam"),
            },
            "tumor_bai": {
                "local_path": tumor_bai_path,
                "sample_id": tumor_name,
                "source": _require_source(tumor_bai, "tumor.bai"),
            },
            "normal_bam": {
                "local_path": normal_bam_path,
                "sample_id": normal_name,
                "source": _require_source(normal_bam, "normal.bam"),
            },
            "normal_bai": {
                "local_path": normal_bai_path,
                "sample_id": normal_name,
                "source": _require_source(normal_bai, "normal.bai"),
            },
            "germline_resource_vcf": {
                "local_path": germline_resource_vcf,
                "source": _require_source(germline_resource_vcf_entry, "germline_resource_vcf"),
            },
            "germline_resource_index": {
                "local_path": germline_resource_index,
                "source": _require_source(germline_resource_index_entry, "germline_resource_index"),
            },
            "panel_of_normals_vcf": {
                "local_path": panel_of_normals_vcf,
                "source": _require_source(panel_of_normals_vcf_entry, "panel_of_normals_vcf"),
            },
            "panel_of_normals_index": {
                "local_path": panel_of_normals_index,
                "source": _require_source(panel_of_normals_index_entry, "panel_of_normals_index"),
            },
            "mutect2_interval_set": {
                "local_path": mutect2_interval_set,
                "source": _require_source(mutect2_interval_set_entry, "mutect2_interval_set"),
            },
        },
        "outputs": {
            "raw_vcf": raw_vcf,
            "raw_vcf_stats": raw_vcf_stats,
            "pon_annotated_vcf": pon_annotated_vcf,
            "f1r2_tar_gz": f1r2,
            "logs_dir": str(logs),
            "tmp_dir": str(tmp),
        },
        "commands": commands,
        "output_root": str(root),
        "interpretation": {
            "authorized_hrd_state": "no_call",
        },
    }


def write_plan(path: Path, plan: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast Parabricks Mutect plan output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_plan_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN_OUTPUT", DEFAULT_OUTPUT))
    plan = build_phase3_fast_parabricks_mutect_plan(
        read_real_json(input_path, "staged_inputs", ManifestError),
        staged_inputs_manifest_sha256=_sha256_path(input_path),
        output_root=os.environ.get("PHASE3_WGS_FAST_PARABRICKS_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
        num_gpus=_require_num_gpus(os.environ.get("PHASE3_WGS_FAST_PARABRICKS_NUM_GPUS")),
    )
    return plan, output_path


def main() -> None:
    plan, output = load_plan_from_environment()
    write_plan(output, plan)
    print(f"Phase 3 WGS fast Parabricks Mutect plan written: {output}")


if __name__ == "__main__":
    main()
