# TIGER benchmark leakage audit

Companion to the [benchmark specification](stil-tiger-benchmark.md). Each model is audited before it is scored. A TIGER slide or ROI that overlaps a model's training, tuning or model-selection data is excluded from that model's metrics. When the training cohort includes a source but its slide list is unpublished, every TIGER slide from that source counts as overlapping.

## TIGER composition relevant to overlap

| Subset | Sources | Overlap-relevant fact |
| --- | --- | --- |
| wsitils (slide scores) | Radboud UMC (`TC_*`), Jules Bordet (numeric S/B) | No TCGA slides |
| wsirois tissue-cells ROIs | TCGA-BRCA (124 slides, adapted from BCSS and NuCLS), RUMC (26), JB (18) | TCGA ROIs are BCSS/NuCLS material |
| wsirois tissue-bcss ROIs | TCGA-BRCA only (BCSS) | |

No wsitils slide or patient is in wsirois tissue-cells (checked by slide ID and RUMC patient number).

## Per-model audit

Status: initial. Updated from primary sources before each model is scored.

| Model | Training data overlapping TIGER | Exclusions |
| --- | --- | --- |
| ECTIL-TCGA fold 0 (with RetCCL encoder) | Trained on TCGA-BRCA. wsitils has no TCGA slides. ECTIL produces no component outputs | None for wsitils, pending confirmation that no TIGER/RUMC/JB cohort was used in training or model selection |
| MuTILs fold 1 | Trained on BCSS and NuCLS (TCGA-BRCA) | All TCGA wsirois ROIs excluded from MuTILs component metrics. wsitils: none |
| HoVer-Net PanNuke / MoNuSAC (step-10) | PanNuke and MoNuSAC are TCGA-derived | TCGA wsirois ROIs treated as overlapping unless slide lists show otherwise |
| VISTA-PATH / Cellpose 3 nuclei / CytoFormer (modular) | Pending | Pending |
