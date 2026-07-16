import { v } from "convex/values";
import { paginationOptsValidator } from "convex/server";
import { mutation, query, type MutationCtx } from "./_generated/server";

const EXPECTED_ISSUER = "https://oidc.vercel.com/jlasters-projects";
const TOTAL_STANDARD_BASES = 3_031_042_417;
const FORWARD_CURSOR_VERSION = 2;
const TERMINAL_SETTLE_GRACE_MS = 2 * 60 * 1_000;
const ACTIVE_JOB_STATUSES = new Set([
  "SUBMITTED",
  "PENDING",
  "RUNNABLE",
  "STARTING",
  "RUNNING",
]);
const ALLOWED_SUBJECTS = new Set(
  ["development", "preview", "production"].map(
    (environment) =>
      `owner:jlasters-projects:project:diana-aws-job-viewer:environment:${environment}`,
  ),
);

const nullableString = v.union(v.string(), v.null());
const nullableNumber = v.union(v.number(), v.null());

const jobValidator = v.object({
  jobId: v.string(),
  name: nullableString,
  status: v.string(),
  statusReason: nullableString,
  queue: nullableString,
  createdAt: nullableNumber,
  startedAt: nullableNumber,
  stoppedAt: nullableNumber,
  runId: v.string(),
  stage: v.string(),
});

const progressEventValidator = v.object({
  eventKey: v.string(),
  jobId: v.string(),
  chromosome: v.string(),
  position: v.number(),
  length: v.number(),
  observedAt: v.number(),
  active: v.boolean(),
});

const logEventValidator = v.object({
  eventKey: v.string(),
  timestamp: v.number(),
  ingestionTime: nullableNumber,
  message: v.string(),
});

async function requireViewerIdentity(ctx: {
  auth: {
    getUserIdentity: () => Promise<{
      issuer: string;
      subject?: string;
    } | null>;
  };
}) {
  const identity = await ctx.auth.getUserIdentity();
  if (
    !identity ||
    identity.issuer !== EXPECTED_ISSUER ||
    !identity.subject ||
    !ALLOWED_SUBJECTS.has(identity.subject)
  ) {
    throw new Error("Unauthorized viewer identity");
  }
}

type ProgressEvent = {
  eventKey: string;
  jobId: string;
  chromosome: string;
  position: number;
  length: number;
  observedAt: number;
  active: boolean;
};

async function upsertProgressEvents(
  ctx: MutationCtx,
  events: ProgressEvent[],
) {
  let progressEventsInserted = 0;
  let chromosomeProgressUpserted = 0;

  for (const event of events) {
    const existingEvent = await ctx.db
      .query("progressEvents")
      .withIndex("by_event_key", (q) => q.eq("eventKey", event.eventKey))
      .unique();
    if (!existingEvent) {
      await ctx.db.insert("progressEvents", event);
      progressEventsInserted += 1;
    }

    const existingProgress = await ctx.db
      .query("chromosomeProgress")
      .withIndex("by_job_chromosome", (q) =>
        q.eq("jobId", event.jobId).eq("chromosome", event.chromosome),
      )
      .unique();

    if (!existingProgress) {
      await ctx.db.insert("chromosomeProgress", {
        jobId: event.jobId,
        chromosome: event.chromosome,
        position: event.position,
        length: event.length,
        firstObservedAt: event.observedAt,
        lastObservedAt: event.observedAt,
        active: event.active,
      });
      chromosomeProgressUpserted += 1;
    } else if (
      event.position > existingProgress.position ||
      event.observedAt > existingProgress.lastObservedAt
    ) {
      await ctx.db.patch(existingProgress._id, {
        position: Math.max(existingProgress.position, event.position),
        length: event.length,
        lastObservedAt: Math.max(
          existingProgress.lastObservedAt,
          event.observedAt,
        ),
        active: event.active,
      });
      chromosomeProgressUpserted += 1;
    }
  }

  return { progressEventsInserted, chromosomeProgressUpserted };
}

export const ingestSnapshot = mutation({
  args: {
    generatedAt: v.number(),
    region: v.string(),
    queues: v.array(v.string()),
    jobs: v.array(jobValidator),
    progressEvents: v.array(progressEventValidator),
  },
  returns: v.object({
    jobsUpserted: v.number(),
    statusEventsInserted: v.number(),
    progressEventsInserted: v.number(),
    chromosomeProgressUpserted: v.number(),
  }),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);

    let statusEventsInserted = 0;
    let progressEventsInserted = 0;
    let chromosomeProgressUpserted = 0;

    for (const job of args.jobs) {
      const existing = await ctx.db
        .query("jobs")
        .withIndex("by_job_id", (q) => q.eq("jobId", job.jobId))
        .unique();
      const isTerminal = !ACTIVE_JOB_STATUSES.has(job.status);
      const jobDocument = {
        ...job,
        lastObservedAt: args.generatedAt,
        ...(isTerminal
          ? {
              terminalObservedAt:
                existing?.terminalObservedAt ?? args.generatedAt,
            }
          : {}),
      };

      if (existing) {
        if (existing.status !== job.status) {
          const eventKey = `${job.jobId}:${job.status}:${args.generatedAt}`;
          await ctx.db.insert("jobStatusEvents", {
            eventKey,
            jobId: job.jobId,
            status: job.status,
            statusReason: job.statusReason,
            observedAt: args.generatedAt,
          });
          statusEventsInserted += 1;
        }
        await ctx.db.patch(existing._id, jobDocument);
      } else {
        await ctx.db.insert("jobs", jobDocument);
        await ctx.db.insert("jobStatusEvents", {
          eventKey: `${job.jobId}:${job.status}:${args.generatedAt}`,
          jobId: job.jobId,
          status: job.status,
          statusReason: job.statusReason,
          observedAt: args.generatedAt,
        });
        statusEventsInserted += 1;
      }
    }

    ({ progressEventsInserted, chromosomeProgressUpserted } =
      await upsertProgressEvents(ctx, args.progressEvents));

    await ctx.db.insert("syncRuns", {
      generatedAt: args.generatedAt,
      ingestedAt: Date.now(),
      region: args.region,
      queues: args.queues,
      jobCount: args.jobs.length,
      progressEventCount: args.progressEvents.length,
    });

    return {
      jobsUpserted: args.jobs.length,
      statusEventsInserted,
      progressEventsInserted,
      chromosomeProgressUpserted,
    };
  },
});

const chromosomeAggregateValidator = v.object({
  name: v.string(),
  position: v.number(),
  length: v.number(),
  percent: v.number(),
  active: v.boolean(),
});

export const getAggregates = query({
  args: { jobIds: v.array(v.string()) },
  returns: v.array(
    v.object({
      jobId: v.string(),
      chromosomes: v.array(chromosomeAggregateValidator),
      started: v.number(),
      active: v.number(),
      completed: v.number(),
      queued: v.number(),
      genomePercent: v.number(),
      rateMbPerMinute: v.number(),
      etaSeconds: v.union(v.number(), v.null()),
    }),
  ),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const now = Date.now();
    const recentCutoff = now - 15 * 60 * 1_000;
    const aggregates = [];

    for (const jobId of args.jobIds) {
      const progress = await ctx.db
        .query("chromosomeProgress")
        .withIndex("by_job", (q) => q.eq("jobId", jobId))
        .collect();
      if (progress.length === 0) continue;

      const chromosomes = progress
        .map((row) => ({
          name: row.chromosome,
          position: row.position,
          length: row.length,
          percent: Math.min(100, (row.position / row.length) * 100),
          active: (row.active ?? true) && now - row.lastObservedAt < 180_000,
        }))
        .sort((left, right) => {
          const leftNumber =
            left.name === "chrX" ? 23 : Number(left.name.slice(3));
          const rightNumber =
            right.name === "chrX" ? 23 : Number(right.name.slice(3));
          return leftNumber - rightNumber;
        });

      const recentEvents = await ctx.db
        .query("progressEvents")
        .withIndex("by_job_time", (q) =>
          q.eq("jobId", jobId).gte("observedAt", recentCutoff),
        )
        .collect();
      const windows = new Map<
        string,
        { firstPosition: number; firstAt: number; lastPosition: number; lastAt: number }
      >();
      for (const event of recentEvents) {
        const window = windows.get(event.chromosome);
        if (!window) {
          windows.set(event.chromosome, {
            firstPosition: event.position,
            firstAt: event.observedAt,
            lastPosition: event.position,
            lastAt: event.observedAt,
          });
        } else {
          if (event.observedAt < window.firstAt) {
            window.firstAt = event.observedAt;
            window.firstPosition = event.position;
          }
          if (event.observedAt > window.lastAt) {
            window.lastAt = event.observedAt;
            window.lastPosition = event.position;
          }
        }
      }

      const firstTimes = [...windows.values()].map((window) => window.firstAt);
      const lastTimes = [...windows.values()].map((window) => window.lastAt);
      const elapsedSeconds =
        firstTimes.length && lastTimes.length
          ? (Math.max(...lastTimes) - Math.min(...firstTimes)) / 1_000
          : 0;
      const deltaBases = [...windows.values()].reduce(
        (sum, window) =>
          sum + Math.max(0, window.lastPosition - window.firstPosition),
        0,
      );
      const rateBasesPerSecond =
        elapsedSeconds > 30 ? deltaBases / elapsedSeconds : 0;
      const traversedBases = chromosomes.reduce(
        (sum, chromosome) =>
          sum + Math.min(chromosome.position, chromosome.length),
        0,
      );
      const remainingBases = Math.max(
        0,
        TOTAL_STANDARD_BASES - traversedBases,
      );

      aggregates.push({
        jobId,
        chromosomes,
        started: chromosomes.length,
        active: chromosomes.filter((chromosome) => chromosome.active).length,
        completed: chromosomes.filter((chromosome) => chromosome.percent >= 99.9)
          .length,
        queued: Math.max(0, 23 - chromosomes.length),
        genomePercent: (traversedBases / TOTAL_STANDARD_BASES) * 100,
        rateMbPerMinute: (rateBasesPerSecond * 60) / 1_000_000,
        etaSeconds:
          rateBasesPerSecond > 0 ? remainingBases / rateBasesPerSecond : null,
      });
    }

    return aggregates;
  },
});

export const getDashboardSummary = query({
  args: {},
  returns: v.object({
    totalJobs: v.number(),
    activeJobs: v.number(),
    succeededJobs: v.number(),
    failedJobs: v.number(),
    latestSync: v.union(
      v.null(),
      v.object({
        generatedAt: v.number(),
        ingestedAt: v.number(),
        region: v.string(),
        jobCount: v.number(),
        progressEventCount: v.number(),
      }),
    ),
  }),
  handler: async (ctx) => {
    await requireViewerIdentity(ctx);
    const jobs = await ctx.db.query("jobs").collect();
    const latestSync = await ctx.db
      .query("syncRuns")
      .withIndex("by_generated_at")
      .order("desc")
      .first();
    const activeStatuses = new Set([
      "SUBMITTED",
      "PENDING",
      "RUNNABLE",
      "STARTING",
      "RUNNING",
    ]);

    return {
      totalJobs: jobs.length,
      activeJobs: jobs.filter((job) => activeStatuses.has(job.status)).length,
      succeededJobs: jobs.filter((job) => job.status === "SUCCEEDED").length,
      failedJobs: jobs.filter((job) => job.status === "FAILED").length,
      latestSync: latestSync
        ? {
            generatedAt: latestSync.generatedAt,
            ingestedAt: latestSync.ingestedAt,
            region: latestSync.region,
            jobCount: latestSync.jobCount,
            progressEventCount: latestSync.progressEventCount,
          }
        : null,
    };
  },
});

export const getJobsNeedingStreamDiscovery = query({
  args: { jobIds: v.array(v.string()), limit: v.number() },
  returns: v.array(v.string()),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const now = Date.now();
    const jobs = [];
    for (const jobId of args.jobIds) {
      const job = await ctx.db
        .query("jobs")
        .withIndex("by_job_id", (q) => q.eq("jobId", jobId))
        .unique();
      if (job) {
        const active = ACTIVE_JOB_STATUSES.has(job.status);
        if (
          !job.streamsDiscoveredAt ||
          (active && now - job.streamsDiscoveredAt >= 2 * 60 * 1_000)
        ) {
          jobs.push(job);
        }
      }
    }
    return jobs
      .sort(
        (left, right) =>
          (left.streamsDiscoveredAt || 0) - (right.streamsDiscoveredAt || 0),
      )
      .slice(0, Math.max(1, Math.min(8, Math.floor(args.limit))))
      .map((job) => job.jobId);
  },
});

export const registerLogStreams = mutation({
  args: {
    discoveredAt: v.number(),
    jobs: v.array(
      v.object({
        jobId: v.string(),
        jobName: nullableString,
        completeDiscovery: v.boolean(),
        streams: v.array(
          v.object({
            logStreamName: v.string(),
            startedAt: v.number(),
          }),
        ),
      }),
    ),
  },
  returns: v.object({ registered: v.number() }),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    let registered = 0;
    for (const jobInput of args.jobs) {
      for (const streamInput of jobInput.streams) {
        const existing = await ctx.db
          .query("logStreams")
          .withIndex("by_job_stream", (q) =>
            q
              .eq("jobId", jobInput.jobId)
              .eq("logStreamName", streamInput.logStreamName),
          )
          .unique();
        if (existing) {
          await ctx.db.patch(existing._id, {
            jobName: jobInput.jobName,
            streamStartedAt: Math.max(
              existing.streamStartedAt || 0,
              streamInput.startedAt,
            ),
            ...(!existing.nextBackfillAt ? { nextBackfillAt: 0 } : {}),
          });
        } else {
          await ctx.db.insert("logStreams", {
            jobId: jobInput.jobId,
            jobName: jobInput.jobName,
            logStreamName: streamInput.logStreamName,
            streamStartedAt: streamInput.startedAt,
            nextForwardToken: null,
            eventCount: 0,
            firstSyncedAt: args.discoveredAt,
            lastSyncedAt: 0,
            backfillComplete: false,
            progressNextForwardToken: null,
            progressLastSyncedAt: 0,
            progressBackfillComplete: false,
            nextBackfillAt: 0,
            backfillFailureCount: 0,
          });
          registered += 1;
        }
      }

      const job = await ctx.db
        .query("jobs")
        .withIndex("by_job_id", (q) => q.eq("jobId", jobInput.jobId))
        .unique();
      if (job && jobInput.completeDiscovery) {
        await ctx.db.patch(job._id, { streamsDiscoveredAt: args.discoveredAt });
      }
    }
    return { registered };
  },
});

export const getBackfillCandidates = query({
  args: { limit: v.number() },
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const now = Date.now();
    const streams = await ctx.db
      .query("logStreams")
      .withIndex("by_next_backfill", (q) => q.lte("nextBackfillAt", now))
      .order("asc")
      .take(Math.max(1, Math.min(8, Math.floor(args.limit))));

    return Promise.all(
      streams.map(async (stream) => {
        const job = await ctx.db
          .query("jobs")
          .withIndex("by_job_id", (q) => q.eq("jobId", stream.jobId))
          .unique();
        const active = job ? ACTIVE_JOB_STATUSES.has(job.status) : false;
        const terminalAt = active
          ? null
          : job?.stoppedAt ||
            job?.terminalObservedAt ||
            job?.lastObservedAt ||
            stream.firstSyncedAt;
        const settledAfter = terminalAt
          ? terminalAt + TERMINAL_SETTLE_GRACE_MS
          : Number.POSITIVE_INFINITY;
        const rawNeedsSync =
          !active &&
          (stream.cursorVersion !== FORWARD_CURSOR_VERSION ||
            !stream.backfillComplete ||
            now < settledAfter ||
            stream.lastSyncedAt < settledAfter);
        const progressNeedsSync =
          active ||
          stream.progressCursorVersion !== FORWARD_CURSOR_VERSION ||
          !stream.progressBackfillComplete ||
          now < settledAfter ||
          (stream.progressLastSyncedAt || 0) < settledAfter;
        return {
          jobId: stream.jobId,
          jobName: stream.jobName,
          logStreamName: stream.logStreamName,
          startedAt: stream.streamStartedAt || 0,
          terminalAt,
          rawNeedsSync,
          progressNeedsSync,
        };
      }),
    );
  },
});

export const initializeBackfillQueue = mutation({
  args: { limit: v.number() },
  returns: v.object({ initialized: v.number() }),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const streams = await ctx.db
      .query("logStreams")
      .filter((q) => q.eq(q.field("nextBackfillAt"), undefined))
      .take(Math.max(1, Math.min(32, Math.floor(args.limit))));
    for (const stream of streams) {
      await ctx.db.patch(stream._id, {
        nextBackfillAt: 0,
        backfillFailureCount: 0,
      });
    }
    return { initialized: streams.length };
  },
});

export const finishBackfillAttempt = mutation({
  args: {
    jobId: v.string(),
    logStreamName: v.string(),
    succeeded: v.boolean(),
  },
  returns: v.null(),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const stream = await ctx.db
      .query("logStreams")
      .withIndex("by_job_stream", (q) =>
        q.eq("jobId", args.jobId).eq("logStreamName", args.logStreamName),
      )
      .unique();
    if (!stream) return null;

    if (!args.succeeded) {
      const failures = Math.min(8, (stream.backfillFailureCount || 0) + 1);
      await ctx.db.patch(stream._id, {
        backfillFailureCount: failures,
        nextBackfillAt:
          Date.now() + Math.min(15 * 60 * 1_000, 30_000 * 2 ** (failures - 1)),
      });
      return null;
    }

    const job = await ctx.db
      .query("jobs")
      .withIndex("by_job_id", (q) => q.eq("jobId", args.jobId))
      .unique();
    const active = job ? ACTIVE_JOB_STATUSES.has(job.status) : false;
    const terminalAt = active
      ? null
      : job?.stoppedAt ||
        job?.terminalObservedAt ||
        job?.lastObservedAt ||
        stream.firstSyncedAt;
    const settledAfter = terminalAt
      ? terminalAt + TERMINAL_SETTLE_GRACE_MS
      : Number.POSITIVE_INFINITY;
    const terminalComplete =
      !active &&
      Date.now() >= settledAfter &&
      stream.cursorVersion === FORWARD_CURSOR_VERSION &&
      stream.backfillComplete &&
      stream.lastSyncedAt >= settledAfter &&
      stream.progressCursorVersion === FORWARD_CURSOR_VERSION &&
      stream.progressBackfillComplete &&
      (stream.progressLastSyncedAt || 0) >= settledAfter;
    await ctx.db.patch(stream._id, {
      backfillFailureCount: 0,
      nextBackfillAt: terminalComplete
        ? Date.now() + 365 * 24 * 60 * 60 * 1_000
        : active
          ? Date.now() + 10_000
          : Date.now() + 1_000,
    });
    return null;
  },
});

export const getLogCursor = query({
  args: {
    jobId: v.string(),
    logStreamName: v.string(),
  },
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const stream = await ctx.db
      .query("logStreams")
      .withIndex("by_job_stream", (q) =>
        q.eq("jobId", args.jobId).eq("logStreamName", args.logStreamName),
      )
      .unique();
    if (!stream) return null;
    return {
      nextForwardToken: stream.nextForwardToken,
      eventCount: stream.eventCount,
      backfillComplete: stream.backfillComplete,
      lastSyncedAt: stream.lastSyncedAt,
      cursorVersion: stream.cursorVersion ?? 1,
    };
  },
});

export const getProgressCursor = query({
  args: {
    jobId: v.string(),
    logStreamName: v.string(),
  },
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const stream = await ctx.db
      .query("logStreams")
      .withIndex("by_job_stream", (q) =>
        q.eq("jobId", args.jobId).eq("logStreamName", args.logStreamName),
      )
      .unique();
    if (!stream) return null;
    return {
      nextForwardToken: stream.progressNextForwardToken ?? null,
      backfillComplete: stream.progressBackfillComplete ?? false,
      lastSyncedAt: stream.progressLastSyncedAt ?? null,
      cursorVersion: stream.progressCursorVersion ?? 1,
    };
  },
});

export const ingestProgressBatch = mutation({
  args: {
    jobId: v.string(),
    jobName: nullableString,
    logStreamName: v.string(),
    expectedForwardToken: v.optional(nullableString),
    nextForwardToken: nullableString,
    backfillComplete: v.boolean(),
    syncedAt: v.number(),
    events: v.array(progressEventValidator),
  },
  returns: v.object({
    progressEventsInserted: v.number(),
    chromosomeProgressUpserted: v.number(),
    cursorAdvanced: v.boolean(),
  }),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const result = await upsertProgressEvents(ctx, args.events);
    const stream = await ctx.db
      .query("logStreams")
      .withIndex("by_job_stream", (q) =>
        q.eq("jobId", args.jobId).eq("logStreamName", args.logStreamName),
      )
      .unique();

    const currentToken = stream?.progressNextForwardToken ?? null;
    const expectedForwardToken =
      args.expectedForwardToken === undefined
        ? currentToken
        : args.expectedForwardToken;
    const legacyCursorWriteAllowed =
      args.expectedForwardToken !== undefined ||
      (stream?.progressCursorVersion ?? 1) < FORWARD_CURSOR_VERSION;
    const cursorAdvanced =
      legacyCursorWriteAllowed && currentToken === expectedForwardToken;

    if (stream && cursorAdvanced) {
      await ctx.db.patch(stream._id, {
        jobName: args.jobName,
        progressNextForwardToken: args.nextForwardToken,
        progressLastSyncedAt: Math.max(
          stream.progressLastSyncedAt || 0,
          args.syncedAt,
        ),
        progressBackfillComplete: args.backfillComplete,
        progressCursorVersion: FORWARD_CURSOR_VERSION,
        nextBackfillAt: args.syncedAt,
      });
    } else if (!stream && cursorAdvanced) {
      await ctx.db.insert("logStreams", {
        jobId: args.jobId,
        jobName: args.jobName,
        logStreamName: args.logStreamName,
        nextForwardToken: null,
        eventCount: 0,
        firstSyncedAt: args.syncedAt,
        lastSyncedAt: args.syncedAt,
        backfillComplete: false,
        progressNextForwardToken: args.nextForwardToken,
        progressLastSyncedAt: args.syncedAt,
        progressBackfillComplete: args.backfillComplete,
        progressCursorVersion: FORWARD_CURSOR_VERSION,
        nextBackfillAt: args.syncedAt,
        backfillFailureCount: 0,
      });
    }

    return { ...result, cursorAdvanced };
  },
});

export const ingestLogBatch = mutation({
  args: {
    jobId: v.string(),
    jobName: nullableString,
    logStreamName: v.string(),
    expectedForwardToken: v.optional(nullableString),
    nextForwardToken: nullableString,
    updateCursor: v.boolean(),
    backfillComplete: v.boolean(),
    syncedAt: v.number(),
    events: v.array(logEventValidator),
  },
  returns: v.object({
    inserted: v.number(),
    totalEvents: v.number(),
    cursorAdvanced: v.boolean(),
  }),
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    let inserted = 0;

    for (const event of args.events) {
      const existing = await ctx.db
        .query("logEvents")
        .withIndex("by_event_key", (q) => q.eq("eventKey", event.eventKey))
        .unique();
      if (existing) continue;
      await ctx.db.insert("logEvents", {
        ...event,
        jobId: args.jobId,
        logStreamName: args.logStreamName,
      });
      inserted += 1;
    }

    const stream = await ctx.db
      .query("logStreams")
      .withIndex("by_job_stream", (q) =>
        q.eq("jobId", args.jobId).eq("logStreamName", args.logStreamName),
      )
      .unique();
    const totalEvents = (stream?.eventCount || 0) + inserted;
    const currentToken = stream?.nextForwardToken ?? null;
    const expectedForwardToken =
      args.expectedForwardToken === undefined
        ? currentToken
        : args.expectedForwardToken;
    const legacyCursorWriteAllowed =
      args.expectedForwardToken !== undefined ||
      (stream?.cursorVersion ?? 1) < FORWARD_CURSOR_VERSION;
    const cursorAdvanced =
      args.updateCursor &&
      legacyCursorWriteAllowed &&
      currentToken === expectedForwardToken;

    if (stream) {
      await ctx.db.patch(stream._id, {
        jobName: args.jobName,
        eventCount: totalEvents,
        lastSyncedAt: Math.max(stream.lastSyncedAt, args.syncedAt),
        backfillComplete: cursorAdvanced
          ? args.backfillComplete
          : stream.backfillComplete,
        ...(cursorAdvanced
          ? {
              nextForwardToken: args.nextForwardToken,
              cursorVersion: FORWARD_CURSOR_VERSION,
              nextBackfillAt: args.syncedAt,
            }
          : {}),
      });
    } else {
      await ctx.db.insert("logStreams", {
        jobId: args.jobId,
        jobName: args.jobName,
        logStreamName: args.logStreamName,
        nextForwardToken: cursorAdvanced ? args.nextForwardToken : null,
        eventCount: totalEvents,
        firstSyncedAt: args.syncedAt,
        lastSyncedAt: args.syncedAt,
        backfillComplete: cursorAdvanced && args.backfillComplete,
        ...(cursorAdvanced
          ? { cursorVersion: FORWARD_CURSOR_VERSION }
          : {}),
        nextBackfillAt: args.syncedAt,
        backfillFailureCount: 0,
      });
    }

    return { inserted, totalEvents, cursorAdvanced };
  },
});

export const getLogPage = query({
  args: {
    jobId: v.string(),
    paginationOpts: paginationOptsValidator,
  },
  handler: async (ctx, args) => {
    await requireViewerIdentity(ctx);
    const [streams, job, result] = await Promise.all([
      ctx.db
        .query("logStreams")
        .withIndex("by_job", (q) => q.eq("jobId", args.jobId))
        .collect(),
      ctx.db
        .query("jobs")
        .withIndex("by_job_id", (q) => q.eq("jobId", args.jobId))
        .unique(),
      ctx.db
        .query("logEvents")
        .withIndex("by_job_time", (q) => q.eq("jobId", args.jobId))
        .order("desc")
        .paginate(args.paginationOpts),
    ]);
    const active = job ? ACTIVE_JOB_STATUSES.has(job.status) : false;
    const terminalAt =
      job?.stoppedAt || job?.terminalObservedAt || job?.lastObservedAt || 0;
    const settledAfter = terminalAt + TERMINAL_SETTLE_GRACE_MS;
    const archiveComplete =
      !active &&
      Date.now() >= settledAfter &&
      streams.length > 0 &&
      streams.every(
        (stream) =>
          stream.cursorVersion === FORWARD_CURSOR_VERSION &&
          stream.backfillComplete &&
          stream.lastSyncedAt >= settledAfter,
      );

    return {
      jobId: args.jobId,
      jobName: streams.find((stream) => stream.jobName)?.jobName || null,
      logStreamName:
        streams.length === 1
          ? streams[0].logStreamName
          : streams.length > 1
            ? `${streams.length} CloudWatch streams`
            : null,
      events: result.page.reverse().map((event) => ({
        eventKey: event.eventKey,
        timestamp: event.timestamp,
        ingestionTime: event.ingestionTime,
        logStreamName: event.logStreamName,
        message: event.message,
      })),
      totalEvents: streams.reduce((sum, stream) => sum + stream.eventCount, 0),
      backfillComplete: archiveComplete,
      isDone: result.isDone,
      continueCursor: result.continueCursor,
    };
  },
});

export const getLogStats = query({
  args: {},
  handler: async (ctx) => {
    await requireViewerIdentity(ctx);
    const streams = await ctx.db.query("logStreams").collect();
    return {
      streamCount: streams.length,
      jobCount: new Set(streams.map((stream) => stream.jobId)).size,
      eventCount: streams.reduce((sum, stream) => sum + stream.eventCount, 0),
      completeStreamCount: streams.filter((stream) => stream.backfillComplete)
        .length,
      latestSyncAt: streams.reduce(
        (latest, stream) => Math.max(latest, stream.lastSyncedAt),
        0,
      ),
    };
  },
});
