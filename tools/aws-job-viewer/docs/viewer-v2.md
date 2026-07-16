# Diana AWS job viewer v2

## Purpose

Viewer v2 is the operational surface for understanding a Diana AWS Batch run without reading an undifferentiated stream of CloudWatch text. It should make three questions answerable at a glance:

1. Which job and run am I looking at?
2. Where is the run in the workflow, and what is blocked, active, or complete?
3. Which log events matter, and can I reach older evidence without managing pages?

The viewer is an observational tool. It reports exploratory pipeline evidence and does not turn a pipeline result into a clinically validated HRD call.

## Information architecture

The desktop workspace has three independently useful regions:

- The **left rail** lists active and recent AWS Batch jobs and controls job selection.
- The **main work surface** contains the selected job heading and the **Overview** and **Logs** tabs.
- The **right rail** presents compact run context by default and becomes a structured event inspector when a log event is deliberately selected.

Both rails are collapsible. Their desktop state persists across reloads in browser storage. The main work surface expands when either rail is collapsed, so dense logs and progress visualizations can use the available width.

Rail controls must expose `aria-expanded`, retain a useful accessible name, and remain reachable while their rail is closed. Collapsing a rail does not clear the selected job, active tab, filters, or loaded log events.

## Job selection

On initial load, the viewer selects the first active job, then the most recent job if there are no active jobs. A selected job row is visually distinct and exposes `aria-pressed="true"`; every other row exposes `aria-pressed="false"`.

Changing jobs updates all of the following as one coherent context:

- status, stage, name, run ID, queue, elapsed time, and attempt count;
- workflow and chromosome progress;
- right-rail execution facts;
- the Logs tab's stream and events.

The viewer must not show logs from the previously selected job while the new job is loading.

## Polling and freshness

The viewer separates broad job discovery from the selected job's active detail so that running work feels live without repeatedly rebuilding the entire workspace. Automatic requests follow these cadences:

| Polling lane | When enabled | Cadence |
| --- | --- | --- |
| Full job inventory | The page is visible and online | Every 30 seconds while any discovered job is active; every 120 seconds when the inventory is idle. |
| Selected job status | The selected job is active and **Overview** is the current tab | Every 10 seconds through the lightweight `/api/job-status` route. |
| Selected job logs | **Logs** is the current tab | Every 10 seconds for an active selected job; every 60 seconds for a terminal selected job. |

The selected-job status lane does not run on Logs, and the log lane does not run on Overview. Terminal jobs rely on the inventory cadence on Overview because their status is no longer changing rapidly. Manual cursor pagination for older log history remains independent of the newest-page log refresh.

Every polling lane is serial: it schedules its next request only after the current request settles. A slow request therefore cannot accumulate overlapping requests in the same lane. Changing the selected job or tab cancels that lane's pending timer and starts the newly relevant lane immediately.

Automatic polling pauses whenever the document is hidden or the browser reports that it is offline. Existing jobs, logs, filters, and selection remain visible while paused. Returning to a visible, online state re-enables the relevant lanes and triggers an immediate catch-up request instead of waiting through a full interval.

The top bar reports freshness truthfully:

- **Live** means automatic refresh is eligible and at least one data request has succeeded within the freshness window.
- **Connecting** means the page is eligible to refresh but no data request has completed yet.
- **Paused** means automatic refresh is intentionally suspended because the page is hidden or offline; the adjacent countdown changes to **Sync paused**.
- **Data stale** means the page is eligible to refresh but the most recent successful data update is older than twice the current inventory interval: more than 60 seconds when active jobs exist or more than 240 seconds when the inventory is idle.
- **Connection issue** takes precedence when a current inventory or selected-status request has failed. Existing successful data stays on screen rather than being presented as newly refreshed.

**Updated N seconds ago** reflects the most recent successful inventory, selected-job, or newest-log response. **Full sync** is the countdown to the full inventory refresh, not a claim that every data lane shares one timer. **Sync now** requests a full inventory refresh; tab-specific polling continues on its own cadence.

## Overview and workflow progress

The Overview tab is the default view. It favors readable hierarchy, restrained color, aligned numeric data, and clear empty states.

The summary metrics cover genome traversed, active shards, throughput, and compute ETA. The workflow view maps the selected job onto these stable stages:

1. Intake integrity
2. Alignment
3. Variant evidence
4. Evidence gather
5. Filter and annotate
6. Readiness and delivery

Every workflow step has one state: `complete`, `active`, `queued`, or `failed`. State must be communicated by label and icon or shape as well as color. The workflow container uses `data-testid="workflow-progress"`, and each step exposes its state through `data-state`.

Chromosome progress remains a separate, fine-grained view. It shows per-chromosome percent, activity, and position when progress events exist, with an explicit waiting state when they do not.

## Structured logs

The Logs tab is an event viewer, not a raw `<pre>` block. Each event is a row or card with a stable timestamp column, level treatment, category, formatted primary message, and optional structured details. Monospace is reserved for timestamps, identifiers, metrics, and literal values; supporting labels and explanations use the interface typeface.

Adapters normalize known event shapes while preserving the original message as evidence:

| Adapter | Recognition | Presentation |
| --- | --- | --- |
| Structured JSON | A JSON object with fields such as `level`, `category`, `event`, or `message` | Promote known fields into badges and key/value details; keep unknown fields available rather than dropping them. |
| Progress | GATK `ProgressMeter`, chromosome progress, percent, throughput, or shard lifecycle text | Emphasize chromosome, percent, and rate as aligned metrics; category is `progress`. |
| AWS Batch/system | Container lifecycle, retries, queueing, resource, or Batch messages | Show the lifecycle action and relevant container/job context; warnings and failures use stronger level treatment. |
| Workflow/artifact | Stage transitions, checksums, uploads, validation, and named output artifacts | Emphasize stage or artifact name and outcome. |
| Generic | Any event not recognized by a more specific adapter | Show timestamp, inferred level/category, and the complete message without loss. |

Level color is consistent: neutral/cool for debug and info, amber for warnings, red for errors, and positive green only for confirmed completion. Color is supplemental: severity remains explicit in the event's accessible name and as visible text in the inspector.

The ledger keeps routine desktop rows close to 30 CSS pixels high by putting timestamp, a single-line adapted title, concise detail, and an explicit inspection affordance on one line. Long production titles truncate instead of wrapping. Mobile rows are 44 pixels high to retain a reliable touch target. Parsed metadata and the raw payload live in the inspector instead of expanding a row and shifting the infinite list.

Selecting an event by its immutable `eventKey` gives the row a calm blue tint and changes the right rail to Event mode. The inspector shows severity, category, source, full timestamp, formatted message, parsed fields, CloudWatch provenance, and the untouched raw payload. Closing it restores focus to the triggering control and preserves the feed's exact scroll position. On mobile the rail is a modal right-edge sheet; lazy pagination pauses while it is open so the selected event cannot move underneath the user.

Each rendered event uses `data-testid="log-event"`, `data-level`, `data-category`, and `data-selected`. These attributes are both stable test hooks and an explicit statement of the adapter's result. The row's explicit inspection control uses `data-testid="inspect-log-event"` and `aria-controls="event-inspector"`.

## Search and filtering

The log toolbar provides:

- `data-testid="log-search"`: case-insensitive free-text search over the rendered message and structured fields;
- `data-testid="log-level-filter"`: a single level filter with `all`, `info`, `success`, `warn`, and `error` values;
- `data-testid="log-category-filter"`: a category filter with `all` plus the categories present in the loaded data.

Search, level, and category filters combine with AND semantics. Filtering is immediate, does not make a network request, and does not discard already loaded events. A no-results state distinguishes “no matching events” from “this stream has no events.” Clearing filters restores the loaded list.

## Lazy loading and infinite history

The first `/api/job-logs` response contains the newest stored page and a `continueCursor` for older history. The event feed uses `data-testid="log-feed"`. A sentinel with `data-testid="log-pagination-sentinel"` requests the next page automatically when it enters the feed's visible scroll area.

Cursor pages are merged by `eventKey`, sorted chronologically, and prepended because they contain older events. Prepending a page preserves the reader's visible scroll position; it must not jump the reader to a different event. Only one older-page request may be in flight at a time. Pagination stops when `isDone` is true or `continueCursor` is absent. Errors appear inline with a retry path and do not erase pages already loaded.

Convex is the preferred durable source. If that archive is unavailable, the API falls back to CloudWatch `GetLogEvents`, paging backward through the current stream and then earlier Batch attempts. Its prefixed opaque cursor bypasses Convex on subsequent pages. The fallback uses the same deterministic event keys, chronological ordering, and response fields, so filtering, event inspection, and infinite loading continue to work. Empty CloudWatch pages advance until the backward token stabilizes; only token stability marks a stream complete. In fallback mode `totalEvents` grows with pages loaded rather than claiming a complete stored count; durable totals resume with Convex.

Search and filters apply to all events loaded so far. Reaching the sentinel continues loading even when the current filter hides most rows, until the archive is complete or enough matching results fill the viewport.

## Responsive behavior

Desktop defaults to both rails open. On a phone-sized viewport, both rails default closed so the selected job and active tab remain readable. Rail toggles open the rails as temporary drawers, and opening one mobile rail closes the other. The drawer overlays the work surface rather than permanently narrowing it.

The mobile log toolbar stacks its search and filters, event metadata wraps without covering the message, and the log feed scrolls within the available viewport. All controls retain at least a 44-by-44 CSS-pixel pointer target and are usable with keyboard navigation.

## API contract used by the viewer

`GET /api/jobs` returns the generated time, AWS region, queues, and normalized jobs. A job includes identity, status and timings, run/stage/dependency context, optional log stream, and optional aggregate progress. This is the full inventory route used by the 30/120-second polling lane and **Sync now**.

`GET /api/job-status?jobId=<id>` returns the generated time, AWS region, and one normalized AWS Batch job. It is the lightweight 10-second Overview refresh for an active selection; it updates that job in place without replacing the rest of the inventory. Fresh AWS status and recent CloudWatch progress are merged with the same durable Convex chromosome maxima used by the full inventory, so a narrow log window cannot regress displayed progress.

Convex maintains an independent forward cursor for progress extraction on every CloudWatch stream. If persistence was unavailable, the next successful sync resumes or replays the missing stream pages, stores per-page chromosome maxima, and repairs the cumulative aggregate before the API responds. Raw-log and progress cursors are separate so a complete log archive cannot incorrectly imply that its derived progress aggregate is also complete.

`GET /api/job-logs?jobId=<id>` returns the newest page for the selected job. Supplying `cursor=<continueCursor>` requests the next older page. Responses include job and stream identity, `events`, `totalEvents`, `backfillComplete`, `isDone`, and the next `continueCursor`.

API errors are visible but never expose credentials or server exception details. Inventory refresh, selected-job refresh, newest-log refresh, and older-log pagination are independent lanes: a delayed request must not create overlap in its lane or erase data already loaded by another lane.

## Stable selectors and accessibility contract

| Surface | Contract |
| --- | --- |
| Left job rail | `data-testid="left-rail"`, `data-collapsed="true|false"` |
| Right context rail | `data-testid="right-rail"`, `data-collapsed="true|false"`, `data-mode="run|event"` |
| Left rail toggle | `data-testid="toggle-left-rail"`, `aria-expanded` |
| Right rail toggle | `data-testid="toggle-right-rail"`, `aria-expanded` |
| Detail tabs | ARIA tabs named `Overview` and `Logs` |
| Workflow | `data-testid="workflow-progress"`; child steps expose `data-state` |
| Log search | `data-testid="log-search"` |
| Level filter | `data-testid="log-level-filter"` |
| Category filter | `data-testid="log-category-filter"` |
| Event feed | `data-testid="log-feed"` |
| Event | `data-testid="log-event"`, `data-level`, `data-category`, `data-selected` |
| Event inspection control | `data-testid="inspect-log-event"`, `aria-controls`, `aria-expanded` |
| Event inspector content | `data-testid="event-inspector-content"` |
| Pagination trigger | `data-testid="log-pagination-sentinel"` |

## Executable acceptance suite

The Playwright suite in `tests/e2e/viewer-v2.spec.ts` intercepts `/api/jobs` and `/api/job-logs` in the browser. Its fixtures are deterministic, include active, completed, and failed jobs, and return two cursor-based log pages with progress, warning, error, JSON, workflow, and artifact messages.

The suite verifies:

- independent desktop rail collapse and persistence across reload;
- active inventory, selected-job, and newest-log polling cadences;
- job selection and selected-row semantics;
- structured metrics and workflow states;
- formatted log adapters and combined search/filter behavior;
- automatic cursor pagination after scrolling the sentinel into view;
- contextual event inspection with parsed and raw fields;
- feed scroll-position and trigger-focus restoration after inspection;
- mobile default collapse and one-drawer-at-a-time behavior.

Run it from `tools/aws-job-viewer`:

```bash
npm run test:e2e
```

Set `PLAYWRIGHT_BASE_URL` to test an already running viewer. Otherwise the configuration starts a local Next.js server on `PLAYWRIGHT_PORT` (default `3107`). On first use, install the Chromium browser binary with `npx playwright install chromium`.

`tests/e2e/production.spec.ts` is an explicit live-data smoke test. It is skipped during deterministic local runs and enabled only with `PLAYWRIGHT_PRODUCTION=1`. With `PLAYWRIGHT_BASE_URL=https://jobs.diana-tnbc.com`, it verifies the deployed document, real `/api/jobs` payload, selected overview, real `/api/job-logs` payload when a stream exists, and the live feed surface.
