const ARCHIVAL_STORAGE_CLASSES = new Set(['GLACIER', 'DEEP_ARCHIVE']);

export function isArchivedStorageClass(storageClass) {
  return ARCHIVAL_STORAGE_CLASSES.has(storageClass);
}

export function normalizeIndexedObject(entry, source) {
  const key = typeof entry.key === 'string' ? entry.key : '';
  const size = Number(entry.size);
  const lastModified = new Date(entry.last_modified);
  const storageClass = typeof entry.storage_class === 'string'
    ? entry.storage_class
    : source.storageClass ?? 'STANDARD';

  if (!key || key.endsWith('/') || !Number.isFinite(size) || Number.isNaN(lastModified.getTime())) {
    return null;
  }

  return {
    key,
    relativeKey: source.prefix && key.startsWith(source.prefix)
      ? key.slice(source.prefix.length)
      : key,
    size,
    lastModified,
    storageClass,
    archived: source.archived === true || isArchivedStorageClass(storageClass),
  };
}
