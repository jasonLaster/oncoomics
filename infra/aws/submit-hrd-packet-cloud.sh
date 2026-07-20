#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_PATH="${DIANA_AWS_CONFIG:-${ROOT_DIR}/infra/aws/nextflow.aws.json}"

usage() {
  cat <<'USAGE'
Usage: infra/aws/submit-hrd-packet-cloud.sh [options]

Submit a bounded AWS Batch job that downloads a pushed repo archive inside AWS,
runs the Rosalind HRD packet builder against a materialized artifact root, and
uploads the packet outputs to the configured results bucket.

Options:
  --dry-run                         Print the AWS Batch payload without submitting.
  --run-id ID                       Packet run id. Defaults to cloud-selective5-<UTC timestamp>.
  --sample-set SETS                 Comma-separated packet sample sets. Defaults to hcc1395_wgs.
  --artifact-root-rel PATH          Repo-relative materialized artifact root. Defaults to artifacts/phase3_wgs_selective5.
  --source-commit SHA               Git commit to download in AWS. Defaults to current HEAD.
  --source-archive-url URL          Archive URL to download in AWS. Defaults to the oncoomics GitHub archive for the commit.
  --s3-prefix URI                   Output S3 prefix. Defaults to <aws_results_dir>/rosalind_hrd/<run-id>.
  --queue NAME_OR_ARN               AWS Batch queue. Defaults to aws_ondemand_queue from infra/aws/nextflow.aws.json.
  --job-definition ARN              AWS Batch job definition. Defaults to active definition matching the configured container image.
  --region REGION                   AWS region. Defaults to aws_region from infra/aws/nextflow.aws.json or us-east-1.
  -h, --help                        Show this help.

Environment overrides:
  ROSALIND_HRD_RUN_ID, ROSALIND_HRD_SAMPLE_SET, ROSALIND_HRD_ARTIFACT_ROOT_REL
  SOURCE_COMMIT, SOURCE_ARCHIVE_URL, S3_PREFIX
  AWS_REGION, AWS_BATCH_JOB_QUEUE, AWS_BATCH_JOB_DEFINITION
  HRD_PACKET_BATCH_VCPUS, HRD_PACKET_BATCH_MEMORY, HRD_PACKET_BATCH_TIMEOUT
USAGE
}

config_value() {
  local key="$1"
  local default_value="${2:-}"
  python3 - "$CONFIG_PATH" "$key" "$default_value" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
default = sys.argv[3]
if not path.exists():
    print(default)
    raise SystemExit(0)
try:
    data = json.loads(path.read_text())
except json.JSONDecodeError:
    print(default)
    raise SystemExit(0)
print(data.get(key) or default)
PY
}

DRY_RUN=0
RUN_ID="${ROSALIND_HRD_RUN_ID:-}"
SAMPLE_SET="${ROSALIND_HRD_SAMPLE_SET:-hcc1395_wgs}"
ARTIFACT_ROOT_REL="${ROSALIND_HRD_ARTIFACT_ROOT_REL:-artifacts/phase3_wgs_selective5}"
SOURCE_COMMIT="${SOURCE_COMMIT:-}"
SOURCE_ARCHIVE_URL="${SOURCE_ARCHIVE_URL:-}"
S3_PREFIX="${S3_PREFIX:-}"
REGION="${AWS_REGION:-}"
QUEUE="${AWS_BATCH_JOB_QUEUE:-}"
JOB_DEFINITION="${AWS_BATCH_JOB_DEFINITION:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --run-id)
      RUN_ID="${2:?missing run id}"
      shift 2
      ;;
    --sample-set)
      SAMPLE_SET="${2:?missing sample set}"
      shift 2
      ;;
    --artifact-root-rel)
      ARTIFACT_ROOT_REL="${2:?missing artifact root path}"
      shift 2
      ;;
    --source-commit)
      SOURCE_COMMIT="${2:?missing source commit}"
      shift 2
      ;;
    --source-archive-url)
      SOURCE_ARCHIVE_URL="${2:?missing source archive url}"
      shift 2
      ;;
    --s3-prefix)
      S3_PREFIX="${2:?missing s3 prefix}"
      shift 2
      ;;
    --queue)
      QUEUE="${2:?missing queue}"
      shift 2
      ;;
    --job-definition)
      JOB_DEFINITION="${2:?missing job definition}"
      shift 2
      ;;
    --region)
      REGION="${2:?missing region}"
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

REGION="${REGION:-$(config_value aws_region us-east-1)}"
RESULTS_DIR="${AWS_RESULTS_DIR:-$(config_value aws_results_dir)}"
QUEUE="${QUEUE:-$(config_value aws_ondemand_queue)}"
CONTAINER_IMAGE="${AWS_BATCH_CONTAINER_IMAGE:-$(config_value container)}"
SOURCE_COMMIT="${SOURCE_COMMIT:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
RUN_ID="${RUN_ID:-cloud-selective5-$(date -u +%Y%m%dT%H%M%SZ)}"
SOURCE_ARCHIVE_URL="${SOURCE_ARCHIVE_URL:-https://github.com/jasonLaster/oncoomics/archive/${SOURCE_COMMIT}.tar.gz}"

VCPUS="${HRD_PACKET_BATCH_VCPUS:-1}"
MEMORY="${HRD_PACKET_BATCH_MEMORY:-2048}"
TIMEOUT="${HRD_PACKET_BATCH_TIMEOUT:-600}"
JOB_NAME="${HRD_PACKET_BATCH_JOB_NAME:-diana-hrd-packet-${RUN_ID}}"

if [[ -z "$S3_PREFIX" ]]; then
  if [[ -z "$RESULTS_DIR" ]]; then
    echo "Missing output S3 prefix. Set S3_PREFIX, AWS_RESULTS_DIR, or configure aws_results_dir." >&2
    exit 2
  fi
  S3_PREFIX="${RESULTS_DIR%/}/rosalind_hrd/${RUN_ID}"
fi
if [[ -z "$QUEUE" ]]; then
  echo "Missing AWS Batch queue. Set AWS_BATCH_JOB_QUEUE or configure aws_ondemand_queue." >&2
  exit 2
fi
if [[ -z "$CONTAINER_IMAGE" ]]; then
  echo "Missing container image. Set AWS_BATCH_CONTAINER_IMAGE or configure container." >&2
  exit 2
fi
if [[ -z "$JOB_DEFINITION" ]]; then
  JOB_DEFINITION="$(
    aws batch describe-job-definitions \
      --region "$REGION" \
      --status ACTIVE \
      --output json |
      python3 -c 'import json, sys
image = sys.argv[1]
data = json.load(sys.stdin)
matches = [
    jd for jd in data.get("jobDefinitions", [])
    if jd.get("containerProperties", {}).get("image") == image
]
matches.sort(key=lambda jd: (jd.get("jobDefinitionName", ""), jd.get("revision", 0)))
print(matches[-1]["jobDefinitionArn"] if matches else "")' "$CONTAINER_IMAGE"
  )"
fi
if [[ -z "$JOB_DEFINITION" ]]; then
  echo "Could not infer AWS Batch job definition for ${CONTAINER_IMAGE}. Set AWS_BATCH_JOB_DEFINITION." >&2
  exit 2
fi

if [[ "$DRY_RUN" -ne 1 ]]; then
  AWS_REGION="$REGION" bash "${ROOT_DIR}/infra/aws/check-daily-cost-guard.sh" "$CONFIG_PATH"
fi

PAYLOAD_PATH="$(mktemp -t diana-hrd-packet-submit.XXXXXX.json)"
export RUN_ID SAMPLE_SET ARTIFACT_ROOT_REL SOURCE_COMMIT SOURCE_ARCHIVE_URL S3_PREFIX REGION QUEUE JOB_DEFINITION
export VCPUS MEMORY TIMEOUT JOB_NAME

python3 - "$PAYLOAD_PATH" <<'PY'
import json
import os
import pathlib
import textwrap
import sys

payload_path = pathlib.Path(sys.argv[1])

cloud_script = r'''set -euo pipefail
export PATH="/opt/diana-aws/bin:$PATH"
RUN_ID="${ROSALIND_HRD_RUN_ID:?}"
SOURCE_ARCHIVE_URL="${SOURCE_ARCHIVE_URL:?}"
S3_PREFIX="${S3_PREFIX:?}"
WORK="/tmp/diana-cloud-packet-${RUN_ID}"
mkdir -p "$WORK"
cd "$WORK"
echo "cloud_packet_run_id=${RUN_ID}"
echo "source_commit=${SOURCE_COMMIT:?}"
echo "s3_prefix=${S3_PREFIX}"
echo "download=${SOURCE_ARCHIVE_URL}"
curl -L --fail --silent --show-error "$SOURCE_ARCHIVE_URL" -o repo.tar.gz
tar -xzf repo.tar.gz
REPO_DIR="$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
export REPO_DIR
cd "$REPO_DIR"
export PYTHONPATH="$REPO_DIR/src"
export DIANA_OMICS_ROOT="$REPO_DIR"
export ROSALIND_HRD_ARTIFACT_ROOT="$REPO_DIR/${ROSALIND_HRD_ARTIFACT_ROOT_REL:?}"
python3 -m diana_omics build:rosalind-hrd-packet
python3 - <<'PY_SUMMARY'
import csv
import hashlib
import json
import os
import pathlib

repo = pathlib.Path(os.environ["REPO_DIR"])
run_id = os.environ["ROSALIND_HRD_RUN_ID"]
packet_root = repo / "results" / "rosalind_hrd"
packet_index = packet_root / run_id / "packet_index.md"
run_manifest = packet_root / run_id / "run_manifest.json"
sample_sets = [item.strip() for item in os.environ["ROSALIND_HRD_SAMPLE_SET"].split(",") if item.strip()]
reviewer_hashes = {}
adapter_rows = {}
for sample in sample_sets:
    sample_dir = packet_root / sample / run_id
    reviewer = sample_dir / "reviewer_packet.md"
    adapter_status = sample_dir / "hrd_adapter_status.csv"
    if reviewer.exists():
        reviewer_hashes[sample] = hashlib.sha256(reviewer.read_bytes()).hexdigest()
    if adapter_status.exists():
        with adapter_status.open(newline="") as handle:
            adapter_rows[sample] = list(csv.DictReader(handle))
summary = {
    "run_id": run_id,
    "source_commit": os.environ["SOURCE_COMMIT"],
    "aws_batch_job_id": os.environ.get("AWS_BATCH_JOB_ID", ""),
    "aws_batch_job_queue": os.environ.get("AWS_BATCH_JQ_NAME", ""),
    "aws_region": os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "")),
    "s3_prefix": os.environ["S3_PREFIX"],
    "artifact_root": os.environ["ROSALIND_HRD_ARTIFACT_ROOT"],
    "sample_sets": sample_sets,
    "packet_index_sha256": hashlib.sha256(packet_index.read_bytes()).hexdigest(),
    "run_manifest_sha256": hashlib.sha256(run_manifest.read_bytes()).hexdigest(),
    "reviewer_packet_sha256": reviewer_hashes,
    "adapter_status_rows": adapter_rows,
    "packet_index_tail": packet_index.read_text().splitlines()[-12:],
}
out = pathlib.Path("/tmp") / f"{run_id}-cloud_batch_run_summary.json"
out.write_text(json.dumps(summary, indent=2) + "\n")
print(out.read_text())
PY_SUMMARY
aws s3 cp --recursive "results/rosalind_hrd/${RUN_ID}" "${S3_PREFIX}/results/rosalind_hrd/${RUN_ID}"
IFS=',' read -r -a sample_sets <<< "${ROSALIND_HRD_SAMPLE_SET}"
for sample in "${sample_sets[@]}"; do
  sample="${sample//[[:space:]]/}"
  [[ -z "$sample" ]] && continue
  aws s3 cp --recursive "results/rosalind_hrd/${sample}/${RUN_ID}" "${S3_PREFIX}/results/rosalind_hrd/${sample}/${RUN_ID}"
done
aws s3 cp "/tmp/${RUN_ID}-cloud_batch_run_summary.json" "${S3_PREFIX}/cloud_batch_run_summary.json"
echo "uploaded_cloud_packet=${S3_PREFIX}"
'''

payload = {
    "jobName": os.environ["JOB_NAME"],
    "jobQueue": os.environ["QUEUE"],
    "jobDefinition": os.environ["JOB_DEFINITION"],
    "containerOverrides": {
        "command": ["bash", "-lc", cloud_script],
        "environment": [
            {"name": "ROSALIND_HRD_RUN_ID", "value": os.environ["RUN_ID"]},
            {"name": "ROSALIND_HRD_SAMPLE_SET", "value": os.environ["SAMPLE_SET"]},
            {"name": "ROSALIND_HRD_ARTIFACT_ROOT_REL", "value": os.environ["ARTIFACT_ROOT_REL"]},
            {"name": "SOURCE_COMMIT", "value": os.environ["SOURCE_COMMIT"]},
            {"name": "SOURCE_ARCHIVE_URL", "value": os.environ["SOURCE_ARCHIVE_URL"]},
            {"name": "S3_PREFIX", "value": os.environ["S3_PREFIX"]},
            {"name": "AWS_REGION", "value": os.environ["REGION"]},
            {"name": "AWS_DEFAULT_REGION", "value": os.environ["REGION"]},
        ],
        "resourceRequirements": [
            {"type": "VCPU", "value": os.environ["VCPUS"]},
            {"type": "MEMORY", "value": os.environ["MEMORY"]},
        ],
    },
    "timeout": {"attemptDurationSeconds": int(os.environ["TIMEOUT"])},
    "tags": {
        "Project": "diana-omics",
        "Purpose": "rosalind-hrd-packet-cloud-validation",
        "RunId": os.environ["RUN_ID"],
    },
}
payload_path.write_text(json.dumps(payload, indent=2) + "\n")
PY

if [[ "$DRY_RUN" -eq 1 ]]; then
  cat "$PAYLOAD_PATH"
  exit 0
fi

aws batch submit-job \
  --region "$REGION" \
  --cli-input-json "file://${PAYLOAD_PATH}"
