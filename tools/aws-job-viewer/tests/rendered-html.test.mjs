import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

test("defines the Diana run monitor shell", async () => {
  const [layout, viewer] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/job-viewer.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /title: "Diana Compute — Run monitor"/);
  assert.match(viewer, /Diana Compute/);
  assert.match(viewer, /Run monitor <span>v2<\/span>/);
  assert.match(viewer, />\s*Overview\s*</);
  assert.match(viewer, />\s*Logs\s*\{/);
  assert.match(viewer, /Updated \$\{dataAgeSeconds\}s ago · Full sync \$\{countdown\}s/);
  assert.match(viewer, /No job selected/);
  assert.match(viewer, /data-testid="left-rail"/);
  assert.match(viewer, /data-testid="right-rail"/);
  assert.match(viewer, /data-testid="toggle-left-rail"/);
  assert.match(viewer, /data-testid="toggle-right-rail"/);
  assert.match(viewer, /data-testid="workflow-progress"/);
});

test("implements automatic refresh and server-side AWS access", async () => {
  const [viewer, jobsRoute, jobStatusRoute, logsRoute, awsBridge] = await Promise.all([
    readFile(new URL("../app/job-viewer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/jobs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/job-status/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/job-logs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/aws.ts", import.meta.url), "utf8"),
  ]);

  assert.match(viewer, /const ACTIVE_INVENTORY_REFRESH_SECONDS = 30/);
  assert.match(viewer, /const IDLE_INVENTORY_REFRESH_SECONDS = 120/);
  assert.match(viewer, /const ACTIVE_DETAIL_REFRESH_SECONDS = 10/);
  assert.match(viewer, /const TERMINAL_LOG_REFRESH_SECONDS = 60/);
  assert.match(viewer, /function useSerialPoll/);
  assert.match(viewer, /function preserveCumulativeProgress/);
  assert.match(viewer, /\/api\/job-status\?jobId=/);
  assert.match(viewer, /document\.visibilityState === "visible"/);
  assert.match(viewer, /navigator\.onLine/);
  assert.match(viewer, /Data stale/);
  assert.match(viewer, /Connecting/);
  assert.match(viewer, /Sync paused/);
  assert.match(viewer, /\/api\/job-logs\?\$\{searchParams\.toString\(\)\}/);
  assert.match(viewer, /new IntersectionObserver/);
  assert.match(viewer, /data-testid="log-pagination-sentinel"/);
  assert.match(viewer, /data-testid="log-feed"/);
  assert.match(viewer, /data-testid="log-search"/);
  assert.match(viewer, /data-testid="log-level-filter"/);
  assert.match(viewer, /data-testid="log-category-filter"/);
  assert.match(viewer, /preserveScrollHeightRef/);
  assert.match(jobsRoute, /listViewerJobs/);
  assert.match(jobStatusRoute, /getViewerJob/);
  assert.match(jobStatusRoute, /persistAndMergeViewerSnapshot/);
  assert.match(jobStatusRoute, /job: payload\.jobs\[0\] \|\| job/);
  assert.match(jobStatusRoute, /const generatedAt = new Date\(\)\.toISOString\(\)/);
  assert.match(jobStatusRoute, /Cache-Control.*no-store/s);
  assert.match(logsRoute, /getPersistentViewerLogsPage/);
  assert.match(logsRoute, /getDirectCloudWatchLogsPage/);
  assert.match(logsRoute, /cloudwatch-fallback/);
  assert.match(awsBridge, /CloudWatchLogsClient/);
  assert.match(awsBridge, /nextBackwardToken/);
  assert.match(awsBridge, /startFromHead: false/);
  assert.match(awsBridge, /DIRECT_LOG_CURSOR_PREFIX = "cloudwatch:"/);
  assert.match(awsBridge, /DescribeJobQueuesCommand/);
  assert.match(awsBridge, /awsCredentialsProvider/);
  assert.match(awsBridge, /AWS_ROLE_ARN/);
  assert.match(awsBridge, /export async function getViewerJob/);
  assert.match(`${jobsRoute}\n${logsRoute}`, /Cache-Control.*no-store|no-store/s);
  assert.doesNotMatch(viewer, /AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});

test("persists normalized progress and complete logs with project-scoped OIDC", async () => {
  const [jobsRoute, convexBridge, awsBridge, schema, functions, authConfig] = await Promise.all([
    readFile(new URL("../app/api/jobs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/convex.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/aws.ts", import.meta.url), "utf8"),
    readFile(new URL("../convex/schema.ts", import.meta.url), "utf8"),
    readFile(new URL("../convex/jobProgress.ts", import.meta.url), "utf8"),
    readFile(new URL("../convex/auth.config.ts", import.meta.url), "utf8"),
  ]);

  assert.match(jobsRoute, /persistAndMergeViewerSnapshot/);
  assert.match(convexBridge, /getVercelOidcToken/);
  assert.match(convexBridge, /ConvexHttpClient/);
  assert.match(convexBridge, /chromosome\.active/);
  assert.match(schema, /progressEvents: defineTable/);
  assert.match(schema, /chromosomeProgress: defineTable/);
  assert.match(schema, /jobStatusEvents: defineTable/);
  assert.match(schema, /logEvents: defineTable/);
  assert.match(schema, /logStreams: defineTable/);
  assert.match(functions, /export const ingestSnapshot = mutation/);
  assert.match(functions, /export const getAggregates = query/);
  assert.match(functions, /export const ingestLogBatch = mutation/);
  assert.match(functions, /export const getLogPage = query/);
  assert.match(functions, /export const getProgressCursor = query/);
  assert.match(functions, /export const ingestProgressBatch = mutation/);
  assert.match(convexBridge, /syncProgressStream/);
  assert.match(convexBridge, /syncForwardPages/);
  assert.match(convexBridge, /FOREGROUND_SYNC_MAX_PAGES = 8/);
  assert.match(convexBridge, /BACKGROUND_SYNC_MAX_PAGES = 1/);
  assert.match(convexBridge, /TERMINAL_SETTLE_GRACE_MS/);
  assert.match(functions, /expectedForwardToken/);
  assert.match(functions, /cursorAdvanced/);
  assert.doesNotMatch(convexBridge, /sync(?:Log|Progress)Stream\(client, stream, 1_000\)/);
  assert.match(awsBridge, /extractChromosomeProgressEvents/);
  assert.match(functions, /paginationOptsValidator/);
  assert.match(functions, /TOTAL_STANDARD_BASES = 3_031_042_417/);
  assert.match(authConfig, /oidc\.vercel\.com\/jlasters-projects/);
  assert.match(functions, /project:diana-aws-job-viewer:environment:/);
  assert.match(schema, /message: v\.string/);
  assert.match(schema, /progressNextForwardToken: v\.optional/);
  assert.match(schema, /progressBackfillComplete: v\.optional/);
  assert.match(schema, /cursorVersion: v\.optional/);
  assert.match(schema, /progressCursorVersion: v\.optional/);
  assert.match(functions, /FORWARD_CURSOR_VERSION = 2/);
  assert.match(functions, /export const registerLogStreams = mutation/);
  assert.match(functions, /export const getBackfillCandidates = query/);
  assert.match(functions, /export const initializeBackfillQueue = mutation/);
  assert.match(functions, /export const finishBackfillAttempt = mutation/);
  assert.match(functions, /backfillFailureCount/);
  assert.match(functions, /legacyCursorWriteAllowed/);
  assert.match(schema, /by_next_backfill/);
  assert.match(convexBridge, /BACKGROUND_SYNC_CANDIDATES = 4/);
  assert.match(convexBridge, /advanceDurableBackfills/);
  assert.match(convexBridge, /Promise\.allSettled/);
  assert.match(convexBridge, /completeDiscovery: succeeded/);
});

test("backfills complete CloudWatch streams into the durable log archive", async () => {
  const backfill = await readFile(
    new URL("../scripts/backfill-convex-logs.mjs", import.meta.url),
    "utf8",
  );
  assert.match(backfill, /startFromHead: true/);
  assert.match(backfill, /response\.nextForwardToken/);
  assert.match(backfill, /ingestLogBatch/);
  assert.match(backfill, /--full/);
  assert.match(backfill, /SOURCE_PAGE_EVENTS = 500/);
  assert.match(backfill, /expectedForwardToken/);
  assert.match(backfill, /ingestProgressBatch/);
  assert.match(backfill, /Backfill incomplete/);
  assert.match(backfill, /sha256/);
});
