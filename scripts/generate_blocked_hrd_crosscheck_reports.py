#!/usr/bin/env python3
"""Generate alias-only blocked HRD cross-check reports.

These packets are intentionally descriptive: they document routes that must not
run yet, keep their evidence state blocked, and provide the same three-file
packet inventory used by executable Sequenza / SigProfiler cross-checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from build_ai_review_bundle import (
    DuplicateJsonKeyError,
    reject_duplicate_json_object_names,
)
from hrd_report_inventory import (
    BLOCKED_CROSSCHECK_METHOD_IDS,
    EXECUTABLE_CROSSCHECK_METHOD_IDS,
    REQUIRED_METHOD_IDS,
)

STATUS = {
    "execution_status": "not_run",
    "evidence_status": "blocked",
    "interpretation_status": "no_call",
    "classification_authorization": "none",
    "patient_result": "none",
}
BLOCKED_REPORT_MANIFEST_KEYS = {
    "schema_version",
    "method_id",
    "report_kind",
    "generated_at",
    *STATUS,
    "authorized_hrd_state",
    "classification_authorized",
    "classification_qc_status",
    "explicit_no_patient_result",
    "alias_scope",
    "intended_computation",
    "prerequisites",
    "blockers",
    "next_gate",
    "sources",
    "run_id",
    "source_report_binding_scope",
    "review_summary",
    "source_sha256",
    "support_sha256",
    "report_sha256",
}

# Keep formatter noise out of this static prose table so diffs only show
# substantive route-contract changes.
# fmt: off
METHODS: tuple[dict[str, Any], ...] = (
    {
        "method_id": "facets_scarhrd_blocked",
        "directory": "facets_scarhrd_blocked",
        "title": "FACETS to scarHRD",
        "alias_scope": ["subject01_tumor", "subject01_normal"],
        "intended_computation": [
            "Run snp-pileup against paired tumor and normal alignments using an "
            "attested common-polymorphic-SNP resource.",
            "Run the FACETS two-pass fit to estimate purity, ploidy, and EM "
            "allele-specific copy-number segments.",
            "Structurally validate total and minor copy number before adapting "
            "segments to the explicit scarHRD input schema.",
            "Compute HRD-LOH, TAI, LST, and their sum with scarHRD using the "
            "declared GRCh38 reference.",
        ],
        "prerequisites": [
            "Final alias-only tumor and normal BAMs plus BAI indexes, each bound "
            "to SHA-256.",
            "Exact GRCh38 FASTA, FAI, and sequence dictionary identities with "
            "matching contig style across every input.",
            "A common-polymorphic-SNP VCF plus index selected for the same GRCh38 "
            "build and bound to SHA-256.",
            "A linux/amd64 FACETS, facets-suite, snp-pileup, and scarHRD runtime "
            "pinned by immutable image digest with SBOM and provenance.",
            "Passed structural gates for SNP evidence, chromosome representation, "
            "finite purity and ploidy, integer allele-specific copy number, and "
            "critical FACETS flags.",
            "A known-answer validation set and locked QC and interpretation "
            "thresholds approved before any result is classified.",
        ],
        "blockers": [
            "The active method contract does not include an attested "
            "common-polymorphic-SNP VCF and index or an enabled FACETS route.",
            "The FACETS image has not been built, pushed, or attested by "
            "immutable digest, and the required x86 execution runtime is not "
            "applied.",
            "The snp-pileup source checkout has no detected license file, so "
            "execution is blocked until an explicit license determination is "
            "recorded.",
            "Known-answer performance, fit acceptance criteria, QC limits, and "
            "interpretation thresholds are not locked.",
        ],
        "next_gate": (
            "Resolve the snp-pileup license review; select, hash, and "
            "reference-attest the common-SNP VCF; add the alias-only FACETS "
            "route; publish the digest-pinned x86 image with SBOM and "
            "provenance; then pass structural and known-answer validation before "
            "authorizing interpretation."
        ),
        "sources": [
            {
                "label": "FACETS v0.6.2",
                "revision": "f3c93ee65b09fc57aaed22a2eb9faa05586a9dc0",
                "url": (
                    "https://github.com/mskcc/facets/tree/"
                    "f3c93ee65b09fc57aaed22a2eb9faa05586a9dc0"
                ),
            },
            {
                "label": "facets-suite 2.0.10",
                "revision": "7d54d0f67e3136bd60d94ad810a9c855df113096",
                "url": (
                    "https://github.com/mskcc/facets-suite/tree/"
                    "7d54d0f67e3136bd60d94ad810a9c855df113096"
                ),
            },
            {
                "label": "scarHRD 0.1.1 source",
                "revision": "c98f8bc42ed0810393a98677d415114360616725",
                "url": (
                    "https://github.com/sztup/scarHRD/tree/"
                    "c98f8bc42ed0810393a98677d415114360616725"
                ),
            },
            {
                "label": "snp-pileup source",
                "revision": "9e793b2da3a5094015d3c3b9b6d3cfe18282867d",
                "url": (
                    "https://github.com/mskcc/htstools/tree/"
                    "9e793b2da3a5094015d3c3b9b6d3cfe18282867d"
                ),
            },
        ],
    },
    {
        "method_id": "oncoanalyser_chord_blocked",
        "directory": "oncoanalyser_chord_blocked",
        "title": "Oncoanalyser and CHORD",
        "alias_scope": ["subject01_tumor", "subject01_normal"],
        "intended_computation": [
            "Run nf-core/oncoanalyser in WGTS mode against the selected "
            "GRCh38_hmf resource bundle.",
            "Independently align and process the paired WGS lanes, call small "
            "variants with SAGE, structural variants with ESVEE, and "
            "allele-specific copy number, purity, and ploidy with AMBER, "
            "COBALT, and PURPLE.",
            "Give CHORD the PURPLE somatic small-variant VCF, PURPLE "
            "structural-variant VCF, and exact reference resources.",
            "Compute SNV, indel, and structural-variant contexts and the CHORD "
            "probability and category fields, subject to CHORD QC and Diana "
            "validation policy.",
        ],
        "prerequisites": [
            "Original checksummed paired tumor and normal FASTQ lanes with an "
            "alias-only lane mapping and samplesheet.",
            "Exact GRCh38_hmf reference and WiGiTS resource identities, with "
            "every file bound to SHA-256.",
            "An nf-core/oncoanalyser commit and compatible Nextflow version "
            "pinned in the route contract.",
            "Every workflow process image mirrored and pinned by immutable "
            "digest with license review, SBOM, and provenance.",
            "A tested linux/amd64 Nextflow controller and Batch runtime plus a "
            "durable, validated CHORD output parser.",
            "Passed dry-run and known-answer validation with locked QC, "
            "classification, and change-control policy.",
        ],
        "blockers": [
            "The active contract contains no original FASTQ lane hashes or "
            "alias-only lane mapping for this route.",
            "The HMF reference and resource identities are not frozen.",
            "The workflow process images are tag-based and unmirrored rather than "
            "digest-attested.",
            "The x86 controller and Batch runtime are not applied and tested.",
            "No durable CHORD result parser is present, and license and "
            "intended-use review is incomplete.",
            "Known-answer performance, QC limits, interpretation thresholds, and "
            "change-control authorization are not locked.",
        ],
        "next_gate": (
            "Reconcile and hash the alias-only FASTQ lanes and HMF resources; "
            "mirror every process image by digest with SBOM and provenance; apply "
            "and test the x86 Nextflow runtime and CHORD parser; then pass "
            "dry-run and known-answer validation before paired-WGS execution or "
            "interpretation."
        ),
        "sources": [
            {
                "label": "nf-core/oncoanalyser 2.3.0",
                "revision": "234fd82acc16a3beb01bf301900d83346b6ec812",
                "url": (
                    "https://github.com/nf-core/oncoanalyser/tree/"
                    "234fd82acc16a3beb01bf301900d83346b6ec812"
                ),
            },
            {
                "label": "oncoanalyser usage contract",
                "revision": "234fd82acc16a3beb01bf301900d83346b6ec812",
                "url": (
                    "https://github.com/nf-core/oncoanalyser/blob/"
                    "234fd82acc16a3beb01bf301900d83346b6ec812/docs/usage.md"
                ),
            },
            {
                "label": "oncoanalyser CHORD module",
                "revision": "234fd82acc16a3beb01bf301900d83346b6ec812",
                "url": (
                    "https://github.com/nf-core/oncoanalyser/blob/"
                    "234fd82acc16a3beb01bf301900d83346b6ec812/modules/local/"
                    "chord/main.nf"
                ),
            },
            {
                "label": "HMF CHORD 2.1.2 source",
                "revision": "ecb124834636dc722a2450375fa6126bc86689f9",
                "url": (
                    "https://github.com/hartwigmedical/hmftools/tree/"
                    "ecb124834636dc722a2450375fa6126bc86689f9/chord"
                ),
            },
        ],
    },
    {
        "method_id": "hrdetect_blocked",
        "directory": "hrdetect_blocked",
        "title": "HRDetect",
        "alias_scope": ["subject01_tumor", "subject01_normal"],
        "intended_computation": [
            "Use a formally selected and pinned GRCh38 HRDetect implementation "
            "with validated somatic small-variant, structural-variant, and "
            "allele-specific copy-number inputs.",
            "Compute the six HRDetect features: microhomology-mediated deletion "
            "proportion, LOH/TAI/LST scar score, SBS3, SBS8, rearrangement "
            "signature 3, and rearrangement signature 5.",
            "Apply the selected fixed model and calibration policy to produce a "
            "probability, while withholding classification unless local "
            "validation and authorization gates pass.",
        ],
        "prerequisites": [
            "A formally selected implementation, model, reference build, "
            "signature definitions, calibration cohort, and reporting threshold.",
            "An alias-only production somatic SNV and indel VCF plus index, a "
            "production structural-variant VCF, and validated allele-specific "
            "segmentation and LOH evidence.",
            "Exact GRCh38 reference and signature resource identities bound to "
            "SHA-256.",
            "A validated microhomology feature path and all six model features "
            "produced under one locked contract.",
            "Every transitive runtime and data dependency pinned by immutable "
            "digest with license and intended-use review, SBOM, and provenance.",
            "Known-answer reproduction and locked QC, calibration, threshold, and "
            "change-control authorization.",
        ],
        "blockers": [
            "No HRDetect route, contract, digest-pinned runtime, or validated "
            "parser has been selected.",
            "The required production structural-variant, allele-specific LOH and "
            "scar, and microhomology feature paths are not available under an "
            "approved contract.",
            "The candidate OICR workflow is GRCh38-capable but depends on "
            "site-specific modules and paths, is not digest-portable, and has no "
            "detected repository license.",
            "The public GPL-licensed implementation hard-codes hg19 and "
            "cohort-standardizes features, so it is not a reproducible GRCh38 "
            "single-sample path.",
            "No known-answer calibration, local performance limits, threshold, "
            "intended-use determination, or classification authorization is "
            "locked.",
        ],
        "next_gate": (
            "Select the implementation, model, signature versions, reference, and "
            "calibration cohort; resolve license and intended use; pin every "
            "runtime and data dependency; generate validated SNV, indel, SV, "
            "copy-number, LOH, and microhomology inputs; then reproduce "
            "known-answer performance and lock the reporting threshold before "
            "execution or interpretation."
        ),
        "sources": [
            {
                "label": "OICR hrDetect 1.8.0",
                "revision": "5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35",
                "url": (
                    "https://github.com/oicr-gsi/hrDetect/tree/"
                    "5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35"
                ),
            },
            {
                "label": "OICR hrDetect WDL",
                "revision": "5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35",
                "url": (
                    "https://github.com/oicr-gsi/hrDetect/blob/"
                    "5d0c0e10f3e2a6c536fbd54acd1d44a36d05ab35/hrDetect.wdl"
                ),
            },
            {
                "label": "Public HRDetect pipeline",
                "revision": "32e609f0479780e2072bb4b0c39190660d7eb634",
                "url": (
                    "https://github.com/eyzhao/hrdetect-pipeline/tree/"
                    "32e609f0479780e2072bb4b0c39190660d7eb634"
                ),
            },
            {
                "label": "Original HRDetect method",
                "revision": "doi:10.1038/nm.4292",
                "url": "https://www.nature.com/articles/nm.4292",
            },
        ],
    },
)
# fmt: on
if tuple(method["method_id"] for method in METHODS) != BLOCKED_CROSSCHECK_METHOD_IDS:
    raise ValueError("blocked method generator drifted from the HRD report inventory")

SOURCE_REPORT_METHOD_IDS = (
    "deterministic_full_wgs",
    "rosalind_diana_wgs",
    *EXECUTABLE_CROSSCHECK_METHOD_IDS,
)
if SOURCE_REPORT_METHOD_IDS != REQUIRED_METHOD_IDS[: len(SOURCE_REPORT_METHOD_IDS)]:
    raise ValueError("blocked method source reports drifted from the HRD inventory")
PRE_ROUTE_SOURCE_REPORT_METHOD_IDS = SOURCE_REPORT_METHOD_IDS[:2]
TERMINAL_SOURCE_REPORT_BINDING_SCOPE = "terminal_source_reports"
PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE = "pre_route_deterministic_rosalind"

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_HEX.fullmatch(value) is not None


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    require_real_hash_input(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def require_real_nonempty_file(path: Path, label: str) -> None:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a real non-empty file")


def require_real_hash_input(path: Path) -> None:
    require_real_nonempty_file(path, f"{path.name} SHA-256 input")


def exact_schema_version(payload: dict[str, Any], expected: int = 1) -> bool:
    return type(payload.get("schema_version")) is int and payload["schema_version"] == expected


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    require_real_nonempty_file(path, label)
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(f"duplicate JSON object name in {label}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {label}: {path}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"{label} must be a JSON object")
    return manifest


def load_source_report_manifest(path: Path, method_id: str) -> None:
    manifest = load_json_object(
        path,
        f"{method_id} source report manifest",
    )
    report_path = path.parent / "report.md"
    require_real_nonempty_file(report_path, f"{method_id} source report")
    if manifest.get("method_id") != method_id:
        raise ValueError(f"source report manifest method_id does not match {method_id}")
    if manifest.get("authorized_hrd_state") != "no_call":
        raise ValueError(f"source report manifest must preserve no_call: {method_id}")
    if manifest.get("classification_authorized") is not False:
        raise ValueError(f"source report manifest must not authorize classification: {method_id}")
    if manifest.get("classification_qc_status") != "not_applicable":
        raise ValueError(f"source report manifest classification QC must remain not_applicable: {method_id}")
    if not is_sha256(manifest.get("report_sha256")):
        raise ValueError(f"source report manifest report_sha256 is malformed: {method_id}")
    if manifest["report_sha256"] != sha256_file(report_path):
        raise ValueError(f"source report manifest hash differs from report.md: {method_id}")
    review_summary = manifest.get("review_summary")
    if not isinstance(review_summary, dict) or not review_summary:
        raise ValueError(f"source report manifest review_summary is required: {method_id}")


def source_report_binding_scope(method_ids: Sequence[str]) -> str:
    observed = tuple(method_ids)
    if observed == SOURCE_REPORT_METHOD_IDS:
        return TERMINAL_SOURCE_REPORT_BINDING_SCOPE
    if observed == PRE_ROUTE_SOURCE_REPORT_METHOD_IDS:
        return PRE_ROUTE_SOURCE_REPORT_BINDING_SCOPE
    raise ValueError(
        f"unsupported blocked source-report binding: {list(observed)!r}"
    )


def load_source_report_manifests(
    values: Sequence[str],
    *,
    allow_pre_route_source_reports: bool = False,
) -> dict[str, str]:
    manifests: dict[str, str] = {}
    for value in values:
        method_id, separator, raw_path = value.partition("=")
        if not separator:
            raise ValueError("source report manifests must use method_id=path")
        if method_id not in REQUIRED_METHOD_IDS:
            raise ValueError(f"unexpected source report method: {method_id}")
        if method_id in manifests:
            raise ValueError(f"duplicate source report method: {method_id}")

        path = Path(raw_path)
        load_source_report_manifest(path, method_id)
        manifests[method_id] = sha256_file(path)
    return validate_source_report_manifests(
        manifests,
        allow_pre_route_source_reports=allow_pre_route_source_reports,
    )


def validate_source_report_manifests(
    value: Mapping[str, str],
    *,
    allow_pre_route_source_reports: bool = False,
) -> dict[str, str]:
    manifests = dict(value)
    for method_id, digest in manifests.items():
        if method_id not in REQUIRED_METHOD_IDS:
            raise ValueError(f"unexpected source report method: {method_id}")
        if not is_sha256(digest):
            raise ValueError(f"source report manifest SHA-256 is malformed: {method_id}")

    observed = tuple(manifests)
    if observed == SOURCE_REPORT_METHOD_IDS or (
        allow_pre_route_source_reports
        and observed == PRE_ROUTE_SOURCE_REPORT_METHOD_IDS
    ):
        return {method_id: manifests[method_id] for method_id in observed}

    if allow_pre_route_source_reports:
        expected_orders = (
            SOURCE_REPORT_METHOD_IDS,
            PRE_ROUTE_SOURCE_REPORT_METHOD_IDS,
        )
        expected_methods = set().union(*(set(order) for order in expected_orders))
        missing = sorted(expected_methods - set(manifests))
        unexpected = sorted(set(manifests) - expected_methods)
        raise ValueError(
            "source report manifests must bind either the four terminal "
            "upstream report packets or the two pre-route deterministic/"
            "Rosalind packets in exact order; "
            f"expected={[list(order) for order in expected_orders]!r} "
            f"observed={list(manifests)!r} missing={missing!r} "
            f"unexpected={unexpected!r}"
        )

    if observed != SOURCE_REPORT_METHOD_IDS:
        missing = sorted(set(SOURCE_REPORT_METHOD_IDS) - set(manifests))
        unexpected = sorted(set(manifests) - set(SOURCE_REPORT_METHOD_IDS))
        raise ValueError(
            "source report manifests must bind the four upstream report packets "
            f"in exact order; expected={list(SOURCE_REPORT_METHOD_IDS)!r} "
            f"observed={list(manifests)!r} missing={missing!r} "
            f"unexpected={unexpected!r}"
        )
    raise AssertionError("unreachable source-report manifest validation state")


def require_safe_new_packet(path: Path) -> Path:
    require_no_symlinked_ancestors(path, "blocked cross-check packet")
    if path.is_symlink():
        raise ValueError("blocked cross-check packet may not be a symlink: " + path.name)
    if path.exists():
        raise FileExistsError("blocked cross-check packet already exists: " + path.name)
    return path.resolve()


def write_file_create_only(path: Path, data: bytes) -> None:
    expected_sha256 = hashlib.sha256(data).hexdigest()
    path = require_safe_new_packet(path)
    descriptor = -1
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        if sha256_file(path) != expected_sha256:
            raise ValueError(
                "blocked cross-check packet changed during write: " + path.name
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_bound_packet_file(packet_dir: Path, name: str, digest: Any) -> None:
    if not is_sha256(digest):
        raise ValueError(f"blocked cross-check report manifest has malformed SHA-256 for {name}")
    path = packet_dir / name
    require_real_nonempty_file(path, "blocked cross-check packet")
    if sha256_file(path) != digest:
        raise ValueError(f"blocked cross-check report manifest is stale for {name}")


def require_blocked_report_manifest(packet_dir: Path) -> None:
    manifest_path = packet_dir / "report_manifest.json"
    manifest = load_json_object(manifest_path, "blocked cross-check packet")
    if (
        set(manifest) != BLOCKED_REPORT_MANIFEST_KEYS
        or not exact_schema_version(manifest)
        or manifest.get("method_id") not in BLOCKED_CROSSCHECK_METHOD_IDS
        or manifest.get("report_kind") != "blocked_method"
        or any(manifest.get(key) != value for key, value in STATUS.items())
        or manifest.get("authorized_hrd_state") != "no_call"
        or manifest.get("classification_authorized") is not False
        or manifest.get("classification_qc_status") != "not_applicable"
        or not str(manifest.get("generated_at", ""))
        or not isinstance(manifest.get("review_summary"), dict)
        or not manifest.get("review_summary")
    ):
        raise ValueError("blocked cross-check report manifest envelope is not exact")

    support_hashes = manifest.get("support_sha256")
    if not isinstance(support_hashes, dict) or set(support_hashes) != {"method_spec.json"}:
        raise ValueError(
            "blocked cross-check report manifest must bind method_spec.json"
        )
    source_hashes = manifest.get("source_sha256")
    review_summary = manifest.get("review_summary")
    source_report_manifests = (
        review_summary.get("source_report_manifests", {})
        if isinstance(review_summary, dict)
        else {}
    )
    if not isinstance(source_hashes, dict) or not isinstance(
        source_report_manifests,
        dict,
    ):
        raise ValueError("blocked cross-check report manifest source hashes are not exact")
    expected_source_hashes = {
        "generator": sha256_file(Path(__file__).resolve()),
        **{
            f"{method_id}_report_manifest": digest
            for method_id, digest in source_report_manifests.items()
        },
    }
    if source_hashes != expected_source_hashes:
        raise ValueError("blocked cross-check report manifest source hashes are not exact")
    require_bound_packet_file(packet_dir, "report.md", manifest.get("report_sha256"))
    require_bound_packet_file(
        packet_dir,
        "method_spec.json",
        support_hashes.get("method_spec.json"),
    )


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_output_root(output_root: Path) -> Path:
    if output_root.is_symlink():
        raise ValueError("blocked cross-check output may not be a symlink")
    require_safe_output_parent(output_root)
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"blocked cross-check output is not a directory: {output_root}")

    targets = [output_root / str(method["directory"]) for method in METHODS]
    existing = [str(path) for path in targets if path.exists() or path.is_symlink()]
    if existing:
        raise FileExistsError("blocked cross-check output already exists: " + ", ".join(existing))

    output_root.mkdir(parents=True, exist_ok=True)
    return output_root.resolve()


def require_safe_output_parent(output_root: Path) -> None:
    for parent in output_root.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"blocked cross-check output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def render_report(
    spec: dict[str, Any],
    generated_at: str,
    *,
    run_id: str,
    source_report_manifests: Mapping[str, str],
    source_report_binding_scope: str,
) -> str:
    lines = [
        f"# {spec['title']} — blocked method report",
        "",
        f"- execution_status: `{STATUS['execution_status']}`",
        f"- evidence_status: `{STATUS['evidence_status']}`",
        f"- interpretation_status: `{STATUS['interpretation_status']}`",
        f"- classification_authorization: `{STATUS['classification_authorization']}`",
        f"- patient_result: `{STATUS['patient_result']}`",
        f"- generated_at: `{generated_at}`",
        f"- source_report_binding_scope: `{source_report_binding_scope}`",
        "",
        (
            "The method was not run. This artifact contains no patient result, "
            "reports no inferred result, and authorizes no HRD classification."
        ),
        "",
        "## Alias scope",
        "",
        ", ".join(f"`{alias}`" for alias in spec["alias_scope"]),
        "",
        "No direct identifiers, source object names, or patient-derived values are included.",
        "",
        "## Upstream report context",
        "",
        f"- run_id: `{run_id or 'not_recorded'}`",
    ]
    lines.extend(
        f"- {method_id} report_manifest_sha256: `{digest}`"
        for method_id, digest in source_report_manifests.items()
    )
    lines.extend(
        [
            "",
            "## Intended computation — not executed",
            "",
        ]
    )
    lines.extend(f"- {value}" for value in spec["intended_computation"])
    lines.extend(["", "## Exact prerequisites", ""])
    lines.extend(f"- {value}" for value in spec["prerequisites"])
    lines.extend(["", "## Current blockers", ""])
    lines.extend(f"- {value}" for value in spec["blockers"])
    lines.extend(["", "## Next gate", "", spec["next_gate"], "", "## Primary sources", ""])
    lines.extend(f"- [{source['label']}]({source['url']}) — `{source['revision']}`" for source in spec["sources"])
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            (
                "Execution remains `not_run`; evidence remains `blocked`; "
                "interpretation remains `no_call`; classification authorization "
                "remains `none`. No patient result exists in this report or its "
                "manifest."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def generate(
    output_root: Path,
    generated_at: str,
    *,
    run_id: str = "",
    source_report_manifests: Mapping[str, str],
    allow_pre_route_source_reports: bool = False,
) -> list[Path]:
    source_report_manifests = validate_source_report_manifests(
        source_report_manifests,
        allow_pre_route_source_reports=allow_pre_route_source_reports,
    )
    binding_scope = source_report_binding_scope(source_report_manifests)
    output_root = prepare_output_root(output_root)
    generator_hash = sha256_file(Path(__file__).resolve())
    written: list[Path] = []
    created_targets: list[Path] = []

    def write_tracked(path: Path, data: bytes) -> None:
        path_preexisted = path.exists() or path.is_symlink()
        try:
            write_file_create_only(path, data)
        except Exception:
            if not path_preexisted:
                written.append(path)
            raise
        written.append(path)

    try:
        for method in METHODS:
            target = output_root / str(method["directory"])
            target.mkdir(parents=True)
            created_targets.append(target)
            spec = {
                "schema_version": 1,
                "method_id": method["method_id"],
                "title": method["title"],
                **STATUS,
                "explicit_no_patient_result": ("The method was not run and no patient result was generated, inferred, or reported."),
                "alias_scope": method["alias_scope"],
                "intended_computation": method["intended_computation"],
                "prerequisites": method["prerequisites"],
                "blockers": method["blockers"],
                "next_gate": method["next_gate"],
                "sources": method["sources"],
                "run_id": run_id,
                "source_report_binding_scope": binding_scope,
                "source_report_manifests": dict(source_report_manifests),
            }
            spec_path = target / "method_spec.json"
            write_tracked(spec_path, json_bytes(spec))
            report_path = target / "report.md"
            write_tracked(
                report_path,
                render_report(
                    method,
                    generated_at,
                    run_id=run_id,
                    source_report_manifests=source_report_manifests,
                    source_report_binding_scope=binding_scope,
                ).encode("utf-8"),
            )
            manifest = {
                "schema_version": 1,
                "method_id": method["method_id"],
                "report_kind": "blocked_method",
                "generated_at": generated_at,
                **STATUS,
                "authorized_hrd_state": "no_call",
                "classification_authorized": False,
                "classification_qc_status": "not_applicable",
                "explicit_no_patient_result": ("The method was not run and no patient result was generated, inferred, or reported."),
                "alias_scope": method["alias_scope"],
                "intended_computation": method["intended_computation"],
                "prerequisites": method["prerequisites"],
                "blockers": method["blockers"],
                "next_gate": method["next_gate"],
                "sources": method["sources"],
                "run_id": run_id,
                "source_report_binding_scope": binding_scope,
                "review_summary": {
                    "evidence_scope": f"{method['title']} blocked-method specification",
                    "source_report_binding_scope": binding_scope,
                    "source_report_manifests": dict(source_report_manifests),
                    "readiness": {
                        "execution_status": "not_run",
                        "evidence_status": "blocked",
                        "authorized_hrd_state": "no_call",
                        "classification_authorization": "none",
                    },
                    "observations": {},
                    "limitations": [
                        "The method was not run.",
                        "No patient result is present.",
                        "No HRD classification is authorized.",
                    ],
                },
                "source_sha256": {
                    "generator": generator_hash,
                    **{f"{method_id}_report_manifest": digest for method_id, digest in source_report_manifests.items()},
                },
                "support_sha256": {
                    "method_spec.json": sha256_file(spec_path),
                },
                "report_sha256": sha256_file(report_path),
            }
            manifest_path = target / "report_manifest.json"
            write_tracked(manifest_path, json_bytes(manifest))
            require_blocked_report_manifest(target)
        fsync_directory(output_root)
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        for target in reversed(created_targets):
            with suppress(OSError):
                target.rmdir()
        with suppress(OSError):
            output_root.rmdir()
        raise
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--run-id",
        default="",
        help="Pseudonymous run ID to bind into each blocked report.",
    )
    parser.add_argument(
        "--source-report-manifest",
        action="append",
        required=True,
        metavar="METHOD_ID=PATH",
        help=("Hash-bind an upstream report manifest into each blocked packet; may be passed more than once."),
    )
    parser.add_argument(
        "--allow-pre-route-source-reports",
        action="store_true",
        help=(
            "Allow the two-report deterministic/Rosalind pre-route binding "
            "used by the fast DAG before Sequenza and SigProfiler reports "
            "exist. Omit this for terminal private-freeze packets."
        ),
    )
    parser.add_argument(
        "--generated-at",
        default=datetime.now(timezone.utc).isoformat(),
        help=("Timestamp recorded in reports and manifests; pass a fixed value for reproducible tests."),
    )
    args = parser.parse_args(argv)
    try:
        written = generate(
            args.output_dir,
            args.generated_at,
            run_id=args.run_id,
            source_report_manifests=load_source_report_manifests(
                args.source_report_manifest,
                allow_pre_route_source_reports=args.allow_pre_route_source_reports,
            ),
            allow_pre_route_source_reports=args.allow_pre_route_source_reports,
        )
    except (FileExistsError, ValueError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
