export function shouldOpenDirectory({
  hasSearchQuery,
  isRoot,
  depth,
  source,
}) {
  return hasSearchQuery
    || isRoot
    || depth <= 1
    || source?.expandByDefault === true;
}
