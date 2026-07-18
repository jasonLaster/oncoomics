#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECEIPTS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/diana-phase3-fast-stub.XXXXXX")"

cleanup() {
  rm -rf "${RECEIPTS_DIR}"
}
trap cleanup EXIT

for receipt in \
  private-freeze \
  private-sha256 \
  reference-freeze \
  reference-sha256 \
  bam-validation \
  contig-compatibility \
  caller-resources; do
  : > "${RECEIPTS_DIR}/${receipt}.json"
done

cd "${ROOT}"
mkdir -p logs
nextflow -log logs/nextflow.log run main.nf -profile local \
  --workflow phase3_wgs_fast \
  --phase3_fast_private_freeze_receipt "${RECEIPTS_DIR}/private-freeze.json" \
  --phase3_fast_private_sha256_receipt "${RECEIPTS_DIR}/private-sha256.json" \
  --phase3_fast_reference_freeze_receipt "${RECEIPTS_DIR}/reference-freeze.json" \
  --phase3_fast_reference_sha256_receipt "${RECEIPTS_DIR}/reference-sha256.json" \
  --phase3_fast_bam_validation_receipt "${RECEIPTS_DIR}/bam-validation.json" \
  --phase3_fast_contig_compatibility_receipt "${RECEIPTS_DIR}/contig-compatibility.json" \
  --phase3_fast_caller_resource_receipt "${RECEIPTS_DIR}/caller-resources.json" \
  --phase3_fast_parameter_sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --phase3_fast_parabricks_container_digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --phase3_fast_parabricks_version stub-parabricks \
  --phase3_fast_cache_prefix s3://stubbed-phase3-fast-cache/wgs-v2/ \
  --phase3_fast_cache_kms_key_arn arn:aws:kms:us-east-2:172630973301:key/00000000-0000-0000-0000-000000000000 \
  --phase3_fast_replication_mode apply \
  --phase3_fast_small_variant_mode execute \
  --phase3_fast_parabricks_cpus 1 \
  --phase3_fast_parabricks_memory '1 GB' \
  --phase3_fast_forbidden_tokens_json '["stubbed-private-token"]' \
  -stub-run
