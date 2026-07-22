import {
  CostExplorerClient,
  GetCostAndUsageCommand,
  type ResultByTime,
} from "@aws-sdk/client-cost-explorer";
import { awsClientConfig } from "./aws.ts";
import {
  type CostCategoryKey,
  type DailyServiceCost,
  type WeeklyCostPayload,
} from "./cost-types.ts";

export type { DailyCost, WeeklyCostPayload } from "./cost-types.ts";

const DAY_MS = 24 * 60 * 60 * 1_000;

export const costExplorer = new CostExplorerClient(awsClientConfig());

function formatUtcDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

export function getCompletedDayRange(now = new Date()) {
  const endDate = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
  const startDate = new Date(endDate.getTime() - 7 * DAY_MS);
  return { start: formatUtcDate(startDate), end: formatUtcDate(endDate) };
}

function amount(value?: string) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function serviceLabel(name: string) {
  const labels: Record<string, string> = {
    "Amazon Simple Storage Service": "S3",
    "Amazon Elastic Compute Cloud - Compute": "EC2 compute",
    "EC2 - Other": "EC2 other",
    "AWS Key Management Service": "KMS",
    "Amazon Virtual Private Cloud": "VPC",
    "AWS Cost Explorer": "Cost Explorer",
    "Amazon EC2 Container Registry (ECR)": "ECR",
    "AWS Lambda": "Lambda",
    "Amazon DynamoDB": "DynamoDB",
    "Amazon Simple Notification Service": "SNS",
    AmazonCloudWatch: "CloudWatch",
  };
  return labels[name] || name.replace(/^Amazon /, "").replace(/^AWS /, "");
}

function categoryForService(name: string): CostCategoryKey {
  if (name === "Amazon Simple Storage Service") return "s3";
  if (name === "Amazon Elastic Compute Cloud - Compute") return "ec2Compute";
  if (name === "EC2 - Other") return "ec2Other";
  if (name === "AWS Cost Explorer") return "costExplorer";
  if (
    name === "AWS Key Management Service" ||
    name === "Amazon Virtual Private Cloud"
  ) {
    return "networkSecurity";
  }
  return "other";
}

function emptyCategories(): Record<CostCategoryKey, number> {
  return {
    s3: 0,
    ec2Compute: 0,
    ec2Other: 0,
    costExplorer: 0,
    networkSecurity: 0,
    other: 0,
  };
}

export function buildWeeklyCostPayload(
  results: ResultByTime[],
  range: { start: string; end: string },
  generatedAt = new Date().toISOString(),
): WeeklyCostPayload {
  const days = results.map((result) => {
    const categories = emptyCategories();
    const services: DailyServiceCost[] = (result.Groups || [])
      .map((group) => {
        const name = group.Keys?.[0] || "Other";
        const serviceAmount = amount(group.Metrics?.UnblendedCost?.Amount);
        categories[categoryForService(name)] += serviceAmount;
        return { name, label: serviceLabel(name), amount: serviceAmount };
      })
      .filter((service) => service.amount > 0)
      .sort((left, right) => right.amount - left.amount);
    const total = services.reduce((sum, service) => sum + service.amount, 0);
    return {
      date: result.TimePeriod?.Start || range.start,
      total,
      estimated: Boolean(result.Estimated),
      categories,
      services,
    };
  });
  const total = days.reduce((sum, day) => sum + day.total, 0);
  const peakDay = days.reduce<WeeklyCostPayload["peakDay"]>(
    (peak, day) => (!peak || day.total > peak.total ? day : peak),
    null,
  );
  return {
    generatedAt,
    start: range.start,
    end: range.end,
    currency: "USD",
    estimated: days.some((day) => day.estimated),
    total,
    dailyAverage: days.length ? total / days.length : 0,
    peakDay: peakDay ? { date: peakDay.date, total: peakDay.total } : null,
    days,
  };
}

export async function getWeeklyCosts(now = new Date()) {
  const range = getCompletedDayRange(now);
  const response = await costExplorer.send(
    new GetCostAndUsageCommand({
      TimePeriod: { Start: range.start, End: range.end },
      Granularity: "DAILY",
      Metrics: ["UnblendedCost"],
      GroupBy: [{ Type: "DIMENSION", Key: "SERVICE" }],
    }),
  );
  return buildWeeklyCostPayload(response.ResultsByTime || [], range);
}
