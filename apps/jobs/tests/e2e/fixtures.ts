import type { Page } from "@playwright/test";

const BASE_TIME = Date.UTC(2026, 6, 16, 18, 0, 0);

const chromosomeProgress = [
  { name: "chr1", position: 248_956_422, length: 248_956_422, percent: 100, active: false },
  { name: "chr2", position: 242_193_529, length: 242_193_529, percent: 100, active: false },
  { name: "chr17", position: 56_245_000, length: 83_257_441, percent: 67.6, active: true },
];

export const jobsPayload = {
  generatedAt: "2026-07-16T18:08:00.000Z",
  region: "us-east-1",
  queues: ["diana-omics-production"],
  jobs: [
    {
      id: "job-evidence-running",
      name: "Diana HRD evidence",
      status: "RUNNING",
      statusReason: "Calling chromosome shards in parallel.",
      queue: "diana-omics-production",
      createdAt: BASE_TIME - 48 * 60_000,
      startedAt: BASE_TIME - 44 * 60_000,
      stoppedAt: null,
      timeoutSeconds: 21_600,
      attempts: 1,
      runId: "run-diana-v2-e2e",
      stage: "evidence",
      logStreamName: "diana/run-diana-v2-e2e/evidence",
      dependsOn: ["job-alignment-complete"],
      progress: {
        chromosomes: chromosomeProgress,
        started: 17,
        active: 1,
        completed: 16,
        queued: 6,
        genomePercent: 37.5,
        rateMbPerMinute: 42.1,
        etaSeconds: 5_400,
      },
    },
    {
      id: "job-alignment-complete",
      name: "Alignment gather",
      status: "SUCCEEDED",
      statusReason: null,
      queue: "diana-omics-production",
      createdAt: BASE_TIME - 102 * 60_000,
      startedAt: BASE_TIME - 98 * 60_000,
      stoppedAt: BASE_TIME - 50 * 60_000,
      timeoutSeconds: 21_600,
      attempts: 1,
      runId: "run-diana-v2-e2e",
      stage: "alignment",
      logStreamName: "diana/run-diana-v2-e2e/alignment",
      dependsOn: ["job-integrity-complete"],
      progress: null,
    },
    {
      id: "job-filter-failed",
      name: "Filter failure sentinel",
      status: "FAILED",
      statusReason: "Container exited after the retry budget was exhausted.",
      queue: "diana-omics-production",
      createdAt: BASE_TIME - 8 * 60 * 60_000,
      startedAt: BASE_TIME - 7.8 * 60 * 60_000,
      stoppedAt: BASE_TIME - 7.5 * 60 * 60_000,
      timeoutSeconds: 21_600,
      attempts: 2,
      runId: "run-failed-v2-e2e",
      stage: "filter",
      logStreamName: "diana/run-failed-v2-e2e/filter",
      dependsOn: ["job-gather-complete"],
      progress: null,
    },
    {
      id: "job-archive-complete",
      name: "Archived validation",
      status: "SUCCEEDED",
      statusReason: null,
      queue: "diana-omics-production",
      createdAt: BASE_TIME - 30 * 60 * 60_000,
      startedAt: BASE_TIME - 29.8 * 60 * 60_000,
      stoppedAt: BASE_TIME - 29.5 * 60 * 60_000,
      timeoutSeconds: 21_600,
      attempts: 1,
      runId: "run-archive-v2-e2e",
      stage: "delivery",
      logStreamName: "diana/run-archive-v2-e2e/delivery",
      dependsOn: ["job-filter-complete"],
      progress: null,
    },
  ],
};

type MockLogEvent = {
  eventKey: string;
  timestamp: number;
  ingestionTime: number;
  logStreamName: string;
  message: string;
};

function event(index: number, message: string): MockLogEvent {
  return {
    eventKey: `mock-log-${index.toString().padStart(3, "0")}`,
    timestamp: BASE_TIME + index * 1_000,
    ingestionTime: BASE_TIME + index * 1_000 + 250,
    logStreamName: "diana/run-diana-v2-e2e/evidence",
    message,
  };
}

const olderEvents = [
  event(1, "INFO Intake integrity checksum verified for tumor.bam"),
  event(2, "INFO Workflow stage alignment completed in 00:47:58"),
  ...Array.from({ length: 16 }, (_, index) =>
    event(index + 3, `INFO Mutect2 shard chr${index + 1} queued`),
  ),
];

const newestEvents = [
  event(19, "INFO ProgressMeter - chr17 67.5% complete at 42.1 Mb/min"),
  event(20, "WARN AWS Batch container retry scheduled after transient interruption"),
  event(21, "ERROR Task failed: contamination threshold exceeded for control sample"),
  event(
    22,
    JSON.stringify({
      level: "info",
      category: "delivery",
      event: "artifact_uploaded",
      message: "Encrypted reviewer packet uploaded",
      artifact: "reviewer_packet.md",
    }),
  ),
  ...Array.from({ length: 8 }, (_, index) =>
    event(index + 23, `INFO Evidence shard chr${index + 18} heartbeat received`),
  ),
];

export const logPages = {
  newest: {
    jobId: "job-evidence-running",
    jobName: "Diana HRD evidence",
    logStreamName: "diana/run-diana-v2-e2e/evidence",
    events: newestEvents,
    totalEvents: olderEvents.length + newestEvents.length,
    backfillComplete: true,
    isDone: false,
    continueCursor: "older-page",
  },
  older: {
    jobId: "job-evidence-running",
    jobName: "Diana HRD evidence",
    logStreamName: "diana/run-diana-v2-e2e/evidence",
    events: olderEvents,
    totalEvents: olderEvents.length + newestEvents.length,
    backfillComplete: true,
    isDone: true,
    continueCursor: null,
  },
};

export async function installApiMocks(
  page: Page,
  options: { statusProgressPercent?: number } = {},
) {
  const jobRequests: string[] = [];
  const statusRequests: string[] = [];
  const logRequests: string[] = [];

  await page.route(/\/api\/jobs(?:\?.*)?$/, async (route) => {
    jobRequests.push(route.request().url());
    await route.fulfill({
      json: jobsPayload,
    });
  });

  await page.route(/\/api\/job-status(?:\?.*)?$/, async (route) => {
    const url = route.request().url();
    statusRequests.push(url);
    const jobId = new URL(url).searchParams.get("jobId");
    const fixtureJob = jobsPayload.jobs.find((item) => item.id === jobId);
    const job =
      fixtureJob &&
      options.statusProgressPercent !== undefined &&
      fixtureJob.progress
        ? {
            ...fixtureJob,
            progress: {
              ...fixtureJob.progress,
              genomePercent: options.statusProgressPercent,
            },
          }
        : fixtureJob;
    await route.fulfill({
      status: job ? 200 : 404,
      json: job
        ? { generatedAt: new Date().toISOString(), region: jobsPayload.region, job }
        : { error: "Job not found" },
    });
  });

  await page.route(/\/api\/job-logs(?:\?.*)?$/, async (route) => {
    const url = route.request().url();
    logRequests.push(url);
    const cursor = new URL(url).searchParams.get("cursor");
    await route.fulfill({
      json: cursor === "older-page" ? logPages.older : logPages.newest,
    });
  });

  return { jobRequests, statusRequests, logRequests };
}
