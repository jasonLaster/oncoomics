# Step 19 QC, module 4: statistics and cross-dataset calibration

The results are in `report.md`. This file covers how to reproduce them.

## Commands

```bash
cd private/analysis/step19-qc/m4_stats/scripts
./run_all.sh            # runs 01-09 in order (about 5.5 min wall-clock on 18 cores)
```

`run.sh` wraps each script as follows:

```
OMP_NUM_THREADS=4 uv run --no-project --python 3.11 --with pandas==2.2.3 --with numpy==2.1.3 --with scipy==1.14.1 \
  --with scikit-learn==1.5.2 --with statsmodels==0.14.4 --with matplotlib==3.9.2 --with h5py==3.12.1 --with anndata==0.11.4 python <script>
```

- **Thread cap.** `OMP_NUM_THREADS=4` matters. Without it, sklearn's HistGradientBoosting oversubscribes threads on macOS, and
  script 02 took more than 10 minutes instead of about 80 s.
- **Versions.** uv 0.11.26, Python 3.11.15. The packages are as pinned above.
- **BLAS warnings.** numpy 2.1.3 with Accelerate prints spurious "divide by zero / overflow encountered in matmul"
  warnings in script 04. I checked them against `np.einsum`: max abs difference 0, all values finite.

| script | what it does |
|---|---|
| `common.py` | Re-implements the step15 bias model and outlier call (same features, GBM settings and seeds) on cached pseudobulks. |
| `01_build_pseudobulk.py` | Builds per-library KH022 pseudobulks (malignant, non-malignant, T/NK, myeloid, fibroblast; qc_pass and not dbl_union, as in step15), per-tumor GSE161529 pseudobulks, and per-nucleus counts for the candidate genes. |
| `02_bias_model_validation.py` | Test 1a: leave-one-compartment-out. Test 1b: housekeeping controls. Test 1c: reference-compartment null and public-tumor-as-query null. Test 1L: length/intron enrichment, residuals vs span, and outliers beyond the training span. |
| `03_dosage.py` | Test 2: tumor-vs-non-malignant log2FC and excess vs public, regressed on log2(CN/2.8). Genes are mapped to segments by Ensembl ID through the GENCODE v23 GTF. |
| `04_bootstrap_candidates.py` | Test 3: bootstrap with B=1000. Nuclei are resampled within each library, and public cells within each tumor. The bias term is drawn from N(bias_hat, span-bin out-of-fold SD). |
| `05_robustness.py` | Test 3b: L1 vs L2 concordance and per-library calls. Test 4: downsampling (public median UMI, and a 2,000-UMI stress level) and a threshold grid. |
| `06_exon_only_recall.py` | Exon-only recall from module 1's BAM recount. **It skipped:** module 1 had produced no `per_barcode/` output when this ran (see the report). |
| `07_length_recalibration.py` | Housekeeping-anchored length recalibration, a bias-uncertainty-margin call, FDR with that margin, and FDR as a function of the fold threshold. |
| `09_genomewide_pcall_longgenes.py` | Genome-wide P(call given bias uncertainty), the long-gene watchlist, a direct-measured-bias variant, and a check of GBM vs linear extrapolation. |
| `08_candidate_table.py` | Merges everything into `tables/candidate_summary.csv`, assigns verdicts and draws the forest plot. |

## Inputs

**Large inputs** (paths from `../BRIEF.md`):
- KH022 filtered matrices: `.../4fbd936b.../scratchpad/step2b/data/<lib>/filtered_feature_bc_matrix.h5`.
- `metrics_summary.csv` (only for script 06).
- `step6-scrna-malignant/barcode_annotations_<lib>.csv.gz`.
- The 8 public `analysis.h5ad` files under `private/scrna/runs/tnbc-*/`.

**Small inputs** (md5):

| file | md5 |
|---|---|
| `ref/HK_genes_Eisenberg2013.txt` | 3c29a7d8976857b6242b317bf58ba25b |
| `step19-qc/candidate_genes.tsv` | c7d8dfd3ba361932266555b298572716 |
| `step5-ascn/segments_fit_S1b_p0.35_ploidy2.80.standardized.tsv` | 3e93eee45f3d5d67028d5f2c02e18cf3 |
| scratchpad `step15/gene_features.csv` | c6c12933752cb6e2aebbe9af731b6a7c |
| scratchpad `gene_coords.tsv` (not used in the end: the mapping goes by Ensembl ID through `step15/g23.gtf.gz`) | 2ba52a0d43c2b174a7e373372d088e94 |
| `step13-targets/all_genes_tumor_vs_other.csv.gz` | 6ba3e3b3e6a1931c1e79cde078510e00 |
| `step15-tnbc-outliers/tumor_cells_vs_public_tnbc.csv.gz` (used only to check reproduction) | 1b5c1e29c0bdfbc66d7b5fba8df35405 |

## Public reference download

- `ref/HK_genes_Eisenberg2013.txt`: 3,804 human housekeeping genes, 66,915 bytes.
- Source: <https://www.tau.ac.il/~elieis/HKG/HK_genes.txt>.
- Citation: Eisenberg E, Levanon EY. Human housekeeping genes, revisited. *Trends Genet* 2013;29:569-574.

## Transfer, cost and outputs

- **S3:** 0 bytes. No BAM access was needed.
- **Cost:** local compute only.
- **Cache:** intermediate files go to the session scratchpad (`.../f61c14bf.../scratchpad/m4/`).
- **Outputs:** `tables/` (CSV; `run_all.log` holds the full console output) and `figures/` (PNG).
