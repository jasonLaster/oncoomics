import { v } from "convex/values";
import { mutation, query } from "./_generated/server";

const EXPECTED_ISSUER = "https://oidc.vercel.com/jlasters-projects";
const TOTAL_STANDARD_BASES = 3_031_042_417;
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
      const jobDocument = { ...job, lastObservedAt: args.generatedAt };

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

    for (const event of args.progressEvents) {
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
