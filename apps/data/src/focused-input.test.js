import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  focusedInputPathFor,
  focusedInputPrefix,
  humanizeInputSlug,
  inputDownloadCommand,
  inputPageConfig,
  parseFocusedInputPath,
} from './focused-input.js';

test('parses one shareable input slug with an optional trailing slash', () => {
  assert.equal(parseFocusedInputPath('/inputs/2026-07-30-h-and-e-slides'), '2026-07-30-h-and-e-slides');
  assert.equal(parseFocusedInputPath('/inputs/2026-07-30-h-and-e-slides/'), '2026-07-30-h-and-e-slides');
  assert.equal(parseFocusedInputPath('/inputs/echo%2Fpersonalis'), null);
  assert.equal(parseFocusedInputPath('/inputs/one/two'), null);
  assert.equal(parseFocusedInputPath('/'), null);
});

test('builds an exact raw-input prefix', () => {
  assert.equal(
    focusedInputPrefix('2026-07-30-h-and-e-slides'),
    'diana/inbox/2026-07-30-h-and-e-slides/',
  );
});

test('humanizes known assay tokens and generic input names', () => {
  assert.equal(humanizeInputSlug('2026-07-30-h-and-e-slides'), 'H&E Slides');
  assert.equal(humanizeInputSlug('2026-07-14-echo-personalis'), 'Echo Personalis');
  assert.equal(humanizeInputSlug('wgs-fastq-delivery'), 'WGS FASTQ Delivery');
});

test('uses a specific H&E introduction and a generic fallback', () => {
  assert.equal(inputPageConfig('2026-07-30-h-and-e-slides').title, 'H&E whole-slide images');
  assert.equal(inputPageConfig('2026-07-14-echo-personalis').title, 'Echo Personalis input');
});

test('offers focused URLs only for top-level raw input directories', () => {
  const source = { id: 'raw-inputs' };
  assert.equal(focusedInputPathFor({
    type: 'directory',
    source,
    key: 'diana/inbox/2026-07-30-h-and-e-slides/',
  }), '/inputs/2026-07-30-h-and-e-slides');
  assert.equal(focusedInputPathFor({
    type: 'directory',
    source,
    key: 'diana/inbox/2026-07-30-h-and-e-slides/data/',
  }), null);
  assert.equal(focusedInputPathFor({
    type: 'file',
    source,
    key: 'diana/inbox/2026-07-30-h-and-e-slides/manifest.csv',
  }), null);
});

test('builds an anonymous recursive download command', () => {
  assert.equal(inputDownloadCommand({
    s3Uri: 's3://example/diana/inbox/import/',
    downloadDirectory: 'import',
  }), "aws s3 cp 's3://example/diana/inbox/import/' './import/' --recursive --no-sign-request");
});
