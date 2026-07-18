# Diana Public Analysis Downloads

Use this guide to browse, cite, or copy public Diana Omics data. The public
surface is intentionally available to outside collaborators without AWS
credentials and includes both reviewed analysis outputs and current raw inbox
deliveries.

## Browse the reviewed index

Browse the live file tree at [data.diana-tnbc.com](https://data.diana-tnbc.com/).
The site reads reviewed analysis outputs from the static index at:

```text
https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json
```

The site also lists the current public Diana inbox directly from:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/
```

The results index contains only current objects under exact Terraform-allowlisted
prefixes. The raw-inputs bucket allows anonymous list and read for current
objects under `diana/inbox/` so new accepted deliveries appear without
republishing `public-index/objects.json`.

## Diana WGS HRD analysis

The public root for the current alias-only WGS analysis is:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/
```

The recovered early-look analysis is under:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/
```

Final deterministic, Rosalind, and cross-check reports should be published as
reviewed subtrees under the same alias-only root. The corresponding Rosalind
HRD packet root is:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/rosalind/
```

These paths identify a run alias, not a patient name. Conclusions must preserve
`partial_evidence`, `blocked`, and `no_call` boundaries from the source reports.

## Stage terminal Diana WGS report packets

After the full-WGS Batch job succeeds, build every terminal source report packet
only from versioned, frozen artifacts. The hand-maintained entry point is a
create-only post-success renderer:

```bash
RUN_ROOT=.codex-tmp/hrd-reports/deterministic-full
POST_SUCCESS_RUNBOOK="$RUN_ROOT/post-success-runbook.$(date -u +%Y%m%dT%H%M%SZ).md"
TERMINAL_BATCH_JOB_ID=<successful-batch-job-id>

python3 scripts/render_post_success_runbook.py \
  --terminal-job-id "$TERMINAL_BATCH_JOB_ID" \
  --output "$POST_SUCCESS_RUNBOOK"
```

Treat the generated runbook, not this Markdown page, as the canonical command
source. It validates the required precomputed custody receipts and recovered
early-look artifacts, then renders the current checked-in script paths, exact
receipt names, explicit AWS region arguments, and the wait boundaries around
submitted Batch jobs.

| Generated stage | Checked-in command path |
| --- | --- |
| Capture the successful WGS Batch execution, executed worker, stage provenance, and final artifacts | `scripts/capture_batch_provenance.py`, `scripts/freeze_stage_provenance.py`, `scripts/freeze_final_artifacts.py`, `scripts/materialize_frozen_artifacts.py` |
| Submit, wait for, and exactly capture the ARM64 cross-check materializer | `scripts/submit_materializer_v4.py`, `scripts/render_materializer_capture_command.py`, `scripts/download_materializer_staged_validation.py` |
| Finalize and privately publish the alias-only cross-check input contract | `scripts/finalize_input_contract.py`, `scripts/check_contract.py`, `scripts/publish_input_contract.py` |
| Stage the deterministic and Diana WGS Rosalind packets from the final frozen artifact root | `scripts/stage_deterministic_wgs_report.py`, `PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet` |
| Submit, wait for, and exactly capture each executable HRD cross-check route | `aws/submit_route.py`, `scripts/capture_route_terminal.py` |
| Compact executable cross-check outputs and render no-call packets for blocked routes | `scripts/download_exact_report_tree.py`, `scripts/stage_hrd_crosscheck_report.py`, `scripts/generate_blocked_hrd_crosscheck_reports.py` |
| Render the seven-source private-freeze and AI-review handoff | `scripts/render_source_report_freeze_runbook.py` |

The deterministic stager writes exactly the six `deterministic_full_wgs` packet
files that Rosalind, cross-check materialization, and the private/public
publishers accept:

```text
report.md
readiness.csv
evidence_checks.json
input_sha256.csv
crosscheck_input_plans.json
report_manifest.json
```

Do not start the generated post-success commands until the Batch job is
`SUCCEEDED`. The renderer deliberately fail-closes if a checked-in helper is
missing, and the downstream freeze/materialize steps bind every report packet
back to exact S3 `VersionId` values.

## Freeze reviewed reports and render AI/publication handoffs

The post-success runbook ends by rendering the private-freeze handoff only after
all seven local source packet directories exist. The canonical source methods
are:

| Method ID | Local packet root |
| --- | --- |
| `deterministic_full_wgs` | `.codex-tmp/hrd-reports/deterministic-full/report` |
| `rosalind_diana_wgs` | `results/rosalind_hrd/diana_wgs/diana-wgs-hrd-20260716T033101Z` |
| `sequenza_scarhrd` | `.codex-tmp/hrd-reports/crosschecks/sequenza_scarhrd` |
| `sigprofiler_sbs3` | `.codex-tmp/hrd-reports/crosschecks/sigprofiler_sbs3` |
| `facets_scarhrd_blocked` | `.codex-tmp/hrd-reports/blocked-crosschecks/facets_scarhrd_blocked` |
| `oncoanalyser_chord_blocked` | `.codex-tmp/hrd-reports/blocked-crosschecks/oncoanalyser_chord_blocked` |
| `hrdetect_blocked` | `.codex-tmp/hrd-reports/blocked-crosschecks/hrdetect_blocked` |

`scripts/render_source_report_freeze_runbook.py` validates those exact packet
inventories, freezes them through `scripts/publish_private_report.py` in the
canonical order from `scripts/hrd_report_inventory.py`, and emits the
`scripts/render_ai_synthesis_runbook.py` command with the resulting seven
private-publication receipts.

The AI-review renderer validates the seven private receipts against their local
`report_manifest.json` hashes, materializes the pinned model-catalog receipt,
prepares the de-identified seven-method reviewer bundle, validates two isolated
reviewer outputs, generates the offline comparative HRD synthesis, and freezes
the two AI reviewer packets plus the synthesis packet privately.

Its final step renders `scripts/render_reviewed_publication_runbook.py` with ten
private receipts: the seven source methods, the two AI reviewer packets, and
`comparative_hrd_synthesis`. The reviewed-publication runbook then emits one
dry-run and one apply command per report method, rebuilds
`public-index/objects.json`, and publishes that index so new reviewed reports
appear at `data.diana-tnbc.com`.

Every renderer writes a mode-0600 runbook with create-only semantics and scans
for raw/vendor tokens such as `E019_S01`, `DRF-PSN49561`, `echo-personalis`, and
`personalis`. Rerender into a new timestamped path or intentionally archive the
prior local runbook before repeating a handoff.

## Download one object

Use the live index to find a key, then convert it to a direct HTTPS URL:

```bash
BUCKET=diana-omics-results-172630973301-us-east-1
KEY='runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/artifacts/early_look_summary.json'

curl --fail --location --remote-name \
  "https://${BUCKET}.s3.us-east-1.amazonaws.com/${KEY}"
```

Use `curl -C -` to resume a partial large download.

## Download a reviewed subtree

The results bucket intentionally denies anonymous listing, so discover exact
keys from `public-index/objects.json`. Download those keys individually, or use
an authenticated collaborator identity when a managed bulk transfer requires
S3 listing.

For a small anonymous manifest-driven copy:

```bash
curl --fail --location \
  'https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json' \
  --output diana-public-objects.json

jq -r '.objects[] | select(.key | startswith("runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/early-look/")) | .key' \
  diana-public-objects.json
```

Use the recorded byte size and any report manifest SHA-256 values to verify the
copy. Method-report manifests are the canonical integrity and provenance
surface for deterministic, Rosalind, and cross-check reports.

## Citation and cross-reference policy

- Cite the direct HTTPS object URL and the run identifier.
- Prefer `report.md`, `report_manifest.json`, packet indexes, and explicit
  publication receipts over transient logs.
- Keep public validation evidence, sample-derived evidence, and external
  research context distinct.
- Do not promote a public `no_call` or `partial_evidence` report into a clinical
  conclusion.
- Keep raw uploads under `s3://diana-omics-raw-inputs-.../diana/inbox/`; do not
  copy them into the results-bucket report prefixes.
- Do not publish private version-history receipts.

## Related documentation

- [Diana raw input intake contract](diana-raw-inputs.md)
- [GCE to Diana S3 upload](gce-s3-upload.md)
- [Rosalind HRD workflow](../rosalind/hrd-workflow.md)
