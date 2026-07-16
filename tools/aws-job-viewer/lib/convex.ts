import { createHash } from "node:crypto";
import { ConvexHttpClient } from "convex/browser";
import { getVercelOidcToken } from "@vercel/oidc";
import { api } from "../convex/_generated/api";
import {
  extractChromosomeProgressEvents,
  getViewerLogStreamPage,
  getViewerLogStreams,
  type listViewerJobs,
  type ViewerLogStream,
} from "./aws";
import { syncForwardPages } from "./forward-sync";

type ViewerPayload = Awaited<ReturnType<typeof listViewerJobs>>;
type LogEventInput = {
  timestamp?: number;
  ingestionTime?: number;
  message?: string;
};

const LOG_BATCH_EVENTS = 100;
const LOG_BATCH_BYTES = 350_000;
const FOREGROUND_SYNC_MAX_PAGES = 8;
const FOREGROUND_SYNC_TIME_BUDGET_MS = 7_000;
const BACKGROUND_SYNC_MAX_PAGES = 1;
const BACKGROUND_SYNC_TIME_BUDGET_MS = 3_000;
const BACKGROUND_SYNC_CANDIDATES = 4;
const STREAM_DISCOVERY_CONCURRENCY = 4;
const TERMINAL_SETTLE_GRACE_MS = 2 * 60 * 1_000;
const ACTIVE_JOB_STATUSES = new Set([
  "SUBMITTED",
  "PENDING",
  "RUNNABLE",
  "STARTING",
  "RUNNING",
]);

type SyncBudget = {
  maxPages: number;
  timeBudgetMs: number;
};

async function mapWithConcurrency<Input, Output>(
  items: Input[],
  concurrency: number,
  worker: (item: Input) => Promise<Output>,
) {
  const results: Output[] = [];
  let nextIndex = 0;
  await Promise.all(
    Array.from(
      { length: Math.min(concurrency, items.length) },
      async () => {
        for (;;) {
          const index = nextIndex;
          nextIndex += 1;
          if (index >= items.length) return;
          results[index] = await worker(items[index]);
        }
      },
    ),
  );
  return results;
}

function convexUrl() {
  return process.env.CONVEX_URL || process.env.NEXT_PUBLIC_CONVEX_URL;
}

async function convexClient() {
  const url = convexUrl();
  if (!url) throw new Error("CONVEX_URL is required for persistent logs");
  const token = await getVercelOidcToken();
  return new ConvexHttpClient(url, { auth: token, logger: false });
}

function normalizedSnapshot(payload: ViewerPayload) {
  const generatedAt = Date.parse(payload.generatedAt);
  return {
    generatedAt,
    region: payload.region,
    queues: payload.queues,
    jobs: payload.jobs
      .filter((job) => Boolean(job.id))
      .map((job) => ({
        jobId: job.id!,
        name: job.name || null,
        status: job.status || "UNKNOWN",
        statusReason: job.statusReason,
        queue: job.queue || null,
        createdAt: job.createdAt,
        startedAt: job.startedAt,
        stoppedAt: job.stoppedAt,
        runId: job.runId,
        stage: job.stage,
      })),
    progressEvents: payload.jobs.flatMap((job) =>
      job.id && job.progress
        ? job.progress.chromosomes.map((chromosome) => ({
            eventKey: `${job.id}:${chromosome.name}:${chromosome.position}`,
            jobId: job.id!,
            chromosome: chromosome.name,
            position: chromosome.position,
            length: chromosome.length,
            observedAt: generatedAt,
            active: chromosome.active,
          }))
        : [],
    ),
  };
}

function normalizeLogEvent(stream: ViewerLogStream, event: LogEventInput) {
  const timestamp = event.timestamp || event.ingestionTime || Date.now();
  const ingestionTime = event.ingestionTime || null;
  const message = event.message || "";
  const eventKey = createHash("sha256")
    .update(
      `${stream.jobId}\0${stream.logStreamName}\0${timestamp}\0${ingestionTime || ""}\0${message}`,
    )
    .digest("hex");
  return { eventKey, timestamp, ingestionTime, message };
}

function chunkLogEvents(events: ReturnType<typeof normalizeLogEvent>[]) {
  const chunks: typeof events[] = [];
  let current: typeof events = [];
  let currentBytes = 0;
  for (const event of events) {
    const eventBytes = Buffer.byteLength(JSON.stringify(event), "utf8");
    if (
      current.length > 0 &&
      (current.length >= LOG_BATCH_EVENTS ||
        currentBytes + eventBytes > LOG_BATCH_BYTES)
    ) {
      chunks.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(event);
    currentBytes += eventBytes;
  }
  if (current.length > 0) chunks.push(current);
  return chunks;
}

async function ingestLogPage(
  client: ConvexHttpClient,
  stream: ViewerLogStream,
  events: LogEventInput[],
  nextForwardToken: string | null,
  backfillComplete: boolean,
  expectedForwardToken: string | null,
) {
  const chunks = chunkLogEvents(
    events.map((event) => normalizeLogEvent(stream, event)),
  );
  if (chunks.length === 0) chunks.push([]);

  let inserted = 0;
  let cursorAdvanced = false;
  for (let index = 0; index < chunks.length; index += 1) {
    const finalChunk = index === chunks.length - 1;
    const result = await client.mutation(api.jobProgress.ingestLogBatch, {
      jobId: stream.jobId,
      jobName: stream.jobName,
      logStreamName: stream.logStreamName,
      expectedForwardToken,
      nextForwardToken,
      updateCursor: finalChunk,
      backfillComplete: finalChunk && backfillComplete,
      syncedAt: Date.now(),
      events: chunks[index],
    });
    inserted += result.inserted;
    if (finalChunk) cursorAdvanced = result.cursorAdvanced;
  }
  return { inserted, cursorAdvanced };
}

async function syncLogStream(
  client: ConvexHttpClient,
  stream: ViewerLogStream,
  budget: SyncBudget,
  terminalAt?: number | null,
) {
  const cursor = await client.query(api.jobProgress.getLogCursor, {
    jobId: stream.jobId,
    logStreamName: stream.logStreamName,
  });
  if (
    cursor?.backfillComplete &&
    cursor.cursorVersion === 2 &&
    terminalAt &&
    Date.now() >= terminalAt + TERMINAL_SETTLE_GRACE_MS &&
    cursor.lastSyncedAt >= terminalAt + TERMINAL_SETTLE_GRACE_MS
  ) {
    return { inserted: 0, pages: 0, caughtUp: true };
  }

  let inserted = 0;
  const result = await syncForwardPages({
    initialCursor: cursor?.nextForwardToken,
    ...budget,
    loadPage: (nextToken) =>
      getViewerLogStreamPage(stream.logStreamName, nextToken),
    persistPage: async ({ page, previousToken, caughtUp }) => {
      const persisted = await ingestLogPage(
        client,
        stream,
        page.events,
        page.nextForwardToken,
        caughtUp,
        previousToken,
      );
      inserted += persisted.inserted;
      return persisted.cursorAdvanced;
    },
  });

  return {
    inserted,
    pages: result.pagesProcessed,
    caughtUp: result.caughtUp,
  };
}

async function syncProgressStream(
  client: ConvexHttpClient,
  stream: ViewerLogStream,
  budget: SyncBudget,
  terminalAt?: number | null,
) {
  const cursor = await client.query(api.jobProgress.getProgressCursor, {
    jobId: stream.jobId,
    logStreamName: stream.logStreamName,
  });
  if (
    cursor?.backfillComplete &&
    cursor.cursorVersion === 2 &&
    terminalAt &&
    Date.now() >= terminalAt + TERMINAL_SETTLE_GRACE_MS &&
    cursor.lastSyncedAt &&
    cursor.lastSyncedAt >= terminalAt + TERMINAL_SETTLE_GRACE_MS
  ) {
    return { progressEventsInserted: 0, pages: 0, caughtUp: true };
  }

  let progressEventsInserted = 0;
  const result = await syncForwardPages({
    initialCursor: cursor?.nextForwardToken,
    ...budget,
    loadPage: (nextToken) =>
      getViewerLogStreamPage(stream.logStreamName, nextToken),
    persistPage: async ({ page, previousToken, caughtUp }) => {
      const events = extractChromosomeProgressEvents(stream.jobId, page.events);
      const persisted = await client.mutation(
        api.jobProgress.ingestProgressBatch,
        {
          jobId: stream.jobId,
          jobName: stream.jobName,
          logStreamName: stream.logStreamName,
          expectedForwardToken: previousToken,
          nextForwardToken: page.nextForwardToken,
          backfillComplete: caughtUp,
          syncedAt: Date.now(),
          events,
        },
      );
      progressEventsInserted += persisted.progressEventsInserted;
      return persisted.cursorAdvanced;
    },
  });

  return {
    progressEventsInserted,
    pages: result.pagesProcessed,
    caughtUp: result.caughtUp,
  };
}

async function discoverSnapshotStreams(
  client: ConvexHttpClient,
  payload: ViewerPayload,
  force: boolean,
) {
  const jobsById = new Map(
    payload.jobs
      .filter((job) => Boolean(job.id))
      .map((job) => [job.id!, job]),
  );
  const jobIds = force
    ? [...jobsById.keys()]
    : await client.query(api.jobProgress.getJobsNeedingStreamDiscovery, {
        jobIds: [...jobsById.keys()],
        limit: STREAM_DISCOVERY_CONCURRENCY,
      });
  const discovered = await mapWithConcurrency(
    jobIds,
    STREAM_DISCOVERY_CONCURRENCY,
    async (jobId) => {
      try {
        const streams = await getViewerLogStreams(jobId);
        return { jobId, streams, succeeded: true };
      } catch (error) {
        console.warn("[convex] CloudWatch stream discovery unavailable", {
          jobId,
          error: error instanceof Error ? error.message : String(error),
        });
        return { jobId, streams: [] as ViewerLogStream[], succeeded: false };
      }
    },
  );

  if (discovered.length > 0) {
    await client.mutation(api.jobProgress.registerLogStreams, {
      discoveredAt: Date.now(),
      jobs: discovered.map(({ jobId, streams, succeeded }) => ({
        jobId,
        jobName: jobsById.get(jobId)?.name || null,
        completeDiscovery: succeeded,
        streams: streams.map((stream) => ({
          logStreamName: stream.logStreamName,
          startedAt: stream.startedAt,
        })),
      })),
    });
  }

  return discovered.flatMap(({ streams }) => streams);
}

async function advanceDurableBackfills(client: ConvexHttpClient) {
  await client.mutation(api.jobProgress.initializeBackfillQueue, { limit: 32 });
  const candidates = await client.query(
    api.jobProgress.getBackfillCandidates,
    { limit: BACKGROUND_SYNC_CANDIDATES },
  );
  const budget = {
    maxPages: BACKGROUND_SYNC_MAX_PAGES,
    timeBudgetMs: BACKGROUND_SYNC_TIME_BUDGET_MS,
  };

  await Promise.all(
    candidates.map(async (candidate) => {
      const stream: ViewerLogStream = {
        jobId: candidate.jobId,
        jobName: candidate.jobName,
        logStreamName: candidate.logStreamName,
        startedAt: candidate.startedAt,
      };
      const tasks = [
        ...(candidate.rawNeedsSync
          ? [syncLogStream(client, stream, budget, candidate.terminalAt)]
          : []),
        ...(candidate.progressNeedsSync
          ? [syncProgressStream(client, stream, budget, candidate.terminalAt)]
          : []),
      ];
      const results = await Promise.allSettled(tasks);
      const succeeded = results.every((result) => result.status === "fulfilled");
      for (const result of results) {
        if (result.status === "rejected") {
          console.warn("[convex] durable backfill slice unavailable", {
            jobId: candidate.jobId,
            logStreamName: candidate.logStreamName,
            error:
              result.reason instanceof Error
                ? result.reason.message
                : String(result.reason),
          });
        }
      }
      try {
        await client.mutation(api.jobProgress.finishBackfillAttempt, {
          jobId: candidate.jobId,
          logStreamName: candidate.logStreamName,
          succeeded,
        });
      } catch (error) {
        console.warn("[convex] unable to schedule the next backfill slice", {
          jobId: candidate.jobId,
          logStreamName: candidate.logStreamName,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }),
  );
}

export async function persistAndMergeViewerSnapshot(
  payload: ViewerPayload,
): Promise<ViewerPayload> {
  if (!convexUrl()) return payload;

  try {
    const client = await convexClient();
    const snapshot = normalizedSnapshot(payload);
    await client.mutation(api.jobProgress.ingestSnapshot, snapshot);
    const primaryStreams = payload.jobs
      .filter((job) => job.id && job.logStreamName)
      .map((job) => ({
        jobId: job.id!,
        jobName: job.name || null,
        completeDiscovery: false,
        streams: [
          {
            logStreamName: job.logStreamName!,
            startedAt: job.startedAt || 0,
          },
        ],
      }));
    if (primaryStreams.length > 0) {
      await client.mutation(api.jobProgress.registerLogStreams, {
        discoveredAt: Date.now(),
        jobs: primaryStreams,
      });
    }
    const foreground = payload.jobs.length === 1;
    const discoveredStreams = await discoverSnapshotStreams(
      client,
      payload,
      foreground,
    );

    if (foreground) {
      const job = payload.jobs[0];
      const isActive = ACTIVE_JOB_STATUSES.has(job?.status || "UNKNOWN");
      const terminalAt = isActive
        ? null
        : job?.stoppedAt || Date.parse(payload.generatedAt);
      const budget = {
        maxPages: FOREGROUND_SYNC_MAX_PAGES,
        timeBudgetMs: FOREGROUND_SYNC_TIME_BUDGET_MS,
      };
      await Promise.all(
        discoveredStreams.map(async (stream) => {
          const results = await Promise.allSettled([
            syncProgressStream(client, stream, budget, terminalAt),
            ...(!isActive
              ? [syncLogStream(client, stream, budget, terminalAt)]
              : []),
          ]);
          for (const result of results) {
            if (result.status === "rejected") {
              console.warn("[convex] foreground backfill slice unavailable", {
                jobId: stream.jobId,
                logStreamName: stream.logStreamName,
                error:
                  result.reason instanceof Error
                    ? result.reason.message
                    : String(result.reason),
              });
            }
          }
        }),
      );
    } else {
      await advanceDurableBackfills(client);
    }

    const aggregates = await client.query(api.jobProgress.getAggregates, {
      jobIds: snapshot.jobs.map((job) => job.jobId),
    });
    const byJobId = new Map(
      aggregates.map((aggregate) => [aggregate.jobId, aggregate]),
    );

    return {
      ...payload,
      jobs: payload.jobs.map((job) => ({
        ...job,
        progress: job.id ? byJobId.get(job.id) || job.progress : job.progress,
      })),
    };
  } catch (error) {
    console.warn("[convex] snapshot persistence unavailable", {
      error: error instanceof Error ? error.message : String(error),
    });
    return payload;
  }
}

export async function getPersistentViewerLogsPage(
  jobId: string,
  cursor: string | null,
  requestedPageSize = 1_000,
) {
  const client = await convexClient();

  if (!cursor) {
    try {
      const streams = await getViewerLogStreams(jobId);
      await Promise.all(
        streams.map(async (stream) => {
          await Promise.all([
            syncLogStream(client, stream, {
              maxPages: FOREGROUND_SYNC_MAX_PAGES,
              timeBudgetMs: FOREGROUND_SYNC_TIME_BUDGET_MS,
            }),
            syncProgressStream(client, stream, {
              maxPages: FOREGROUND_SYNC_MAX_PAGES,
              timeBudgetMs: FOREGROUND_SYNC_TIME_BUDGET_MS,
            }),
          ]);
        }),
      );
    } catch (error) {
      console.warn("[convex] live CloudWatch log sync unavailable", {
        jobId,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return client.query(api.jobProgress.getLogPage, {
    jobId,
    paginationOpts: {
      cursor,
      numItems: Math.max(1, Math.min(1_000, requestedPageSize)),
    },
  });
}
