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
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/sv_evidence_plan.json"
DEFAULT_OUTPUT_ROOT = "/scratch/diana/phase3_wgs_fast/sv_evidence"
DEFAULT_THREADS = 8
ROLES = ("tumor", "normal")


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
    if type(value) is not int or value <= 0:
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


def _require_threads(value: str | int | None) -> int:
    if value is None or value == "":
        return DEFAULT_THREADS
    try:
        parsed = int(value)
    except ValueError as error:
        raise ManifestError("PHASE3_WGS_FAST_SV_EVIDENCE_THREADS must be an integer") from error
    return _require_positive_int(parsed, "threads")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(container: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    return _require_mapping(container.get(key), f"{label}.{key}")


def _require_source(entry: Mapping[str, Any], artifact: str) -> dict[str, str]:
    source = _require_mapping(entry.get("source"), f"{artifact} source")
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{artifact} source uri"),
        "version_id": _require_string(source.get("version_id"), f"{artifact} source version_id"),
    }


def _bam_input(entry: Mapping[str, Any], artifact: str) -> dict[str, str]:
    if entry.get("artifact") != artifact:
        raise ManifestError(f"{artifact} entry artifact must match")
    return {
        "local_path": _require_absolute_path(entry.get("local_path"), f"{artifact} local_path"),
        "sample_id": _require_string(entry.get("sample_id"), f"{artifact} sample_id"),
        "source": _require_source(entry, artifact),
    }


def _role_plan(role: str, pair: Mapping[str, Any], output_root: Path, threads: int) -> dict[str, Any]:
    role_inputs = _require_mapping(pair.get(role), f"bam_pair.{role}")
    bam = _bam_input(_entry(role_inputs, "bam", f"bam_pair.{role}"), f"{role}.bam")
    bai = _bam_input(_entry(role_inputs, "bai", f"bam_pair.{role}"), f"{role}.bai")
    if bam["sample_id"] != bai["sample_id"]:
        raise ManifestError(f"{role}.bam and {role}.bai sample_id values must match")
    if Path(bam["local_path"]).parent != Path(bai["local_path"]).parent:
        raise ManifestError(f"{role}.bam and {role}.bai must be staged together")

    outputs = {
        "idxstats": str(output_root / role / "idxstats.tsv"),
        "supplementary_alignments": str(output_root / role / "supplementary_alignments.count.txt"),
        "discordant_mapped_pairs": str(output_root / role / "discordant_mapped_pairs.sam"),
    }
    return {
        "inputs": {
            "bam": bam,
            "bai": bai,
        },
        "outputs": outputs,
        "commands": {
            "idxstats": {
                "argv": ["samtools", "idxstats", bam["local_path"]],
                "stdout_path": outputs["idxstats"],
            },
            "supplementary_alignments": {
                "argv": ["samtools", "view", "-@", str(threads), "-c", "-f", "2048", bam["local_path"]],
                "stdout_path": outputs["supplementary_alignments"],
            },
            "discordant_mapped_pairs": {
                "argv": ["samtools", "view", "-@", str(threads), "-f", "1", "-F", "14", bam["local_path"]],
                "stdout_path": outputs["discordant_mapped_pairs"],
            },
        },
    }


def build_phase3_fast_sv_evidence_plan(
    staged_inputs_manifest: Mapping[str, Any],
    *,
    staged_inputs_manifest_sha256: str,
    output_root: str | os.PathLike[str] = DEFAULT_OUTPUT_ROOT,
    threads: int = DEFAULT_THREADS,
) -> dict[str, Any]:
    if staged_inputs_manifest.get("manifest_type") != "phase3_wgs_fast_staged_inputs_manifest":
        raise ManifestError("staged inputs manifest_type must be phase3_wgs_fast_staged_inputs_manifest")
    if staged_inputs_manifest.get("status") != "ready":
        raise ManifestError("staged inputs status must be ready")
    if _require_mapping(staged_inputs_manifest.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("SV evidence plan authorized_hrd_state must remain no_call")

    pair = _require_mapping(staged_inputs_manifest.get("bam_pair"), "bam_pair")
    root = _require_output_root(output_root)
    thread_count = _require_positive_int(threads, "threads")
    role_plans = {role: _role_plan(role, pair, root, thread_count) for role in ROLES}
    if role_plans["tumor"]["inputs"]["bam"]["sample_id"] == role_plans["normal"]["inputs"]["bam"]["sample_id"]:
        raise ManifestError("tumor and normal sample names must differ")

    output_paths = {path for role in ROLES for path in role_plans[role]["outputs"].values()}
    if len(output_paths) != sum(len(role_plans[role]["outputs"]) for role in ROLES):
        raise ManifestError("SV evidence output paths must be unique")

    source = _require_mapping(staged_inputs_manifest.get("source"), "source")
    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_sv_evidence_plan",
        "status": "planned",
        "workflow": dict(_require_mapping(staged_inputs_manifest.get("workflow"), "workflow")),
        "run": dict(_require_mapping(staged_inputs_manifest.get("run"), "run")),
        "runtime": {
            **dict(_require_mapping(staged_inputs_manifest.get("runtime"), "runtime")),
            "samtools_threads": thread_count,
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
        "inputs": {role: role_plans[role]["inputs"] for role in ROLES},
        "outputs": {role: role_plans[role]["outputs"] for role in ROLES},
        "commands": {role: role_plans[role]["commands"] for role in ROLES},
        "output_root": str(root),
        "interpretation": {
            "authorized_hrd_state": "no_call",
            "hrd_use": "mechanical_sv_evidence_not_validated_sv_callset",
            "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
        },
    }


def write_plan(path: Path, plan: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast SV evidence plan output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_plan_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_SV_EVIDENCE_PLAN_OUTPUT", DEFAULT_OUTPUT))
    plan = build_phase3_fast_sv_evidence_plan(
        read_real_json(input_path, "staged_inputs", ManifestError),
        staged_inputs_manifest_sha256=_sha256_path(input_path),
        output_root=os.environ.get("PHASE3_WGS_FAST_SV_EVIDENCE_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
        threads=_require_threads(os.environ.get("PHASE3_WGS_FAST_SV_EVIDENCE_THREADS")),
    )
    return plan, output_path


def main() -> None:
    plan, output = load_plan_from_environment()
    write_plan(output, plan)
    print(f"Phase 3 WGS fast SV evidence plan written: {output}")


if __name__ == "__main__":
    main()
