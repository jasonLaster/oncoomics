# Held-out TIGER benchmark for breast H&E stromal TIL scoring

Frozen October 22, 2026, before any model output on this data was examined. This document fixes the split, endpoints, metrics, subgroups and pass thresholds for the research sTIL pipelines described in the [scoring plan](../rosalind/stromal-til-scoring-plan.md). It is a research benchmark, not clinical validation.

**Why this exists.** Three pipelines disagree by 10–1000× on the same slides, and only two locally scored reference slides exist. Tuning against those two slides would overfit. TIGER provides 82 whole-slide images with pathologist sTIL scores and 195 slides with region and lymphocyte annotations. All method work uses the development split. The locked test is scored once per frozen pipeline. The two local reference slides are a final sanity check after the locked test, never a calibration target.

## Data

| Subset | Content | Use here |
| --- | --- | --- |
| `wsitils/` | 82 WSIs (multiresolution TIF, 0.5 µm/px) with tissue masks and one sTIL score per slide (0–95) | Slide-level agreement |
| `wsirois/roi-level-annotations/tissue-cells/` | 1,879 ROI PNGs from TCGA-BRCA (via BCSS/NuCLS), Radboud UMC and Jules Bordet, with tissue masks and lymphocyte + plasma-cell boxes (`tiger-coco.json`) | Component checks |
| `wsirois/roi-level-annotations/tissue-bcss/` | 151 larger tissue-only ROIs, TCGA only | Optional tissue check |

Source: `s3://tiger-training/`, public with `--no-sign-request`. The license file states that annotations and the RUMC/JB slides are CC BY-NC 4.0, and that TCGA-BRCA slides carry their original TCGA terms. This repository commits slide IDs, split assignments and derived metrics only, not images or the score table. The score file is bound by SHA-256 `a70061c9…c846` in the [split manifest](../../manifests/stil_tiger_benchmark_split.json).

Per the [TIGER data page](https://tiger.grand-challenge.org/Data/), wsitils contains biopsies and resections of TNBC and HER2+ cancer from RUMC (`TC_*` IDs) and Jules Bordet (numeric IDs, where suffix `S` is a resection and `B` a biopsy). One board-certified breast pathologist scored each slide following the TILs Working Group recommendations. There are no wsitils pathologist annotations. These are not post-neoadjuvant specimens; post-treatment applicability needs a separate component check, for example TCIA Post-NAT-BRCA.

No wsitils slide or patient appears in the wsirois tissue-cells ROIs. This was checked by exact slide ID and by RUMC patient number; the numeric JB IDs in the two subsets are disjoint.

## Frozen split

[`scripts/stil_tiger_split.py`](../../scripts/stil_tiger_split.py) generates [`stil_tiger_benchmark_split.json`](../../manifests/stil_tiger_benchmark_split.json) with seed `20261022`. It verifies the score-file hash and refuses to overwrite a different frozen split. Run `--check` to confirm the committed file is reproduced exactly.

- 40 development and 42 locked-test slides, stratified by source (JB numeric vs RUMC `TC_*`) × score band (0–4, 5–9, 10–29, 30–59, 60+). The allocation uses largest remainders, so every stratum is within one slide of proportional.
- Five development folds, dealt round-robin in band order. Any calibration or threshold choice must be fit on four folds and evaluated on the fifth, with all five out-of-fold predictions reported.
- Pitfall flags are parsed from the pathologist comment: DCIS, normal structures/lobules, lymph node, necrosis (including fat necrosis), neutrophils, granulation tissue, lymphoid aggregates, or the word "pitfall". 14 development and 17 test slides carry at least one flag.

Locked-test rules: no model is run on a locked-test slide until a pipeline, including any calibration, is frozen by commit hash. Each frozen pipeline is scored once on the locked test. A re-run after a change is a new pipeline version and is reported alongside earlier versions, not instead of them. Staging scripts do not copy locked-test images until that point.

## Endpoint mapping

The reference is a **visual estimate** of the percentage of stromal area occupied by mononuclear inflammatory cells. None of the baselines measures exactly that. The baseline is scored on each pipeline's native output, multiplied by 100 where the native value is a fraction, with no calibration or rescaling. That raw comparison is the point: it shows how far each native endpoint sits from the visual score.

| Pipeline | Native output compared | Relationship to visual sTIL |
| --- | --- | --- |
| ECTIL-TCGA fold 0 | `uncalibrated_model_output_fraction` × 100 over FESI-admitted tiles | Regressed prediction of a pathologist TIL score; same target, uncalibrated |
| MuTILs fold 1 | `TILs2AnyStromaRatio` × 100 (pooled predicted TIL-rich-region pixels / predicted stroma + TIL pixels over admitted ROIs) | Region-area ratio. Closer to visual area than a nuclear count, but limited to admitted ROIs |
| Modular VISTA-PATH → Cellpose 3 → CytoFormer (committed `a1764b5a`) | `exploratory_model_stroma_nuclear_area_percent` (accepted lymphocyte + plasma nuclear pixels / predicted stroma pixels over sampled cores) | Nuclear-area proxy. It omits cytoplasm and halo, so it is expected to sit well below visual area at equal cellularity |
| Step-10 HoVer-Net (PanNuke × MoNuSAC consensus) | Lymphocyte nuclear area in non-tumor-nest stroma / estimated stroma area, summed over sampled tiles | Nuclear-area proxy, same caveat |

A secondary analysis may report each pipeline after a monotone calibration fit within development folds (out-of-fold only), labeled as calibrated. Baseline numbers are always reported uncalibrated.

## Prespecified slide-level metrics

Computed by [`diana_omics.stil_benchmark.agreement`](../../src/diana_omics/stil_benchmark.py), on percentage points, prediction minus reference:

- **MAE** (pp), with a 2,000-replicate slide bootstrap 95% CI.
- **Bland–Altman** bias and 95% limits of agreement (bias ± 1.96 SD of differences); plotted against the mean of reference and prediction.
- **Lin's CCC** and **ICC(A,1)** (two-way, absolute agreement, single measurement), with bootstrap CIs.
- **Spearman ρ**, reported for association only; it does not count toward a pass.
- **Categorical agreement** at ≥10% and ≥30%: accuracy, Cohen's κ, sensitivity and specificity for the high class.
- **Per-band** MAE and bias by reference band. **Subgroups** reported separately: pitfall-comment slides vs. the rest, each pitfall category, RUMC vs. JB, and JB biopsy vs. resection.

No-calls: a slide where a pipeline returns no result stays in the denominator of the no-call rate. Agreement metrics use callable slides, and no-calls are listed by ID. Slides excluded for training-data overlap with a given model (see the leakage audit) are removed from that model's metrics only, and listed.

## Pass thresholds and their anchors

There is one TIGER reader, so the model-versus-reference comparison is a two-reader comparison. The right anchor is pairwise pathologist agreement, not agreement with a consensus. Published sTIL agreement:

| Source | Statistic |
| --- | --- |
| International TILs Working Group ring studies 1–3, summarized in [Kos et al. 2020, Table 1](https://doi.org/10.1038/s41523-020-0156-0) | ICC 0.70 (0.62–0.78), 0.89 (0.85–0.92), 0.76 (0.69–0.83). Mean pairwise concordance at <10 vs ≥10%: 0.77, 0.86, 0.79; at <30 vs ≥30%: 0.81, 0.93, 0.87 |
| [Denkert et al. 2016](https://doi.org/10.1038/modpathol.2016.109) | Predefined success target: lower 95% CI bound of the ICC above 0.7 |
| [IVITA, Van Bockstal et al. 2021](https://doi.org/10.1038/s41379-021-00865-z) (40 pathologists, TNBC biopsies) | Pairwise ICC mean 0.659, range −0.376 to 0.947 |
| [ECTIL, arXiv 2501.14379](https://arxiv.org/abs/2501.14379) | ECTIL-TCGA vs. one pathologist on five external cohorts: r = 0.54–0.74 |

Thresholds for the locked test, all on point estimates. A pipeline passes a tier only if every criterion in that tier holds:

| Criterion | Minimum (typical pathologist pair) | Ring-study level |
| --- | --- | --- |
| ICC(A,1) | ≥ 0.66 (IVITA mean pair) and bootstrap lower bound ≥ 0.50 | ≥ 0.76 (ring study 3) and lower bound ≥ 0.66 |
| Lin's CCC | ≥ 0.66 | ≥ 0.76 |
| Accuracy at ≥10% | ≥ 0.77 (ring study 1) | ≥ 0.79 (ring study 3) |
| Accuracy at ≥30% | ≥ 0.81 (ring study 1) | ≥ 0.87 (ring study 3) |
| \|Bland–Altman bias\| | ≤ 5 pp | ≤ 3 pp |
| MAE | ≤ 15 pp | ≤ 10 pp |
| No-call rate | ≤ 5% (at most 2 of 42) | ≤ 5% |

The ICC, CCC and categorical thresholds come directly from the published studies. The bias and MAE thresholds are engineering targets, not literature values: none of the sources above reports pairwise MAE or limits of agreement for sTIL. For context only, if pathologist error were homoscedastic, an ICC of 0.76 on TIGER's score spread (SD 31 pp) would imply a pairwise MAE near 20 pp. Real errors are smaller at low scores and larger at high scores, so that figure is an upper bound and is not used as a threshold. Limits of agreement are reported without a pass rule, because they are expected to widen with score.

With 42 test slides, CIs will be wide: an ICC bootstrap interval of roughly ±0.1 is typical at this size. A point estimate that clears a threshold while its interval crosses well below it is reported as inconclusive, not as a pass.

## Component metrics on wsirois

Components localize error: stroma mask, tumor mask, lymphocyte/plasma detection, and the nuclear-area-to-visual-area conversion.

- **Tissue Dice** over annotated pixels only (mask label 0 is unannotated and excluded). TIGER labels: 1 invasive tumor, 2 tumor-associated stroma, 3 in-situ tumor, 4 healthy glands, 5 necrosis, 6 inflamed stroma, 7 rest. **Stroma** = {2, 6}; **tumor** = {1}. Report per-ROI Dice and pooled Dice (sum intersections over sum sizes), per source (TCGA, RUMC, JB).
- **Detection**: reference points are the centers of `tiger-coco.json` boxes (lymphocytes and plasma cells, one category). A predicted lymphocyte or plasma cell matches at most one reference within **4 µm** (8 px at 0.5 µm/px). This is [TIGER's own hit criterion](https://tiger.grand-challenge.org/Evaluation/). Matching is greedy by ascending distance. Report pooled precision, recall and F1, per source, with 8 µm as a sensitivity analysis. Predictions are restricted to the annotated ROI extent.
- **Endpoint ratio**: on ROIs with both tissue and cell annotations, compare each pipeline's immune-area-in-stroma ratio with the same ratio computed from reference boxes in reference stroma. This separates conversion error from detection error.

## Leakage audit

Before scoring a model, list its training and tuning data and check for overlap with each TIGER subset. Overlapping slides or ROIs are excluded from that model's metrics and listed. When slide IDs of a training set are not published but the training cohort is known to include a source (for example TCGA-BRCA), every TIGER slide from that source is treated as overlapping for that model. The audit table is in [stil-tiger-benchmark-leakage.md](stil-tiger-benchmark-leakage.md).

## Reproduction

```sh
python scripts/stil_tiger_split.py --scores <dir>/tiger-til-scores-wsitils.csv --check
python -m pytest tests/test_stil_benchmark.py
```

Staging, adapters and evaluation: [stil-tiger-benchmark-runbook.md](stil-tiger-benchmark-runbook.md).
