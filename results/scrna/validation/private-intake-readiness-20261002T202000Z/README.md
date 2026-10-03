# Single-cell private intake readiness evidence

This is a curated export of **public controls and synthetic engineering tests**, not a complete patient run or a method qualification certificate. No Diana data were processed. Canonical run artifacts remain in versioned private S3; the copied artifact indexes describe those full runs. This export includes only selected public summaries, audit/assessment receipts, environment controls and plots. Do not run patient admission against this partial export.

Open `review.html` for the readiness review and `docs/scrna-patient-intake.md` from the repository root for arrival operations. `readiness.json` records the tested runs. All three public controls remain `provisional_hold`; the two breast libraries share one sorted IDC donor and have unknown clinical subtype. The earlier GSE176078 cohort remains quarantined.

The synthetic counter's initial test exposed STARsolo 2.7.11b TopCells' zero-based threshold rank and tie inclusion. The synthetic-only recipe now uses rank N-1; the fixed final run matches every expected count. Human counting uses EmptyDrops_CR and remains unqualified. A public breast run also failed during upload; its failed/partial prefix was retained, and recovery completed under a new ID with bounded transfer retries. No failed or partial run was used for the final count-preservation claim.

The PBMC3k regression exactly matches the earlier QC CSV, UMAP CSV, markers, cluster marker scores and reference overlap. Source changes and frozen environments are retained in the canonical run indexes. Test validation: 106 tests and 12 subtests passed, Ruff passed, and source bytecode compilation passed. One duplicate-symbol warning is expected in the checkpoint round-trip regression fixture.

Mechanical count equality, fitted ambient candidates and successful execution do not validate biological cell selection, annotation, doublet accuracy, malignant-cell calling or clinical use. Those gaps, failed breast screens, missing reference fingerprints and required human review are preserved in the assessments.
