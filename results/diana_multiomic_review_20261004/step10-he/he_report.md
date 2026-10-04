# Step 10: computational first read of two H&E whole-slide images

> **CORRECTION (2026-10-04): the board-certified pathologist read supersedes this computational estimate.**
> HistoWiz report 40822 PC3152 (Julie Feldstein MD, 2026-07-14; raw-scores sheet):
> - **Slide B, SP-26-027487:** right breast core biopsy dated 4/10/2026 (Stanford). Invasive ductal carcinoma, grade 3,
>   suspected lymphovascular invasion, ER/PR negative, HER2 IHC 0 / ISH 0, Ki67 40-50%. Tumor-associated stroma 55%,
>   **sTIL 50%**, tumor cellularity 50%.
> - **Slide A, SP-26-22231:** right axillary lymph node core dated 3/23/2026. Metastatic carcinoma (CK7/GATA3/SOX10+),
>   tumor ~30%, sTIL ~10%.
>
> The computational sTIL (~6%) below underestimated the pathologist's score about 8-fold and must not be used.
> Likely causes: a nuclear-area pixel ratio versus the visual ITWG estimate; lymphocyte under-classification; and
> plasma cells/other mononuclear cells counted by ITWG. The tumor-cell estimate (~30% by nuclei) is closer to the
> pathologist's 50% cellularity.
>
> Note also the date: HistoWiz dates SP-26-027487 to a 4/10/2026 Stanford biopsy, while the proteomics report gives
> specimen SP-26-027487-BR-VL3-A1 as collected 3/13/2026 (Sutter). The HistoWiz order lists a separate 3/13 Sutter
> breast biopsy that it did not review. The link between slide B and the proteomics block needs confirmation.


> **This is not a pathology report.** It is an automated, unvalidated read made for research prioritization. No
> pathologist reviewed it, and it must not be used for diagnosis, staging, grading or treatment decisions. Every
> number here is a model output and needs the confirmations listed in §7.

Run date: 2026-10-03. Everything was computed locally (Apple silicon) by `scripts/01`–`08`; see `README.md`. The
CIs are 95% spatial block-bootstrap intervals: blocks of 4×4 tiles (656 µm), 2000 replicates. The tiles are 164 µm
(624 px at 0.263 µm/px, 40×).

## 1. Slides and coverage
| | Slide A | **Slide B (key)** |
|---|---|---|
| Accession prefix | SP-26-022231 (different accession) | SP-26-027487 (matches the pre-treatment proteomics/Altera block) |
| Tissue | 7 fragments ≥0.1 mm² (+11 small); 35.4 mm² stained | **one needle core**, ~18.8 × 1.5 mm; 14.3 mm² stained |
| Tiles (≥25% tissue) | 1550 | 643 |
| StarDist (segmentation, rule typing) | all 1550 tiles: 356k nuclei | all 643 tiles: 60k nuclei |
| HoVer-Net PanNuke + MoNuSAC (typing) | stratified random 325 tiles (21%): 87.5k nuclei | **all 643 tiles: 75.1k nuclei** |
| Out-of-focus tiles (Laplacian var <100) | 2 / 325 | 0 / 643 |

- The slide-A sample is representative. The StarDist-rule tumour fraction is 6.6% in the sampled tiles and 7.1% in
  the unsampled ones; the nuclei per tile are 220 and 233 (`sample_representativeness_A.csv`).

## 2. Slide B: tumour cellularity (nuclei-count based)
**Headline (HoVer-Net consensus): tumour nuclei are 31.6% of all nuclei (95% CI 26.6–36.3%).**
- Within the tumour bed (545/643 tiles): 33.9% (28.8–38.5%).
- The other nuclei are:

| class | % of nuclei (CI) |
|---|---|
| lymphocyte | 35.5 (30.7–40.9) |
| stromal / fibroblast | 29.0 (25.4–33.0) |
| dead / apoptotic | 1.5 (1.3–1.7) |
| benign epithelium | 0.9 |

- Nuclear density is low: 5,430 nuclei/mm² (slide A: 12,590), meaning a stroma-rich, desmoplastic core.

Model sensitivity (whole slide B; same tiles):
| variant | tumour fraction (CI) |
|---|---|
| Consensus (main) | **31.6 (26.6–36.3)** |
| Strict: PanNuke neoplastic AND MoNuSAC epithelial | 23.6 (19.4–27.7) |
| Lenient: + unassigned/benign epithelium | 32.7 (27.6–37.8) |
| PanNuke only | 36.8 (31.2–42.0) |
| MoNuSAC epithelial only | 44.6 (38.0–51.3) |
| StarDist + size rule, k = 1.6 / **2.0** / 2.5 × lymphocyte area | 30.4 / **19.1** / 9.9 |
| StarDist permissive thresholds (S2), k = 2.0 | 19.1 (16.2–22.0) |

- The plausible nuclei-count range is **~20–45%**, and most variants fall at 24–37%.
- The two pipelines agree when the StarDist rule commits to a class:
  - 80% of rule-"tumour" nuclei are consensus-tumour.
  - 88% of rule-"lymph" nuclei are consensus-lymph.
  - The rule leaves 44% of consensus-tumour nuclei as "other", which is why it reads low.
  - 95% of StarDist nuclei match a HoVer-Net nucleus within 3 µm.

Other anchors:
- **Abercrombie (section-thickness) correction.** Larger nuclei are more likely to appear in a section.
  - Median nuclear area: tumour 31.8 µm², lymphocyte 16.6 µm², stromal 18.6 µm².
  - Assuming a 4-µm section, the profile count over-weights tumour nuclei by ~1.2×.
  - Corrected tumour **cell** fraction ≈ **28%**. This is approximate because the section thickness is unknown.
- **Nuclear-area-weighted tumour fraction:** 45.8% (39.6–51.3%).
- **Tumour-nest area** (10-µm envelope around tumour nuclei): 20.9% of tissue area.
- **Strong regional heterogeneity along the core.**
  - Tumour nuclei fraction by third: lower-left 12.0%, middle 35.6%, upper-right 41.5% (`qc/tile_maps.png`).
  - Tile-level median is 26%, IQR 11–45%. 20% of tiles are ≥50% tumour nuclei.

## 3. Slide B: stromal TILs (computational ITWG approximation)
**sTIL ≈ 6% (95% CI 4.7–7.6%). The method bracket is 4.0% (nuclear area only) to 8.1% (cell area = 2× nuclear).**

- Method: within tumour-bed tiles, excluding necrosis and haemorrhage tiles:
  - numerator: lymphocyte cell area (1.5× nuclear) outside tumour nests;
  - denominator: stromal area (tissue minus tumour-nest mask minus fat vacuoles).
  - Stromal lymphocyte density is 2,400/mm².
- Caveats:
  - Pathologists' visual sTIL estimates usually run higher than pixel-area ratios.
  - Plasma cells are partly missed (MoNuSAC has no plasma class).
  - Fibroblasts misread as lymphocytes are visible in `qc/gallery_B.png`.
- Read: **low sTIL, plausibly 5–15% on pathologist review.** This is well below the 30% and 50% (LPBC)
  thresholds; ≥30% is unlikely.

## 4. Composition and necrosis
| | Slide A | Slide B |
|---|---|---|
| Necrosis-suspect tiles (≥10 dead nuclei and ≥20% dead) | 0% | 0% |
| Dead-nucleus fraction | 0.7% | 1.5% |
| Haemorrhage (RBC pixels) | 5.3% of tissue (blood clot in fragments) | 0.2% |
| Fat vacuoles (% of fragment envelope) | 0.2% | 3.4% |
| Tumour-nest area | 34.7% | 20.9% |

- No confluent necrosis was detected on either slide. The dead-cell class is weak, though, and a single core can miss
  necrosis.

## 5. Slide A (different accession): handle with caution
- The slide is dominated by dense lymphoid tissue:
  - 66% of nuclei are lymphocytes (61.8–70.6%);
  - 12,600 nuclei/mm²;
  - the gallery shows sheets of small lymphocytes with admixed large atypical cells.
- The consensus tumour fraction is 25.6% (21.6–29.5%), but **the models disagree badly.**

  | variant | tumour fraction |
  |---|---|
  | PanNuke only | 65% (it calls lymphoid cells neoplastic) |
  | MoNuSAC epithelial | 21% |
  | Strict | 16% |
  | StarDist rule (k = 2.0 / 1.6) | 7% / 13% |

  Treat slide A cellularity as **~7–29%, unresolved**.
- The tumour is concentrated in fragment 1 (30% of nuclei) and is sparse elsewhere (7–12%).
- A computed "sTIL" of 37% (32–41%) is **not interpretable** until a pathologist says what this tissue is. If it is a
  lymph node with metastasis, sTIL scoring does not apply.

## 6. Interpretation against DNA and RNA purity
These measures count different things, so they should not agree numerically:
- **DNA purity** is the fraction of *DNA* that comes from tumour cells.
  - Aneuploid tumour cells carry more DNA than diploid normal cells.
  - Implied tumour *cell* fraction: f = 2p / (ψ(1−p) + 2p), where p is DNA purity and ψ is tumour ploidy
    (`purity_to_cellfraction.csv`).
  - Serova ASCAT p = 0.37 gives **25–29%** at ψ 2.9–3.5. The Serova ploidy was not re-checked here.
  - ASCN candidate S1 (p 0.32, ψ 2.92) gives **24.5%**.
  - ASCN candidate S2 (p 0.48, ψ 4.90) gives **27.4%**. The ASCN refit is still in progress.
- **Nuclei-count cellularity on slide B is 31.6%, and ~28% after the section-thickness correction.** It is
  therefore *consistent* with DNA purity ~0.3–0.5 once ploidy is accounted for.
  - H&E cannot discriminate between the two ASCN candidates: both imply ~25–27% tumour cells.
  - What H&E does argue against is a purity far outside ~0.2–0.55.
- **Area-based estimates read higher (~46% by nuclear area), and pathologists' visual "tumour content" tends to
  follow area.** Tumour nuclei are ~1.9× larger than lymphocyte nuclei, but DNA content scales with ploidy, not area.
  The tumour-nest area (21%) reads lower because desmoplastic stroma dominates the core.
- **Specimen and region effects can be as large as the method gaps.**
  - Within this single core, the tumour fraction varies 12% → 42% from one end to the other.
  - The DNA, the snRNA (~50% malignant nuclei) and the tumour-poor bulk RNA each come from other specimens or
    regions.
- **snRNA ~50% malignant** is expected to exceed the H&E value. Nuclei isolation under-recovers fibroblast nuclei
  from dense collagenous stroma, and QC filters remove low-complexity lymphocyte and stromal nuclei.
- **Bulk RNA looking tumour-poor** fits a stroma-rich sample like the lower-left third of this core.

## 7. What a pathologist must confirm (checklist)
1. **Slide B diagnosis and block identity.** Confirm it is invasive carcinoma (the TNBC under study) and that this
   section is the block used for proteomics/Altera (and, if applicable, the WGS).
2. **Slide B tumour bed and cellularity.** Visual % tumour cells, compared with 24–37% (nuclei) and 46% (area).
   Note which part of the core was sampled for molecular work, given the 12% → 42% gradient.
3. **Slide B sTIL by the ITWG method.** Exclude intratumoural TILs, crush, necrosis and DCIS/normal areas. Computed
   ~6% (4–8%), expected visually at 5–15%.
4. **Slide A tissue type.**
   - Is it a lymph node with metastatic carcinoma, carcinoma with a lymphoid stroma, or another lymphoid lesion?
   - If nodal: metastasis size and extranodal extension.
   - Is it pre- or post-treatment? If post-neoadjuvant, it needs residual-disease (RCB) assessment.
5. **Slide A neoplastic cells:** confirm the large atypical cells are carcinoma, and estimate their fraction.
6. **Necrosis on both slides.** None was detected computationally, and the dead-cell class has low sensitivity.
7. **Slide A haemorrhage/clot** (~5% of tissue) and any benign epithelium or DCIS mislabelled as tumour (3% of
   slide-A nuclei were called benign epithelium).
8. **Spot-check model calls** in `qc/gallery_{A,B}.png`. Fibroblast nuclei are sometimes called lymphocytes, and
   tumour clusters may be under-split (which would undercount tumour).
9. Out of scope here: grade, mitoses, lymphovascular invasion, margins, receptor/HER2 status.

## 8. Limits
- The models are generic (PanNuke/MoNuSAC/StarDist). They were not trained on this lab's stain or validated on TNBC
  cores.
- The cellularity CIs reflect spatial sampling only, not model error. Model error is shown by the sensitivity table,
  which is wider than any CI.
- Slide A HoVer-Net ran on a 21% random sample of tiles.
- The section thickness is unknown.

## 9. Privacy and data handling
- **Raw-data deletion: completed 2026-10-03 17:12 PDT.** Deleted from the old scratchpad
  `…/4fbd936b-…/scratchpad/step10/`:
  - both SVS files (3.07 GB + 1.93 GB) and the `slides/` directory;
  - the `A.svs`/`B.svs` symlinks;
  - the `peek_*.jpg` renders and `hv_extra/`.

  The new scratchpad `…/f61c14bf-…/scratchpad/step10/` was never created. A search afterwards found no `.svs`/`.tif`
  slide files in either scratchpad.
  - What remains in the old scratch: derived nuclei tables (`hv/`, `sd/`, CSVs), tissue masks (`.npy`) and the
    Python venvs. None of these contain label or macro pixels.
- The label and macro images were never read by step 10. All QC images are tissue pyramid levels only.
- ⚠ **Not created by step 10, and needs your decision:** `…/4fbd936b-…/scratchpad/step1/he/` contains 12 PNGs.
  - Their filenames mark them as extracted slide **label/macro** images, for example `A_SP-26-022231_label.png` and
    `B_SP-26-027487_macro.png`.
  - They were not opened, and step 10 did not delete them because they belong to step 1.
  - Recommended: `rm -rf /private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step1/he`.
