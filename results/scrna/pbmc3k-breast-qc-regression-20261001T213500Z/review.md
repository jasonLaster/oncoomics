# Single-cell calibration

Public matrix-level calibration on Modal with S3 custody.

| Dataset | Input cells | Retained | Doublets flagged | Clusters | Seed ARI | Reference ARI | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| pbmc3k | 2700 | 2330 | 110 | 5 | 0.967 | 0.842 | pass |

## Interpretation boundaries

Ambient RNA is unassessed because empty-droplet matrices were not provided. Doublet precision/recall is unvalidated. PBMC3k tutorial labels are a same-dataset comparison, not independent truth. Labels are provisional marker hints. Captures/sample proxies are analyzed separately; published breast labels are evaluation only. No donor-level differential expression, malignant-cell validation, or clinical claims.

Use artifact_index.json and run_manifest.json for immutable custody.
