# Out-of-fold endpoint mapping on the TIGER development split

Prespecified October 22, 2026, before any mapping was fitted. Companion to the [benchmark specification](stil-tiger-benchmark.md).

**Question.** The development-split baselines found that segmentation pipelines' native endpoints read far below the pathologist's visual sTIL (bias about −22 pp). Can an explicit monotone mapping from a measured stromal lymphocyte signal to visual sTIL reach the minimum pass tier when it is fitted and evaluated out-of-fold?

**What was already known when this was written.** The uncalibrated slide-level results were known: Spearman 0.26 for the HoVer-Net nuclear-area endpoint, 0.49 for the MuTILs region ratio and 0.49 for ECTIL. The new features listed below have not been compared with the reference. Because rank correlation limits what a monotone map can achieve, a pass is not expected.

## Data

- **Slides.** Only the 40 TIGER wsitils development slides, using the frozen `dev_fold` 0–4 from [`stil_tiger_benchmark_split.json`](../../manifests/stil_tiger_benchmark_split.json). The locked test and the two local HistoWiz slides are not used.
- **Inputs.** Only outputs that already exist from the baseline runs. No new inference.
- **No-calls and not-run.** A pipeline's no-call slides stay no-calls; for MuTILs that is 236B, so 1 of 35 attempted. Not-run slides are excluded and listed. A pipeline is mapped only if it has at least 30 scored slides. That excludes the modular chain (11 slides).

## Features

One **primary** feature per pipeline decides pass or fail. Exploratory features are reported for information only.

| Pipeline | Primary feature | Exploratory features |
| --- | --- | --- |
| Step-10 HoVer-Net (40 slides) | Stromal lymphocyte density: consensus lymphocytes outside tumor nests per mm² of estimated stroma, summed over the tumor-bed tiles used by its sTIL endpoint (necrosis-suspect and hemorrhage tiles excluded) | Native nuclear-area sTIL (`stil_nuclear_area_percent`); lymphocyte fraction of all nuclei |
| MuTILs fold 1 (34 slides) | `nTILsCells2AnyStromaRegionArea`, converted to TIL cells per mm² of stroma at the MuTILs working scale of 0.5 µm/px (× 4 × 10⁶) | `TILs2AnyStromaRatio` × 100; `nTILsCells2nAllStromaCells` × 100 |
| ECTIL-TCGA fold 0 (40 slides) | Uncalibrated prediction × 100 (single-feature comparator) | — |

## Models

Both are monotone non-decreasing in the feature. No source, specimen or band terms are used.

1. **Log-logit, primary.** Fit `logit(r / 100) = a + b · ln(x + c)` by ordinary least squares, with `b ≥ 0`; if the fitted b is negative, set `b = 0` and `a = mean`. The reference r is clipped to [0.5, 99.5] before the logit. The offset c is fixed, not fitted: 10 cells/mm² for densities, 0.01 for percentage features. Predict `100 · sigmoid(a + b · ln(x + c))`. Two parameters.
2. **Isotonic, secondary.** Fit an increasing pool-adjacent-violators regression of r on x. For a new x, interpolate linearly between fitted block values, holding the end values flat outside the training range.

## Cross-fitting

For each fold k in 0–4, fit on the slides in the other four folds and predict the slides in fold k. Pool the out-of-fold predictions across all five folds.

## Metrics and pass rule

Metrics are computed on the pooled out-of-fold predictions, with [`diana_omics.stil_benchmark.agreement`](../../src/diana_omics/stil_benchmark.py):

- MAE with a 2,000-replicate slide bootstrap 95% CI;
- Bland–Altman bias and limits of agreement;
- Lin's CCC and ICC(A,1), both with bootstrap CIs;
- Spearman correlation;
- accuracy and κ at the 10% and 30% cutoffs;
- per-band error;
- subgroups: RUMC vs JB, and JB biopsy vs resection.

The in-sample fit on all callable slides is reported as a labeled reference only. It is not evidence of performance.

A primary feature × model combination **passes** only if every minimum-tier criterion of the [benchmark specification](stil-tiger-benchmark.md#pass-thresholds-and-their-anchors) holds on the out-of-fold predictions: ICC(A,1) ≥ 0.66 with a bootstrap lower bound ≥ 0.50; CCC ≥ 0.66; accuracy ≥ 0.77 at 10% and ≥ 0.81 at 30%; |bias| ≤ 5 pp; MAE ≤ 15 pp; and a no-call rate ≤ 5%.

There are six primary analyses (three pipelines × two models). If more than one passes, the one with the highest out-of-fold CCC is carried forward. Exploratory features that pass are hypothesis-generating only and need a new prespecification.

If a primary analysis passes, the mapping is refit on all callable development slides, frozen by commit and documented as the exact locked-test procedure. **The locked test is not run without the user's approval.** If none passes, the report says so and lists what additional features or data would be needed, with costs.

Code: [`diana_omics.stil_calibration`](../../src/diana_omics/stil_calibration.py) and [`scripts/stil_tiger_calibrate.py`](../../scripts/stil_tiger_calibrate.py).
