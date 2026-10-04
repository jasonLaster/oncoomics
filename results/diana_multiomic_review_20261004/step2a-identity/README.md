# step2a-identity: how to reproduce (private)

Results are in `identity_report.md`. Work dir (subset BAMs, indexes, intermediates):
`/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step2a/` (`$WORK`).
It holds patient germline reads; delete it when no longer needed.

## Versions
samtools 1.23.1, bcftools 1.23.1 (not used for calls), Python 3.11 venv (`uv venv --python 3.11 $WORK/.venv`;
`uv pip install pysam numpy pandas scipy vireoSNP`): pysam 0.24.1, numpy 2.4.6, pandas 3.0.6, scipy 1.17.1, vireoSNP 0.5.9.
AWS CLI default credentials. Presigned URLs **must** use `--region us-east-1`. URLs were written to `$WORK/urls.sh` (chmod 600, 12 h expiry).

## Steps (PY=$WORK/.venv/bin/python; run from this directory)
1. Download the small files to `$WORK/idx/`: the four `.bai` (L1, L2, normal, tumor), `sample_filtered_barcodes.csv` for both libraries, and `reference.fa.fai`.
   Write the BAM header contig order to `idx/L1.contigs.txt`. Make `idx/L{1,2}.bc.txt` (barcode column of the csv).
2. `$PY 01_select_tiles.py $WORK 1500`. Picks 1,500 random autosomal 16-kb tiles with scRNA leaf-bin span 0.5-2 MB, excluding MHC/IG/TCR, in 2 batches.
   Writes `tiles.tsv` and `beds/b{0,1}.chrN.bed` (seed 20261003).
3. Reference slices: `samtools faidx --fai-idx idx/ref.fa.fai "$REF_URL" -r ref/chrN.regions -o ref/chrN.fa`.
4. `02_fetch_subset.sh $WORK <L1|L2|N|T> <batch> <chrom>` (run under `xargs -P`). Each call is `samtools view -M -L tiles.bed URL##idx##local.bai`:
   - scRNA: `-q 255 -F 0x904 -D CB:called_barcodes`, with CR/CY/UR/UY/RG dropped.
   - WGS: `-q 20 -F 0xF04`.
   - Tumor: batch 0 only.
5. `$PY 03_pass1.py 0 1`. Read-level A/C/G/T counts (BQ >= 20) per tile position for normal and both libraries.
6. `$PY 04_pass2.py 0 1`. Selects candidate sites and collects UMI-deduplicated per-cell observations.
7. `$PY 05_assemble.py`. Writes `sites_all.tsv.gz` and the normal genotype calls.
8. `$PY 06_identity.py` -> `identity_stats.json`, `sites_identity_L{1,2}.tsv.gz`.
9. `$PY 07_pooled_pseudobulk.py` (read-level, descriptive) and `$PY 07b_pooled_umi.py` (primary pooled test) -> `pooled_pseudobulk.json`, `pooled_umi.json`, `sites_hom_discordant.tsv.gz`.
10. `$PY 08_percell.py` (per-cell hom-alt discordance and vireo K=1..3) -> `percell_stats.json`. `$PY 08b_vireo_spikein.py L1` -> `vireo_spikein_L1.json`.
11. `$PY 09_loh.py` -> `loh_by_chrom.tsv`, `sites_tumor_het_af.tsv.gz`.

Helpers: `common.py`, `bai_tiles.py`, `percell_lib.py`.

## Bytes transferred from S3 (estimate)
Per-process `nettop` counters turned out to be unreliable (logged in `$WORK/logs/net.log`), so these figures are estimated from BAI chunk spans of the fetched tiles plus measured file sizes:

| item | GB |
| --- | --- |
| KH022-1 tiles (1,500) | 1.33 |
| KH022-1-1 tiles (1,500) | 1.29 |
| normal WGS tiles (1,500) | 0.43 |
| tumor WGS tiles (750) | 0.22 |
| four .bai + barcodes + fai + md5 lists | 0.06 |
| reference slices | 0.03 |
| seqz header peek (chr21, stream cut early) | <0.05 |
| throughput tests (curl range reads) and KH022-1-1 index check (60 MB BAM head) | about 0.39 |
| **total** | **about 3.8 GB** (allow up to about 4.5 GB for BGZF/higher-bin overhead) |

That is well under the 15 GB cap. No whole BAM was downloaded, nothing was written to S3, and there were no git operations.

## Outputs here
`identity_report.md`, `identity_stats.json`, `pooled_umi.json`, `pooled_pseudobulk.json`, `percell_stats.json`, `vireo_spikein_L1.json`, `loh_by_chrom.tsv`, and the `sites_*.tsv.gz` tables. The tables carry germline genotypes, so keep them private.
