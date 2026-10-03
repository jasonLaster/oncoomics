# Public-data patient-path shadow run

Public controls only; no Diana data. Clinical readiness: no. All unresolved outputs remain on provisional hold.

Two sorted breast libraries represent one public donor. Subtype, treatment, and reference content fingerprint remain unknown. PBMC is a technical control. This is post-count QC, not a FASTQ-to-count validation.

| Control | Input | Retained | Retention | Seed ARI | Failed QC screens |
|---|---:|---:|---:|---:|---|
| breast-standard | 5680 | 3536 | 62.3% | 0.635 | retention, seed_stability |
| breast-lt | 687 | 440 | 64.0% | 0.656 | retention, seed_stability |
| pbmc1k | 1222 | 1012 | 82.8% | 0.859 | none |

All source-to-checkpoint audits pass ten checks per capture. All shared non-alias QC, selection, marker, and UMAP columns match the earlier runs exactly. Method identity equality is recorded separately; LT's baseline predates added review and custody fields.

Seven read-only intake fault scenarios behaved as expected: changed count/metadata checksums, duplicate capture counts, and an extra identifying field were rejected; unresolved pooled capture and nuclei were blocked; filtered-only intake retained an explicit ambient assessment gap.

SoupX estimates at the 1% lower boundary of the published [1.6.2 default range](https://cran.r-project.org/src/contrib/SoupX_1.6.2.tar.gz) are flagged for review in the evidence JSON. They do not establish that true contamination is 1% or absent. The wrapper does not override the range; corrections remain diagnostic and unused.

The report records exclusion overlaps and a diagnostic MT sensitivity table. Changing thresholds would require a new analysis; newly eligible cells have no doublet calls.

Canonical complete outputs are in private/scrna/runs/<run_id> and versioned KMS-encrypted private S3. This directory is a small, explicitly public-source review export; it is not a complete run or method qualification certificate.

Before interpreting Diana's cell composition, review excluded barcodes and compartment losses, ambient diagnostics, doublets, unstable clusters, and unknown annotations with the sample metadata. Preserve the intake/qualification holds until the independent evidence and reviewer sign-off are available.

See [review.html](review.html) and [shadow_review.json](shadow_review.json) for provenance, method identities, canonical artifact manifests, audit checks, and default assessment decisions.
