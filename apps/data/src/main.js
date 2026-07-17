import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import markdown from 'highlight.js/lib/languages/markdown';
import 'highlight.js/styles/github-dark.css';
import './styles.css';

hljs.registerLanguage('bash', bash);
hljs.registerLanguage('markdown', markdown);

const PUBLIC_INDEX_URL = 'https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json';

const PUBLIC_SOURCES = [
  {
    id: 'results',
    name: 'Reviewed analysis results',
    treeName: 'analysis/results',
    bucket: 'diana-omics-results-172630973301-us-east-1',
    region: 'us-east-1',
    indexUrl: PUBLIC_INDEX_URL,
    description: 'Reviewed validation outputs and alias-only Diana analysis reports.',
    statusLabel: 'Indexed',
    loadingLabel: 'Loading reviewed index…',
  },
  {
    id: 'raw-inputs',
    name: 'Diana input',
    treeName: 'diana/input',
    bucket: 'diana-omics-raw-inputs-172630973301-us-east-1',
    region: 'us-east-1',
    prefix: 'diana/inbox/',
    description: 'Public FASTQ, BAM, manifest, and checksum objects delivered to the Diana inbox.',
    statusLabel: 'Live',
    loadingLabel: 'Loading live inventory…',
    downloadDirectory: 'diana-input',
  },
].map((source) => ({
  ...source,
  prefix: source.prefix ?? '',
  origin: `https://${source.bucket}.s3.${source.region}.amazonaws.com`,
  s3Uri: `s3://${source.bucket}/${source.prefix ?? ''}`,
}));

const markdownInstructions = `## Download the reviewed analysis index

\`\`\`bash
curl --fail --location \\
  '${PUBLIC_INDEX_URL}' \\
  --output diana-public-objects.json
\`\`\`

## Download a reviewed analysis result

Copy a direct file URL from the browser, then run:

\`\`\`bash
curl --fail --location --remote-name 'DIRECT_FILE_URL'
\`\`\`

## Download the Diana input files

\`\`\`bash
aws s3 cp \\
  s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/ \\
  ./diana-input/ \\
  --recursive \\
  --no-sign-request
\`\`\``;

const highlightMarkdownWithBash = (source) => {
  const fencePattern = /```bash\n([\s\S]*?)\n```/g;
  let highlighted = '';
  let previousIndex = 0;

  for (const match of source.matchAll(fencePattern)) {
    const matchIndex = match.index ?? 0;
    highlighted += hljs.highlight(source.slice(previousIndex, matchIndex), { language: 'markdown' }).value;
    highlighted += '<span class="hljs-code"><span class="hljs-meta">```bash</span>\n';
    highlighted += hljs.highlight(match[1], { language: 'bash' }).value;
    highlighted += '\n<span class="hljs-meta">```</span></span>';
    previousIndex = matchIndex + match[0].length;
  }

  highlighted += hljs.highlight(source.slice(previousIndex), { language: 'markdown' }).value;
  return highlighted;
};

document.querySelector('#app').innerHTML = `
  <header class="site-header">
    <a class="brand" href="#top" aria-label="Diana Omics home">
      <span class="brand-mark" aria-hidden="true">D<span>/</span></span>
      <span>Diana Omics</span>
    </a>
    <span class="access-badge"><i></i> Public S3 data</span>
  </header>

  <main class="shell" id="top">
    <section class="intro">
      <div>
        <p class="eyebrow">Open genomic dataset</p>
        <h1>Diana Omics public data</h1>
        <p class="intro-copy">Browse reviewed current analysis outputs and raw Diana inbox deliveries. No AWS account or credentials are required for these public files.</p>
      </div>
      <dl class="dataset-stats" aria-label="Dataset summary">
        <div><dt>Files</dt><dd id="object-count">—</dd></div>
        <div><dt>Size</dt><dd id="total-size">—</dd></div>
        <div><dt>Updated</dt><dd id="last-updated">—</dd></div>
      </dl>
    </section>

    <section class="source-section" aria-labelledby="sources-heading">
      <div class="source-heading">
        <p class="eyebrow">Public S3 sources</p>
        <h2 id="sources-heading">Live data surfaces</h2>
      </div>
      <div class="source-grid">
        ${PUBLIC_SOURCES.map((source) => `
          <article class="source-card" id="source-${source.id}">
            <div class="source-card-heading">
              <h3>${source.name}</h3>
              <span class="source-state"><i></i><span>Loading</span></span>
            </div>
            <p>${source.description}</p>
            <code>${source.indexUrl ?? source.s3Uri}</code>
            <div class="source-stats" aria-live="polite">
              <strong>—</strong>
              <span>${source.loadingLabel}</span>
            </div>
          </article>`).join('')}
      </div>
    </section>

    <section class="download-section" aria-labelledby="download-heading">
      <div class="download-copy">
        <p class="eyebrow">Download guide</p>
        <h2 id="download-heading">Get the data</h2>
        <p>Download individual public objects directly, use the reviewed index for report outputs, or copy the live Diana inbox with anonymous S3 reads.</p>
        <a href="https://github.com/jasonLaster/oncoomics/blob/main/docs/operations/diana-public-data-download.md">Open the full download guide <span aria-hidden="true">→</span></a>
      </div>
      <div class="code-card">
        <div class="code-bar">
          <span>DOWNLOAD.md</span>
          <button id="copy-instructions" type="button">Copy Markdown</button>
        </div>
        <pre><code id="markdown-code" class="language-markdown"></code></pre>
      </div>
    </section>

    <section class="tree-section" aria-labelledby="files-heading">
      <div class="section-heading">
        <div>
          <h2 id="files-heading">Public files</h2>
          <p id="inventory-status">Loading public inventories…</p>
        </div>
        <div class="tree-actions">
          <button id="expand-all" type="button">Expand all</button>
          <button id="collapse-all" type="button">Collapse all</button>
        </div>
      </div>

      <div class="tree-panel">
        <div class="tree-toolbar">
          <div class="path-label"><span>s3</span><code>${PUBLIC_SOURCES.length} public sources</code></div>
          <label class="search-field">
            <span aria-hidden="true">⌕</span>
            <span class="sr-only">Search files, folders, and buckets</span>
            <input id="tree-search" type="search" placeholder="Search files, folders, and buckets" autocomplete="off" />
          </label>
        </div>
        <div class="tree-column-headings" aria-hidden="true">
          <span></span><span>Latest file</span><span>Size</span>
        </div>
        <div class="tree" id="file-tree" aria-live="polite">
          ${Array.from({ length: 8 }, (_, index) => `<div class="tree-skeleton" style="--skeleton-depth: ${Math.min(index, 4)}"><span></span></div>`).join('')}
        </div>
      </div>
    </section>

  </main>

  <footer>
    <div class="shell footer-inner">
      <span>Diana Omics Open Data</span>
      <span>Reviewed index · Live S3 · Anonymous reads</span>
    </div>
  </footer>
`;

const codeElement = document.querySelector('#markdown-code');
codeElement.innerHTML = highlightMarkdownWithBash(markdownInstructions);
codeElement.classList.add('hljs');

let objects = [];
let searchTerm = '';
let failedSourceCount = 0;

const escapeHtml = (value) => value
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const objectUrl = (object) => `${object.source.origin}/${object.key.split('/').map(encodeURIComponent).join('/')}`;

const formatBytes = (bytes, precise = false) => {
  if (!Number.isFinite(bytes) || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1000)), units.length - 1);
  const value = bytes / 1000 ** index;
  return `${value.toFixed(precise || value < 10 ? 1 : 0)} ${units[index]}`;
};

const formatDate = (date) => new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
}).format(date);

const typeForKey = (key) => {
  if (key.endsWith('.fastq.gz') || key.endsWith('.fq.gz')) return 'FASTQ';
  if (key.endsWith('.vcf.gz') || key.endsWith('.vcf')) return 'VCF';
  if (key.endsWith('.bam')) return 'BAM';
  if (key.endsWith('.bai')) return 'BAI';
  if (key.endsWith('.sha256') || key.endsWith('checksum.txt')) return 'SHA-256';
  if (key.endsWith('.csv')) return 'CSV';
  if (key.endsWith('.tsv')) return 'TSV';
  if (key.endsWith('.json')) return 'JSON';
  if (key.endsWith('.md')) return 'MD';
  if (key.endsWith('.html')) return 'HTML';
  if (key.endsWith('.bed')) return 'BED';
  if (key.endsWith('.fa') || key.endsWith('.fasta')) return 'FASTA';
  if (key.endsWith('.py')) return 'PY';
  return 'FILE';
};

function buildTree(items) {
  const root = {
    name: 'Diana public S3',
    type: 'directory',
    children: new Map(),
    size: 0,
    fileCount: 0,
    lastModified: new Date(0),
  };

  items.forEach((object) => {
    const sourceKey = `source:${object.source.id}`;
    if (!root.children.has(sourceKey)) {
      root.children.set(sourceKey, {
        name: object.source.treeName,
        type: 'directory',
        children: new Map(),
        size: 0,
        fileCount: 0,
        lastModified: new Date(0),
        source: object.source,
      });
    }

    root.size += object.size;
    root.fileCount += 1;
    if (object.lastModified > root.lastModified) root.lastModified = object.lastModified;
    let directory = root.children.get(sourceKey);
    directory.size += object.size;
    directory.fileCount += 1;
    if (object.lastModified > directory.lastModified) directory.lastModified = object.lastModified;

    const parts = object.relativeKey.split('/').filter(Boolean);
    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      if (isFile) {
        directory.children.set(`file:${part}`, { ...object, name: part, type: 'file' });
        return;
      }

      const childKey = `directory:${part}`;
      if (!directory.children.has(childKey)) {
        directory.children.set(childKey, {
          name: part,
          type: 'directory',
          children: new Map(),
          size: 0,
          fileCount: 0,
          lastModified: new Date(0),
        });
      }
      directory = directory.children.get(childKey);
      directory.size += object.size;
      directory.fileCount += 1;
      if (object.lastModified > directory.lastModified) directory.lastModified = object.lastModified;
    });
  });

  return root;
}

function sortedChildren(directory) {
  return [...directory.children.values()].sort((a, b) => {
    if (a.type !== b.type) return a.type === 'directory' ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { numeric: true });
  });
}

function renderDirectory(directory, depth = 0, isRoot = false) {
  const childMarkup = sortedChildren(directory).map((child) => {
    if (child.type === 'directory') return renderDirectory(child, depth + 1);

    const fileType = typeForKey(child.key);
    const url = objectUrl(child);
    return `
      <div class="tree-file" style="--depth: ${depth + 1}">
        <span class="file-glyph" aria-hidden="true"></span>
        <a class="file-name" href="${url}" title="Download ${escapeHtml(child.name)}">${escapeHtml(child.name)}</a>
        <span class="file-type">${fileType}</span>
        <time class="item-date" datetime="${child.lastModified.toISOString()}" title="Updated ${child.lastModified.toISOString()}">${formatDate(child.lastModified)}</time>
        <span class="item-size">${formatBytes(child.size)}</span>
        <a class="download-link" href="${url}" aria-label="Download ${escapeHtml(child.name)}" title="Download">↓</a>
      </div>`;
  }).join('');

  const startsOpen = Boolean(searchTerm) || isRoot || depth <= 1;
  const sourceTitle = directory.source ? ` title="${escapeHtml(directory.source.description)}"` : '';

  return `
    <details class="tree-directory${isRoot ? ' root-directory' : ''}"${startsOpen ? ' open' : ''}>
      <summary style="--depth: ${depth}"${sourceTitle}>
        <span class="chevron" aria-hidden="true"></span>
        <span class="folder-glyph" aria-hidden="true"></span>
        <strong>${escapeHtml(directory.name)}</strong>
        <span class="directory-meta">${directory.fileCount} ${directory.fileCount === 1 ? 'file' : 'files'}</span>
        <time class="item-date" datetime="${directory.lastModified.toISOString()}" title="Most recent file: ${directory.lastModified.toISOString()}">${formatDate(directory.lastModified)}</time>
        <span class="item-size">${formatBytes(directory.size)}</span>
      </summary>
      <div class="tree-children">${childMarkup}</div>
    </details>`;
}

function renderTree() {
  const filtered = searchTerm
    ? objects.filter((object) => object.searchText.includes(searchTerm))
    : objects;
  const treeElement = document.querySelector('#file-tree');

  if (!filtered.length) {
    treeElement.innerHTML = objects.length
      ? '<div class="empty-tree">No files or folders match that search.</div>'
      : '<div class="empty-tree error">The public inventories are currently unavailable. Refresh to try again.</div>';
  } else {
    treeElement.innerHTML = renderDirectory(buildTree(filtered), 0, true);
  }

  const suffix = searchTerm ? ` matching “${searchTerm}”` : '';
  const failureNotice = failedSourceCount ? ' · inventory unavailable' : '';
  document.querySelector('#inventory-status').textContent = `${filtered.length.toLocaleString()} of ${objects.length.toLocaleString()} public files${suffix}${failureNotice}`;
}

async function fetchInventory(source) {
  if (!source.indexUrl) return fetchS3Inventory(source);

  const response = await fetch(source.indexUrl, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${source.name} index returned ${response.status}`);

  const inventory = await response.json();
  if (!Array.isArray(inventory.objects)) throw new Error(`${source.name} index did not contain an objects array`);

  const generatedAt = new Date(inventory.generated_at);
  const collected = inventory.objects.flatMap((entry) => {
    const key = typeof entry.key === 'string' ? entry.key : '';
    const size = Number(entry.size);
    const lastModified = new Date(entry.last_modified);
    if (!key || key.endsWith('/') || !Number.isFinite(size) || Number.isNaN(lastModified.getTime())) return [];

    return [{
      key,
      relativeKey: key,
      source,
      searchText: `${source.name} ${source.treeName} ${key}`.toLowerCase(),
      size,
      lastModified,
    }];
  });

  return {
    generatedAt: Number.isNaN(generatedAt.getTime()) ? null : generatedAt,
    objects: collected,
  };
}

async function fetchS3Inventory(source) {
  const collected = [];
  let continuationToken = '';

  do {
    const query = new URLSearchParams({ 'list-type': '2', prefix: source.prefix, 'max-keys': '1000' });
    if (continuationToken) query.set('continuation-token', continuationToken);
    const response = await fetch(`${source.origin}/?${query}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${source.name} inventory returned ${response.status}`);

    const xml = new DOMParser().parseFromString(await response.text(), 'application/xml');
    if (xml.querySelector('parsererror, Error')) throw new Error(`${source.name} inventory response was not readable`);

    xml.querySelectorAll('Contents').forEach((entry) => {
      const key = entry.querySelector('Key')?.textContent ?? '';
      if (!key || key.endsWith('/') || !key.startsWith(source.prefix)) return;

      const size = Number(entry.querySelector('Size')?.textContent ?? 0);
      const lastModified = new Date(entry.querySelector('LastModified')?.textContent ?? 0);
      if (!Number.isFinite(size) || Number.isNaN(lastModified.getTime())) return;

      collected.push({
        key,
        relativeKey: key.slice(source.prefix.length),
        source,
        searchText: `${source.name} ${source.bucket} ${source.treeName} ${key}`.toLowerCase(),
        size,
        lastModified,
      });
    });

    continuationToken = xml.querySelector('IsTruncated')?.textContent === 'true'
      ? xml.querySelector('NextContinuationToken')?.textContent ?? ''
      : '';
  } while (continuationToken);

  return {
    generatedAt: null,
    objects: collected,
  };
}

function updateSourceCard(source, sourceObjects, generatedAt = null, error = null) {
  const card = document.querySelector(`#source-${source.id}`);
  const state = card.querySelector('.source-state');
  const stats = card.querySelector('.source-stats');

  if (error) {
    card.classList.add('source-error');
    state.classList.add('error');
    state.querySelector('span').textContent = 'Unavailable';
    stats.innerHTML = '<strong>—</strong><span>Refresh to retry this inventory.</span>';
    return;
  }

  const bytes = sourceObjects.reduce((sum, object) => sum + object.size, 0);
  const newest = sourceObjects.reduce((latest, object) => object.lastModified > latest ? object.lastModified : latest, new Date(0));
  state.querySelector('span').textContent = source.statusLabel;
  const generatedLabel = generatedAt ? ` · index ${formatDate(generatedAt)}` : '';
  const latestLabel = sourceObjects.length ? ` · latest file ${formatDate(newest)}` : '';
  stats.innerHTML = `<strong>${sourceObjects.length.toLocaleString()} files</strong><span>${formatBytes(bytes, true)}${latestLabel}${generatedLabel}</span>`;
}

async function loadInventory() {
  const inventories = await Promise.allSettled(PUBLIC_SOURCES.map((source) => fetchInventory(source)));

  inventories.forEach((result, index) => {
    const source = PUBLIC_SOURCES[index];
    if (result.status === 'fulfilled') {
      objects.push(...result.value.objects);
      updateSourceCard(source, result.value.objects, result.value.generatedAt);
    } else {
      failedSourceCount += 1;
      updateSourceCard(source, [], null, result.reason);
      console.error(result.reason);
    }
  });

  const bytes = objects.reduce((sum, object) => sum + object.size, 0);
  const newest = objects.reduce((latest, object) => object.lastModified > latest ? object.lastModified : latest, new Date(0));
  document.querySelector('#object-count').textContent = objects.length.toLocaleString();
  document.querySelector('#total-size').textContent = formatBytes(bytes, true);
  document.querySelector('#last-updated').textContent = objects.length ? formatDate(newest) : 'Unavailable';
  renderTree();
}

document.querySelector('#tree-search').addEventListener('input', (event) => {
  searchTerm = event.target.value.trim().toLowerCase();
  renderTree();
});

document.querySelector('#expand-all').addEventListener('click', () => {
  document.querySelectorAll('.tree-directory').forEach((directory) => { directory.open = true; });
});

document.querySelector('#collapse-all').addEventListener('click', () => {
  document.querySelectorAll('.tree-directory').forEach((directory) => { directory.open = directory.classList.contains('root-directory'); });
});

document.querySelector('#copy-instructions').addEventListener('click', async (event) => {
  await navigator.clipboard.writeText(markdownInstructions);
  const button = event.currentTarget;
  button.textContent = 'Copied';
  window.setTimeout(() => { button.textContent = 'Copy Markdown'; }, 1800);
});

loadInventory();
