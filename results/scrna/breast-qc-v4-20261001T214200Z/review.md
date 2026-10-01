# Single-cell calibration

Public matrix-level calibration on Modal with S3 custody.

| Dataset | Input cells | Retained | Doublets flagged | Clusters | Seed ARI | Reference ARI | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| CID44971 | 7986 | 6605 | 567 | 19 | 0.871 | Not available | needs_review |
| CID3941 | 631 | 508 | 16 | 6 | 0.910 | Not available | needs_review |
| CID3838 | 2353 | 2066 | 88 | 10 | 0.955 | Not available | needs_review |

### CID44971: breast QC readiness

Coarse author-label balanced agreement 0.971; production ready: no.

- Independent annotation/doublet truth is unavailable
- Empty-droplet matrix unavailable: ambient RNA correction unvalidated
- Technical capture map unresolved: scDblFinder used sample matrix as a proxy
- Per-sample chemistry unresolved
- At least one published compartment retained less than 70%; inspect loss before downstream use

### CID3941: breast QC readiness

Coarse author-label balanced agreement 0.571; production ready: no.

- Independent annotation/doublet truth is unavailable
- Empty-droplet matrix unavailable: ambient RNA correction unvalidated
- Technical capture map unresolved: scDblFinder used sample matrix as a proxy
- Per-sample chemistry unresolved
- At least one published compartment retained less than 70%; inspect loss before downstream use

### CID3838: breast QC readiness

Coarse author-label balanced agreement 0.992; production ready: no.

- Independent annotation/doublet truth is unavailable
- Empty-droplet matrix unavailable: ambient RNA correction unvalidated
- Technical capture map unresolved: scDblFinder used sample matrix as a proxy
- Per-sample chemistry unresolved
- At least one published compartment retained less than 70%; inspect loss before downstream use

## Interpretation boundaries

Ambient RNA is unassessed because empty-droplet matrices were not provided. Doublet precision/recall is unvalidated. PBMC3k tutorial labels are a same-dataset comparison, not independent truth. Labels are provisional marker hints. Captures/sample proxies are analyzed separately; published breast labels are evaluation only. No donor-level differential expression, malignant-cell validation, or clinical claims.

Use artifact_index.json and run_manifest.json for immutable custody.
