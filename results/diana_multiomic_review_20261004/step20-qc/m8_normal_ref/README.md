# Step 19 QC, module 8: clean normal-breast epithelial reference

The results are in `report.md`. This file covers how to reproduce them.

## Commands

```bash
cd private/analysis/step19-qc/m8_normal_ref/scripts
CACHE=/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/f61c14bf-e23e-4829-a09a-24be63d09400/scratchpad/m8
OLD=/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad

# 0. downloads (done once, 2026-10-05; curl 6-way parallel, then single retries for 3 files that returned an
#    HTTP 403 page; one of them needed ftp://). URLs are in ../sources.lock.json.
#    Destination: data/raw/scrna/GSE161529/ (git-ignored by `data/raw/*` in .gitignore)
curl -sS -o ../tables/GSE161529_series_matrix.txt.gz \
  https://ftp.ncbi.nlm.nih.gov/geo/series/GSE161nnn/GSE161529/matrix/GSE161529_series_matrix.txt.gz
./run.sh 00_sources_lock.py                    # sample selection, sizes, sha256 -> ../sources.lock.json
./run.sh 01_process_public.py "$CACHE"         # ~3.5 min, 6 processes
./run.sh 02_diana_pseudobulk.py "$OLD" "$CACHE"  # ~1 min
./run.sh 03_compare.py "$CACHE"                # ~1 min
./run.sh 04_figure.py
```

`run.sh` pins the environment:

```
OMP_NUM_THREADS=3 uv run --no-project --python 3.11 --with pandas==2.2.3 --with numpy==2.1.3 --with scipy==1.14.1 \
  --with scanpy==1.10.4 --with anndata==0.11.4 --with leidenalg==0.10.2 --with igraph==0.11.8 \
  --with scikit-learn==1.5.2 --with scikit-image==0.24.0 --with h5py==3.12.1 --with matplotlib==3.9.2 python <script>
```

- **Versions.** uv 0.11.26, Python 3.11.15, packages as pinned above.
- **Runtime.** About 6 minutes wall-clock in total on the 18-core machine.
- **Seeds.** Every random step is seeded: scrublet, PCA, neighbors, Leiden, score_genes (0), and the donor bootstrap (`default_rng(0)`).

| script | what it does |
|---|---|
| `00_sources_lock.py` | Parses the GEO series matrix, picks the 12 samples, records URL / bytes / sha256 / GEO metadata. |
| `01_process_public.py` | Per sample, with no integration across samples. **QC:** ≥500 genes, ≥1,000 UMI, <20% MT, genes ≤ 99.5th percentile, then scrublet doublets removed. **Clustering:** normalize, log1p, 2,000 HVG, PCA 30, kNN 15, Leiden 1.0. **Labels:** each cluster gets the highest mean `score_genes` module across 8 marker sets. **Sensitivity:** relabelling without any candidate gene in the marker sets. **Output:** per-donor per-lineage pseudobulks over all 33,538 genes. |
| `02_diana_pseudobulk.py` | Builds KH022 genome-wide matrix pseudobulks. **Groups:** malignant; myoepithelial (non-malignant); L2 `epithelial_luminal_HS` (non-malignant, 79 nuclei). All use qc_pass & ~dbl_union. **Ambient:** the empty-droplet (10-100 UMI) profile per library. |
| `03_compare.py` | **Tests:** A (exon-only, ambient-corrected, no bias model), B (step15/m4 bias model) and W (same-chemistry within-sample). **Calibration:** genome-wide and candidate nulls. **Outputs:** verdicts, `per_gene.csv`, `scorecard_column.csv`. |
| `04_figure.py` | Draws `figures/fold_vs_normal_lineages.png`. |

## Inputs

**Public data.** GSE161529 (Pal et al. 2021, EMBO J 40:e107333). Selected samples:

| Group | Samples | Population |
|---|---|---|
| Normal | 8 "Epithelial" samples, GSM4909256/60/62/64/67/69/73/75 | EpCAM-sorted total epithelium (all lineages) |
| BRCA1-carrier pre-neoplastic | 4 "Total" samples, GSM4909277-80 | Total; no epithelial-sorted carrier samples exist |

- **Download size:** 24 files, **482,493,269 bytes** (460 MiB) of new data, plus the 7,153-byte series matrix. That is under the brief's 500 MB cap.
- **Failed attempts:** three attempts returned 980-byte HTML error pages, which were discarded.
- **Already local:** the shared `GSE161529_features.tsv.gz` was downloaded on 2026-10-02 for step 15.
- **Checksums:** sha256 for every file is in `sources.lock.json`.
- **Data flow:** no patient data left the machine.

**Patient data and earlier modules** (paths from `../BRIEF.md`):
- KH022 filtered and raw `*_feature_bc_matrix.h5`, under `$OLD/step2b/data/<lib>/`.
- `step6-scrna-malignant/barcode_annotations_<lib>.csv.gz`.

**Small inputs** (md5):

| file | md5 |
|---|---|
| `step19-qc/candidate_genes.tsv` | c7d8dfd3ba361932266555b298572716 |
| `step19-qc/m1_counting/exonic_only_by_group.csv` | abbcb979e86fb7ae41937584a39168eb |
| `step19-qc/m4_stats/tables/genes_master.csv.gz` (bias_hat) | 3c9180e1d8fdbfa03801cde1d8f78b43 |
| `step19-qc/m4_stats/tables/candidate_summary.csv` (bias_sd) | 3ee60568943e4ed9a51ec9fd4933abbe |
| `step19-qc/m3_ambient/tables/candidate_robustness_verdicts.csv` (tumor observed / ambient) | 0607f031522f0b767de85a2a7834f4fa |

## Outputs

| file | content |
|---|---|
| `per_gene.csv` | One row per candidate (47). The columns are explained in `report.md` §6. |
| `scorecard_column.csv` | gene, G11_vs_normal_breast, fold_vs_LP, fold_vs_ML, n_donors_exceeded (test A, ambient-corrected) |
| `sources.lock.json` | URLs, bytes, sha256 and GEO metadata of every downloaded file |
| `tables/lineage_counts.csv`, `qc_per_sample.csv` | Cells per lineage per donor; QC summary |
| `tables/cluster_labels.csv`, `marker_means_by_lineage.csv`, `label_sensitivity.csv` | Annotation evidence |
| `tables/per_gene_per_donor_cpm.csv` | Public CPM per donor and lineage for every candidate |
| `tables/calibration_nulls_genomewide.csv`, `fdr_by_fold_threshold*.csv` | Genome-wide same-lineage nulls for test B |
| `tables/calibration_myo_vs_public_basal_candidates.csv` | Candidate-level null for test A (Diana myoepithelium as query) |
| `tables/lineage_marker_crosscheck.csv` | Canonical markers in Diana HS / myo / tumor vs public LP / ML / basal |
| `figures/fold_vs_normal_lineages.png` | Per-donor folds (A) and within-sample folds (W) |

Cached pseudobulks (`public_pb.pkl`, `diana_pb.pkl`) live in the scratchpad (`$CACHE`), not in the repo.
