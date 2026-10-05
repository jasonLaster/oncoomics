# step19-qc / m2_labels: how to reproduce

Results are in `report.md`. Run date: 2026-10-05.

## Work directory

- Scratch (`$W`): `/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/f61c14bf-e23e-4829-a09a-24be63d09400/scratchpad/m2/`
- It holds sparse local copies of the BAM leaf chunks, per-molecule tables and presigned URLs.
- It contains patient reads. Delete it when no longer needed.

## Environment and versions

- **Python:** 3.11 via `uv run --no-project --python 3.11 --with ...`.
- **Python packages:** pandas 2.2.3, numpy 2.1.3, scipy 1.14.1, pysam 0.22.1, h5py 3.12.1, matplotlib 3.9.2.
- **Command-line tools:** samtools 1.23.1, bcftools 1.23.1 (Homebrew), AWS CLI (presign only).
- **Compute:** local only, no cloud jobs.

Shorthand used below:

    PY="uv run --no-project --python 3.11 --with pandas==2.2.3 --with numpy==2.1.3 --with scipy==1.14.1"

## Inputs (sha256)

| file | sha256 |
|---|---|
| step8-wgs-somatic/results/final/consensus_pass.vcf.gz | 471897211dee7d94f25067c58417567da9d3477df851c9c55f722315f1e36bba |
| step5-ascn/segments_fit_S1b_p0.35_ploidy2.80.standardized.tsv | a6ae7c78b56b75c7121cbc9a5815b8806afc43fe2235dd95dea6fc88ceef4d06 |
| step7-provenance/results/reconciled_table.tsv | a53fe89c97504788c701c0baa4a88c598726fdca7d71044bdec4e11d6c7b3ead |
| step19-qc/candidate_genes.tsv | 4f005f9334ada63bb204021d217dc327b0d9e93f71388ce204025e215adade36 |
| step6-scrna-malignant/barcode_annotations_KH022-1.csv.gz | 9ee8f336d9691e558abb721b75460e9e289e3f21032300c7ace69ad8b892e073 |
| step6-scrna-malignant/barcode_annotations_KH022-1-1.csv.gz | ae9222598c047145db672f3851dc21ce547501f519547f52a476516f05d6e819 |
| scratchpad/step15/g23.gtf.gz (GENCODE v23) | 5d40060eab5fea553ddb17bcd20b7506b98c9332603509bd064e1075c17a13dc |
| step2b/data/KH022-1/sample_alignments.bam.bai | 9044c00ac84ba9141f30585c4be1ac349b2e9107eb189265f73133da4db15761 |
| step2b/data/KH022-1-1/sample_alignments.bam.bai | dc5c962f5e9b86eaaf82a34da04f93cb429315d44bf0b85ab5c91b5971c5a336 |

- **Matrices:** `step2b/data/<lib>/{filtered,raw}_feature_bc_matrix.h5`, from the previous session's scratchpad.
- **Remote BAMs:** `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-10-02-scrna-seq-kh022/data/signios/1012026/<lib>/per_sample_outs/<lib>/sample_alignments.bam`.
- **Leaf-loss check:** step 6's local subsets `step6/bam/<lib>.chr{9,13,17}.bam`.

## Steps (run from `scripts/`)

| # | command | what it does | runtime |
|---|---|---|---|
| 1 | `$PY python 01_sites.py` | consensus SNVs -> gene-body truth set (8,065) plus the 12 step-7 subclone sites; CN, multiplicity, clonal/subclonal call. Writes `$W/sites.tsv`, `$W/sites.bed`, `tables/sites_truthset.tsv`. | ~20 s |
| 2a | presign both BAMs (`aws s3 presign --region us-east-1 --expires-in 21600`) into `$W/urls.json` | | |
| 2b | `02_fetch.sh <lib>` through `range_counting_proxy.py` (step 7's byte-counting proxy) | **aborted**; kept for the record. `samtools view -M -L` starts each region at the linear-index minimum offset, which long spliced reads drag far upstream, so it read the BAM nearly sequentially: 0.12 GB for ~25 sites. | – |
| 2c | `uv run ... --with pysam==0.22.1 python 02_fetch_leaf.py <lib>` | Leaf-bin fetch (details below). | ~40-50 min per library, wall clock; dominated by ~16k small tail requests |
| 3 | `$PY --with pysam==0.22.1 python 03_count.py <lib>` | UMI-level ref/alt per (CB, UB, site), all barcodes. Writes `$W/mol_<lib>.tsv.gz`. | ~15 s |
| 3b | `$PY --with h5py==3.12.1 python 03b_barcodes.py` | per-barcode UMI totals from the raw matrices (for empty droplets). | ~1 min |
| 4 | `$PY --with pysam==0.22.1 python 04_leaf_loss.py` | leaf-only vs all-reads molecule counts on step 6's complete chr9/13/17 subsets. Writes `tables/leaf_loss.csv`. | ~30 s |
| 5 | `$PY python 05_labels.py` | site filters, ambient model, s calibration, pi per group, precision/recall, confusion table. | ~4 min |
| 5b | `RHO_SCALE=0.5 TAG=_rho0.5 $PY python 05_labels.py` and `RHO_SCALE=2 TAG=_rho2 ...` | ambient sensitivity runs. | ~6 min each |
| 6 | `$PY python 06_clonality.py` | presence scale k by site class. Writes `tables/clonality_*`, `subclone_sites_detail.csv`. | ~1 min |
| 7 | `$PY --with h5py==3.12.1 python 07_sensitivity.py` | candidate log2FC under label schemes a-d2. Writes `tables/candidate_sensitivity*.csv`. | ~2 min |
| 8 | `uv run ... --with matplotlib==3.9.2 python 08_figures.py` | `figures/fig1-4*.png`. | ~10 s |

**Step 2c details (leaf-bin fetch).**
- For each 16-kb window holding a site, it downloads only the BAI leaf-bin chunks, plus the BGZF block at each chunk's
  end, using exact closed HTTP Range requests over keep-alive connections.
- The chunks are written at their true offsets into a sparse local file the size of the remote BAM, together with the
  header MiB and the EOF block.
- It writes a reduced `.bai` containing only those leaf bins, with the linear index zeroed.
- It verifies that each chunk's first record lies in its window: 0 bad of 7,734 (L1) and 0 bad of 7,370 (L2).
- It is resumable: chunks already present (BGZF magic at the offset) are skipped.
- Bytes are logged to `$W/bytes_leaf_<lib>.ledger.json`.

## Bytes transferred from S3

| item | bytes |
|---|---:|
| aborted samtools -M -L attempt (KH022-1, counted by proxy) | 120,520,732 |
| KH022-1 leaf fetch, run 1 (killed at the 30-min background limit; on-disk allocation of the sparse file, an upper-bound proxy) | 1,722,077,184 |
| KH022-1 leaf fetch, run 2 (resume; counted response bodies) | 32,820,166 |
| KH022-1-1 leaf fetch, run 1 (stopped to switch to keep-alive; on-disk allocation) | 806,215,680 |
| KH022-1-1 leaf fetch, run 2 (resume; counted) | 845,984,442 |
| **total** | **~3.53 GB** (cap 5 GB) |

- Run-1 response bodies that were in flight when a process was killed (at most 24 concurrent, each <= a few MB) are not
  in the on-disk figure. Allow up to about 0.05 GB for them.
- No whole BAM was downloaded. Nothing was uploaded. No git operations.

## Notes

- `05_labels.py` takes `RHO_SCALE` (ambient multiplier), `TAG` (output suffix) and `FSCALE` (fix s instead of fitting
  it) from the environment.
- `07_sensitivity.py` reads `$W/nuclei.tsv.gz` from step 5. A copy is in `tables/nuclei_genotype.tsv.gz`.
- Random seed: `numpy.random.default_rng(20261005)`, used for the bootstraps.
