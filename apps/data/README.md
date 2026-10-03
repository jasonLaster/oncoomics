# Diana Omics Public Data

Vite landing page for public Diana Omics data.

The file browser fetches reviewed analysis outputs from a static object index:

`https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json`

The index schema is:

```json
{
  "generated_at": "2026-07-17T00:00:00Z",
  "objects": [
    {
      "key": "runs/public-validation/example.json",
      "size": 1234,
      "last_modified": "2026-07-17T00:00:00Z",
      "reviewed_public": {
        "version_id": "3Lg...",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "checksum_sha256": "ASNFZ4mrze8BI0VniavN7wEjRWeJq83vASNFZ4mrze8="
      }
    }
  ]
}
```

The browser also lists current public raw inbox objects directly from:

```text
s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/
```

The results-bucket index is intentionally static and reviewed. The raw inbox is
publicly listable and readable under `diana/inbox/` so accepted external
deliveries appear without rebuilding the index. File links use direct HTTPS URLs
for current object versions.

Public WGS cache objects stored in Glacier Flexible Retrieval are listed from a
metadata-only snapshot generated at:

```text
public/glacier-index.json
```

Refresh that snapshot with `npm run refresh:glacier-index`. The generator is
strictly scoped to `cache/phase3_wgs/`; it does not publish `private/` or
`security/` key metadata. Glacier rows are visibly marked and are not direct
download links. Their action menu provides an owner-authorized S3 restore
command instead.

The generated restore command requests a seven-day temporary restored copy. That
window does not delete or expire the underlying Glacier object.

## Shareable input pages

Every raw input folder has a focused download page at:

```text
https://data.diana-tnbc.com/inputs/INPUT_PATH
```

For example:

```text
https://data.diana-tnbc.com/inputs/2026-07-30-h-and-e-slides
```

Focused pages query only that import's live S3 prefix, show anonymous AWS CLI
and checksum instructions, list its files, and link back to the complete public
data browser. Nested folders keep their full path, for example
`/inputs/2026-07-14-echo-personalis/data/immunoid`. The all-data browser exposes
these pages from the action menu on every raw input folder.

```bash
npm install
npm run dev
```
