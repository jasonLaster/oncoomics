# Metadata-held breast matrix diagnostics

Use this lane when vendor 10x gene-expression matrices have frozen input receipts,
but specimen identity, cells versus nuclei, loading or complete-capture scope still
needs review. It preserves every vendor-called barcode and the original sparse
integer counts. It does not change the patient intake or production admission gates.
Publicly accessible patient files remain `patient_research`.

The pinned Modal worker runs per-library scDblFinder diagnostics, raw-to-filtered
lineage verification, SoupX as a challenger, conditional whole-cell QC flags,
three-seed clustering, UMAP, conservative breast marker hints and descriptive gene
panels. `clinical_ready`, `production_ready` remain false and `metadata_hold` stays
true. Neither doublet flags nor mitochondrial thresholds exclude cells. Unknown
marker hints stay unknown; epithelial hints and vendor labels do not establish
malignancy. No library integration or biological replicate assumption is made.

For `chemistry: "10x_3prime_v4"`, the worker additionally runs scDblFinder with
`dbr.per1k=0.004` and a rate-free `dbr.sd=1` challenger. These are diagnostics;
loading and complete-capture metadata still require qualification. The rate-free
setting removes the expected-rate constraint and does not validate the calls.
See [10x GEM-X documentation](https://www.10xgenomics.com/blog/the-next-generation-of-single-cell-rna-seq-an-introduction-to-gem-x-technology)
and the [scDblFinder vignette](https://www.bioconductor.org/packages/release/bioc/vignettes/scDblFinder/inst/doc/scDblFinder.html).

## Run contract

Keep the plan and outputs under ignored `private/`. The JSON plan requires:

- `schema_version: 1`, a unique `run_id` and the matching
  `private/scrna/runs/<run_id>/` output prefix.
- Explicit `evidence_lane: "patient_research"` or `"public_control"`,
  `metadata_hold: true` and `clinical_ready: false`.
- One to four libraries, each with a unique `library_id`, `expected_cells`
  between 100 and 100000, and optional `chemistry: "10x_3prime_v4"`.
- Exactly one `raw_h5` and one `filtered_h5` per library. Each input carries
  `bucket`, `key`, durable non-null `version_id`, full `sha256`, `size_bytes`
  and a unique basename `local_name`. Use the frozen private delivery receipts.
  The supported H5 matrices contain gene-expression features only.

```bash
export SCRNA_EXPLORATORY_PLAN="$PWD/private/example/plan.json"
uv run --no-project --python 3.11 --with modal==1.5.2 --with boto3==1.40.45 \
  python -m modal run --detach scripts/modal/scrna_exploratory.py
```

Compute is bounded to one 8-CPU, 64-GiB container, no GPU, and a two-hour timeout.
The local operator claims the run namespace with a create-only write. The worker
receives expiring exact-version GET capabilities and one KMS-constrained output
POST policy through an ephemeral Modal Secret. No account credentials or signed
URLs appear in plans or result manifests. Each completed library is uploaded
before starting the next. The final artifact index and returned S3 versions are
bound by a manifest written last. Source modules, Python packages and R session
information are retained with outputs; these version receipts are not an immutable
digest lock of every transitive container dependency.

Collect with `diana_omics.scrna_private.collect_private(s3, run_id, destination)`.
It reads the index and every artifact at the versions in the completion manifest,
verifies full bytes and SHA-256, and checks private storage and KMS controls.
Use an empty destination and archive the resulting manifest version separately.

## Independent numerical review

`audit_exploratory_counts(library, original_filtered_h5, library_output)` in
`diana_omics.scrna_exploratory_audit` independently checks the vendor H5 against
the H5AD sparse arrays, barcode order and stable gene IDs. It reproduces every
barcode's counts, genes and mitochondrial percentage; every requested target UMI;
the complete group/target inventory; and detection, pseudobulk CPM and log-CP10k
summaries. It also checks no cells were excluded and the metadata hold remains.
Mechanical integrity is separate from biological qualification.

`scrna_cross_assay.summarize_targets` adds separate original-count and SoupX
candidate views by supplied compartment and doublet labels. It requires exact
ordered barcode correspondence and uses totals from the same layer. Groups below
100 barcodes retain counts but receive no abundance fractions or ranks. Stable
Ensembl IDs, with only version suffixes removed, are the cross-assay join keys;
ambiguous symbols need explicit review. Summarize libraries independently: shared
barcode strings never prove a shared physical cell.

Bulk TPM, single-cell UMI CPM and protein amount are different measurements. Do
not divide them to infer protein translation, surface accessibility or response.
Descriptive RNA panels are not pathway activity, flux, HRD or cohort percentiles.
Specimen matching, breast-specific annotation, malignant-cell validation, ambient
method selection, capture-aware doublet qualification and independent biological
review remain required before any production or clinical interpretation.

## EVEE allele cross-check

`variant_read_audit.audit_bam` accepts a bounded panel of 1–100 complete,
one-based GRCh38 SNVs and a reference contig-length dictionary. It reports three
fixed mapping/base-quality/end-distance policies, excludes duplicate and nonprimary
alignments and QC failures, collapses overlapping mates by read group/query name,
and removes discordant fragments. Verify reference alleles against the locked
FASTA before calling it; contig lengths alone do not prove reference identity.
Remote BAMs need exact-version capabilities and a hash-verified local BAI.

Pair results with `evidence_state`. States are diagnostic triage, never a caller's
`PASS`: the default depth floor is 20 fragments in each sample, with at least three
tumor alternate fragments and no normal alternate fragments for tumor-enriched
support. Low coverage stays unresolved. Zero alternate reads have an explicitly
depth-limited upper bound; they do not disprove a low-frequency clone. Purity,
allelic copy number, mapping artifacts, sequencing errors, complete somatic calls
and specimen matching remain separate gates. Model pathogenicity, functional
direction, pathway state, dependency and drug evidence must remain separate.
