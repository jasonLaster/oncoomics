# Module 1: how to reproduce

Set `SP=<session scratchpad>/m1`. Run each Python step with:

```bash
uv run --no-project --python 3.11 --with pandas==2.2.3 --with numpy==2.1.3 --with h5py==3.12.1 --with scipy==1.14.1 --with pysam==0.22.1 --with matplotlib==3.9.2 python <script>
```

Run order:
1. `00_gene_table.py $SP/gene_table.tsv`
2. `00b_estimate_bytes.py $SP/gene_table.tsv $SP/KH022-1.header.sam`
3. `00c_ensembl_spans.py $SP/gene_table.tsv $SP/ensembl_spans.tsv`
4. `bash 01_fetch_regions.sh $SP/gene_table.tsv $SP/bam MALAT1`, run alongside `nettop_sampler.sh`. Repeat with
   `gene_table_ext.tsv` (CARD18_full, BRCA1_full).
5. `01b_transfer_accounting.py`
6. `02_count_bam.py`, once into `$SP/counts` and once into `$SP/counts_ext`.
7. `03_groups_reconcile.py`, once for each of those.
8. `04_annotation.py <gene table> step15/g23.gtf.gz $SP`
9. `05_detection_ceiling.py <gene table> step15/gene_features.csv $SP`
10. `06_write_exonic_by_group.py`, then `07_per_gene.py`, then `08_figures.py`.

**Environment**
- samtools/htslib 1.23.1.
- Public reference: Ensembl REST lookups by gene ID only.
- Runtime: fetch ~28 min (6 jobs in parallel), counting 4 min, groups and bootstrap ~3 min.

**Bytes transferred**
- **Why measured indirectly:** en0 totals are unusable because other modules streamed at the same time.
- **Main 106 regions:**
  - The .bai chunk estimate is 5.05 GB.
  - nettop per-process measurement on 33 regions came to 0.56× the estimate, which calibrates the total to ~2.8 GB.
  - Using measured values where sampled and estimates elsewhere gives 4.3 GB, the conservative figure.
- **Other fetches:** extension fetches 0.047 GB; test fetches ~0.1 GB. An aborted 5-minute probe of the remote
  molecule_info.h5 was not measured.
- **Total:** best estimate ~3 GB; upper bound ~4.5 GB plus the probe.

**Input checksums (sha256 prefixes)**
- candidate_genes.tsv 4f005f93
- annotations: L1 9ee8f336, L2 ae922259
- g23.gtf.gz 5d40060e
- gene_features.csv 3408ed81
- filtered h5: L1 250d0cbd, L2 ee50b8b0
- bai: L1 9044c00a, L2 dc5c962f
