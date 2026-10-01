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


def extract_matrix(archive: Path, target: Path) -> Path:
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
    matrices = list(target.rglob("matrix.mtx")) + list(target.rglob("matrix.mtx.gz"))
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
        if dataset["species"] != "Homo sapiens" or dataset["tissue"] != "PBMC":
            raise ValueError("Pilot thresholds and markers are restricted to human PBMCs")
        if dataset["format"] not in {"10x_mtx_tar", "10x_h5"}:
            raise ValueError("Only count matrices are supported; FASTQ is a separate lane")
        if not 100 <= dataset["expected_cells"] <= 25000:
            raise ValueError("Dataset exceeds bounded calibration size")
        if sum(i["role"] == "counts" for i in dataset["inputs"]) != 1:
            raise ValueError("Exactly one counts input required per dataset")
        for item in dataset["inputs"]:
            safe_key(item["filename"])
            if "/" in item["filename"] or not item["url"].startswith("https://"):
                raise ValueError("Expected HTTPS source and a plain filename")


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
