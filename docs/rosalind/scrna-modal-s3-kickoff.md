# Rosalind scRNA-seq Modal + S3 Kickoff

This is the executable first rung of the Rosalind single-cell workbench path. It uses a small public 10x PBMC3k count matrix to prove S3 custody, Modal authentication, a read-only input mount, a write-enabled results mount, Scanpy execution, and checksummed reviewer artifacts before any Diana-derived single-cell data are introduced.

## Storage and credential boundary

- Public input: `s3://diana-omics-raw-inputs-172630973301-us-east-1/public/10x/pbmc3k/`
- Results: `s3://diana-omics-results-172630973301-us-east-1/modal/rosalind-scrna/runs/<run_id>/`
- Modal profile: the locally authenticated profile; API tokens stay in `~/.modal.toml`.
- AWS access inside Modal: `modal.Secret.from_name("onco-omics-use1")`; AWS keys are never copied into the repo or command line.
- The raw S3 mount is read-only and restricted to the public PBMC3k prefix.

The checked-in source record is [the kickoff manifest](../../manifests/rosalind_scrna_kickoff.csv). Its SHA-256 is verified inside Modal before extraction.

## Stage the public fixture

Download the official 10x fixture to a temporary directory, verify it, and upload it with server-side encryption and SHA-256 metadata:

```sh
shasum -a 256 /tmp/<download-dir>/pbmc3k_filtered_gene_bc_matrices.tar.gz

aws s3 cp \
  /tmp/<download-dir>/pbmc3k_filtered_gene_bc_matrices.tar.gz \
  s3://diana-omics-raw-inputs-172630973301-us-east-1/public/10x/pbmc3k/pbmc3k_filtered_gene_bc_matrices.tar.gz \
  --region us-east-1 \
  --sse AES256 \
  --metadata sha256=847d6ebd9a1ec9a768f2be7e40ca42cbfe75ebeb6d76a4c24167041699dc28b5
```

## Run

```sh
modal run scripts/modal/modal_s3_scrna_kickoff.py \
  --run-id pbmc3k-<UTC timestamp>
```

Defaults can be changed without editing the runner:

```text
MODAL_AWS_SECRET_NAME
ROSALIND_SCRNA_RAW_BUCKET
ROSALIND_SCRNA_RAW_PREFIX
ROSALIND_SCRNA_RESULTS_BUCKET
ROSALIND_SCRNA_RESULTS_PREFIX
```

The runner refuses to overwrite a run prefix. Use a new immutable run ID for every iteration.

HDF5 and other analysis artifacts are created on Modal's local ephemeral filesystem, then copied sequentially to S3. This avoids random-access HDF5 writes against the object-store mount. `run_manifest.json` is uploaded last and is the completion marker for a run prefix.

## Output contract

```text
run_manifest.json
input_evidence_index.json
artifact_index.json
scrna_qc_summary.csv
cell_qc.csv
cluster_summary.csv
marker_genes.csv
umap_leiden.png
pbmc3k_processed.h5ad
summary.md
```

`run_manifest.json` records the input SHA-256, package versions, thresholds, random seed, compute shape, output S3 prefix, and the evidence boundary. `artifact_index.json` records bytes and SHA-256 for every analysis artifact. Cell-type annotations intentionally remain `unreviewed`; the first Rosalind review should inspect the UMAP and ranked markers before assigning labels.

## Real-cohort handoff

The current Diana raw bucket contains FASTQ and BAM material but no 10x matrix, H5, or H5AD single-cell input. Do not point this public-fixture runner at those FASTQs. The next cohort-specific rung should begin only after confirming:

1. single-cell assay and chemistry;
2. count-matrix versus FASTQ input;
3. sample sheet and patient/lesion matching;
4. genome/reference and feature definitions;
5. cloud-processing authorization for the exact human-data prefix;
6. doublet, ambient-RNA, batch, and malignant-cell annotation policies.

For count matrices, extend the input adapter while retaining the same manifests and result contract. For raw single-cell FASTQs, add a separate STARsolo, Cell Ranger, or nf-core/scrnaseq count-generation rung rather than treating generic FASTQs as single-cell data.

## Evidence boundary

This kickoff is a public workflow demonstration. It is not Diana sample evidence, does not identify malignant cells, does not prove surface protein abundance, and cannot support treatment selection.

## Executed kickoff

Run `pbmc3k-20260903T213200Z` completed on 2026-09-03. It retained 2,638 of 2,700 cells, selected 1,826 highly variable genes, and produced six unreviewed Leiden clusters. The result prefix contains ten AES-256-encrypted, versioned objects; all eight analysis-artifact hashes matched the downloaded artifact index, and the H5AD and UMAP passed format and visual checks.

The exact input/output VersionIds, hashes, run URL, validation checks, and two zero-output failed attempts are recorded in the [kickoff receipt](../../results/rosalind_scrna/pbmc3k/pbmc3k-20260903T213200Z/kickoff_receipt.json).

The [Workbench handoff](../../results/rosalind_scrna/pbmc3k/pbmc3k-20260903T213200Z/workbench_handoff.md) provides the exact S3 prefix, manifest hash, review order, and starter question for provisional immune-cell annotation.
