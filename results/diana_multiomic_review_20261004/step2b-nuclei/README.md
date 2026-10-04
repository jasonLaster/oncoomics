# step2b-nuclei: how this was produced (private, git-ignored)

Read-only work. No repo source edits, no git operations, S3 used read-only. Scratch directory:
`/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step2b/`.
Inputs and the presigned URLs live only in scratch; URLs are never written here.

## Versions
- Tools: samtools/htslib 1.23.1 (libcurl), aws-cli 2.34.63.
- Python 3.11.15 via `uv run --no-project`, with pysam 0.24.1, h5py 3.16.0, numpy 2.4.6, pandas 2.3.3, scipy 1.17.1,
  matplotlib 3.11.2, diptest 0.11.0 and pypdf 6.19.0.
- Vendor data: Cell Ranger 10.1.0, GEM-X 3' v4, refdata-gex-GRCh38-2024-A, introns included.

## Inputs
- **S3 inputs.** Prefix: `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-10-02-scrna-seq-kh022/data/signios/1012026/`.
  - Per library (KH022-1, KH022-1-1): `filtered_feature_bc_matrix.h5`, `raw_feature_bc_matrix.h5`,
    `qc_library_metrics.csv`, `qc_sample_metrics.csv`.
  - From `per_sample_outs/<lib>/`: `metrics_summary.csv`, `sample_filtered_barcodes.csv` and
    `sample_alignments.bam.bai`.
  - Vendor QC PDF: `qc/2011765_qc.pdf`. It is FASTQ QC only and says nothing about the prep.
- **Local benchmarks.**
  - GSE161529 matrices in `data/raw/scrna/GSE161529`, restricted to the barcodes in each capture's
    `private/scrna/runs/tnbc-*/<capture>/all_cells_qc.csv`. My MT and RP values match the pipeline's own values
    (r = 1.0, max difference 1e-14).
  - `data/raw/scrna/pbmc1k-v3` (filtered and raw) and `data/raw/scrna/5k_pbmc_protein_v3_nextgem_filtered_feature_bc_matrix.h5`.
  - Breast_Cancer_3p is not present locally, so it was not used.

## Bytes transferred
- **Full-file downloads: 856.8 MB.** The four .h5 files are 140.3 + 272.3 + 133.0 + 274.0 MB; the two BAI files
  35 MB; the CSVs and PDF under 1 MB.
- **BAM range reads.** samtools/pysam read the per-sample BAMs over presigned HTTPS using the local BAI; the BAM was
  never downloaded whole.
  - Useful span chr1:0-40,000,000, estimated from BAI linear-index offsets: KH022-1 604 MB, KH022-1-1 573 MB, total
    about **1.18 GB**.
  - Plus about 10 MB for the TACSTD2 locus (chr1:58,570,000-58,585,000; about 100k reads per library).
  - Re-fetches from dropped or stalled connections (one 15 Mb attempt per library, then watchdog restarts) add an
    estimated ≤0.9 GB.
  - **Total BAM transfer was about 1.2-2.1 GB, under the 3 GB cap.** The interface byte counter could not isolate
    this job because other agents shared the network, so these figures are BAI-based estimates, not measurements.
- **Public documents:** 10x technical notes CG000376 (1.5 MB) and CG000554 (0.9 MB); a 7.6 MB partial download of the
  Slyper PDF (unusable); about 400 kB of the GSE140819 SOFT header; Ensembl REST gene-coordinate lookups (public gene
  symbols only).

## Commands (in order; run from `scripts/`)
`UV="uv run --no-project --python 3.11 --with h5py --with numpy --with pandas --with scipy --with matplotlib --with pysam --with diptest"`

1. `$UV python bench_matrix.py`: per-barcode composition of the benchmark captures (written to scratch).
2. `$UV python kh022_matrix.py`: KH022 per-barcode composition (`metrics_per_barcode_*.csv.gz`) and ambient
   composition and top genes for KH022 and pbmc1k (`metrics_ambient_*`, `metrics_matrix_summary.json`).
3. `$UV python summarize_matrix.py`: `metrics_composition_by_capture.csv`, `metrics_separability_auc.json`,
   `metrics_nuclei_corner_fraction.csv` and two figures. Then `make_tables.py` writes `table_benchmark_composition.md`.
4. `$UV python qc_threshold_effects.py`, `target_detection.py`, `target_ambient_share.py` and `gene_ambient.py`.
5. Presign the BAMs: `aws s3 presign --region us-east-1 s3://.../<lib>/per_sample_outs/<lib>/sample_alignments.bam --expires-in 43200 > scratch/data/<lib>/bam.url`.
   Then stream the region: `$UV python bam_region.py <lib> <urlfile> <bai> <sample_filtered_barcodes.csv> scratch/bam chr1 0 60000000 5000000`.
   - The run is chunked and resumable, with a watchdog. It was stopped once both libraries reached 40 Mb, and only
     chunks common to both libraries are analysed.
   - The TACSTD2 locus used the same script with `chr1 58570000 58585000 15000`.
6. `$UV python gene_lengths.py` (Ensembl gene spans), then `bam_analysis.py`. This writes `metrics_bam_*`,
   `fig_bam_intronic_fraction.png` and `bam_analysis_log.txt`, and validates the BAM against the matrix.
7. `$UV python target_locus.py`, `pooled_adjust.py` and `fig_ambient.py`.

## Definitions
- **Gene sets.** MT = `MT-*`. RP = `^RP[SL]\d`, the same definition as the benchmark pipeline. Nuclear lncRNA =
  MALAT1 + NEAT1. XIST is reported separately because Xi loss is common in BRCA1-like tumors.
- **Ambient.** Non-called barcodes with 1-99 UMIs (the same definition as the prior SoupX run). Sensitivity sets use
  10-99 and 100-400 UMIs.
- **BAM tags.** UMI = a read with `xf & 8` (the counted-UMI representative), a GN tag and RE in {E,N}. Intronic
  fraction = N/(E+N).
  - This definition reproduces the vendor filtered matrix exactly.
  - Antisense reads carry no GN tag and are excluded, which makes the measure comparable to 10x CG000376's
    "sense intronic / (sense exonic + sense intronic)".
- **Epithelial-marker-high.** KRT8 + KRT18 + KRT19 ≥3 UMIs. This is a crude label, applied identically to every
  capture.
