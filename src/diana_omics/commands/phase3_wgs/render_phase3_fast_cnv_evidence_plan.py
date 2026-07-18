from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import ensure_parent, read_json, standard_contig
from .cnv_contigs import require_no_standard_autosome_gaps
from .render_phase3_fast_input_manifest import HEX64, ManifestError, _require_s3_uri, normalize_method_parameters
from .safe_json_output import require_safe_output_path

DEFAULT_INPUT = "manifests/phase3_wgs_fast/staged_inputs_manifest.json"
DEFAULT_OUTPUT = "manifests/phase3_wgs_fast/cnv_evidence_plan.json"
DEFAULT_OUTPUT_ROOT = "/scratch/diana/phase3_wgs_fast/cnv_evidence"
DEFAULT_BIN_SIZE = 5_000_000
DEFAULT_BEDCOV_WORKERS = 4
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


def _require_env_positive_int(value: str | int | None, *, default: int, env_name: str, label: str) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ManifestError(f"{env_name} must be an integer") from error
    return _require_positive_int(parsed, label)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_contig(contig: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", contig)


def _entry(container: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    return _require_mapping(container.get(key), f"{label}.{key}")


def _require_source(entry: Mapping[str, Any], artifact: str) -> dict[str, str]:
    source = _require_mapping(entry.get("source"), f"{artifact} source")
    return {
        "uri": _require_s3_uri(source.get("uri"), f"{artifact} source uri"),
        "version_id": _require_string(source.get("version_id"), f"{artifact} source version_id"),
    }


def _artifact_input(entry: Mapping[str, Any], artifact: str) -> dict[str, Any]:
    if entry.get("artifact") != artifact:
        raise ManifestError(f"{artifact} entry artifact must match")
    result: dict[str, Any] = {
        "local_path": _require_absolute_path(entry.get("local_path"), f"{artifact} local_path"),
        "source": _require_source(entry, artifact),
    }
    sample_id = entry.get("sample_id")
    if sample_id is not None:
        result["sample_id"] = _require_string(sample_id, f"{artifact} sample_id")
    return result


def _bam_input(entry: Mapping[str, Any], artifact: str) -> dict[str, Any]:
    result = _artifact_input(entry, artifact)
    result["sample_id"] = _require_string(result.get("sample_id"), f"{artifact} sample_id")
    return result


def _bam_inputs(pair: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    role_inputs: dict[str, dict[str, dict[str, Any]]] = {}
    for role in ROLES:
        role_container = _require_mapping(pair.get(role), f"bam_pair.{role}")
        bam = _bam_input(_entry(role_container, "bam", f"bam_pair.{role}"), f"{role}.bam")
        bai = _bam_input(_entry(role_container, "bai", f"bam_pair.{role}"), f"{role}.bai")
        if bam["sample_id"] != bai["sample_id"]:
            raise ManifestError(f"{role}.bam and {role}.bai sample_id values must match")
        if Path(bam["local_path"]).parent != Path(bai["local_path"]).parent:
            raise ManifestError(f"{role}.bam and {role}.bai must be staged together")
        role_inputs[role] = {"bam": bam, "bai": bai}

    if role_inputs["tumor"]["bam"]["sample_id"] == role_inputs["normal"]["bam"]["sample_id"]:
        raise ManifestError("tumor and normal sample names must differ")
    return role_inputs


def _standard_contigs(reference: Mapping[str, Any]) -> list[tuple[str, int]]:
    rows = reference.get("standard_contigs")
    if not isinstance(rows, list):
        raise ManifestError("reference.standard_contigs must be a list")

    contigs: list[tuple[str, int]] = []
    seen: set[str] = set()
    for index, value in enumerate(rows, start=1):
        row = _require_mapping(value, f"reference.standard_contigs[{index}]")
        contig = _require_string(row.get("contig"), f"reference.standard_contigs[{index}].contig")
        if not standard_contig(contig):
            continue
        if contig in seen:
            raise ManifestError(f"reference.standard_contigs contains duplicate contig {contig}")
        seen.add(contig)
        length = _require_positive_int(row.get("length"), f"reference.standard_contigs[{index}].length")
        contigs.append((contig, length))

    if not contigs:
        raise ManifestError("reference.standard_contigs must include at least one standard chr1-chr22/chrX/chrY contig")
    require_no_standard_autosome_gaps(
        (contig for contig, _ in contigs),
        "reference.standard_contigs",
        ManifestError,
    )
    return contigs


def _reference_inputs(reference: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    fasta = _artifact_input(_entry(reference, "fasta", "reference"), "reference.fa")
    fai = _artifact_input(_entry(reference, "fai", "reference"), "reference.fa.fai")
    sequence_dictionary = _artifact_input(_entry(reference, "sequence_dictionary", "reference"), "reference.dict")
    if Path(fasta["local_path"]).parent != Path(fai["local_path"]).parent:
        raise ManifestError("reference.fa and reference.fa.fai must be staged together")
    if Path(fasta["local_path"]).parent != Path(sequence_dictionary["local_path"]).parent:
        raise ManifestError("reference.fa and reference.dict must be staged together")
    return {
        "fasta": fasta,
        "fai": fai,
        "sequence_dictionary": sequence_dictionary,
    }


def _interval_shards(contigs: list[tuple[str, int]], output_root: Path, bin_size: int) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    for contig, length in contigs:
        bin_count = (length + bin_size - 1) // bin_size
        safe_contig = _safe_contig(contig)
        shards.append(
            {
                "contig": contig,
                "length": length,
                "bin_size": bin_size,
                "bin_count": bin_count,
                "intervals_bed": str(output_root / "intervals" / f"{safe_contig}.bed"),
                "bedcov_tsv": str(output_root / "bedcov_shards" / f"{safe_contig}.bedcov.tsv"),
            }
        )
    return shards


def build_phase3_fast_cnv_evidence_plan(
    staged_inputs_manifest: Mapping[str, Any],
    *,
    staged_inputs_manifest_sha256: str,
    output_root: str | os.PathLike[str] = DEFAULT_OUTPUT_ROOT,
    bin_size: int = DEFAULT_BIN_SIZE,
    bedcov_workers: int = DEFAULT_BEDCOV_WORKERS,
) -> dict[str, Any]:
    if staged_inputs_manifest.get("manifest_type") != "phase3_wgs_fast_staged_inputs_manifest":
        raise ManifestError("staged inputs manifest_type must be phase3_wgs_fast_staged_inputs_manifest")
    if staged_inputs_manifest.get("status") != "ready":
        raise ManifestError("staged inputs status must be ready")
    if _require_mapping(staged_inputs_manifest.get("interpretation"), "interpretation").get("authorized_hrd_state") != "no_call":
        raise ManifestError("CNV evidence plan authorized_hrd_state must remain no_call")

    root = _require_output_root(output_root)
    checked_bin_size = _require_positive_int(bin_size, "bin_size")
    checked_bedcov_workers = _require_positive_int(bedcov_workers, "bedcov_workers")
    bam_inputs = _bam_inputs(_require_mapping(staged_inputs_manifest.get("bam_pair"), "bam_pair"))
    reference = _require_mapping(staged_inputs_manifest.get("reference"), "reference")
    reference_inputs = _reference_inputs(reference)
    shards = _interval_shards(_standard_contigs(reference), root, checked_bin_size)

    outputs = {
        "combined_bedcov": str(root / "coverage_cnv_bedcov.tsv"),
        "coverage_bins": str(root / "coverage_cnv_bins.csv"),
        "summary_csv": str(root / "coverage_cnv_summary.csv"),
        "summary_json": str(root / "coverage_cnv_summary.json"),
    }
    output_paths = set(outputs.values())
    for shard in shards:
        output_paths.add(shard["intervals_bed"])
        output_paths.add(shard["bedcov_tsv"])
    if len(output_paths) != len(outputs) + 2 * len(shards):
        raise ManifestError("CNV evidence output paths must be unique")

    tumor_bam = bam_inputs["tumor"]["bam"]["local_path"]
    normal_bam = bam_inputs["normal"]["bam"]["local_path"]
    commands = {
        shard["contig"]: {
            "argv": ["samtools", "bedcov", shard["intervals_bed"], tumor_bam, normal_bam],
            "stdout_path": shard["bedcov_tsv"],
        }
        for shard in shards
    }
    source = _require_mapping(staged_inputs_manifest.get("source"), "source")
    return {
        "schema_version": 1,
        "manifest_type": "phase3_wgs_fast_cnv_evidence_plan",
        "status": "planned",
        "workflow": dict(_require_mapping(staged_inputs_manifest.get("workflow"), "workflow")),
        "run": dict(_require_mapping(staged_inputs_manifest.get("run"), "run")),
        "runtime": {
            **dict(_require_mapping(staged_inputs_manifest.get("runtime"), "runtime")),
            "bin_size": checked_bin_size,
            "bedcov_workers": checked_bedcov_workers,
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
            "tumor": bam_inputs["tumor"],
            "normal": bam_inputs["normal"],
            "reference": reference_inputs,
        },
        "interval_shards": shards,
        "outputs": outputs,
        "commands": {
            "bedcov_by_contig": commands,
        },
        "output_root": str(root),
        "interpretation": {
            "authorized_hrd_state": "no_call",
            "hrd_use": "coverage_cnv_evidence_not_allele_specific",
            "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
        },
    }


def write_plan(path: Path, plan: Mapping[str, Any]) -> None:
    require_safe_output_path(path, "fast CNV evidence plan output", ManifestError)
    ensure_parent(path)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_plan_from_environment() -> tuple[dict[str, Any], Path]:
    input_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST", DEFAULT_INPUT))
    output_path = path_from_root(os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN_OUTPUT", DEFAULT_OUTPUT))
    plan = build_phase3_fast_cnv_evidence_plan(
        read_json(input_path),
        staged_inputs_manifest_sha256=_sha256_path(input_path),
        output_root=os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
        bin_size=_require_env_positive_int(
            os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_BIN_SIZE"),
            default=DEFAULT_BIN_SIZE,
            env_name="PHASE3_WGS_FAST_CNV_EVIDENCE_BIN_SIZE",
            label="bin_size",
        ),
        bedcov_workers=_require_env_positive_int(
            os.environ.get("PHASE3_WGS_FAST_CNV_EVIDENCE_BEDCOV_WORKERS"),
            default=DEFAULT_BEDCOV_WORKERS,
            env_name="PHASE3_WGS_FAST_CNV_EVIDENCE_BEDCOV_WORKERS",
            label="bedcov_workers",
        ),
    )
    return plan, output_path


def main() -> None:
    plan, output = load_plan_from_environment()
    write_plan(output, plan)
    print(f"Phase 3 WGS fast CNV evidence plan written: {output}")


if __name__ == "__main__":
    main()
