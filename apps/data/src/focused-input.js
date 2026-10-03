const RAW_INPUT_PREFIX = 'diana/inbox/';
const INPUT_SEGMENT_PATTERN = /^[a-z0-9][a-z0-9._-]*$/i;

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
  const match = pathname.match(/^\/inputs\/(.+?)\/?$/);
  if (!match) return null;

  const segments = match[1].split('/').map((segment) => {
    try {
      return decodeURIComponent(segment);
    } catch {
      return null;
    }
  });

  return segments.length && segments.every((segment) => segment && INPUT_SEGMENT_PATTERN.test(segment))
    ? segments.join('/')
    : null;
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

export function inputPageConfig(inputPath) {
  if (INPUT_OVERRIDES[inputPath]) return INPUT_OVERRIDES[inputPath];

  const segments = inputPath.split('/');
  const title = humanizeInputSlug(segments.at(-1));
  return segments.length === 1 ? {
    title: `${title} input`,
    eyebrow: 'Public input',
    description: 'Download this public Diana input import, including its manifest and checksum files when supplied.',
  } : {
    title: `${title} files`,
    eyebrow: 'Public input folder',
    description: 'Download the public files in this Diana input folder, including nested files and integrity metadata when supplied.',
  };
}

export function focusedInputPrefix(inputPath) {
  return `${RAW_INPUT_PREFIX}${inputPath}/`;
}

export function focusedInputPathFor(item) {
  if (item?.type !== 'directory' || item?.source?.id !== 'raw-inputs') return null;
  if (!item.key?.startsWith(RAW_INPUT_PREFIX)) return null;

  const relativeKey = item.key.slice(RAW_INPUT_PREFIX.length).replace(/\/$/, '');
  const segments = relativeKey.split('/');
  if (!relativeKey || segments.some((segment) => !INPUT_SEGMENT_PATTERN.test(segment))) return null;
  return `/inputs/${segments.map(encodeURIComponent).join('/')}`;
}

export function inputDownloadCommand(source) {
  return `aws s3 cp '${source.s3Uri}' './${source.downloadDirectory}/' --recursive --no-sign-request`;
}
