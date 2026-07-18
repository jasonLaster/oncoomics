from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from ...paths import path_from_root
from ...utils import read_json

DEFAULT_RECEIPT = "results/phase3_wgs_fast/parabricks_mirror_receipt.json"
REQUIRED_AWS_REGION = "us-east-2"
REQUIRED_PLATFORM = "linux/amd64"

DIGEST = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
PINNED_IMAGE = re.compile(r"^\S+@(sha256:[0-9a-fA-F]{64})$")
ECR_REPOSITORY = re.compile(r"^\d{12}\.dkr\.ecr\.([a-z]{2}-[a-z]+-\d)\.amazonaws\.com/[a-z0-9][a-z0-9._/-]*$")


class MirrorReceiptError(ValueError):
    """Raised when the Parabricks ECR mirror receipt is not safe to pin."""


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise MirrorReceiptError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MirrorReceiptError(f"{label} is required")
    return value.strip()


def _require_digest(value: Any, label: str) -> str:
    value = _require_string(value, label)
    if DIGEST.fullmatch(value) is None:
        raise MirrorReceiptError(f"{label} must be sha256:<64 hex>")
    return value.lower()


def _require_pinned_image(value: Any, label: str) -> tuple[str, str]:
    image = _require_string(value, label)
    match = PINNED_IMAGE.fullmatch(image)
    if match is None:
        raise MirrorReceiptError(f"{label} must be pinned as <image>@sha256:<64 hex>")
    return image, match.group(1).lower()


def validate_mirror_receipt(receipt: Mapping[str, Any]) -> dict[str, str]:
    if receipt.get("schema_version") != 1:
        raise MirrorReceiptError("schema_version must be 1")
    if receipt.get("manifest_type") != "parabricks_mirror_receipt":
        raise MirrorReceiptError("manifest_type must be parabricks_mirror_receipt")

    source = _require_mapping(receipt.get("source"), "source")
    destination = _require_mapping(receipt.get("destination"), "destination")

    source_image, image_digest = _require_pinned_image(source.get("image"), "source.image")
    source_digest = _require_digest(source.get("digest"), "source.digest")
    if image_digest != source_digest:
        raise MirrorReceiptError("source.digest must match source.image")

    platform = _require_string(source.get("platform"), "source.platform")
    if platform != REQUIRED_PLATFORM:
        raise MirrorReceiptError(f"source.platform must be {REQUIRED_PLATFORM}")

    region = _require_string(destination.get("region"), "destination.region")
    if region != REQUIRED_AWS_REGION:
        raise MirrorReceiptError(f"destination.region must be {REQUIRED_AWS_REGION}")

    repository = _require_string(destination.get("repository"), "destination.repository")
    repository_match = ECR_REPOSITORY.fullmatch(repository)
    if repository_match is None or repository_match.group(1) != REQUIRED_AWS_REGION:
        raise MirrorReceiptError(f"destination.repository must be an ECR repository URI in {REQUIRED_AWS_REGION}")

    destination_digest = _require_digest(destination.get("digest"), "destination.digest")
    expected_container = f"{repository}@{destination_digest}"
    if destination.get("parabricks_container") != expected_container:
        raise MirrorReceiptError("destination.parabricks_container must match destination repository and digest")

    expected_tag = f"sha256-{source_digest.removeprefix('sha256:')}"
    if destination.get("tag") != expected_tag:
        raise MirrorReceiptError("destination.tag must be the full source digest tag")

    return {
        "destination_digest": destination_digest,
        "parabricks_container": expected_container,
        "region": region,
        "repository": repository,
        "source_digest": source_digest,
        "source_image": source_image,
        "tag": expected_tag,
    }


def load_mirror_digest(*, parabricks_container: str, region: str, aws_cli: str = "aws") -> str:
    repository, digest = parabricks_container.split("@", 1)
    repository_name = repository.split("/", 1)[1]
    try:
        result = subprocess.run(
            [
                aws_cli,
                "ecr",
                "describe-images",
                "--region",
                region,
                "--repository-name",
                repository_name,
                "--image-ids",
                f"imageDigest={digest}",
                "--output",
                "json",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as error:
        raise MirrorReceiptError(f"{aws_cli} is required to verify the mirrored Parabricks image") from error
    except subprocess.CalledProcessError as error:
        output = (error.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise MirrorReceiptError(f"Unable to find mirrored Parabricks image {parabricks_container}{detail}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise MirrorReceiptError("ECR did not return JSON") from error

    if not isinstance(payload, dict):
        raise MirrorReceiptError("ECR response must be a JSON object")
    image_details = payload.get("imageDetails")
    if not isinstance(image_details, list) or not image_details:
        raise MirrorReceiptError(f"ECR did not return imageDetails for {parabricks_container}")
    if image_details[0].get("imageDigest") != digest:
        raise MirrorReceiptError(f"ECR imageDigest must match {digest}")
    return digest


def load_receipt_from_environment() -> tuple[dict[str, Any], Path]:
    path = path_from_root(os.environ.get("PARABRICKS_MIRROR_RECEIPT", DEFAULT_RECEIPT))
    if not path.exists():
        raise MirrorReceiptError(f"Missing Parabricks mirror receipt: {path}")
    receipt = read_json(path)
    if not isinstance(receipt, dict):
        raise MirrorReceiptError(f"{path} must contain a JSON object")
    return receipt, path


def main() -> None:
    try:
        receipt, path = load_receipt_from_environment()
        summary = validate_mirror_receipt(receipt)
        observed_digest = load_mirror_digest(
            parabricks_container=summary["parabricks_container"],
            region=summary["region"],
        )
    except MirrorReceiptError as error:
        raise SystemExit(str(error)) from error

    print(
        f"Parabricks mirror receipt passed: {path} "
        f"tag={summary['tag']} "
        f"parabricks_container={summary['parabricks_container']} "
        f"image_digest={observed_digest}"
    )
    print(
        "TF_VAR_parabricks_container="
        f"'{summary['parabricks_container']}' "
        "PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:plan:use2"
    )


if __name__ == "__main__":
    main()
