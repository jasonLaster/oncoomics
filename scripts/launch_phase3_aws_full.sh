#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_NAME="${1:?usage: scripts/launch_phase3_aws_full.sh RUN_NAME RUN_DIR CONTAINER}"
RUN_DIR="${2:?usage: scripts/launch_phase3_aws_full.sh RUN_NAME RUN_DIR CONTAINER}"
CONTAINER="${3:?usage: scripts/launch_phase3_aws_full.sh RUN_NAME RUN_DIR CONTAINER}"
AWS_PROFILE="${PHASE3_AWS_PROFILE:-awsbatch_spot}"
AWS_MAX_RETRIES="${AWS_MAX_RETRIES:-0}"
PHASE3_FETCH_CPUS="${PHASE3_FETCH_CPUS:-8}"
PHASE3_FETCH_MEMORY="${PHASE3_FETCH_MEMORY:-28 GB}"
PHASE3_REF_CPUS="${PHASE3_REF_CPUS:-16}"
PHASE3_REF_MEMORY="${PHASE3_REF_MEMORY:-28 GB}"
PHASE3_ALIGN_CPUS="${PHASE3_ALIGN_CPUS:-16}"
PHASE3_ALIGN_MEMORY="${PHASE3_ALIGN_MEMORY:-96 GB}"
PHASE3_DOWNSTREAM_CPUS="${PHASE3_DOWNSTREAM_CPUS:-16}"
PHASE3_DOWNSTREAM_MEMORY="${PHASE3_DOWNSTREAM_MEMORY:-64 GB}"
PHASE3_ALIGNER="${PHASE3_ALIGNER:-bwa}"
PHASE3_BWA_THREADS="${PHASE3_BWA_THREADS:-0}"
PHASE3_SORT_THREADS="${PHASE3_SORT_THREADS:-0}"
PHASE3_ALIGN_INPUT_MODE="${PHASE3_ALIGN_INPUT_MODE:-local_fastq}"
PHASE3_ALIGN_PROFILE_MODE="${PHASE3_ALIGN_PROFILE_MODE:-pipe}"
PHASE3_SCATTER_OUTPUT_MODE="${PHASE3_SCATTER_OUTPUT_MODE:-merged_bam}"
PHASE3_SHARD_INPUT_MODE="${PHASE3_SHARD_INPUT_MODE:-fastq_cache}"
PHASE3_FORCE="${PHASE3_FORCE:-0}"
PHASE3_FORCE_SHARD_ALIGNMENT="${PHASE3_FORCE_SHARD_ALIGNMENT:-0}"
PHASE3_SCATTER_ROLE="${PHASE3_SCATTER_ROLE:-tumor}"
PHASE3_SHARD_COUNT="${PHASE3_SHARD_COUNT:-8}"
PHASE3_BAM_VALIDATION_MODE="${PHASE3_BAM_VALIDATION_MODE:-full}"
PHASE3_COVERAGE_CNV_MODE="${PHASE3_COVERAGE_CNV_MODE:-full}"
PHASE3_PREREQ_MODE="${PHASE3_PREREQ_MODE:-minimal}"
PHASE3_WORKFLOW="${PHASE3_WORKFLOW:-phase3_wgs}"
PHASE3_ALIGNMENT_CACHE_WORKERS="${PHASE3_ALIGNMENT_CACHE_WORKERS:-2}"
PHASE3_OUTDIR="${PHASE3_OUTDIR:-}"
ALLOW_LEGACY_PHASE3_AWS_FULL="${ALLOW_LEGACY_PHASE3_AWS_FULL:-}"

if [[ "$PHASE3_WORKFLOW" == "phase3_wgs" || "$PHASE3_WORKFLOW" == "phase3_wgs_monolith" ]]; then
  if [[ "$ALLOW_LEGACY_PHASE3_AWS_FULL" != "YES" ]]; then
    cat >&2 <<'EOF'
Refusing to launch a legacy full-source Phase 3 WGS AWS CPU workflow.

The stopped Diana WGS evidence run should resume through phase3_wgs_fast on the
GPU/distributed architecture, not another monolithic CPU retry. Set
ALLOW_LEGACY_PHASE3_AWS_FULL=YES only for an explicitly approved legacy public
SEQC2/HCC1395 run.
EOF
    exit 64
  fi
fi

bash "${ROOT_DIR}/infra/aws/check-daily-cost-guard.sh" \
  "${DIANA_AWS_CONFIG:-${ROOT_DIR}/infra/aws/nextflow.aws.json}"

mkdir -p "$RUN_DIR"

if [[ -z "$PHASE3_OUTDIR" && -f infra/aws/nextflow.aws.json ]]; then
  PHASE3_OUTDIR="$(python3 - "$RUN_NAME" <<'PY'
import json
import sys
from pathlib import Path

run_name = sys.argv[1]
params = json.loads(Path("infra/aws/nextflow.aws.json").read_text(encoding="utf-8"))
base = str(params.get("aws_results_dir") or "").rstrip("/")
print(f"{base}/{run_name}" if base else "")
PY
)"
fi

nextflow_args=(
  -log "$RUN_DIR/nextflow.log"
  run main.nf
  -profile "$AWS_PROFILE"
  -params-file infra/aws/nextflow.aws.json
  -name "$RUN_NAME"
  --container "$CONTAINER"
)
if [[ -n "$PHASE3_OUTDIR" ]]; then
  nextflow_args+=(--outdir "$PHASE3_OUTDIR")
fi
nextflow_args+=(
  --aws_max_retries "$AWS_MAX_RETRIES"
  --workflow "$PHASE3_WORKFLOW"
  --phase3_reads full
  --allow_legacy_phase3_cpu_full true
  --phase3_source_mode aws_sra
  --phase3_fetch_cpus "$PHASE3_FETCH_CPUS"
  --phase3_fetch_memory "$PHASE3_FETCH_MEMORY"
  --phase3_ref_cpus "$PHASE3_REF_CPUS"
  --phase3_ref_memory "$PHASE3_REF_MEMORY"
  --phase3_align_cpus "$PHASE3_ALIGN_CPUS"
  --phase3_align_memory "$PHASE3_ALIGN_MEMORY"
  --phase3_downstream_cpus "$PHASE3_DOWNSTREAM_CPUS"
  --phase3_downstream_memory "$PHASE3_DOWNSTREAM_MEMORY"
  --phase3_aligner "$PHASE3_ALIGNER"
  --phase3_bwa_threads "$PHASE3_BWA_THREADS"
  --phase3_sort_threads "$PHASE3_SORT_THREADS"
  --phase3_align_input_mode "$PHASE3_ALIGN_INPUT_MODE"
  --phase3_align_profile_mode "$PHASE3_ALIGN_PROFILE_MODE"
  --phase3_scatter_output_mode "$PHASE3_SCATTER_OUTPUT_MODE"
  --phase3_shard_input_mode "$PHASE3_SHARD_INPUT_MODE"
  --phase3_force "$PHASE3_FORCE"
  --phase3_force_shard_alignment "$PHASE3_FORCE_SHARD_ALIGNMENT"
  --phase3_scatter_role "$PHASE3_SCATTER_ROLE"
  --phase3_shard_count "$PHASE3_SHARD_COUNT"
  --phase3_bam_validation_mode "$PHASE3_BAM_VALIDATION_MODE"
  --phase3_coverage_cnv_mode "$PHASE3_COVERAGE_CNV_MODE"
  --phase3_fetch_concurrency 8
  --phase3_s3_range_concurrency 8
  --phase3_sra_run_concurrency 2
  --phase3_cache_upload_workers 4
  --phase3_alignment_cache_workers "$PHASE3_ALIGNMENT_CACHE_WORKERS"
  --phase3_fastq_stats_mode metadata
  --phase3_include_wes false
  --phase3_prereq_mode "$PHASE3_PREREQ_MODE"
  -with-trace "$RUN_DIR/trace.tsv"
  -with-report "$RUN_DIR/report.html"
  -with-timeline "$RUN_DIR/timeline.html"
)

set +e
nextflow "${nextflow_args[@]}"
code=$?
set -e

echo "$code" > "$RUN_DIR/nextflow.exit"
exit "$code"
