#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_WORKSPACE="${DIANA_AWS_TERRAFORM_WORKSPACE:-}"
SOURCE_IMAGE="${PARABRICKS_SOURCE_IMAGE:-${1:-}}"
PLATFORM="${PARABRICKS_PLATFORM:-linux/amd64}"
RECEIPT_PATH="${PARABRICKS_MIRROR_RECEIPT:-${ROOT_DIR}/results/phase3_wgs_fast/parabricks_mirror_receipt.json}"
DIANA_PARABRICKS_DOCKERFILE="${ROOT_DIR}/infra/aws/Dockerfile.parabricks"

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
[[ "${SOURCE_IMAGE}" =~ ^[^[:space:]]+@sha256:[0-9a-fA-F]{64}$ ]] || die "PARABRICKS_SOURCE_IMAGE must be pinned as <registry>/<image>@sha256:<64 hex>"
[[ "${PLATFORM}" == "linux/amd64" ]] || die "PARABRICKS_PLATFORM must be linux/amd64"
[[ -f "${DIANA_PARABRICKS_DOCKERFILE}" && ! -L "${DIANA_PARABRICKS_DOCKERFILE}" ]] \
  || die "Diana Parabricks Dockerfile must be a real file: ${DIANA_PARABRICKS_DOCKERFILE}"

source_digest="${SOURCE_IMAGE##*@}"
source_digest_hex="${source_digest#sha256:}"
source_digest_hex="$(printf '%s' "${source_digest_hex}" | tr 'A-F' 'a-f')"
source_digest="sha256:${source_digest_hex}"

dirty_source="$(git -C "${ROOT_DIR}" status --porcelain --untracked-files=all -- . \
  ':(exclude)artifacts/**' \
  ':(exclude)bam/**' \
  ':(exclude)data/processed/**' \
  ':(exclude)data/raw/**' \
  ':(exclude)logs/**' \
  ':(exclude)nextflow-out/**' \
  ':(exclude)results/**' \
  ':(exclude)tmp/**' \
  ':(exclude)work/**' \
  ':(exclude)infra/aws/terraform.tfstate.d/**' \
  ':(exclude)infra/aws/*.tfplan' \
  ':(exclude)infra/aws/*.tfstate' \
  ':(exclude)infra/aws/*.tfstate.*' \
  ':(exclude)infra/aws/nextflow.aws*.json')"
dirty_included_results="$(git -C "${ROOT_DIR}" status --porcelain --untracked-files=all -- \
  results/full_wes_benchmark/full_wes_benchmark_summary.json)"
if [[ -n "${dirty_source}" && -n "${dirty_included_results}" ]]; then
  dirty_source="${dirty_source}"$'\n'"${dirty_included_results}"
elif [[ -n "${dirty_included_results}" ]]; then
  dirty_source="${dirty_included_results}"
fi
[[ -z "${dirty_source}" ]] || die "commit or revert source changes before mirroring the Diana Parabricks runtime:
${dirty_source}"

diana_revision="$(git -C "${ROOT_DIR}" rev-parse --verify HEAD)"
remote_refs="$(git -C "${ROOT_DIR}" for-each-ref \
  --format='%(refname:short)' \
  --contains "${diana_revision}" \
  refs/remotes)"
[[ -n "${remote_refs}" ]] || die "push ${diana_revision} to a remote before mirroring the Diana Parabricks runtime"

diana_revision_short="${diana_revision:0:12}"
dockerfile_sha256="sha256:$(shasum -a 256 "${DIANA_PARABRICKS_DOCKERFILE}" | awk '{print $1}')"
target_tag="sha256-${source_digest_hex}-diana-${diana_revision_short}"
[[ "${target_tag}" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]] || die "internal Parabricks mirror tag is not a valid ECR image tag"

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

describe_target_digest() {
  aws ecr describe-images \
    --region "${REGION}" \
    --repository-name "${repository_name}" \
    --image-ids "imageTag=${target_tag}" \
    --query 'imageDetails[0].imageDigest' \
    --output text
}

target_digest=""
if existing_target_digest="$(describe_target_digest 2>&1)"; then
  target_digest="${existing_target_digest}"
  echo "Reusing immutable ${target_image}"
else
  [[ "${existing_target_digest}" == *ImageNotFound* ]] || die "unable to inspect ${target_image}: ${existing_target_digest}"

  echo "Pulling ${PLATFORM} ${SOURCE_IMAGE}"
  docker pull --platform "${PLATFORM}" "${SOURCE_IMAGE}"

  echo "Logging in to ${registry}"
  aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${registry}"

  echo "Building Diana Parabricks runtime ${target_image}"
  docker build \
    --platform "${PLATFORM}" \
    --build-arg "PARABRICKS_BASE_IMAGE=${SOURCE_IMAGE}" \
    -f "${DIANA_PARABRICKS_DOCKERFILE}" \
    -t "${target_image}" \
    "${ROOT_DIR}"

  echo "Pushing ${target_image}"
  docker push "${target_image}"

  target_digest="$(describe_target_digest)"
fi
[[ "${target_digest}" =~ ^sha256:[0-9a-fA-F]{64}$ ]] || die "ECR did not return a digest for ${target_image}"

python3 - "${RECEIPT_PATH}" "${SOURCE_IMAGE}" "${source_digest}" "${PLATFORM}" "${REGION}" \
  "${repository_url}" "${target_tag}" "${target_digest}" "${diana_revision}" "${dockerfile_sha256}" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    receipt_path,
    source_image,
    source_digest,
    platform,
    region,
    repository_url,
    target_tag,
    target_digest,
    diana_revision,
    dockerfile_sha256,
) = sys.argv[1:]
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
    "diana_omics": {
        "git_commit": diana_revision,
        "dockerfile_sha256": dockerfile_sha256,
    },
}


def require_safe_receipt_path(path: Path) -> None:
    if path.is_symlink():
        raise SystemExit(f"Parabricks mirror receipt output may not be a symlink: {path}")
    if path.exists() and not path.is_file():
        raise SystemExit(f"Parabricks mirror receipt output is not a file: {path}")

    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        next_parent = parent.parent
        if next_parent == parent:
            raise SystemExit(f"Parabricks mirror receipt parent does not exist: {path.parent}")
        parent = next_parent

    if parent.is_symlink():
        raise SystemExit(f"Parabricks mirror receipt parent may not be a symlink: {parent}")
    if parent.exists() and not parent.is_dir():
        raise SystemExit(f"Parabricks mirror receipt parent is not a directory: {parent}")


receipt_path = Path(receipt_path)
require_safe_receipt_path(receipt_path)
receipt_path.parent.mkdir(parents=True, exist_ok=True)
temporary_path = receipt_path.with_name(f".{receipt_path.name}.tmp")
if temporary_path.exists() or temporary_path.is_symlink():
    raise SystemExit(f"Temporary Parabricks mirror receipt already exists: {temporary_path}")
temporary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
require_safe_receipt_path(receipt_path)
temporary_path.replace(receipt_path)
PY

PARABRICKS_MIRROR_RECEIPT="${RECEIPT_PATH}" PYTHONPATH="${ROOT_DIR}/src" \
  /usr/bin/python3 -m diana_omics verify:parabricks-mirror-receipt

echo "Mirrored ${repository_url}@${target_digest}"
echo "Wrote ${RECEIPT_PATH}"
echo
echo "To pin this image in the P5en workspace:"
echo "TF_VAR_parabricks_container='${repository_url}@${target_digest}' PYTHONPATH=src /usr/bin/python3 -m diana_omics infra:aws:plan:use2"
