import assert from "node:assert/strict";
import test from "node:test";

import { mergeViewerJobs } from "../lib/job-inventory.ts";

const liveJob = {
  id: "job-live",
  name: "Live job",
  status: "RUNNING",
  statusReason: null,
  queue: "production",
  createdAt: 200,
  startedAt: 210,
  stoppedAt: null,
  timeoutSeconds: 3_600,
  attempts: 1,
  runId: "run-live",
  stage: "evidence",
  logStreamName: "live/stream",
  dependsOn: [],
  progress: null,
};

test("merges live AWS state into the complete durable job inventory", () => {
  const durableJobs = [
    {
      jobId: "job-archive",
      name: "Archived job",
      status: "SUCCEEDED",
      statusReason: null,
      queue: "production",
      createdAt: 100,
      startedAt: 110,
      stoppedAt: 150,
      runId: "run-archive",
      stage: "delivery",
    },
    {
      jobId: "job-live",
      name: "Stale live job",
      status: "SUBMITTED",
      statusReason: null,
      queue: "production",
      createdAt: 200,
      startedAt: null,
      stoppedAt: null,
      runId: "run-live",
      stage: "evidence",
    },
  ];
  const archiveProgress = {
    jobId: "job-archive",
    chromosomes: [],
    started: 0,
    active: 0,
    completed: 0,
    queued: 23,
    genomePercent: 100,
    rateMbPerMinute: 0,
    etaSeconds: null,
  };

  const jobs = mergeViewerJobs([liveJob], durableJobs, [archiveProgress]);

  assert.deepEqual(
    jobs.map((job) => job.id),
    ["job-live", "job-archive"],
  );
  assert.equal(jobs[0].status, "RUNNING");
  assert.equal(jobs[0].logStreamName, "live/stream");
  assert.equal(jobs[1].status, "SUCCEEDED");
  assert.equal(jobs[1].logStreamName, null);
  assert.equal(jobs[1].progress?.genomePercent, 100);
});
