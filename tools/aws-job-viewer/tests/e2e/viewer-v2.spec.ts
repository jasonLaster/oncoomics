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
    if (isMobile) {
      expect(rowHeight).toBeGreaterThanOrEqual(44);
      expect(rowHeight).toBeLessThanOrEqual(46);
    } else {
      expect(rowHeight).toBeGreaterThanOrEqual(28);
      expect(rowHeight).toBeLessThanOrEqual(34);
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

    await page.getByTestId("toggle-left-rail").click();
    await expect(leftRail).toHaveAttribute("data-collapsed", "false");
    await expect(rightRail).toHaveAttribute("data-collapsed", "true");

    await page.getByTestId("toggle-right-rail").click();
    await expect(leftRail).toHaveAttribute("data-collapsed", "true");
    await expect(rightRail).toHaveAttribute("data-collapsed", "false");
  });
});
