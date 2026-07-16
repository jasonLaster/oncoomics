#!/bin/zsh
set -euo pipefail

cd "${0:A:h}/.."

profile="${AWS_PROFILE:-default}"
if ! credentials="$(aws configure export-credentials --profile "$profile" --format env 2>/dev/null)"; then
  print -u2 "Unable to load AWS profile '$profile'. Refresh or sign in to that profile, then retry."
  exit 1
fi

eval "$credentials"
exec npm run dev
