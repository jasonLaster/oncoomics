import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

const nullableString = v.union(v.string(), v.null());
const nullableNumber = v.union(v.number(), v.null());

export default defineSchema({
  jobs: defineTable({
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
    lastObservedAt: v.number(),
  })
    .index("by_job_id", ["jobId"])
    .index("by_status", ["status"])
    .index("by_run_id", ["runId"]),

  jobStatusEvents: defineTable({
    eventKey: v.string(),
    jobId: v.string(),
    status: v.string(),
    statusReason: nullableString,
    observedAt: v.number(),
  })
    .index("by_event_key", ["eventKey"])
    .index("by_job_time", ["jobId", "observedAt"])
    .index("by_status_time", ["status", "observedAt"]),

  progressEvents: defineTable({
    eventKey: v.string(),
    jobId: v.string(),
    chromosome: v.string(),
    position: v.number(),
    length: v.number(),
    observedAt: v.number(),
    active: v.optional(v.boolean()),
  })
    .index("by_event_key", ["eventKey"])
    .index("by_job_time", ["jobId", "observedAt"])
    .index("by_job_chromosome_time", ["jobId", "chromosome", "observedAt"]),

  chromosomeProgress: defineTable({
    jobId: v.string(),
    chromosome: v.string(),
    position: v.number(),
    length: v.number(),
    firstObservedAt: v.number(),
    lastObservedAt: v.number(),
    active: v.optional(v.boolean()),
  })
    .index("by_job", ["jobId"])
    .index("by_job_chromosome", ["jobId", "chromosome"]),

  syncRuns: defineTable({
    generatedAt: v.number(),
    ingestedAt: v.number(),
    region: v.string(),
    queues: v.array(v.string()),
    jobCount: v.number(),
    progressEventCount: v.number(),
  }).index("by_generated_at", ["generatedAt"]),
});
