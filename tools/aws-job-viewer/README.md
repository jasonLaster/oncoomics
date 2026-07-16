# Diana AWS job viewer

A private local dashboard for Diana AWS Batch jobs and CloudWatch logs.

## Open the viewer

```bash
cd tools/aws-job-viewer
npm install
npm run viewer
```

Then open [http://localhost:3000](http://localhost:3000). The viewer reads the current AWS CLI profile, discovers enabled Batch queues, and refreshes every 60 seconds. Set `AWS_PROFILE` before launching to use a profile other than `default`.

AWS credentials stay in the server process and are never sent to the browser. The profile only needs read access for Batch job discovery and CloudWatch log events.

Vercel deployments use `AWS_ROLE_ARN` with Vercel OIDC to exchange short-lived tokens for a scoped AWS read-only session. Static AWS access keys are not required.

The hosted viewer also persists normalized job-status, chromosome-progress, and complete CloudWatch log events in Convex. Convex receives the same project-scoped Vercel OIDC identity. Log messages are deduplicated with deterministic SHA-256 event keys, and a per-stream forward cursor makes each one-minute refresh incremental. Durable chromosome maxima are merged back into each response so cold starts do not lose completed work.

If the durable Convex deployment is temporarily unavailable, log reads degrade to direct, backward-cursor CloudWatch pagination instead of failing the viewer. The response retains the same event and cursor contract and traverses the current stream before earlier Batch attempts; persistence and a complete historical event count resume when Convex is available again.

The stable Convex production deployment is released with `npm run convex:deploy` while a production deploy key is present. `CONVEX_URL` selects that deployment at runtime; when it is absent, the viewer continues in live AWS-only mode. Vercel Preview and Production point to the same stable operational history rather than creating isolated per-branch databases.

## Views

- The flexible workspace has independently collapsible job and context-inspector rails. Desktop rail state persists across reloads; mobile uses one temporary rail at a time so the work surface stays readable.
- **Overview** combines run health, observed stage state, dependency progress, execution context, and chromosome-level GATK progress.
- **Logs** renders cursor-paginated Convex history as a compact structured ledger. Diana, AWS, Nextflow, GATK, JSON telemetry, command, artifact, warning, and error adapters preserve the raw message while promoting useful fields. Selecting an event opens parsed fields, provenance, and the raw payload in the contextual right rail without reflowing the feed. Search, level filters, and event-type filters apply to every page loaded so far.
- Older events load automatically when the history sentinel enters the scroll viewport. Rows use browser-native `content-visibility` so large loaded archives remain inexpensive to paint.

The complete v2 behavior, accessibility, responsive-layout, API, and stable-selector contract is specified in [docs/viewer-v2.md](docs/viewer-v2.md).

## Verify the viewer

```bash
npm run test:unit
npm run test:e2e
npm run build
```

The Playwright suite mocks both API routes and covers the two rails, job selection, structured workflow progress, log adapters, combined filtering, infinite cursor pagination, contextual event inspection, scroll/focus restoration, and mobile drawer behavior. An opt-in production spec exercises the live jobs and logs APIs:

```bash
PLAYWRIGHT_BASE_URL=https://jobs.diana-tnbc.com \
PLAYWRIGHT_PRODUCTION=1 \
npm run test:e2e
```

## Backfill CloudWatch logs

After deploying the Convex schema, backfill every event retained for every stream-bearing job discoverable in the enabled AWS Batch queues:

```bash
cd tools/aws-job-viewer
CONVEX_URL=https://your-production-deployment.convex.cloud \
  npm run convex:backfill-logs
```

The process starts each stream at its head, paginates until CloudWatch returns a stable forward token, and safely resumes after interruptions. Re-running it is idempotent. AWS access comes from the normal SDK credential chain or `AWS_ROLE_ARN`; Convex access uses the project-scoped `VERCEL_OIDC_TOKEN`.

Optional runtime configuration is documented in `.env.example`.
