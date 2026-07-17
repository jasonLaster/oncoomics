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

After the full-WGS Batch job succeeds, build the deterministic report packet
only from versioned, frozen artifacts. `scripts/stage_deterministic_wgs_report.py`
expects:

- a final frozen worker artifact tree materialized by exact S3 VersionId;
- terminal Batch execution and executed-worker freeze receipts;
- final-artifact and stage-provenance freeze receipts plus their S3 anchors;
- exact cross-check materialization and staged-input validation receipts;
- the prior early-look artifact tree for early-versus-full deltas; and
- explicit forbidden raw/vendor tokens.

The stager writes exactly the five `deterministic_full_wgs` packet files that
the private/public publishers accept:

```text
report.md
readiness.csv
evidence_checks.json
input_sha256.csv
report_manifest.json
```

Use a run-local scratch directory and publish the generated packet only after a
dry-run receipt verifies the five-file inventory and `no_call` boundary:

```bash
RUN_ROOT=.codex-tmp/hrd-reports/deterministic-full

python3 scripts/stage_deterministic_wgs_report.py \
  --artifact-root "$RUN_ROOT/materialized-final" \
  --preflight-json "$RUN_ROOT/quarantine.preflight.json" \
  --gather-json "$RUN_ROOT/quarantine.gather.json" \
  --sha-audit "$RUN_ROOT/private-input-sha256.json" \
  --execution-json "$RUN_ROOT/terminal.execution.succeeded.json" \
  --executed-worker-freeze-receipt "$RUN_ROOT/executed-worker-freeze-receipt.json" \
  --executed-worker-freeze-receipt-upload "$RUN_ROOT/executed-worker-freeze-receipt-upload.json" \
  --final-freeze-receipt "$RUN_ROOT/terminal.final-freeze.json" \
  --final-freeze-anchor "$RUN_ROOT/terminal.final-freeze.anchor.json" \
  --exact-materialization-receipt "$RUN_ROOT/terminal.materialize.json" \
  --crosscheck-materialization-receipt "$RUN_ROOT/terminal.materializer.receipt.json" \
  --stage-provenance-receipt "$RUN_ROOT/terminal.stage-freeze.json" \
  --stage-provenance-anchor "$RUN_ROOT/terminal.stage-freeze.anchor.json" \
  --staged-input-validation-json "$RUN_ROOT/staged_input_validation.json" \
  --expected-kms-key-arn "$DIANA_PRIVATE_RESULTS_KMS_KEY_ARN" \
  --early-look-root .codex-tmp/hrd-reports/deterministic-early-look \
  --output-dir "$RUN_ROOT/report" \
  --forbidden-token E019_S01 \
  --forbidden-token DRF-PSN49561 \
  --forbidden-token echo-personalis \
  --forbidden-token personalis
```

Then point the Diana WGS Rosalind packet at the same final artifact root and
the deterministic report directory:

```bash
env \
  ROSALIND_HRD_SAMPLE_SET=diana_wgs \
  ROSALIND_HRD_RUN_ID=diana-wgs-hrd-20260716T033101Z \
  ROSALIND_HRD_ARTIFACT_ROOT="$RUN_ROOT/materialized-final" \
  ROSALIND_HRD_DETERMINISTIC_REPORT_DIR="$RUN_ROOT/report" \
  'ROSALIND_HRD_FORBIDDEN_TOKENS_JSON=["E019_S01","DRF-PSN49561","echo-personalis","personalis"]' \
  PYTHONPATH=src \
  /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

## Freeze and publish a reviewed report packet

First freeze the reviewed local report tree in the versioned private results
bucket with `scripts/publish_private_report.py`. The private publisher accepts
only allowlisted files for the selected method, validates the packet manifest's
`no_call` boundary, scans for source identifiers, and writes a
private-publication receipt with exact S3 VersionIds, SHA-256 values, object
sizes, and KMS custody.

For the Diana WGS Rosalind packet, dry-run the private freeze first:

```bash
python3 scripts/publish_private_report.py \
  --packet-dir .codex-tmp/hrd-reports/deterministic-full/rosalind/ \
  --method-id rosalind_diana_wgs \
  --receipt-output .codex-tmp/hrd-reports/deterministic-full/rosalind-private-publication.dry.json
```

Review the dry-run receipt, then apply with a different, unused mode-0600
receipt path:

```bash
python3 scripts/publish_private_report.py \
  --packet-dir .codex-tmp/hrd-reports/deterministic-full/rosalind/ \
  --method-id rosalind_diana_wgs \
  --receipt-output .codex-tmp/hrd-reports/deterministic-full/rosalind-private-publication.json \
  --apply
```

Use `scripts/publish_reviewed_public_report.py` only after the corresponding
private freeze has passed. The public publisher reads that passed
private-publication receipt, downloads every report file by its exact private
S3 VersionId, verifies SHA-256, bytes, and KMS custody, and runs a second
identifier scan before any public write.

The method ID pins both the accepted report inventory and destination subtree.
It cannot publish raw data or operator-selected filenames. For the Diana WGS
Rosalind packet, run the default dry-run first with a new local receipt path:

| Method ID | Local packet root | Reviewed public destination |
| --- | --- | --- |
| `deterministic_full_wgs` | `scripts/stage_deterministic_wgs_report.py` output | `.../deterministic/` |
| `rosalind_diana_wgs` | `results/rosalind_hrd/diana_wgs/<run-id>/` | `.../rosalind/` |

```bash
python3 scripts/publish_reviewed_public_report.py \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/rosalind-private-publication.json \
  --method-id rosalind_diana_wgs \
  --destination-prefix s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/rosalind/ \
  --receipt-output .codex-tmp/hrd-reports/deterministic-full/rosalind-publication.dry.json
```

Review the dry-run receipt and preserve the source packet's `partial_evidence`
and `no_call` boundary. Apply with a different, unused mode-0600 receipt path:

```bash
python3 scripts/publish_reviewed_public_report.py \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/rosalind-private-publication.json \
  --method-id rosalind_diana_wgs \
  --destination-prefix s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/rosalind/ \
  --receipt-output .codex-tmp/hrd-reports/deterministic-full/rosalind-publication.json \
  --apply
```

Apply mode requires an empty version history at the exact method destination,
uses create-only SSE-S3 uploads with full-object SHA-256, and succeeds only when
the final history contains exactly one current version per allowlisted file and
no delete markers.

## Render the AI review and synthesis handoff

Use `scripts/render_source_report_freeze_runbook.py` to render the seven
private-freeze commands for the canonical source report packets and the
follow-on AI handoff command:

```bash
python3 scripts/render_source_report_freeze_runbook.py \
  --output .codex-tmp/hrd-reports/deterministic-full/source-freeze-runbook.md
```

After all seven source report packets are privately frozen,
`scripts/render_ai_synthesis_runbook.py` renders the two-reviewer AI handoff,
offline comparative synthesis, and private publication commands for reviewer A,
reviewer B, and the synthesis packet.

Pass the seven private-publication receipts in the pinned method order from
`scripts/hrd_report_inventory.py`: `deterministic_full_wgs`,
`rosalind_diana_wgs`, `sequenza_scarhrd`, `sigprofiler_sbs3`,
`facets_scarhrd_blocked`, `oncoanalyser_chord_blocked`, then
`hrdetect_blocked`. The renderer validates the current private receipt schema
with `scripts/publish_reviewed_public_report.py` and also requires each local
`report_manifest.json` to hash to the exact row frozen in S3.

```bash
python3 scripts/render_ai_synthesis_runbook.py \
  --output .codex-tmp/hrd-reports/ai-review/post-reports-runbook.md \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/terminal.deterministic_full_wgs.private.json \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/terminal.rosalind_diana_wgs.private.json \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/terminal.sequenza_scarhrd.private.json \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/terminal.sigprofiler_sbs3.private.json \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/terminal.facets_scarhrd_blocked.private.json \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/terminal.oncoanalyser_chord_blocked.private.json \
  --private-publication-receipt .codex-tmp/hrd-reports/deterministic-full/terminal.hrdetect_blocked.private.json
```

The rendered runbook calls the checked-in AI review and synthesis scripts only:
`prepare_ai_review_run.py`, `validate_ai_review.py`,
`generate_comparative_hrd_synthesis.py`, `finalize_ai_review.py`, and
`publish_private_report.py`.

After publication, rebuild and publish `public-index/objects.json` so the new
report appears at `data.diana-tnbc.com`:

```bash
python3 scripts/build_public_results_index.py \
  --output .codex-tmp/public-index/objects.json

python3 scripts/publish_public_results_index.py \
  --index .codex-tmp/public-index/objects.json \
  --receipt-output .codex-tmp/public-index/public-index.dry.json

python3 scripts/publish_public_results_index.py \
  --index .codex-tmp/public-index/objects.json \
  --receipt-output .codex-tmp/public-index/public-index.json \
  --apply
```

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
