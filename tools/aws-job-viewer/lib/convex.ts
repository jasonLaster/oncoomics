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

type ViewerPayload = Awaited<ReturnType<typeof listViewerJobs>>;
type LogEventInput = {
  timestamp?: number;
  ingestionTime?: number;
  message?: string;
};

const LOG_BATCH_EVENTS = 100;
const LOG_BATCH_BYTES = 350_000;

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
) {
  const chunks = chunkLogEvents(
    events.map((event) => normalizeLogEvent(stream, event)),
  );
  if (chunks.length === 0) chunks.push([]);

  let inserted = 0;
  for (let index = 0; index < chunks.length; index += 1) {
    const finalChunk = index === chunks.length - 1;
    const result = await client.mutation(api.jobProgress.ingestLogBatch, {
      jobId: stream.jobId,
      jobName: stream.jobName,
      logStreamName: stream.logStreamName,
      nextForwardToken,
      updateCursor: finalChunk,
      backfillComplete: finalChunk && backfillComplete,
      syncedAt: Date.now(),
      events: chunks[index],
    });
    inserted += result.inserted;
  }
  return inserted;
}

async function syncLogStream(
  client: ConvexHttpClient,
  stream: ViewerLogStream,
  maxPages: number,
) {
  const cursor = await client.query(api.jobProgress.getLogCursor, {
    jobId: stream.jobId,
    logStreamName: stream.logStreamName,
  });
  let nextToken = cursor?.nextForwardToken || undefined;
  let inserted = 0;
  let pages = 0;

  while (pages < maxPages) {
    const previousToken = nextToken;
    const page = await getViewerLogStreamPage(
      stream.logStreamName,
      nextToken,
    );
    const complete = page.nextForwardToken === (previousToken || null);
    inserted += await ingestLogPage(
      client,
      stream,
      page.events,
      page.nextForwardToken,
      complete,
    );
    pages += 1;
    nextToken = page.nextForwardToken || undefined;
    if (complete) break;
  }

  return { inserted, pages };
}

async function syncProgressStream(
  client: ConvexHttpClient,
  stream: ViewerLogStream,
  maxPages: number,
) {
  const cursor = await client.query(api.jobProgress.getProgressCursor, {
    jobId: stream.jobId,
    logStreamName: stream.logStreamName,
  });
  let nextToken = cursor?.nextForwardToken || undefined;
  let progressEventsInserted = 0;
  let pages = 0;

  while (pages < maxPages) {
    const previousToken = nextToken;
    const page = await getViewerLogStreamPage(
      stream.logStreamName,
      nextToken,
    );
    const complete = page.nextForwardToken === (previousToken || null);
    const events = extractChromosomeProgressEvents(stream.jobId, page.events);
    const result = await client.mutation(api.jobProgress.ingestProgressBatch, {
      jobId: stream.jobId,
      jobName: stream.jobName,
      logStreamName: stream.logStreamName,
      nextForwardToken: page.nextForwardToken,
      backfillComplete: complete,
      syncedAt: Date.now(),
      events,
    });
    progressEventsInserted += result.progressEventsInserted;
    pages += 1;
    nextToken = page.nextForwardToken || undefined;
    if (complete) break;
  }

  return { progressEventsInserted, pages };
}

export async function persistAndMergeViewerSnapshot(
  payload: ViewerPayload,
): Promise<ViewerPayload> {
  if (!convexUrl()) return payload;

  try {
    const client = await convexClient();
    const snapshot = normalizedSnapshot(payload);
    await Promise.all(
      payload.jobs
        .filter(
          (job) =>
            job.id && job.status === "RUNNING" && Boolean(job.logStreamName),
        )
        .map(async (job) => {
          const streams = await getViewerLogStreams(job.id!);
          await Promise.all(
            streams.map((stream) => syncProgressStream(client, stream, 1_000)),
          );
        }),
    );
    await client.mutation(api.jobProgress.ingestSnapshot, snapshot);
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
            syncLogStream(client, stream, 1_000),
            syncProgressStream(client, stream, 1_000),
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
