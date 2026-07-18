#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_WORKSPACE="${DIANA_AWS_TERRAFORM_WORKSPACE:-}"
TAG="${AWS_IMAGE_TAG:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD)}"

restore_workspace() {
  if [[ -n "${ORIGINAL_WORKSPACE:-}" ]]; then
    terraform -chdir="${ROOT_DIR}/infra/aws" workspace select "${ORIGINAL_WORKSPACE}" >/dev/null
  fi
}

if [[ -n "${TARGET_WORKSPACE}" ]]; then
  ORIGINAL_WORKSPACE="$(terraform -chdir="${ROOT_DIR}/infra/aws" workspace show)"
  if [[ "${ORIGINAL_WORKSPACE}" != "${TARGET_WORKSPACE}" ]]; then
    terraform -chdir="${ROOT_DIR}/infra/aws" workspace select "${TARGET_WORKSPACE}" >/dev/null
    trap restore_workspace EXIT
  fi
fi

REGION="${AWS_REGION:-$(terraform -chdir="${ROOT_DIR}/infra/aws" output -raw region)}"
repository_url="$(terraform -chdir="${ROOT_DIR}/infra/aws" output -raw ecr_repository_url)"
registry="${repository_url%/*}"

echo "Building diana-omics:${TAG}"
docker build -t "diana-omics:${TAG}" "${ROOT_DIR}"

echo "Logging in to ${registry}"
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${registry}"

echo "Pushing ${repository_url}:${TAG}"
docker tag "diana-omics:${TAG}" "${repository_url}:${TAG}"
docker push "${repository_url}:${TAG}"

echo "Pushed ${repository_url}:${TAG}"
