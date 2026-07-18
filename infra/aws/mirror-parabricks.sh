#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_WORKSPACE="${DIANA_AWS_TERRAFORM_WORKSPACE:-}"
SOURCE_IMAGE="${PARABRICKS_SOURCE_IMAGE:-${1:-}}"
PLATFORM="${PARABRICKS_PLATFORM:-linux/amd64}"
RECEIPT_PATH="${PARABRICKS_MIRROR_RECEIPT:-${ROOT_DIR}/results/phase3_wgs_fast/parabricks_mirror_receipt.json}"

die() {
  echo "mirror-parabricks: $*" >&2
  exit 1
}

restore_workspace() {
  if [[ -n "${ORIGINAL_WORKSPACE:-}" ]]; then
    terraform -chdir="${ROOT_DIR}/infra/aws" workspace select "${ORIGINAL_WORKSPACE}" >/dev/null
  fi
}

[[ -n "${SOURCE_IMAGE}" ]] || die "set PARABRICKS_SOURCE_IMAGE or pass a digest-pinned source image"
[[ "${SOURCE_IMAGE}" =~ @sha256:[0-9a-fA-F]{64}$ ]] || die "PARABRICKS_SOURCE_IMAGE must be pinned as <registry>/<image>@sha256:<64 hex>"

source_digest="${SOURCE_IMAGE##*@}"
source_digest_hex="${source_digest#sha256:}"
target_tag="${PARABRICKS_MIRROR_TAG:-sha256-${source_digest_hex:0:16}}"
[[ "${target_tag}" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]] || die "PARABRICKS_MIRROR_TAG is not a valid ECR image tag"

if [[ -n "${TARGET_WORKSPACE}" ]]; then
  ORIGINAL_WORKSPACE="$(terraform -chdir="${ROOT_DIR}/infra/aws" workspace show)"
  if [[ "${ORIGINAL_WORKSPACE}" != "${TARGET_WORKSPACE}" ]]; then
    terraform -chdir="${ROOT_DIR}/infra/aws" workspace select "${TARGET_WORKSPACE}" >/dev/null
    trap restore_workspace EXIT
  fi
fi

REGION="${AWS_REGION:-$(terraform -chdir="${ROOT_DIR}/infra/aws" output -raw region)}"
repository_url="$(terraform -chdir="${ROOT_DIR}/infra/aws" output -raw parabricks_mirror_repository_url)"
[[ -n "${repository_url}" ]] || die "parabricks_mirror_repository_url is empty; run infra:aws:apply:use2 first"
registry="${repository_url%%/*}"
repository_name="${repository_url#*/}"
target_image="${repository_url}:${target_tag}"

echo "Pulling ${PLATFORM} ${SOURCE_IMAGE}"
docker pull --platform "${PLATFORM}" "${SOURCE_IMAGE}"

echo "Logging in to ${registry}"
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${registry}"

echo "Pushing ${target_image}"
docker tag "${SOURCE_IMAGE}" "${target_image}"
docker push "${target_image}"

target_digest="$(
  aws ecr describe-images \
    --region "${REGION}" \
    --repository-name "${repository_name}" \
    --image-ids "imageTag=${target_tag}" \
    --query 'imageDetails[0].imageDigest' \
    --output text
)"
[[ "${target_digest}" =~ ^sha256:[0-9a-fA-F]{64}$ ]] || die "ECR did not return a digest for ${target_image}"

mkdir -p "$(dirname "${RECEIPT_PATH}")"
python3 - "${RECEIPT_PATH}" "${SOURCE_IMAGE}" "${source_digest}" "${PLATFORM}" "${REGION}" \
  "${repository_url}" "${target_tag}" "${target_digest}" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

receipt_path, source_image, source_digest, platform, region, repository_url, target_tag, target_digest = sys.argv[1:]
payload = {
    "schema_version": 1,
    "manifest_type": "parabricks_mirror_receipt",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "source": {
        "image": source_image,
        "digest": source_digest,
        "platform": platform,
    },
    "destination": {
        "region": region,
        "repository": repository_url,
        "tag": target_tag,
        "digest": target_digest,
        "parabricks_container": f"{repository_url}@{target_digest}",
    },
}
Path(receipt_path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "Mirrored ${repository_url}@${target_digest}"
echo "Wrote ${RECEIPT_PATH}"
echo
echo "To pin this image in the P5en workspace:"
echo "TF_VAR_parabricks_container='${repository_url}@${target_digest}' PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:plan:use2"
