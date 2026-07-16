#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  BatchClient,
  DescribeJobQueuesCommand,
  DescribeJobsCommand,
  ListJobsCommand,
} from "@aws-sdk/client-batch";
import {
  CloudWatchLogsClient,
  GetLogEventsCommand,
} from "@aws-sdk/client-cloudwatch-logs";
import { getVercelOidcToken } from "@vercel/oidc";
import { awsCredentialsProvider } from "@vercel/oidc-aws-credentials-provider";
import { ConvexHttpClient } from "convex/browser";
import { anyApi } from "convex/server";

const REGION = process.env.AWS_REGION || "us-east-1";
const LOG_GROUP = process.env.AWS_BATCH_LOG_GROUP || "/aws/batch/job";
const CONVEX_URL = process.env.CONVEX_URL || process.env.NEXT_PUBLIC_CONVEX_URL;
const FULL_BACKFILL = process.argv.includes("--full");
const SOURCE_PAGE_EVENTS = 500;
const STATUSES = [
  "SUBMITTED",
  "PENDING",
  "RUNNABLE",
  "STARTING",
  "RUNNING",
  "SUCCEEDED",
  "FAILED",
];
const MAX_EVENTS_PER_MUTATION = 100;
const MAX_BYTES_PER_MUTATION = 350_000;
const STANDARD_CHROMOSOME_LENGTHS = {
  chr1: 248_956_422,
  chr2: 242_193_529,
  chr3: 198_295_559,
  chr4: 190_214_555,
  chr5: 181_538_259,
  chr6: 170_805_979,
  chr7: 159_345_973,
  chr8: 145_138_636,
  chr9: 138_394_717,
  chr10: 133_797_422,
  chr11: 135_086_622,
  chr12: 133_275_309,
  chr13: 114_364_328,
  chr14: 107_043_718,
  chr15: 101_991_189,
  chr16: 90_338_345,
  chr17: 83_257_441,
  chr18: 80_373_285,
  chr19: 58_617_616,
  chr20: 64_444_167,
  chr21: 46_709_983,
  chr22: 50_818_468,
  chrX: 156_040_895,
};

if (!CONVEX_URL) {
  throw new Error("CONVEX_URL is required");
}

function clientConfig() {
  const accessKeyId = process.env.AWS_ACCESS_KEY_ID;
  const secretAccessKey = process.env.AWS_SECRET_ACCESS_KEY;
  const sessionToken = process.env.AWS_SESSION_TOKEN;
  const roleArn = process.env.AWS_ROLE_ARN;
  const credentials =
    accessKeyId && secretAccessKey
      ? {
          accessKeyId,
          secretAccessKey,
          ...(sessionToken ? { sessionToken } : {}),
        }
      : roleArn
        ? awsCredentialsProvider({ roleArn })
        : undefined;
  return { region: REGION, ...(credentials ? { credentials } : {}) };
}

function chunk(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function chunkEvents(events) {
  const chunks = [];
  let current = [];
  let currentBytes = 0;
  for (const event of events) {
    const eventBytes = Buffer.byteLength(JSON.stringify(event), "utf8");
    if (
      current.length > 0 &&
      (current.length >= MAX_EVENTS_PER_MUTATION ||
        currentBytes + eventBytes > MAX_BYTES_PER_MUTATION)
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

function normalizeEvent(jobId, logStreamName, event) {
  const timestamp = event.timestamp || event.ingestionTime || Date.now();
  const ingestionTime = event.ingestionTime || null;
  const message = event.message || "";
  const eventKey = createHash("sha256")
    .update(
      `${jobId}\0${logStreamName}\0${timestamp}\0${ingestionTime || ""}\0${message}`,
    )
    .digest("hex");
  return { eventKey, timestamp, ingestionTime, message };
}

function progressEvents(jobId, events) {
  const maxima = new Map();
  for (const event of events) {
    const observedAt = event.timestamp || Date.now();
    for (const match of (event.message || "").matchAll(
      /ProgressMeter\s+-\s+(chr(?:\d+|X)):(\d+)/g,
    )) {
      const chromosome = match[1];
      const position = Number(match[2]);
      if (!STANDARD_CHROMOSOME_LENGTHS[chromosome] || !Number.isFinite(position)) {
        continue;
      }
      const current = maxima.get(chromosome);
      if (
        !current ||
        position > current.position ||
        (position === current.position && observedAt > current.observedAt)
      ) {
        maxima.set(chromosome, { position, observedAt });
      }
    }
  }
  return [...maxima.entries()].map(([chromosome, value]) => ({
    eventKey: `${jobId}:${chromosome}:${value.position}`,
    jobId,
    chromosome,
    position: value.position,
    length: STANDARD_CHROMOSOME_LENGTHS[chromosome],
    observedAt: value.observedAt,
    active: Date.now() - value.observedAt < 180_000,
  }));
}

async function enabledQueues(batch) {
  const response = await batch.send(
    new DescribeJobQueuesCommand({ maxResults: 100 }),
  );
  const configuredQueue = process.env.AWS_BATCH_JOB_QUEUE;
  return (response.jobQueues || [])
    .filter((queue) => queue.state === "ENABLED")
    .filter(
      (queue) => !configuredQueue || queue.jobQueueName === configuredQueue,
    )
    .map((queue) => queue.jobQueueName)
    .filter(Boolean);
}

async function allJobIds(batch, queues) {
  const ids = new Set();
  for (const jobQueue of queues) {
    for (const jobStatus of STATUSES) {
      let nextToken;
      do {
        const response = await batch.send(
          new ListJobsCommand({
            jobQueue,
            jobStatus,
            maxResults: 100,
            ...(nextToken ? { nextToken } : {}),
          }),
        );
        for (const job of response.jobSummaryList || []) {
          if (job.jobId) ids.add(job.jobId);
        }
        nextToken = response.nextToken;
      } while (nextToken);
    }
  }
  return [...ids];
}

async function describeAllJobs(batch, jobIds) {
  const jobs = [];
  for (const ids of chunk(jobIds, 100)) {
    const response = await batch.send(new DescribeJobsCommand({ jobs: ids }));
    jobs.push(...(response.jobs || []));
  }
  return jobs;
}

function jobStreams(job) {
  const names = [
    job.container?.logStreamName,
    ...(job.attempts || []).map((attempt) => attempt.container?.logStreamName),
  ].filter(Boolean);
  return [...new Set(names)].map((logStreamName) => ({
    jobId: job.jobId,
    jobName: job.jobName || null,
    logStreamName,
  }));
}

async function ingestPage(
  convex,
  stream,
  events,
  nextForwardToken,
  backfillComplete,
  expectedForwardToken,
) {
  const chunks = chunkEvents(
    events.map((event) =>
      normalizeEvent(stream.jobId, stream.logStreamName, event),
    ),
  );
  if (chunks.length === 0) chunks.push([]);
  let inserted = 0;
  let cursorAdvanced = false;
  for (let index = 0; index < chunks.length; index += 1) {
    const finalChunk = index === chunks.length - 1;
    const result = await convex.mutation(
      anyApi.jobProgress.ingestLogBatch,
      {
        jobId: stream.jobId,
        jobName: stream.jobName,
        logStreamName: stream.logStreamName,
        expectedForwardToken,
        nextForwardToken,
        updateCursor: finalChunk,
        backfillComplete: finalChunk && backfillComplete,
        syncedAt: Date.now(),
        events: chunks[index],
      },
    );
    inserted += result.inserted;
    if (finalChunk) cursorAdvanced = result.cursorAdvanced;
  }
  return { inserted, cursorAdvanced };
}

async function backfillStream(logs, convex, stream) {
  const saved = await convex.query(anyApi.jobProgress.getLogCursor, {
    jobId: stream.jobId,
    logStreamName: stream.logStreamName,
  });
  let nextToken = FULL_BACKFILL ? undefined : saved?.nextForwardToken || undefined;
  let expectedForwardToken = saved?.nextForwardToken || null;
  let inserted = 0;
  let pages = 0;

  for (;;) {
    const previousToken = nextToken;
    const response = await logs.send(
      new GetLogEventsCommand({
        logGroupName: LOG_GROUP,
        logStreamName: stream.logStreamName,
        limit: SOURCE_PAGE_EVENTS,
        startFromHead: true,
        ...(nextToken ? { nextToken } : {}),
      }),
    );
    const nextForwardToken = response.nextForwardToken || null;
    const complete = nextForwardToken === (previousToken || null);
    const persisted = await ingestPage(
      convex,
      stream,
      response.events || [],
      nextForwardToken,
      complete,
      expectedForwardToken,
    );
    inserted += persisted.inserted;
    if (!persisted.cursorAdvanced) {
      console.log(
        `${stream.jobName || stream.jobId}: cursor moved concurrently; resuming from the durable cursor on the next sweep`,
      );
      return { inserted, pages, conflicted: true };
    }
    pages += 1;
    expectedForwardToken = nextForwardToken;
    nextToken = nextForwardToken || undefined;
    if (complete) break;
  }

  return { inserted, pages, conflicted: false };
}

async function backfillProgressStream(logs, convex, stream) {
  const saved = await convex.query(anyApi.jobProgress.getProgressCursor, {
    jobId: stream.jobId,
    logStreamName: stream.logStreamName,
  });
  let nextToken = FULL_BACKFILL ? undefined : saved?.nextForwardToken || undefined;
  let expectedForwardToken = saved?.nextForwardToken || null;
  let inserted = 0;
  let pages = 0;

  for (;;) {
    const previousToken = nextToken;
    const response = await logs.send(
      new GetLogEventsCommand({
        logGroupName: LOG_GROUP,
        logStreamName: stream.logStreamName,
        limit: SOURCE_PAGE_EVENTS,
        startFromHead: true,
        ...(nextToken ? { nextToken } : {}),
      }),
    );
    const nextForwardToken = response.nextForwardToken || null;
    const complete = nextForwardToken === (previousToken || null);
    const result = await convex.mutation(
      anyApi.jobProgress.ingestProgressBatch,
      {
        jobId: stream.jobId,
        jobName: stream.jobName,
        logStreamName: stream.logStreamName,
        expectedForwardToken,
        nextForwardToken,
        backfillComplete: complete,
        syncedAt: Date.now(),
        events: progressEvents(stream.jobId, response.events || []),
      },
    );
    inserted += result.progressEventsInserted;
    if (!result.cursorAdvanced) {
      return { inserted, pages, conflicted: true };
    }
    pages += 1;
    expectedForwardToken = nextForwardToken;
    nextToken = nextForwardToken || undefined;
    if (complete) break;
  }

  return { inserted, pages, conflicted: false };
}

const batch = new BatchClient(clientConfig());
const logs = new CloudWatchLogsClient(clientConfig());
const token = await getVercelOidcToken();
const convex = new ConvexHttpClient(CONVEX_URL, {
  auth: token,
  logger: false,
});
const queues = await enabledQueues(batch);
const jobIds = await allJobIds(batch, queues);
const jobs = await describeAllJobs(batch, jobIds);
const streams = jobs.flatMap(jobStreams);

console.log(
  `Backfilling ${streams.length} CloudWatch streams from ${jobs.length} Batch jobs in ${queues.length} queues.`,
);

let inserted = 0;
let progressInserted = 0;
let conflicts = 0;
for (let index = 0; index < streams.length; index += 1) {
  const stream = streams[index];
  try {
    const progressResult = await backfillProgressStream(logs, convex, stream);
    const result = await backfillStream(logs, convex, stream);
    inserted += result.inserted;
    progressInserted += progressResult.inserted;
    if (result.conflicted || progressResult.conflicted) conflicts += 1;
    console.log(
      `[${index + 1}/${streams.length}] ${stream.jobName || stream.jobId}: ${result.inserted} new logs / ${progressResult.inserted} progress events across ${result.pages} raw / ${progressResult.pages} progress pages`,
    );
  } catch (error) {
    if (error?.name === "ResourceNotFoundException") {
      console.log(
        `[${index + 1}/${streams.length}] ${stream.jobName || stream.jobId}: CloudWatch stream expired or unavailable`,
      );
      continue;
    }
    throw error;
  }
}

const stats = await convex.query(anyApi.jobProgress.getLogStats, {});
if (conflicts > 0) {
  console.error(
    `Backfill incomplete: ${conflicts} streams moved concurrently. Re-run to resume from the winning cursors.`,
  );
  process.exitCode = 1;
} else {
  console.log(
    `Backfill complete: ${inserted} new logs and ${progressInserted} progress events; ${stats.eventCount} total logs across ${stats.streamCount} streams (${stats.completeStreamCount} caught up).`,
  );
}
