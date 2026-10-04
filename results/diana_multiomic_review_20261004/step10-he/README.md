# step10-he: computational first read of two H&E whole-slide images (private)

This is a research prioritization aid, **not a pathology report**. The results are in `he_report.md`.

## Inputs (read-only)
- Source: `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-30-h-and-e-slides/data/` (us-east-1).
  It holds two Aperio SVS files (scanner SS12248, 40x, 0.263089 um/px, scanned 07/09/2026). They were downloaded once
  and checked against the provided `checksums.sha256`.
  - Slide A: accession prefix SP-26-022231, 3.07 GB.
  - Slide B: accession prefix SP-26-027487, 1.93 GB. This matches the pre-treatment proteomics/Altera block.
- Privacy: the SVS associated images (label, macro) show the patient's name. No script reads them.
  - Every read is `read_region` on pyramid levels 0 to 3 (the tissue scan area).
  - The QC images contain only those pixels.

## Models and weights
| model | weights / source | use |
|---|---|---|
| HoVer-Net (fast), PanNuke | `hovernet_fast-pannuke.pth`, TIA Centre pretrained, huggingface.co/TIACentre/TIAToolbox_pretrained_weights, via TIAToolbox 2.1.3 `get_pretrained_model` | segmentation and 5-class typing (neoplastic / inflammatory / connective / dead / non-neoplastic epithelial) |
| HoVer-Net (fast), MoNuSAC | `hovernet_fast-monusac.pth`, same source | 4-class typing (epithelial / lymphocyte / macrophage / neutrophil); trusted for lymphocytes |
| StarDist 2D_versatile_he | stardist 0.9.1 `StarDist2D.from_pretrained('2D_versatile_he')` (registered public weights) | independent segmentation; nuclei typed by a slide-normalized morphology rule (see `scripts/05_aggregate.py`) |

- References:
  - Graham et al. 2019 (HoVer-Net), doi:10.1016/j.media.2019.101563.
  - Gamper et al. 2020 (PanNuke), arXiv:2003.10778.
  - Verma et al. 2021 (MoNuSAC), doi:10.1109/TMI.2021.3085712.
  - Pocock et al. 2022 (TIAToolbox), doi:10.1038/s43856-022-00186-5.
  - Schmidt et al. 2018 and Weigert et al. 2020 (StarDist).
  - Salgado et al. 2015, doi:10.1093/annonc/mdu450, and Amgad et al. 2020, doi:10.1038/s41523-020-0154-2 (TILs
    Working Group method and its computational translation).
  - Ruifrok & Johnston 2001 (HED colour deconvolution).
- The models were not fine-tuned or validated on these slides. No pathologist annotations were used.

## Environment (local, Apple silicon)
- HoVer-Net: Python 3.11.15 `venv_tia`.
  - Packages: tiatoolbox 2.1.3, torch 2.12.1 (MPS), openslide-python 1.4.3, numpy 2.4.3, scipy 1.17.0,
    scikit-image 0.26.0, pandas 3.0.2, opencv 4.14.0, matplotlib 3.11.0.
- StarDist and the colour/aggregation steps: Python 3.11.15 `venv`.
  - Packages: stardist 0.9.1, tensorflow 2.15.1 (CPU), pandas 3.0.6, matplotlib 3.11.2, opencv 5.0.0,
    openslide-python 1.4.6.
- No cloud compute was used.

## Commands
Set the paths first:
- `SCR` is the scratch directory that holds `A.svs` and `B.svs` (symlinks to the downloaded files).
- `OUT` is this directory.

Run these from `$SCR`:
```
venv/bin/python     $OUT/scripts/01_tissue.py      $SCR $OUT   # tissue mask, fragments, 624-px (164 um) tile grid
venv/bin/python     $OUT/scripts/03_stardist.py    $SCR        # StarDist on ALL tiles (2193), ~60 min CPU
venv/bin/python     $OUT/scripts/02b_sample_A.py   $SCR        # stratified random 325-tile sample of slide A (seed 11)
venv_tia/bin/python $OUT/scripts/02_hovernet.py    $SCR B      # HoVer-Net x2 on all 643 slide-B tiles (~55 min MPS)
venv_tia/bin/python $OUT/scripts/02_hovernet.py    $SCR A      # HoVer-Net x2 on the slide-A sample (resumable)
venv/bin/python     $OUT/scripts/04_color.py       $SCR        # level-1 pixel composition (RBC, white/fat)
venv/bin/python     $OUT/scripts/05_aggregate.py   $SCR $OUT   # per-tile classes, StarDist rule, sTIL inputs, agreement
venv/bin/python     $OUT/scripts/06_slide_metrics.py $SCR $OUT # slide metrics + 4x4-tile block bootstrap CIs (2000 reps)
venv/bin/python     $OUT/scripts/07_gallery.py     $SCR $OUT   # qc/gallery_A.png, qc/gallery_B.png
venv/bin/python     $OUT/scripts/08_supplement.py  $SCR $OUT   # area-weighted fractions, purity->cell fraction, tile maps
```
- `overlay_lib.py` holds helper code from the model-selection stage. The final outputs do not use it.
- Run history: the first agent died partway through the slide-A HoVer-Net sample (165 of 325 tiles). The run was
  resumed with the same script and sample file, so 325 of 325 tiles are now done. Steps 05 to 08 were then re-run.
- `hv_extra/` (scratch, now deleted) held 108 slide-A tiles from an early raster-order sharded run. They are not part
  of the random sample, and none of the outputs use them.

## Outputs
| file | contents |
|---|---|
| `he_report.md` | the report |
| `per_slide_metrics.csv` | final per-slide metrics with block-bootstrap 95% CIs (`_lo`/`_hi`) |
| `tile_metrics.csv.gz` | per-tile counts (HoVer-Net consensus, PanNuke/MoNuSAC raw, StarDist S1/S2 x k), composition, flags |
| `fragments.csv`, `fragment_metrics.csv` | tissue fragments; per-fragment class fractions |
| `area_weighted_fractions.csv` | nuclear-area-weighted class fractions, median nuclear areas |
| `purity_to_cellfraction.csv` | tumour cell fraction implied by DNA purity x ploidy |
| `sample_representativeness_A.csv` | slide-A HoVer-Net sample vs unsampled tiles (StarDist rule) |
| `agreement_consensus_vs_stardist_rule_{A,B}.csv` | per-nucleus confusion table between the two pipelines |
| `stardist_slide_refs.json`, `slide_metadata.json` | rule reference sizes; slide/pyramid metadata (no label/macro) |
| `qc/slide{A,B}_tissue_overview.png` | tissue mask on pyramid level 3 |
| `qc/gallery_{A,B}.png` | 6 random tiles per slide: raw, HoVer-Net consensus, StarDist rule |
| `qc/tile_maps.png` | per-tile tumour/lymphocyte fraction maps (no pixels) |

## Raw-data deletion (confirmed 2026-10-03 17:12 PDT)
- Deleted from `/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step10/`:
  - both raw SVS files and the `slides/` directory;
  - the `A.svs`/`B.svs` symlinks;
  - the `peek_*.jpg` renders and `hv_extra/`.
- The new scratchpad `.../f61c14bf-e23e-4829-a09a-24be63d09400/scratchpad/step10/` was never created.
- A `find` afterwards for `*.svs`, `*.tif*`, `*.ndpi` and accession-named files in both scratchpads found no slide
  files.
- Still in the old scratch step10: derived nuclei arrays (`hv/`, `sd/`), CSVs, tissue masks and the two venvs (~4 GB,
  mostly venvs). None contain label/macro pixels; delete them when they are no longer needed.
- Not part of step 10: `.../4fbd936b-.../scratchpad/step1/he/` holds 12 PNGs named as slide label/macro extracts.
  These are patient-identifying. They were not opened or deleted here; see `he_report.md` §9.
