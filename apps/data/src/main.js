import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import markdown from 'highlight.js/lib/languages/markdown';
import 'highlight.js/styles/github-dark.css';
import './styles.css';

hljs.registerLanguage('bash', bash);
hljs.registerLanguage('markdown', markdown);

const BUCKET = 'diana-omics-raw-inputs-172630973301-us-east-1';
const REGION = 'us-east-1';
const PREFIX = 'diana/inbox/';
const S3_ORIGIN = `https://${BUCKET}.s3.${REGION}.amazonaws.com`;
const S3_URI = `s3://${BUCKET}/${PREFIX}`;

const markdownInstructions = `## Download everything

\`\`\`bash
aws s3 cp ${S3_URI} ./diana-inbox/ \\
  --recursive \\
  --no-sign-request
\`\`\`

## Download one directory

\`\`\`bash
aws s3 cp ${S3_URI}2026-07-14-echo-personalis/data/wgs/ ./wgs/ \\
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
    <span class="access-badge"><i></i> Public data</span>
  </header>

  <main class="shell" id="top">
    <section class="intro">
      <div>
        <p class="eyebrow">Open genomic dataset</p>
        <h1>Diana Omics data</h1>
        <p class="intro-copy">Browse the folders below or download files directly. No AWS account or credentials are required.</p>
      </div>
      <dl class="dataset-stats" aria-label="Dataset summary">
        <div><dt>Files</dt><dd id="object-count">—</dd></div>
        <div><dt>Size</dt><dd id="total-size">—</dd></div>
        <div><dt>Updated</dt><dd id="last-updated">—</dd></div>
      </dl>
    </section>

    <section class="download-section" aria-labelledby="download-heading">
      <div class="download-copy">
        <p class="eyebrow">Download guide</p>
        <h2 id="download-heading">Get the data</h2>
        <p>Download locally or transfer the dataset to another S3 bucket, Google Cloud, a GCE disk, or Box.</p>
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
          <h2 id="files-heading">Files</h2>
          <p id="inventory-status">Loading live inventory…</p>
        </div>
        <div class="tree-actions">
          <button id="expand-all" type="button">Expand all</button>
          <button id="collapse-all" type="button">Collapse all</button>
        </div>
      </div>

      <div class="tree-panel">
        <div class="tree-toolbar">
          <div class="path-label"><span>s3</span><code>${S3_URI}</code></div>
          <label class="search-field">
            <span aria-hidden="true">⌕</span>
            <span class="sr-only">Search files and folders</span>
            <input id="tree-search" type="search" placeholder="Search files and folders" autocomplete="off" />
          </label>
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
      <span>Live index · Amazon S3 · Anonymous reads</span>
    </div>
  </footer>
`;

const codeElement = document.querySelector('#markdown-code');
codeElement.innerHTML = highlightMarkdownWithBash(markdownInstructions);
codeElement.classList.add('hljs');

let objects = [];
let searchTerm = '';

const escapeHtml = (value) => value
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const objectUrl = (key) => `${S3_ORIGIN}/${key.split('/').map(encodeURIComponent).join('/')}`;

const formatBytes = (bytes, precise = false) => {
  if (!Number.isFinite(bytes) || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1000)), units.length - 1);
  const value = bytes / 1000 ** index;
  return `${value.toFixed(precise || value < 10 ? 1 : 0)} ${units[index]}`;
};

const formatDate = (date) => new Intl.DateTimeFormat('en-US', {
  month: 'short', day: 'numeric', year: 'numeric'
}).format(date);

const typeForKey = (key) => {
  if (key.endsWith('.fastq.gz')) return 'FASTQ';
  if (key.endsWith('.bam')) return 'BAM';
  if (key.endsWith('.bai')) return 'BAI';
  if (key.endsWith('.sha256') || key.endsWith('checksum.txt')) return 'SHA-256';
  if (key.endsWith('.csv')) return 'CSV';
  return 'FILE';
};

function buildTree(items) {
  const root = { name: 'diana/inbox', type: 'directory', children: new Map(), size: 0, fileCount: 0 };

  items.forEach((object) => {
    const parts = object.key.slice(PREFIX.length).split('/');
    let directory = root;
    directory.size += object.size;
    directory.fileCount += 1;

    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      if (isFile) {
        directory.children.set(`file:${part}`, { ...object, name: part, type: 'file' });
        return;
      }

      const childKey = `directory:${part}`;
      if (!directory.children.has(childKey)) {
        directory.children.set(childKey, { name: part, type: 'directory', children: new Map(), size: 0, fileCount: 0 });
      }
      directory = directory.children.get(childKey);
      directory.size += object.size;
      directory.fileCount += 1;
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
    return `
      <div class="tree-file" style="--depth: ${depth + 1}">
        <span class="file-glyph" aria-hidden="true"></span>
        <a class="file-name" href="${objectUrl(child.key)}" title="Download ${escapeHtml(child.name)}">${escapeHtml(child.name)}</a>
        <span class="file-type">${fileType}</span>
        <span class="item-size">${formatBytes(child.size)}</span>
        <a class="download-link" href="${objectUrl(child.key)}" aria-label="Download ${escapeHtml(child.name)}" title="Download">↓</a>
      </div>`;
  }).join('');

  const collapsedByDefault = depth === 3 && ['immunoid', 'wgs'].includes(directory.name.toLowerCase());
  const startsOpen = Boolean(searchTerm) || !collapsedByDefault;

  return `
    <details class="tree-directory${isRoot ? ' root-directory' : ''}"${startsOpen ? ' open' : ''}>
      <summary style="--depth: ${depth}">
        <span class="chevron" aria-hidden="true"></span>
        <span class="folder-glyph" aria-hidden="true"></span>
        <strong>${escapeHtml(directory.name)}</strong>
        <span class="directory-meta">${directory.fileCount} ${directory.fileCount === 1 ? 'file' : 'files'}</span>
        <span class="item-size">${formatBytes(directory.size)}</span>
      </summary>
      <div class="tree-children">${childMarkup}</div>
    </details>`;
}

function renderTree() {
  const filtered = searchTerm
    ? objects.filter((object) => object.key.toLowerCase().includes(searchTerm))
    : objects;
  const treeElement = document.querySelector('#file-tree');

  if (!filtered.length) {
    treeElement.innerHTML = '<div class="empty-tree">No files or folders match that search.</div>';
  } else {
    treeElement.innerHTML = renderDirectory(buildTree(filtered), 0, true);
  }

  const suffix = searchTerm ? ` matching “${searchTerm}”` : '';
  document.querySelector('#inventory-status').textContent = `${filtered.length} of ${objects.length} files${suffix}`;
}

async function fetchInventory() {
  const collected = [];
  let continuationToken = '';

  do {
    const query = new URLSearchParams({ 'list-type': '2', prefix: PREFIX, 'max-keys': '1000' });
    if (continuationToken) query.set('continuation-token', continuationToken);
    const response = await fetch(`${S3_ORIGIN}/?${query}`);
    if (!response.ok) throw new Error(`S3 returned ${response.status}`);

    const xml = new DOMParser().parseFromString(await response.text(), 'application/xml');
    if (xml.querySelector('parsererror, Error')) throw new Error('S3 inventory response was not readable');

    xml.querySelectorAll('Contents').forEach((entry) => {
      const key = entry.querySelector('Key')?.textContent ?? '';
      if (!key || key.endsWith('/')) return;
      collected.push({
        key,
        size: Number(entry.querySelector('Size')?.textContent ?? 0),
        lastModified: new Date(entry.querySelector('LastModified')?.textContent ?? 0),
      });
    });

    continuationToken = xml.querySelector('IsTruncated')?.textContent === 'true'
      ? xml.querySelector('NextContinuationToken')?.textContent ?? ''
      : '';
  } while (continuationToken);

  return collected;
}

async function loadInventory() {
  try {
    objects = await fetchInventory();
    const bytes = objects.reduce((sum, object) => sum + object.size, 0);
    const newest = objects.reduce((latest, object) => object.lastModified > latest ? object.lastModified : latest, new Date(0));
    document.querySelector('#object-count').textContent = objects.length.toLocaleString();
    document.querySelector('#total-size').textContent = formatBytes(bytes, true);
    document.querySelector('#last-updated').textContent = formatDate(newest);
    renderTree();
  } catch (error) {
    document.querySelector('#file-tree').innerHTML = '<div class="empty-tree error">The live inventory could not be loaded. Refresh to try again.</div>';
    document.querySelector('#inventory-status').textContent = 'Inventory unavailable';
    console.error(error);
  }
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
