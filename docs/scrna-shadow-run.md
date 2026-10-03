# Public-data shadow run through the patient path

This rehearsal uses the exact public raw and filtered matrices in
`manifests/scrna/controls/sources.lock.json`. It executes the real `patient_research`
intake, private S3 custody, Modal QC, collection, independent source audit, and
default admission assessment. Source classification remains `public_control` in
the rehearsal manifest and reviewed metadata packets. It contains no Diana data.

The standard and LT breast libraries are separate technical captures from one
public sorted-cell donor. They are processed separately within one case. They do
not establish performance across independent donors or TNBC subtypes. The PBMC
sample is a separate technical control. Reference content fingerprints and
breast subtype/treatment remain unresolved. See the
[patient intake runbook](scrna-patient-intake.md) for actual private deliveries.

## Reproduce

Use a fresh UTC identifier each time. These commands assume the hash-locked public
matrices are cached in `data/raw/scrna/` and the local scRNA dependencies are
installed. The preparer verifies the complete public source set before creating
the delivery and refuses to replace an existing directory.

```sh
REHEARSAL=private/scrna/shadow-20261002T203500Z
BREAST_RUN=shadow-breast-20261002T203500Z
PBMC_RUN=shadow-pbmc-20261002T203500Z
.venv-scrna/bin/python scripts/prepare_scrna_shadow.py --destination "$REHEARSAL"
.venv-scrna/bin/python scripts/scrna_patient.py storage-check
for CASE in breast pbmc; do
  .venv-scrna/bin/python scripts/scrna_patient.py inventory \
    --delivery "$REHEARSAL/$CASE/delivery" --report "$REHEARSAL/$CASE/inventory.json"
  .venv-scrna/bin/python scripts/scrna_patient.py inspect \
    --contract "$REHEARSAL/$CASE/contract.json" --delivery "$REHEARSAL/$CASE/delivery" \
    --report "$REHEARSAL/$CASE/inspection.json"
  .venv-scrna/bin/python scripts/scrna_patient.py stage \
    --contract "$REHEARSAL/$CASE/contract.json" --delivery "$REHEARSAL/$CASE/delivery" \
    --report "$REHEARSAL/$CASE/stage_receipt.json"
done
.venv-scrna/bin/python scripts/scrna_patient.py run \
  --receipt "$REHEARSAL/breast/stage_receipt.json" --run-id "$BREAST_RUN"
.venv-scrna/bin/python scripts/scrna_patient.py run \
  --receipt "$REHEARSAL/pbmc/stage_receipt.json" --run-id "$PBMC_RUN"
```

After both runs report `complete_qc_provisional`, collect each into a new ignored
private directory, audit the source counts independently, then assess admission:

```sh
for CASE in breast pbmc; do
  if [ "$CASE" = breast ]; then RUN="$BREAST_RUN"; else RUN="$PBMC_RUN"; fi
  .venv-scrna/bin/python scripts/scrna_patient.py status --run-id "$RUN"
  .venv-scrna/bin/python scripts/scrna_patient.py collect \
    --run-id "$RUN" --destination "private/scrna/runs/$RUN"
  .venv-scrna/bin/python scripts/scrna_patient.py audit \
    --run-dir "private/scrna/runs/$RUN" --contract "$REHEARSAL/$CASE/contract.json" \
    --delivery "$REHEARSAL/$CASE/delivery" --report "$REHEARSAL/$CASE/source_audit.json"
  .venv-scrna/bin/python scripts/scrna_patient.py assess \
    --run-dir "private/scrna/runs/$RUN" --audit "$REHEARSAL/$CASE/source_audit.json" \
    --report "$REHEARSAL/$CASE/assessment.json"
done
```

Assessment exit code **2** is the expected `provisional_hold`: neither a method
qualification certificate nor a patient reviewer approval is fabricated. Inspect
the report; other failures must be investigated. Do not rerun into an occupied
run prefix. A fresh identifier preserves the failed attempt and source custody.

The review exporter verifies public provenance, the source delivery, complete run
artifacts, intake binding, and independent audits before exporting a small report:

```sh
.venv-scrna/bin/python scripts/review_scrna_shadow.py \
  --rehearsal "$REHEARSAL" --breast-run-id "$BREAST_RUN" --pbmc-run-id "$PBMC_RUN" \
  --destination results/scrna/validation/shadow-patient-qc-20261002T203500Z
```

The comparison baseline is recorded in `scripts/review_scrna_shadow.py`; its
canonical private run directories must also be available. Aliased identity
columns are excluded from equality comparisons. Numerical QC, selection, marker
outputs, and embeddings are compared exactly over shared columns. The LT
baseline predates the full-barcode marker review and method storage/runner
binding; it must not be reported as the same method identity.

The exporter also exercises seven read-only intake faults against the public
delivery. It rejects altered checksums, duplicate capture counts, and extra
identifying fields; blocks unresolved pooled captures and nuclei; and records
the explicit ambient gap for filtered-only intake. It changes no staged data.

## What to review

The report separates count integrity from QC screening and biological validity.
Every vendor barcode remains in the private checkpoint. Exclusive exclusion
counts avoid double counting overlapping low-gene, low-UMI, and MT flags.
Review-only per-cell marker hints show compartment losses, including unknown or
mixed expression. Those hints differ from retained cluster annotations and have
no independent truth labels or calibrated probabilities.

MT sensitivity tables are posthoc core eligibility counts. Newly eligible
barcodes have no doublet calls under the frozen policy. They are not rescued cells,
validated alternative thresholds, or a recommendation to relax filtering. SoupX
candidate corrections remain diagnostic; downstream analysis uses original counts.
Review failed retention and seed stability screens before interpreting proportions
or clusters. An epithelial marker hint does not establish malignancy.

This is a **post-count QC rehearsal**. It does not qualify upstream FASTQ counting,
cell calling, nuclei, integration, differential expression, or clinical use.

Completed evidence: [2026-10-02 shadow review](../results/scrna/validation/shadow-patient-qc-20261002T220301Z/README.md)
(superseding the [fixed-resolution run](../results/scrna/validation/shadow-patient-qc-20261002T203500Z/README.md)).

The earlier run's seed screen compared one seed pair at a fixed resolution of 0.5, where large
populations split arbitrarily (ARI 0.635 and 0.656; PBMC's 0.859 was a favorable pair). The
patient path now selects resolution by multi-seed reproducibility alone (see the
[intake runbook](scrna-patient-intake.md)). This rule was adopted after observing that failure,
so this rehearsal is development evidence, not independent qualification of it.

With barcode QC, doublet and selection outputs unchanged (exact match), seed stability is
0.885 for breast-standard (resolution 0.3) and 0.998 for PBMC (0.2). Breast LT still fails at
0.825 (best eligible resolution 1.0 on 440 cells). Both breast captures still fail retention
(62.3% and 64.0% versus 70%): about a quarter of breast-standard vendor barcodes exceed 70%
mitochondrial counts with a median of 285 genes, a damaged-cell mode rather than over-filtering.
That is a sample-quality finding, and composition from these captures is biased (fibroblast and
unknown/mixed losses). PBMC passes every QC screen. All cases remain held for independent method
qualification and human review. Do not relax the screens or tune parameters to turn the
rehearsal into a pass.
