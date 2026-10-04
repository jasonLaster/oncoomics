# Step 7: report provenance + reconciled somatic findings (PRIVATE)

PRIVATE patient derivatives; git-ignored (`private/`). Never commit/publish. Regional BAMs carry germline genotypes and read names.
Research prioritization only. Nothing was sent to anyone; the questions file is a draft.

Read: `provenance_report.md` (findings), `reconciled_somatic_findings.md` (per-variant status, drop list),
`questions_for_goodfire_and_pipeline_author.md` (draft questions).

## Files

- `results/variant_panel_raw.json` (149 claimed variants -> GRCh37 SPDI candidates; `.recoder_cache.json` raw Ensembl replies),
  `results/variant_panel_sites.json` (+ GRCh38 liftover, scan windows), `results/regions_grch37.bed`, `results/regions_grch38.bed` (196 each)
- `results/audit_results.json` (every candidate site x 5 BAMs + local scans), `results/reconciled_table.tsv|.md`, `results/status_summary.json`
- `results/evee_pdf_text.txt` (pdftotext -layout of the EVEE PDF), `results/bytes_transferred_via_proxy.json`, `results/regional_bam_sha256.txt`
- `regional_bams/{tumor_exome,normal_exome,rna_sorted,tumor_wgs,normal_wgs}.bam(+.bai)` (35 MB total)
- `scripts/`: `01_variant_panel.py` (panel + Ensembl GRCh37 variant_recoder, all transcripts), `01b_codons.py` (unused alternative resolver,
  aborted), `02_sites.py` (SPDI -> sites, pyliftover hg19->hg38, BEDs), `02b_extract.sh` (region streaming), `range_counting_proxy.py`
  (copied from step 3), `03_audit.py` (fragment-level counts + scans), `04_summarize.py`, `05_write_tables.py`

## Inputs (read-only)

- Exome/RNA: `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/E019_S01/`
  `DNA_Pipeline/Alignments/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bam`, `...DNA_E019_S05_Vial1_normal_dna_aligned_recal.sorted.bam`,
  `RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.sorted.bam` (version ntUadPKrIcUDmSfTqyk37GClAHg8Y8CC). Indexes reused from step 3 scratch.
- WGS: `s3://diana-omics-private-results-172630973301-us-east-1/runs/subject01/diana-wgs-hrd-20260716T033101Z/deterministic/inputs/`
  `tumor.markdup.bam` (51,081,679,103 B, version APPI0V_GH4Jzi4TKtDOnAtG2SPappDHS) and `normal.markdup.bam` (55,978,126,326 B, version
  xXSOcffjAvujaB0wpWcy6kq9FH_r1_0I); indexes = local copies in `private/evee/deep-20261003/` (sizes match S3).
- Source reports: `private/evee/deep-20261003/source_reports/*`; repo early look `results/diana_wgs_hrd/early-look-intersected-20260716T150517Z/`.

## Commands (P = this dir, S = scratchpad/step7)

```bash
pdftotext -layout source_reports/08-11-wgs-evee-variant-interpretation-report.pdf $S/evee.txt; pdfinfo ...
# provenance search
git grep -l -F "<pattern>" $(git rev-list --all)        # DRF-PSN49561, 16,000, two independent, Strelka, HRD score of 62, LST 27, 607, software setting, Soft Star, K2 supports
mdfind -name drf-psn49561; mdfind -name evee; mdls -name kMDItemWhereFroms ~/Downloads/DRF-PSN49561_Analysis_Summary.md ...
find <repo, worktrees, /private/tmp/diana-*, ~/Downloads, vault diagnostics> -iname '*.vcf*' -o -iname '*.maf*' -o -iname '*somatic*' ...
aws s3 ls s3://<bucket> --recursive --region <r>         # 12 buckets
aws s3api list-object-versions --bucket <b> --region <r>  # noncurrent + delete markers; get-bucket-versioning; get-bucket-lifecycle-configuration
# variant panel
python3 scripts/01_variant_panel.py results/variant_panel_raw.json         # Ensembl GRCh37 REST (gene symbol + protein change only)
uv run --no-project --python 3.11 --with pyliftover python scripts/02_sites.py $P $S/hg19ToHg38.over.chain.gz
aws s3 presign <bam> --expires-in 43200 --region us-east-1   # 5 URLs -> $S/urls.json (deleted afterwards)
python3 scripts/range_counting_proxy.py $S/urls.json 18777 $S/bytes_counter.json &
scripts/02b_extract.sh $P $S 18777                         # samtools view -b -M -L regions.bed "http://127.0.0.1:18777/<k>.bam##idx##<bai>"
uv run --no-project --python 3.11 --with pysam python scripts/03_audit.py $P
python3 scripts/04_summarize.py $P; python3 scripts/05_write_tables.py $P
# spot checks: samtools view on regional BAMs at CBL (11:119149356 / chr11:119278646); UCSC getData hg19 sequence for the repeat
# stats: scipy mannwhitneyu on WGS tumor depth / tumor:normal depth ratio (EVEE-only vs Altera sites)
```

## Bytes transferred (S3 -> this machine, proxy-counted)

| BAM | bytes | requests |
|---|---|---|
| tumor exome | 239,206,428 | 148 |
| normal exome | 271,450,168 | 228 |
| tumor RNA (raw STAR) | 347,275,292 | 168 |
| tumor WGS | 136,904,732 | 147 |
| normal WGS | 152,371,228 | 146 |
| **total** | **1,147,207,848 (~1.15 GB)** | |

Not counted (small): S3 listings/version listings/head-object metadata; UCSC chain `hg19ToHg38.over.chain.gz` (227,698 B) and one
30-bp hg19 sequence query; Ensembl REST (gene symbols + protein changes + public coordinates only). No index downloads (reused).
No whole BAM downloaded. Presigned URLs deleted and proxy stopped at the end.

## Environment / gotchas

samtools 1.23.1; aws-cli 2 (always `--region us-east-1` for presign); Python 3.11 via uv with pysam/pyliftover/scipy.
- Ensembl GRCh37 `variant_recoder` with gene-symbol HGVS is slow (~10-40 s per id) and can time out on batched POSTs; use parallel GETs
  with a cache. It returns LRG_ accessions alongside NC_; keep NC_ only.
- `pgrep -f <script>` inside a `zsh -c` wait loop matches the loop's own command line and never exits.
- Choosing "best candidate" among transcript-alternative SNVs: for EVEE sites force the reported GRCh38 allele (otherwise ties pick
  the wrong base, e.g. RXRA C>G vs reported C>A).
