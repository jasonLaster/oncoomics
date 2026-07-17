# Diana Omics Public Validation Results

Vite landing page for reviewed Diana Omics results generated from public benchmark datasets and validation runs.

The file browser fetches a reviewed static object index from:

`https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/public-index/objects.json`

The index schema is:

```json
{
  "generated_at": "2026-07-17T00:00:00Z",
  "objects": [
    {
      "key": "runs/public-validation/example.json",
      "size": 1234,
      "last_modified": "2026-07-17T00:00:00Z"
    }
  ]
}
```

Only objects included in that reviewed index appear in the browser. File links use direct HTTPS URLs for current object versions; the site does not enumerate the bucket.

```bash
npm install
npm run dev
```
