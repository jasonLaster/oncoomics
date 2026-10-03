export function shouldOpenDirectory({
  hasSearchQuery,
  isRoot,
  depth,
  source,
  key,
}) {
  return hasSearchQuery
    || isRoot
    || depth <= 1
    || source?.defaultOpenDirectoryKeys?.includes(key) === true;
}
