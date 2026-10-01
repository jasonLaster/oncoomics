# Single-cell calibration

Public PBMC matrix-level calibration on Modal with S3 custody.

| Dataset | Input cells | Retained | Doublets flagged | Clusters | Seed ARI | Reference ARI | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| pbmc3k | 2700 | 2330 | 110 | 5 | 0.967 | 0.842 | pass |
| pbmc5k-nextgem | 5527 | 3890 | 249 | 10 | 0.814 | Not available | needs_review |

## Interpretation boundaries

Ambient RNA is unassessed because empty-droplet matrices were not provided. Doublet precision/recall is unvalidated. PBMC3k tutorial labels are a same-dataset comparison, not independent truth. Labels are provisional marker hints. Captures are analyzed separately; no donor-level differential expression, tumor validation, or clinical claims.

Use artifact_index.json and run_manifest.json for immutable custody.
