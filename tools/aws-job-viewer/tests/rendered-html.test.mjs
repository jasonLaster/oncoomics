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
  assert.match(viewer, /Run monitor/);
  assert.match(viewer, />Overview</);
  assert.match(viewer, /Raw logs/);
  assert.match(viewer, /Refresh in \{countdown\}s/);
  assert.match(viewer, /No job selected/);
});

test("implements automatic refresh and server-side AWS access", async () => {
  const [viewer, jobsRoute, logsRoute, awsBridge] = await Promise.all([
    readFile(new URL("../app/job-viewer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/jobs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/job-logs/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/aws.ts", import.meta.url), "utf8"),
  ]);

  assert.match(viewer, /const REFRESH_SECONDS = 60/);
  assert.match(viewer, /setInterval\(\(\) => void fetchJobs\(\), REFRESH_SECONDS \* 1_000\)/);
  assert.match(viewer, /\/api\/job-logs\?jobId=/);
  assert.match(viewer, /latest 1,000 events/);
  assert.match(jobsRoute, /listViewerJobs/);
  assert.match(logsRoute, /getViewerLogs/);
  assert.match(awsBridge, /CloudWatchLogsClient/);
  assert.match(awsBridge, /DescribeJobQueuesCommand/);
  assert.match(`${jobsRoute}\n${logsRoute}`, /Cache-Control.*no-store|no-store/s);
  assert.doesNotMatch(viewer, /AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});
