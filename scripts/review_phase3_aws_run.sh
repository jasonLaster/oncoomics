#!/usr/bin/env bash
set -euo pipefail

RUN_NAME="${1:?usage: scripts/review_phase3_aws_run.sh RUN_NAME RUN_DIR [interval_seconds]}"
RUN_DIR="${2:?usage: scripts/review_phase3_aws_run.sh RUN_NAME RUN_DIR [interval_seconds]}"
INTERVAL="${3:-600}"
REGION="${AWS_REGION:-us-east-1}"
LOG_GROUP="${AWS_BATCH_LOG_GROUP:-/aws/batch/diana-omics-prod-use1}"
SPOT_QUEUE="${AWS_BATCH_SPOT_QUEUE:-diana-omics-prod-use1-spot}"
ONDEMAND_QUEUE="${AWS_BATCH_ONDEMAND_QUEUE:-diana-omics-prod-use1-ondemand}"
REVIEW_LOG="$RUN_DIR/review.log"
START_MARKER="$RUN_DIR/start_epoch_ms"

mkdir -p "$RUN_DIR"
if [[ ! -f "$START_MARKER" ]]; then
  python3 - <<'PY' > "$START_MARKER"
import time
print(int(time.time() * 1000))
PY
fi

START_EPOCH_MS="$(cat "$START_MARKER")"

list_queue_jobs() {
  local queue="$1"
  local status="$2"
  aws batch list-jobs \
    --region "$REGION" \
    --job-queue "$queue" \
    --job-status "$status" \
    --max-results 100 \
    --output json |
    jq -r --argjson start "$START_EPOCH_MS" '
      .jobSummaryList[]
      | select(.createdAt >= $start)
      | select(.jobName | test("PHASE3_WGS|phase3"; "i"))
      | [.createdAt, .status, .jobName, .jobId] | @tsv
    ' 2>/dev/null || true
}

recent_jobs() {
  for queue in "$SPOT_QUEUE" "$ONDEMAND_QUEUE"; do
    for status in SUBMITTED PENDING RUNNABLE STARTING RUNNING SUCCEEDED FAILED; do
      list_queue_jobs "$queue" "$status"
    done
  done | sort -n
}

tail_job_logs() {
  recent_jobs |
    awk '$2 == "RUNNING" || $2 == "FAILED" {print $4}' |
    tail -6 |
    while read -r job_id; do
      [[ -z "$job_id" ]] && continue
      local stream
      stream="$(aws batch describe-jobs --region "$REGION" --jobs "$job_id" --query 'jobs[0].container.logStreamName' --output text 2>/dev/null || true)"
      [[ -z "$stream" || "$stream" == "None" || "$stream" == "null" ]] && continue
      echo "== CloudWatch tail job=$job_id stream=$stream =="
      aws logs tail "$LOG_GROUP" --region "$REGION" --log-stream-name-prefix "$stream" --since 12m || true
    done
}

trace_summary() {
  local trace="$RUN_DIR/trace.tsv"
  [[ -f "$trace" ]] || return 0
  echo "== Trace summary =="
  awk -F '\t' '
    NR == 1 { next }
    {
      status[$5] += 1
      line = $3 "\t" $4 "\t" $5 "\t" $7 "\t" $8 "\t" $10 "\t" $11
      rows[++n] = line
    }
    END {
      for (s in status) print "status", s, status[s]
      start = n - 10
      if (start < 1) start = 1
      for (i = start; i <= n; i++) print rows[i]
    }
  ' "$trace"
}

review_once() {
  {
    echo
    echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) run=$RUN_NAME ====="
    echo "== Recent Batch jobs =="
    recent_jobs || true
    trace_summary || true
    if [[ -f "$RUN_DIR/nextflow.log" ]]; then
      echo "== Nextflow tail =="
      tail -80 "$RUN_DIR/nextflow.log"
    fi
    tail_job_logs || true
  } >> "$REVIEW_LOG" 2>&1
}

while true; do
  review_once
  if [[ -f "$RUN_DIR/nextflow.exit" ]]; then
    break
  fi
  sleep "$INTERVAL"
done
