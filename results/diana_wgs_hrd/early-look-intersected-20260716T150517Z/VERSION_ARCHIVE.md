# Public S3 version archive

All noncurrent object content captured in the 2026-07-16 results-bucket
snapshot is publicly archived under SSE-S3. The original S3 version chain was
left unchanged.

## Public archive root

```text
s3://diana-omics-results-172630973301-us-east-1/version-history/2026-07-16-snapshot/
```

Browse anonymously:

<https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/?list-type=2&prefix=version-history%2F2026-07-16-snapshot%2F>

## Snapshot result

- Snapshot acquired: `2026-07-16T18:44:13Z`
- Noncurrent object versions archived: `1,465`
- Archived content bytes: `845,410,505`
- Copy failures: `0`
- Archive encryption: `AES256` for all `1,465` content objects
- Delete markers recorded: `1,142`
- Original versions or delete markers removed: `0`

Delete markers contain no object body. Their key, version ID, timestamp, and
owner metadata are preserved in `VERSION_DELETE_MARKERS.tsv` and in the public
archive manifest directory.

## Object mapping

Archive objects use deterministic keys:

```text
version-history/2026-07-16-snapshot/objects/<first-two-sha256-characters>/<sha256>
```

The digest is SHA-256 over the UTF-8 original key, one NUL byte, and the S3
version ID. `VERSION_ARCHIVE_MANIFEST.tsv` maps every archive object to its
original key and version ID and supplies a direct anonymous HTTPS URL.

## Public provenance files

- `manifests/noncurrent_versions.tsv`: complete public mapping and copy result
- `manifests/delete_markers.tsv`: complete delete-marker inventory
- `manifests/archive_results.jsonl`: machine-readable copy results
- `source/object_versions_snapshot.json`: source `ListObjectVersions` snapshot
- `provenance/archive_noncurrent_s3_versions.py`: exact copy implementation

## Anonymous download

```bash
ARCHIVE='s3://diana-omics-results-172630973301-us-east-1/version-history/2026-07-16-snapshot'

aws s3api list-object-versions \
  --bucket diana-omics-results-172630973301-us-east-1 \
  --no-sign-request

aws s3 cp "$ARCHIVE/manifests/noncurrent_versions.tsv" \
  ./noncurrent_versions.tsv --no-sign-request

aws s3 sync "$ARCHIVE/objects/" ./versioned-objects/ \
  --no-sign-request --only-show-errors
```

The archive makes the content of historical SSE-KMS versions available
anonymously as new SSE-S3 objects. The original version IDs remain in the
bucket for provenance and still retain their original encryption. Bucket
version metadata is also anonymously listable, so SSE-S3 versions created
after this snapshot remain directly discoverable and readable by version ID.
