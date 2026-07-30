const RAW_INPUT_PREFIX = 'diana/inbox/';

const INPUT_OVERRIDES = {
  '2026-07-30-h-and-e-slides': {
    title: 'H&E whole-slide images',
    eyebrow: 'H&E input',
    description: 'Download two public H&E whole-slide images in SVS (BigTIFF) format, with a manifest and SHA-256 checksums.',
  },
};

const DISPLAY_TOKENS = new Map([
  ['h', 'H'],
  ['e', 'E'],
  ['he', 'H&E'],
  ['h&e', 'H&E'],
  ['dna', 'DNA'],
  ['rna', 'RNA'],
  ['wgs', 'WGS'],
  ['wes', 'WES'],
  ['fastq', 'FASTQ'],
  ['bam', 'BAM'],
  ['svs', 'SVS'],
  ['hrd', 'HRD'],
]);

export function parseFocusedInputPath(pathname) {
  const match = pathname.match(/^\/inputs\/([^/]+)\/?$/);
  if (!match) return null;

  let slug;
  try {
    slug = decodeURIComponent(match[1]);
  } catch {
    return null;
  }

  return /^[a-z0-9][a-z0-9._-]*$/i.test(slug) ? slug : null;
}

export function humanizeInputSlug(slug) {
  const withoutDate = slug.replace(/^\d{4}-\d{2}-\d{2}-/, '');
  const words = withoutDate.split(/[-_]+/).filter(Boolean);
  const displayWords = [];

  for (let index = 0; index < words.length; index += 1) {
    const word = words[index].toLowerCase();
    if (word === 'h' && words[index + 1]?.toLowerCase() === 'and' && words[index + 2]?.toLowerCase() === 'e') {
      displayWords.push('H&E');
      index += 2;
      continue;
    }

    displayWords.push(DISPLAY_TOKENS.get(word) ?? `${word.charAt(0).toUpperCase()}${word.slice(1)}`);
  }

  return displayWords.join(' ') || slug;
}

export function inputPageConfig(slug) {
  return INPUT_OVERRIDES[slug] ?? {
    title: `${humanizeInputSlug(slug)} input`,
    eyebrow: 'Public input',
    description: 'Download this public Diana input import, including its manifest and checksum files when supplied.',
  };
}

export function focusedInputPrefix(slug) {
  return `${RAW_INPUT_PREFIX}${slug}/`;
}

export function focusedInputPathFor(item) {
  if (item?.type !== 'directory' || item?.source?.id !== 'raw-inputs') return null;
  if (!item.key?.startsWith(RAW_INPUT_PREFIX)) return null;

  const relativeKey = item.key.slice(RAW_INPUT_PREFIX.length);
  if (!/^[^/]+\/$/.test(relativeKey)) return null;
  return `/inputs/${encodeURIComponent(relativeKey.slice(0, -1))}`;
}

export function inputDownloadCommand(source) {
  return `aws s3 cp '${source.s3Uri}' './${source.downloadDirectory}/' --recursive --no-sign-request`;
}
