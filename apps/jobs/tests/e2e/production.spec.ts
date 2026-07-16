import { expect, test } from "@playwright/test";

const production = process.env.PLAYWRIGHT_PRODUCTION === "1";

test.describe("production viewer", () => {
  test.skip(!production, "Runs only during an explicit production QA pass.");

  test("serves live jobs, overview, and logs from the production APIs", async ({ page, request }) => {
    const jobsResponse = await request.get("/api/jobs");
    expect(jobsResponse.ok()).toBeTruthy();
    const payload = await jobsResponse.json();
    expect(payload.region).toBeTruthy();
    expect(Array.isArray(payload.jobs)).toBeTruthy();

    await page.goto("/");
    await expect(page).toHaveTitle(/Diana Compute/);
    await expect(page.getByRole("heading", { name: /Run monitor/i })).toBeVisible();

    if (payload.jobs.length === 0) {
      await expect(page.getByText("No job selected")).toBeVisible();
      return;
    }

    const selected =
      payload.jobs.find((job: { status: string }) =>
        ["SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING"].includes(job.status),
      ) || payload.jobs[0];
    await expect(page.getByRole("heading", { name: selected.name })).toBeVisible();
    await expect(page.getByTestId("workflow-progress")).toBeVisible();

    await page.getByRole("tab", { name: "Logs" }).click();
    if (!selected.logStreamName) {
      await expect(page.getByText("Log stream not created yet")).toBeVisible();
      return;
    }

    const logsResponse = await request.get(
      `/api/job-logs?jobId=${encodeURIComponent(selected.id)}&limit=10`,
    );
    expect(logsResponse.ok()).toBeTruthy();
    const logs = await logsResponse.json();
    expect(Array.isArray(logs.events)).toBeTruthy();
    await expect(page.getByTestId("log-feed")).toBeVisible();
  });
});
