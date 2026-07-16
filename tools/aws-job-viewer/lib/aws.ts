import { createHash } from "node:crypto";
import {
  BatchClient,
  DescribeJobQueuesCommand,
  DescribeJobsCommand,
  ListJobsCommand,
  type JobDetail,
  type JobStatus,
} from "@aws-sdk/client-batch";
import {
  CloudWatchLogsClient,
  GetLogEventsCommand,
  type OutputLogEvent,
} from "@aws-sdk/client-cloudwatch-logs";
import { awsCredentialsProvider } from "@vercel/oidc-aws-credentials-provider";

export const REGION = process.env.AWS_REGION || "us-east-1";
export const LOG_GROUP = process.env.AWS_BATCH_LOG_GROUP || "/aws/batch/job";

const ACTIVE_STATUSES: JobStatus[] = [
  "SUBMITTED",
  "PENDING",
  "RUNNABLE",
  "STARTING",
  "RUNNING",
];
const TERMINAL_STATUSES: JobStatus[] = ["SUCCEEDED", "FAILED"];
const STANDARD_CHROMOSOME_LENGTHS: Record<string, number> = {
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
const TOTAL_STANDARD_BASES = Object.values(STANDARD_CHROMOSOME_LENGTHS).reduce(
  (sum, length) => sum + length,
  0,
);

type CachedChromosome = { position: number; seenAt: number };
const chromosomeCache = new Map<string, Map<string, CachedChromosome>>();

export type ViewerProgressEvent = {
  eventKey: string;
  jobId: string;
  chromosome: string;
  position: number;
  length: number;
  observedAt: number;
  active: boolean;
};

export function extractChromosomeProgressEvents(
  jobId: string,
  events: Array<{ timestamp?: number; message?: string }>,
): ViewerProgressEvent[] {
  const maxima = new Map<
    string,
    { position: number; observedAt: number }
  >();

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
  return {
    region: REGION,
    ...(credentials ? { credentials } : {}),
  };
}

export const batch = new BatchClient(clientConfig());
export const logs = new CloudWatchLogsClient(clientConfig());

function chunk<T>(items: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function commandText(job: JobDetail): string {
  return [job.jobName, ...(job.container?.command || [])].join(" ");
}

function inferRunId(job: JobDetail): string {
  const text = commandText(job);
  const explicit = text.match(/diana-wgs-hrd-\d{8}T\d{6}Z/);
  if (explicit) return explicit[0];
  const timestamp = text.match(/\d{8}T\d{6}Z/);
  return timestamp ? `run-${timestamp[0]}` : job.jobName || job.jobId || "unknown";
}

function inferStage(job: JobDetail): string {
  const text = commandText(job).toLowerCase();
  if (text.includes("sha256") || text.includes("checksum")) return "integrity";
  if (text.includes("preflight")) return "preflight";
  if (text.includes("align")) return "alignment";
  if (text.includes("gather")) return "gather";
  if (text.includes("evidence")) return "evidence";
  return "batch";
}

export async function latestLogEvents(
  logStreamName: string,
  limit = 1_000,
): Promise<OutputLogEvent[]> {
  try {
    const response = await logs.send(
      new GetLogEventsCommand({
        logGroupName: LOG_GROUP,
        logStreamName,
        limit,
        startFromHead: false,
      }),
    );
    return response.events || [];
  } catch (error) {
    if ((error as { name?: string }).name === "ResourceNotFoundException") {
      return [];
    }
    throw error;
  }
}

export type ViewerLogStream = {
  jobId: string;
  jobName: string | null;
  logStreamName: string;
  startedAt: number;
};

export async function getViewerLogStreams(
  jobId: string,
): Promise<ViewerLogStream[]> {
  const response = await batch.send(new DescribeJobsCommand({ jobs: [jobId] }));
  const job = response.jobs?.[0];
  if (!job) throw new Error("Job not found");
  const latestAttemptStartedAt = Math.max(
    job.startedAt || 0,
    ...(job.attempts || []).map((attempt) => attempt.startedAt || 0),
  );
  const candidates = [
    {
      logStreamName: job.container?.logStreamName,
      startedAt: latestAttemptStartedAt,
    },
    ...(job.attempts || []).map((attempt) => ({
      logStreamName: attempt.container?.logStreamName,
      startedAt: attempt.startedAt || 0,
    })),
  ].filter(
    (candidate): candidate is { logStreamName: string; startedAt: number } =>
      Boolean(candidate.logStreamName),
  );
  const byName = new Map<string, number>();
  for (const candidate of candidates) {
    byName.set(
      candidate.logStreamName,
      Math.max(byName.get(candidate.logStreamName) || 0, candidate.startedAt),
    );
  }
  return [...byName.entries()]
    .sort((left, right) => right[1] - left[1])
    .map(([logStreamName, startedAt]) => ({
      jobId,
      jobName: job.jobName || null,
      logStreamName,
      startedAt,
    }));
}

export async function getViewerLogStreamPage(
  logStreamName: string,
  nextToken?: string,
  limit = 500,
) {
  try {
    const response = await logs.send(
      new GetLogEventsCommand({
        logGroupName: LOG_GROUP,
        logStreamName,
        limit,
        startFromHead: true,
        ...(nextToken ? { nextToken } : {}),
      }),
    );
    return {
      events: response.events || [],
      nextForwardToken: response.nextForwardToken || null,
    };
  } catch (error) {
    if ((error as { name?: string }).name === "ResourceNotFoundException") {
      return { events: [], nextForwardToken: nextToken || null };
    }
    throw error;
  }
}

type DirectLogCursor = {
  version: 1;
  jobId: string;
  streamName: string;
  nextBackwardToken: string | null;
};

const DIRECT_LOG_CURSOR_PREFIX = "cloudwatch:";

function decodeDirectLogCursor(cursor: string | null): DirectLogCursor | null {
  if (!cursor?.startsWith(DIRECT_LOG_CURSOR_PREFIX)) return null;
  try {
    const decoded = JSON.parse(
      Buffer.from(cursor.slice(DIRECT_LOG_CURSOR_PREFIX.length), "base64url").toString(
        "utf8",
      ),
    ) as DirectLogCursor;
    if (
      decoded.version !== 1 ||
      typeof decoded.jobId !== "string" ||
      typeof decoded.streamName !== "string" ||
      (decoded.nextBackwardToken !== null &&
        typeof decoded.nextBackwardToken !== "string")
    ) {
      return null;
    }
    return decoded;
  } catch {
    return null;
  }
}

function encodeDirectLogCursor(cursor: DirectLogCursor) {
  return `${DIRECT_LOG_CURSOR_PREFIX}${Buffer.from(JSON.stringify(cursor)).toString("base64url")}`;
}

function directLogEvent(
  stream: ViewerLogStream,
  event: OutputLogEvent,
) {
  const timestamp = event.timestamp ?? event.ingestionTime ?? 0;
  const ingestionTime = event.ingestionTime ?? null;
  const message = event.message || "";
  const eventKey = createHash("sha256")
    .update(
      `${stream.jobId}\0${stream.logStreamName}\0${timestamp}\0${ingestionTime || ""}\0${message}`,
    )
    .digest("hex");
  return {
    eventKey,
    timestamp,
    ingestionTime,
    logStreamName: stream.logStreamName,
    message,
  };
}

/**
 * Read newest-first CloudWatch history when the durable Convex archive is
 * unavailable. The opaque cursor records the active attempt by stream name and
 * advances older only after that stream's backward token stabilizes.
 */
export async function getDirectCloudWatchLogsPage(
  jobId: string,
  cursor: string | null,
  requestedPageSize = 1_000,
) {
  const streams = await getViewerLogStreams(jobId);
  if (streams.length === 0) {
    return {
      jobId,
      jobName: null,
      logStreamName: null,
      events: [],
      totalEvents: 0,
      backfillComplete: true,
      isDone: true,
      continueCursor: null,
    };
  }

  const previous = decodeDirectLogCursor(cursor);
  let streamIndex =
    previous?.jobId === jobId
      ? streams.findIndex((stream) => stream.logStreamName === previous.streamName)
      : 0;
  if (streamIndex < 0) streamIndex = 0;
  let nextToken = previous?.jobId === jobId ? previous.nextBackwardToken : null;
  const limit = Math.max(1, Math.min(10_000, requestedPageSize));

  while (streamIndex < streams.length) {
    const stream = streams[streamIndex];
    let response;
    try {
      response = await logs.send(
        new GetLogEventsCommand({
          logGroupName: LOG_GROUP,
          logStreamName: stream.logStreamName,
          limit,
          startFromHead: false,
          ...(nextToken ? { nextToken } : {}),
        }),
      );
    } catch (error) {
      if ((error as { name?: string }).name === "ResourceNotFoundException") {
        streamIndex += 1;
        nextToken = null;
        continue;
      }
      throw error;
    }

    const nextBackwardToken = response.nextBackwardToken || null;
    if (nextToken && nextBackwardToken === nextToken) {
      streamIndex += 1;
      nextToken = null;
      continue;
    }

    const events = (response.events || [])
      .map((event) => directLogEvent(stream, event))
      .sort(
        (left, right) =>
          left.timestamp - right.timestamp ||
          left.eventKey.localeCompare(right.eventKey),
      );
    const streamHasMore = nextBackwardToken !== null;
    const hasOlderStream = streamIndex < streams.length - 1;
    const isDone = !streamHasMore && !hasOlderStream;
    const nextCursor: DirectLogCursor | null = isDone
      ? null
      : streamHasMore
        ? {
            version: 1,
            jobId,
            streamName: stream.logStreamName,
            nextBackwardToken,
          }
        : {
            version: 1,
            jobId,
            streamName: streams[streamIndex + 1].logStreamName,
            nextBackwardToken: null,
          };
    return {
      jobId,
      jobName: streams.find((item) => item.jobName)?.jobName || null,
      logStreamName:
        streams.length === 1
          ? streams[0].logStreamName
          : `${streams.length} CloudWatch streams`,
      events,
      totalEvents: events.length,
      backfillComplete: isDone,
      isDone,
      continueCursor: nextCursor ? encodeDirectLogCursor(nextCursor) : null,
    };
  }

  return {
    jobId,
    jobName: streams.find((stream) => stream.jobName)?.jobName || null,
    logStreamName:
      streams.length === 1
        ? streams[0].logStreamName
        : `${streams.length} CloudWatch streams`,
    events: [],
    totalEvents: 0,
    backfillComplete: true,
    isDone: true,
    continueCursor: null,
  };
}

function parseChromosomeProgress(jobId: string, events: OutputLogEvent[]) {
  const cached = chromosomeCache.get(jobId) || new Map<string, CachedChromosome>();
  const windowFirst = new Map<string, { position: number; seenAt: number }>();
  const windowLast = new Map<string, { position: number; seenAt: number }>();

  for (const event of events) {
    const seenAt = event.timestamp || Date.now();
    const message = event.message || "";
    for (const match of message.matchAll(/ProgressMeter\s+-\s+(chr(?:\d+|X)):(\d+)/g)) {
      const chromosome = match[1];
      const position = Number(match[2]);
      if (!STANDARD_CHROMOSOME_LENGTHS[chromosome] || !Number.isFinite(position)) {
        continue;
      }
      if (!windowFirst.has(chromosome)) {
        windowFirst.set(chromosome, { position, seenAt });
      }
      windowLast.set(chromosome, { position, seenAt });
      const previous = cached.get(chromosome);
      if (!previous || position >= previous.position) {
        cached.set(chromosome, { position, seenAt });
      }
    }
  }
  chromosomeCache.set(jobId, cached);

  const chromosomes = [...cached.entries()]
    .map(([name, value]) => {
      const length = STANDARD_CHROMOSOME_LENGTHS[name];
      return {
        name,
        position: value.position,
        length,
        percent: Math.min(100, (value.position / length) * 100),
        active: Date.now() - value.seenAt < 180_000,
      };
    })
    .sort((left, right) => {
      const leftNumber = left.name === "chrX" ? 23 : Number(left.name.slice(3));
      const rightNumber = right.name === "chrX" ? 23 : Number(right.name.slice(3));
      return leftNumber - rightNumber;
    });

  let rateBasesPerSecond = 0;
  const firstTimes = [...windowFirst.values()].map((value) => value.seenAt);
  const lastTimes = [...windowLast.values()].map((value) => value.seenAt);
  if (firstTimes.length && lastTimes.length) {
    const elapsedSeconds = (Math.max(...lastTimes) - Math.min(...firstTimes)) / 1_000;
    const deltaBases = [...windowLast.entries()].reduce((sum, [name, value]) => {
      const first = windowFirst.get(name);
      return sum + (first ? Math.max(0, value.position - first.position) : 0);
    }, 0);
    if (elapsedSeconds > 30) rateBasesPerSecond = deltaBases / elapsedSeconds;
  }

  const traversedBases = chromosomes.reduce(
    (sum, chromosome) => sum + Math.min(chromosome.position, chromosome.length),
    0,
  );
  const remainingBases = Math.max(0, TOTAL_STANDARD_BASES - traversedBases);
  const etaSeconds = rateBasesPerSecond > 0 ? remainingBases / rateBasesPerSecond : null;

  return {
    chromosomes,
    started: chromosomes.length,
    active: chromosomes.filter((chromosome) => chromosome.active).length,
    completed: chromosomes.filter((chromosome) => chromosome.percent >= 99.9).length,
    queued: Math.max(0, 23 - chromosomes.length),
    genomePercent: (traversedBases / TOTAL_STANDARD_BASES) * 100,
    rateMbPerMinute: (rateBasesPerSecond * 60) / 1_000_000,
    etaSeconds,
  };
}

async function viewerJobFromDetail(job: JobDetail) {
  const logStreamName = job.container?.logStreamName || null;
  const logEvents =
    job.status === "RUNNING" && logStreamName
      ? await latestLogEvents(logStreamName, 1_000)
      : [];
  const progress = logEvents.length
    ? parseChromosomeProgress(job.jobId || "unknown", logEvents)
    : null;
  return {
    id: job.jobId,
    name: job.jobName,
    status: job.status,
    statusReason: job.statusReason || job.container?.reason || null,
    queue: job.jobQueue?.split("/").at(-1) || job.jobQueue,
    createdAt: job.createdAt || null,
    startedAt: job.startedAt || null,
    stoppedAt: job.stoppedAt || null,
    timeoutSeconds: job.timeout?.attemptDurationSeconds || null,
    attempts: job.attempts?.length || 0,
    runId: inferRunId(job),
    stage: inferStage(job),
    logStreamName,
    dependsOn: (job.dependsOn || []).map((dependency) => dependency.jobId),
    array: job.arrayProperties
      ? {
          size: job.arrayProperties.size || null,
          index: job.arrayProperties.index ?? null,
          statusSummary: job.arrayProperties.statusSummary || null,
        }
      : null,
    progress,
  };
}

export async function getViewerJob(jobId: string) {
  const response = await batch.send(new DescribeJobsCommand({ jobs: [jobId] }));
  const job = response.jobs?.[0];
  if (!job) return null;
  return viewerJobFromDetail(job);
}

export async function listViewerJobs() {
  const queueResponse = await batch.send(
    new DescribeJobQueuesCommand({ maxResults: 100 }),
  );
  const configuredQueue = process.env.AWS_BATCH_JOB_QUEUE;
  const queues = (queueResponse.jobQueues || [])
    .filter((queue) => queue.state === "ENABLED")
    .filter((queue) => !configuredQueue || queue.jobQueueName === configuredQueue)
    .map((queue) => queue.jobQueueName)
    .filter((queue): queue is string => Boolean(queue));

  const cutoff = Date.now() - 24 * 60 * 60 * 1_000;
  const summaries = (
    await Promise.all(
      queues.flatMap((jobQueue) =>
        [...ACTIVE_STATUSES, ...TERMINAL_STATUSES].map(async (jobStatus) => {
          const response = await batch.send(
            new ListJobsCommand({ jobQueue, jobStatus, maxResults: 100 }),
          );
          return (response.jobSummaryList || [])
            .filter(
              (job) =>
                ACTIVE_STATUSES.includes(jobStatus) || (job.createdAt || 0) >= cutoff,
            )
            .map((job) => ({ ...job, sourceQueue: jobQueue }));
        }),
      ),
    )
  ).flat();

  const uniqueIds = [
    ...new Set(
      summaries
        .sort((left, right) => (right.createdAt || 0) - (left.createdAt || 0))
        .map((job) => job.jobId)
        .filter((jobId): jobId is string => Boolean(jobId)),
    ),
  ].slice(0, 100);

  const details = (
    await Promise.all(
      chunk(uniqueIds, 100).map(async (jobs) => {
        const response = await batch.send(new DescribeJobsCommand({ jobs }));
        return response.jobs || [];
      }),
    )
  ).flat();

  const jobs = await Promise.all(details.map(viewerJobFromDetail));

  return {
    generatedAt: new Date().toISOString(),
    region: REGION,
    queues,
    jobs: jobs.sort((left, right) => (right.createdAt || 0) - (left.createdAt || 0)),
  };
}

export async function getViewerLogs(jobId: string) {
  const response = await batch.send(new DescribeJobsCommand({ jobs: [jobId] }));
  const job = response.jobs?.[0];
  if (!job) throw new Error("Job not found");
  const logStreamName = job.container?.logStreamName;
  if (!logStreamName) {
    return { jobId, jobName: job.jobName, logStreamName: null, events: [] };
  }
  const events = await latestLogEvents(logStreamName, 1_000);
  return {
    jobId,
    jobName: job.jobName,
    logStreamName,
    events: events.map((event) => ({
      timestamp: event.timestamp || null,
      message: event.message || "",
    })),
  };
}
