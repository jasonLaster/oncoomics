# GSE161529 TNBC captures through the patient-path QC (exploratory, public data)

Eight treatment-naive TNBC tumors (4 sporadic, 4 BRCA1) from [GSE161529](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE161529)
(Pal et al. 2021), run through intake, private S3 custody, Modal QC, the independent count audit and assessment on the
`public_control` lane. No Diana data. Sources are hash-locked in `manifests/scrna/controls/gse161529-tnbc.sources.lock.json`.

Chemistry (3' v2 vs v3), reference and capture identity are **not stated per sample** by the source, and there are no raw droplet
matrices. The metadata screens therefore fail by design, ambient RNA is unassessable, and every capture stays on provisional hold.
All 190 artifacts verified and the independent count audit passed (ten checks per capture).

| Capture | Input | Retained | Seed ARI | Unknown labels | Failed screens besides metadata |
|---|---:|---:|---:|---:|---|
| tn-mh0114 | 2,015 | 73.5% | 0.90 | 0.0% | none |
| tn-mh0126 | 3,666 | 84.7% | 1.00 | 0.0% | none |
| tn-mh0135 | 15,870 | 74.6% | 0.74 | 93.6% | seed stability |
| tn-sh0106 | 1,065 | 79.6% | 0.97 | 2.1% | none |
| tn-b1-mh0131 | 6,456 | 77.3% | 0.60 | 88.4% | seed stability |
| tn-b1-mh0177 | 21,130 | 71.9% | 0.87 | 0.0% | none |
| tn-b1-mh4031 | 5,581 | 81.9% | 0.79 | 81.3% | seed stability |
| tn-b1-tum0554 | 9,593 | 81.0% | 0.93 | 2.0% | none |

## What this shows

- **Retention passes on all eight** (71.9-84.7%, screen 70%). The sorted-cell 10x demo's 62-64% was a sample-quality
  artifact (dead-cell barcodes), not a pipeline defect. Five of eight captures also pass seed stability.
- **Three captures fail seed stability** (0.60-0.79) and are the same three with 81-94% Unknown/mixed labels. Their unlabeled
  clusters are tumor cells (top markers include KRT17, KRT81, KRT14, UBE2C, CD24). The epithelial hint panel
  (EPCAM, KRT8, KRT18, KRT19) is luminal and does not label basal-like TNBC cells, and one large continuous tumor population splits
  arbitrarily across seeds. The screens are doing their job; thresholds were not tuned.
- scDblFinder flags 2-15% of input barcodes (highest in the two largest captures, 12.5% and 15.0%); these calls are unvalidated.

## Not established

Chemistry/reference, ambient RNA, doublet accuracy, cell identity, malignancy and any clinical use. Adding basal keratins
(KRT5/14/17) to the epithelial hint panel is a plausible fix, but it changes the method after seeing these results, so it needs a
held-out check before adoption.
