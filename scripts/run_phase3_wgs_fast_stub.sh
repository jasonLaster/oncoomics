#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${ROOT}/.codex-tmp"
RUN_ROOT="$(mktemp -d "${ROOT}/.codex-tmp/phase3-fast-stub.XXXXXX")"
RECEIPTS_DIR="${RUN_ROOT}/receipts"
LOG_DIR="${RUN_ROOT}/logs"
WORK_DIR="${RUN_ROOT}/work"
OUT_DIR="${RUN_ROOT}/out"
FORBIDDEN_TOKENS_JSON='["stubbed-private-token"]'
mkdir -p "${RECEIPTS_DIR}" "${LOG_DIR}" "${WORK_DIR}" "${OUT_DIR}"

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
echo "Writing Phase 3 fast stub outputs under ${RUN_ROOT}"
nextflow -log "${LOG_DIR}/nextflow.log" run main.nf -profile local \
  -work-dir "${WORK_DIR}" \
  --workflow phase3_wgs_fast \
  --outdir "${OUT_DIR}" \
  --phase3_fast_private_freeze_receipt "${RECEIPTS_DIR}/private-freeze.json" \
  --phase3_fast_private_sha256_receipt "${RECEIPTS_DIR}/private-sha256.json" \
  --phase3_fast_reference_freeze_receipt "${RECEIPTS_DIR}/reference-freeze.json" \
  --phase3_fast_reference_sha256_receipt "${RECEIPTS_DIR}/reference-sha256.json" \
  --phase3_fast_bam_validation_receipt "${RECEIPTS_DIR}/bam-validation.json" \
  --phase3_fast_contig_compatibility_receipt "${RECEIPTS_DIR}/contig-compatibility.json" \
  --phase3_fast_caller_resource_receipt "${RECEIPTS_DIR}/caller-resources.json" \
  --phase3_fast_parameter_sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --parabricks_container \
    172630973301.dkr.ecr.us-east-2.amazonaws.com/diana-omics/parabricks@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --phase3_fast_parabricks_container_digest sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --phase3_fast_parabricks_version stub-parabricks \
  --phase3_fast_sequenza_female true \
  --phase3_fast_cache_prefix s3://stubbed-phase3-fast-cache/wgs-v2/ \
  --phase3_fast_cache_kms_key_arn arn:aws:kms:us-east-2:172630973301:key/00000000-0000-0000-0000-000000000000 \
  --phase3_fast_replication_mode apply \
  --phase3_fast_small_variant_mode execute \
  --phase3_fast_parabricks_cpus 1 \
  --phase3_fast_parabricks_memory '1 GB' \
  --phase3_fast_generated_at 2026-07-16T03:31:01+00:00 \
  --phase3_fast_forbidden_tokens_json "${FORBIDDEN_TOKENS_JSON}" \
  -stub-run

echo "Validating Phase 3 fast stub private report packets"
PYTHONPATH="${ROOT}/src:${ROOT}/scripts" \
  python3 "${ROOT}/scripts/validate_phase3_fast_report_packets.py" \
    --deterministic-report-dir \
      "${OUT_DIR}/phase3_wgs_fast/deterministic_report/workspace/results/phase3_wgs_fast/deterministic_report" \
    --rosalind-report-dir \
      "${OUT_DIR}/phase3_wgs_fast/rosalind_hrd/workspace/results/rosalind_hrd/diana_wgs/diana-wgs-hrd-20260716T033101Z" \
    --facets-scarhrd-report-dir \
      "${OUT_DIR}/phase3_wgs_fast/blocked_crosschecks/workspace/results/phase3_wgs_fast/blocked_crosschecks/facets_scarhrd_blocked" \
    --oncoanalyser-chord-report-dir \
      "${OUT_DIR}/phase3_wgs_fast/blocked_crosschecks/workspace/results/phase3_wgs_fast/blocked_crosschecks/oncoanalyser_chord_blocked" \
    --hrdetect-report-dir \
      "${OUT_DIR}/phase3_wgs_fast/blocked_crosschecks/workspace/results/phase3_wgs_fast/blocked_crosschecks/hrdetect_blocked" \
    --forbidden-tokens-json "${FORBIDDEN_TOKENS_JSON}" \
    --output "${OUT_DIR}/phase3_wgs_fast/report_packet_validation.json"
