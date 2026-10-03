import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isArchivedStorageClass, normalizeIndexedObject } from './inventory.js';

test('recognizes Glacier storage classes as archived', () => {
  assert.equal(isArchivedStorageClass('GLACIER'), true);
  assert.equal(isArchivedStorageClass('DEEP_ARCHIVE'), true);
  assert.equal(isArchivedStorageClass('STANDARD'), false);
});

test('normalizes Glacier index entries relative to the public archive prefix', () => {
  const object = normalizeIndexedObject({
    key: 'cache/phase3_wgs/fastq/example.fastq.gz',
    size: 1234,
    last_modified: '2026-07-30T19:35:10+00:00',
    storage_class: 'GLACIER',
  }, {
    prefix: 'cache/phase3_wgs/',
    storageClass: 'GLACIER',
    archived: true,
  });

  assert.equal(object.relativeKey, 'fastq/example.fastq.gz');
  assert.equal(object.storageClass, 'GLACIER');
  assert.equal(object.archived, true);
});

test('rejects malformed index entries', () => {
  assert.equal(normalizeIndexedObject({
    key: '',
    size: 1,
    last_modified: '2026-07-30T19:35:10+00:00',
  }, {}), null);

  assert.equal(normalizeIndexedObject({
    key: 'example.txt',
    size: 'not-a-number',
    last_modified: '2026-07-30T19:35:10+00:00',
  }, {}), null);
});
