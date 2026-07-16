import assert from "node:assert/strict";
import test from "node:test";

import { syncForwardPages } from "../lib/forward-sync.ts";

test("repeated bounded refreshes finish a backlog larger than the old page cap", async () => {
  const advancingPages = 2_505;
  const maxPagesPerRefresh = 17;
  let durableCursor = null;
  let refreshes = 0;
  let totalPages = 0;
  let caughtUp = false;

  while (!caughtUp) {
    const result = await syncForwardPages({
      initialCursor: durableCursor,
      maxPages: maxPagesPerRefresh,
      timeBudgetMs: 1_000_000,
      loadPage: async (cursor) => {
        const current = cursor ? Number(cursor) : 0;
        return {
          nextForwardToken:
            current < advancingPages ? String(current + 1) : String(current),
        };
      },
      persistPage: async ({ page, previousToken }) => {
        assert.equal(previousToken, durableCursor);
        durableCursor = page.nextForwardToken;
        return true;
      },
    });

    refreshes += 1;
    totalPages += result.pagesProcessed;
    caughtUp = result.caughtUp;
    assert.ok(result.pagesProcessed <= maxPagesPerRefresh);
  }

  assert.ok(refreshes > 1);
  assert.equal(durableCursor, String(advancingPages));
  assert.equal(totalPages, advancingPages + 1);
});

test("a refresh stops at its time budget and resumes from its committed cursor", async () => {
  let durableCursor = null;
  let clock = 0;
  const loadPage = async (cursor) => {
    const current = cursor ? Number(cursor) : 0;
    clock += 6;
    return { nextForwardToken: String(current + 1) };
  };
  const persistPage = async ({ page, previousToken }) => {
    assert.equal(previousToken, durableCursor);
    durableCursor = page.nextForwardToken;
    return true;
  };

  const first = await syncForwardPages({
    initialCursor: durableCursor,
    maxPages: 50,
    timeBudgetMs: 10,
    loadPage,
    persistPage,
    now: () => clock,
  });
  assert.equal(first.pagesProcessed, 2);
  assert.equal(durableCursor, "2");
  assert.equal(first.hasMore, true);

  const second = await syncForwardPages({
    initialCursor: durableCursor,
    maxPages: 1,
    timeBudgetMs: 10,
    loadPage,
    persistPage,
    now: () => clock,
  });
  assert.equal(second.pagesProcessed, 1);
  assert.equal(durableCursor, "3");
});

test("compare-and-set rejection prevents an older worker from regressing a cursor", async () => {
  let durableCursor = "token-10";
  const result = await syncForwardPages({
    initialCursor: durableCursor,
    maxPages: 8,
    timeBudgetMs: 1_000,
    loadPage: async () => ({ nextForwardToken: "token-11" }),
    persistPage: async ({ previousToken }) => {
      assert.equal(previousToken, "token-10");
      durableCursor = "token-12";
      return false;
    },
  });

  assert.equal(result.cursorConflict, true);
  assert.equal(result.pagesProcessed, 0);
  assert.equal(durableCursor, "token-12");
});
