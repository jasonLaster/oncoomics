#!/usr/bin/env bash
set -euo pipefail

LOG_GROUP="${AWS_BATCH_LOG_GROUP:-/aws/batch/diana-omics-prod}"
REGION="${AWS_REGION:-us-west-1}"
INTERVAL="${AWS_MONITOR_INTERVAL:-60}"
SINCE="${AWS_LOG_SINCE:-2m}"
FOLLOW=0
ONCE=0

usage() {
  cat <<'USAGE'
Usage: infra/aws/monitor-batch-job.sh JOB_ID [--once] [--follow] [--interval SECONDS] [--since DURATION]

Poll an AWS Batch job and its CloudWatch log stream.

Examples:
  infra/aws/monitor-batch-job.sh 5f6c56d5-3e9d-4c56-8346-2942a225211c
  infra/aws/monitor-batch-job.sh 5f6c56d5-3e9d-4c56-8346-2942a225211c --once
  infra/aws/monitor-batch-job.sh 5f6c56d5-3e9d-4c56-8346-2942a225211c --follow
  AWS_REGION=us-west-1 AWS_BATCH_LOG_GROUP=/aws/batch/diana-omics-prod infra/aws/monitor-batch-job.sh JOB_ID
USAGE
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

JOB_ID="$1"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --follow)
      FOLLOW=1
      shift
      ;;
    --once)
      ONCE=1
      shift
      ;;
    --interval)
      INTERVAL="${2:?missing interval value}"
      shift 2
      ;;
    --since)
      SINCE="${2:?missing since value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

job_json() {
  aws batch describe-jobs --region "$REGION" --jobs "$JOB_ID" --output json
}

job_field() {
  aws batch describe-jobs --region "$REGION" --jobs "$JOB_ID" --query "$1" --output text
}

print_status() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
  aws batch describe-jobs \
    --region "$REGION" \
    --jobs "$JOB_ID" \
    --query 'jobs[0].{jobName:jobName,status:status,statusReason:statusReason,createdAt:createdAt,startedAt:startedAt,stoppedAt:stoppedAt,exitCode:container.exitCode,reason:container.reason,queue:jobQueue,logStream:container.logStreamName,image:container.image}' \
    --output json

  queue_arn="$(job_field 'jobs[0].jobQueue')"
  if [[ "$queue_arn" != "None" && "$queue_arn" != "null" && -n "$queue_arn" ]]; then
    queue_name="${queue_arn##*/}"
    aws batch describe-job-queues \
      --region "$REGION" \
      --job-queues "$queue_name" \
      --query 'jobQueues[0].computeEnvironmentOrder[].computeEnvironment' \
      --output text |
      tr '\t' '\n' |
      while read -r compute_environment; do
        [[ -z "$compute_environment" || "$compute_environment" == "None" ]] && continue
        aws batch describe-compute-environments \
          --region "$REGION" \
          --compute-environments "$compute_environment" \
          --query 'computeEnvironments[0].{name:computeEnvironmentName,status:status,state:state,desired:computeResources.desiredvCpus,min:computeResources.minvCpus,max:computeResources.maxvCpus}' \
          --output json
      done
  fi

  aws ec2 describe-instances \
    --region "$REGION" \
    --filters 'Name=tag:Name,Values=diana-omics-prod-batch' 'Name=instance-state-name,Values=pending,running' \
    --query 'Reservations[].Instances[].{id:InstanceId,state:State.Name,type:InstanceType,launch:LaunchTime}' \
    --output json
}

tail_logs_once() {
  local log_stream="$1"
  if [[ "$log_stream" == "None" || "$log_stream" == "null" || -z "$log_stream" ]]; then
    echo "CloudWatch log stream is not assigned yet."
    return
  fi

  aws logs tail "$LOG_GROUP" \
    --region "$REGION" \
    --log-stream-name-prefix "$log_stream" \
    --since "$SINCE"
}

if [[ "$FOLLOW" -eq 1 ]]; then
  print_status
  log_stream="$(job_field 'jobs[0].container.logStreamName')"
  while [[ "$log_stream" == "None" || "$log_stream" == "null" || -z "$log_stream" ]]; do
    sleep "$INTERVAL"
    print_status
    log_stream="$(job_field 'jobs[0].container.logStreamName')"
  done

  aws logs tail "$LOG_GROUP" \
    --region "$REGION" \
    --log-stream-name-prefix "$log_stream" \
    --since "$SINCE" \
    --follow
else
  while true; do
    print_status
    log_stream="$(job_field 'jobs[0].container.logStreamName')"
    tail_logs_once "$log_stream"
    status="$(job_field 'jobs[0].status')"
    if [[ "$ONCE" -eq 1 || "$status" == "SUCCEEDED" || "$status" == "FAILED" ]]; then
      break
    fi
    sleep "$INTERVAL"
  done
fi
