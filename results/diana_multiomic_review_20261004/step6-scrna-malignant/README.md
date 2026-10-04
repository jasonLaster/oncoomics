# step6-scrna-malignant: how to reproduce (private)

The results are in `scrna_malignant_report.md`. The scratch work directory is
`$TMP = /private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step6`.
It holds the processed h5ad files, the CNV matrices, the regional BAMs (2.9 GB of patient reads) and the presigned
URLs (`bam/*.url`, chmod 600, 12 h). Delete it when it is no longer needed.

## Environment
- Python 3.11.15, run through `$TMP/py.sh`:
  `uv run --no-project --python 3.11 --with scanpy==1.11.1 --with anndata --with igraph==0.11.8 --with leidenalg==0.10.2 --with scikit-learn --with infercnvpy --with pysam --with h5py --with matplotlib --with scipy --with pandas --with scikit-misc`.
  - `PYTHONPATH` = repo `src` (for `diana_omics.scrna.stable_leiden`) plus `scripts/`.
- Package versions: scanpy 1.11.1, anndata 0.12.19, infercnvpy 0.6.1, pysam 0.24.1, leidenalg 0.10.2, igraph 0.11.8,
  scikit-learn 1.5.2, numpy 2.4.6, pandas 2.3.3, scipy 1.17.1, matplotlib 3.11.2, scikit-misc 0.5.2, h5py 3.16.0.
  samtools 1.23.1.
- No R was needed. The scDblFinder calls are reused from Codex `gemx-results/<lib>/gemx_rate.csv` (scDblFinder
  1.20.2, dbr.per1k = 0.004).

## Inputs
- Matrices: `scratchpad/step2b/data/<lib>/{filtered,raw}_feature_bc_matrix.h5`.
- Step 2b per-barcode intronic fractions.
- Step 2a tumor-WGS het AF and site tables.
- `scratchpad/cnv/coverage_cnv_bins.csv` (tumor WGS 5 Mb coverage bins).
- Gene annotation: Ensembl 110 (= GENCODE 44, the GRCh38-2024-A build) canonical transcripts, from BioMart
  (`jul2023.archive.ensembl.org`). Queries are in this README's history and the outputs are in
  `$TMP/{genes,exons,tx}_e110.tsv`.
- Somatic sites: exome/Altera-validated sites from step 3. MTOR P1125A and PTPN23 P981A were lifted with Ensembl REST
  `/map/human/GRCh37/.../GRCh38`, and the reference bases were checked with `samtools faidx` on the WGS reference.
- Four core-HRR Mutect2 PASS calls (`s3://diana-omics-results-.../core_hrr.mutect2.filtered.vcf.gz`, 43 KB) are
  included as unvalidated extras.

## Steps (run from `scripts/`; `PY=$TMP/py.sh`)
1. `$PY 01_qc_cluster.py <lib>`: QC metrics and flags, ambient profile, scDblFinder join, HVG/PCA/kNN,
   stable_leiden, UMAP and panel scores.
2. `$PY 02_compartments.py <lib>`: cluster-to-compartment rule and the heterotypic doublet heuristic.
3. `$PY 03_infercnv.py`: shared gene set, reference / held-out split, infercnvpy, window positions.
4. `$PY 04_cnv_calls.py`: cross-library consensus correlation, CNV calls, arm validation vs WGS, CNV figures.
5. `05_fetch_regions.sh <lib> <name> <regions...>`: streams regions of the remote scRNA BAM (presigned URL with the
   local .bai) to `$TMP/bam/`.
   - Run for chr17, chr13 and chr9 in both libraries.
   - Also run for "points" (±100 bp windows at the somatic sites on chr1, chr2, chr3 and chr16). The points BAM was
     then `samtools sort`ed and indexed.
6. `$PY 06_allele_counts.py discover <chrom>`, then `$PY 06b_candidates.py <chrom>`, then
   `$PY 06_allele_counts.py collect $TMP/cand_<chrom>.tsv <chrom>`, for chr9, chr17 and chr13.
   - Also run `$PY 06_allele_counts.py collect $TMP/somatic_pos.tsv somatic`.
7. `$PY 07_genotype_labels.py`: germline-het filter, cross-library phasing, per-arm mixture, somatic molecules,
   combined labels.
8. `$PY 08_readouts.py`: readout tables and the dot plot.
9. `$PY 09_heterogeneity_figures.py`: malignant subclusters, dropout model, UMAP and violin figures, per-barcode
   annotation tables.
10. `$PY 10_report_tables.py`: markdown tables for the report.

Runtime is about 40 min of compute, plus about 35 min of BAM streaming.

## Bytes transferred from S3 (read-only)
These are estimates from the BAI linear-index spans of the fetched regions; process network counters were not used.

| item | GB |
|---|---:|
| KH022-1 chr17 / chr13 / chr9 | 1.32 / 0.56 / 1.06 |
| KH022-1-1 chr17 / chr13 / chr9 | 1.27 / 0.55 / 1.02 |
| point windows (both libraries) | < 0.01 |
| aborted first KH022-1 chr13 stream (restarted) | about 0.07 |
| BAM headers, reference faidx slices, HRR VCF | < 0.01 |
| **total** | **about 5.85 GB** (cap 10 GB) |

BioMart and Ensembl REST queries came to about 18 MB. Nothing was written to S3. There were no git operations and no
repo code edits.
