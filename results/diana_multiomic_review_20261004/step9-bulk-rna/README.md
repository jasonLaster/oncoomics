# step9-bulk-rna: how this was produced (private, git-ignored)

Local-only work, run 2026-10-03. No repo source edits, no git operations, no cloud compute. Patient data never left
the machine; only public references were downloaded. Scratch: `/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step9/`
(`ref/` = public downloads with `ref_sha256.txt`; `work/` = harmonized matrices). The report is `bulk_rna_report.md`.

## Inputs

- **Patient bulk RNA.** `private/scrna/kh022-analysis-20261003T070755Z/bulk_gene_expression.csv`. This is gene-level
  Salmon TPM on GENCODE v23 (59,939 genes); the receipt is alongside (sha256 f93d5d90...). The Personalis tumor RNA FASTQ
  names carry the `ACE4` capture tag (step-1 ledger), so the library is capture-based, not poly(A). Specimen date unknown.
- **Protein.** CP0216 values are as quoted in `comparison.md` and `next-steps-20261003.md`.
- **Single-nucleus.** Read at about 16:12 from step-6 outputs still in progress:
  `private/analysis/step6-scrna-malignant/{cluster_compartments_*.csv, genotype_and_labels_summary.json, readouts_primary_wide.csv}`.

## Public references (URL, version, citation)

| Resource | Source | Notes |
|---|---|---|
| TCGA expression | UCSC Xena TOIL `tcga_RSEM_gene_tpm.gz`, https://toil-xena-hub.s3.us-east-1.amazonaws.com/download/tcga_RSEM_gene_tpm.gz (740,772,247 B; sha256 2ac7215f...) | RSEM, GENCODE v23, log2(TPM+0.001). Vivian et al. 2017 Nat Biotechnol doi:10.1038/nbt.3772 |
| Gene probemap | Xena `probeMap/gencode.v23.annotation.gene.probemap` | |
| TCGA BRCA clinical / PAM50 | repo copy `data/raw/xena/brca_clinical_matrix.tsv` (Xena TCGA.BRCA.sampleMap) | `PAM50Call_RNAseq`, receptor fields |
| TCGA TNBC set and Lehmann calls | repo copy `data/processed/lehmann/tcga_tnbc_lehmann_s1_calls.csv` = Lehmann 2016 PLoS One S1, doi:10.1371/journal.pone.0157368 | 180 TNBC; TNBCtype and refined TNBCtype-4 |
| TCGA HRD scores | GDC PanCanAtlas `TCGA.HRD_withSampleID.txt` (file 66dd07d7-6366-4774-83c3-5ad1e22b177e) | Knijnenburg 2018 Cell Rep doi:10.1016/j.celrep.2018.03.076 |
| TCGA BRCA1 somatic mutations | repo copy `data/processed/cbioportal/mutations_hrr.csv` | context only |
| PAM50 centroids | genefu `data/pam50.robust.rda`, https://github.com/bhklab/genefu | Parker 2009 JCO doi:10.1200/JCO.2008.18.1370 |
| Lehmann signatures | BCTL-Bordet `lehmann.RData`, https://github.com/BCTL-Bordet/TNBC_molecularsubtypes | Lehmann 2011 JCI doi:10.1172/JCI45014; scoring per Garcia 2023 CCR doi:10.1158/1078-0432.CCR-23-1267. Identical to repo `data/processed/lehmann/lehmann_signature_genes.csv` |
| ESTIMATE gene sets | `SI_geneset.RData` from https://github.com/r-forge/estimate (pkg/estimate/data) | Yoshihara 2013 Nat Commun doi:10.1038/ncomms3612; ssGSEA re-implemented from estimateScore |
| Immune / TLS / CAF / HR sets | IOBR `data/signature_collection.rda`, https://github.com/IOBR/IOBR | Danaher 2017 doi:10.1186/s40425-017-0215-8; Ayers 2017 doi:10.1172/JCI91190; Rooney 2015 doi:10.1016/j.cell.2014.12.033; Cabrita 2020 doi:10.1038/s41586-019-1922-8; KEGG HR |
| Ayers final GEP gene list | Ayers 2017 JCI (18 genes, typed in `02_analysis.py`) | published weights not applied |
| PAM50 proliferation genes | Nielsen 2010 Clin Cancer Res doi:10.1158/1078-0432.CCR-10-1282 | 11 genes |
| BRCA1ness template | Severson 2017 Breast Cancer Res doi:10.1186/s13058-017-0861-2, Additional file 1 (Springer ESM xlsx) | Agilent centroids; used as a direction vector (cross-platform adaptation) |
| EPIC reference | GfellerLab/EPIC `data/TRef.rda`, `mRNA_cell_default.rda`, https://github.com/GfellerLab/EPIC | Racle 2017 eLife doi:10.7554/eLife.26476; algorithm re-implemented (weighted constrained LS) |
| Cancer gene lists | OncoKB `cancerGeneList.txt`, https://www.oncokb.org/api/v1/utils/cancerGeneList.txt (downloaded 2026-10-03) | Used to flag likely capture-augmented genes (OncoKB / FoundationOne / MSK-IMPACT columns) |

LM22/CIBERSORT was not used. It is license-restricted and microarray-derived, so EPIC was used instead. Burstein 2015
(doi:10.1158/1078-0432.CCR-14-0432) has no public, reproducible centroid implementation, so only marker proxies are given.

## Commands

```bash
cd /Users/jasonlaster/src/projects/diana-omics/private/analysis/step9-bulk-rna
UV="uv run --no-project --python 3.11 --with numpy --with pandas --with scipy --with scikit-learn --with matplotlib"
# public downloads (curl) and .rda -> csv conversions (uv --with rdata/openpyxl) were done interactively; files + sha256 in scratch ref/
$UV python scripts/01_build_reference.py   # TOIL BRCA primary tumors (1,092), harmonization, cohort labels (~15 s)
$UV python scripts/02_analysis.py          # QN, platform/capture QC, subtypes, signatures, EPIC, tables (~17 min)
$UV python scripts/02b_capture_residuals.py # panel-gene residual probe; writes work/capture_residuals.csv used by fig1
$UV python scripts/03_figures.py           # figures/
```

Versions: Python 3.11.15, numpy 2.4.6, pandas 3.0.6, scipy 1.17.1, scikit-learn 1.9.1, matplotlib 3.11.2, rdata 1.1.0,
openpyxl 3.1.5. GitHub heads at download time: genefu 9c9b66d1 (2025-05-20), BCTL-Bordet f9ee16fb (2024-01-25),
EPIC 50a4f404 (2023-07-12), IOBR 635effe4 (2026-07-23), r-forge/estimate abd60e49 (2022-06-09).
`rdata` and `openpyxl` were used only to convert the R/xlsx sources.

## Outputs

- `bulk_rna_report.md`: the findings.
- `percentiles.csv`: per-gene TPM, TCGA-TNBC / BRCA / Basal / immune-high-TNBC percentiles, z-score, capture residual,
  panel flags, `capture_concern` and the protein value.
- `subtype_scores.csv`: PAM50 correlations and Lehmann signature scores with percentiles and bootstrap frequencies.
- `signature_scores.csv`: immune, stromal, proliferation and DDR signature percentiles, with and without capture-flagged
  genes, and the random-gene-set null.
- `epic_deconvolution.csv`: EPIC cell fractions, patient vs TCGA-TNBC.
- `summary_numbers.json`: every headline number quoted in the report.
- `figures/fig1..fig5*.png`.
