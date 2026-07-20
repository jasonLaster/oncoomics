#!/usr/bin/env python3
"""Build an isolated HCC1395 WGS HRD known-answer report and AI-input stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from forbidden_text import merge_forbidden_tokens
from build_ai_review_bundle import validate_report_manifest_support
from hrd_report_inventory import (
    HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
    HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS,
    inventory_payload,
    inventory_sha256,
)
from prepare_ai_review_run import MANIFEST_ARGUMENTS, require_prepared_run_support
from stage_ai_review_inputs import reviewer_inventory, validate_bundle

from diana_omics.commands.hrd_context import build_rosalind_hrd_packet as rosalind


HCC_SAMPLE_SET = "hcc1395_wgs"
METHOD_SPECS: tuple[dict[str, Any], ...] = (
    {
        "method_id": "sequenza_scarhrd",
        "title": "Sequenza to scarHRD known-answer cross-check",
        "evidence_status": "blocked",
        "available_evidence": "Tumor-normal 5 Mb coverage bins exist as a plumbing check.",
        "process": (
            "Generate allele-specific segments with total and minor copy number.",
            "Estimate and validate purity and ploidy.",
            "Run scarHRD to calculate HRD-LOH, TAI, LST, and their sum.",
        ),
        "missing_inputs": (
            "Validated allele-specific total and minor copy-number segments.",
            "Validated purity and ploidy estimates.",
            "A pinned Sequenza and scarHRD runtime plus known-answer thresholds.",
        ),
    },
    {
        "method_id": "sigprofiler_sbs3",
        "title": "SigProfiler SBS3 known-answer cross-check",
        "evidence_status": "partial_evidence",
        "available_evidence": "A real 96-channel matrix exists from 265 usable PASS SNVs.",
        "process": (
            "Run a pinned signature-assignment implementation on the mutation matrix.",
            "Record reconstruction quality and the SBS3 contribution.",
            "Apply the locked minimum-mutation and interpretation policy.",
        ),
        "missing_inputs": (
            "Completed signature assignment with reconstruction metrics.",
            "A locked minimum-mutation and SBS3 interpretation policy.",
            "Known-answer performance for the pinned implementation.",
        ),
    },
    {
        "method_id": "facets_scarhrd_blocked",
        "title": "FACETS to scarHRD known-answer cross-check",
        "evidence_status": "blocked",
        "available_evidence": "WGS alignment and coverage mechanics passed, but no FACETS fit exists.",
        "process": (
            "Run paired SNP pileup against an attested common-SNP resource.",
            "Fit FACETS purity, ploidy, and allele-specific segments.",
            "Validate and adapt the segments before running scarHRD.",
        ),
        "missing_inputs": (
            "A validated common-SNP resource and paired SNP pileup.",
            "A pinned and license-reviewed FACETS runtime.",
            "Validated FACETS fit criteria and scarHRD known-answer thresholds.",
        ),
    },
    {
        "method_id": "oncoanalyser_chord_blocked",
        "title": "Oncoanalyser CHORD known-answer cross-check",
        "evidence_status": "blocked",
        "available_evidence": "Small-variant output and BAM-derived SV counters exist; no production SV callset exists.",
        "process": (
            "Generate validated somatic SNV, indel, SV, and copy-number features.",
            "Run the pinned CHORD feature extractor and model.",
            "Apply known-answer QC and interpretation thresholds.",
        ),
        "missing_inputs": (
            "A production somatic SV VCF or BEDPE.",
            "Validated CNV context and completed CHORD feature extraction.",
            "A pinned runtime, parser, and known-answer calibration.",
        ),
    },
    {
        "method_id": "hrdetect_blocked",
        "title": "HRDetect known-answer cross-check",
        "evidence_status": "blocked",
        "available_evidence": "Partial substitution, copy-number, and mechanical SV evidence surfaces exist.",
        "process": (
            "Produce all six locked HRDetect feature classes.",
            "Apply the selected fixed model and calibration.",
            "Withhold classification unless local known-answer gates pass.",
        ),
        "missing_inputs": (
            "Validated substitution, indel, rearrangement, and CNV/LOH features.",
            "A validated microhomology feature path.",
            "A pinned implementation, calibration, threshold, and known-answer policy.",
        ),
    },
)

if tuple(spec["method_id"] for spec in METHOD_SPECS) != HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS[2:]:
    raise ValueError("HCC1395 method specifications drifted from the report inventory")


STACK_MANIFEST_KEYS = {
    "schema_version",
    "status",
    "run_id",
    "generated_at",
    "inventory",
    "inventory_sha256",
    "authorized_hrd_state",
    "source_reports",
    "ai_review_bundle_manifest",
    "ai_review_prepare_receipt",
    "ai_review_stage_receipt",
    "model_catalog_receipt_sha256",
    "models_invoked",
}
STACK_AI_REVIEW_OUTPUTS = {
    "ai_review_bundle_manifest": "ai-review/bundle/bundle_manifest.json",
    "ai_review_prepare_receipt": "ai-review/prepare_ai_review_run_receipt.json",
    "ai_review_stage_receipt": "ai-review/stage_ai_review_inputs_receipt.json",
}
AI_REVIEW_ENTRIES = {
    "bundle",
    "prepare_ai_review_run_receipt.json",
    "reviewer-inputs",
    "stage_ai_review_inputs_receipt.json",
}
REVIEWER_INPUT_ENTRIES = {"reviewer-a-input", "reviewer-b-input"}
STACK_ROOT_ENTRIES = {"ai-review", "source-reports", "stack_manifest.json"}
SOURCE_REPORT_ROOT_ENTRIES = {
    "deterministic_full_wgs",
    "rosalind",
    *HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS[2:],
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_stable_file(path: Path, label: str) -> bytes:
    data, identity = read_real_hash_input_once(path, label)
    digest = sha256_bytes(data)
    stable_data, stable_identity = read_real_hash_input_once(path, label)
    if (
        not data
        or stable_identity != identity
        or sha256_bytes(stable_data) != digest
    ):
        raise ValueError(f"{label} changed during read: {path}")
    return data


def read_real_hash_input_once(
    path: Path,
    label: str,
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    require_real_hash_input(path)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(f"{label} is not a regular file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read()
            after_read = os.fstat(handle.fileno())
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ValueError(f"{label} changed during read: {path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    require_real_hash_input(path)
    if (
        stat_identity(opened) != stat_identity(after_read)
        or stat_identity(after_read) != stat_identity(current)
    ):
        raise ValueError(f"{label} changed during read: {path}")
    return data, stat_identity(opened)


def stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def sha256(path: Path) -> str:
    return sha256_bytes(read_stable_file(path, f"{path.name} SHA-256 input"))


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_sha256 = sha256_bytes(payload)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
            require_installed_file(path, expected_sha256)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_json(path: Path, value: Any) -> None:
    write_bytes(path, json_bytes(value))


def write_text(path: Path, value: str) -> None:
    write_bytes(path, value.encode("utf-8"))


class DuplicateJsonObjectName(ValueError):
    """Raised when a JSON object repeats a name."""


def reject_duplicate_json_object_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonObjectName(key)
        result[key] = value
    return result


def read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a real non-empty file: {path}")
    try:
        value = json.loads(
            read_stable_file(path, label).decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonObjectName as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {label}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_hash_input(path: Path) -> None:
    label = f"{path.name} SHA-256 input"
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def require_installed_file(path: Path, expected_sha256: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"output changed during write: {path}")
    require_no_symlinked_ancestors(path, "output")
    if sha256(path) != expected_sha256:
        raise ValueError(f"output changed during write: {path}")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_safe_new_output(path: Path) -> Path:
    path = path.expanduser().absolute()
    require_no_symlinked_ancestors(path, "output")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or set(value) - set("0123456789abcdef")
    ):
        raise ValueError(f"{label} is not an exact SHA-256")
    return value


def require_nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def exact_schema_version(payload: Mapping[str, Any], expected: int = 1) -> bool:
    return (
        type(payload.get("schema_version")) is int
        and payload["schema_version"] == expected
    )


def require_object_rows(value: Any, label: str) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(row, dict) for row in value)
    ):
        raise ValueError(f"{label} must be a non-empty list of JSON objects")
    return value


def require_relative_file(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{label} path is not exact")
    path = Path(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} path is not a local relative file")
    return root / path


def require_bound_file(root: Path, details: Any, expected: str, label: str) -> Path:
    if not isinstance(details, dict) or set(details) != {"path", "sha256"}:
        raise ValueError(f"HCC1395 stack manifest {label} binding is not exact")
    path = require_relative_file(root, details.get("path"), label)
    digest = require_sha256(details.get("sha256"), f"{label} SHA-256")
    if str(path.relative_to(root)) != expected:
        raise ValueError(f"HCC1395 stack manifest {label} path is stale")
    if sha256(path) != digest:
        raise ValueError(f"HCC1395 stack manifest is stale for {label}")
    return path


def require_directory_inventory(
    path: Path,
    expected: set[str],
    label: str,
) -> None:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} is not a real directory: {path}")
    observed = {child.name for child in path.iterdir()}
    if observed != expected:
        raise ValueError(
            f"{label} inventory is not exact; "
            f"expected={sorted(expected)!r} observed={sorted(observed)!r}"
        )


def expected_artifact_source_sha256(artifact_root: Path) -> dict[str, str]:
    return {
        f"source_artifact_{index:03d}": sha256(path)
        for index, path in enumerate(artifact_paths(artifact_root), 1)
    }


def require_exact_source_sha256(
    manifest: Mapping[str, Any],
    expected: Mapping[str, str],
    label: str,
) -> None:
    if manifest.get("source_sha256") != dict(expected):
        raise ValueError(f"{label} source hashes are stale")


def require_ai_review_inputs(ai_review: Path) -> None:
    require_directory_inventory(ai_review, AI_REVIEW_ENTRIES, "HCC1395 AI review")
    require_directory_inventory(
        ai_review / "reviewer-inputs",
        REVIEWER_INPUT_ENTRIES,
        "HCC1395 reviewer-input root",
    )
    hashes = validate_bundle(ai_review / "bundle")
    reviewer_inventory(
        ai_review / "reviewer-inputs" / "reviewer-a-input",
        "A",
        hashes,
    )
    reviewer_inventory(
        ai_review / "reviewer-inputs" / "reviewer-b-input",
        "B",
        hashes,
    )


def require_source_report(
    root: Path,
    method_id: str,
    details: Any,
) -> Path:
    if not isinstance(details, dict) or set(details) != {"manifest", "manifest_sha256"}:
        raise ValueError(f"HCC1395 {method_id} source report binding is not exact")
    path = require_relative_file(
        root,
        details.get("manifest"),
        f"HCC1395 {method_id} report manifest",
    )
    if path.name != "report_manifest.json":
        raise ValueError(f"HCC1395 {method_id} source report path is not a manifest")
    digest = require_sha256(
        details.get("manifest_sha256"),
        f"HCC1395 {method_id} report manifest SHA-256",
    )
    if sha256(path) != digest:
        raise ValueError(f"HCC1395 stack manifest is stale for {method_id}")
    manifest = read_object(path, f"HCC1395 {method_id} report manifest")
    validate_report_manifest_support(path.parent, manifest, method_id)
    report_sha256 = require_sha256(
        manifest.get("report_sha256"),
        f"HCC1395 {method_id} report SHA-256",
    )
    if sha256(path.parent / "report.md") != report_sha256:
        raise ValueError(f"HCC1395 {method_id} report manifest is stale for report.md")
    return path


def require_stack_manifest(
    root: Path,
    catalog: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    require_directory_inventory(root, STACK_ROOT_ENTRIES, "HCC1395 stack")
    require_directory_inventory(
        root / "source-reports",
        SOURCE_REPORT_ROOT_ENTRIES,
        "HCC1395 source-report root",
    )
    manifest = read_object(root / "stack_manifest.json", "HCC1395 stack manifest")
    if (
        set(manifest) != STACK_MANIFEST_KEYS
        or not exact_schema_version(manifest)
        or manifest.get("status") != "passed"
        or manifest.get("authorized_hrd_state") != "no_call"
        or manifest.get("models_invoked") is not False
        or manifest.get("inventory")
        != inventory_payload(HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID)
        or manifest.get("inventory_sha256")
        != inventory_sha256(HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID)
    ):
        raise ValueError("HCC1395 stack manifest envelope is not exact")

    source_reports = manifest.get("source_reports")
    if (
        not isinstance(source_reports, dict)
        or set(source_reports) != set(HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS)
    ):
        raise ValueError("HCC1395 stack source reports are not exact")

    report_manifests = {
        method_id: read_object(
            require_source_report(root, method_id, source_reports[method_id]),
            f"HCC1395 {method_id} report manifest",
        )
        for method_id in HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS
    }

    artifact_source_sha256 = expected_artifact_source_sha256(artifact_root)
    for method_id in ("deterministic_full_wgs", "rosalind_hcc1395_wgs"):
        require_exact_source_sha256(
            report_manifests[method_id],
            artifact_source_sha256,
            f"HCC1395 {method_id}",
        )

    upstream_source_sha256 = {
        f"{method_id}_report_manifest": source_reports[method_id]["manifest_sha256"]
        for method_id in HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS[:2]
    }
    for spec in METHOD_SPECS:
        method_id = str(spec["method_id"])
        require_exact_source_sha256(
            report_manifests[method_id],
            {
                "generator": sha256(Path(__file__).resolve()),
                **upstream_source_sha256,
            },
            f"HCC1395 {method_id}",
        )

    for label, expected in STACK_AI_REVIEW_OUTPUTS.items():
        require_bound_file(root, manifest.get(label), expected, label)
    require_ai_review_inputs(root / "ai-review")
    require_prepared_run_support(root / "ai-review")

    expected_catalog_sha256 = require_sha256(
        manifest.get("model_catalog_receipt_sha256"),
        "HCC1395 model catalog receipt SHA-256",
    )
    if sha256(catalog) != expected_catalog_sha256:
        raise ValueError("HCC1395 stack model catalog receipt SHA-256 is stale")

    return manifest


@contextmanager
def environment(values: Mapping[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def artifact_paths(artifact_root: Path) -> list[Path]:
    paths = [artifact_root / relative for relative in rosalind.PACKET_SPECS[HCC_SAMPLE_SET].artifacts]
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"missing HCC1395 source artifact: {path}")
    return paths


def build_deterministic_packet(
    artifact_root: Path,
    output: Path,
    generated_at: str,
    run_id: str,
) -> Path:
    inputs = artifact_paths(artifact_root)
    summary = read_object(
        artifact_root / "results/phase3_wgs_smoke/phase3_wgs_summary.json",
        "Phase 3 WGS summary",
    )
    sv = read_object(
        artifact_root / "results/phase3_wgs_smoke/sv_evidence_summary.json",
        "SV evidence summary",
    )
    if not (
        summary.get("status") == "passed"
        and summary.get("fullSourceFastqs") is True
        and summary.get("bamValidationStatus") == "passed"
        and summary.get("mutect2Status") == "passed"
    ):
        raise ValueError("HCC1395 deterministic known-answer mechanics are not passed")
    sv_rows = require_object_rows(sv.get("rows"), "SV evidence rows")
    discordant_pairs = sum(
        require_nonnegative_int(
            row.get("discordant_mapped_pairs"),
            "SV discordant_mapped_pairs",
        )
        for row in sv_rows
        if isinstance(row, dict)
    )
    observations = {
        "full_source_wgs": True,
        "read_pairs_per_end": require_nonnegative_int(
            summary.get("readPairsPerEnd"),
            "readPairsPerEnd",
        ),
        "bam_validation": str(summary.get("bamValidationStatus", "missing")),
        "truth_depth_eligible_variants": require_nonnegative_int(
            summary.get("truthVariantsDepthEligible"),
            "truthVariantsDepthEligible",
        ),
        "pass_records_in_intervals": require_nonnegative_int(
            summary.get("passRecordsInIntervals"),
            "passRecordsInIntervals",
        ),
        "exact_pass_truth_matches": require_nonnegative_int(
            summary.get("exactPassTruthMatches"),
            "exactPassTruthMatches",
        ),
        "coverage_bin_count": require_nonnegative_int(
            summary.get("coverageCnvBins"),
            "coverageCnvBins",
        ),
        "sbs96_usable_snv_count": require_nonnegative_int(
            summary.get("sbs96UsableSnvRecords"),
            "sbs96UsableSnvRecords",
        ),
        "sv_evidence_row_count": len(sv_rows),
        "discordant_mapped_pair_count": discordant_pairs,
    }
    limitations = [
        "Coverage bins are not allele-specific CNV/LOH segments.",
        "BAM-derived SV counters are not a production somatic SV VCF or BEDPE.",
        "The SBS96 matrix is input evidence; signature assignment did not run.",
        "No scalar or categorical HRD classification is authorized.",
    ]
    report = "\n".join(
        [
            "# HCC1395 WGS deterministic known-answer report",
            "",
            f"- run_id: `{run_id}`",
            "- evidence_status: `partial_evidence`",
            "- authorized_hrd_state: `no_call`",
            "",
            "## Process",
            "",
            "The public tumor-normal WGS rehearsal aligned the full FASTQ inputs, validated the BAMs, ran matched-normal Mutect2 and filtering, compared calls in truth intervals, generated 5 Mb coverage bins, built a 96-channel mutation matrix, and counted BAM-derived SV evidence.",
            "",
            "## Results",
            "",
            *[f"- {key}: `{value}`" for key, value in observations.items()],
            "",
            "## Limitations",
            "",
            *[f"- {value}" for value in limitations],
            "",
            "## Authorized conclusion",
            "",
            "The deterministic mechanics passed for this public known-answer rehearsal. HRD interpretation remains `no_call` with `partial_evidence`.",
            "",
        ]
    )
    output.mkdir(parents=True)
    report_path = output / "report.md"
    write_text(report_path, report)
    support = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": generated_at,
        "observations": observations,
        "limitations": limitations,
    }
    support_path = output / "deterministic_summary.json"
    write_json(support_path, support)
    manifest = {
        "schema_version": 1,
        "method_id": "deterministic_full_wgs",
        "report_kind": "hcc1395_wgs_known_answer",
        "evidence_status": "partial_evidence",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "classification_qc_status": "not_applicable",
        "report_sha256": sha256(report_path),
        "support_sha256": {"deterministic_summary.json": sha256(support_path)},
        "source_sha256": {
            f"source_artifact_{index:03d}": sha256(path)
            for index, path in enumerate(inputs, 1)
        },
        "review_summary": {
            "overall": {
                "evidence_status": "partial_evidence",
                "authorized_hrd_state": "no_call",
            },
            "scope": "public_known_answer_wgs_rehearsal",
            "process": [
                "full-source tumor-normal WGS alignment and BAM validation",
                "matched-normal small-variant calling and truth-interval comparison",
                "coverage-bin, SBS96-input, and BAM-derived SV evidence generation",
            ],
            "observations": observations,
            "limitations": limitations,
        },
    }
    manifest_path = output / "report_manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path


def build_method_packet(
    spec: Mapping[str, Any],
    output: Path,
    generated_at: str,
    run_id: str,
    upstream_manifest_hashes: Mapping[str, str],
) -> Path:
    output.mkdir(parents=True)
    process = list(spec["process"])
    missing_inputs = list(spec["missing_inputs"])
    report = "\n".join(
        [
            f"# {spec['title']}",
            "",
            f"- run_id: `{run_id}`",
            "- execution_status: `not_run`",
            f"- evidence_status: `{spec['evidence_status']}`",
            "- authorized_hrd_state: `no_call`",
            "",
            "## Process — not executed",
            "",
            *[f"- {value}" for value in process],
            "",
            "## Available evidence",
            "",
            str(spec["available_evidence"]),
            "",
            "## Missing inputs and validation",
            "",
            *[f"- {value}" for value in missing_inputs],
            "",
            "## Result",
            "",
            "The method was not run. No score, probability, category, or biological classification was generated.",
            "",
            "## Authorized conclusion",
            "",
            "The method remains `no_call`; the available evidence cannot be rewritten as an HRD-negative result.",
            "",
        ]
    )
    report_path = output / "report.md"
    write_text(report_path, report)
    method_spec = {
        "schema_version": 1,
        "method_id": spec["method_id"],
        "run_id": run_id,
        "generated_at": generated_at,
        "execution_status": "not_run",
        "evidence_status": spec["evidence_status"],
        "authorized_hrd_state": "no_call",
        "available_evidence": spec["available_evidence"],
        "process": process,
        "missing_inputs": missing_inputs,
    }
    spec_path = output / "method_spec.json"
    write_json(spec_path, method_spec)
    manifest = {
        "schema_version": 1,
        "method_id": spec["method_id"],
        "report_kind": "public_known_answer_method_no_call",
        "evidence_status": spec["evidence_status"],
        "execution_status": "not_run",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "classification_qc_status": "not_applicable",
        "report_sha256": sha256(report_path),
        "support_sha256": {"method_spec.json": sha256(spec_path)},
        "source_sha256": {
            "generator": sha256(Path(__file__).resolve()),
            **{
                f"{method_id}_report_manifest": digest
                for method_id, digest in upstream_manifest_hashes.items()
            },
        },
        "review_summary": {
            "overall": {
                "evidence_status": spec["evidence_status"],
                "authorized_hrd_state": "no_call",
            },
            "execution_status": "not_run",
            "available_evidence": spec["available_evidence"],
            "intended_process": process,
            "missing_inputs": missing_inputs,
            "result": "No method output was generated; interpretation remains no_call.",
        },
    }
    manifest_path = output / "report_manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path


def run_ai_review_prepare(
    manifests: Sequence[Path],
    output: Path,
    args: argparse.Namespace,
) -> None:
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "prepare_ai_review_run.py"),
        "--inventory-id",
        HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
    ]
    for argument, manifest in zip(MANIFEST_ARGUMENTS, manifests):
        command.extend(["--" + argument.replace("_", "-"), str(manifest)])
    command.extend(
        [
            token
            for method_id, manifest in zip(HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS, manifests)
            for token in (
                "--expected-source-manifest-sha256",
                f"{method_id}={sha256(manifest)}",
            )
        ]
    )
    command.extend(
        [
            "--output-dir",
            str(output),
            "--subject-alias",
            args.subject_alias,
            "--reviewer-a-provider",
            args.reviewer_a_provider,
            "--reviewer-a-model-id",
            args.reviewer_a_model_id,
            "--reviewer-b-provider",
            args.reviewer_b_provider,
            "--reviewer-b-model-id",
            args.reviewer_b_model_id,
            "--model-catalog-verified-at",
            args.model_catalog_verified_at,
            "--model-catalog-receipt",
            str(args.model_catalog_receipt),
        ]
    )
    for token in merge_forbidden_tokens(("DirectIdentifier", *args.forbidden_token)):
        command.extend(["--forbidden-token", token])
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("\n".join(value for value in (result.stdout, result.stderr) if value).strip())


def build(args: argparse.Namespace) -> dict[str, Any]:
    artifact_root = args.artifact_root.expanduser().resolve()
    artifact_paths(artifact_root)
    catalog = args.model_catalog_receipt.expanduser().resolve()
    read_object(catalog, "model catalog receipt")
    output = require_safe_new_output(args.output_dir)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    ).resolve()
    installed = False
    try:
        report_root = staging / "source-reports"
        deterministic_manifest = build_deterministic_packet(
            artifact_root,
            report_root / "deterministic_full_wgs",
            args.generated_at,
            args.run_id,
        )
        rosalind_root = report_root / "rosalind"
        with environment(
            {
                "ROSALIND_HRD_ARTIFACT_ROOT": str(artifact_root),
                "ROSALIND_HRD_OUTPUT_ROOT": str(rosalind_root),
            }
        ):
            rosalind_summary = rosalind.write_packet(
                rosalind.PACKET_SPECS[HCC_SAMPLE_SET],
                args.run_id,
            )
        rosalind_manifest = Path(rosalind_summary["reportManifest"])
        rosalind_payload = read_object(rosalind_manifest, "Rosalind report manifest")
        if rosalind_payload.get("method_id") != "rosalind_hcc1395_wgs":
            raise ValueError("Rosalind HCC1395 packet was relabeled")

        upstream = {
            "deterministic_full_wgs": sha256(deterministic_manifest),
            "rosalind_hcc1395_wgs": sha256(rosalind_manifest),
        }
        method_manifests = [
            build_method_packet(
                spec,
                report_root / str(spec["method_id"]),
                args.generated_at,
                args.run_id,
                upstream,
            )
            for spec in METHOD_SPECS
        ]
        manifests = [deterministic_manifest, rosalind_manifest, *method_manifests]
        ai_review = staging / "ai-review"
        run_ai_review_prepare(manifests, ai_review, args)

        stack_manifest = {
            "schema_version": 1,
            "status": "passed",
            "run_id": args.run_id,
            "generated_at": args.generated_at,
            "inventory": inventory_payload(HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID),
            "inventory_sha256": inventory_sha256(HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID),
            "authorized_hrd_state": "no_call",
            "source_reports": {
                method_id: {
                    "manifest": str(manifest.relative_to(staging)),
                    "manifest_sha256": sha256(manifest),
                }
                for method_id, manifest in zip(HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS, manifests)
            },
            "ai_review_bundle_manifest": {
                "path": "ai-review/bundle/bundle_manifest.json",
                "sha256": sha256(ai_review / "bundle/bundle_manifest.json"),
            },
            "ai_review_prepare_receipt": {
                "path": "ai-review/prepare_ai_review_run_receipt.json",
                "sha256": sha256(ai_review / "prepare_ai_review_run_receipt.json"),
            },
            "ai_review_stage_receipt": {
                "path": "ai-review/stage_ai_review_inputs_receipt.json",
                "sha256": sha256(ai_review / "stage_ai_review_inputs_receipt.json"),
            },
            "model_catalog_receipt_sha256": sha256(catalog),
            "models_invoked": False,
        }
        write_json(staging / "stack_manifest.json", stack_manifest)
        require_stack_manifest(staging, catalog, artifact_root)
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"output appeared during build: {output}")
        try:
            staging.rename(output)
            fsync_directory(output.parent)
            require_stack_manifest(output, catalog, artifact_root)
        except Exception:
            if output.is_dir() and not output.is_symlink():
                shutil.rmtree(output)
            raise
        installed = True
        return stack_manifest
    finally:
        if not installed and staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--model-catalog-receipt", required=True, type=Path)
    parser.add_argument("--model-catalog-verified-at", required=True)
    parser.add_argument("--reviewer-a-provider", required=True)
    parser.add_argument("--reviewer-a-model-id", required=True)
    parser.add_argument("--reviewer-b-provider", required=True)
    parser.add_argument("--reviewer-b-model-id", required=True)
    parser.add_argument("--subject-alias", default="subject99")
    parser.add_argument("--forbidden-token", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        manifest = build(args)
    except (FileExistsError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
