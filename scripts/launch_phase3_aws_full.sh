#!/usr/bin/env bash
set -euo pipefail

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
PHASE3_BWA_THREADS="${PHASE3_BWA_THREADS:-0}"
PHASE3_SORT_THREADS="${PHASE3_SORT_THREADS:-0}"

mkdir -p "$RUN_DIR"

set +e
nextflow \
  -log "$RUN_DIR/nextflow.log" \
  run main.nf \
  -profile "$AWS_PROFILE" \
  -params-file infra/aws/nextflow.aws.json \
  -name "$RUN_NAME" \
  --container "$CONTAINER" \
  --aws_max_retries "$AWS_MAX_RETRIES" \
  --workflow phase3_wgs \
  --phase3_reads full \
  --phase3_source_mode aws_sra \
  --phase3_fetch_cpus "$PHASE3_FETCH_CPUS" \
  --phase3_fetch_memory "$PHASE3_FETCH_MEMORY" \
  --phase3_ref_cpus "$PHASE3_REF_CPUS" \
  --phase3_ref_memory "$PHASE3_REF_MEMORY" \
  --phase3_align_cpus "$PHASE3_ALIGN_CPUS" \
  --phase3_align_memory "$PHASE3_ALIGN_MEMORY" \
  --phase3_downstream_cpus "$PHASE3_DOWNSTREAM_CPUS" \
  --phase3_downstream_memory "$PHASE3_DOWNSTREAM_MEMORY" \
  --phase3_bwa_threads "$PHASE3_BWA_THREADS" \
  --phase3_sort_threads "$PHASE3_SORT_THREADS" \
  --phase3_fetch_concurrency 8 \
  --phase3_s3_range_concurrency 8 \
  --phase3_sra_run_concurrency 2 \
  --phase3_cache_upload_workers 4 \
  --phase3_alignment_cache_workers 2 \
  --phase3_fastq_stats_mode metadata \
  --phase3_include_wes false \
  --phase3_prereq_mode minimal \
  -with-trace "$RUN_DIR/trace.tsv" \
  -with-report "$RUN_DIR/report.html" \
  -with-timeline "$RUN_DIR/timeline.html"
code=$?
set -e

echo "$code" > "$RUN_DIR/nextflow.exit"
exit "$code"
