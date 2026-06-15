# Lehmann Signature TCGA Validation

## Bottom Line

The non-dry expression path completed. It fetched 719938 cBioPortal expression records for the public Lehmann signature genes and produced subtype scores for 179 of 180 official TCGA TNBC samples.

The local signature-score approximation matched 142 refined official calls out of 179 assessable samples. That confirms the expression fetch and scoring mechanics work, but the mismatch means this should remain a validation approximation until a locked Vanderbilt TNBCtype implementation or archived web-tool output is used for Diana.

## Signature Coverage

| subtype | available | signature | coverage |
| --- | --- | --- | --- |
| basal_like_1 | 659 | 671 | 0.9821 |
| basal_like_2 | 414 | 430 | 0.9628 |
| immunomodulatory | 1034 | 1055 | 0.9801 |
| mesenchymal | 816 | 836 | 0.9761 |
| mesenchymal_stem_like | 2323 | 2346 | 0.9902 |
| luminal_ar | 2205 | 2220 | 0.9932 |

## Missing Expression Samples

TCGA-AR-A2LR-01

## Boundary

This validates expression acquisition and signature scoring, but it is not the Vanderbilt TNBCtype centroid/permutation web-tool implementation.
