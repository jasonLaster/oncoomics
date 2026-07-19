#!/usr/bin/env python3
"""Stage a strict deterministic full-WGS packet from frozen worker artifacts."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import finalize_input_contract as INPUT_CONTRACT
from capture_materializer_terminal import (
    EXPECTED_DESTINATION_INVENTORY_KEYS as EXPECTED_CROSSCHECK_DESTINATION_INVENTORY_KEYS,
)
from capture_materializer_terminal import (
    EXPECTED_EXACT_RECEIPT_DOWNLOAD_CHECKS as EXPECTED_CROSSCHECK_RECEIPT_DOWNLOAD_CHECKS,
)
from capture_materializer_terminal import (
    EXPECTED_MATERIALIZER_RECEIPT_CHECKS as EXPECTED_CROSSCHECK_RECEIPT_CHECKS,
)
from capture_materializer_terminal import (
    EXPECTED_MATERIALIZER_RECEIPT_KEYS as EXPECTED_CROSSCHECK_RECEIPT_KEYS,
)
from forbidden_text import merge_forbidden_tokens

EXPECTED_READINESS = {
    "source_sha256": "ready",
    "wgs_alignment": "ready",
    "matched_normal_somatic_variants": "ready",
    "coverage_cnv": "partial_evidence",
    "sbs96": "partial_evidence",
    "sv": "partial_evidence",
    "scarHRD": "no_call",
    "CHORD": "no_call",
    "HRDetect": "no_call",
    "overall_hrd": "no_call",
}

OUTPUT_READINESS = [
    ("Intake SHA-256", "ready", "Every audited source payload object, including all WGS FASTQs, matched its expected size and SHA-256."),
    ("Tumor/normal alignment", "ready", "Both full-WGS BAM validation rows passed and agree with gather provenance."),
    ("Matched-normal somatic caller output", "ready", "A filtered genome-wide Mutect2 VCF and valid index are present; this is output readiness, not interpretation readiness."),
    ("Contamination QC", "ready", "Matched-normal contamination estimation and segmentation artifacts are present."),
    ("BRCA1/BRCA2 region extraction", "partial_evidence", "PASS rows are region-only records requiring annotation and review."),
    ("SBS96 input", "partial_evidence", "A 96-channel matrix was derived from PASS SNVs; no SBS3 assignment is authorized."),
    ("Coverage-CNV proxy", "partial_evidence", "Normalized 5 Mb depth bins are not allele-specific segments."),
    ("BAM-derived SV evidence", "partial_evidence", "Discordant/supplementary counts are descriptive and are not a production breakend callset."),
    ("Biallelic HRR/LOH", "no_call", "No allele-specific CNV/LOH and curated second-hit assessment is present."),
    ("Purity/ploidy", "no_call", "No validated purity/ploidy solution is present."),
    ("SBS3", "no_call", "No validated signature assignment and locked SBS3 threshold policy is present."),
    ("Production breakend SV", "no_call", "No validated production breakend-SV VCF/BEDPE is present."),
    ("scarHRD", "no_call", "Allele-specific total/minor copy-number segments plus purity/ploidy are absent."),
    ("CHORD", "no_call", "Required somatic SNV/indel and validated production breakend-SV feature inputs are absent."),
    ("HRDetect-style model", "no_call", "The complete calibrated feature vector and validated integration policy are absent."),
    ("Overall HRD", "no_call", "The full deterministic evidence bundle remains partial_evidence without a defensible scalar or categorical HRD call."),
]

SV_COUNT_FIELDS = (
    "total_alignments",
    "supplementary_alignments",
    "discordant_mapped_pairs",
    "interchromosomal_pairs",
    "large_insert_pairs",
)

OUTPUT_NAMES = (
    "report.md",
    "readiness.csv",
    "evidence_checks.json",
    "crosscheck_input_plans.json",
    "input_sha256.csv",
    "report_manifest.json",
)
REPORT_MANIFEST_KEYS = {
    "schema_version",
    "method_id",
    "report_kind",
    "evidence_status",
    "authorized_hrd_state",
    "classification_authorized",
    "classification_qc_status",
    "support_sha256",
    "source_sha256",
    "report_sha256",
    "review_summary",
}
SBS_MUTATION_TYPES = ("C>A", "C>G", "C>T", "T>A", "T>C", "T>G")
SBS_BASES = "ACGT"
EXPECTED_SBS96 = {
    (mutation, f"{left}[{mutation}]{right}")
    for mutation in SBS_MUTATION_TYPES
    for left in SBS_BASES
    for right in SBS_BASES
}
EXPECTED_STAGE_PROVENANCE_OBJECT_CHECKS: dict[str, bool] = {
    "get_matches_head": True,
    "local_bytes_exact": True,
    "semantic_binding": True,
    "source_kms_exact": True,
    "source_unchanged": True,
    "copy_version_exact": True,
    "destination_get_matches_head": True,
    "bytes_equal": True,
    "sha256_equal": True,
    "full_object_checksum": True,
    "exact_kms": True,
}
EXPECTED_STAGE_PROVENANCE_ANCHOR_CHECKS: dict[str, bool] = {
    "version_exact": True,
    "get_matches_head": True,
    "bytes_exact": True,
    "local_sha256_exact": True,
    "sha256_checksum_exact": True,
    "exact_kms": True,
    "content_type_exact": True,
    "history_exact": True,
}
EXPECTED_FINAL_FREEZE_ROW_CHECKS: dict[str, bool] = {
    "listed_inventory_stable": True,
    "source_stable": True,
    "size_matches": True,
    "common_checksum_matches": True,
    "exact_kms_matches": True,
    "destination_versioned": True,
    "copy_response_version_matches": True,
}
EXPECTED_FINAL_FREEZE_CHECKS: dict[str, bool] = {
    "execution_receipt_bound": True,
    "complete_source_inventory_unchanged": True,
    "destination_exact_history_and_receipt_match": True,
}
EXPECTED_FINAL_FREEZE_ANCHOR_CHECKS: dict[str, bool] = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "sha256_checksum_exact": True,
    "exact_kms": True,
    "single_create_only_version": True,
}
EXPECTED_BATCH_WORKER_CHECKS: dict[str, bool] = {
    "receipt_status": True,
    "receipt_envelope": True,
    "receipt_source_envelope": True,
    "receipt_freeze_envelope": True,
    "receipt_freeze_metadata": True,
    "receipt_checks": True,
    "receipt_upload": True,
    "receipt_upload_envelope": True,
    "receipt_upload_object_envelope": True,
    "receipt_upload_metadata": True,
    "task_identity": True,
    "task_host_mapping": True,
    "hash_command_definition": True,
    "freeze_command_definition": True,
    "live_hash_command": True,
    "live_freeze_command": True,
    "exact_version": True,
    "bytes": True,
    "sha256": True,
    "full_object_checksum": True,
    "kms": True,
}
EXPECTED_EXECUTED_WORKER_FREEZE_CHECKS: dict[str, bool] = {
    "active_task_identity_matches_batch_job": True,
    "container_file_hash_and_size_captured": True,
    "container_file_uploaded_directly": True,
    "s3_bytes_match_container_bytes": True,
    "s3_exact_kms_key_matches": True,
    "s3_exact_version_present": True,
    "s3_full_object_sha256_matches_container_sha256": True,
    "s3_metadata_sha256_matches_container_sha256": True,
}
EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_CHECKS: dict[str, bool] = {
    "bytes": True,
    "exact_kms": True,
    "exact_version": True,
    "full_object_sha256": True,
    "local_sha256_matches_s3_checksum": True,
    "metadata": True,
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
S3_CHECKSUM_FIELDS = {
    "ChecksumCRC64NVME",
    "ChecksumSHA256",
    "ChecksumSHA1",
    "ChecksumCRC32C",
    "ChecksumCRC32",
}
EXPECTED_CROSSCHECK_CAPTURE_CHECKS: dict[str, bool] = {
    "terminal_batch_identity": True,
    "exact_cloudwatch_stream": True,
    "single_terminal_anchor": True,
    "logged_receipt_binding": True,
    "bucket_versioning_enabled": True,
    "exact_version_get": True,
    "exact_version_head": True,
    "logged_local_sha256_and_bytes": True,
    "s3_sha256_checksums": True,
    "exact_kms": True,
    "single_version_no_delete_history": True,
    "private_mode_0600": True,
}
EXPECTED_CROSSCHECK_BATCH_CHECKS: dict[str, bool] = {
    "job_id_exact": True,
    "succeeded": True,
    "terminal_timestamps": True,
    "exact_job_definition": True,
    "exact_queue": True,
    "one_retry_attempt": True,
    "one_terminal_attempt": True,
    "job_exit_zero": True,
    "attempt_exit_zero": True,
    "parameters_exact": True,
    "log_stream_exact": True,
    "definition_exact": True,
    "definition_log_exact": True,
    "queue_live_exact": True,
    "arm_compute_environment_exact": True,
}
EXPECTED_CROSSCHECK_ANCHOR_CHECKS: dict[str, bool] = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_create_only_version": True,
}
EXPECTED_CROSSCHECK_OUTPUT_CHECKS: dict[str, bool] = {
    "create_only_put": True,
    "version_exact": True,
    "bytes_exact": True,
    "sha256_checksum_exact": True,
    "metadata_sha256_exact": True,
    "exact_kms": True,
    "single_version_history": True,
}
EXPECTED_STAGED_VALIDATION_DOWNLOAD_CHECKS: dict[str, bool] = {
    "version_exact": True,
    "bytes_exact": True,
    "sha256_exact": True,
    "get_checksum_present": True,
    "head_checksum_present": True,
    "full_object_sha256_exact": True,
    "exact_kms": True,
}


def load_json(path: Path) -> dict[str, Any]:
    require_real_input_path(path, "JSON input")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def load_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    require_real_input_path(path, "CSV input")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode("ascii")


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_snapshot_receipt(path: Path, value: dict[str, Any]) -> None:
    require_no_symlinked_ancestors(path, "input snapshot receipt")
    if path.is_symlink():
        raise ValueError(f"input snapshot receipt may not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"input snapshot receipt already exists: {path}")

    data = json_bytes(value)
    expected_sha256 = sha256_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), 0o400)
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        require_installed_snapshot_receipt(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_installed_snapshot_receipt(path: Path, expected_sha256: str) -> None:
    require_real_input_path(path, "input snapshot receipt")
    if (path.stat().st_mode & 0o777) != 0o400:
        raise ValueError(f"input snapshot receipt mode is not 0400: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(f"input snapshot receipt changed during write: {path}")


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def regular_file_identity(path: Path, label: str) -> tuple[int, int, int, int, int, int]:
    value = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"{label} is not a real regular file: {path}")
    return stat_identity(value)


def discover_input_tree(
    root: Path, label: str
) -> dict[str, tuple[Path, tuple[int, int, int, int, int, int]]]:
    root_stat = os.stat(root, follow_symlinks=False)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError(f"{label} must be a real directory: {root}")
    rows: dict[str, tuple[Path, tuple[int, int, int, int, int, int]]] = {}
    for current_value, directories, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_value)
        directories.sort()
        files.sort()
        for name in directories:
            directory = current / name
            value = os.stat(directory, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode):
                raise ValueError(f"{label} contains a symlink or non-directory: {directory}")
        for name in files:
            path = current / name
            relative = safe_artifact_relative(path.relative_to(root).as_posix())
            identity = regular_file_identity(path, label)
            if relative in rows:
                raise ValueError(f"{label} contains a duplicate path: {relative}")
            rows[relative] = (path, identity)
    if not rows:
        raise ValueError(f"{label} contains no files")
    return rows


def copy_baseline_file(
    source: Path,
    destination: Path,
    expected_identity: tuple[int, int, int, int, int, int],
) -> None:
    before = os.stat(source, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or stat_identity(before) != expected_identity:
        raise ValueError(f"input changed before stable snapshot: {source}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or stat_identity(opened) != expected_identity:
            raise ValueError(f"input changed while opening stable snapshot: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.parent.chmod(0o700)
        copied = 0
        with os.fdopen(descriptor, "rb", closefd=False) as input_handle:
            with destination.open("xb") as output_handle:
                for block in iter(lambda: input_handle.read(8 * 1024 * 1024), b""):
                    output_handle.write(block)
                    copied += len(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if stat_identity(after) != expected_identity or copied != expected_identity[3]:
        destination.unlink(missing_ok=True)
        raise ValueError(f"input changed during stable snapshot: {source}")
    destination.chmod(0o400)


def verify_input_tree_unchanged(
    root: Path,
    label: str,
    baseline: dict[str, tuple[Path, tuple[int, int, int, int, int, int]]],
) -> None:
    current = discover_input_tree(root, label)
    if set(current) != set(baseline):
        raise ValueError(f"{label} inventory changed during stable snapshot")
    for relative, (_, expected_identity) in baseline.items():
        if current[relative][1] != expected_identity:
            raise ValueError(
                f"{label} file changed during stable snapshot: {relative}"
            )


def create_stable_input_snapshot(
    artifact_root: Path,
    early_root: Path,
    external_sources: dict[str, Path],
    snapshot_root: Path,
) -> dict[str, Any]:
    require_no_symlinked_ancestors(artifact_root, "artifact input tree")
    require_no_symlinked_ancestors(early_root, "early-look input tree")
    if artifact_root.is_symlink() or early_root.is_symlink():
        raise ValueError("input tree roots may not be symlinks")
    artifact_root = artifact_root.resolve()
    early_root = early_root.resolve()
    if (
        artifact_root == early_root
        or artifact_root.is_relative_to(early_root)
        or early_root.is_relative_to(artifact_root)
    ):
        raise ValueError("artifact and early-look input trees must be disjoint")
    snapshot_root.mkdir(parents=True, exist_ok=False)
    snapshot_root.chmod(0o700)
    artifact_baseline = discover_input_tree(artifact_root, "artifact input tree")
    early_baseline = discover_input_tree(early_root, "early-look input tree")
    external_baseline: dict[
        str, tuple[Path, tuple[int, int, int, int, int, int]]
    ] = {}
    for input_id, source in sorted(external_sources.items()):
        if not re.fullmatch(r"[a-z0-9_]+", input_id):
            raise ValueError(f"unsafe external input identifier: {input_id}")
        require_no_symlinked_ancestors(source, f"external input {input_id}")
        if source.is_symlink():
            raise ValueError(f"external input may not be a symlink: {input_id}")
        resolved = source.resolve()
        identity = regular_file_identity(resolved, f"external input {input_id}")
        if identity[3] <= 0:
            raise ValueError(f"external input is empty: {input_id}")
        external_baseline[input_id] = (resolved, identity)

    artifact_snapshot = snapshot_root / "artifact-root"
    early_snapshot = snapshot_root / "early-look-root"
    external_snapshot = snapshot_root / "external"
    for relative, (source, identity) in sorted(artifact_baseline.items()):
        copy_baseline_file(source, artifact_snapshot / relative, identity)
    for relative, (source, identity) in sorted(early_baseline.items()):
        copy_baseline_file(source, early_snapshot / relative, identity)
    external_paths: dict[str, Path] = {}
    for input_id, (source, identity) in sorted(external_baseline.items()):
        destination = external_snapshot / f"{input_id}.input"
        copy_baseline_file(source, destination, identity)
        external_paths[input_id] = destination

    verify_input_tree_unchanged(
        artifact_root, "artifact input tree", artifact_baseline
    )
    verify_input_tree_unchanged(early_root, "early-look input tree", early_baseline)
    for input_id, (source, expected_identity) in external_baseline.items():
        if regular_file_identity(source, f"external input {input_id}") != expected_identity:
            raise ValueError(
                f"external input changed during stable snapshot: {input_id}"
            )

    manifest_rows: list[dict[str, Any]] = []
    for namespace, destination_root, baseline in (
        ("artifact", artifact_snapshot, artifact_baseline),
        ("early_look", early_snapshot, early_baseline),
    ):
        for relative in sorted(baseline):
            path = destination_root / relative
            manifest_rows.append(
                {
                    "input_id": f"{namespace}/{relative}",
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    for input_id, path in sorted(external_paths.items()):
        manifest_rows.append(
            {
                "input_id": f"external/{input_id}",
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "status": "passed",
        "snapshot_strategy": "open_no_follow_fstat_copy_global_restat",
        "file_count": len(manifest_rows),
        "files": manifest_rows,
    }
    manifest_path = snapshot_root / "input-snapshot-receipt.json"
    write_snapshot_receipt(manifest_path, manifest)
    return {
        "artifact_root": artifact_snapshot,
        "early_root": early_snapshot,
        "external_paths": external_paths,
        "manifest_path": manifest_path,
        "manifest": manifest,
    }


def safe_artifact_relative(value: Any) -> str:
    text = str(value)
    path = PurePosixPath(text)
    if (
        not text
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in text
        or path.as_posix() != text
    ):
        raise ValueError(f"Unsafe artifact relative key: {text}")
    return text


def format_int(value: Any) -> str:
    return f"{int(value):,}"


def format_gib(value: Any) -> str:
    return f"{int(value) / (1024 ** 3):.3f} GiB"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [f"| {' | '.join(headers)} |", f"| {' | '.join(['---'] * len(headers))} |"]
    lines.extend(f"| {' | '.join(str(value).replace('|', '/') for value in row)} |" for row in rows)
    return "\n".join(lines)


def add_check(checks: list[dict[str, str]], check_id: str, condition: bool, detail: str) -> None:
    checks.append({"check_id": check_id, "status": "passed" if condition else "failed", "detail": detail})


def bcftools_count(bcftools: str, path: Path, args: Iterable[str]) -> int:
    command = [bcftools, "view", *args, "-H", str(path)]
    count = 0
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        assert proc.stdout is not None
        for _ in proc.stdout:
            count += 1
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError(f"bcftools failed ({return_code}): {' '.join(command)}\n{stderr}")
    return count


def bcftools_index_records(bcftools: str, path: Path) -> int:
    output = subprocess.check_output([bcftools, "index", "-n", str(path)], text=True, stderr=subprocess.STDOUT).strip()
    return int(output)


def safe_float(value: Any) -> float:
    return float(str(value))


def valid_sha256(value: Any) -> bool:
    return bool(HEX64.fullmatch(str(value)))


def valid_version_id(value: Any) -> bool:
    text = str(value)
    return bool(
        text
        and text.lower() not in {"none", "null"}
        and not any(character.isspace() for character in text)
    )


def s3_checksums(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: str(raw)
        for key, raw in value.items()
        if key in S3_CHECKSUM_FIELDS and str(raw).strip()
    }


def s3_full_object_sha256_matches(value: Any, digest: Any) -> bool:
    text = str(digest)
    if not valid_sha256(text) or not isinstance(value, dict):
        return False
    return (
        value.get("ChecksumType") == "FULL_OBJECT"
        and value.get("ChecksumSHA256") == checksum_sha256(text)
    )


def s3_key(value: Any) -> str:
    parsed = urlparse(str(value))
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        return ""
    return parsed.path.lstrip("/")


def positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def integer_equals(value: Any, expected: int) -> bool:
    return type(value) is int and type(expected) is int and value == expected


def parse_nonnegative_int_text(value: Any) -> Optional[int]:
    if type(value) is not str or not value.isdecimal():
        return None
    if len(value) > 1 and value.startswith("0"):
        return None
    return int(value)


def require_nonnegative_exact_int(value: Any, label: str) -> int:
    if not nonnegative_int(value):
        raise ValueError(f"{label} is not an exact nonnegative integer")
    return value


def require_exact_bool(value: Any, expected: bool, label: str) -> bool:
    if value is not expected:
        raise ValueError(f"{label} is not exactly {expected}")
    return value


def exact_schema_version(payload: dict[str, Any], expected: int) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def exact_schema_status(payload: dict[str, Any], expected: int = 1) -> bool:
    return exact_schema_version(payload, expected) and payload.get("status") == "passed"


def exact_materialization_receipt_envelope(receipt: dict[str, Any]) -> bool:
    observed = set(receipt)
    unexpected = (
        observed
        - INPUT_CONTRACT.EXPECTED_MATERIALIZATION_KEYS
        - INPUT_CONTRACT.OPTIONAL_MATERIALIZATION_RECOVERY_KEYS
    )
    return observed >= INPUT_CONTRACT.EXPECTED_MATERIALIZATION_KEYS and not unexpected


def validate_stage_provenance(
    receipt: dict[str, Any],
    anchor: dict[str, Any],
    *,
    receipt_path: Path,
    execution_path: Path,
    preflight_path: Path,
    gather_path: Path,
    run_id: str,
    batch_job_id: str,
    expected_kms_key_arn: str,
) -> dict[str, Any]:
    rows = receipt.get("objects") if isinstance(receipt.get("objects"), list) else []
    by_name: dict[str, dict[str, Any]] = {}
    duplicate_or_malformed = False
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            duplicate_or_malformed = True
            continue
        name = str(raw_row.get("name", ""))
        if name in by_name or name not in {"preflight.json", "gather.json"}:
            duplicate_or_malformed = True
            continue
        by_name[name] = raw_row

    destination_prefix = str(receipt.get("destination_prefix", ""))
    source_prefix = str(receipt.get("source_prefix", ""))
    destination_match = re.fullmatch(
        rf"s3://(diana-omics-private-results-[^/]+)/"
        rf"(runs/subject01/{re.escape(run_id)}/deterministic/provenance/wgs-stage/)",
        destination_prefix,
    )
    source_match = re.fullmatch(
        rf"s3://(diana-omics-work-[^/]+)/"
        rf"(runs/diana-hrd/{re.escape(run_id)}/private-results/)",
        source_prefix,
    )
    source_prefix_valid = bool(source_match)
    source_bucket = source_match.group(1) if source_match else ""
    source_key_prefix = source_match.group(2) if source_match else ""
    destination_bucket = destination_match.group(1) if destination_match else ""
    destination_key_prefix = destination_match.group(2) if destination_match else ""
    local_paths = {
        "preflight.json": preflight_path,
        "gather.json": gather_path,
    }
    object_checks: dict[str, bool] = {}
    for name, local_path in local_paths.items():
        row = by_name.get(name, {})
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        destination = (
            row.get("destination")
            if isinstance(row.get("destination"), dict)
            else {}
        )
        row_checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
        local_sha = sha256(local_path)
        object_checks[name] = bool(
            row.get("status") == "passed"
            and row_checks == EXPECTED_STAGE_PROVENANCE_OBJECT_CHECKS
            and source.get("bucket") == source_bucket
            and source.get("key") == source_key_prefix + name
            and source.get("version_id") == "null"
            and integer_equals(source.get("bytes"), local_path.stat().st_size)
            and source.get("checksum_type") == "FULL_OBJECT"
            and bool(s3_checksums(source.get("checksums")))
            and source.get("sha256") == local_sha
            and source.get("server_side_encryption") == "aws:kms"
            and source.get("kms_key_id") == expected_kms_key_arn
            and destination.get("bucket") == destination_bucket
            and destination.get("key") == destination_key_prefix + name
            and valid_version_id(destination.get("version_id"))
            and integer_equals(destination.get("bytes"), local_path.stat().st_size)
            and destination.get("checksum_type") == "FULL_OBJECT"
            and bool(s3_checksums(destination.get("checksums")))
            and destination.get("sha256") == local_sha
            and destination.get("kms_key_id") == expected_kms_key_arn
        )

    receipt_sha = sha256(receipt_path)
    anchor_checks = anchor.get("checks") if isinstance(anchor.get("checks"), dict) else {}
    expected_receipt_uri = (
        destination_prefix + f"receipts/{receipt_sha}.json"
        if destination_match
        else ""
    )
    checks = {
        "receipt_schema_status": exact_schema_status(receipt),
        "receipt_run_execution": (
            receipt.get("run_id") == run_id
            and receipt.get("batch_job_id") == batch_job_id
            and receipt.get("batch_status") == "SUCCEEDED"
            and receipt.get("execution_receipt_sha256") == sha256(execution_path)
        ),
        "receipt_private_destination": bool(destination_match),
        "receipt_work_source": source_prefix_valid,
        "receipt_kms": receipt.get("kms_key_arn") == expected_kms_key_arn,
        "receipt_versioning_and_history": (
            receipt.get("source_bucket_versioning") == "Suspended"
            and receipt.get("destination_bucket_versioning") == "Enabled"
            and receipt.get("destination_history_exact") is True
        ),
        "receipt_script": valid_sha256(receipt.get("script_sha256")),
        "receipt_anchor_strategy": (
            receipt.get("receipt_anchor_strategy")
            == "sha256_content_addressed_never_overwritten"
        ),
        "receipt_exact_inventory": (
            not duplicate_or_malformed
            and set(by_name) == {"preflight.json", "gather.json"}
            and len(rows) == 2
            and integer_equals(receipt.get("object_count"), 2)
            and integer_equals(receipt.get("passed_count"), 2)
        ),
        "preflight_exact_version": object_checks.get("preflight.json") is True,
        "gather_exact_version": object_checks.get("gather.json") is True,
        "anchor_schema_status": exact_schema_status(anchor),
        "anchor_content_address": (
            anchor.get("receipt_sha256") == receipt_sha
            and integer_equals(anchor.get("receipt_bytes"), receipt_path.stat().st_size)
            and anchor.get("receipt_uri") == expected_receipt_uri
            and valid_version_id(anchor.get("receipt_version_id"))
        ),
        "anchor_checks": bool(anchor_checks)
        and anchor_checks == EXPECTED_STAGE_PROVENANCE_ANCHOR_CHECKS,
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "receipt_sha256": receipt_sha,
        "receipt_version_id": str(anchor.get("receipt_version_id", "")),
        "object_count": len(rows),
        "checks": checks,
    }


def validate_crosscheck_terminal_capture(
    capture: dict[str, Any],
    anchor: dict[str, Any],
    receipt: dict[str, Any],
    download: dict[str, Any],
    *,
    capture_path: Path,
    anchor_path: Path,
    receipt_path: Path,
    download_path: Path,
    staged_input_validation_path: Path,
    expected_kms_key_arn: str,
    run_id: str,
) -> dict[str, Any]:
    capture_checks = (
        capture.get("checks") if isinstance(capture.get("checks"), dict) else {}
    )
    cloudwatch = (
        capture.get("cloudwatch")
        if isinstance(capture.get("cloudwatch"), dict)
        else {}
    )
    receipt_summary = (
        capture.get("receipt") if isinstance(capture.get("receipt"), dict) else {}
    )
    local_anchor = (
        capture.get("local_anchor")
        if isinstance(capture.get("local_anchor"), dict)
        else {}
    )
    receipt_upload = (
        cloudwatch.get("receipt_upload")
        if isinstance(cloudwatch.get("receipt_upload"), dict)
        else {}
    )
    batch = capture.get("batch") if isinstance(capture.get("batch"), dict) else {}
    batch_checks = (
        batch.get("checks") if isinstance(batch.get("checks"), dict) else {}
    )
    anchor_checks = (
        anchor.get("checks") if isinstance(anchor.get("checks"), dict) else {}
    )
    receipt_checks = (
        receipt_summary.get("checks")
        if isinstance(receipt_summary.get("checks"), dict)
        else {}
    )
    download_checks = (
        download.get("checks") if isinstance(download.get("checks"), dict) else {}
    )
    download_object = (
        download.get("object") if isinstance(download.get("object"), dict) else {}
    )
    crosscheck_outputs = (
        receipt.get("outputs") if isinstance(receipt.get("outputs"), dict) else {}
    )
    staged_output = (
        crosscheck_outputs.get("staged_input_validation.json")
        if isinstance(crosscheck_outputs.get("staged_input_validation.json"), dict)
        else {}
    )
    receipt_sha = sha256(receipt_path)
    anchor_sha = sha256(anchor_path)
    staged_sha = sha256(staged_input_validation_path)
    expected_receipt_uri = (
        "s3://diana-omics-private-results-"
        + f"[^/]+/runs/subject01/{re.escape(run_id)}/deterministic/"
        + f"provenance/crosscheck-materialization-receipts/{receipt_sha}\\.json"
    )
    history = (
        receipt_summary.get("history")
        if isinstance(receipt_summary.get("history"), list)
        else []
    )
    single_receipt_version = (
        len(history) == 1
        and isinstance(history[0], dict)
        and history[0].get("history_kind") == "version"
        and history[0].get("IsLatest") is True
        and history[0].get("VersionId") == anchor.get("receipt_version_id")
    )
    checks = {
        "capture_schema_status": (
            exact_schema_status(capture)
            and capture.get("scope")
            == "private read-only terminal materializer custody capture"
        ),
        "capture_checks_passed": bool(capture_checks)
        and capture_checks == EXPECTED_CROSSCHECK_CAPTURE_CHECKS,
        "batch_terminal_identity": (
            batch.get("status") == "SUCCEEDED"
            and batch.get("log_group") == "/aws/batch/job"
            and batch.get("attempt_count") == 1
            and batch.get("exit_code") == 0
            and batch_checks == EXPECTED_CROSSCHECK_BATCH_CHECKS
        ),
        "cloudwatch_anchor_matches_local_anchor": (
            cloudwatch.get("receipt_anchor") == anchor
            and valid_sha256(cloudwatch.get("terminal_payload_sha256"))
            and valid_sha256(cloudwatch.get("terminal_json_sha256"))
            and valid_sha256(cloudwatch.get("messages_sha256"))
            and positive_int(cloudwatch.get("event_count"))
            and receipt_upload.get("uri") == anchor.get("receipt_uri")
            and receipt_upload.get("version_id") == anchor.get("receipt_version_id")
            and receipt_upload.get("sha256") == receipt_sha
            and integer_equals(receipt_upload.get("bytes"), receipt_path.stat().st_size)
            and receipt_upload.get("kms_key_arn") == expected_kms_key_arn
        ),
        "anchor_schema_checks": (
            exact_schema_status(anchor)
            and anchor_checks == EXPECTED_CROSSCHECK_ANCHOR_CHECKS
        ),
        "anchor_binds_receipt": (
            anchor.get("receipt_sha256") == receipt_sha
            and integer_equals(anchor.get("receipt_bytes"), receipt_path.stat().st_size)
            and re.fullmatch(expected_receipt_uri, str(anchor.get("receipt_uri", "")))
            is not None
            and valid_version_id(anchor.get("receipt_version_id"))
        ),
        "capture_binds_local_anchor": (
            local_anchor.get("sha256") == anchor_sha
            and integer_equals(local_anchor.get("bytes"), anchor_path.stat().st_size)
        ),
        "capture_binds_local_receipt": (
            receipt_summary.get("uri") == anchor.get("receipt_uri")
            and receipt_summary.get("version_id") == anchor.get("receipt_version_id")
            and receipt_summary.get("sha256") == receipt_sha
            and integer_equals(receipt_summary.get("bytes"), receipt_path.stat().st_size)
            and receipt_summary.get("local_sha256") == receipt_sha
            and integer_equals(
                receipt_summary.get("local_bytes"), receipt_path.stat().st_size
            )
            and receipt_checks == EXPECTED_CROSSCHECK_RECEIPT_DOWNLOAD_CHECKS
            and receipt_summary.get("kms_key_arn") == expected_kms_key_arn
            and single_receipt_version
        ),
        "download_schema_checks": (
            exact_schema_status(download)
            and download.get("expected_kms_key_arn") == expected_kms_key_arn
            and download.get("materializer_receipt_sha256") == receipt_sha
            and download_checks == EXPECTED_STAGED_VALIDATION_DOWNLOAD_CHECKS
        ),
        "download_binds_staged_validation": (
            download_object.get("uri") == staged_output.get("uri")
            and download_object.get("version_id") == staged_output.get("version_id")
            and download_object.get("expected_sha256") == staged_output.get("sha256")
            and integer_equals(download_object.get("expected_bytes"), staged_output.get("bytes"))
            and download_object.get("sha256") == staged_sha
            and integer_equals(
                download_object.get("bytes"),
                staged_input_validation_path.stat().st_size,
            )
            and staged_output.get("sha256") == staged_sha
            and s3_full_object_sha256_matches(
                staged_output.get("checksums"),
                staged_sha,
            )
        ),
        "boundary_preserved": (
            capture.get("classification_authorization") == "none"
            and capture.get("authorized_hrd_state") == "no_call"
            and receipt.get("classification_authorization") == "none"
            and receipt.get("authorized_hrd_state") == "no_call"
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "capture_sha256": sha256(capture_path),
        "anchor_sha256": anchor_sha,
        "receipt_sha256": receipt_sha,
        "download_sha256": sha256(download_path),
        "checks": checks,
    }


def validate_final_freeze_provenance(
    receipt: dict[str, Any],
    anchor: dict[str, Any],
    *,
    receipt_path: Path,
    execution_path: Path,
    run_id: str,
    batch_job_id: str,
    expected_kms_key_arn: str,
) -> dict[str, Any]:
    rows = receipt.get("objects") if isinstance(receipt.get("objects"), list) else []
    destination_inventory = (
        receipt.get("destination_inventory")
        if isinstance(receipt.get("destination_inventory"), list)
        else []
    )
    initial_identity = (
        receipt.get("initial_inventory_identity")
        if isinstance(receipt.get("initial_inventory_identity"), list)
        else []
    )
    final_identity = (
        receipt.get("final_inventory_identity")
        if isinstance(receipt.get("final_inventory_identity"), list)
        else []
    )
    receipt_checks = (
        receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    )
    source_prefix = str(receipt.get("source_prefix", ""))
    destination_prefix = str(receipt.get("destination_prefix", ""))
    source_match = re.fullmatch(
        rf"s3://(diana-omics-work-([^/]+))/"
        rf"(runs/diana-hrd/{re.escape(run_id)}/private-results/final/artifacts/)",
        source_prefix,
    )
    destination_match = re.fullmatch(
        rf"s3://(diana-omics-private-results-([^/]+))/"
        rf"(runs/subject01/{re.escape(run_id)}/deterministic/final/)",
        destination_prefix,
    )
    source_bucket = source_match.group(1) if source_match else ""
    source_suffix = source_match.group(2) if source_match else ""
    source_key_prefix = source_match.group(3) if source_match else ""
    destination_bucket = destination_match.group(1) if destination_match else ""
    destination_suffix = destination_match.group(2) if destination_match else ""
    destination_key_prefix = destination_match.group(3) if destination_match else ""

    by_relative: dict[str, dict[str, Any]] = {}
    inventory_by_relative: dict[str, dict[str, Any]] = {}
    malformed = False
    for raw in rows:
        if not isinstance(raw, dict):
            malformed = True
            continue
        try:
            relative = safe_artifact_relative(raw.get("relative_key", ""))
        except ValueError:
            malformed = True
            continue
        if relative in by_relative:
            malformed = True
        by_relative[relative] = raw
    for raw in destination_inventory:
        if not isinstance(raw, dict):
            malformed = True
            continue
        try:
            relative = safe_artifact_relative(raw.get("relative_key", ""))
        except ValueError:
            malformed = True
            continue
        if relative in inventory_by_relative:
            malformed = True
        inventory_by_relative[relative] = raw

    object_custody = not malformed and bool(by_relative)
    for relative, row in by_relative.items():
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        destination = (
            row.get("destination")
            if isinstance(row.get("destination"), dict)
            else {}
        )
        row_checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
        inventory = inventory_by_relative.get(relative, {})
        if not (
            row.get("status") == "passed"
            and row_checks == EXPECTED_FINAL_FREEZE_ROW_CHECKS
            and source.get("bucket") == source_bucket
            and source.get("key") == source_key_prefix + relative
            and valid_version_id(source.get("version_id"))
            and positive_int(source.get("bytes"))
            and source.get("checksum_type") == "FULL_OBJECT"
            and bool(s3_checksums(source.get("checksums")))
            and destination.get("bucket") == destination_bucket
            and destination.get("key") == destination_key_prefix + relative
            and valid_version_id(destination.get("version_id"))
            and positive_int(destination.get("bytes"))
            and destination.get("checksum_type") == "FULL_OBJECT"
            and bool(s3_checksums(destination.get("checksums")))
            and destination.get("server_side_encryption") == "aws:kms"
            and destination.get("kms_key_id") == expected_kms_key_arn
            and inventory.get("key") == destination.get("key")
            and inventory.get("version_id") == destination.get("version_id")
            and integer_equals(inventory.get("bytes"), destination.get("bytes"))
            and s3_checksums(inventory.get("checksums"))
            == s3_checksums(destination.get("checksums"))
            and inventory.get("checksum_type") == "FULL_OBJECT"
            and inventory.get("kms_key_id") == expected_kms_key_arn
        ):
            object_custody = False

    receipt_sha = sha256(receipt_path)
    anchor_checks = anchor.get("checks") if isinstance(anchor.get("checks"), dict) else {}
    expected_anchor_uri = (
        f"s3://{destination_bucket}/runs/subject01/{run_id}/deterministic/"
        f"provenance/final-artifact-freeze-receipts/{receipt_sha}.json"
        if destination_match
        else ""
    )
    checks = {
        "receipt_schema_status": exact_schema_status(receipt),
        "receipt_run_execution": receipt.get("run_id") == run_id
        and receipt.get("batch_job_id") == batch_job_id
        and receipt.get("batch_status") == "SUCCEEDED"
        and isinstance(receipt.get("execution_receipt"), dict)
        and receipt["execution_receipt"].get("sha256") == sha256(execution_path),
        "canonical_source_destination": bool(source_match)
        and bool(destination_match)
        and source_suffix == destination_suffix,
        "receipt_kms": receipt.get("kms_key_arn") == expected_kms_key_arn,
        "receipt_versioning_history": receipt.get("destination_bucket_versioning")
        == "Enabled"
        and integer_equals(receipt.get("destination_initial_version_history_count"), 0)
        and receipt.get("receipt_anchor_strategy")
        == "sha256_content_addressed_create_only",
        "receipt_script": valid_sha256(receipt.get("script_sha256")),
        "receipt_inventory_counts": len(rows)
        == len(destination_inventory)
        == len(initial_identity)
        == len(final_identity)
        and integer_equals(receipt.get("object_count"), len(rows))
        and integer_equals(receipt.get("passed_count"), len(rows))
        and set(by_relative) == set(inventory_by_relative),
        "source_inventory_unchanged": initial_identity == final_identity,
        "receipt_checks": receipt_checks == EXPECTED_FINAL_FREEZE_CHECKS,
        "object_custody": object_custody,
        "anchor_schema_status": exact_schema_status(anchor)
        and anchor.get("run_id") == run_id
        and anchor.get("batch_job_id") == batch_job_id,
        "anchor_content_address": anchor.get("receipt_sha256") == receipt_sha
        and integer_equals(anchor.get("receipt_bytes"), receipt_path.stat().st_size)
        and anchor.get("receipt_uri") == expected_anchor_uri
        and valid_version_id(anchor.get("receipt_version_id")),
        "anchor_checks": anchor_checks == EXPECTED_FINAL_FREEZE_ANCHOR_CHECKS,
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "receipt_sha256": receipt_sha,
        "receipt_version_id": str(anchor.get("receipt_version_id", "")),
        "object_count": len(rows),
        "checks": checks,
    }


def normalized_reference(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def forbidden_tokens(
    summary: dict[str, Any],
    contamination_rows: list[dict[str, str]],
    sbs_rows: list[dict[str, str]],
    audit: dict[str, Any],
    explicit: list[str],
    forbidden_token_files: Iterable[Path] = (),
) -> list[str]:
    values: set[str] = {token.strip() for token in explicit if token.strip()}
    generic_words = {
        "analysis",
        "data",
        "diana",
        "dna",
        "east",
        "inputs",
        "intake",
        "matched",
        "normal",
        "omics",
        "results",
        "rna",
        "runs",
        "sample",
        "sha256",
        "source",
        "tumor",
        "wgs",
    }

    def add_value(value: Any, *, split_words: bool = False) -> None:
        text = str(value).strip()
        if not text:
            return
        values.add(text)
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{4,}", text):
            if any(character.isdigit() for character in token):
                values.add(token)
        if split_words:
            for word in re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", text):
                if word.lower() not in generic_words:
                    values.add(word)

    input_payload = summary.get("input", {}) if isinstance(summary.get("input"), dict) else {}
    for key in ("dataset", "pair"):
        add_value(input_payload.get(key, ""), split_words=True)
    for row in contamination_rows:
        add_value(row.get("sample", ""))
    for row in sbs_rows:
        add_value(row.get("sample", ""))
    objects = audit.get("objects", []) if isinstance(audit.get("objects"), list) else []
    for row in objects:
        if not isinstance(row, dict):
            continue
        add_value(row.get("sample_id", ""))
        add_value(row.get("assay", ""), split_words=True)
    for key in ("source_uri", "result_uri"):
        add_value(audit.get(key, ""), split_words=True)
    return rank_forbidden_tokens(
        merge_forbidden_tokens(values, files=forbidden_token_files)
    )


def rank_forbidden_tokens(tokens: Iterable[str]) -> list[str]:
    return sorted(tokens, key=lambda value: (-len(value), value.lower()))


def scan_outputs(paths: list[Path], tokens: list[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for token in tokens:
            if token.lower() in lowered:
                findings.append({"path": path.name, "token": token})
    return findings


def write_outputs(
    staging: Path,
    report: str,
    readiness_rows: list[dict[str, str]],
    checks_payload: dict[str, Any],
    crosscheck_input_plans: dict[str, Any],
    input_rows: list[dict[str, Any]],
) -> list[Path]:
    report_path = staging / "report.md"
    write_staged_text(report_path, report)
    readiness_path = staging / "readiness.csv"
    write_staged_csv(
        readiness_path,
        readiness_rows,
        ["evidence_surface", "state", "reason"],
    )
    checks_path = staging / "evidence_checks.json"
    write_staged_json(checks_path, checks_payload)
    crosscheck_input_plans_path = staging / "crosscheck_input_plans.json"
    write_staged_json(crosscheck_input_plans_path, crosscheck_input_plans)
    hashes_path = staging / "input_sha256.csv"
    write_staged_csv(
        hashes_path,
        input_rows,
        ["input_id", "path", "bytes", "sha256"],
    )
    return [
        report_path,
        readiness_path,
        checks_path,
        crosscheck_input_plans_path,
        hashes_path,
    ]


def crosscheck_output_plan(
    outputs: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    row = outputs[name] if isinstance(outputs.get(name), dict) else {}
    return {
        "path": name,
        "bytes": int(row["bytes"]),
        "sha256": str(row["sha256"]).lower(),
    }


def build_crosscheck_input_plans(
    crosscheck_materialization: dict[str, Any],
    input_contract: dict[str, Any],
) -> dict[str, Any]:
    outputs = (
        crosscheck_materialization.get("outputs", {})
        if isinstance(crosscheck_materialization.get("outputs"), dict)
        else {}
    )
    inputs = (
        crosscheck_materialization.get("input_sha256", {})
        if isinstance(crosscheck_materialization.get("input_sha256"), dict)
        else {}
    )
    validation = (
        crosscheck_materialization.get("validation", {})
        if isinstance(crosscheck_materialization.get("validation"), dict)
        else {}
    )
    validation_counts = {
        name: require_nonnegative_exact_int(
            validation.get(name),
            f"{name} materialized cross-check validation count",
        )
        for name in (
            "pass_snv_records",
            "pass_snv_alleles",
            "sbs96_contexts",
            "sbs96_burden",
        )
    }
    matrix_matches = require_exact_bool(
        validation.get("matrix_matches_independent_pass_vcf_derivation"),
        True,
        "matrix equivalence validation flag",
    )
    source_sample_names_retained = require_exact_bool(
        validation.get("source_sample_names_retained"),
        False,
        "source sample retention validation flag",
    )
    routes = input_contract.get("routes")
    if not isinstance(routes, list):
        raise ValueError("input contract lacks executable cross-check routes")
    missing_routes = sorted(
        set(("sequenza_scarhrd", "sigprofiler_sbs3")) - set(routes)
    )
    if missing_routes:
        raise ValueError(
            "input contract is missing executable cross-check routes: "
            + ", ".join(missing_routes)
        )
    input_artifacts = (
        input_contract.get("artifacts", {})
        if isinstance(input_contract.get("artifacts"), dict)
        else {}
    )
    sequenza_parameters = (
        input_contract.get("method_parameters", {}).get("sequenza", {})
        if isinstance(input_contract.get("method_parameters"), dict)
        and isinstance(input_contract.get("method_parameters", {}).get("sequenza"), dict)
        else {}
    )
    sequenza_inputs = {
        name: str(
            (input_artifacts.get(name, {}) if isinstance(input_artifacts.get(name), dict) else {}).get(
                "sha256", ""
            )
        ).lower()
        for name in ("tumor_bam", "tumor_bai", "normal_bam", "normal_bai")
    }
    return {
        "schema_version": 1,
        "plan_type": "terminal_crosscheck_input_materialization_plan",
        "status": "contract_ready",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "routes": {
            "sigprofiler_sbs3": {
                "status": "inputs_materialized",
                "execution_status": "not_run",
                "interpretation_status": "no_call",
                "materializer": "scripts/materialize_crosscheck_inputs.py",
                "source_artifacts": {
                    "somatic_vcf": crosscheck_output_plan(
                        outputs, "somatic.pass.vcf.gz"
                    ),
                    "somatic_vcf_index": crosscheck_output_plan(
                        outputs, "somatic.pass.vcf.gz.tbi"
                    ),
                    "sbs96_matrix": crosscheck_output_plan(outputs, "sbs96.csv"),
                    "staged_validation": crosscheck_output_plan(
                        outputs, "staged_input_validation.json"
                    ),
                },
                "source_sha256": {
                    "filtered_vcf": str(inputs.get("filtered_vcf", "")).lower(),
                    "filtered_vcf_index": str(
                        inputs.get("filtered_vcf_index", "")
                    ).lower(),
                    "reference_fai": str(inputs.get("reference_fai", "")).lower(),
                    "reference_fasta": str(
                        inputs.get("reference_fasta", "")
                    ).lower(),
                    "source_sbs96_matrix": str(
                        inputs.get("source_sbs96_matrix", "")
                    ).lower(),
                },
                "validation": {
                    "pass_snv_records": validation_counts["pass_snv_records"],
                    "pass_snv_alleles": validation_counts["pass_snv_alleles"],
                    "sbs96_contexts": validation_counts["sbs96_contexts"],
                    "sbs96_burden": validation_counts["sbs96_burden"],
                    "matrix_matches_independent_pass_vcf_derivation": matrix_matches,
                    "source_sample_names_retained": source_sample_names_retained,
                },
                "blockers": [
                    "SigProfilerAssignment execution and SBS3 thresholds are not validated.",
                    "The executable cross-check route has not run on the materialized inputs.",
                ],
            },
            "sequenza_scarhrd": {
                "status": "contract_ready",
                "execution_status": "not_run",
                "interpretation_status": "no_call",
                "source_sha256": sequenza_inputs,
                "method_parameters": {
                    "female": sequenza_parameters.get("female"),
                },
                "blockers": [
                    "Sequenza and scarHRD have not run on the finalized contract.",
                    "Purity/ploidy and scarHRD interpretation thresholds are not validated.",
                ],
            },
        },
    }


def build_input_rows(
    paths: dict[str, Path], artifact_root: Path, early_root: Path
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for input_id, path in sorted(paths.items()):
        if path.is_relative_to(artifact_root):
            logical_path = (
                "artifact-root/" + path.relative_to(artifact_root).as_posix()
            )
        elif path.is_relative_to(early_root):
            logical_path = (
                "early-look-root/" + path.relative_to(early_root).as_posix()
            )
        elif input_id == "input_snapshot":
            logical_path = "snapshot/input-snapshot-receipt.json"
        else:
            logical_path = f"external/{input_id}"
        rows.append(
            {
                "input_id": input_id,
                "path": logical_path,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return rows


def prepare_output_dir(output: Path, expected_names: Iterable[str]) -> None:
    output = resolve_report_output_dir(output)
    expected = set(expected_names)
    if output.exists() and not output.is_dir():
        raise ValueError(f"report output is not a directory: {output}")

    output.mkdir(parents=True, exist_ok=True)

    unexpected: list[str] = []
    invalid: list[str] = []
    for path in output.iterdir():
        if path.name not in expected:
            unexpected.append(path.name)
        elif path.is_symlink() or not path.is_file():
            invalid.append(path.name)
    if unexpected:
        raise ValueError(
            "report output contains unexpected existing files: "
            + ", ".join(sorted(unexpected))
        )
    if invalid:
        raise ValueError(
            "report output contains invalid existing packet paths: "
            + ", ".join(sorted(invalid))
        )

    existing = sorted(path.name for path in output.iterdir() if path.name in expected)
    if existing:
        raise ValueError(
            "report output already contains packet files: " + ", ".join(existing)
        )


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_input_path(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a non-empty real file: {path}")
    return path.resolve()


def resolve_report_output_dir(output: Path) -> Path:
    if output.is_symlink():
        raise ValueError("report output may not be a symlink")
    for parent in output.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"report output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"report output parent is not a directory: {parent}")
    return output.resolve()


def require_safe_new_packet(path: Path) -> Path:
    require_no_symlinked_ancestors(path, "report output packet")
    if path.is_symlink():
        raise ValueError("report output packet may not be a symlink: " + path.name)
    if path.exists():
        raise ValueError("report output packet already exists: " + path.name)
    return path.resolve()


def require_safe_new_staged_file(path: Path) -> Path:
    require_no_symlinked_ancestors(path, "staged report packet")
    if path.is_symlink():
        raise ValueError("staged report packet may not be a symlink: " + path.name)
    if path.exists():
        raise ValueError("staged report packet already exists: " + path.name)
    return path.resolve()


def require_staged_file(path: Path, expected_sha256: str | None = None) -> None:
    require_real_input_path(path, "staged report packet")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"staged report packet mode is not 0600: {path}")
    if expected_sha256 is not None and sha256(path) != expected_sha256:
        raise ValueError("staged report packet changed during write: " + path.name)


def write_staged_bytes(path: Path, data: bytes) -> None:
    expected_sha256 = sha256_bytes(data)
    path = require_safe_new_staged_file(path)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        require_staged_file(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_staged_text(path: Path, text: str) -> None:
    write_staged_bytes(path, text.encode("utf-8"))


def write_staged_json(path: Path, value: dict[str, Any]) -> None:
    write_staged_bytes(path, json_bytes(value))


def write_staged_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    write_staged_text(path, buffer.getvalue())


def require_report_manifest(packet_dir: Path) -> None:
    manifest_path = packet_dir / "report_manifest.json"
    require_real_input_path(manifest_path, "report packet")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report manifest must be a JSON object")
    if set(payload) != REPORT_MANIFEST_KEYS:
        raise ValueError("report manifest envelope is not exact")
    if (
        not exact_schema_version(payload, 1)
        or payload.get("method_id") != "deterministic_full_wgs"
        or payload.get("report_kind") != "deterministic_baseline"
        or payload.get("evidence_status") != "partial_evidence"
        or payload.get("authorized_hrd_state") != "no_call"
        or payload.get("classification_authorized") is not False
        or payload.get("classification_qc_status") != "not_applicable"
        or not isinstance(payload.get("review_summary"), dict)
    ):
        raise ValueError("report manifest identity is not exact")

    support_hashes = payload.get("support_sha256")
    support_names = {
        "crosscheck_input_plans.json",
        "evidence_checks.json",
        "input_sha256.csv",
        "readiness.csv",
    }
    if not isinstance(support_hashes, dict) or set(support_hashes) != support_names:
        raise ValueError("report manifest support SHA-256 inventory is not exact")

    source_hashes = payload.get("source_sha256")
    if (
        not isinstance(source_hashes, dict)
        or not source_hashes
        or any(
            not isinstance(key, str) or not HEX64.fullmatch(str(value))
            for key, value in source_hashes.items()
        )
    ):
        raise ValueError("report manifest source SHA-256 inventory is not exact")

    expected = [("report.md", str(payload.get("report_sha256", "")))]
    expected.extend(
        (name, str(support_hashes.get(name, "")))
        for name in sorted(support_names)
    )
    for name, expected_sha256 in expected:
        if not HEX64.fullmatch(expected_sha256):
            raise ValueError("report manifest has malformed SHA-256 for " + name)
        path = require_real_input_path(packet_dir / name, "report packet")
        if sha256(path) != expected_sha256:
            raise ValueError("report manifest is stale for " + name)


def copy_create_only(source: Path, destination: Path) -> None:
    source = require_real_input_path(source, "staged report packet")
    expected_sha256 = sha256(source)
    destination = require_safe_new_packet(destination)
    with source.open("rb") as source_handle:
        try:
            file_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644,
            )
        except FileExistsError as error:
            raise ValueError(
                "report output packet already exists: " + destination.name
            ) from error

        try:
            destination_handle = os.fdopen(file_descriptor, "wb")
        except Exception:
            os.close(file_descriptor)
            destination.unlink(missing_ok=True)
            raise

        try:
            with destination_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            fsync_directory(destination.parent)
            if (
                sha256(source) != expected_sha256
                or sha256(destination) != expected_sha256
            ):
                raise ValueError(
                    "staged report packet changed during copy: " + source.name
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_packet_create_only(staged_paths: Iterable[Path], output: Path) -> None:
    installed: list[Path] = []
    expected_hashes: dict[Path, str] = {}
    try:
        for path in staged_paths:
            destination = output / path.name
            expected_hashes[destination] = sha256(
                require_real_input_path(path, "staged report packet")
            )
            destination_preexisted = destination.exists() or destination.is_symlink()
            try:
                copy_create_only(path, destination)
            except Exception:
                if not destination_preexisted:
                    installed.append(destination)
                raise
            installed.append(destination)
        fsync_directory(output)
        for destination, expected_sha256 in expected_hashes.items():
            path = require_real_input_path(destination, "report output packet")
            if sha256(path) != expected_sha256:
                raise ValueError(
                    "report output packet changed during install: "
                    + destination.name
                )
        require_report_manifest(output)
    except Exception:
        for path in reversed(installed):
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a private deterministic full-WGS evidence report after strict validation.")
    parser.add_argument("--artifact-root", required=True, type=Path, help="Materialized final worker artifacts directory.")
    parser.add_argument("--preflight-json", required=True, type=Path)
    parser.add_argument("--gather-json", required=True, type=Path)
    parser.add_argument("--sha-audit", required=True, type=Path)
    parser.add_argument("--execution-json", required=True, type=Path)
    parser.add_argument("--executed-worker-freeze-receipt", required=True, type=Path)
    parser.add_argument(
        "--executed-worker-freeze-receipt-upload", required=True, type=Path
    )
    parser.add_argument("--final-freeze-receipt", required=True, type=Path)
    parser.add_argument("--final-freeze-anchor", required=True, type=Path)
    parser.add_argument("--exact-materialization-receipt", required=True, type=Path)
    parser.add_argument(
        "--crosscheck-materialization-receipt", required=True, type=Path
    )
    parser.add_argument("--input-contract", required=True, type=Path)
    parser.add_argument(
        "--crosscheck-materialization-capture", required=True, type=Path
    )
    parser.add_argument(
        "--crosscheck-materialization-anchor", required=True, type=Path
    )
    parser.add_argument("--stage-provenance-receipt", required=True, type=Path)
    parser.add_argument("--stage-provenance-anchor", required=True, type=Path)
    parser.add_argument("--staged-input-validation-json", required=True, type=Path)
    parser.add_argument(
        "--staged-input-validation-download-receipt", required=True, type=Path
    )
    parser.add_argument("--expected-kms-key-arn", required=True)
    parser.add_argument("--early-look-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument("--forbidden-tokens-file", action="append", default=[], type=Path)
    args = parser.parse_args()

    if args.artifact_root.is_symlink() or args.early_look_root.is_symlink():
        raise SystemExit("Fail-closed: input roots may not be symlinks")
    source_artifact_root = args.artifact_root.resolve()
    source_early_root = args.early_look_root.resolve()
    try:
        output = resolve_report_output_dir(args.output_dir)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    if (
        output in (source_artifact_root, source_early_root)
        or output.is_relative_to(source_artifact_root)
        or output.is_relative_to(source_early_root)
    ):
        raise SystemExit("Fail-closed: report output must be outside input trees")
    try:
        prepare_output_dir(output, OUTPUT_NAMES)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    external_sources = {
        "preflight": args.preflight_json,
        "gather": args.gather_json,
        "sha_audit": args.sha_audit,
        "execution": args.execution_json,
        "executed_worker_freeze": args.executed_worker_freeze_receipt,
        "executed_worker_freeze_upload": args.executed_worker_freeze_receipt_upload,
        "final_freeze": args.final_freeze_receipt,
        "final_freeze_anchor": args.final_freeze_anchor,
        "exact_materialization": args.exact_materialization_receipt,
        "crosscheck_materialization": args.crosscheck_materialization_receipt,
        "input_contract": args.input_contract,
        "crosscheck_materialization_capture": (
            args.crosscheck_materialization_capture
        ),
        "crosscheck_materialization_anchor": args.crosscheck_materialization_anchor,
        "stage_provenance": args.stage_provenance_receipt,
        "stage_provenance_anchor": args.stage_provenance_anchor,
        "staged_input_validation": args.staged_input_validation_json,
        "staged_input_validation_download": (
            args.staged_input_validation_download_receipt
        ),
    }
    snapshot_guard = tempfile.TemporaryDirectory(
        prefix="deterministic-full-input-snapshot-", dir=str(output.parent)
    )
    try:
        snapshot = create_stable_input_snapshot(
            source_artifact_root,
            source_early_root,
            external_sources,
            Path(snapshot_guard.name) / "inputs",
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: stable input snapshot failed: {error}") from error
    artifact_root = snapshot["artifact_root"]
    early_root = snapshot["early_root"]
    external_paths = snapshot["external_paths"]
    paths = {
        "summary": artifact_root / "diana_hrd_summary.json",
        "readiness": artifact_root / "hrd_readiness.csv",
        "alignment_json": artifact_root / "alignment/bam_validation_summary.json",
        "alignment_csv": artifact_root / "alignment/bam_validation_summary.csv",
        "tumor_flagstat": artifact_root / "alignment/tumor.flagstat.txt",
        "normal_flagstat": artifact_root / "alignment/normal.flagstat.txt",
        "variant_summary": artifact_root / "variants/mutect2_summary.json",
        "filtered_vcf": artifact_root / "variants/diana.wgs.mutect2.filtered.vcf.gz",
        "filtered_vcf_index": artifact_root / "variants/diana.wgs.mutect2.filtered.vcf.gz.tbi",
        "contamination": artifact_root / "variants/contamination.table",
        "tumor_segmentation": artifact_root / "variants/tumor-segmentation.table",
        "tumor_pileups": artifact_root / "variants/tumor.pileups.table",
        "normal_pileups": artifact_root / "variants/normal.pileups.table",
        "orientation_model": artifact_root / "variants/read-orientation-model.tar.gz",
        "brca_rows": artifact_root / "variants/brca1_brca2_pass_variants.csv",
        "brca_vcf": artifact_root / "variants/brca1_brca2.pass.vcf.gz",
        "brca_vcf_index": artifact_root / "variants/brca1_brca2.pass.vcf.gz.tbi",
        "cnv_summary": artifact_root / "cnv/coverage_cnv_summary.json",
        "cnv_bins": artifact_root / "cnv/coverage_cnv_bins.csv",
        "signature_summary": artifact_root / "signatures/signature_assignment_summary.json",
        "sbs96": artifact_root / "signatures/wgs_sbs96_matrix.csv",
        "sv_summary": artifact_root / "sv/sv_evidence_summary.json",
        "sv_csv": artifact_root / "sv/sv_evidence_summary.csv",
        "tool_versions": artifact_root / "tool_versions.json",
        "preflight": external_paths["preflight"],
        "gather": external_paths["gather"],
        "sha_audit": external_paths["sha_audit"],
        "execution": external_paths["execution"],
        "executed_worker_freeze": external_paths["executed_worker_freeze"],
        "executed_worker_freeze_upload": external_paths[
            "executed_worker_freeze_upload"
        ],
        "final_freeze": external_paths["final_freeze"],
        "final_freeze_anchor": external_paths["final_freeze_anchor"],
        "exact_materialization": external_paths["exact_materialization"],
        "crosscheck_materialization": external_paths[
            "crosscheck_materialization"
        ],
        "input_contract": external_paths["input_contract"],
        "crosscheck_materialization_capture": external_paths[
            "crosscheck_materialization_capture"
        ],
        "crosscheck_materialization_anchor": external_paths[
            "crosscheck_materialization_anchor"
        ],
        "stage_provenance": external_paths["stage_provenance"],
        "stage_provenance_anchor": external_paths["stage_provenance_anchor"],
        "staged_input_validation": external_paths["staged_input_validation"],
        "staged_input_validation_download": external_paths[
            "staged_input_validation_download"
        ],
        "early_summary": early_root / "early_look_summary.json",
        "early_pass_variants": early_root / "variants/core_hrr_pass_variants.csv",
        "early_cnv_bins": early_root / "coverage_cnv/coverage_cnv_bins.csv",
        "input_snapshot": snapshot["manifest_path"],
    }
    missing = [str(path) for path in paths.values() if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise SystemExit("Fail-closed: required full-WGS evidence is missing or empty:\n" + "\n".join(missing))

    bcftools = shutil.which("bcftools")
    if not bcftools:
        raise SystemExit("Fail-closed: bcftools is required to validate the final VCF and indexes.")

    summary = load_json(paths["summary"])
    readiness_rows = load_csv(paths["readiness"])
    alignment = load_json(paths["alignment_json"])
    alignment_rows = load_csv(paths["alignment_csv"])
    variants = load_json(paths["variant_summary"])
    contamination_rows = load_csv(paths["contamination"], delimiter="\t")
    brca_rows = load_csv(paths["brca_rows"])
    cnv = load_json(paths["cnv_summary"])
    cnv_rows = load_csv(paths["cnv_bins"])
    signatures = load_json(paths["signature_summary"])
    sbs_rows = load_csv(paths["sbs96"])
    sv = load_json(paths["sv_summary"])
    sv_rows = load_csv(paths["sv_csv"])
    tools = load_json(paths["tool_versions"])
    preflight = load_json(paths["preflight"])
    gather = load_json(paths["gather"])
    audit = load_json(paths["sha_audit"])
    execution = load_json(paths["execution"])
    executed_worker_freeze = load_json(paths["executed_worker_freeze"])
    executed_worker_freeze_upload = load_json(paths["executed_worker_freeze_upload"])
    final_freeze = load_json(paths["final_freeze"])
    final_freeze_anchor = load_json(paths["final_freeze_anchor"])
    exact_materialization = load_json(paths["exact_materialization"])
    crosscheck_materialization = load_json(paths["crosscheck_materialization"])
    input_contract = load_json(paths["input_contract"])
    crosscheck_materialization_capture = load_json(
        paths["crosscheck_materialization_capture"]
    )
    crosscheck_materialization_anchor = load_json(
        paths["crosscheck_materialization_anchor"]
    )
    stage_provenance = load_json(paths["stage_provenance"])
    stage_provenance_anchor = load_json(paths["stage_provenance_anchor"])
    staged_input_validation = load_json(paths["staged_input_validation"])
    staged_input_validation_download = load_json(
        paths["staged_input_validation_download"]
    )
    input_snapshot = load_json(paths["input_snapshot"])
    early = load_json(paths["early_summary"])
    early_pass_rows = load_csv(paths["early_pass_variants"])
    early_cnv_rows = load_csv(paths["early_cnv_bins"])
    checks: list[dict[str, str]] = []

    snapshot_rows = (
        input_snapshot.get("files")
        if isinstance(input_snapshot.get("files"), list)
        else []
    )
    snapshot_ids = [
        str(row.get("input_id", ""))
        for row in snapshot_rows
        if isinstance(row, dict)
    ]
    add_check(
        checks,
        "stable_input_snapshot",
        exact_schema_status(input_snapshot)
        and input_snapshot.get("snapshot_strategy")
        == "open_no_follow_fstat_copy_global_restat"
        and integer_equals(input_snapshot.get("file_count"), len(snapshot_rows))
        and len(snapshot_ids) == len(set(snapshot_ids))
        and all(
            isinstance(row, dict)
            and bool(row.get("input_id"))
            and nonnegative_int(row.get("bytes"))
            and valid_sha256(row.get("sha256"))
            for row in snapshot_rows
        ),
        "Every artifact-tree, early-look-tree, and external evidence input was copied through O_NOFOLLOW/fstat checks into a private snapshot and globally re-statted before validation.",
    )

    add_check(checks, "summary_boundary", summary.get("status") == "no_call" and summary.get("evidence_status") == "partial_evidence" and bool(summary.get("boundary")), "Summary is partial_evidence with an explicit overall no_call boundary.")
    embedded_readiness = summary.get("hrd_readiness", []) if isinstance(summary.get("hrd_readiness"), list) else []
    normalized_embedded = [{key: str(row.get(key, "")) for key in ("evidence_surface", "status", "detail")} for row in embedded_readiness if isinstance(row, dict)]
    normalized_csv = [{key: str(row.get(key, "")) for key in ("evidence_surface", "status", "detail")} for row in readiness_rows]
    observed_readiness = {row.get("evidence_surface", ""): row.get("status", "") for row in readiness_rows}
    add_check(checks, "readiness_contract", normalized_embedded == normalized_csv and len(readiness_rows) == len(EXPECTED_READINESS) and observed_readiness == EXPECTED_READINESS, "Readiness CSV matches the embedded summary and preserves exact ready/partial_evidence/no_call states.")
    add_check(checks, "embedded_component_summaries", summary.get("alignment") == alignment and summary.get("variants") == variants and summary.get("coverage_cnv") == cnv and summary.get("signatures") == signatures and summary.get("sv") == sv, "Standalone component summaries match the full-run summary.")

    run_ids = {str(summary.get("run_id", "")), str(preflight.get("run_id", "")), str(gather.get("run_id", ""))}
    input_payload = summary.get("input", {}) if isinstance(summary.get("input"), dict) else {}
    add_check(
        checks,
        "run_provenance",
        len(run_ids) == 1
        and "" not in run_ids
        and preflight.get("status") == "passed"
        and gather.get("status") == "passed"
        and integer_equals(input_payload.get("lanes"), 8)
        and integer_equals(preflight.get("wgs_lanes"), 8)
        and input_payload.get("source_integrity") == "passed",
        "Summary, preflight, and gather share one run ID; eight lanes and source integrity are explicit.",
    )

    execution_batch = execution.get("batch", {}) if isinstance(execution.get("batch"), dict) else {}
    execution_container = execution.get("container", {}) if isinstance(execution.get("container"), dict) else {}
    execution_worker = execution.get("worker", {}) if isinstance(execution.get("worker"), dict) else {}
    execution_queue = execution.get("queue", {}) if isinstance(execution.get("queue"), dict) else {}
    execution_definition = execution.get("job_definition", {}) if isinstance(execution.get("job_definition"), dict) else {}
    execution_command = execution_batch.get("command", []) if isinstance(execution_batch.get("command"), list) else []
    execution_attempts = execution_batch.get("attempts", []) if isinstance(execution_batch.get("attempts"), list) else []
    execution_attempt = execution_attempts[0] if len(execution_attempts) == 1 and isinstance(execution_attempts[0], dict) else {}
    execution_timeout = execution_batch.get("timeout", {}) if isinstance(execution_batch.get("timeout"), dict) else {}
    execution_retry = execution_batch.get("retry_strategy", {}) if isinstance(execution_batch.get("retry_strategy"), dict) else {}
    image_digest = str(execution_container.get("image_digest", ""))
    worker_sha = str(execution_worker.get("sha256", ""))
    add_check(
        checks,
        "batch_execution_provenance",
        exact_schema_version(execution, 1)
        and execution.get("run_id") == summary.get("run_id")
        and execution_batch.get("status") == "SUCCEEDED"
        and positive_int(execution_batch.get("started_at_epoch_ms"))
        and nonnegative_int(execution_batch.get("stopped_at_epoch_ms"))
        and execution_batch["stopped_at_epoch_ms"] >= execution_batch["started_at_epoch_ms"]
        and bool(execution_batch.get("job_id"))
        and bool(execution_batch.get("job_queue_arn"))
        and bool(execution_batch.get("job_definition_arn"))
        and bool(execution_batch.get("log_stream"))
        and integer_equals(execution_batch.get("attempt_count"), 1)
        and len(execution_attempts) == 1
        and positive_int(execution_attempt.get("started_at_epoch_ms"))
        and nonnegative_int(execution_attempt.get("stopped_at_epoch_ms"))
        and execution_attempt["stopped_at_epoch_ms"] >= execution_attempt["started_at_epoch_ms"]
        and integer_equals(execution_attempt.get("exit_code"), 0)
        and execution_attempt.get("task_arn") == execution_container.get("task_arn")
        and execution_attempt.get("log_stream") == execution_batch.get("log_stream")
        and positive_int(execution_timeout.get("attemptDurationSeconds"))
        and integer_equals(execution_retry.get("attempts"), 1)
        and image_digest.startswith("sha256:")
        and len(image_digest) == 71
        and len(worker_sha) == 64
        and all(character in "0123456789abcdef" for character in worker_sha)
        and summary.get("run_id") in " ".join(str(value) for value in execution_command)
        and execution_queue.get("status") == "VALID"
        and positive_int(execution_definition.get("revision")),
        "The single successful Batch attempt, effective timeout/retry controls, queue, definition revision, command, log stream, immutable container digest, and worker SHA-256 are captured.",
    )
    stage_provenance_evidence = validate_stage_provenance(
        stage_provenance,
        stage_provenance_anchor,
        receipt_path=paths["stage_provenance"],
        execution_path=paths["execution"],
        preflight_path=paths["preflight"],
        gather_path=paths["gather"],
        run_id=str(summary.get("run_id", "")),
        batch_job_id=str(execution_batch.get("job_id", "")),
        expected_kms_key_arn=args.expected_kms_key_arn,
    )
    add_check(
        checks,
        "stage_provenance_custody",
        stage_provenance_evidence["status"] == "passed",
        "Preflight and gather bytes match their exact private S3 VersionIds, full-object checksums, SHA-256 values, KMS key, successful execution receipt, and content-addressed receipt anchor.",
    )
    worker_checks = execution_worker.get("checks")
    worker_freeze_checks = executed_worker_freeze.get("checks")
    worker_freeze_source = (
        executed_worker_freeze.get("source")
        if isinstance(executed_worker_freeze.get("source"), dict)
        else {}
    )
    worker_freeze_object = (
        executed_worker_freeze.get("freeze")
        if isinstance(executed_worker_freeze.get("freeze"), dict)
        else {}
    )
    worker_freeze_upload_object = (
        executed_worker_freeze_upload.get("object")
        if isinstance(executed_worker_freeze_upload.get("object"), dict)
        else {}
    )
    worker_freeze_upload_checks = executed_worker_freeze_upload.get("checks")
    executed_worker_uri = (
        f"s3://{worker_freeze_object.get('bucket', '')}/{worker_freeze_object.get('key', '')}"
    )
    add_check(
        checks,
        "batch_worker_custody",
        exact_schema_status(executed_worker_freeze)
        and executed_worker_freeze.get("run_id") == summary.get("run_id")
        and executed_worker_freeze.get("batch_job_id") == execution_batch.get("job_id")
        and worker_freeze_source.get("task_arn") == execution_container.get("task_arn")
        and worker_freeze_source.get("container_runtime_id")
        in (execution_container.get("runtime_ids") or [])
        and worker_freeze_source.get("bytes") == execution_worker.get("bytes")
        and worker_freeze_source.get("sha256") == execution_worker.get("sha256")
        and worker_freeze_object.get("bytes") == execution_worker.get("bytes")
        and worker_freeze_object.get("checksum_sha256_hex")
        == execution_worker.get("sha256")
        and worker_freeze_object.get("version_id")
        == execution_worker.get("executed_version_id")
        and executed_worker_uri == execution_worker.get("executed_uri")
        and str(execution_worker.get("executed_uri", "")).startswith(
            "s3://diana-omics-private-results-"
        )
        and str(execution_worker.get("launch_uri", ""))
        in " ".join(str(value) for value in execution_command)
        and execution_worker.get("freeze_receipt_sha256")
        == sha256(paths["executed_worker_freeze"])
        and execution_worker.get("freeze_receipt_upload_sha256")
        == sha256(paths["executed_worker_freeze_upload"])
        and exact_schema_status(executed_worker_freeze_upload)
        and executed_worker_freeze_upload.get("local_receipt_sha256")
        == sha256(paths["executed_worker_freeze"])
        and worker_freeze_upload_object.get("version_id")
        == execution_worker.get("freeze_receipt_version_id")
        and worker_freeze_upload_object.get("checksum_sha256_hex")
        == sha256(paths["executed_worker_freeze"])
        and worker_freeze_upload_object.get("kms_key_id")
        == args.expected_kms_key_arn
        and execution_worker.get("server_side_encryption") == "aws:kms"
        and execution_worker.get("kms_key_id") == args.expected_kms_key_arn
        and worker_freeze_object.get("kms_key_id") == args.expected_kms_key_arn
        and positive_int(execution_worker.get("bytes"))
        and len(str(execution_worker.get("sha256", ""))) == 64
        and bool(execution_worker.get("etag"))
        and bool(execution_worker.get("last_modified"))
        and execution_worker.get("checksum_type") == "FULL_OBJECT"
        and isinstance(execution_worker.get("checksums"), dict)
        and bool(execution_worker.get("checksums"))
        and worker_checks == EXPECTED_BATCH_WORKER_CHECKS
        and worker_freeze_checks == EXPECTED_EXECUTED_WORKER_FREEZE_CHECKS
        and worker_freeze_upload_checks
        == EXPECTED_EXECUTED_WORKER_FREEZE_UPLOAD_CHECKS,
        "The exact worker bytes read from the active ECS container were SHA-256 hashed, frozen under a non-null private S3 VersionId, and independently rebound to the Batch task, runtime ID, full-object checksum, and exact KMS key.",
    )

    freeze_rows = final_freeze.get("objects", []) if isinstance(final_freeze.get("objects"), list) else []
    final_freeze_evidence = validate_final_freeze_provenance(
        final_freeze,
        final_freeze_anchor,
        receipt_path=paths["final_freeze"],
        execution_path=paths["execution"],
        run_id=str(summary.get("run_id", "")),
        batch_job_id=str(execution_batch.get("job_id", "")),
        expected_kms_key_arn=args.expected_kms_key_arn,
    )
    freeze_by_relative: dict[str, dict[str, Any]] = {}
    duplicate_freeze_keys = False
    for row in freeze_rows:
        if not isinstance(row, dict):
            duplicate_freeze_keys = True
            continue
        try:
            relative_key = safe_artifact_relative(row.get("relative_key", ""))
        except ValueError:
            duplicate_freeze_keys = True
            continue
        if relative_key in freeze_by_relative:
            duplicate_freeze_keys = True
            continue
        freeze_by_relative[relative_key] = row
    consumed_artifacts = {
        str(path.relative_to(artifact_root)): path
        for path in paths.values()
        if path.is_relative_to(artifact_root)
    }
    freeze_consumed_valid = not duplicate_freeze_keys and bool(consumed_artifacts)
    freeze_all_valid = freeze_consumed_valid and set(consumed_artifacts).issubset(freeze_by_relative)
    consumed_version_ids: dict[str, str] = {}
    for relative_key, row in freeze_by_relative.items():
        local_path = artifact_root / relative_key
        destination = row.get("destination", {}) if isinstance(row.get("destination"), dict) else {}
        row_checks = row.get("checks", {}) if isinstance(row.get("checks"), dict) else {}
        version_id = str(destination.get("version_id", ""))
        if relative_key in consumed_artifacts:
            consumed_version_ids[relative_key] = version_id
        if not (
            local_path.is_file()
            and row.get("status") == "passed"
            and integer_equals(destination.get("bytes"), local_path.stat().st_size)
            and version_id not in {"", "null", "None"}
            and destination.get("server_side_encryption") == "aws:kms"
            and destination.get("kms_key_id") == args.expected_kms_key_arn
            and isinstance(destination.get("checksums"), dict)
            and bool(destination.get("checksums"))
            and row_checks == EXPECTED_FINAL_FREEZE_ROW_CHECKS
        ):
            freeze_all_valid = False
    freeze_consumed_valid = freeze_all_valid
    add_check(
        checks,
        "final_artifact_freeze",
        exact_schema_status(final_freeze)
        and final_freeze.get("run_id") == summary.get("run_id")
        and final_freeze.get("batch_job_id") == execution_batch.get("job_id")
        and final_freeze.get("batch_status") == "SUCCEEDED"
        and final_freeze.get("kms_key_arn") == args.expected_kms_key_arn
        and final_freeze_evidence["status"] == "passed"
        and integer_equals(final_freeze.get("object_count"), len(freeze_rows))
        and all(isinstance(row, dict) and row.get("status") == "passed" for row in freeze_rows)
        and freeze_consumed_valid,
        "Every frozen final artifact is present locally and bound to a passed private freeze row with matching bytes, non-null VersionId, checksum, exact KMS key, successful Batch job, and run ID.",
    )

    materialized_rows = (
        exact_materialization.get("objects", [])
        if isinstance(exact_materialization.get("objects"), list)
        else []
    )
    materialized_by_relative: dict[str, dict[str, Any]] = {}
    duplicate_materialized_keys = False
    for row in materialized_rows:
        if not isinstance(row, dict):
            duplicate_materialized_keys = True
            continue
        try:
            relative_key = safe_artifact_relative(row.get("relative_key", ""))
        except ValueError:
            duplicate_materialized_keys = True
            continue
        if relative_key in materialized_by_relative:
            duplicate_materialized_keys = True
            continue
        materialized_by_relative[relative_key] = row
    exact_materialization_valid = (
        not duplicate_materialized_keys
        and bool(consumed_artifacts)
        and exact_materialization_receipt_envelope(exact_materialization)
        and valid_sha256(exact_materialization.get("script_sha256"))
        and str(exact_materialization.get("materialization_dir", "")).strip()
        and set(materialized_by_relative) == set(freeze_by_relative)
    )
    for relative_key, row in materialized_by_relative.items():
        local_path = artifact_root / relative_key
        freeze_destination = freeze_by_relative.get(relative_key, {}).get("destination", {})
        row_checks = row.get("checks", {}) if isinstance(row.get("checks"), dict) else {}
        if not (
            local_path.is_file()
            and set(row) == INPUT_CONTRACT.EXPECTED_MATERIALIZATION_ROW_KEYS
            and row.get("version_id") == freeze_destination.get("version_id")
            and row.get("bucket") == freeze_destination.get("bucket")
            and row.get("key") == freeze_destination.get("key")
            and integer_equals(row.get("bytes"), local_path.stat().st_size)
            and row.get("sha256") == sha256(local_path)
            and row.get("checksums") == freeze_destination.get("checksums")
            and row.get("checksum_type") == freeze_destination.get("checksum_type") == "FULL_OBJECT"
            and row.get("server_side_encryption") == "aws:kms"
            and row.get("kms_key_id") == args.expected_kms_key_arn
            and isinstance(row.get("checksums"), dict)
            and bool(row.get("checksums"))
            and row_checks == INPUT_CONTRACT.EXPECTED_MATERIALIZATION_CHECKS
        ):
            exact_materialization_valid = False
    add_check(
        checks,
        "exact_version_materialization",
        exact_schema_status(exact_materialization)
        and exact_materialization.get("run_id") == summary.get("run_id")
        and exact_materialization.get("batch_job_id") == execution_batch.get("job_id")
        and exact_materialization.get("freeze_receipt_sha256") == sha256(paths["final_freeze"])
        and exact_materialization.get("expected_kms_key_arn") == args.expected_kms_key_arn
        and integer_equals(
            exact_materialization.get("object_count"),
            len(materialized_rows),
        )
        and integer_equals(
            exact_materialization.get("passed_count"),
            len(materialized_rows),
        )
        and len(materialized_rows) == len(freeze_rows)
        and exact_materialization_valid,
        "Every frozen artifact was downloaded from its exact S3 VersionId and re-bound to the returned checksum, byte count, KMS key, and local SHA-256.",
    )

    crosscheck_sources = (
        crosscheck_materialization.get("source_custody", {})
        if isinstance(crosscheck_materialization.get("source_custody"), dict)
        else {}
    )
    crosscheck_inputs = (
        crosscheck_materialization.get("input_sha256", {})
        if isinstance(crosscheck_materialization.get("input_sha256"), dict)
        else {}
    )
    crosscheck_outputs = (
        crosscheck_materialization.get("outputs", {})
        if isinstance(crosscheck_materialization.get("outputs"), dict)
        else {}
    )
    crosscheck_validation = (
        crosscheck_materialization.get("validation", {})
        if isinstance(crosscheck_materialization.get("validation"), dict)
        else {}
    )
    expected_crosscheck_sources = {
        "vcf": (
            "variants/diana.wgs.mutect2.filtered.vcf.gz",
            "filtered_vcf",
        ),
        "vcf_index": (
            "variants/diana.wgs.mutect2.filtered.vcf.gz.tbi",
            "filtered_vcf_index",
        ),
        "matrix": ("signatures/wgs_sbs96_matrix.csv", "source_sbs96_matrix"),
    }
    crosscheck_sources_valid = (
        set(crosscheck_sources) == {"vcf", "vcf_index", "matrix", "fasta", "fai"}
        and set(crosscheck_inputs)
        == {
            "filtered_vcf",
            "filtered_vcf_index",
            "source_sbs96_matrix",
            "reference_fasta",
            "reference_fai",
        }
    )
    for source_name, (relative_key, input_name) in expected_crosscheck_sources.items():
        source = (
            crosscheck_sources.get(source_name, {})
            if isinstance(crosscheck_sources.get(source_name), dict)
            else {}
        )
        freeze_destination = (
            freeze_by_relative.get(relative_key, {}).get("destination", {})
            if isinstance(
                freeze_by_relative.get(relative_key, {}).get("destination"), dict
            )
            else {}
        )
        materialized = materialized_by_relative.get(relative_key, {})
        source_sha256 = str(source.get("sha256", ""))
        if not (
            valid_version_id(source.get("version_id"))
            and source.get("version_id") == freeze_destination.get("version_id")
            and source.get("version_id") == materialized.get("version_id")
            and positive_int(source.get("bytes"))
            and integer_equals(source.get("bytes"), materialized.get("bytes"))
            and valid_sha256(source_sha256)
            and source_sha256 == materialized.get("sha256")
            and source_sha256 == crosscheck_inputs.get(input_name)
            and source.get("kms_key_arn") == args.expected_kms_key_arn
            and s3_checksums(source.get("checksums"))
            == s3_checksums(materialized.get("checksums"))
            and bool(s3_checksums(source.get("checksums")))
        ):
            crosscheck_sources_valid = False

    staged_checks = (
        staged_input_validation.get("checks", {})
        if isinstance(staged_input_validation.get("checks"), dict)
        else {}
    )
    staged_vcf = (
        staged_checks.get("somatic_vcf_reference", {})
        if isinstance(staged_checks.get("somatic_vcf_reference"), dict)
        else {}
    )
    staged_sbs96 = (
        staged_checks.get("sbs96_equivalence", {})
        if isinstance(staged_checks.get("sbs96_equivalence"), dict)
        else {}
    )
    for source_name, input_name, staged_hash_name in (
        ("fasta", "reference_fasta", "reference_fasta_sha256"),
        ("fai", "reference_fai", "reference_fai_sha256"),
    ):
        source = (
            crosscheck_sources.get(source_name, {})
            if isinstance(crosscheck_sources.get(source_name), dict)
            else {}
        )
        source_sha256 = str(source.get("sha256", ""))
        if not (
            valid_version_id(source.get("version_id"))
            and positive_int(source.get("bytes"))
            and valid_sha256(source_sha256)
            and source_sha256 == source.get("expected_sha256")
            and source_sha256 == crosscheck_inputs.get(input_name)
            and source_sha256 == staged_vcf.get(staged_hash_name)
            and source.get("kms_key_arn") == args.expected_kms_key_arn
            and bool(s3_checksums(source.get("checksums")))
        ):
            crosscheck_sources_valid = False

    expected_crosscheck_output_names = {
        "somatic.pass.vcf.gz",
        "somatic.pass.vcf.gz.tbi",
        "sbs96.csv",
        "staged_input_validation.json",
    }
    freeze_destination_prefix = str(final_freeze.get("destination_prefix", ""))
    final_suffix = "/deterministic/final/"
    crosscheck_output_prefix = ""
    if freeze_destination_prefix.endswith(final_suffix):
        crosscheck_output_prefix = freeze_destination_prefix
    crosscheck_receipt_checks = (
        crosscheck_materialization.get("checks")
        if isinstance(crosscheck_materialization.get("checks"), dict)
        else {}
    )
    destination_inventory = (
        crosscheck_materialization.get("destination_inventory")
        if isinstance(crosscheck_materialization.get("destination_inventory"), list)
        else []
    )
    inventory_by_name: dict[str, dict[str, Any]] = {}
    duplicate_or_malformed_inventory = False
    for raw_row in destination_inventory:
        if (
            not isinstance(raw_row, dict)
            or set(raw_row) != EXPECTED_CROSSCHECK_DESTINATION_INVENTORY_KEYS
        ):
            duplicate_or_malformed_inventory = True
            continue
        filename = str(raw_row.get("filename", ""))
        if filename in inventory_by_name:
            duplicate_or_malformed_inventory = True
            continue
        inventory_by_name[filename] = raw_row

    crosscheck_outputs_valid = (
        bool(crosscheck_output_prefix)
        and set(crosscheck_outputs) == expected_crosscheck_output_names
        and set(crosscheck_materialization) == EXPECTED_CROSSCHECK_RECEIPT_KEYS
        and crosscheck_materialization.get("destination_prefix")
        == crosscheck_output_prefix
        and crosscheck_materialization.get("destination_bucket_versioning")
        == "Enabled"
        and crosscheck_materialization.get("destination_initial_version_history_count")
        == 0
        and crosscheck_materialization.get("receipt_anchor_strategy")
        == "sha256_content_addressed_create_only"
        and crosscheck_receipt_checks == EXPECTED_CROSSCHECK_RECEIPT_CHECKS
        and not duplicate_or_malformed_inventory
        and set(inventory_by_name) == expected_crosscheck_output_names
    )
    for output_name in expected_crosscheck_output_names:
        output_row = (
            crosscheck_outputs.get(output_name, {})
            if isinstance(crosscheck_outputs.get(output_name), dict)
            else {}
        )
        output_checks = (
            output_row.get("checks")
            if isinstance(output_row.get("checks"), dict)
            else {}
        )
        inventory = inventory_by_name.get(output_name, {})
        if not (
            output_row.get("uri") == crosscheck_output_prefix + output_name
            and valid_version_id(output_row.get("version_id"))
            and positive_int(output_row.get("bytes"))
            and valid_sha256(output_row.get("sha256"))
            and output_row.get("kms_key_arn") == args.expected_kms_key_arn
            and s3_full_object_sha256_matches(
                output_row.get("checksums"),
                output_row.get("sha256"),
            )
            and output_checks == EXPECTED_CROSSCHECK_OUTPUT_CHECKS
            and inventory.get("key") == s3_key(output_row.get("uri"))
            and inventory.get("version_id") == output_row.get("version_id")
            and inventory.get("bytes") == output_row.get("bytes")
            and inventory.get("sha256") == output_row.get("sha256")
            and inventory.get("checksums") == output_row.get("checksums")
        ):
            crosscheck_outputs_valid = False
    staged_output = (
        crosscheck_outputs.get("staged_input_validation.json", {})
        if isinstance(crosscheck_outputs.get("staged_input_validation.json"), dict)
        else {}
    )
    crosscheck_outputs_valid = (
        crosscheck_outputs_valid
        and staged_output.get("sha256") == sha256(paths["staged_input_validation"])
        and integer_equals(
            staged_output.get("bytes"),
            paths["staged_input_validation"].stat().st_size,
        )
    )
    crosscheck_validation_valid = (
        crosscheck_validation.get("status") == "passed"
        and crosscheck_validation.get("run_alias") == "subject01"
        and crosscheck_validation.get("source_sample_names_retained") is False
        and crosscheck_validation.get("matrix_matches_independent_pass_vcf_derivation")
        is True
        and integer_equals(
            crosscheck_validation.get("pass_snv_records"),
            staged_vcf.get("pass_snv_records"),
        )
        and integer_equals(
            crosscheck_validation.get("pass_snv_alleles"),
            staged_sbs96.get("usable_pass_snv_alleles"),
        )
        and integer_equals(
            crosscheck_validation.get("sbs96_contexts"),
            staged_sbs96.get("contexts"),
        )
        and integer_equals(
            crosscheck_validation.get("sbs96_burden"),
            staged_sbs96.get("matrix_burden"),
        )
    )
    crosscheck_terminal_evidence = validate_crosscheck_terminal_capture(
        crosscheck_materialization_capture,
        crosscheck_materialization_anchor,
        crosscheck_materialization,
        staged_input_validation_download,
        capture_path=paths["crosscheck_materialization_capture"],
        anchor_path=paths["crosscheck_materialization_anchor"],
        receipt_path=paths["crosscheck_materialization"],
        download_path=paths["staged_input_validation_download"],
        staged_input_validation_path=paths["staged_input_validation"],
        expected_kms_key_arn=args.expected_kms_key_arn,
        run_id=str(summary.get("run_id", "")),
    )
    add_check(
        checks,
        "crosscheck_materialization_custody",
        exact_schema_status(crosscheck_materialization, 2)
        and crosscheck_materialization.get("run_alias") == "subject01"
        and valid_sha256(crosscheck_materialization.get("script_sha256"))
        and crosscheck_materialization.get("classification_authorization") == "none"
        and crosscheck_materialization.get("authorized_hrd_state") == "no_call"
        and exact_schema_version(staged_input_validation, 1)
        and staged_input_validation.get("classification_authorization") == "none"
        and staged_input_validation.get("authorized_hrd_state") == "no_call"
        and crosscheck_sources_valid
        and crosscheck_outputs_valid
        and crosscheck_validation_valid,
        "The cross-check materializer consumed the exact frozen VCF/index/matrix VersionIds and SHA-256 values, used hash-pinned reference inputs, and emitted versioned KMS-bound canonical outputs whose staged-validation bytes are consumed by this report.",
    )
    add_check(
        checks,
        "crosscheck_terminal_custody",
        crosscheck_terminal_evidence["status"] == "passed",
        "The report consumed the exact terminal Batch materializer capture, its CloudWatch receipt anchor, its downloaded receipt bytes, and the exact staged-input-validation download receipt.",
    )

    audit_objects = (
        audit.get("objects", []) if isinstance(audit.get("objects"), list) else []
    )
    audit_rows = [row for row in audit_objects if isinstance(row, dict)]
    audit_byte_values = [row.get("actual_size_bytes") for row in audit_rows]
    audit_rows_exact = (
        len(audit_rows) == len(audit_objects)
        and all(nonnegative_int(value) for value in audit_byte_values)
    )
    audit_bytes = sum(value for value in audit_byte_values if nonnegative_int(value))
    audit_passed = sum(row.get("status") == "passed" for row in audit_rows)
    audit_matches = audit_rows_exact and all(
        row.get("size_matches") is True and row.get("sha256_matches") is True
        for row in audit_rows
    )
    wgs_objects = [row for row in audit_rows if row.get("dataset") == "wgs"]
    wgs_bytes = sum(
        row["actual_size_bytes"]
        for row in wgs_objects
        if nonnegative_int(row.get("actual_size_bytes"))
    )
    add_check(
        checks,
        "intake_sha256",
        audit.get("status") == "passed"
        and audit.get("algorithm") == "sha256"
        and audit_rows_exact
        and integer_equals(audit.get("object_count"), len(audit_rows))
        and audit_passed == len(audit_rows)
        and integer_equals(audit.get("passed_count"), audit_passed)
        and integer_equals(audit.get("failed_count"), 0)
        and integer_equals(audit.get("bytes_streamed"), audit_bytes)
        and audit_matches,
        "Audit totals and all per-object size/SHA-256 comparisons pass.",
    )
    add_check(checks, "wgs_provenance", len(wgs_objects) == 16 and all(row.get("data_type") == "FASTQ" and row.get("status") == "passed" for row in wgs_objects) and integer_equals(preflight.get("wgs_bytes"), wgs_bytes), "Sixteen WGS FASTQs passed SHA-256 and their bytes match preflight.")

    alignment_json_rows = alignment.get("rows", []) if isinstance(alignment.get("rows"), list) else []
    alignment_by_role = {str(row.get("role", "")): row for row in alignment_json_rows if isinstance(row, dict)}
    alignment_csv_by_role = {row.get("role", ""): row for row in alignment_rows}
    gather_samples = gather.get("samples", []) if isinstance(gather.get("samples"), list) else []
    gather_by_role = {str(row.get("role", "")): row for row in gather_samples if isinstance(row, dict)}
    reference_values = [input_payload.get("reference"), preflight.get("reference"), gather.get("reference")]
    reference_values.extend(row.get("reference") for row in alignment_json_rows if isinstance(row, dict))
    add_check(checks, "reference_provenance", len({normalized_reference(value) for value in reference_values}) == 1 and normalized_reference(reference_values[0]) != "", "Summary, preflight, gather, and alignment rows use the same normalized reference identity.")
    add_check(checks, "alignment_roles", alignment.get("status") == "passed" and set(alignment_by_role) == {"tumor", "normal"} and set(alignment_csv_by_role) == {"tumor", "normal"} and all(row.get("status") == "passed" for row in alignment_json_rows if isinstance(row, dict)), "Alignment JSON/CSV contain passed tumor and normal rows.")
    alignment_consistent = True
    for role in ("tumor", "normal"):
        json_row = alignment_by_role.get(role, {})
        csv_row = alignment_csv_by_role.get(role, {})
        gather_row = gather_by_role.get(role, {})
        for field in ("bam_bytes", "total_reads", "mapped_reads", "duplicate_reads"):
            if not nonnegative_int(json_row.get(field)) or str(
                json_row.get(field)
            ) != str(csv_row.get(field, "")):
                alignment_consistent = False
        if not integer_equals(
            json_row.get("bam_bytes"),
            gather_row.get("output_bam_bytes"),
        ) or not integer_equals(gather_row.get("lane_count"), 4):
            alignment_consistent = False
    add_check(checks, "alignment_provenance", alignment_consistent and set(gather_by_role) == {"tumor", "normal"}, "Alignment JSON/CSV metrics match four-lane-per-role gather BAM provenance.")
    alignment_metrics_valid = True
    for role in ("tumor", "normal"):
        row = alignment_by_role.get(role, {})
        bam_bytes = row.get("bam_bytes")
        total_reads = row.get("total_reads")
        mapped_reads = row.get("mapped_reads")
        duplicate_reads = row.get("duplicate_reads")
        if not (
            positive_int(bam_bytes)
            and positive_int(total_reads)
            and nonnegative_int(mapped_reads)
            and nonnegative_int(duplicate_reads)
            and mapped_reads <= total_reads
            and duplicate_reads <= total_reads
        ):
            alignment_metrics_valid = False
    add_check(
        checks,
        "alignment_metric_bounds",
        alignment_metrics_valid,
        "Tumor and normal BAM sizes/read totals are positive and mapped/duplicate counts are bounded by total reads.",
    )

    flagstat_consistent = True
    for role in ("tumor", "normal"):
        text = paths[f"{role}_flagstat"].read_text(encoding="utf-8")
        patterns = {
            "total_reads": r"^(\d+) \+ \d+ in total",
            "mapped_reads": r"^(\d+) \+ \d+ mapped",
            "duplicate_reads": r"^(\d+) \+ \d+ duplicates",
        }
        for field, pattern in patterns.items():
            match = re.search(pattern, text, re.MULTILINE)
            if not match or not integer_equals(
                alignment_by_role[role].get(field),
                int(match.group(1)),
            ):
                flagstat_consistent = False
    add_check(checks, "alignment_flagstat", flagstat_consistent, "Role-level flagstat totals match alignment summaries.")

    add_check(checks, "contamination_artifacts", variants.get("contamination_table") == paths["contamination"].name and len(contamination_rows) == 1 and bool(contamination_rows[0].get("sample")) and 0 <= safe_float(contamination_rows[0].get("contamination")) < 1 and safe_float(contamination_rows[0].get("error")) >= 0 and all(paths[name].stat().st_size > 0 for name in ("tumor_segmentation", "tumor_pileups", "normal_pileups", "orientation_model")), "Contamination, matched-normal pileups, segmentation, and orientation-bias artifacts are present and parseable.")

    filtered_total = bcftools_index_records(bcftools, paths["filtered_vcf"])
    filtered_total_streamed = bcftools_count(bcftools, paths["filtered_vcf"], [])
    filtered_pass = bcftools_count(bcftools, paths["filtered_vcf"], ["-f", "PASS"])
    filtered_snvs = bcftools_count(bcftools, paths["filtered_vcf"], ["-f", "PASS", "-v", "snps"])
    filtered_indels = bcftools_count(bcftools, paths["filtered_vcf"], ["-f", "PASS", "-v", "indels"])
    add_check(checks, "filtered_vcf_index", paths["filtered_vcf_index"].stat().st_size > 0 and filtered_total == filtered_total_streamed, "The filtered VCF index is readable and its record count matches a full VCF stream.")
    variant_summary_counts_match = (
        variants.get("status") == "passed"
        and integer_equals(variants.get("total_filtered_records"), filtered_total)
        and integer_equals(variants.get("pass_records"), filtered_pass)
        and integer_equals(variants.get("pass_snvs"), filtered_snvs)
        and integer_equals(variants.get("pass_indels"), filtered_indels)
    )
    add_check(checks, "variant_summary_counts", variant_summary_counts_match, "Filtered, PASS, SNV, and indel VCF counts match mutect2_summary.json.")

    brca_vcf_count = bcftools_index_records(bcftools, paths["brca_vcf"])
    brca_stream_count = bcftools_count(bcftools, paths["brca_vcf"], [])
    brca_rows_valid = all(row.get("filter") == "PASS" and row.get("region_label") in {"BRCA1", "BRCA2"} and row.get("annotation_status") == "region_only_requires_variant_annotation_review" for row in brca_rows)
    brca_region_rows_match = (
        paths["brca_vcf_index"].stat().st_size > 0
        and brca_vcf_count == brca_stream_count == len(brca_rows)
        and integer_equals(
            variants.get("brca1_brca2_pass_region_records"), len(brca_rows)
        )
        and brca_rows_valid
    )
    add_check(checks, "brca_region_rows", brca_region_rows_match, "Indexed BRCA-region VCF, CSV rows, summary count, PASS state, and region-only annotation boundary agree.")

    sbs_counts = [int(row.get("count", -1)) for row in sbs_rows]
    sbs_count_sum = sum(sbs_counts)
    sbs_keys = {(row.get("mutation_type", ""), row.get("trinucleotide", "")) for row in sbs_rows}
    sbs96_matrix_match = (
        signatures.get("status") == "partial_evidence"
        and len(sbs_rows) == 96
        and integer_equals(signatures.get("sbs96_rows"), len(sbs_rows))
        and sbs_keys == EXPECTED_SBS96
        and min(sbs_counts, default=-1) >= 0
        and integer_equals(signatures.get("usable_snv_records"), sbs_count_sum)
        and nonnegative_int(signatures.get("skipped_snv_records"))
        and str(signatures.get("sbs3_status", "")).startswith("no_call")
        and signatures.get("source_vcf") == paths["filtered_vcf"].name
    )
    add_check(
        checks,
        "sbs96_matrix",
        sbs96_matrix_match,
        "SBS96 has exactly the 96 canonical nonnegative channels summing to the summary count; SBS3 remains no_call.",
    )
    add_check(
        checks,
        "independent_vcf_sbs96_validation",
        staged_input_validation.get("status") == "passed"
        and staged_input_validation.get("route") == "sigprofiler_sbs3"
        and staged_vcf.get("status") == "passed"
        and staged_sbs96.get("status") == "passed"
        and staged_sbs96.get("matrix_matches_independent_pass_vcf_derivation") is True
        and integer_equals(staged_sbs96.get("contexts"), 96)
        and integer_equals(
            staged_sbs96.get("usable_pass_snv_alleles"),
            signatures.get("usable_snv_records"),
        )
        and integer_equals(
            staged_sbs96.get("matrix_burden"),
            signatures.get("usable_snv_records"),
        ),
        "An independent indexed-reference pass reproduced every SBS96 channel exactly from the final PASS-SNV VCF and validated VCF/reference compatibility.",
    )

    cnv_classes = Counter(row.get("coverage_class", "") for row in cnv_rows)
    coverage_cnv_match = (
        cnv.get("status") == "partial_evidence"
        and integer_equals(cnv.get("bin_count"), len(cnv_rows))
        and set(cnv_classes) <= {"relative_gain", "relative_loss", "neutral_or_low_signal"}
        and integer_equals(cnv.get("relative_gain_bins"), cnv_classes["relative_gain"])
        and integer_equals(cnv.get("relative_loss_bins"), cnv_classes["relative_loss"])
        and str(cnv.get("scarhrd_input_status", "")).startswith("no_call")
    )
    add_check(checks, "coverage_cnv", coverage_cnv_match, "CNV rows use only the worker's three coverage classes, row/class counts match the summary, and scarHRD input remains no_call.")

    sv_json_rows = sv.get("rows", []) if isinstance(sv.get("rows"), list) else []
    sv_json_by_role = {str(row.get("role", "")): row for row in sv_json_rows if isinstance(row, dict)}
    sv_csv_by_role = {row.get("role", ""): row for row in sv_rows}
    sv_consistent = sv.get("status") == "partial_evidence" and sv.get("production_sv_callset_status") == "no_call" and set(sv_json_by_role) == set(sv_csv_by_role) == {"tumor", "normal"}
    for role in ("tumor", "normal"):
        json_row = sv_json_by_role.get(role, {})
        csv_row = sv_csv_by_role.get(role, {})
        for field in SV_COUNT_FIELDS:
            csv_value = parse_nonnegative_int_text(csv_row.get(field))
            if csv_value is None or not integer_equals(
                json_row.get(field), csv_value
            ):
                sv_consistent = False
        if str(json_row.get("chord_input_status", "")) != str(
            csv_row.get("chord_input_status", "")
        ):
            sv_consistent = False
        if not integer_equals(
            json_row.get("total_alignments"),
            alignment_by_role[role].get("total_reads"),
        ) or not str(json_row.get("chord_input_status", "")).startswith("no_call"):
            sv_consistent = False
    add_check(checks, "sv_evidence", sv_consistent, "SV JSON/CSV agree by role; alignment totals reconcile; production SV and CHORD inputs remain no_call.")

    add_check(checks, "tool_versions", set(tools) == {"bwa", "samtools", "bcftools", "gatk"} and all(str(value).strip() for value in tools.values()), "BWA, samtools, bcftools, and GATK versions are present.")
    early_variants = early.get("core_hrr_variants", {}) if isinstance(early.get("core_hrr_variants"), dict) else {}
    early_cnv = early.get("coverage_cnv", {}) if isinstance(early.get("coverage_cnv"), dict) else {}
    early_bam_qc = early.get("bam_qc", {}) if isinstance(early.get("bam_qc"), dict) else {}
    early_tumor_bam_qc = early_bam_qc.get("tumor", {}) if isinstance(early_bam_qc.get("tumor"), dict) else {}
    early_normal_bam_qc = early_bam_qc.get("normal", {}) if isinstance(early_bam_qc.get("normal"), dict) else {}
    early_cnv_classes = Counter(row.get("coverage_class", "") for row in early_cnv_rows)
    early_baseline_match = (
        early.get("status") == "partial_evidence"
        and early.get("overall_hrd_status") == "no_call"
        and positive_int(early_tumor_bam_qc.get("total_reads"))
        and positive_int(early_normal_bam_qc.get("total_reads"))
        and integer_equals(early_variants.get("pass_records"), len(early_pass_rows))
        and nonnegative_int(early_variants.get("brca1_brca2_pass_records"))
        and early_variants.get("brca1_brca2_pass_records")
        <= early_variants.get("pass_records")
        and integer_equals(early_cnv.get("bin_count"), len(early_cnv_rows))
        and set(early_cnv_classes) <= {"relative_gain", "relative_loss", "neutral_or_low_signal"}
        and integer_equals(
            early_cnv.get("relative_gain_bins"), early_cnv_classes["relative_gain"]
        )
        and integer_equals(
            early_cnv.get("relative_loss_bins"), early_cnv_classes["relative_loss"]
        )
    )
    add_check(checks, "early_baseline_boundary", early_baseline_match, "Early-look baseline is internally consistent and remains partial_evidence/no_call.")

    failed = [row for row in checks if row["status"] != "passed"]
    if failed:
        raise SystemExit("Fail-closed: evidence validation failed:\n" + "\n".join(f"{row['check_id']}: {row['detail']}" for row in failed))

    input_rows = build_input_rows(paths, artifact_root, early_root)
    input_snapshot_file_count = input_snapshot["file_count"]
    contamination = safe_float(contamination_rows[0]["contamination"])
    contamination_error = safe_float(contamination_rows[0]["error"])
    early_contamination = safe_float(early.get("contamination", {}).get("contamination"))
    brca_counts = Counter(row.get("region_label", "") for row in brca_rows)
    usable_snv_records = signatures["usable_snv_records"]
    skipped_snv_records = signatures["skipped_snv_records"]
    exact_alignment_by_role = {
        role: {
            "bam_bytes": alignment_by_role[role]["bam_bytes"],
            "total_reads": alignment_by_role[role]["total_reads"],
            "mapped_reads": alignment_by_role[role]["mapped_reads"],
            "duplicate_reads": alignment_by_role[role]["duplicate_reads"],
        }
        for role in ("tumor", "normal")
    }
    neutral_bins = cnv_classes["neutral_or_low_signal"]
    early_tumor_total_reads = early_tumor_bam_qc["total_reads"]
    early_normal_total_reads = early_normal_bam_qc["total_reads"]
    early_total_pass = early_variants["pass_records"]
    early_brca = early_variants["brca1_brca2_pass_records"]
    comparison_rows = [
        ["Tumor total reads", format_int(early_tumor_total_reads), format_int(alignment_by_role["tumor"]["total_reads"]), format_int(alignment_by_role["tumor"]["total_reads"] - early_tumor_total_reads)],
        ["Normal total reads", format_int(early_normal_total_reads), format_int(alignment_by_role["normal"]["total_reads"]), format_int(alignment_by_role["normal"]["total_reads"] - early_normal_total_reads)],
        ["Contamination fraction", f"{early_contamination:.12g}", f"{contamination:.12g}", f"{contamination - early_contamination:+.12g}"],
        ["BRCA1/BRCA2 region PASS records", str(early_brca), str(len(brca_rows)), str(len(brca_rows) - early_brca)],
        ["Coverage-CNV bins", str(early_cnv["bin_count"]), str(cnv["bin_count"]), str(cnv["bin_count"] - early_cnv["bin_count"])],
        ["Relative-gain bins", str(early_cnv["relative_gain_bins"]), str(cnv["relative_gain_bins"]), str(cnv["relative_gain_bins"] - early_cnv["relative_gain_bins"])],
        ["Relative-loss bins", str(early_cnv["relative_loss_bins"]), str(cnv["relative_loss_bins"]), str(cnv["relative_loss_bins"] - early_cnv["relative_loss_bins"])],
        ["Median raw log2 tumor/normal", str(early_cnv.get("median_raw_log2_tumor_normal")), str(cnv.get("median_raw_log2_tumor_normal")), f"{safe_float(cnv.get('median_raw_log2_tumor_normal')) - safe_float(early_cnv.get('median_raw_log2_tumor_normal')):+.4f}"],
    ]
    alignment_report_rows = [
        [
            role,
            format_int(exact_alignment_by_role[role]["total_reads"]),
            format_int(exact_alignment_by_role[role]["mapped_reads"]),
            f"{100 * exact_alignment_by_role[role]['mapped_reads'] / exact_alignment_by_role[role]['total_reads']:.4f}%",
            format_int(exact_alignment_by_role[role]["duplicate_reads"]),
            f"{100 * exact_alignment_by_role[role]['duplicate_reads'] / exact_alignment_by_role[role]['total_reads']:.4f}%",
            f"{format_int(exact_alignment_by_role[role]['bam_bytes'])} ({format_gib(exact_alignment_by_role[role]['bam_bytes'])})",
        ]
        for role in ("tumor", "normal")
    ]
    sv_report_rows = [
        [
            role,
            format_int(sv_json_by_role[role]["supplementary_alignments"]),
            format_int(sv_json_by_role[role]["discordant_mapped_pairs"]),
            format_int(sv_json_by_role[role]["interchromosomal_pairs"]),
            format_int(sv_json_by_role[role]["large_insert_pairs"]),
        ]
        for role in ("tumor", "normal")
    ]
    tool_rows = [[key, str(tools[key])] for key in ("bwa", "samtools", "bcftools", "gatk")]
    command_text = " ".join(str(value) for value in execution_command)
    output_readiness = [{"evidence_surface": surface, "state": state, "reason": reason} for surface, state, reason in OUTPUT_READINESS]
    report = "\n".join(
        [
            "# Deterministic full-WGS HRD evidence report",
            "",
            f"Run ID: `{summary.get('run_id')}`",
            f"Source timestamp: `{summary.get('generated_at')}`",
            "",
            "**Evidence status: `partial_evidence`. Overall HRD status: `no_call`.**",
            "",
            "This private research-use report is descriptive. It does not make pathogenicity, biallelic, scarHRD, SBS3, CHORD, HRDetect, treatment, or clinical conclusions.",
            "",
            "## 1. Inputs and provenance",
            "",
            f"The intake audit validated {format_int(audit['passed_count'])}/{format_int(audit['object_count'])} payload objects and {format_int(audit['bytes_streamed'])} bytes ({format_gib(audit['bytes_streamed'])}) with SHA-256; zero objects failed. The WGS subset contained {format_int(len(wgs_objects))} FASTQs totaling {format_int(wgs_bytes)} bytes ({format_gib(wgs_bytes)}).",
            "",
            f"The final private freeze receipt contains {format_int(len(freeze_rows))} passed objects, including {format_int(len(consumed_artifacts))} directly consumed by this report, and binds the complete worker artifact tree to exact non-null S3 VersionIds, matching byte counts/checksums, the successful Batch job, and the declared KMS key. The source inventory was unchanged across the transaction, the destination has exactly one version per expected key and no extras/delete markers, and the receipt is frozen under content-addressed VersionId `{final_freeze_evidence['receipt_version_id']}`. Receipt SHA-256: `{sha256(paths['final_freeze'])}`; anchor SHA-256: `{sha256(paths['final_freeze_anchor'])}`.",
            f"The exact-version local materialization receipt re-downloaded all {format_int(len(materialized_rows))} frozen objects by VersionId and bound their returned S3 checksums and local SHA-256 values. Receipt SHA-256: `{sha256(paths['exact_materialization'])}`.",
            f"The cross-check materialization receipt independently re-bound the final filtered VCF, index, and SBS96 source matrix to those frozen VersionIds and SHA-256 values, then recorded exact VersionIds, SHA-256 values, checksums, byte counts, and the run KMS key for all four canonical outputs. Receipt SHA-256: `{sha256(paths['crosscheck_materialization'])}`.",
            f"The terminal materializer capture bound that receipt to the one successful Batch/CloudWatch terminal payload, and the staged-input-validation download receipt re-bound the consumed local staged-validation bytes. Capture SHA-256: `{crosscheck_terminal_evidence['capture_sha256']}`.",
            f"Preflight and gather were independently frozen in private storage at exact VersionIds under the run KMS key. Their receipt is content-addressed at VersionId `{stage_provenance_evidence['receipt_version_id']}` with SHA-256 `{stage_provenance_evidence['receipt_sha256']}`.",
            f"Before validation, all {format_int(input_snapshot_file_count)} files in the artifact tree, early-look tree, and external receipt set were copied into a private stable snapshot using no-follow opens, file-descriptor identity checks, and a global source re-stat. Snapshot receipt SHA-256: `{sha256(paths['input_snapshot'])}`.",
            "",
            f"Preflight and gather share the full-run ID and record eight lanes, the `{input_payload.get('reference')}` reference, and four lanes per tumor/normal role. Input SHA-256 verification establishes byte integrity, not sequence quality or biological interpretation.",
            "",
            "## 2. Methods and tool versions",
            "",
            f"Matched tumor-normal reads were aligned, merged by role, duplicate-marked, indexed, and validated. Somatic SNV/indel calling used `{variants.get('caller')}` with a panel of normals, germline resource, contamination estimation, and orientation-bias filtering. Coverage used `{cnv.get('tool')}`. SBS96 counts came from `{signatures.get('source_record_policy')}` records in the filtered VCF. SV evidence consists only of BAM-derived counts.",
            "",
            markdown_table(["tool", "version"], tool_rows),
            "",
            "## 3. Execution provenance",
            "",
            f"AWS Batch job `{execution_batch.get('job_id')}` completed with status `SUCCEEDED` on its sole allowed attempt on queue `{execution_queue.get('name')}` using job definition `{execution_definition.get('name')}:{execution_definition.get('revision')}`. The effective per-attempt timeout was {format_int(execution_timeout.get('attemptDurationSeconds'))} seconds with retry attempts fixed at {format_int(execution_retry.get('attempts'))}. The container reference was `{execution_container.get('image_reference')}` and its immutable runtime digest was `{image_digest}`.",
            "",
            f"The executed worker was read directly from the active ECS container, measured at {format_int(execution_worker.get('bytes'))} bytes with SHA-256 `{worker_sha}`, and frozen at exact private S3 VersionId `{execution_worker.get('executed_version_id')}` with a full-object checksum and expected SSE-KMS protection. The container-capture receipt SHA-256 is `{sha256(paths['executed_worker_freeze'])}` and that receipt is itself frozen at VersionId `{execution_worker.get('freeze_receipt_version_id')}`. The launch key was unversioned and later changed, so it is recorded only as the command source—not as executed-byte provenance. The CloudWatch log stream was `{execution_batch.get('log_group')}/{execution_batch.get('log_stream')}`.",
            "",
            "Exact Batch command:",
            "",
            "```text",
            command_text,
            "```",
            "",
            "## 4. Alignment QC",
            "",
            markdown_table(["role", "total reads", "mapped reads", "mapped", "duplicate reads", "duplicate fraction", "BAM bytes"], alignment_report_rows),
            "",
            "Both alignment rows are `passed`. These are structural and descriptive QC metrics, not an HRD performance validation.",
            "",
            "## 5. Contamination",
            "",
            f"The matched-normal contamination estimate is `{contamination_rows[0]['contamination']}` ({100 * contamination:.6f}%) with reported error `{contamination_rows[0]['error']}` ({100 * contamination_error:.6f} percentage points). Pileup, segmentation, and orientation-bias artifacts are present. This estimate is not tumor purity and is not evidence for or against HRD.",
            "",
            "## 6. Genome-wide somatic variants and BRCA-region extraction",
            "",
            f"The indexed filtered VCF contains {format_int(filtered_total)} records: {format_int(filtered_pass)} PASS records, including {format_int(filtered_snvs)} PASS SNV records and {format_int(filtered_indels)} PASS indel records under bcftools record-type filters. The bounded BRCA-region extraction contains {format_int(len(brca_rows))} PASS rows ({brca_counts['BRCA1']} BRCA1-region and {brca_counts['BRCA2']} BRCA2-region).",
            "",
            "`PASS` is a caller filter state. BRCA rows are region-only and require build-matched consequence annotation and review. This report makes no pathogenicity, origin, phase, second-hit, LOH, or biallelic statement.",
            "",
            "## 7. SBS96 input",
            "",
            f"The SBS96 matrix has {format_int(len(sbs_rows))} canonical channels summing to {format_int(usable_snv_records)} usable PASS SNV alleles; {format_int(skipped_snv_records)} SNV records/alleles were skipped by the context rules. Assignment readiness is `{signatures.get('sigprofiler_assignment_status')}`. SBS3 remains `no_call` because signature assignment and threshold policy are not validated and locked.",
            "",
            "A separate verifier re-read the indexed PASS-SNV VCF against the exact indexed FASTA, confirmed VCF/reference compatibility, and reproduced all 96 matrix channels exactly. This establishes matrix derivation consistency; it does not validate signature attribution or an SBS3 threshold.",
            "",
            "## 8. Coverage-CNV proxy",
            "",
            f"The normalized table has {format_int(cnv['bin_count'])} 5 Mb bins: {format_int(cnv['relative_gain_bins'])} relative-gain, {format_int(cnv['relative_loss_bins'])} relative-loss, and {format_int(neutral_bins)} neutral-or-low-signal bins. Median raw tumor/normal log2 ratio was `{cnv.get('median_raw_log2_tumor_normal')}` before centering.",
            "",
            "These bins are not segmented, allele-specific total/minor copy number, LOH, purity/ploidy, or scarHRD input. No chromosome- or gene-level copy-number conclusion is authorized.",
            "",
            "## 9. BAM-derived SV evidence",
            "",
            markdown_table(["role", "supplementary", "discordant mapped pairs", "interchromosomal pairs", "large-insert pairs"], sv_report_rows),
            "",
            "These counts are `partial_evidence` only. They are not breakpoint calls, a production breakend-SV VCF/BEDPE, or valid CHORD inputs.",
            "",
            "## 10. Comparison with deterministic early-look baseline",
            "",
            markdown_table(["metric", "early look", "full run", "delta"], comparison_rows),
            "",
            f"The early look used a targeted callset; its {format_int(early_total_pass)} total targeted PASS {'record' if early_total_pass == 1 else 'records'} are not directly comparable with the genome-wide PASS total. The BRCA-region, contamination, alignment, and coverage metrics are compared because both bundles expose like-for-like fields. A difference is descriptive and must be investigated before interpretation.",
            "",
            "## 11. Readiness states",
            "",
            markdown_table(["evidence surface", "state", "reason"], [[row["evidence_surface"], row["state"], row["reason"]] for row in output_readiness]),
            "",
            "## 12. Limitations",
            "",
            "- The filtered VCF and BRCA-region rows are not consequence- or pathogenicity-reviewed.",
            "- No germline-origin conclusion or biallelic HRR assessment is present.",
            "- Coverage bins lack allele-specific segmentation, LOH, purity, and ploidy.",
            "- SBS96 is an input matrix, not an SBS3 result.",
            "- BAM-derived SV counts are not a production breakend callset.",
            "- scarHRD, CHORD, HRDetect-style scoring, and overall HRD classification remain unsupported and `no_call`.",
            "- No treatment or clinical decision is authorized from this report.",
            "",
            "## 13. Exact next steps",
            "",
            "1. Annotate and manually review PASS HRR-region events; retain unreviewed records as unclassified.",
            "2. Generate validated allele-specific total/minor copy-number and LOH segments with a reviewed purity/ploidy solution.",
            "3. Generate and validate a production breakend-SV VCF/BEDPE with known-answer controls.",
            "4. Validate genome-wide signature assignment and lock SBS3 acceptance thresholds against known-answer samples.",
            "5. Only after their required inputs and validation gates pass, run independent scarHRD, CHORD, and HRDetect-style cross-checks; do not use agreement among unvalidated models as validation.",
            "6. Regenerate this deterministic report, investigate every early/full delta, and retain overall `no_call` unless the complete integration policy passes.",
            "",
            "## 14. Reproducibility",
            "",
            f"The generator executed {len(checks)} fail-closed evidence assertions against one stable local snapshot; all passed before any report output was published. `evidence_checks.json` records them, and `input_sha256.csv` records the snapshot SHA-256 of every consumed artifact and receipt.",
            "",
        ]
    )

    checks_payload = {
        "status": "passed",
        "report_status": "partial_evidence",
        "overall_hrd_status": "no_call",
        "run_id": summary.get("run_id"),
        "source_generated_at": summary.get("generated_at"),
        "checks": checks,
        "input_sha256": input_rows,
        "input_snapshot": {
            "receipt_sha256": sha256(paths["input_snapshot"]),
            "file_count": input_snapshot_file_count,
            "strategy": input_snapshot["snapshot_strategy"],
        },
        "stage_provenance": stage_provenance_evidence,
        "crosscheck_terminal": crosscheck_terminal_evidence,
        "early_full_comparison": comparison_rows,
    }
    review_summary = {
        "overall": {
            "evidence_status": "partial_evidence",
            "authorized_hrd_state": "no_call",
        },
        "custody": {
            "private_freeze_status": "passed",
            "frozen_object_count": len(freeze_rows),
            "report_consumed_versioned_artifacts": len(consumed_artifacts),
            "freeze_receipt_sha256": sha256(paths["final_freeze"]),
            "freeze_receipt_anchor_sha256": sha256(
                paths["final_freeze_anchor"]
            ),
            "freeze_receipt_version_id": final_freeze_evidence[
                "receipt_version_id"
            ],
            "executed_worker_freeze_receipt_sha256": sha256(paths["executed_worker_freeze"]),
            "executed_worker_freeze_receipt_upload_sha256": sha256(
                paths["executed_worker_freeze_upload"]
            ),
            "exact_materialization_receipt_sha256": sha256(paths["exact_materialization"]),
            "crosscheck_materialization_receipt_sha256": sha256(
                paths["crosscheck_materialization"]
            ),
            "crosscheck_materialization_capture_sha256": (
                crosscheck_terminal_evidence["capture_sha256"]
            ),
            "crosscheck_materialization_anchor_sha256": (
                crosscheck_terminal_evidence["anchor_sha256"]
            ),
            "staged_input_validation_download_receipt_sha256": (
                crosscheck_terminal_evidence["download_sha256"]
            ),
            "stage_provenance_receipt_sha256": sha256(
                paths["stage_provenance"]
            ),
            "stage_provenance_anchor_sha256": sha256(
                paths["stage_provenance_anchor"]
            ),
            "stage_provenance_receipt_version_id": stage_provenance_evidence[
                "receipt_version_id"
            ],
            "input_snapshot_receipt_sha256": sha256(paths["input_snapshot"]),
            "exact_kms_match": True,
        },
        "alignment": {
            role: {
                "total_reads": exact_alignment_by_role[role]["total_reads"],
                "mapped_reads": exact_alignment_by_role[role]["mapped_reads"],
                "duplicate_reads": exact_alignment_by_role[role]["duplicate_reads"],
            }
            for role in ("tumor", "normal")
        },
        "contamination": {
            "fraction": contamination,
            "reported_error": contamination_error,
            "boundary": "not_tumor_purity",
        },
        "somatic_variants": {
            "filtered_records": filtered_total,
            "pass_records": filtered_pass,
            "pass_snv_records": filtered_snvs,
            "pass_indel_records": filtered_indels,
            "bounded_brca_region_pass_records": len(brca_rows),
            "boundary": "region_only_unannotated",
        },
        "sbs96": {
            "canonical_channels": len(sbs_rows),
            "usable_pass_snv_alleles": usable_snv_records,
            "skipped_snv_alleles": skipped_snv_records,
            "matrix_equivalence": "passed",
            "sbs3_state": "no_call",
        },
        "coverage_cnv": {
            "bin_count": cnv["bin_count"],
            "relative_gain_bins": cnv["relative_gain_bins"],
            "relative_loss_bins": cnv["relative_loss_bins"],
            "neutral_or_low_signal_bins": neutral_bins,
            "boundary": "not_allele_specific",
        },
        "sv_evidence": {
            role: {
                "supplementary_alignments": sv_json_by_role[role]["supplementary_alignments"],
                "discordant_mapped_pairs": sv_json_by_role[role]["discordant_mapped_pairs"],
                "interchromosomal_pairs": sv_json_by_role[role]["interchromosomal_pairs"],
                "large_insert_pairs": sv_json_by_role[role]["large_insert_pairs"],
            }
            for role in ("tumor", "normal")
        },
        "readiness": {
            row["evidence_surface"]: row["state"] for row in output_readiness
        },
    }
    tokens = forbidden_tokens(
        summary,
        contamination_rows,
        sbs_rows,
        audit,
        list(args.forbidden_token),
        args.forbidden_tokens_file,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deterministic-full-", dir=str(output.parent)) as temporary:
        staging = Path(temporary)
        crosscheck_input_plans = build_crosscheck_input_plans(
            crosscheck_materialization,
            input_contract,
        )
        staged_paths = write_outputs(
            staging,
            report,
            output_readiness,
            checks_payload,
            crosscheck_input_plans,
            input_rows,
        )
        report_manifest = {
            "schema_version": 1,
            "method_id": "deterministic_full_wgs",
            "report_kind": "deterministic_baseline",
            "evidence_status": "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "support_sha256": {
                path.name: sha256(path)
                for path in staged_paths
                if path.name != "report.md"
            },
            "source_sha256": {
                row["input_id"]: row["sha256"] for row in input_rows
            },
            "report_sha256": sha256(staged_paths[0]),
            "review_summary": review_summary,
        }
        manifest_path = staging / "report_manifest.json"
        write_staged_json(manifest_path, report_manifest)
        require_report_manifest(staging)
        staged_paths.append(manifest_path)
        findings = scan_outputs(staged_paths, tokens)
        if findings:
            raise SystemExit("Fail-closed: sample/vendor identifier scan failed:\n" + "\n".join(f"{row['path']}: {row['token']}" for row in findings))
        try:
            install_packet_create_only(staged_paths, output)
        except ValueError as error:
            raise SystemExit("Fail-closed: " + str(error)) from error
    snapshot_guard.cleanup()
    print(f"Wrote deterministic full-WGS report: {output / 'report.md'}")
    print(f"Validated checks: {len(checks)}/{len(checks)} passed")
    print(f"Identifier scan: {len(tokens)} sensitive tokens checked; 0 findings")


if __name__ == "__main__":
    main()
