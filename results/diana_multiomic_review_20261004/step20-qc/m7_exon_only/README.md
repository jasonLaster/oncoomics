# Module 7: exon-only comparison with public TNBC (no bias model)

**What this compares**
- **Diana:** tumor-nucleus exonic UMIs from the module 1 BAM recount, normalized by total UMIs × the library exonic
  fraction (0.431 / 0.438).
- **Public:** tumor cells from 8 GSE161529 TNBC tumors, counted exon-only as whole cells. Per-tumor CPMs are recovered
  from step 15.
- **Why it helps:** this removes the intron-counting inflation of long genes in nuclei.

**Direction of the remaining bias**
- Nuclei under-sample cytoplasmic mRNA. GAPDH and ACTB come out 8-16x lower in Diana, and B2M and HLA-A ~6x lower.
- So for most genes this comparison understates Diana. A gene that still exceeds public tumors is a conservative call.
- **The exception is ambient-exposed genes.** Exonic counts include background RNA: CSN3 and PTPRC appear "up" here.
  Read every call together with the ambient module (m3) and the intronic share.

Run: `uv run --no-project --python 3.11 --with pandas python exon_only_vs_public.py`. Output: `exon_only_vs_public.csv`.

## Key results vs earlier claims

| Gene | Intronic share (tumor) | Step 15 (intron-included + bias model) | Exon-only, no bias model | Change |
|---|---|---|---|---|
| **VTCN1 (B7-H4)** | 92% | ~2.9x, 8/8 | **~0.7x, 0/8** | **No longer an outlier**; also equal to her normal epithelium |
| **CARD18** | ~100% | ~800x, 8/8 | ~2 CPM exonic | **Annotation artifact** (module 1) |
| ERBB4 | 99% | ~77x, 8/8 | ~30x, 6/8 (48 CPM) | Mature mRNA is low but above other TNBC; equal to her normal epithelium; HER4 protein ND |
| ATR | 65% | ~5x but fragile (module 4) | ~22x, 8/8 | **Strengthened** |
| PRLR | 83% | ~3x, 5/8 | ~7x, 8/8 | Strengthened vs TNBC, but equal to her normal epithelium |
| SOX6, MECOM, ESRRG, SHANK2, NAALADL2 | 90-98% | outliers (long-gene caveat) | 15-110x, 8/8 | **Survive** exon-only |
| ENPP3, SLC28A3, HORMAD1, SPECC1L, SLC6A14, EHF, FOLH1, POLQ, KIF18A, KYNU | 56-89% | outliers | 15-50x, 7-8/8 | **Survive** |
| CD44 | 69% | ~6x, 7/8 | ~6x, 7/8 | Unchanged (dosage-driven) |
| TACSTD2, TOP1, NECTIN4, EGFR, CCND1 | | typical | typical or below | Unchanged |
| TAP1, PSMB9, B2M, HLA-A, CDKN1A | | low | low (partly the cytoplasmic bias) | Direction unchanged |
