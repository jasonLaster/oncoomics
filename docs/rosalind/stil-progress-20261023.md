# H&E sTIL scoring: progress and remaining work

Oct 23, 2026 · Jason Laster · Live version: [Claude Doc](https://claude.ai/artifact/XVjptZnwKVuAMwjqK5HQbD)

## Bottom line

**We do not yet have a trustworthy sTIL score for the 9/24 post-chemo surgical slides.** Every number computed so far is unreliable. On a public benchmark with pathologist scores, every pipeline we tried fails the pass criteria we wrote down before seeing results.

- **The main error is the measurement itself.** Lymphocyte nuclear area as a share of stroma reads \~2% at densities a pathologist scores far higher. On the HistoWiz core scored 50%, our earlier pipeline read \~6%.
- **Calibration alone doesn't rescue it.** A mapping fit on held-out folds removes the bias but reaches agreement of only 0.62 (the bar is 0.66).
- **No public benchmark covers post-chemo tissue.** Even a pipeline that passes TIGER needs a pathologist read on these slides.

The most reliable next step is a HistoWiz residual-disease TIL read on the 7 breast slides. The computational path continues in parallel only if the budget is raised.

## What happened, Oct 21–23

Three days took us from a first model run to a benchmark showing why none of the numbers hold up. Newest first:

| When | Step | Outcome |
| --- | --- | --- |
| Oct 23 | Budget review | Proposed a staged plan for a $100 total cap (Remaining work) |
| Oct 22, 16:30 | Out-of-fold calibration on TIGER development slides | No mapping passed; best agreement 0.62 vs the 0.66 bar |
| Oct 22, evening | Fixed stroma mask (v2) tested on TIGER, locally on the Mac | No change: agreement 0.04 vs 0.05 for v1 on 11 slides |
| Oct 22, 12:00–16:00 | TIGER baselines: ECTIL, HoVer-Net, MuTILs, modular | All four fail every pass criterion; $39.72 of the $40 cap spent |
| Oct 22, 09:30 | Froze TIGER development/held-out split and pass criteria | 40 development and 42 held-out slides; criteria committed before any results |
| Oct 22, 10:00 | Sampling and stroma-mask fixes (v2) | Ink and fat excluded; immune-infiltrate prompts; QC gates added |
| Oct 22, morning | Audit of the first two days' work | Found pen-ink sampling, a stroma mask that drops lymphocytes, and no reference |
| Oct 22, 06:37 | Modular VISTA-PATH → Cellpose 3 → CytoFormer run on the 9 UCSF slides (Pavan's suggestion) | 0.03–2.4% on breast slides |
| Oct 21 | MuTILs and ECTIL run on the 9 UCSF H&E slides | MuTILs 0–1.5% (2 no-calls), ECTIL 11–17% |
| Oct 21 | Planning doc for breast H&E sTIL scoring | Model shortlist and validation plan |

## Results on the UCSF post-chemo slides (not usable)

On the 7 breast slides, the three methods disagree by one to three orders of magnitude, and each has a known bias. These numbers are kept for the record only. None of them is an sTIL score.

| Slide | Tissue | ECTIL % | MuTILs % | Modular % (original mask) |
| --- | --- | --: | --: | --: |
| B3-5 | breast | 17.2 | 0.24 | 1.02 |
| B4-1 | breast | 11.7 | no-call | 0.24 |
| B5-1 | breast | 11.1 | 0.66 | 0.21 |
| B6-3 | breast | 13.0 | 1.50 | 2.36 |
| B7-1 | breast | 11.2 | no-call | 0.03 |
| B8-1 | breast | 12.0 | <0.01 | 0.45 |
| E1-5 | lateral margin | 15.1 | 0.34 | 0.08 |
| F2-3 | sentinel node 1 | 52.9 | 58.5 | 22.7 |
| G1-5 | sentinel node 2 | 43.4 | 36.5 | 30.1 |

- **Specimen:** right partial mastectomy, 9/24, after neoadjuvant chemotherapy. The report gives RCB-II with about 5% residual cellularity: scattered single cells and small nests across 41 × 20 mm. No TIL score was reported.
- **Biases:** ECTIL's 11–17% is close to its floor on almost any breast tissue. MuTILs and the modular chain undercount by construction (see TIGER benchmark).
- **Nodes:** node values are not sTIL. Nodal scoring has to exclude the node's own lymphoid tissue.
- **Excluded:** ten non-H&E slides (IHC stains).

## Audit findings (Oct 22)

The file-integrity and arithmetic checks all passed (3,186 output files re-hashed, 288 tiles re-extracted from the source slides). The science underneath failed in four ways:

1. **Tiles landed on pen ink.** A thumbnail colour rule put 102 of 288 tiles (35%) on the pathologist's handwriting beside the tissue ("Inv ⊕…"). On 5 of 7 breast slides that was 17–21 of 32 tiles. Most remaining tiles were fat or collagen; on B6-3, only about 4 tiles touched its one dense cellular focus.
2. **The stroma mask dropped lymphocytes.** VISTA-PATH was prompted with only "Tumor" and "Stroma", thresholded per tile (one tile's tumor cutoff was 0.02 probability). It called 17–32% of breast tissue tumor against \~5% reported cellularity. Only 6–71% of immune nuclei fell inside predicted stroma.
3. **Wrong measurement.** Nuclear area as a share of stroma isn't what a pathologist estimates. The TIGER benchmark later showed this is the dominant error.
4. **No reference.** The surgical report gives no TIL number. HistoWiz scored only pre-treatment specimens.

Two housekeeping risks were also found. `results/stil/` (568 MB, with surgery date, specimen and slide thumbnails) sat untracked but not gitignored in a public repo. Ten MuTILs/ECTIL runner scripts were never committed. Both were fixed on Oct 23 (`5f2e927b`).

## The HistoWiz reference slides

The two slides HistoWiz's pathologist (Julie Feldstein, report 40822 PC3152, July 14) scored "in entirety" are in S3 as whole-slide scans (`2026-07-30-h-and-e-slides/`, 40×, 0.263 µm/px). Their filenames carry the same accessions as the report.

| Specimen | Date | Pathologist sTIL | Other reported values | Our earlier computational read (step10, Oct 3) |
| --- | --- | --: | --- | --- |
| SP-26-027487, breast core | Apr 10, day 8 of treatment | 50% | 55% tumor-associated stroma, 50% cellularity | \~6% (nuclear-area 4%), an \~8× underestimate |
| SP-26-022231, axillary node metastasis | Mar 23, before treatment | 10% | 5% tumor-associated stroma, 30% cellularity | Not interpretable as sTIL |

- **How we use them:** as a final sanity check only, after a pipeline passes the TIGER held-out test. Nothing is tuned or calibrated on them: one patient and one usable breast point would just move the bias around.
- **No direct comparison:** they're pre-treatment specimens, so they're not a reference for the 9/24 post-chemo slides.

## TIGER benchmark

No pipeline we've tried agrees with pathologist sTIL on 40 public development slides. A held-out mapping fixes the scale but not the ranking.

**Setup.** We used [TIGER](https://tiger.grand-challenge.org/Data/) `wsitils`: 82 public breast whole slides (HER2+ and TNBC), each with a whole-slide visual sTIL score from one breast pathologist (0–95%, median 10).

- **Split:** frozen into 40 development and 42 held-out test slides, stratified by score band and source. The held-out slides have not been touched.
- **Pass criteria, written down before results:** agreement (CCC/ICC) ≥ 0.66, mean absolute error ≤ 15 points, |bias| ≤ 5, and accuracy ≥ 0.77 at the 10% cutoff and ≥ 0.81 at 30%.
- **Component checks:** `wsirois` (hand-drawn stroma and lymphocyte boxes) scores the stroma mask and cell detection separately.
- **Leakage audit:** each model's training data was checked for overlap with these slides.

**Baselines (development slides, uncalibrated).** All four fail every criterion.

| Pipeline | Slides | Mean abs. error (pts) | Bias (pts) | Agreement (CCC) | Rank corr. |
| --- | --: | --: | --: | --: | --: |
| ECTIL (TCGA fold 0) | 40 | 21.4 | −0.7 | 0.35 | 0.49 |
| HoVer-Net (step10 method) | 40 | 24.4 | −22.5 | 0.04 | 0.26 |
| MuTILs (fold 1, logging patch) | 34 | 22.6 | −22.3 | 0.10 | 0.49 |
| Modular, original mask | 11\* | 18.1 | −18.1 | 0.05 | 0.63 |
| Modular, v2 mask (Mac rerun) | 11\* | 18.4 | −18.4 | 0.04 | 0.59 |

\*10 of 11 slides from one source; cell classification stopped at the budget cap.

**Where the error is.**

1. **The measurement.** At correct lymphocyte density (HoVer-Net 1.02× the annotated density on JB regions), nuclei still cover only \~2% of stroma. A pathologist scores that tissue far higher.
2. **Stroma mask.** Overlap with annotated stroma is 0.44–0.58, and the masks call 1.4–3.4× too much tissue stroma, including DCIS and normal glands.
3. **Cell classification.** Cellpose + CytoFormer beat HoVer-Net (F1 0.52–0.55 vs 0.32–0.47).

**Out-of-fold calibration (Oct 22).** Features and model forms were committed before fitting (`2df436e9`), with monotone maps fit on 4 development folds and predicting the fifth.

- **Best prespecified result:** MuTILs lymphocyte density with an isotonic fit, n = 34. Mean error 17.1, CCC 0.62, accuracy 0.65 / 0.76 at 10% / 30%.
- **Closest overall:** a feature chosen after seeing data (CCC 0.68) still failed bias, cutoff accuracy and the ICC lower bound, so it can't count.
- **The ceiling:** the mapping removes the bias, but agreement can't exceed each feature's rank correlation (≤ 0.61).

## Code, data and spend

All code is on `main` in the public repo [jasonLaster/oncoomics](https://github.com/jasonLaster/oncoomics), pushed Oct 23 at `5f2e927b`. Patient-derived outputs stay local or in private storage. The 40 sTIL tests pass.

| What | Where | Notes |
| --- | --- | --- |
| Scoring plan | `docs/rosalind/stromal-til-scoring-plan.md` | Endpoint definitions, model shortlist |
| Modular pipeline (v1 + v2 fixes) | `scripts/modal/stil_modular_execute.py`, `src/diana_omics/stil_sampling.py`, `stil_tissue.py` | v2 = tissue/ink/fat-aware sampling, immune prompts, QC gates |
| MuTILs / ECTIL runners | `scripts/modal/stil_batch.py` + helpers | Committed in this push; hash-pinned by the TIGER code |
| TIGER benchmark | `docs/validation/stil-tiger-benchmark*.md`, `manifests/stil_tiger_*`, `scripts/stil_tiger_*.py`, `src/diana_omics/stil_benchmark.py`, `stil_calibration.py` | Frozen split, metrics spec, leakage audit, runbook, calibration spec |
| UCSF slide results (MuTILs/ECTIL) | `results/stil/20261021/` (local, now gitignored) | Includes the original reviewer report |
| UCSF slide results (modular) | `private/stil/modular-execution-20261022/` | Reviewer packet and atlases |
| TIGER results | `private/stil/benchmark-20261022/README.md` | Baselines, components, calibration addendum, v2 results |
| Earlier HistoWiz-slide analysis | `private/analysis/step10-he/` | The \~6% vs 50% result |
| Report summarizer with case details | `private/stil/code-20261021/stil_summarize.py` | Moved out of the public repo |
| Model outputs | Modal volumes `diana-stil-pilot-20261021`, `diana-stil-tiger-*` | Private |

**GPU spend:** $39.72 on Modal against the $40 cap, all on the TIGER benchmark (MuTILs $15.24). The v2 stroma rerun ran on the Mac at no cost. The Oct 21–22 UCSF runs are not included in that figure.

## Remaining work

Two tracks remain. A pathologist read gives a usable number for these slides. A staged computational plan, which needs the budget raised to about $100 total, could give a reusable pipeline.

Staged plan (each paid step runs only if the one before it clears its gate):

1. **Finish cell classification:** 29 development slides plus the 5 MuTILs slides that didn't run (~$10–13).
2. **Inflamed-stroma area classifier,** trained on TIGER `wsirois` regions (~$5–15). Gate: rank correlation above ~0.7, else stop.
3. **Out-of-fold mapping to the visual score,** with features prespecified before fitting ($0). Gate: passes the prespecified bar out-of-fold.
4. **Locked test, run once,** on the 42 held-out TIGER slides (~$15–25). Gate: passes on the held-out slides.
5. **Score the UCSF slides:** 7 breast slides, nodes kept separate (~$5). The pathologist read runs in parallel, independent of GPU budget, and is the reference for this step.

All steps together cost about $35–60, inside $100. Denser tiling of high-TIL slides (up to \~$48) is left out unless step 2 shows strong ranking.

**Decisions needed**

- [ ] Request a HistoWiz residual-disease TIL read on the 7 UCSF breast slides (B3-5, B4-1, B5-1, B6-3, B7-1, B8-1, E1-5), with the tumor bed outlined
- [ ] Raise the GPU budget from $40 to $100 for the staged plan, or stop the computational track here
- [ ] Ask the pathologist what the on-tissue ink dots on B6-3 and B7-1 mark

**Open questions**

- [ ] Confirm with the lab that the BR research slide labels map to the 9/24 surgical case, including the F2/G1 node blocks
- [ ] Decide whether nodes get a separate nodal-metastasis TIL protocol or are dropped from sTIL entirely
- [ ] Pick a post-chemo component check: TCIA Post-NAT-BRCA lymphocyte labels (96 slides, no TIL scores), or new annotations on development regions

**Housekeeping**

- [ ] Other untracked items in the repo (`results/pet_target_review_20261009_yuga/`, `.runs/`, three dated HTML reports) are unrelated to sTIL and were left as they are; review whether they hold private data
