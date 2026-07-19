#!/usr/bin/env python3
"""Build an isolated HCC1395 WGS HRD known-answer report and AI-input stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from forbidden_text import merge_forbidden_tokens
from hrd_report_inventory import (
    HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
    HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS,
    inventory_payload,
    inventory_sha256,
)
from prepare_ai_review_run import MANIFEST_ARGUMENTS

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


def sha256(path: Path) -> str:
    require_real_hash_input(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
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
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonObjectName as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
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


def require_safe_new_output(path: Path) -> Path:
    path = path.expanduser().absolute()
    require_no_symlinked_ancestors(path, "output")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
    sv_rows = sv.get("rows") if isinstance(sv.get("rows"), list) else []
    discordant_pairs = sum(
        int(row.get("discordant_mapped_pairs", 0) or 0)
        for row in sv_rows
        if isinstance(row, dict)
    )
    observations = {
        "full_source_wgs": True,
        "read_pairs_per_end": int(summary.get("readPairsPerEnd", 0)),
        "bam_validation": str(summary.get("bamValidationStatus", "missing")),
        "truth_depth_eligible_variants": int(summary.get("truthVariantsDepthEligible", 0)),
        "pass_records_in_intervals": int(summary.get("passRecordsInIntervals", 0)),
        "exact_pass_truth_matches": int(summary.get("exactPassTruthMatches", 0)),
        "coverage_bin_count": int(summary.get("coverageCnvBins", 0)),
        "sbs96_usable_snv_count": int(summary.get("sbs96UsableSnvRecords", 0)),
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
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"output appeared during build: {output}")
        staging.rename(output)
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
