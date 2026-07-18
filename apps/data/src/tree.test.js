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

test('opens live raw input descendants by default', () => {
  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 7,
    source: { id: 'raw-inputs', expandByDefault: true },
  }), true);
});

test('keeps reviewed result descendants collapsed without search', () => {
  assert.equal(shouldOpenDirectory({
    hasSearchQuery: false,
    isRoot: false,
    depth: 2,
    source: { id: 'results' },
  }), false);
});
