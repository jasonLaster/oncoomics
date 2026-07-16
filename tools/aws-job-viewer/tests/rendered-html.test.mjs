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
  assert.match(viewer, /Next sync \{countdown\}s/);
  assert.match(viewer, /No job selected/);
  assert.match(viewer, /data-testid="left-rail"/);
  assert.match(viewer, /data-testid="right-rail"/);
  assert.match(viewer, /data-testid="toggle-left-rail"/);
  assert.match(viewer, /data-testid="toggle-right-rail"/);
  assert.match(viewer, /data-testid="workflow-progress"/);
});

test("implements automatic refresh and server-side AWS access", async () => {
  const [viewer, jobsRoute, logsRoute, awsBridge] = await Promise.all([
    readFile(new URL("../app/job-viewer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/jobs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/job-logs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/aws.ts", import.meta.url), "utf8"),
  ]);

  assert.match(viewer, /const REFRESH_SECONDS = 60/);
  assert.match(
    viewer,
    /const refreshTimer = window\.setInterval\([\s\S]*?fetchJobs\(\)[\s\S]*?REFRESH_SECONDS \* 1_000/,
  );
  assert.match(viewer, /\/api\/job-logs\?\$\{searchParams\.toString\(\)\}/);
  assert.match(viewer, /new IntersectionObserver/);
  assert.match(viewer, /data-testid="log-pagination-sentinel"/);
  assert.match(viewer, /data-testid="log-feed"/);
  assert.match(viewer, /data-testid="log-search"/);
  assert.match(viewer, /data-testid="log-level-filter"/);
  assert.match(viewer, /data-testid="log-category-filter"/);
  assert.match(viewer, /preserveScrollHeightRef/);
  assert.match(jobsRoute, /listViewerJobs/);
  assert.match(logsRoute, /getPersistentViewerLogsPage/);
  assert.match(awsBridge, /CloudWatchLogsClient/);
  assert.match(awsBridge, /DescribeJobQueuesCommand/);
  assert.match(awsBridge, /awsCredentialsProvider/);
  assert.match(awsBridge, /AWS_ROLE_ARN/);
  assert.match(`${jobsRoute}\n${logsRoute}`, /Cache-Control.*no-store|no-store/s);
  assert.doesNotMatch(viewer, /AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});

test("persists normalized progress and complete logs with project-scoped OIDC", async () => {
  const [jobsRoute, convexBridge, schema, functions, authConfig] = await Promise.all([
    readFile(new URL("../app/api/jobs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/convex.ts", import.meta.url), "utf8"),
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
  assert.match(functions, /paginationOptsValidator/);
  assert.match(functions, /TOTAL_STANDARD_BASES = 3_031_042_417/);
  assert.match(authConfig, /oidc\.vercel\.com\/jlasters-projects/);
  assert.match(functions, /project:diana-aws-job-viewer:environment:/);
  assert.match(schema, /message: v\.string/);
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
  assert.match(backfill, /sha256/);
});
