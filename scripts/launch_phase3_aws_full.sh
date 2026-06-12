#!/usr/bin/env bash
set -euo pipefail

RUN_NAME="${1:?usage: scripts/launch_phase3_aws_full.sh RUN_NAME RUN_DIR CONTAINER}"
RUN_DIR="${2:?usage: scripts/launch_phase3_aws_full.sh RUN_NAME RUN_DIR CONTAINER}"
CONTAINER="${3:?usage: scripts/launch_phase3_aws_full.sh RUN_NAME RUN_DIR CONTAINER}"

mkdir -p "$RUN_DIR"

set +e
nextflow \
  -log "$RUN_DIR/nextflow.log" \
  run main.nf \
  -profile awsbatch_spot \
  -params-file infra/aws/nextflow.aws.json \
  -name "$RUN_NAME" \
  --container "$CONTAINER" \
  --workflow phase3_wgs \
  --phase3_reads full \
  --phase3_source_mode aws_sra \
  --phase3_fetch_cpus 8 \
  --phase3_fetch_memory "28 GB" \
  --phase3_ref_cpus 16 \
  --phase3_ref_memory "28 GB" \
  --phase3_align_cpus 16 \
  --phase3_align_memory "96 GB" \
  --phase3_downstream_cpus 16 \
  --phase3_downstream_memory "64 GB" \
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
