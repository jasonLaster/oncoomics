import { expect, test } from "@playwright/test";

import { installApiMocks, logPages } from "./fixtures";

test.describe("viewer v2 desktop workspace", () => {
  test.skip(({ isMobile }) => Boolean(isMobile), "Desktop rail behavior is covered with a desktop viewport.");

  test.beforeEach(async ({ page }) => {
    await installApiMocks(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Diana HRD evidence" })).toBeVisible();
  });

  test("collapses both rails and restores their state after reload", async ({ page }) => {
    const leftRail = page.getByTestId("left-rail");
    const rightRail = page.getByTestId("right-rail");
    const leftToggle = page.getByTestId("toggle-left-rail");
    const rightToggle = page.getByTestId("toggle-right-rail");

    await expect(leftRail).toHaveAttribute("data-collapsed", "false");
    await expect(rightRail).toHaveAttribute("data-collapsed", "false");
    await expect(leftToggle).toHaveAttribute("aria-expanded", "true");
    await expect(rightToggle).toHaveAttribute("aria-expanded", "true");

    await leftToggle.click();
    await rightToggle.click();
    await expect(leftRail).toHaveAttribute("data-collapsed", "true");
    await expect(rightRail).toHaveAttribute("data-collapsed", "true");

    await page.reload();
    await expect(leftRail).toHaveAttribute("data-collapsed", "true");
    await expect(rightRail).toHaveAttribute("data-collapsed", "true");
    await expect(leftToggle).toHaveAttribute("aria-expanded", "false");
    await expect(rightToggle).toHaveAttribute("aria-expanded", "false");
  });

  test("selects a job and presents structured overview progress", async ({ page }) => {
    const selectedJob = page.getByRole("button", { name: /Diana HRD evidence/ });
    const failedJob = page.getByRole("button", { name: /Filter failure sentinel/ });
    const archivedJob = page.getByRole("button", { name: /Archived validation/ });

    await expect(page.getByRole("heading", { name: /Running now/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /Last 24 hours/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: /All jobs/ })).toBeVisible();
    await expect(selectedJob).toHaveAttribute("aria-pressed", "true");
    const metrics = page.getByLabel("Run metrics");
    await expect(metrics.getByText("37.5%", { exact: true })).toBeVisible();
    await expect(metrics.getByText("42.1 Mb/min", { exact: true })).toBeVisible();

    const progress = page.getByTestId("workflow-progress");
    await expect(progress.getByText("Intake integrity", { exact: true })).toBeVisible();
    await expect(progress.getByText("Variant evidence", { exact: true })).toBeVisible();
    await expect(progress.locator('[data-state="complete"]')).toHaveCount(2);
    await expect(progress.locator('[data-state="active"]')).toHaveCount(1);
    await expect(progress.locator('[data-state="queued"]')).toHaveCount(3);

    await failedJob.click();
    await expect(failedJob).toHaveAttribute("aria-pressed", "true");
    await expect(selectedJob).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByRole("heading", { name: "Filter failure sentinel" })).toBeVisible();
    await expect(page.getByText(/retry budget was exhausted/i)).toBeVisible();

    await archivedJob.click();
    await expect(archivedJob).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("heading", { name: "Archived validation" })).toBeVisible();
  });
});

test.describe("viewer v2 live refresh", () => {
  test.skip(({ isMobile }) => Boolean(isMobile), "The polling contract is viewport-independent.");

  test("refreshes active jobs and their logs on the live cadence", async ({ page }) => {
    await page.clock.install();
    const { jobRequests, statusRequests, logRequests } = await installApiMocks(page);
    await page.goto("/");
    await page.clock.runFor(1);
    await expect.poll(() => jobRequests.length).toBeGreaterThan(0);

    await expect.poll(() => statusRequests.length).toBeGreaterThan(0);
    const statusBefore = statusRequests.length;
    await page.clock.fastForward(10_100);
    await expect.poll(() => statusRequests.length).toBeGreaterThan(statusBefore);

    const jobsBefore = jobRequests.length;
    await page.clock.fastForward(20_100);
    await expect.poll(() => jobRequests.length).toBeGreaterThan(jobsBefore);

    await page.getByRole("tab", { name: "Logs" }).click();
    await page.clock.runFor(1);
    await expect.poll(
      () => logRequests.filter((url) => !url.includes("cursor=")).length,
    ).toBeGreaterThan(0);

    const freshLogsBefore = logRequests.filter(
      (url) => !url.includes("cursor="),
    ).length;
    await page.clock.fastForward(10_100);

    await expect.poll(
      () => logRequests.filter((url) => !url.includes("cursor=")).length,
    ).toBeGreaterThan(freshLogsBefore);
  });

  test("pauses polling offline and catches up after reconnect", async ({
    context,
    page,
  }) => {
    await page.clock.install();
    const { jobRequests, statusRequests } = await installApiMocks(page);
    await page.goto("/");
    await page.clock.runFor(1);
    await expect.poll(() => statusRequests.length).toBeGreaterThan(0);
    await expect(page.getByText("Live", { exact: true })).toBeVisible();

    await context.setOffline(true);
    await expect(page.getByText("Paused", { exact: true })).toBeVisible();
    await expect(page.getByText("Sync paused", { exact: true })).toBeVisible();
    const jobsBeforePause = jobRequests.length;
    const statusBeforePause = statusRequests.length;
    await page.clock.fastForward(30_100);
    expect(jobRequests).toHaveLength(jobsBeforePause);
    expect(statusRequests).toHaveLength(statusBeforePause);

    await context.setOffline(false);
    await page.clock.runFor(1);
    await expect.poll(() => jobRequests.length).toBeGreaterThan(jobsBeforePause);
    await expect.poll(() => statusRequests.length).toBeGreaterThan(statusBeforePause);
    await expect(page.getByText("Live", { exact: true })).toBeVisible();
  });

  test("never regresses cumulative progress from a partial status window", async ({
    page,
  }) => {
    const { statusRequests } = await installApiMocks(page, {
      statusProgressPercent: 12.5,
    });
    await page.goto("/");
    await expect.poll(() => statusRequests.length).toBeGreaterThan(0);
    await expect(
      page.getByLabel("Run metrics").getByText("37.5%", { exact: true }),
    ).toBeVisible();
  });
});

test.describe("viewer v2 structured logs", () => {
  test("formats events and combines search, level, and category filters", async ({ page, isMobile }) => {
    await installApiMocks(page);
    await page.goto("/");
    await page.getByRole("tab", { name: "Logs" }).click();
    await expect(page.getByTestId("log-feed")).toBeVisible();

    const events = page.getByTestId("log-event");
    const progressEvent = events.filter({ hasText: "chr17 · 67.5%" });

    await expect(progressEvent).toHaveAttribute("data-level", "info");
    await expect(progressEvent).toHaveAttribute("data-category", "progress");
    const artifactEvent = events.filter({ hasText: "Encrypted reviewer packet uploaded" });
    await expect(artifactEvent).toHaveCount(1);
    await expect(artifactEvent).toHaveAttribute("data-category", "artifact");

    const rowHeight = await progressEvent.evaluate((node) => node.getBoundingClientRect().height);
    const intrinsicSize = await progressEvent.evaluate(
      (node) => getComputedStyle(node).containIntrinsicSize,
    );
    if (isMobile) {
      expect(rowHeight).toBeGreaterThanOrEqual(44);
      expect(rowHeight).toBeLessThanOrEqual(46);
      expect(intrinsicSize).toContain("44px");
      for (const control of [
        page.getByTestId("log-level-filter"),
        page.getByTestId("log-category-filter"),
      ]) {
        const box = await control.boundingBox();
        expect(box?.height).toBeGreaterThanOrEqual(44);
      }
    } else {
      expect(rowHeight).toBeGreaterThanOrEqual(28);
      expect(rowHeight).toBeLessThanOrEqual(34);
      expect(intrinsicSize).toContain("24px");
    }

    await page.getByTestId("log-search").fill("contamination threshold");
    await expect(events).toHaveCount(1);
    await expect(events.first()).toHaveAttribute("data-level", "error");

    await page.getByTestId("log-search").fill("");
    await page.getByTestId("log-level-filter").selectOption("warn");
    await expect(events).toHaveCount(1);
    await expect(events.first()).toContainText("AWS Batch container retry");

    await page.getByTestId("log-level-filter").selectOption("all");
    await page.getByTestId("log-category-filter").selectOption("progress");
    await expect(events).toHaveCount(9);
    await expect(events.first()).toContainText("GATK progress");
    await expect(events.last()).toContainText("Shard heartbeat");
  });

  test("loads the next log page automatically when the sentinel enters view", async ({ page }) => {
    const { logRequests } = await installApiMocks(page);
    await page.goto("/");
    await page.getByRole("tab", { name: "Logs" }).click();
    await expect(page.getByTestId("log-feed")).toBeVisible();

    const sentinel = page.getByTestId("log-pagination-sentinel");
    await expect(sentinel).toBeAttached();
    await sentinel.scrollIntoViewIfNeeded();

    await expect.poll(() => logRequests.some((url) => url.includes("cursor=older-page"))).toBe(true);
    await expect(
      page.getByTestId("log-event").filter({ hasText: "Intake integrity checksum verified" }),
    ).toHaveCount(1);
    await expect(page.getByTestId("log-event")).toHaveCount(
      logPages.newest.events.length + logPages.older.events.length,
    );
  });

  test("inspects an event without losing the feed position", async ({ page, isMobile }) => {
    await installApiMocks(page);
    await page.goto("/");
    await page.getByRole("tab", { name: "Logs" }).click();

    const feed = page.getByTestId("log-feed");
    const event = page
      .getByTestId("log-event")
      .filter({ hasText: "Encrypted reviewer packet uploaded" });
    await event.scrollIntoViewIfNeeded();
    const inspect = event.getByTestId("inspect-log-event");

    await inspect.click();
    await expect(event).toHaveAttribute("data-selected", "true");
    await expect(page.getByTestId("right-rail")).toHaveAttribute("data-mode", "event");
    await expect(page.getByTestId("event-inspector-content")).toContainText(
      "Encrypted reviewer packet uploaded",
    );
    await expect(page.getByTestId("event-inspector-content")).toContainText("Raw payload");
    const scrollTop = await feed.evaluate((node) => node.scrollTop);
    if (isMobile) {
      await expect(page.getByRole("dialog")).toBeVisible();
      await expect(page.locator(".main-panel")).toHaveAttribute("inert", "");
    }

    await page.getByRole("button", { name: "Back to run" }).click();
    await expect(page.getByTestId("right-rail")).toHaveAttribute("data-mode", "run");
    await expect(inspect).toBeFocused();
    await expect.poll(() => feed.evaluate((node) => node.scrollTop)).toBe(scrollTop);
    if (isMobile) {
      await expect(page.getByTestId("right-rail")).toHaveAttribute("data-collapsed", "true");
    }
  });
});

test.describe("viewer v2 mobile workspace", () => {
  test.skip(({ isMobile }) => !isMobile, "Mobile drawer behavior is covered with a phone viewport.");

  test("keeps the work surface readable and opens one rail at a time", async ({ page }) => {
    await installApiMocks(page);
    await page.goto("/");

    const leftRail = page.getByTestId("left-rail");
    const rightRail = page.getByTestId("right-rail");
    await expect(leftRail).toHaveAttribute("data-collapsed", "true");
    await expect(rightRail).toHaveAttribute("data-collapsed", "true");
    await expect(page.getByRole("heading", { name: "Diana HRD evidence" })).toBeVisible();

    for (const control of [
      page.getByTestId("toggle-left-rail"),
      page.getByTestId("toggle-right-rail"),
      page.getByRole("tab", { name: "Overview" }),
      page.getByRole("tab", { name: "Logs" }),
    ]) {
      const box = await control.boundingBox();
      expect(box?.width).toBeGreaterThanOrEqual(44);
      expect(box?.height).toBeGreaterThanOrEqual(44);
    }

    await page.getByTestId("toggle-left-rail").click();
    await expect(leftRail).toHaveAttribute("data-collapsed", "false");
    await expect(rightRail).toHaveAttribute("data-collapsed", "true");

    await page.getByRole("button", { name: /Filter failure sentinel/ }).click();
    await expect(leftRail).toHaveAttribute("data-collapsed", "true");
    await expect(page.getByRole("heading", { name: "Filter failure sentinel" })).toBeVisible();

    await page.getByTestId("toggle-right-rail").click();
    await expect(leftRail).toHaveAttribute("data-collapsed", "true");
    await expect(rightRail).toHaveAttribute("data-collapsed", "false");
  });
});
