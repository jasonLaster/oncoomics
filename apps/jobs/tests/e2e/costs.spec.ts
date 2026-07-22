import { expect, test } from "@playwright/test";

const categories = {
  s3: 2,
  ec2Compute: 3,
  ec2Other: 1,
  costExplorer: 0,
  networkSecurity: 0.5,
  other: 0.25,
};

function payload(total: number, generatedAt: string) {
  return {
    generatedAt,
    start: "2026-07-15",
    end: "2026-07-22",
    currency: "USD",
    estimated: true,
    total,
    dailyAverage: total / 7,
    peakDay: { date: "2026-07-16", total: 20 },
    days: Array.from({ length: 7 }, (_, index) => ({
      date: `2026-07-${String(15 + index).padStart(2, "0")}`,
      total: index === 1 ? 20 : 6.75,
      estimated: true,
      categories,
      services: [
        { name: "Amazon Elastic Compute Cloud - Compute", label: "EC2 compute", amount: 3 },
        { name: "Amazon Simple Storage Service", label: "S3", amount: 2 },
        { name: "EC2 - Other", label: "EC2 other", amount: 1 },
        { name: "AWS Key Management Service", label: "KMS", amount: 0.5 },
        { name: "AWS Lambda", label: "Lambda", amount: 0.25 },
      ],
    })),
  };
}

test("shows a responsive daily breakdown and refreshes live cost data", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/costs", async (route) => {
    requests += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        requests === 1
          ? payload(60.5, "2026-07-22T18:00:00.000Z")
          : payload(61.25, "2026-07-22T18:05:00.000Z"),
      ),
    });
  });

  await page.goto("/costs");
  await expect(page.getByRole("heading", { name: "Seven-day cost breakdown" })).toBeVisible();
  await page.getByRole("button", { name: /Refresh costs|Try again/ }).click();
  await expect(page.getByText("$60.50", { exact: true })).toBeVisible();
  await expect(page.getByTestId("daily-cost-chart").locator("article")).toHaveCount(7);
  await expect(page.getByText("EC2 compute", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Refresh costs" }).click();
  await expect(page.getByText("$61.25", { exact: true })).toBeVisible();
  expect(requests).toBe(2);
});
