import assert from 'node:assert/strict';
import { test } from 'node:test';

import { shouldOpenDirectory } from './tree.js';

test('opens the root and top-level source directories', () => {
  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: true,
    depth: 0,
    source: null,
  }), true);

  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 1,
    source: { id: 'results' },
  }), true);
});

test('opens only the selected raw input path by default', () => {
  const source = {
    id: 'raw-inputs',
    defaultOpenDirectoryKeys: [
      'diana/inbox/2026-07-14-echo-personalis/',
      'diana/inbox/2026-07-14-echo-personalis/data/',
    ],
  };

  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 2,
    source,
    key: 'diana/inbox/2026-07-14-echo-personalis/',
  }), true);

  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 3,
    source,
    key: 'diana/inbox/2026-07-14-echo-personalis/data/',
  }), true);

  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 4,
    source,
    key: 'diana/inbox/2026-07-14-echo-personalis/data/wgs/',
  }), false);

  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 2,
    source,
    key: 'diana/inbox/2026-07-30-h-and-e-slides/',
  }), false);
});

test('keeps reviewed result descendants collapsed without search', () => {
  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 2,
    source: { id: 'results' },
  }), false);
});
