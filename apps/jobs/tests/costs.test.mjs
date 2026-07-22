import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  buildWeeklyCostPayload,
  costExplorer,
  getCompletedDayRange,
  getWeeklyCosts,
} from "../lib/costs.ts";

const originalSend = costExplorer.send;

afterEach(() => {
  costExplorer.send = originalSend;
});

function group(name, value) {
  return {
    Keys: [name],
    Metrics: { UnblendedCost: { Amount: String(value), Unit: "USD" } },
  };
}

test("uses the seven completed UTC billing days", () => {
  assert.deepEqual(getCompletedDayRange(new Date("2026-07-22T18:45:00Z")), {
    start: "2026-07-15",
    end: "2026-07-22",
  });
});

test("builds daily service and chart-category totals without inventing values", () => {
  const payload = buildWeeklyCostPayload(
    [
      {
        TimePeriod: { Start: "2026-07-15", End: "2026-07-16" },
        Estimated: true,
        Groups: [
          group("Amazon Simple Storage Service", 2.5),
          group("Amazon Elastic Compute Cloud - Compute", 3),
          group("EC2 - Other", 1.25),
          group("AWS Key Management Service", 0.5),
          group("Amazon Virtual Private Cloud", 0.25),
          group("AWS Lambda", 0.01),
        ],
      },
      {
        TimePeriod: { Start: "2026-07-16", End: "2026-07-17" },
        Estimated: false,
        Groups: [group("AWS Cost Explorer", 0.02)],
      },
    ],
    { start: "2026-07-15", end: "2026-07-22" },
    "2026-07-22T19:00:00.000Z",
  );

  assert.ok(Math.abs(payload.total - 7.53) < 1e-10);
  assert.ok(Math.abs(payload.dailyAverage - 3.765) < 1e-10);
  assert.deepEqual(payload.peakDay, { date: "2026-07-15", total: 7.51 });
  assert.equal(payload.estimated, true);
  assert.deepEqual(payload.days[0].categories, {
    s3: 2.5,
    ec2Compute: 3,
    ec2Other: 1.25,
    costExplorer: 0,
    networkSecurity: 0.75,
    other: 0.01,
  });
  assert.deepEqual(
    payload.days[0].services.map((service) => service.label),
    ["EC2 compute", "S3", "EC2 other", "KMS", "VPC", "Lambda"],
  );
});

test("requests unblended daily costs grouped by AWS service", async () => {
  let input;
  costExplorer.send = async (command) => {
    input = command.input;
    return { ResultsByTime: [] };
  };

  const payload = await getWeeklyCosts(new Date("2026-07-22T18:45:00Z"));

  assert.deepEqual(input.TimePeriod, { Start: "2026-07-15", End: "2026-07-22" });
  assert.equal(input.Granularity, "DAILY");
  assert.deepEqual(input.Metrics, ["UnblendedCost"]);
  assert.deepEqual(input.GroupBy, [{ Type: "DIMENSION", Key: "SERVICE" }]);
  assert.equal(payload.days.length, 0);
});
