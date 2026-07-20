#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_PATH="${1:-${DIANA_AWS_CONFIG:-${ROOT_DIR}/infra/aws/nextflow.aws.json}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ "$CONFIG_PATH" != /* ]]; then
  CONFIG_PATH="${ROOT_DIR}/${CONFIG_PATH}"
fi

config_value() {
  local key="$1"
  "$PYTHON_BIN" - "$CONFIG_PATH" "$key" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]

try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except OSError as error:
    print(
        f"Fail-closed: unable to read daily cost guard config {path}: {error}",
        file=sys.stderr,
    )
    raise SystemExit(64) from error
except json.JSONDecodeError as error:
    print(
        f"Fail-closed: daily cost guard config {path} is not JSON: {error}",
        file=sys.stderr,
    )
    raise SystemExit(64) from error

value = payload.get(key)
if not isinstance(value, str) or not value.strip():
    print(
        f"Fail-closed: daily cost guard config {path} omits {key}",
        file=sys.stderr,
    )
    raise SystemExit(64)
print(value)
PY
}

REGION="${AWS_REGION:-$(config_value aws_region)}"
DAILY_COST_GUARD_LEDGER="$(config_value daily_cost_guard_ledger)"
DAILY_COST_GUARD_LIVE_STOP_USD="$(config_value daily_cost_guard_live_stop_usd)"

"$PYTHON_BIN" "${ROOT_DIR}/scripts/daily_cost_guard.py" \
  --ledger "$DAILY_COST_GUARD_LEDGER" \
  --region "$REGION" \
  --live-stop-usd "$DAILY_COST_GUARD_LIVE_STOP_USD" >/dev/null
