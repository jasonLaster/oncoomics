# Step 11: germline predisposition cross-check (private)

PRIVATE patient-data derivatives under git-ignored `private/` (verified: `.gitignore:64:private/`). Never commit or publish.
Research cross-check only; NOT a clinical germline test. Anything significant needs CLIA confirmation and genetic counseling.

Read first: `germline_report.md`. Machine-readable: `variants_annotated.tsv`, `coverage_by_gene.csv`, `results/*`.

## Sources and versions

| Item | Source / version |
|---|---|
| Normal WGS | `s3://diana-omics-private-results-172630973301-us-east-1/runs/subject01/diana-wgs-hrd-20260716T033101Z/deterministic/inputs/normal.markdup.bam` (GRCh38 UCSC analysis set); tumor `tumor.markdup.bam`; reference `reference/reference.fa(.fai)`. Size/ETag/VersionId in `results/input_objects.json` |
| Normal exome | `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/E019_S01/DNA_Pipeline/Alignments/DNA_E019_S05_Vial1_normal_dna_aligned_recal.sorted.bam` (hs37d5); tumor `DNA_E019_S01_tumor_dna_aligned_recal.sorted.bam` |
| Gene list | NCCN Genetic/Familial High-Risk Assessment (Breast/Ovarian/Pancreatic; Lynch genes from the Colorectal guideline) high/moderate-penetrance genes + requested HR/Fanconi genes (29 genes; tier in `coverage_by_gene.csv`) |
| Transcripts | Ensembl REST (release current on 2026-10-03) canonical = MANE Select for all 29 genes (RefSeq match in `regions/transcripts.json`). GRCh37 coordinates = GRCh38 exon/CDS boundaries lifted with the UCSC hg38ToHg19 chain (pyliftover 0.4.1), exon lengths asserted unchanged |
| GRCh37 reference sequence | UCSC REST `getData/sequence` hg19 for the 387 fetch windows (primary-chromosome sequence identical to hs37d5); padded with N to the hs37d5 contig lengths |
| ClinVar | NCBI FTP `vcf_GRCh38/clinvar.vcf.gz` (fileDate 2026-09-28, md5 707723f0a08d1d711eb1c1de660a9098 verified) and GRCh37 (md5 321f3d9e9532c63149eb9ccc5b840a52) |
| gnomAD | v4.1 exomes sites VCF (AWS Open Data `gnomad-public-us-east-1`), whole target regions only (coding exons +/-20 bp of all 29 genes); frequency INFO fields kept |
| Founder variant coordinates | Ensembl `variant_recoder` on 15 textbook HGVS names (public; `results/founder_variants_grch38.json`) |
| Tools | samtools/bcftools/htslib 1.23.1; uv Python 3.11.15 with pysam 0.24.x, pyliftover 0.4.1; aws-cli 2.34.63 |

Privacy: no patient sequence or patient-derived variant was sent to any external service. gnomAD was queried by gene region
(identical for any person); ClinVar was downloaded whole; VEP REST was NOT used (local MANE annotator `scripts/txlib.py`, validated on
17 known variants in `results/txlib_selftest.json`).

## Commands (P = this dir, S = scratchpad/step11)

```bash
export AWS_DEFAULT_REGION=us-east-1
uv run --no-project --python 3.11 --with pyliftover python scripts/01_gene_regions.py $P   # regions/*.bed, transcripts.json
python3 scripts/merge_bed.py regions/fetch_grch38.unsorted.bed regions/fetch_grch38.bed      # same for grch37
aws s3 cp <each .bai and reference.fa.fai> $S/idx/ --region us-east-1; aws s3 presign <bam|fa> --expires-in 43200 --region us-east-1  # -> $S/urls.json
python3 scripts/range_counting_proxy.py $S/urls.json 18811 $S/bytes_counter.json &          # counts every relayed byte
bash scripts/02_fetch_regions.sh $P $S 18811        # samtools view -M per BAM over fetch windows; reference slices via faidx
#   (wgs_normal was first fetched without -M -> 226 duplicate records from adjacent windows; removed by scripts/dedup_sorted_bam.py)
python3 scripts/03_build_refs.py $P $S              # padded full-coordinate GRCh38 / hs37d5 references (N outside windows)
bash scripts/04_gnomad_subset.sh $P $S              # gnomAD v4.1 exome target subset
bash scripts/05_call.sh $P $S                       # bcftools mpileup (-q20 -Q20, AD/DP) + call -m, pass A default, pass B --indels-cns; norm -m-both
python3 scripts/06_coverage.py $P $S                # coverage_by_gene.csv, results/coverage_by_exon.csv
uv run ... python scripts/07_annotate.py $P $S      # variants_annotated.tsv, results/calls_summary.json (forced genotyping in 4 BAMs)
uv run ... python scripts/08_cn_screen.py $P $S     # results/cn_*.csv|json
python3 scripts/09_founder_lookup.py $P             # results/founder_variants_grch38.json
uv run ... python scripts/10_somatic_check.py $P $S # results/somatic_confirmation.json
uv run ... python scripts/11_txlib_selftest.py $P $S
bash scripts/12_clinvar_plp_scan.sh $P $S           # 12a select + 12b join: results/clinvar_plp_scan*.{json,tsv}
uv run ... python scripts/13_indel_locus_detail.py $P $S chr2 47414419 MSH2_c942p3; uv run ... python scripts/14_msh2_tract_reads.py $P $S
uv run ... python scripts/15_lowvaf_followup.py $P $S; uv run ... python scripts/16_founder_check.py $P $S
python3 scripts/17_finalize.py $P                   # review notes + results/concordance_summary.json
```

## Bytes transferred

| Source | Bytes | How measured |
|---|---|---|
| S3 private: normal WGS regions | 261,423,132 | counting proxy (first fetch without -M: per-window seeks) |
| S3 private: tumor WGS regions | 73,269,276 | counting proxy |
| S3 raw-inputs: normal exome regions | 145,752,092 | counting proxy |
| S3 raw-inputs: tumor exome regions | 259,391,516 | counting proxy |
| S3 private: reference.fa slices (387 windows) | 25,165,824 | counting proxy |
| S3: 4 BAI + reference.fa.fai (whole files) | 28,850,762 | file sizes |
| **S3 total** | **793,852,602 (~0.79 GB; cap 5 GB)** | |
| Public: ClinVar GRCh38 + GRCh37 VCF (+tbi, md5) | ~397,440,000 | file sizes |
| Public: gnomAD v4.1 exome region subsets | not metered (15 per-chromosome indexes ~1 MB + 546 range queries; kept subset 2.7 MB) | htslib remote |
| Public: UCSC REST hg19 sequence (387 windows, 0.73 Mbp), Ensembl REST lookups | <5 MB | estimate |

Regional BAMs, padded references, ClinVar and the gnomAD subset stay in the scratchpad (), not here.
