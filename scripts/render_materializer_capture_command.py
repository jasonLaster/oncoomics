#!/usr/bin/env python3
"""Render the exact cross-check materializer terminal-capture command.

The materializer submitter writes two private receipts:

- the exact ``SubmitJob`` request that was authorized; and
- the AWS Batch submission response bound to that request.

This helper refuses to guess any Batch parameters.  It validates both receipts,
checks that the response is cryptographically bound to the request, and writes
a create-only shell command containing the exact job id and the exact eight
materializer parameters required by ``capture_materializer_terminal.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Iterable


REGION = "us-east-1"
ACCOUNT_ID = "172630973301"
SUBJECT_ALIAS = "subject01"
RUN_ID = "diana-wgs-hrd-20260716T033101Z"
KMS_KEY_ARN = (
    f"arn:aws:kms:{REGION}:{ACCOUNT_ID}:key/"
    "45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
)
DETERMINISTIC_DESTINATION_PREFIX = (
    f"s3://diana-omics-private-results-{ACCOUNT_ID}-{REGION}/runs/"
    f"{SUBJECT_ALIAS}/{RUN_ID}/deterministic"
)
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
SHA_PARAMETER_NAMES = frozenset(
    (
        "source_vcf_sha256",
        "source_vcf_index_sha256",
        "source_matrix_sha256",
    )
)
REQUIRED_RESPONSE_CHECKS = frozenset(
    (
        "request_receipt_mode_0600",
        "exact_job_name",
        "job_id_and_arn",
        "one_shot_no_retry",
    )
)
JOB_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
AWS_BATCH_ARN_PREFIX = f"arn:aws:batch:{REGION}:{ACCOUNT_ID}:job/"


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def shell_join(values: Iterable[str | os.PathLike[str]]) -> str:
    return " ".join(shlex.quote(os.fspath(value)) for value in values)


def write_once(path: Path, text: str) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    if path.parent.is_symlink():
        raise ValueError(f"output parent is a symlink: {path.parent}")
    if path.parent.exists() and not path.parent.is_dir():
        raise NotADirectoryError(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def validate_parameters(value: Any) -> dict[str, str]:
    parameters = require_object(value, "submit_job_request.parameters")
    if set(parameters) != set(PARAMETER_NAMES):
        raise ValueError(
            "submit_job_request.parameters must contain exactly the eight "
            "materializer keys"
        )

    result: dict[str, str] = {}
    for name in PARAMETER_NAMES:
        parameter = parameters[name]
        if not isinstance(parameter, str) or not parameter:
            raise ValueError(f"materializer parameter {name} must be a non-empty string")
        if name in SHA_PARAMETER_NAMES:
            if not re.fullmatch(r"[0-9a-f]{64}", parameter):
                raise ValueError(f"materializer parameter {name} is not lowercase SHA-256")
        elif re.search(r"\s", parameter):
            raise ValueError(f"materializer parameter {name} contains whitespace")
        result[name] = parameter
    return result


def validate_receipts(
    request_path: Path, request: dict[str, Any], response: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    if request.get("status") != "submission_authorized":
        raise ValueError("request receipt was not an authorized submission")
    if response.get("status") != "submitted":
        raise ValueError("response receipt does not record a successful submission")

    request_summary = require_object(
        response.get("request_receipt"), "response.request_receipt"
    )
    request_sha256 = sha256_path(request_path)
    if request_summary.get("sha256") != request_sha256:
        raise ValueError("response receipt is not bound to the request receipt bytes")

    submit_request = require_object(
        request.get("submit_job_request"), "submit_job_request"
    )
    expected_submit_sha256 = sha256_bytes(canonical_bytes(submit_request))
    if response.get("submit_job_request_sha256") != expected_submit_sha256:
        raise ValueError("response receipt is not bound to the submit_job_request")
    if submit_request.get("retryStrategy") != {"attempts": 1}:
        raise ValueError("materializer SubmitJob request must be one-shot")

    checks = require_object(response.get("checks"), "response.checks")
    missing_or_false = sorted(
        name for name in REQUIRED_RESPONSE_CHECKS if checks.get(name) is not True
    )
    if missing_or_false:
        raise ValueError(
            "response receipt is missing required true checks: "
            + ", ".join(missing_or_false)
        )

    batch_response = require_object(response.get("response"), "response.response")
    if batch_response.get("jobName") != submit_request.get("jobName"):
        raise ValueError("Batch response jobName does not match SubmitJob request")
    job_id = batch_response.get("jobId")
    if not isinstance(job_id, str) or JOB_ID_PATTERN.fullmatch(job_id) is None:
        raise ValueError("Batch response jobId is malformed")
    job_arn = batch_response.get("jobArn")
    if job_arn != f"{AWS_BATCH_ARN_PREFIX}{job_id}":
        raise ValueError("Batch response jobArn does not match jobId")

    return job_id, validate_parameters(submit_request.get("parameters"))


def render_command(
    *,
    capture_script: Path,
    job_id: str,
    parameters: dict[str, str],
    expected_receipt_prefix: str,
    expected_kms_key_arn: str,
    capture_output: Path,
    anchor_output: Path,
    receipt_output: Path,
    region: str,
) -> str:
    command = [
        "python3",
        capture_script,
        "--job-id",
        job_id,
        *[
            token
            for name in PARAMETER_NAMES
            for token in ("--expected-parameter", f"{name}={parameters[name]}")
        ],
        "--expected-receipt-prefix",
        expected_receipt_prefix,
        "--expected-kms-key-arn",
        expected_kms_key_arn,
        "--capture-output",
        capture_output,
        "--anchor-output",
        anchor_output,
        "--receipt-output",
        receipt_output,
        "--region",
        region,
    ]
    return "#!/usr/bin/env bash\nset -euo pipefail\n" + shell_join(command) + "\n"


def render_from_files(args: argparse.Namespace) -> str:
    request_path = args.request_receipt.resolve()
    request = read_json_object(request_path)
    response = read_json_object(args.response_receipt)
    job_id, parameters = validate_receipts(request_path, request, response)
    return render_command(
        capture_script=Path(__file__).resolve().parent
        / "capture_materializer_terminal.py",
        job_id=job_id,
        parameters=parameters,
        expected_receipt_prefix=args.expected_receipt_prefix,
        expected_kms_key_arn=args.expected_kms_key_arn,
        capture_output=args.capture_output,
        anchor_output=args.anchor_output,
        receipt_output=args.receipt_output,
        region=args.region,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-receipt", required=True, type=Path)
    parser.add_argument("--response-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--capture-output", required=True, type=Path)
    parser.add_argument("--anchor-output", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument(
        "--expected-receipt-prefix",
        default=(
            f"{DETERMINISTIC_DESTINATION_PREFIX}/provenance/"
            "crosscheck-materialization-receipts/"
        ),
    )
    parser.add_argument("--expected-kms-key-arn", default=KMS_KEY_ARN)
    parser.add_argument("--region", default=REGION, choices=[REGION])
    args = parser.parse_args()

    try:
        command = render_from_files(args)
        write_once(args.output, command)
    except (FileExistsError, OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    print(json.dumps({"status": "rendered", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
