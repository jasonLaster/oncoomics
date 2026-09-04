# Corrective TROP-2 Modal run

This Nextflow wrapper creates a durable NGS Analysis Workbench run for the
private Personalis ImmunoID TROP-2 bulk-RNA analysis while keeping the actual
large-file computation on Modal with read-only S3 input and private,
versioned, KMS-encrypted S3 output.

The selected method is intentionally narrow. It reruns FastQC/MultiQC and
focused `TACSTD2` BAM evidence, fixes the depth exclusion mask, applies an
explicit paired-read overlap policy, records flagstat for both BAM stages, and
separates raw FASTQ reads from pre-BQSR and post-`SplitNCigarReads` alignment
record spaces. It does not perform differential expression or infer surface
protein, ADC response, eligibility, or treatment benefit.

## Required parameters

- `repo_root`: absolute path to the local `diana-omics` checkout.
- `runner_path`: absolute path to `modal_s3_bulk_rna_trop2.py` within that
  checkout.
- `runner_sha256`: expected SHA-256 of the Modal runner.
- `helper_path`: absolute path to the local TROP-2 helper module.
- `helper_sha256`: expected SHA-256 of that helper module.
- `run_id`: new immutable Modal/S3 run identifier.
- `recover_existing_run`: set only for a Workbench retry when the Modal compute
  completed but bounded result transfer failed. This mode never reruns or
  overwrites the S3 computation.

The workflow performs the runner's two remote preflight checks before launching
the full computation. It refuses to launch if either source hash differs from
the approval-bound parameter file. A bounded review bundle is returned to
`<workbench_run_dir>/results/modal_result`; the complete immutable output stays
under the run-specific private S3 prefix.

## Runtime

The local controller requires Nextflow, Python, and an authenticated Modal CLI.
The Modal function uses its named AWS secret; credential values are never
placed in the workflow parameters, logs, repository, or Workbench registry.
