#!/usr/bin/env python3
"""Render the frozen-script Batch definition for the cross-check materializer.

This helper is source-only: it renders the local ``register-job-definition``
payload that a future reviewed materializer revision will use, but it never
uploads the script, registers the definition, or submits a Batch job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

REGION = "us-east-1"
JOB_DEFINITION_NAME = "diana-wgs-hrd-materialize-crosscheck-inputs"
PARAMETER_NAMES = (
    "source_vcf_version_id",
    "source_vcf_index_version_id",
    "source_matrix_version_id",
    "source_vcf_sha256",
    "source_vcf_index_sha256",
    "source_matrix_sha256",
    "reference_fasta_version_id",
    "reference_fai_version_id",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IMAGE = re.compile(r"^[0-9]{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/[A-Za-z0-9_./-]+@sha256:[0-9a-f]{64}$")
KMS = re.compile(r"^arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9A-Za-z-]+$")
ROLE = re.compile(r"^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$")
S3 = re.compile(r"^s3://([^/]+)/(.+)$")
SHELL_LITERAL = re.compile(r"^[A-Za-z0-9_./:@+=,-]+$")
VERSION_ID = re.compile(r"^\S+$")


def shell_literal(value: str, label: str) -> str:
    if not SHELL_LITERAL.fullmatch(value):
        raise ValueError(f"{label} contains unsafe shell characters: {value}")
    return value


def require_hex(value: str, label: str) -> str:
    if not HEX64.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def require_s3(value: str, label: str) -> str:
    if not S3.fullmatch(value):
        raise ValueError(f"{label} must be an S3 object URI")
    return shell_literal(value, label)


def require_version_id(value: str, label: str) -> str:
    if value.lower() in {"", "none", "null"} or not VERSION_ID.fullmatch(value):
        raise ValueError(f"{label} must be an exact S3 VersionId")
    return shell_literal(value, label)


def script_parts(uri: str) -> tuple[str, str]:
    match = S3.fullmatch(uri)
    if match is None:
        raise ValueError("script URI must be an S3 object URI")
    return match.group(1), match.group(2)


def require_image(value: str) -> str:
    if not IMAGE.fullmatch(value):
        raise ValueError("image must be an exact us-east-1 ECR sha256 digest")
    return shell_literal(value, "image")


def require_job_role(value: str) -> str:
    if not ROLE.fullmatch(value):
        raise ValueError("job role must be an IAM role ARN")
    return shell_literal(value, "job role")


def require_kms(value: str) -> str:
    if not KMS.fullmatch(value):
        raise ValueError("KMS key must be a us-east-1 KMS key ARN")
    return shell_literal(value, "KMS key")


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_safe_output(path: Path) -> None:
    if path.is_symlink():
        raise FileExistsError(f"output may not be a symlink: {path}")
    if path.exists():
        raise FileExistsError(f"refusing to overwrite output: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise FileExistsError(f"output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_create_only(path: Path, value: dict[str, Any]) -> None:
    require_safe_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, sort_keys=True) + "\n"
    expected_sha256 = hashlib.sha256(data.encode("utf-8")).hexdigest()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        fsync_directory(path.parent)
        require_installed_output(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def require_installed_output(path: Path, expected_sha256: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"output changed during write: {path}")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"output changed during write: {path}")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"output mode changed during write: {path}")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"output changed during write: {path}")


def sha256_file(path: Path) -> str:
    digest = sha256_file_once(path)
    if sha256_file_once(path) != digest:
        raise ValueError(f"{path.name} SHA-256 input changed during read")
    return digest


def sha256_file_once(path: Path) -> str:
    require_real_file(path, f"{path.name} SHA-256 input")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_real_file(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is missing or a symlink: {path}")


def render(args: argparse.Namespace) -> dict[str, Any]:
    script_uri = require_s3(args.script_uri, "script URI")
    script_version_id = require_version_id(args.script_version_id, "script VersionId")
    script_sha256 = require_hex(args.script_sha256, "script SHA-256")
    source_vcf_uri = require_s3(args.source_vcf_uri, "source VCF URI")
    source_vcf_index_uri = require_s3(args.source_vcf_index_uri, "source VCF index URI")
    source_matrix_uri = require_s3(args.source_matrix_uri, "source matrix URI")
    reference_fasta_uri = require_s3(args.reference_fasta_uri, "reference FASTA URI")
    reference_fai_uri = require_s3(args.reference_fai_uri, "reference FAI URI")
    reference_fasta_sha256 = require_hex(args.reference_fasta_sha256, "reference FASTA SHA-256")
    reference_fai_sha256 = require_hex(args.reference_fai_sha256, "reference FAI SHA-256")
    destination_prefix = require_s3(args.destination_prefix, "destination prefix").rstrip("/")
    receipt_prefix = require_s3(args.receipt_prefix, "receipt prefix").rstrip("/")
    kms_key_arn = require_kms(args.kms_key_arn)
    image = require_image(args.image)
    job_role_arn = require_job_role(args.job_role_arn)
    script_bucket, script_key = script_parts(script_uri)

    body = (
        "set -euo pipefail; "
        "mkdir -p /work/materialize/run; "
        f"/opt/diana-aws/bin/aws s3api get-object --bucket {script_bucket} "
        f"--key {script_key} --version-id {script_version_id} "
        f"--checksum-mode ENABLED --region {REGION} "
        "/work/materialize/materialize_crosscheck_inputs.py "
        ">/work/materialize/script-get.json; "
        "actual=$(sha256sum /work/materialize/materialize_crosscheck_inputs.py | awk '{print $1}'); "
        f"test \"$actual\" = {script_sha256}; "
        "python3 -u /work/materialize/materialize_crosscheck_inputs.py "
        f"--source-vcf-uri {source_vcf_uri} "
        f"--source-vcf-index-uri {source_vcf_index_uri} "
        f"--source-matrix-uri {source_matrix_uri} "
        f"--reference-fasta-uri {reference_fasta_uri} "
        f"--reference-fai-uri {reference_fai_uri} "
        "--source-vcf-version-id \"$1\" "
        "--source-vcf-index-version-id \"$2\" "
        "--source-matrix-version-id \"$3\" "
        "--source-vcf-sha256 \"$4\" "
        "--source-vcf-index-sha256 \"$5\" "
        "--source-matrix-sha256 \"$6\" "
        "--reference-fasta-version-id \"$7\" "
        "--reference-fai-version-id \"$8\" "
        f"--reference-fasta-sha256 {reference_fasta_sha256} "
        f"--reference-fai-sha256 {reference_fai_sha256} "
        f"--destination-prefix {destination_prefix} "
        f"--receipt-prefix {receipt_prefix} "
        "--receipt-anchor-output /work/materialize/materialization-receipt-anchor.json "
        f"--kms-key-arn {kms_key_arn} "
        "--run-alias subject01 "
        f"--region {REGION} "
        "--work-dir /work/materialize/run"
    )
    return {
        "jobDefinitionName": JOB_DEFINITION_NAME,
        "type": "container",
        "platformCapabilities": ["EC2"],
        "containerProperties": {
            "image": image,
            "jobRoleArn": job_role_arn,
            "vcpus": 8,
            "memory": 32000,
            "command": [
                "bash",
                "-lc",
                body,
                "materializer",
                *[f"Ref::{name}" for name in PARAMETER_NAMES],
            ],
            "environment": [{"name": "AWS_REGION", "value": REGION}],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/aws/batch/job",
                    "awslogs-region": REGION,
                    "awslogs-stream-prefix": "diana-wgs-hrd-materialize",
                },
            },
        },
        "retryStrategy": {"attempts": 1},
        "timeout": {"attemptDurationSeconds": 21600},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script-uri", required=True)
    parser.add_argument("--script-version-id", required=True)
    parser.add_argument("--script-sha256", required=True)
    parser.add_argument("--source-vcf-uri", required=True)
    parser.add_argument("--source-vcf-index-uri", required=True)
    parser.add_argument("--source-matrix-uri", required=True)
    parser.add_argument("--reference-fasta-uri", required=True)
    parser.add_argument("--reference-fai-uri", required=True)
    parser.add_argument("--reference-fasta-sha256", required=True)
    parser.add_argument("--reference-fai-sha256", required=True)
    parser.add_argument("--destination-prefix", required=True)
    parser.add_argument("--receipt-prefix", required=True)
    parser.add_argument("--kms-key-arn", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--job-role-arn", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = render(args)
    write_json_create_only(args.output, payload)
    print(json.dumps({"status": "rendered_only", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
