#!/usr/bin/env python3
"""Validate the private, alias-only HRD cross-check input contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
S3_URI = re.compile(r"^s3://[^/]+/.+")
ALIAS = re.compile(r"^subject[0-9]{2,}$")
KMS_ARN = re.compile(r"^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[A-Za-z0-9-]+$")

ROUTE_REQUIREMENTS = {
    "sigprofiler_sbs3": ["sbs96_matrix", "somatic_vcf", "somatic_vcf_index"],
    "sequenza_scarhrd": ["tumor_bam", "tumor_bai", "normal_bam", "normal_bai"],
    "facets_scarhrd": [
        "tumor_bam",
        "tumor_bai",
        "normal_bam",
        "normal_bai",
        "common_snp_vcf",
        "common_snp_vcf_index",
    ],
    "oncoanalyser_chord": [],
}


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def private_input(uri: str) -> bool:
    return bool(
        re.match(
            r"^s3://diana-omics-(?:raw-inputs|work|private-results)-[^/]+/.+",
            uri,
        )
    )


def valid_version_id(value: object) -> bool:
    version_id = str(value)
    return bool(
        version_id
        and version_id.lower() not in {"none", "null"}
        and not any(character.isspace() for character in version_id)
    )


def valid_blob(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        private_input(str(value.get("uri", "")))
        and bool(HEX64.match(str(value.get("sha256", ""))))
        and valid_version_id(value.get("version_id"))
    )


def private_output(uri: str) -> bool:
    return bool(
        re.match(
            r"^s3://diana-omics-private-results-[^/]+/runs/subject[0-9]{2,}/[A-Za-z0-9_.-]+/?$",
            uri,
        )
    )


def validate(contract: dict) -> dict:
    shared: list[str] = []
    alias = str(contract.get("run_alias", ""))
    if not ALIAS.match(alias):
        shared.append("run_alias must be a de-identified alias such as subject01")

    reference = contract.get("reference", {})
    if reference.get("build") != "GRCh38":
        shared.append("reference.build must be GRCh38")
    for key in ("fasta", "fai", "dict"):
        if not valid_blob(reference.get(key)):
            shared.append(
                f"reference.{key} must have an approved private Diana S3 URI, exact VersionId, and 64-hex SHA-256"
            )

    kms_key_arn = str(contract.get("kms_key_arn", ""))
    if not KMS_ARN.match(kms_key_arn):
        shared.append("kms_key_arn must be an exact AWS KMS key ARN")

    output_uri = str(contract.get("output_uri", ""))
    if not private_output(output_uri):
        shared.append(
            "output_uri must be the durable private-results bucket under "
            "runs/subjectNN/RUN_ID; public results, raw inbox, and expiring work output are prohibited"
        )
    elif f"/runs/{alias}/" not in output_uri:
        shared.append("output_uri alias must match run_alias")

    attest = contract.get("attestations", {})
    for key in (
        "input_sha256_verified",
        "final_primary_wgs_artifacts",
        "no_direct_identifiers_in_aliases",
    ):
        if attest.get(key) is not True:
            shared.append(f"attestations.{key} must be true")

    custody = contract.get("custody")
    if not isinstance(custody, dict):
        shared.append("custody must contain the receipt-bound finalization evidence")
    else:
        if custody.get("schema_version") != 1 or custody.get("status") != "passed":
            shared.append("custody must be a passed schema-1 finalization record")
        for key in (
            "finalizer_script_sha256",
            "final_freeze_receipt_sha256",
            "exact_materialization_receipt_sha256",
            "crosscheck_materialization_receipt_sha256",
            "crosscheck_materializer_script_sha256",
        ):
            if not HEX64.match(str(custody.get(key, ""))):
                shared.append(f"custody.{key} must be an exact SHA-256")
        for key in (
            "final_freeze_receipt_version_id",
            "crosscheck_materialization_receipt_version_id",
        ):
            if not valid_version_id(custody.get(key)):
                shared.append(f"custody.{key} must be an exact S3 VersionId")
        checks = custody.get("checks")
        if (
            not isinstance(checks, dict)
            or not checks
            or any(value is not True for value in checks.values())
        ):
            shared.append("custody.checks must be present and all true")
        primary = custody.get("final_primary_artifacts")
        if not isinstance(primary, dict):
            shared.append("custody.final_primary_artifacts must bind final outputs")
        else:
            artifacts = contract.get("artifacts", {})
            for key in ("somatic_vcf", "somatic_vcf_index", "sbs96_matrix"):
                if primary.get(key) != artifacts.get(key):
                    shared.append(
                        f"custody.final_primary_artifacts.{key} must exactly equal artifacts.{key}"
                    )

    artifacts = contract.get("artifacts", {})
    route_results: dict[str, dict] = {}
    routes = contract.get("routes", [])
    if not routes:
        shared.append("at least one route must be requested")

    for route in routes:
        reasons = list(shared)
        if route not in ROUTE_REQUIREMENTS:
            reasons.append(f"unsupported route: {route}")
        else:
            for key in ROUTE_REQUIREMENTS[route]:
                if not valid_blob(artifacts.get(key)):
                    reasons.append(
                        f"artifacts.{key} requires an approved private Diana S3 URI, exact VersionId, and 64-hex SHA-256"
                    )

        if route == "sigprofiler_sbs3":
            if artifacts.get("sbs96_matrix", {}).get("derived_from_final_pass_vcf") is not True:
                reasons.append("SBS96 matrix must be derived from the final PASS VCF")
        elif route in {"sequenza_scarhrd", "facets_scarhrd"}:
            for key in ("bam_quickcheck_passed", "bam_reference_digest_matched"):
                if attest.get(key) is not True:
                    reasons.append(f"attestations.{key} must be true")
            if route == "facets_scarhrd" and attest.get("common_snp_vcf_reference_matched") is not True:
                reasons.append("attestations.common_snp_vcf_reference_matched must be true")
            if route == "sequenza_scarhrd":
                method_parameters = contract.get("method_parameters", {})
                sequenza_parameters = method_parameters.get("sequenza", {})
                if not isinstance(sequenza_parameters.get("female"), bool):
                    reasons.append(
                        "method_parameters.sequenza.female must explicitly declare the Sequenza sex model"
                    )
        elif route == "oncoanalyser_chord":
            lanes = contract.get("fastq_lanes", [])
            roles = {x.get("role") for x in lanes if isinstance(x, dict)}
            if not {"tumor", "normal"}.issubset(roles):
                reasons.append("at least one tumor and one normal FASTQ lane are required")
            for index, lane in enumerate(lanes):
                if lane.get("role") not in {"tumor", "normal"}:
                    reasons.append(f"fastq_lanes[{index}].role must be tumor or normal")
                for read in ("r1", "r2"):
                    if not valid_blob(lane.get(read)):
                        reasons.append(
                            f"fastq_lanes[{index}].{read} requires an approved private Diana S3 URI, exact VersionId, and SHA-256"
                        )
            if attest.get("fastq_checksums_match_delivery_manifest") is not True:
                reasons.append("attestations.fastq_checksums_match_delivery_manifest must be true")

        route_results[route] = {
            "status": "ready" if not reasons else "blocked",
            "reasons": reasons,
        }

    return {
        "overall_status": (
            "ready"
            if route_results and all(x["status"] == "ready" for x in route_results.values())
            else "blocked"
        ),
        "routes": route_results,
    }


def load_contract(path: Path) -> dict:
    require_no_symlinked_ancestors(path, "contract")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"contract must be a real JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"contract must be a JSON object: {path}")
    return value


def write_text_once(path: Path, value: str) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"contract readiness output already exists: {path}")
    require_safe_output_parent(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            fsync_directory(path.parent)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_safe_output_parent(path: Path) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(
                f"contract readiness output parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(load_contract(args.contract))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        try:
            write_text_once(args.json_out, rendered + "\n")
        except FileExistsError as error:
            raise SystemExit(
                f"Fail-closed: contract readiness output already exists: {args.json_out}"
            ) from error
        except (NotADirectoryError, ValueError) as error:
            raise SystemExit(f"Fail-closed: {error}") from error
    return 0 if result["overall_status"] == "ready" or args.allow_blocked else 2


if __name__ == "__main__":
    sys.exit(main())
