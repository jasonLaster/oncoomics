# Rosalind Workbench Handoff

Use the NGS single-cell post-count analysis path to review the completed public benchmark at:

```text
s3://diana-omics-results-172630973301-us-east-1/modal/rosalind-scrna/runs/pbmc3k-20260903T213200Z/
```

Before interpretation, verify `run_manifest.json` SHA-256 `9d31d1fc5da1db2dd52f2af0f8b8aa72131f0cfe0b881f34021f594070175868` and then verify each artifact against `artifact_index.json`.

## Starter prompt

```text
Review this completed public PBMC3k scRNA-seq benchmark as a post-count analysis. Start from run_manifest.json and artifact_index.json, then inspect scrna_qc_summary.csv, cluster_summary.csv, marker_genes.csv, umap_leiden.png, and pbmc3k_processed.h5ad.

Question: What immune subsets are plausibly represented by the six Leiden clusters, and which marker genes support each provisional label?

Return cluster_annotation_review.csv, reviewer_notes.md, and next_actions.md. Keep every label provisional unless the marker pattern is coherent. Flag doublet, ambient-RNA, low-cell-count, and mixed-lineage concerns. Do not describe this public benchmark as Diana sample evidence and do not make clinical, target-readiness, or treatment claims.
```

If the Workbench storage integration cannot read the S3 prefix directly, attach the two manifests, QC and cluster CSVs, marker table, and UMAP. Keep the H5AD in approved storage and let the analysis runtime open it rather than placing its raw contents into the conversation context.
