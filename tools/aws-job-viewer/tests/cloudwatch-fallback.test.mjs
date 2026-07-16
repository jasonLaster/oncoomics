import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  batch,
  extractChromosomeProgressEvents,
  getDirectCloudWatchLogsPage,
  logs,
} from "../lib/aws.ts";

const originalBatchSend = batch.send;
const originalLogsSend = logs.send;

afterEach(() => {
  batch.send = originalBatchSend;
  logs.send = originalLogsSend;
});

function job({
  current = "attempt-new",
  attempts = [
    { startedAt: 100, container: { logStreamName: "attempt-old" } },
    { startedAt: 300, container: { logStreamName: "attempt-new" } },
  ],
} = {}) {
  return {
    jobId: "job-1",
    jobName: "Evidence run",
    startedAt: 50,
    container: current ? { logStreamName: current } : {},
    attempts,
  };
}

function mockJob(detail) {
  batch.send = async () => ({ jobs: [detail] });
}

function cursor(value) {
  return `cloudwatch:${Buffer.from(JSON.stringify(value)).toString("base64url")}`;
}

function decodeCursor(value) {
  return JSON.parse(
    Buffer.from(value.slice("cloudwatch:".length), "base64url").toString("utf8"),
  );
}

test("extracts page maxima for durable chromosome progress", () => {
  const now = Date.now();
  const events = extractChromosomeProgressEvents("job-1", [
    {
      timestamp: now - 30_000,
      message: "INFO ProgressMeter - chr17:12000000  1.0  12000000",
    },
    {
      timestamp: now - 10_000,
      message:
        "INFO ProgressMeter - chr17:43044295  2.0  43044295 ProgressMeter - chr2:242193100",
    },
    {
      timestamp: now,
      message: "INFO ProgressMeter - chrY:1000 ignored",
    },
  ]);

  assert.deepEqual(
    events.map((event) => [event.chromosome, event.position]),
    [
      ["chr17", 43_044_295],
      ["chr2", 242_193_100],
    ],
  );
  assert.equal(events[0].eventKey, "job-1:chr17:43044295");
  assert.equal(events[0].observedAt, now - 10_000);
  assert.equal(events[0].active, true);
});

test("reads the newest attempt first and produces stable event keys", async () => {
  mockJob(job());
  const calls = [];
  logs.send = async (command) => {
    calls.push(command.input);
    return {
      events: [{ timestamp: 200, ingestionTime: 210, message: "heartbeat" }],
      nextBackwardToken: "new-token",
    };
  };

  const first = await getDirectCloudWatchLogsPage("job-1", null, 25);
  const second = await getDirectCloudWatchLogsPage("job-1", null, 25);

  assert.equal(calls[0].logStreamName, "attempt-new");
  assert.equal(calls[0].startFromHead, false);
  assert.equal(calls[0].limit, 25);
  assert.equal(first.events.length, 1);
  assert.equal(first.events[0].eventKey, second.events[0].eventKey);
  assert.match(first.continueCursor, /^cloudwatch:/);
  assert.equal(decodeCursor(first.continueCursor).streamName, "attempt-new");
});

test("keeps paging after an empty page when the backward token changes", async () => {
  mockJob(job({ current: "only", attempts: [] }));
  logs.send = async () => ({ events: [], nextBackwardToken: "token-2" });

  const page = await getDirectCloudWatchLogsPage(
    "job-1",
    cursor({
      version: 1,
      jobId: "job-1",
      streamName: "only",
      nextBackwardToken: "token-1",
    }),
    10,
  );

  assert.equal(page.events.length, 0);
  assert.equal(page.isDone, false);
  assert.equal(page.backfillComplete, false);
  assert.equal(decodeCursor(page.continueCursor).nextBackwardToken, "token-2");
});

test("advances from a stable newest-attempt token to the prior attempt", async () => {
  mockJob(job());
  const calls = [];
  logs.send = async (command) => {
    calls.push(command.input);
    if (command.input.logStreamName === "attempt-new") {
      return { events: [], nextBackwardToken: "new-token" };
    }
    return {
      events: [{ timestamp: 90, ingestionTime: 91, message: "prior attempt" }],
      nextBackwardToken: "old-token",
    };
  };

  const page = await getDirectCloudWatchLogsPage(
    "job-1",
    cursor({
      version: 1,
      jobId: "job-1",
      streamName: "attempt-new",
      nextBackwardToken: "new-token",
    }),
    10,
  );

  assert.deepEqual(
    calls.map((call) => call.logStreamName),
    ["attempt-new", "attempt-old"],
  );
  assert.equal(page.events[0].message, "prior attempt");
  assert.equal(decodeCursor(page.continueCursor).streamName, "attempt-old");
});

test("a named cursor survives a newly inserted retry", async () => {
  mockJob(
    job({
      current: "attempt-latest",
      attempts: [
        { startedAt: 100, container: { logStreamName: "attempt-old" } },
        { startedAt: 500, container: { logStreamName: "attempt-latest" } },
      ],
    }),
  );
  const calls = [];
  logs.send = async (command) => {
    calls.push(command.input);
    return { events: [], nextBackwardToken: "old-token-2" };
  };

  await getDirectCloudWatchLogsPage(
    "job-1",
    cursor({
      version: 1,
      jobId: "job-1",
      streamName: "attempt-old",
      nextBackwardToken: "old-token",
    }),
    10,
  );

  assert.equal(calls[0].logStreamName, "attempt-old");
  assert.equal(calls[0].nextToken, "old-token");
});

test("marks the archive complete after the oldest stream token stabilizes", async () => {
  mockJob(job());
  logs.send = async () => ({ events: [], nextBackwardToken: "old-token" });

  const page = await getDirectCloudWatchLogsPage(
    "job-1",
    cursor({
      version: 1,
      jobId: "job-1",
      streamName: "attempt-old",
      nextBackwardToken: "old-token",
    }),
    10,
  );

  assert.equal(page.isDone, true);
  assert.equal(page.backfillComplete, true);
  assert.equal(page.continueCursor, null);
});

test("handles jobs without streams and malformed cursors", async () => {
  mockJob(job({ current: null, attempts: [] }));
  let logCalls = 0;
  logs.send = async () => {
    logCalls += 1;
    return {};
  };
  const empty = await getDirectCloudWatchLogsPage("job-1", null, 10);
  assert.equal(empty.isDone, true);
  assert.equal(empty.logStreamName, null);
  assert.equal(logCalls, 0);

  mockJob(job({ current: "only", attempts: [] }));
  logs.send = async (command) => {
    assert.equal(command.input.nextToken, undefined);
    return {
      events: [{ timestamp: 1, ingestionTime: 2, message: "first" }],
      nextBackwardToken: null,
    };
  };
  const recovered = await getDirectCloudWatchLogsPage(
    "job-1",
    "cloudwatch:not-json",
    10,
  );
  assert.equal(recovered.events[0].message, "first");
  assert.equal(recovered.isDone, true);
});
