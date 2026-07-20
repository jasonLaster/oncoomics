# Diana WGS HRD Progress Dashboard Instructions

Use this checklist when updating `docs/status/diana-wgs-hrd-progress.html`.

## Update contract

- Keep the page self-contained and readable from a local `file://` URL.
- Keep the summary user-centric: lead with what a collaborator can understand now, what changed, and what remains blocked.
- Preserve `partial_evidence`, `no_call`, and `blocked` boundaries. Do not imply Diana HRD, scarHRD, SBS3, CHORD, or HRDetect readiness until real terminal artifacts and reviewed cross-check reports exist.
- Update the visual progress dashboard, the Cost Explorer past-day breakdown,
  priority todo lists, and changelog for every material source milestone.
- Update the ignored preview copy after editing:

```sh
mkdir -p .codex-tmp/diana-wgs-hrd-progress
cp docs/status/diana-wgs-hrd-progress.html .codex-tmp/diana-wgs-hrd-progress/index.html
```

## Cost Explorer past-day breakdown

Every dashboard refresh should include an AWS Cost Explorer breakdown for the latest
complete UTC billing day. Treat "the past day" as the newest complete UTC day,
not as a rolling 24-hour window, so the card matches Cost Explorer's daily
buckets and avoids partial same-day estimates.

- Query Cost Explorer with `Granularity=DAILY`.
- Use `Start` as the latest complete UTC date and `End` as the following UTC date; Cost Explorer treats `End` as exclusive.
- Request `UnblendedCost`.
- Group by `SERVICE` first and `USAGE_TYPE` second.
- Use the Cost Explorer API response as the source of truth for the displayed
  values; do not estimate the past-day total from service dashboards or
  CloudWatch metrics.
- Re-run Cost Explorer immediately before each dashboard refresh so the
  yesterday card never carries a stale spend snapshot alongside fresh progress
  text.
- Display the covered UTC date, total unblended cost, and the top service / usage-type rows.
- Keep the breakdown row-level: every visible non-`Other` row should come from
  one exact Cost Explorer `SERVICE` / `USAGE_TYPE` pair, except rows that
  intentionally combine a single plain-language cost such as Public IPv4 across
  regions.
- Sort rows by descending unblended cost, sum all returned rows into the visible
  total, and aggregate low-dollar rows into `Other` only after preserving the
  largest cost drivers as their own rows.
- Preserve enough visible row detail to explain the prior-day total at a glance;
  a lone aggregate cost number is not a valid dashboard refresh.
- Keep the panel near the top of the dashboard as a plain-English
  "Yesterday's AWS cost" card so spend is visible alongside execution status.
- Label each row in plain language first, then keep the raw Cost Explorer service and usage type in the smaller secondary text.
- Refresh the covered UTC window, visible total, and row list even for
  source-only dashboard edits; if Cost Explorer returns the same values, leave
  the card values unchanged and record only the source milestone.
- Do not expose AWS account IDs, quota case IDs, raw private S3 paths, or
  collaborator transfer identifiers in the cost card.
- If Cost Explorer is unavailable or permission denied, keep the cost card visible and state the attempted UTC window plus the read-only error class; do not omit the card.

Example query shape:

```sh
python3 - <<'PY'
from datetime import datetime, timedelta, timezone

end = datetime.now(timezone.utc).date()
start = end - timedelta(days=1)
print(f"START={start}")
print(f"END={end}")
PY

aws ce get-cost-and-usage \
  --region us-east-1 \
  --time-period "Start=${START},End=${END}" \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE Type=DIMENSION,Key=USAGE_TYPE \
  --output json
```

## Public-safety scan

Before publishing a dashboard edit, scan the added lines and fail closed on:

- raw or private S3 URIs;
- AWS account IDs;
- sample IDs or collaborator/vendor names from private transfer threads;
- credential, signed-URL, or secret-sharing wording;
- legacy replacement-compute language;
- HRD, scarHRD, SBS3, CHORD, or HRDetect positivity/readiness claims.
