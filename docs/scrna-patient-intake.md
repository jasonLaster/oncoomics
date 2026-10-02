# Diana single-cell arrival runbook

The private intake and provisional analysis path is implemented on S3 and Modal. It preserves source bytes and original counts, validates a complete technical capture, and collects every result against versioned checksums. **This establishes operational custody and reproducibility, not breast/TNBC biological accuracy or clinical readiness.** The public breast controls still expose substantial QC losses and unstable clustering. A completed Modal run is not an admitted result.

See the [2 October readiness review](../results/scrna/validation/private-intake-readiness-20261002T202000Z/review.html) for the public-control audits, synthetic known-answer counter and unchanged PBMC regression.

## Before the delivery

Use the managed `scrna-breast-qc` checkout. Keep the delivery, identifiers, vendor documents, contracts, receipts and reports in its ignored `private/scrna/` directory, or an access-controlled external directory. `private/` is excluded from Git. The CLI uses owner-only permissions and refuses patient reports in tracked repository folders. The workstation, backups and filesystem still need appropriate operator access controls; Git ignores and Unix modes do not establish institutional privacy compliance.

Patient files go only to the existing private bucket `diana-omics-private-results-172630973301-us-east-1`, under `private/scrna/`. Every stage/run checks all four S3 public access blocks, nonpublic bucket policy, enabled versioning and the pinned KMS key. **Do not use the intentionally public raw inbox or the public calibration worker for Diana's delivery.** No patient data were used in readiness testing.

Obtain the vendor delivery manifest, file checksums if available, run/chemistry details, reference manifest, sample identity and clinical/sample context. Assign opaque case/specimen/capture aliases; keep the identifying crosswalk separately. A capture is a physical droplet capture, not a donor, lane, chunk or arbitrary split. A capture can have several paired FASTQ chunks. Do not split a capture before doublet calling or combine captures into one matrix.

Supported provisional post-count inputs are modern 10x HDF5 or explicitly declared MEX raw integer UMI matrices, with stable gene IDs, human gene symbols including `MT-` genes, and preserved channel suffixes. Whole-cell standalone 10x GEX has a provisional post-count profile; chemistry-specific biological qualification remains outstanding. Count generation supports 3prime v2, v3, v3.1 and LT v3.1 layouts. Unknown chemistry/material/reference, nuclei, pooled donors, Flex/FFPE, spatial, multiome and 5prime/v4 counting require separate recipes; do not relabel them to fit this one. A filtered-only matrix can run provisional QC, but ambient assessment and research admission remain blocked.

The current compute envelope is 4 CPU / 16 GiB / 1 hour for post-count QC and 8 CPU / 64 GiB / 2 hours for reference-locked counting; one container per function. Matrix intake limits are 100,000 features, 7 million raw barcodes, 250 million nonzeros and 100–100,000 declared filtered cells. These are rejection bounds, not validated performance guarantees for every input at the limits. Reference assets must be unpacked FASTA/GTF plus the exact chemistry whitelist; the index is rebuilt with STAR 2.7.11b. Large or unusual deliveries need a reviewed resource plan before execution.

## Local intake

Use Python 3.11. Set up an isolated local tool environment once:

```bash
uv venv --python 3.11 .venv-scrna
uv pip install --python .venv-scrna/bin/python -e '.[scrna-qc-test]'
mkdir -p private/scrna/arrival
chmod 700 private private/scrna private/scrna/arrival
.venv-scrna/bin/python scripts/scrna_patient.py storage-check
.venv-scrna/bin/python scripts/scrna_patient.py inventory \
  --delivery private/scrna/arrival/delivery --report private/scrna/arrival/inventory.json
```

Copy `manifests/scrna/patient/intake.template.json` to `private/scrna/arrival/contract.json` and fill every role, byte size, SHA-256 and alias from the source inventory and vendor manifest. Local SHA-256 establishes byte identity; it does not authenticate the vendor or sample. Compare vendor checksums independently when supplied. Use `expected_cells` from the vendor count report for matrices, not a convenient target. For FASTQs it is the declared cell-loading expectation for the caller.

The metadata-review template must be completed from source documents. It binds capture/specimen, assay, chemistry, reference, species, tissue, material and pooling status. Hash the completed packet, and put that hash/path in the intake contract. Its `reviewer`, `source`, `source_sha256` and `complete_capture` fields are operator attestations; this software does not authenticate the reviewer or fetch and authenticate the source document. Preserve that source locally and verify identity and capture completeness independently. An unresolved packet permits custody inspection but blocks QC.

For matrices, the reference fingerprint may be `unknown` during provisional QC; it blocks qualification. For FASTQs it must equal `digest_json(reference_lock)` from `diana_omics.scrna_private`, not the pretty-printed file hash. The reference-lock template binds the exact FASTA, GTF, whitelist, chemistry, STAR version and reference ID. For a human run use `reference_class: human_grch38`; synthetic references are rejected in the patient lane. Verify that the reference matches the vendor/library preparation. No reference has been selected for Diana without her delivery metadata.

```bash
.venv-scrna/bin/python scripts/scrna_patient.py inspect \
  --contract private/scrna/arrival/contract.json --delivery private/scrna/arrival/delivery \
  --report private/scrna/arrival/inspection.json
```

Inspection checks every file hash/size, metadata packet, feature and barcode identity, integer counts, and exact raw-to-filtered lineage. Ambient support requires at least 100 noncell droplets with 1–99 UMIs. FASTQ inspection samples the first 10,000 records per chunk for layout/mate checks; the actual counter validates every record, gzip stream and mate identity before STAR. Exit 2 means the bytes can be inventoried but this analysis path is blocked. Exit 1 means invalid input or an execution error; inspect the protected report. Nothing should be silently repaired or coerced into an assay type.

## Private execution and collection

For compatible matrices:

```bash
.venv-scrna/bin/python scripts/scrna_patient.py stage \
  --contract private/scrna/arrival/contract.json --delivery private/scrna/arrival/delivery \
  --report private/scrna/arrival/stage_receipt.json
.venv-scrna/bin/python scripts/scrna_patient.py run \
  --receipt private/scrna/arrival/stage_receipt.json --run-id arrival-qc-YYYYMMDDTHHMMSSZ
.venv-scrna/bin/python scripts/scrna_patient.py status --run-id arrival-qc-YYYYMMDDTHHMMSSZ
.venv-scrna/bin/python scripts/scrna_patient.py collect \
  --run-id arrival-qc-YYYYMMDDTHHMMSSZ --destination private/scrna/runs/arrival-qc-YYYYMMDDTHHMMSSZ
.venv-scrna/bin/python scripts/scrna_patient.py audit \
  --run-dir private/scrna/runs/arrival-qc-YYYYMMDDTHHMMSSZ \
  --contract private/scrna/arrival/contract.json --delivery private/scrna/arrival/delivery \
  --report private/scrna/arrival/source_audit.json
.venv-scrna/bin/python scripts/scrna_patient.py assess \
  --run-dir private/scrna/runs/arrival-qc-YYYYMMDDTHHMMSSZ --audit private/scrna/arrival/source_audit.json \
  --report private/scrna/arrival/decision.json
```

The local CLI starts an on-demand pinned Modal app with expiring exact-version input GETs and output POSTs limited to this run prefix, KMS key and object size. No account AWS credentials or private bucket mount go into the worker. Signed capabilities are bearer secrets; they travel as ephemeral Modal secrets and must never be printed, saved, pasted into browser tabs or added to logs. They expire after 2 hours for QC and 3 hours for counting. Check the storage guard and exact output versions again at collection. Institutional/vendor authorization for the chosen cloud processors and retention policy must be established before an actual patient transfer; the storage canary is not evidence of those agreements.

Source staging uses atomic nonreplacement uploads and verifies the actual returned version bytes. `_STARTED.json` claims the run locally before remote processing. Worker POSTs are versioned, **not** server-enforced write-once; retries may create additional versions. The completion manifest pins the selected version of every artifact and is written last. Do not consume partial prefixes. Running, complete count/QC, failed, inconsistent, stale and absent states are distinct. Investigate a failed/stale run, preserve its evidence, and retry under a fresh ID. An expired token or denied request fails; there is no broad-credential fallback. Downloads resume exact pinned bytes on transient interruption; uploads retry at most three times.

The independent audit rereads the original source using a different reader and verifies every vendor barcode, raw integer counts, retained subsets, QC decisions and correction monotonicity. This audit proves count preservation, not that the selected cells or annotations are biologically correct. A failed collection has no local completion controls and must be recollected into a fresh directory.

## FASTQ route and handoff

Before staging, run `count-plan` with `--contract`, `--delivery`, `--reference-lock`, `--reference-root` and `--report`. For staging, add both `--reference-lock private/scrna/arrival/reference_lock.json` and `--reference-root private/scrna/arrival/reference-assets` to the `stage` command above. `run` then selects the counter using that stage receipt; use a distinct `arrival-count-...` run ID. Collect the complete count run before the next step.

```bash
.venv-scrna/bin/python scripts/scrna_patient.py prepare-counted \
  --count-run-dir private/scrna/runs/arrival-count-YYYYMMDDTHHMMSSZ \
  --source-contract private/scrna/arrival/contract.json --source-delivery private/scrna/arrival/delivery \
  --destination private/scrna/arrival/counted --report private/scrna/arrival/count_handoff.json
```

This verifies all count artifacts and their reference/intake binding, copies canonical MEX matrices, derives the called barcode count, and embeds count provenance in a separate matrix contract. That derived count is descriptive, not independent vendor truth. Inspect/stage/run/audit the new `counted/contract.json` and `counted/` delivery under a fresh QC run ID. There is no automatic chain from FASTQs to an admitted result. The upstream STAR cell caller is explicitly unqualified for patient use; the derived contract retains that flag, and patient assessment continues to hold it even with a post-count certificate. Counting qualification needs a separate implementation/evidence gate before those outputs can be admitted.

## What can be trusted now

Original input bytes, versioned provenance, barcode/feature mappings and persisted raw count equality can be checked mechanically. SoupX 1.6.2 fits a diagnostic challenger from raw noncell droplets and preliminary original-count clusters; an unidentifiable fit yields a no-call. Original `X` is unchanged. Candidate integer counts live in `soupx_counts_candidate`; they never enter the analysis automatically. scDblFinder runs on each declared capture after core QC, with no fallback. Stress, cycling, hemoglobin and ribosomal flags are review-only. miQC is disabled in the private path.

Open the private `review.html` locally. Review `all_cells_qc.h5ad`/CSV (including exclusions), `provisional_compartment_losses.csv`, thresholds, seed stability, scDblFinder calls and ambient fit/session logs. Coarse hints and their margins are uncalibrated. The loss table includes unknown/mixed cells even when marker coverage is insufficient. Hints do not change filtering; epithelial expression does not establish malignancy. Preserve the full checkpoint before drawing any composition conclusion. No integration, patient-level differential expression or clinical treatment inference is provided.

`assess` defaults to `provisional_hold`. Method qualification and patient review are separate. A method certificate requires an independently approved SHA-256, exact method/environment binding, a narrow tissue/chemistry/reference/subtype scope, expiry and reviewed content-bound reports covering held-out validation, compartment loss, ambient RNA, doublets and annotation. External method evaluation requires at least three donors and a separate study without training overlap. That is **method evidence**, not a requirement that Diana have published cell labels, multiple subtypes or three specimens. Qualification limited to TNBC can remain TNBC-only.

Per-case admission requires the source audit, passing QC screens, an identifiable raw-droplet ambient assessment and a human review of identity, capture metadata, losses, ambient findings and annotation uncertainty bound to the exact artifact index/method. Templates start unperformed; never fill successful attestations until the work is reviewed. The tool does not authenticate reviewers or biologically validate an attestation. There is no clinical admission or private-to-public promotion command. A `reviewed_research` result still makes only the narrow post-count research claim.

For Diana's arrival, first establish delivery identity/chemistry/material and the matched reference, then run this as a **shadow analysis**. The breast controls' failed retention/stability screens and missing independently qualified annotation/doublet/cell-calling evidence remain open scientific work. Clinical reliance needs its own accredited/validated workflow and responsible clinical review.
