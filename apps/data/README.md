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

```bash
npm install
npm run dev
```
