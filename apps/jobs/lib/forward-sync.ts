export type ForwardPage = {
  nextForwardToken: string | null;
};

export type ForwardSyncOptions<Page extends ForwardPage> = {
  initialCursor?: string | null;
  maxPages: number;
  timeBudgetMs: number;
  loadPage: (cursor?: string) => Promise<Page>;
  persistPage: (input: {
    page: Page;
    previousToken: string | null;
    caughtUp: boolean;
  }) => Promise<boolean>;
  now?: () => number;
};

export type ForwardSyncResult = {
  pagesProcessed: number;
  caughtUp: boolean;
  hasMore: boolean;
  cursorConflict: boolean;
  nextForwardToken: string | null;
};

/**
 * Advances a durable CloudWatch forward cursor for one bounded refresh slice.
 * There is deliberately no lifetime page limit: callers persist every page and
 * invoke another slice from the returned cursor until the token stabilizes.
 */
export async function syncForwardPages<Page extends ForwardPage>({
  initialCursor,
  maxPages,
  timeBudgetMs,
  loadPage,
  persistPage,
  now = Date.now,
}: ForwardSyncOptions<Page>): Promise<ForwardSyncResult> {
  if (!Number.isInteger(maxPages) || maxPages < 1) {
    throw new Error("maxPages must be a positive integer");
  }
  if (!Number.isFinite(timeBudgetMs) || timeBudgetMs < 0) {
    throw new Error("timeBudgetMs must be non-negative");
  }

  const startedAt = now();
  let nextToken = initialCursor || undefined;
  let pagesProcessed = 0;

  while (
    pagesProcessed < maxPages &&
    (pagesProcessed === 0 || now() - startedAt < timeBudgetMs)
  ) {
    const previousToken = nextToken || null;
    const page = await loadPage(nextToken);
    const caughtUp = page.nextForwardToken === previousToken;
    const cursorAdvanced = await persistPage({
      page,
      previousToken,
      caughtUp,
    });

    if (!cursorAdvanced) {
      return {
        pagesProcessed,
        caughtUp: false,
        hasMore: true,
        cursorConflict: true,
        nextForwardToken: previousToken,
      };
    }

    pagesProcessed += 1;
    nextToken = page.nextForwardToken || undefined;
    if (caughtUp) {
      return {
        pagesProcessed,
        caughtUp: true,
        hasMore: false,
        cursorConflict: false,
        nextForwardToken: page.nextForwardToken,
      };
    }
  }

  return {
    pagesProcessed,
    caughtUp: false,
    hasMore: true,
    cursorConflict: false,
    nextForwardToken: nextToken || null,
  };
}
