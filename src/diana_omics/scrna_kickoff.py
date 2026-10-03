from __future__ import annotations

import hashlib
import re
import tarfile
from pathlib import Path
from typing import Any, Iterable

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def require_run_id(value: str) -> str:
    run_id = value.strip()
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must be 1-128 characters using only letters, numbers, dot, underscore, or dash")
    return run_id


def require_relative_object(value: str) -> str:
    object_key = value.strip()
    path = Path(object_key)
    if not object_key or path.is_absolute() or ".." in path.parts or object_key.endswith("/"):
        raise ValueError("input_object must be a non-directory relative S3 object key")
    return object_key


def require_sha256(value: str) -> str:
    digest = value.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("expected_sha256 must be a lowercase 64-character SHA-256 digest")
    return digest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, root: Path) -> dict[str, Any]:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise ValueError(f"artifact path is outside the run root: {path}")
    return {
        "path": resolved_path.relative_to(resolved_root).as_posix(),
        "bytes": resolved_path.stat().st_size,
        "sha256": file_sha256(resolved_path),
    }


def safe_extract_tar(archive_path: Path, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=False)
    resolved_destination = destination.resolve()
    extracted: list[Path] = []
    with tarfile.open(archive_path, mode="r:*") as archive:
        members = archive.getmembers()
        for member in members:
            if member.issym() or member.islnk():
                raise ValueError(f"archive links are not allowed: {member.name}")
            if not member.isfile() and not member.isdir():
                raise ValueError(f"unsupported archive member type: {member.name}")
            output_path = (destination / member.name).resolve()
            if output_path != resolved_destination and resolved_destination not in output_path.parents:
                raise ValueError(f"archive member escapes the extraction root: {member.name}")
            extracted.append(output_path)
        archive.extractall(destination, members=members)
    return extracted


def find_10x_matrix_dir(extracted: Iterable[Path]) -> Path:
    matrix_files = [path for path in extracted if path.is_file() and path.name in {"matrix.mtx", "matrix.mtx.gz"}]
    if len(matrix_files) != 1:
        raise ValueError(f"expected exactly one 10x matrix.mtx file, found {len(matrix_files)}")
    matrix_dir = matrix_files[0].parent
    barcode_files = [matrix_dir / "barcodes.tsv", matrix_dir / "barcodes.tsv.gz"]
    feature_files = [
        matrix_dir / "features.tsv",
        matrix_dir / "features.tsv.gz",
        matrix_dir / "genes.tsv",
        matrix_dir / "genes.tsv.gz",
    ]
    if not any(path.is_file() for path in barcode_files):
        raise ValueError("10x matrix directory is missing barcodes.tsv")
    if not any(path.is_file() for path in feature_files):
        raise ValueError("10x matrix directory is missing features.tsv or genes.tsv")
    return matrix_dir
