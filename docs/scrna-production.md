# Breast cohort research release

The research release controls are implemented and exercised on Modal and S3. **The current three-patient GSE176078 cohort is quarantined, not production ready.** Its public inputs cannot support verified capture-aware doublet calling or raw-droplet ambient assessment, and existing compartment-loss screens still fail. No production release object has been published for it. Clinical interpretation and malignant-cell calling are outside this release scope.

## Implemented controls

`scrna_platform.py status` distinguishes running, complete, failed, inconsistent, absent, and stale runs. A start claim records the frozen configuration digest and 1,800-second worker timeout; the stale allowance is five minutes. A failed or stale run is investigated and retried with a **new** ID. Neither an existing run prefix nor a release manifest is overwritten.

The ingress validator bounds compute parameters and rejects non-finite settings, unsupported matrices/material, duplicate technical partitions, and verified capture/chemistry claims lacking sample-specific source URL, checksum, and locator. Counts must be finite, nonnegative, and exactly integer-valued. The collector rejects duplicate, reserved, escaping, or oversized artifact paths before downloading artifacts.

`assess-release` rechecks every indexed local artifact, the frozen configuration, the scientific source snapshot, the Modal runner, and the independent source-count audit. That audit must cover all samples and be bound to the exact artifact index. A stale receipt, changed file, incomplete sample audit, failed screen, or missing evidence cannot authorize release. The assessment policy's own source checksum is recorded separately, so an existing immutable run can be reassessed under a newer release policy.

The breast research admission policy adds coarse balanced author-label agreement ≥0.80 and unknown coarse labels ≤10% to the existing calibration screens. These are additional review screens, not independent accuracy measurements. The existing 70% compartment-retention, capture/chemistry, and seed-stability screens remain unchanged. A raw-droplet ambient assessment must actually be recorded for every sample; validation of a method on another dataset cannot turn an unassessed sample into a pass.

Admission also requires a reviewed, content-bound packet covering capture/chemistry, ambient RNA, annotation, doublets, and held-out donors. Its recipe and artifact-index checksums must match the run. Each report needs a reviewer, source, local relative path, and SHA-256. External evaluation must have at least three donors, all three clinical subtypes, no training/evaluation donor overlap, and a study separate from method calibration. These report fields are human attestations backed by source reports; the software does not authenticate reviewer identities or independently establish biological truth.

`promote` reruns assessment before any S3 writes. Only an admitted cohort receives `public/scrna/releases/<run_id>/release_manifest.json`. It binds the decision to matching, versioned S3 run/index controls and verifies the encrypted upload. A repeat with identical evidence is idempotent; different evidence cannot replace the same release. Production consumers must require this release manifest and verify its referenced artifact hashes. A calibration completion marker alone does not admit a cohort.

There is no clinical signoff, public API, new bucket, GPU service, private-data mount, or recurring monitoring job in this change. Monitoring is an explicit CLI operation. The ambient correction backend and general raw-droplet breast importer remain unimplemented; ingress continues to reject that unsupported role.

## Runbook

```sh
# Execute the pinned public recipe, then collect every indexed artifact.
PYTHONPATH=src modal run --timestamps scripts/modal/scrna_platform.py \
  --run-id breast-YYYYMMDDTHHMMSSZ --config manifests/scrna/breast/calibration.lock.json
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py status \
  --run-id breast-YYYYMMDDTHHMMSSZ
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py collect \
  --run-id breast-YYYYMMDDTHHMMSSZ
uv run --no-project --with numpy==1.26.4 --with pandas==2.2.3 --with scipy==1.15.2 \
  --with anndata==0.11.4 --python 3.11 python scripts/audit_scrna_breast_qc.py \
  --run-id breast-YYYYMMDDTHHMMSSZ
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py assess-release \
  --run-id breast-YYYYMMDDTHHMMSSZ
```

Assessment writes `results/scrna/validation/<run_id>/release_decision.json` and `release_review.html`. Exit 2 means quarantined, with explicit reasons. Missing or corrupt canonical artifacts produce an error. A future completed qualification packet is passed through `--evidence <packet.json>` to `assess-release` and `promote`; there is no override flag. Do not create successful attestations until the referenced work has been performed and reviewed.

```sh
uv run --no-project --with boto3==1.40.45 python scripts/scrna_platform.py promote \
  --run-id breast-YYYYMMDDTHHMMSSZ --evidence path/to/reviewed-packet.json
```

## Recipe 5 evidence

Run `breast-readiness-v5-20261001T220500Z` completed with 125 indexed artifacts, all downloaded and checksum-verified. The independent reader verified source-to-all-barcode and retained-cell counts, barcode/gene ordering, doublet exclusions, and uncalled malignancy for all three samples. Active barcode QC/doublet fields, UMAP/clusters, and marker tables match recipe 4 exactly. Recipe 5 adds a **diagnostic-only miQC 1.14.0 challenger**; it does not change filtering or select more favorable thresholds.

[miQC](https://github.com/greenelab/miQC/blob/main/vignettes/miQC.Rmd) jointly models detected genes and mitochondrial fraction with a two-component linear mixture. This run uses the published posterior cutoff 0.75 and two seeds, 42 and 43. The bridge sends only the two QC metrics and barcodes to R, not the expression matrix or author labels. It saves probabilities, both decisions, parameters, model objects, plots, package versions, and execution logs. Unidentifiable fits produce explicit no-calls; missing R/packages remain execution failures. No successful keep-all fallback is allowed.

| Sample | Active final singlets | miQC-only candidate kept | Agreement between miQC seeds |
| --- | ---: | ---: | ---: |
| CID44971, TNBC | 6,605 / 7,986 | 3,869 / 7,986 | 100% |
| CID3941, ER+ | 508 / 631 | 506 / 631 | 100% |
| CID3838, HER2+ | 2,066 / 2,353 | 2,055 / 2,353 | 100% |

The miQC column excludes neither additional low-count failures nor doublets; it is not a final singlet count. Repeatability does not establish correct quality calls. In TNBC, the challenger keeps only 542 / 1,629 published epithelial cells, 67 / 369 B cells, and 2,191 / 4,366 T/NK cells. Its model can separate biological populations in an already-filtered matrix without proving a damaged-cell population. It therefore remains review-only and supplies no basis to replace the active policy.

The deployed image preflight verifies Scanpy 1.11.1, scDblFinder 1.20.2, miQC 1.14.0, and access to the existing buckets. PBMC3k regression `pbmc3k-readiness-regression-20261001T220800Z` passes the original screens and exactly matches the prior barcode-QC, UMAP, marker, and cluster-score hashes. The focused suite has 48 passing tests and 12 passing subtests, covering denial, artifact tampering, stale audits, no-call persistence, compute bounds, and immutable promotion mechanics. Positive admission/promotion unit tests use fabricated controls and are explicitly not biological validation.

The real `promote` command exits 2 for the breast run. The release prefix is checked separately to confirm that no release manifest was created. See [the release review](../results/scrna/validation/breast-readiness-v5-20261001T220500Z/release_review.html) and [QC/miQC plots](../results/scrna/breast-readiness-v5-20261001T220500Z/review.html).

## Inputs and validation needed to admit this cohort

For CID44971, CID3941, and CID3838, obtain a per-library capture/channel map covering every original barcode, exact chemistry, reference identity, and source-backed treatment/timepoint metadata. A donor or `orig.ident` sample ID does not establish a capture. Obtain the matching unfiltered droplets and filtered cell counts with aligned gene identifiers and preserved channel suffixes. The author repository's [public Cell Ranger sample sheet](https://github.com/Swarbricklab-code/BrCa_cell_atlas/blob/main/cellranger_processing/config/sample_input_file.csv) is a template, not these patients' capture records. The authors distribute processed/filtered matrices publicly and describe raw sequencing as EGA data in their [data availability statement](https://github.com/Swarbricklab-code/BrCa_cell_atlas#data-availability).

Use [the three-sample intake table](../manifests/scrna/breast/readiness-intake.tsv) to supply locations and source custody. [The validation packet template](../manifests/scrna/breast/validation-packet.template.json) starts with every report unperformed; it asserts no approval and cannot pass admission as provided.

Those inputs enable a separately implemented and calibrated ambient lane preserving original and corrected counts. A validated tissue-aware QC policy must address epithelial and rare immune/stromal loss without training on the pilot's evaluation labels. A matched reference and external held-out cohort must support annotation and doublet evaluation. Until that work is complete, use this cohort for calibration/review, not cell-proportion inference or automatic downstream biological conclusions.

Rollback selects a previously admitted immutable release; it never edits historical run artifacts. There is presently no admitted breast release to roll back to. After a recipe or runtime change, rerun the frozen public controls, independent count audit, regression comparison, and release assessment before producing a new release manifest.
