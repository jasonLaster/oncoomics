from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent, read_json
from .render_phase3_fast_input_manifest import HEX64, ManifestError

DEFAULT_STAGED_INPUTS = "manifests/phase3_wgs_fast/staged_inputs_manifest.json"
DEFAULT_MUTECT_PLAN = "manifests/phase3_wgs_fast/parabricks_mutect_plan.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/filter_mutect_plan.json"
DEFAULT_OUTPUT_ROOT = "/scratch/diana/phase3_wgs_fast/filter_mutect"


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


def _require_absolute_path(value: Any, label: str) -> str:
    path = Path(_require_string(value, label))
    if not path.is_absolute():
        raise ManifestError(f"{label} must be an absolute path")
    return str(path)


def _entry(container: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _require_mapping(container.get(key), key)


def _artifact_path(entry: Mapping[str, Any], artifact: str) -> str:
    if entry.get("artifact") != artifact:
        raise ManifestError(f"{artifact} entry artifact must match")
    return _require_absolute_path(entry.get("local_path"), f"{artifact} local_path")


def _output_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise ManifestError("output_root must be an absolute path")
    return root


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _gatk(gatk_jar: str, memory: str, arguments: list[str]) -> list[str]:
    return [
        "java",
        f"-Xmx{memory}",
        "-jar",
        gatk_jar,
        *arguments,
    ]


def build_phase3_fast_filter_mutect_plan(
    staged_inputs_manifest: Mapping[str, Any],
    mutect_plan: Mapping[str, Any],
    *,
    staged_inputs_manifest_sha256: str,
    mutect_plan_sha256: str,
    output_root: str | os.PathLike[str] = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    if staged_inputs_manifest.get("manifest_type") != "phase3_wgs_fast_staged_inputs_manifest":
        raise ManifestError("staged inputs manifest_type must be phase3_wgs_fast_staged_inputs_manifest")
    if staged_inputs_manifest.get("status") != "ready":
        raise ManifestError("staged inputs status must be ready")
    if mutect_plan.get("manifest_type") != "phase3_wgs_fast_parabricks_mutect_plan":
        raise ManifestError("Mutect plan manifest_type must be phase3_wgs_fast_parabricks_mutect_plan")
    if mutect_plan.get("status") != "planned":
        raise ManifestError("Mutect plan status must be planned")
    if _require_mapping(staged_inputs_manifest.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("filter Mutect plan staged inputs authorized_hrd_state must remain no_call")
    if _require_mapping(mutect_plan.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("filter Mutect plan authorized_hrd_state must remain no_call")

    runtime = _require_mapping(staged_inputs_manifest.get("runtime"), "runtime")
    if runtime.get("caller") != "parabricks_mutectcaller":
        raise ManifestError("runtime caller must be parabricks_mutectcaller")

    staged_sha = _require_hex(staged_inputs_manifest_sha256, "staged_inputs_manifest_sha256")
    mutect_source = _require_mapping(mutect_plan.get("source"), "Mutect plan source")
    if mutect_source.get("staged_inputs_manifest_sha256") != staged_sha:
        raise ManifestError("Mutect plan must be derived from the staged inputs manifest")

    root = _output_root(output_root)
    pileups = root / "pileups"
    variants = root / "variants"

    reference = _require_mapping(staged_inputs_manifest.get("reference"), "reference")
    bam_pair = _require_mapping(staged_inputs_manifest.get("bam_pair"), "bam_pair")
    caller_resources = _require_mapping(staged_inputs_manifest.get("caller_resources"), "caller_resources")
    tumor = _require_mapping(bam_pair.get("tumor"), "bam_pair.tumor")
    normal = _require_mapping(bam_pair.get("normal"), "bam_pair.normal")

    gatk_jar = _artifact_path(_entry(caller_resources, "gatk_jar"), "gatk_jar")
    common_sites = _artifact_path(_entry(caller_resources, "common_sites_vcf"), "common_sites_vcf")
    common_sites_index = _artifact_path(_entry(caller_resources, "common_sites_index"), "common_sites_index")
    reference_fasta = _artifact_path(_entry(reference, "fasta"), "reference.fa")
    tumor_bam = _artifact_path(_entry(tumor, "bam"), "tumor.bam")
    normal_bam = _artifact_path(_entry(normal, "bam"), "normal.bam")
    if Path(common_sites).parent != Path(common_sites_index).parent:
        raise ManifestError("common_sites_vcf and common_sites_index must be staged together")

    mutect_outputs = _require_mapping(mutect_plan.get("outputs"), "Mutect plan outputs")
    raw_vcf = _require_absolute_path(mutect_outputs.get("raw_vcf"), "raw_vcf")
    raw_stats = _require_absolute_path(mutect_outputs.get("raw_vcf_stats"), "raw_vcf_stats")
    if raw_stats != f"{raw_vcf}.stats":
        raise ManifestError("raw_vcf_stats must be the raw_vcf .stats sidecar")
    pon_annotated_vcf = _require_absolute_path(mutect_outputs.get("pon_annotated_vcf"), "pon_annotated_vcf")
    pon_annotated_vcf_index = f"{pon_annotated_vcf}.tbi"
    f1r2 = _require_absolute_path(mutect_outputs.get("f1r2_tar_gz"), "f1r2_tar_gz")

    tumor_pileups = str(pileups / "tumor.pileups.table")
    normal_pileups = str(pileups / "normal.pileups.table")
    contamination = str(pileups / "contamination.table")
    tumor_segments = str(pileups / "tumor-segmentation.table")
    priors = str(variants / "read-orientation-model.tar.gz")
    filtered = str(variants / "diana.wgs.mutect2.parabricks.filtered.vcf.gz")

    commands = {
        "get_tumor_pileups": {
            "argv": _gatk(
                gatk_jar,
                "12g",
                [
                    "GetPileupSummaries",
                    "-R",
                    reference_fasta,
                    "-I",
                    tumor_bam,
                    "-V",
                    common_sites,
                    "-L",
                    common_sites,
                    "-O",
                    tumor_pileups,
                ],
            ),
        },
        "get_normal_pileups": {
            "argv": _gatk(
                gatk_jar,
                "12g",
                [
                    "GetPileupSummaries",
                    "-R",
                    reference_fasta,
                    "-I",
                    normal_bam,
                    "-V",
                    common_sites,
                    "-L",
                    common_sites,
                    "-O",
                    normal_pileups,
                ],
            ),
        },
        "learn_read_orientation_model": {
            "argv": _gatk(
                gatk_jar,
                "8g",
                [
                    "LearnReadOrientationModel",
                    "-I",
                    f1r2,
                    "-O",
                    priors,
                ],
            ),
        },
        "calculate_contamination": {
            "argv": _gatk(
                gatk_jar,
                "8g",
                [
                    "CalculateContamination",
                    "-I",
                    tumor_pileups,
                    "-matched",
                    normal_pileups,
                    "-O",
                    contamination,
                    "--tumor-segmentation",
                    tumor_segments,
                ],
            ),
        },
        "index_pon_annotated_vcf": {
            "argv": [
                "bcftools",
                "index",
                "-t",
                "-f",
                pon_annotated_vcf,
            ],
        },
        "filter_mutect_calls": {
            "argv": _gatk(
                gatk_jar,
                "12g",
                [
                    "FilterMutectCalls",
                    "-R",
                    reference_fasta,
                    "-V",
                    pon_annotated_vcf,
                    "--stats",
                    raw_stats,
                    "--contamination-table",
                    contamination,
                    "--tumor-segmentation",
                    tumor_segments,
                    "--orientation-bias-artifact-priors",
                    priors,
                    "-O",
                    filtered,
                ],
            ),
        },
        "index_filtered_vcf": {
            "argv": [
                "bcftools",
                "index",
                "-t",
                "-f",
                filtered,
            ],
        },
    }

    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_filter_mutect_plan",
        "status": "planned",
        "workflow": dict(_require_mapping(staged_inputs_manifest.get("workflow"), "workflow")),
        "run": dict(_require_mapping(staged_inputs_manifest.get("run"), "run")),
        "runtime": dict(runtime),
        "source": {
            "staged_inputs_manifest_sha256": staged_sha,
            "parabricks_mutect_plan_sha256": _require_hex(mutect_plan_sha256, "parabricks_mutect_plan_sha256"),
        },
        "inputs": {
            "gatk_jar": {"local_path": gatk_jar},
            "reference_fasta": {"local_path": reference_fasta},
            "tumor_bam": {"local_path": tumor_bam},
            "normal_bam": {"local_path": normal_bam},
            "common_sites_vcf": {"local_path": common_sites},
            "common_sites_index": {"local_path": common_sites_index},
            "raw_vcf": {"local_path": raw_vcf},
            "raw_vcf_stats": {"local_path": raw_stats},
            "pon_annotated_vcf": {"local_path": pon_annotated_vcf},
            "f1r2_tar_gz": {"local_path": f1r2},
        },
        "outputs": {
            "tumor_pileups": tumor_pileups,
            "normal_pileups": normal_pileups,
            "contamination": contamination,
            "tumor_segments": tumor_segments,
            "read_orientation_model": priors,
            "pon_annotated_vcf_index": pon_annotated_vcf_index,
            "filtered_vcf": filtered,
            "filtered_vcf_index": f"{filtered}.tbi",
        },
        "commands": commands,
        "output_root": str(root),
        "interpretation": {
            "authorized_hrd_state": "no_call",
        },
    }


def write_plan(path: Path, plan: Mapping[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_plan_from_environment() -> tuple[dict[str, Any], Path]:
    staged_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST", DEFAULT_STAGED_INPUTS))
    mutect_plan_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN", DEFAULT_MUTECT_PLAN))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_FILTER_MUTECT_PLAN_OUTPUT", DEFAULT_OUTPUT))
    plan = build_phase3_fast_filter_mutect_plan(
        read_json(staged_path),
        read_json(mutect_plan_path),
        staged_inputs_manifest_sha256=_sha256_path(staged_path),
        mutect_plan_sha256=_sha256_path(mutect_plan_path),
        output_root=os.environ.get("PHASE3_WGS_FAST_FILTER_MUTECT_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
    )
    return plan, output_path


def main() -> None:
    plan, output = load_plan_from_environment()
    write_plan(output, plan)
    print(f"Phase 3 WGS fast FilterMutectCalls plan written: {output}")


if __name__ == "__main__":
    main()
