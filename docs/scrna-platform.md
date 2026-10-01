# Single-cell RNA-seq platform

This platform runs bounded, reproducible public PBMC post-count analysis on Modal and stores source matrices and immutable results in the existing Diana S3 buckets. It is a separate single-cell analysis lane beside the DNA/HRD workflows.

[Breast tumor QC recipe 4](scrna-breast-qc.md) adds a separate tissue profile, explicit sample/capture readiness, nuisance review signals, and compartment-loss/sensitivity audits. The PBMC recipe and its screens remain the baseline below.

## Scientific plan

The first decision is whether the post-count pipeline preserves counts and custody, performs capture-aware QC/doublet assessment, returns plausible cell compartments, and recovers published PBMC structure. This is matrix-level calibration, not validation of FASTQ counting, ambient removal, tumor annotation, or clinical interpretation.

Two public datasets exercise different input formats and chemistries:

| Dataset | Inputs | Expected barcodes | Reference | Calibration role |
| --- | --- | ---: | --- | --- |
| [10x PBMC3k](https://www.10xgenomics.com/datasets/3-k-pbm-cs-from-a-healthy-donor-1-standard-1-1-0) | Legacy 10x MTX archive | 2,700 | Vendor hg19 counts | Format regression and agreement with [Scanpy tutorial annotations](https://scanpy.scverse.org/en/stable/generated/scanpy.datasets.pbmc3k_processed.html) |
| [10x PBMC5k Next GEM](https://www.10xgenomics.com/datasets/5-k-peripheral-blood-mononuclear-cells-pbm-cs-from-a-healthy-donor-with-cell-surface-proteins-next-gem-3-1-standard-3-1-0) | HDF5 gene expression plus antibody tags | 5,527 | Vendor GRCh38-3.0.0 counts | Second chemistry, H5 parsing, explicit exclusion of antibody tags from RNA analysis |

Each capture is processed separately. Donor identifiers are dataset-specific custody placeholders; donor relatedness across public datasets is not established. Cells are not biological replicates. No cross-reference concatenation, differential expression, integration, or disease comparison is performed. Tutorial annotations are reserved for scoring after unsupervised analysis; they are not fed into clustering or marker hints. They are same-dataset annotations, not independent truth.

`manifests/scrna/calibration.json` defines sources, expected input dimensions, assay metadata, method parameters, and acceptance screens before execution. `calibration.lock.json` freezes actual source hashes and S3 versions. A changed source fails checksum verification when restaging the lock file.

## Architecture

```mermaid
flowchart LR
    Public[Official public matrices] --> Stage[Checksum and metadata staging]
    Stage --> Raw[S3 content-addressed inputs]
    Raw --> Worker[Modal worker: 4 CPU / 16 GiB]
    Worker --> QC[QC distributions and scDblFinder per capture]
    QC --> Analysis[Sparse normalization / HVG / PCA / Leiden / UMAP]
    Analysis --> Evaluate[Frozen calibration screens]
    Evaluate --> Results[S3 immutable run and artifact hashes]
    Results --> Review[Verified local HTML review and H5AD]
```

Existing Modal secret `onco-omics-use1` supplies AWS credentials. No credentials are copied into this repository. Workers mount only the raw bucket's `public/` prefix, read-only. H5AD checkpoints are written on local ephemeral disk because HDF5 uses random access; completed files are uploaded through the S3 API. The platform provisions no VPC, NAT gateway, persistent worker, GPU, new bucket, or public web endpoint.

- Input bucket: `diana-omics-raw-inputs-172630973301-us-east-1`, prefix `public/scrna/inputs/<dataset>/<sha256>/`.
- Result bucket: `diana-omics-results-172630973301-us-east-1`, prefix `public/scrna/runs/<run-id>/`.
- Modal app: `diana-scrna-platform`, region `us-east`, maximum two worker containers, 30-minute timeout per invocation.

S3 inputs and results use AES256 server-side encryption. Object writes use `IfNoneMatch="*"`; run reservation is atomic and existing run IDs cannot be overwritten. An exception writes `_FAILED.json`. `run_manifest.json` is the last object written and means all indexed uploads completed. It does **not** by itself imply scientific calibration passed. Download verification checks all sizes and SHA-256 hashes against the artifact index, whose hash is bound into the completion manifest. `s3_verification.json` records downloaded object version IDs.

## Analysis policy

1. Check raw UMI counts, unique barcodes, expected cell count, mitochondrial symbols, source hashes, and assay metadata.
2. Inspect detected genes, UMIs, and mitochondrial fraction. Use lower 3-MAD tails in log1p genes/UMIs and an upper 3-MAD mitochondrial tail, with PBMC guardrails of 50 genes, 100 UMIs, and 5–25% mitochondrial fraction. Save observed distributions with threshold lines. Hemoglobin is measured as a review signal, not an exclusion rule. These are pilot human PBMC policies and require review before another tissue.
3. Call [scDblFinder](https://bioconductor.org/packages/release/bioc/html/scDblFinder.html) on core-QC-qualified cells within each capture. Preserve scores/classes. Cells failing core QC explicitly have an uncalled doublet state.
4. Keep all raw counts and barcode decisions in `all_cells_qc.h5ad` and CSV. Analyze singlets passing core QC; retain raw counts in `analysis.h5ad`'s `counts` layer. Verify the persisted counts checkpoint.
5. Normalize to 10,000 counts, log1p, select 2,000 HVGs, scale only the sparse HVG subset, then PCA, neighbors, Leiden through convergence (`n_iterations=-1`), and UMAP. PCA is appropriate for these small single-capture pilots; no scVI integration is implied.
6. Produce exploratory Wilcoxon cluster markers and coarse PBMC marker hints. Hints and score margins are provisional; margins are not confidence probabilities. Fine labels stay `unreviewed`.
7. Evaluate expected cell count, retention (70–99%), cluster range (4–25), finite embeddings, preserved counts, completed doublet calls, Leiden stability across two seeds (ARI ≥0.85), and PBMC3k tutorial agreement (≥2,000 shared barcodes; ARI ≥0.55). These are engineering/plausibility screens, not clinical sensitivity/specificity. Record failures as `needs_review`; do not weaken thresholds to obtain a pass.

Ambient RNA is **not assessed or corrected** in this pilot because filtered matrices lack empty droplets. Doublet precision/recall needs independently labeled mixtures. Marker labels, tumor/malignant-cell detection, target suitability, and donor-level statistics remain unvalidated.

## Run and recover

From the repository root with existing machine-scoped AWS/Modal authentication:

```sh
# Freeze and stage sources. Reruns should use --config manifests/scrna/calibration.lock.json.
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py stage

# Verify cloud dependencies and S3 access.
PYTHONPATH=src modal run scripts/modal/scrna_platform.py --preflight-only

# Use a fresh immutable run ID.
PYTHONPATH=src modal run --timestamps scripts/modal/scrna_platform.py --run-id pbmc-calibration-YYYYMMDDTHHMMSSZ --repeat-check

# Verify and download completed artifacts. This performs no recomputation.
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py collect --run-id pbmc-calibration-YYYYMMDDTHHMMSSZ
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py collect --run-id pbmc-calibration-YYYYMMDDTHHMMSSZ-repeat
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py compare --first-run pbmc-calibration-YYYYMMDDTHHMMSSZ --second-run pbmc-calibration-YYYYMMDDTHHMMSSZ-repeat

# Deploy callable functions; containers scale to zero between calls.
PYTHONPATH=src modal deploy scripts/modal/scrna_platform.py
```

The source package and Modal runner are copied into each run's artifact set. Python versions and an explicit Conda/R environment export accompany results; primary Python versions and scDblFinder are pinned in the Modal image. The explicit export captures transitive dependencies of the actual run; rebuilding from open transitive dependencies may drift until an image/lock snapshot is reused. Modal CLI 1.5.2 was used for the initial build.

Open `results/scrna/<run-id>/review.html` for figures, metrics, artifact links, and limitations. `review.md`, `calibration_summary.json`, `artifact_index.json`, `run_manifest.json`, and `s3_verification.json` are the audit surfaces. Large H5ADs are ignored by Git and recoverable from S3.

## Extend after the pilot

- FASTQ-to-count: add chemistry/read-role/whitelist validation and a pinned compatible counting implementation with separately calibrated cell calling.
- Ambient RNA: add unfiltered droplets and a validated SoupX/CellBender lane; preserve original and corrected matrices.
- Annotation: add a matched, versioned immune reference and independent held-out labels; evaluate accuracy and rejection of ambiguous cells.
- Breast tumor cohorts: add donor/sample/capture metadata, tissue-specific QC review, independently reviewed malignant-cell labels, and multi-donor calibration before biology claims.
- Integration: evaluate scVI when actual cross-donor/chemistry integration is required; quantify preservation of biological structure and removal of technical effects.
- Statistics: require biological replication and donor-level pseudobulk designs before differential-expression claims.

These are later validation stages, not implemented capabilities of this pilot.

## Calibration iteration

The first recipe stopped Leiden after two iterations. PBMC3k passed all screens (2,330 retained cells; five clusters; tutorial ARI 0.844), but PBMC5k seed stability was 0.840, below the predeclared 0.850 gate. Recipe 2 runs Leiden through convergence; the seed-stability acceptance threshold stays 0.850. Prior S3 runs retain their original source, manifest, parameters, and failed screen. This is an algorithm-convergence change, not a weaker acceptance rule.

Verified recipe-2 run: `pbmc-calibration-v2-20261001T210600Z` (October 1, 2026).

| Dataset | Retained cells | Clusters | Seed ARI | Tutorial ARI | Outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| PBMC3k | 2,330 / 2,700 | 5 | 0.967 | 0.842 | All pilot screens passed |
| PBMC5k Next GEM | 3,890 / 5,527 | 10 | 0.814 | Unavailable | Seed-stability screen needs review |

All 43 suite artifacts and 27 PBMC3k repeat artifacts were downloaded from S3 and hash-verified, with the index hashes checked against completion manifests. The repeat matched exact hashes for barcode QC decisions, UMAP/cluster coordinates, markers, code, and environments. An independent local audit confirmed exact raw-count equality against the all-barcode checkpoints for both datasets.

The PBMC5k seed cross-tab has ten clusters in each run and 3,494 / 3,890 (89.8%) best-matched barcode assignments. Redistribution between neighboring clusters remains substantial enough to fail the original ARI screen. Through-convergence clustering did not solve this. The operational platform works; PBMC5k fine cluster structure and generalization beyond PBMC3k remain uncalibrated.

The verified review is in `results/scrna/pbmc-calibration-v2-20261001T210600Z/review.html`; independent follow-up tables live separately in `results/scrna/validation/pbmc-calibration-v2-20261001T210600Z/`. Use these outputs to review granularity and reference labeling before accepting PBMC5k subdivisions. Do not interpret its engineering completion as scientific acceptance.
