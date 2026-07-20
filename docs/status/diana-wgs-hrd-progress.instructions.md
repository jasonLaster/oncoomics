# Diana WGS HRD Progress Dashboard Instructions

Use this checklist when updating `docs/status/diana-wgs-hrd-progress.html`.

## Update contract

- Keep the page self-contained and readable from a local `file://` URL.
- Keep the summary user-centric: lead with what a collaborator can understand now, what changed, and what remains blocked.
- Preserve `partial_evidence`, `no_call`, and `blocked` boundaries. Do not imply Diana HRD, scarHRD, SBS3, CHORD, or HRDetect readiness until real terminal artifacts and reviewed cross-check reports exist.
- Update the visual progress dashboard, priority todo lists, and changelog for every material source milestone.
- Update the ignored preview copy after editing:

```sh
mkdir -p .codex-tmp/diana-wgs-hrd-progress
cp docs/status/diana-wgs-hrd-progress.html .codex-tmp/diana-wgs-hrd-progress/index.html
```

## Cost Explorer panel

Every dashboard refresh should include an AWS Cost Explorer breakdown for the previous complete UTC day.

- Query Cost Explorer with `Granularity=DAILY`.
- Use `Start` as yesterday's UTC date and `End` as today's UTC date; Cost Explorer treats `End` as exclusive.
- Request `UnblendedCost`.
- Group by `SERVICE` first and `USAGE_TYPE` second.
- Display the covered UTC date, total unblended cost, and the top service / usage-type rows.
- Fold tiny rows into `Other` if that keeps the card readable.
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
