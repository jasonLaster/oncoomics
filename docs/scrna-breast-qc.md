# Breast tumor single-cell QC

Recipe 4 extends the public post-count platform with a breast tumor profile, explicit cohort metadata, tissue review signals, and loss audits against published compartments. It preserves the PBMC profile and its original acceptance screens. It remains a public research calibration lane.

## Calibration design

The pilot uses three author-processed matrices from [GSE176078](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE176078), associated with [Wu et al., Nature Genetics 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC9044823/). Selection precedes execution: CID44971 supplies the TNBC epithelial/immune/stromal mix shown in the publication; CID3941 and CID3838 exercise ER-positive and HER2-positive samples. Each patient is processed separately. These three samples are a bounded pilot, not the full atlas or a powered comparison between subtypes.

| Sample | GEO accession | Published subtype | Input cells | Purpose |
| --- | --- | --- | ---: | --- |
| CID44971 | GSM5354531 | TNBC | 7,986 | Mixed epithelial, immune, and stromal populations |
| CID3941 | GSM5354516 | ER+ | 631 | Small sample with epithelial and immune populations |
| CID3838 | GSM5354514 | HER2+ | 2,353 | Immune-rich sample with no author-labeled epithelial cells in this released matrix |

Source counts are integer UMIs, but the released cells have already passed author selection. GEO describes EmptyDrops, detected genes >200, UMIs >250, and mitochondrial fraction <20%. The author archive also contains curated labels. Removed cells, empty droplets, and raw sequencing reads cannot be reconstructed from it. The pilot therefore tests **additional QC on already-filtered cells**, not initial cell calling, ambient correction, or sensitivity to cells discarded upstream.

`manifests/scrna/breast/calibration.json` freezes the recipe, expected cell counts, source checksums, and screens. `calibration.lock.json` adds immutable S3 keys and version IDs. `source_metadata.soft` preserves the selected public GEO sample records. The matrices' `orig.ident` and subtype must match the manifest; metadata must cover every barcode exactly once. Calculated UMI and detected-gene totals must match author metadata.

The study reports primary pre-treatment tumors. That treatment timing is study-level evidence. The public sample records do not resolve technical capture channels or each sample's 3-prime versus 5-prime chemistry. `capture_scope=sample_proxy_unresolved` and `chemistry_status=unresolved` preserve those gaps. A sample ID does not prove a capture channel. scDblFinder runs on each sample matrix as a documented proxy, and unresolved metadata fails readiness screens. Multiple datasets with the same capture ID are rejected to prevent splitting one capture before doublet calling.

## QC policy

- Compute genes, UMIs, mitochondrial fraction, hemoglobin, ribosomal, stress/dissociation, and cycling expression per sample. The breast profile uses lower log1p MAD tails, caps lower cutoffs at the observed fifth percentile to protect low-RNA populations in mixed tissues, and uses the observed upper mitochondrial MAD tail without PBMC 5–25% bounds. Floors remain 50 genes and 100 UMIs. A zero-MAD breast metric disables its outlier tail. These choices are provisional and require calibration; they are not universal breast cancer thresholds.
- Exclude only failures of the core genes/UMIs/mitochondrial rules and called scDblFinder doublets. Upper UMI outliers, stress, cycling, hemoglobin, and ribosomal signals are **review only**. Large epithelial cells are not removed solely for high RNA content.
- Persist all input cells, original sparse counts, pass/fail flags, failure reasons, doublet scores/classes/partition, review flags, and donor/sample/treatment/capture metadata. `analysis.h5ad` preserves retained original counts in its `counts` layer. Original counts remain canonical; no ambient-corrected counts are claimed.
- Inspect plots with threshold lines, UMI-versus-gene scatter, and nuisance signals. Audit removal and retention by author-labeled coarse compartment after QC. The audit cannot choose thresholds or train annotations. Sensitivity tables evaluate 2, 3, and 4 MAD core policies; they do not rerun doublets or select the most favorable policy.
- Analyze each sample with sparse HVG/PCA/Leiden/UMAP. Breast embeddings omit mitochondrial, hemoglobin, ribosomal, and stress HVGs while preserving cycling genes. This affects the embedding, not counts or pass/fail decisions. No cross-donor integration, scVI model, or donor-level differential expression is performed.
- Use breast epithelial, T/NK, B/plasma, myeloid, fibroblast, endothelial, and perivascular marker panels for provisional compartment hints. T and NK scores combine into a coarse T/NK lineage; shared cytotoxic programs are insufficient for a fine call. The author major T category also contains NK cells. Fine labels remain unreviewed. Unknown/mixed is permitted; score margins are not probabilities. Epithelial expression does not establish malignancy, and author cancer/normal epithelial labels collapse to the same coarse compartment for evaluation.

The profile currently accepts whole-cell GEO breast archives with exact matching author metadata. It refuses nuclei, unsupported raw-droplet roles, and tissue/profile mismatches. A nuclei profile, a general clinical cohort importer, and ambient correction need their own supported inputs and calibration.

## Screens and readiness

Frozen engineering screens retain the original minimum 70% overall retention, 4–25 clusters, finite embeddings, preserved counts, completed scDblFinder calls, and Leiden seed ARI ≥0.85. The maximum retention is 100% for this already-filtered source; the pipeline need not discard cells to pass. Breast screens additionally require at least 70% retention within every published coarse compartment and resolved capture/chemistry metadata. Failures stay `needs_review`.

Published coarse-label accuracy, balanced accuracy, unknown-label fraction, and cross-tabs are diagnostic comparisons against the same dataset's author annotations. They do not measure independent annotation accuracy or malignant-cell sensitivity. No threshold is lowered after seeing a failure. Recipe 4 only aligns coarse T/NK reporting with the source taxonomy and leaves all recipe-3 QC rules and screens unchanged.

`production_ready` stays false for this pilot. Required next evidence includes unfiltered droplets for an ambient lane, confirmed technical capture and chemistry metadata, independently reviewed annotations/doublet truth, and broader donor validation. No private Diana samples are staged or mounted.

## Execute and review

Use the existing Modal secret, public-only raw mount, CPU workers, and S3 custody described in [the platform runbook](scrna-platform.md).

```sh
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py stage --config manifests/scrna/breast/calibration.lock.json
PYTHONPATH=src modal run --timestamps scripts/modal/scrna_platform.py --run-id breast-qc-YYYYMMDDTHHMMSSZ --config manifests/scrna/breast/calibration.lock.json
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py collect --run-id breast-qc-YYYYMMDDTHHMMSSZ
uv run --no-project --with numpy==1.26.4 --with pandas==2.2.3 --with scipy==1.15.2 --with anndata==0.11.4 --python 3.11 python scripts/audit_scrna_breast_qc.py --run-id breast-qc-YYYYMMDDTHHMMSSZ
```

Review `review.html`, `cohort_qc.csv`, per-sample `compartment_retention.csv`, `qc_sensitivity.csv`, `reference_compartment_overlap.csv`, `calibration.json`, and the all-barcode decisions. The completion manifest means artifact uploads completed; the separate calibration and readiness fields determine scientific acceptance.

The `scrna-qc-test` optional dependency group supplies the pinned Python QC/import dependencies. Use Python 3.11, matching Modal. Basic repository environments skip the science-dependent test module when dependencies are absent; calibration verification requires running it with dependencies installed:

```sh
uv run --python 3.11 --extra dev --extra scrna-qc-test pytest -q tests/test_scrna_platform.py tests/test_scrna_breast_qc.py tests/test_scrna_kickoff.py
```

## Findings requiring review

Recipe-3 run `breast-qc-v3-20261001T213900Z` completed, and all 75 indexed artifacts were downloaded and hash-verified. An independent reader compared the frozen source archives directly with both the all-barcode and retained-cell checkpoints: counts, gene/barcode order, and doublet exclusions matched exactly for all three samples. Biological acceptance still failed.

| Sample | Retained cells | Compartment finding |
| --- | ---: | --- |
| TNBC CID44971 | 6,605 / 7,986 | Epithelial retention 63.97%; 532 / 1,629 epithelial cells fail the mt rule and 52 further cells are called doublets |
| ER+ CID3941 | 508 / 631 | Epithelial retention 66.84%; 65 / 196 fail the mt rule. Myeloid retention 43.24%; low counts and doublets contribute |
| HER2+ CID3838 | 2,066 / 2,353 | B-cell retention 65.96%; 14 / 47 fail the mt rule |

These losses are not proof that excluded cells are artifacts. The author-filtered tissue contains different mitochondrial distributions across compartments. An overall retention check alone would miss the potential composition bias. All three samples remain `needs_review`; capture/chemistry gaps also fail readiness. Breast and PBMC profile decisions happened to match in these three source matrices, so this pilot does not demonstrate better biological filtering from the profile alone. The new compartment audit reveals why further calibration is necessary.

Recipe 4 aligns annotation to a coarse T/NK compartment. The source's major `T-cells` group includes cells explicitly annotated `NK cells` at the minor level. Shared cytotoxic genes also cannot reliably distinguish T versus NK in the fallback scores. Combining the coarse lineage fixes the taxonomy mismatch without using author labels to train the marker calls or changing QC decisions. Fine T/NK identity needs a matched reference and independent review.

Before using cell proportions or donor-level biology, review the epithelial mitochondrial losses with orthogonal quality evidence and a lineage-aware or multivariate QC design. The 2/3/4-MAD table is a sensitivity diagnostic, not approval to select a permissive setting. Obtain verified capture/chemistry metadata and unfiltered droplets for ambient assessment. Preserve original counts when adding correction. A malignant-cell workflow additionally needs reviewed reference cells and independent CNV/pathology evidence; epithelial markers alone cannot supply it.

PBMC3k regression `pbmc3k-breast-qc-regression-20261001T213500Z` passed the original screens. Every barcode's core/final QC decision and doublet score/class matched the baseline, as did exact UMAP, marker, and cluster-score CSV hashes: 2,330 retained cells, five clusters, seed ARI 0.96694, and tutorial ARI 0.84157. Its source snapshot predates the isolated GEO-import repair and breast-only coarse T/NK reporting change; the PBMC path and profile remain unchanged.

Final recipe-4 run `breast-qc-v4-20261001T214200Z` completed and all 75 indexed artifacts were downloaded and hash-verified. The independent raw-count audit passed for all three samples. Source snapshots match the current Python modules and Modal runner exactly. Barcode QC and doublet decisions, cluster assignments, UMAP coordinates, and marker tables match recipe 3 exactly; only coarse annotation reporting changes.

Coarse balanced agreement with the author labels is 97.11% (TNBC), 57.14% (ER+), and 99.15% (HER2+). These are same-dataset coarse comparisons. The small ER+ sample does not recover several rare stromal/myeloid compartments in the fallback labels; its high overall agreement would hide that gap. Fine annotations remain unreviewed. All three samples continue to fail compartment-retention and metadata-readiness screens.

Open [the final review](../results/scrna/breast-qc-v4-20261001T214200Z/review.html). Large H5ADs and complete historical runs remain recoverable through S3. Git keeps the final review artifacts and a small recipe-3 custody/metrics record; `collect` restores its full archive when needed. Independent checks and the annotation-only comparison are in `results/scrna/validation/`.
