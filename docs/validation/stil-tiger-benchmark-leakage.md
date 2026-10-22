# TIGER benchmark leakage audit

Companion to the [benchmark specification](stil-tiger-benchmark.md). Each model is audited before it is scored. A TIGER slide or ROI that overlaps a model's training, tuning or model-selection data is excluded from that model's metrics. When the training cohort includes a source but its slide list is unpublished, every TIGER slide from that source counts as overlapping.

Audited October 22, 2026, from primary sources, before any baseline was scored on TIGER.

## TIGER composition relevant to overlap

| Subset | Sources | Overlap-relevant fact |
| --- | --- | --- |
| wsitils (slide scores) | Radboud UMC (`TC_*`), Jules Bordet (numeric S/B) | No TCGA slides |
| wsirois tissue-cells ROIs | 124 TCGA-BRCA slides (BCSS tissue + NuCLS cells), 26 RUMC, 18 JB | TCGA ROIs are BCSS/NuCLS (PanopTILs) material |
| wsirois tissue-bcss ROIs | 151 TCGA-BRCA slides (BCSS) | |

Slide IDs and RUMC patient numbers are disjoint across wsitils (82), the non-TCGA wsirois slides (44) and wsibulk (93). This was checked against the bucket listing; the [TIGER data page](https://tiger.grand-challenge.org/Data/) does not state it.

## Per-model audit

| Model | Training / tuning data | Overlap with TIGER | Exclusions in this benchmark |
| --- | --- | --- | --- |
| ECTIL-TCGA fold 0 | TCGA-BRCA, 342 patients in five centre-stratified folds. The fold file `data/clini/tcga_bc_folds.csv` is published in the [repository](https://github.com/NKI-AI/ectil). Externally tested on non-TIGER cohorts ([arXiv 2501.14379](https://arxiv.org/abs/2501.14379)) | wsitils: none. Of the 151 TIGER TCGA patients, 74 are in fold-0 train/val, 15 in fold-0 test and 62 outside the cohort | wsitils: none. ECTIL has no component outputs, so wsirois is not scored |
| RetCCL encoder (ECTIL features) | Self-supervised on TCGA (about 32,000 WSIs) plus PAIP, per the [RetCCL README](https://github.com/Xiyue-Wang/RetCCL). No labels | Likely saw every TCGA image, unlabeled. No RUMC/JB | None for wsitils |
| MuTILs fold 1 | PanopTILs (BCSS + NuCLS, TCGA-BRCA) plus CPS-II slides; hospital folds; fold 1 was also the tuning fold ([Amgad et al. 2024](https://doi.org/10.1038/s41523-024-00663-1)) | All TIGER TCGA wsirois are PanopTILs material | All TCGA wsirois ROIs. wsitils: none |
| HoVer-Net PanNuke (step 10) | PanNuke: fields from TCGA WSIs across 19 tissues, breast the largest; no slide IDs ([arXiv 2003.10778](https://arxiv.org/abs/2003.10778)) | TCGA wsirois cannot be checked | Treat TCGA wsirois as possibly seen; report TCGA and RUMC/JB separately, with RUMC/JB primary |
| HoVer-Net MoNuSAC (step 10) | MoNuSAC: TCGA crops from four organs including breast; patient barcodes published | TCGA overlap possible | Same as PanNuke |
| VISTA-PATH (modular stroma) | 22 public segmentation sources, including **TIGER wsirois, TIGER wsibulk** and BCSS. The split is 95% random per source, by image ([VISTA-PATH](https://github.com/zhihuanglab/VISTA-PATH), [data card](https://huggingface.co/datasets/zhihuanglab/VISTA-PATH_data)) | All wsirois tissue annotations | **All wsirois ROIs are excluded from VISTA-PATH stroma/tumor Dice.** No clean TIGER tissue check exists for this model. wsitils: none |
| Cellpose 3 `nuclei` (modular) | Fluorescence nuclei sets plus 30 MoNuSeg H&E images | No MoNuSeg training patient is a TIGER patient | None |
| CytoFormer breast head (modular) | Xenium-registered H&E cells labeled from transcriptomics; UNI2-h backbone pretrained on institutional slides ([CytoFormer](https://github.com/zhihuanglab/CytoFormer), [UNI2-h](https://huggingface.co/MahmoodLab/UNI2-h)) | None stated | None. The sources give no full dataset list, so this rests on absence of evidence |

**Bottom line.** wsitils is clean for every baseline, so the slide-level benchmark needs no exclusions. Component checks on wsirois are cleanest on the RUMC/JB ROIs for MuTILs and HoVer-Net. VISTA-PATH has no uncontaminated tissue check in TIGER, so its stroma mask needs another annotated set, such as TCIA Post-NAT-BRCA or newly annotated development ROIs.
