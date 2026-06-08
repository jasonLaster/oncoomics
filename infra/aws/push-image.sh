#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REGION="${AWS_REGION:-us-west-1}"
TAG="${AWS_IMAGE_TAG:-$(git -C "${ROOT_DIR}" rev-parse --short HEAD)}"

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
