"""Custody and input validation for public single-cell calibration runs."""
from __future__ import annotations

import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}", value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def safe_key(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")) or "\\" in value:
        raise ValueError(f"Unsafe relative path: {value!r}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, expected: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or sha256_file(path) != expected:
        raise ValueError(f"SHA-256 mismatch: {path.name}")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def extract_matrix(archive: Path, target: Path, matrix_name: str = "matrix.mtx") -> Path:
    """Reject links, special files, traversal, and oversized archives before extracting."""
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as handle:
        members = handle.getmembers()
        if len(members) > 100 or sum(m.size for m in members) > 1024**3:
            raise ValueError("Archive exceeds public-fixture limits")
        for member in members:
            safe_key(member.name.rstrip("/"))
            if not (member.isfile() or member.isdir()):
                raise ValueError("Archive contains link or special file")
        for member in members:
            dest = target / member.name
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                source = handle.extractfile(member)
                if source is None:
                    raise ValueError("Archive member is unreadable")
                with source, dest.open("xb") as output:
                    while block := source.read(1024 * 1024):
                        output.write(block)
    matrices = list(target.rglob(matrix_name)) + list(target.rglob(matrix_name + ".gz"))
    if len(matrices) != 1:
        raise ValueError("Expected exactly one 10x matrix")
    return matrices[0].parent


def artifact_index(root: Path) -> list[dict]:
    return [
        {"path": p.relative_to(root).as_posix(), "size_bytes": p.stat().st_size, "sha256": sha256_file(p)}
        for p in sorted(root.rglob("*")) if p.is_file() and p.name not in {"artifact_index.json", "run_manifest.json"}
    ]


def validate_config(config: dict) -> None:
    if config.get("evidence_lane") != "public_benchmark" or not config.get("datasets"):
        raise ValueError("This runner accepts public calibration datasets only")
    ids = [safe_id(d["dataset_id"]) for d in config["datasets"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate dataset identifiers")
    for dataset in config["datasets"]:
        for field in ("species", "tissue", "assay", "chemistry", "reference", "capture_id", "donor_id"):
            if not dataset.get(field):
                raise ValueError(f"Missing metadata: {field}")
        profile = dataset.get("qc_profile", "human_pbmc")
        tissues = {"human_pbmc": "PBMC", "human_breast_tumor": "breast tumor"}
        if dataset["species"] != "Homo sapiens" or tissues.get(profile) != dataset["tissue"]:
            raise ValueError("QC profile must match human PBMC or breast tumor tissue")
        if profile == "human_breast_tumor":
            for field in ("sample_id", "material", "clinical_subtype", "treatment_status", "timepoint", "capture_scope", "chemistry_status", "upstream_processing"):
                if not dataset.get(field):
                    raise ValueError(f"Missing breast cohort metadata: {field}")
            if dataset["material"] != "whole_cell":
                raise ValueError("Breast profile is whole-cell only; nuclei require separate calibration")
            if dataset["capture_scope"] not in {"verified_single_capture", "sample_proxy_unresolved"}:
                raise ValueError("Invalid capture scope")
            if dataset["chemistry_status"] not in {"verified", "unresolved"}:
                raise ValueError("Invalid chemistry status")
            multipliers = config.get("parameters", {}).get("qc_sensitivity_multipliers", [])
            if len(multipliers) < 2 or any(not 0 < m <= 10 for m in multipliers):
                raise ValueError("Breast QC requires positive sensitivity multipliers")
        if dataset["format"] not in {"10x_mtx_tar", "10x_h5", "geo_breast_mtx_tar"}:
            raise ValueError("Only count matrices are supported; FASTQ is a separate lane")
        if (profile == "human_breast_tumor") != (dataset["format"] == "geo_breast_mtx_tar"):
            raise ValueError("Breast pilot requires a GEO breast matrix with aligned author metadata")
        if not 100 <= dataset["expected_cells"] <= 25000:
            raise ValueError("Dataset exceeds bounded calibration size")
        roles = [i["role"] for i in dataset["inputs"]]
        if len(roles) != len(set(roles)) or set(roles) - {"counts", "reference_labels"}:
            raise ValueError("Input roles must be unique and supported; ambient raw-droplet inputs require a separate correction lane")
        if roles.count("counts") != 1:
            raise ValueError("Exactly one counts input required per dataset")
        for item in dataset["inputs"]:
            safe_key(item["filename"])
            if "/" in item["filename"] or not item["url"].startswith("https://"):
                raise ValueError("Expected HTTPS source and a plain filename")
    captures = [d["capture_id"] for d in config["datasets"]]
    if len(captures) != len(set(captures)):
        raise ValueError("A capture cannot be split across datasets: combine its cells before doublet calling")


def calibration_gates(metrics: dict, expected: int, acceptance: dict, has_reference: bool) -> dict[str, bool]:
    gates = {
        "input_cells_match": metrics["input_cells"] == expected,
        "retention": acceptance["retained_fraction_min"] <= metrics["retained_fraction"] <= acceptance["retained_fraction_max"],
        "cluster_count": acceptance["clusters_min"] <= metrics["clusters"] <= acceptance["clusters_max"],
        "finite_embedding": bool(metrics["finite_embedding"]),
        "seed_stability": metrics["seed_stability_ari"] >= acceptance["seed_stability_ari_min"],
        "raw_counts_preserved": bool(metrics["raw_counts_preserved"]),
        "doublets_called": metrics["doublet_method"] == "scDblFinder",
    }
    if has_reference:
        gates["reference_overlap"] = metrics.get("reference_common_cells", 0) >= acceptance["reference_common_cells_min"]
        gates["reference_agreement"] = metrics.get("reference_ari", -1) >= acceptance["reference_ari_min"]
    return gates
