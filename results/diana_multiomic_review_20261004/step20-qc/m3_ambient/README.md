# Step 19 / module 3: ambient RNA (private)

Report: `report.md`. Everything below was run locally on the shared 18-core / 36 GB Mac.
No S3 reads: **0 bytes transferred**. No downloads beyond PyPI packages.

## Inputs

| input | md5 |
|---|---|
| `step19-qc/candidate_genes.tsv` | c7d8dfd3ba361932266555b298572716 |
| `step6-scrna-malignant/barcode_annotations_KH022-1.csv.gz` | 66b502165221cb345dd71d83062605bc |
| `step6-scrna-malignant/barcode_annotations_KH022-1-1.csv.gz` | 5c8a711b8ef43830433d2022d63ca25b |
| `.../step2b/data/KH022-1/raw_feature_bc_matrix.h5` | 569a7a972762ee775c30ae429ea15952 |
| `.../step2b/data/KH022-1-1/raw_feature_bc_matrix.h5` | e251ae5c1fa83efac1e11d12feeeec6b |

Also read: `filtered_feature_bc_matrix.h5` (step 15 reproduction), `step13-targets/all_genes_tumor_vs_other.csv.gz` and
`tumor_enriched_genes.csv`, `step15-tnbc-outliers/tumor_cells_vs_public_tnbc.csv.gz` (published bias model),
`scratchpad/step15/gene_features.csv`, and the 8 public GSE161529 `analysis.h5ad` files.
The prior R SoupX 1.6.2 global estimates (L1 0.121, L2 0.081) come from
`private/scrna/kh022-analysis-20261003T070755Z/comparison.md`.

## Commands (in order; run from `scripts/`)

```bash
PY="uv run --no-project --python 3.11 --with h5py==3.12.1 --with pandas==2.2.3 --with numpy==2.1.3 --with scipy==1.14.1"
$PY --with matplotlib==3.9.2 python 01_barcode_rank.py            # barcode-rank curve, CellBender settings
nohup ./02_run_cellbender.sh KH022-1 38994 8 &                    # CellBender, L1 (background, ~3 h)
nohup ./02_run_cellbender.sh KH022-1-1 37805 8 &                  # CellBender, L2
./run_03_05.sh                                                    # 03 empty-droplet test + 05 cell mixture, both libs
$PY python 04_candidate_robustness.py KH022-1                     # after CellBender has finished
$PY python 04_candidate_robustness.py KH022-1-1
$PY --with anndata==0.11.3 --with scikit-learn==1.5.2 python 06_tnbc_reeval.py
$PY --with matplotlib==3.9.2 python 07_tables_figures.py
```

`04` uses `cb_<lib>/cb.h5` (FPR 0.01) if it exists; otherwise it runs without CellBender and `07` uses the cell
mixture model as method (d). Intermediates go to the session scratchpad (`.../scratchpad/m3/`); final tables are in `tables/`.

## Scripts

| script | what | runtime |
|---|---|---|
| `common3.py` | paths | |
| `01_barcode_rank.py` | barcode-rank curve, `figures/barcode_rank.png`, `tables/barcode_rank_summary.json` | ~1 min |
| `02_run_cellbender.sh` | CellBender 0.3.2 remove-background, CPU | see below |
| `03_ambient_tests.py` | soup profiles (3 empty-droplet definitions), per-group rho, genome-wide obs/ambient test with joint bootstrap | 80 s / lib |
| `05_cell_mixture.py` | DecontX-style per-cell mixture with the measured plateau soup (EM, 22 iterations) | ~14 min / lib |
| `04_candidate_robustness.py` | candidates and genome-wide: tumor CPM and tumor vs non-malignant log2FC under 6 corrections, 500 bootstraps | ~3 min / lib |
| `06_tnbc_reeval.py` | step 15 comparison re-run with corrected inputs | ~5 min |
| `07_tables_figures.py` | verdicts, tables, figures | ~1 min |

## CellBender settings and runtime

- CellBender 0.3.2; Python 3.10.20, **torch 1.13.1, pyro-ppl 1.8.6, numpy < 2 (1.26.4)**, pinned in `02_run_cellbender.sh`.
- `--expected-cells` = the Cell Ranger call (38,994 / 37,805). `--total-droplets-included 70000`.
  - The barcode-rank curve has its knee at ~40k and an empty-droplet plateau at ~450-600 UMIs from rank ~45k to ~170k.
  - 70k droplets reaches ~25k barcodes into the plateau.
  - CellBender's own prior for empty droplets was 527 / 537 UMIs.
- `--epochs 60 --learning-rate 1e-4 --fpr 0.01 0.05 --projected-ambient-count-threshold 1 --cpu-threads 8`
  (26,176 / 24,570 features analysed).
- A first attempt with 100k droplets, 150 epochs and threshold 0.1 ran at 3-8 min/epoch, which projected to 10-20 h,
  so it was stopped at epoch 5 and the run above replaced it.
- **Failed attempt.** With the uv default resolution (torch 2.14.1, pyro 1.9.2) the checkpoint cannot be saved (`cannot
  pickle 'weakref.ReferenceType'`). The cause is pyro's `param.unconstrained` weakref, which torch >= 2 pickles.
  - CellBender 0.3.2 reloads the checkpoint to compute the posterior. A full 60-epoch run therefore trained (10,500 s)
    and then died with no output.
  - torch 2.1.2 + pyro 1.8.6 fails the same way. torch 1.13.1 + pyro 1.8.6 works, verified by a 2-epoch smoke test
    that ran to completion. Logs of the failed run are in the scratchpad `m3/failed_torch214/`.
- **Successful runs:** 20,296 s (L1) and 19,688 s (L2) wall time, 7 threads each. Peak RSS was ~5 GB each, and the
  checkpoint (`ckpt.tar.gz`) is ~2-3 GB.
  - Outputs (scratchpad `m3/cb_<lib>/`): `cb_FPR_0.01.h5` (primary; `cb.h5` is a symlink to it), `cb_FPR_0.05.h5`,
    `cb_posterior.h5`, `cb_cell_barcodes.csv`, reports.
  - CellBender metrics are copied to `tables/cellbender_metrics_*.csv`. Counts removed: 13.1% / 12.9% (FPR 0.01),
    16.5% (FPR 0.05). Convergence indicator: 0.03 (L1) / 0.46 (L2).
- `08_depth_scaling.py` (model-free check, ~1 min) runs after `07`:
  `$PY --with matplotlib==3.9.2 python 08_depth_scaling.py`.
- **Deliverable gap.** `report.md` could not be written by the subagent (the tool environment blocked it). Its full
  text was returned to the caller to be saved here.

## Package versions (analysis scripts)

Python 3.11; h5py 3.12.1, pandas 2.2.3, numpy 2.1.3, scipy 1.14.1, matplotlib 3.9.2, anndata 0.11.3, scikit-learn 1.5.2.
numpy 2.1 with Apple Accelerate prints spurious "divide by zero / overflow in matmul" RuntimeWarnings for float32
matmul. The point estimates from those matmuls reproduce step 13 exactly (max difference 3e-16), so the warnings were ignored.
