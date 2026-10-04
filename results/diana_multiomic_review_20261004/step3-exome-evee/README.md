# Step 3: deep-exome audit of the ten EVEE-report alleles (private)

PRIVATE patient data derivatives. This directory is git-ignored (`private/`); never commit or publish it. The regional BAMs contain
germline genotypes (re-identifiable) and read names. Research prioritization only; no clinical claim.

Read first: `exome_evee_audit.md` (summary tables, interpretation, limits). Machine-readable: `site_metrics.csv` (one row per
site x assay x policy; 13 loci), `site_summary.csv`, `results/*.json`.

## What was done

1. GRCh38 -> GRCh37 liftover of the ten sites (UCSC hg38ToHg19 chain through pyliftover), REF validated against hg19 sequence from the
   UCSC REST API, plus an independent GRCh37 Ensembl VEP check of gene/protein/HGVSc (`sites_grch37.csv|json`, `results/vep_grch37_validation.json`).
2. Streamed 10 windows from each of the tumor exome (+/-50 kb) and normal exome (+/-50 kb) and the two tumor RNA BAMs (+/-5 kb), plus 4
   extra loci (BRCA2 and PIKFYVE controls, PPARD codon-415 candidate, RB1CC1 reported coordinate; +/-5 kb), via presigned URLs and
   `samtools view` (no whole BAM downloaded).
3. Fragment-level audit with the repo's rules (duplicates/secondary/supplementary/QC-fail excluded, overlapping mates collapsed by
   read-group + query name, discordant mates removed; three policies relaxed 20/20/0, primary 30/30/5, strict 40/30/10; gate =
   `diana_omics.variant_read_audit.evidence_state`, imported read-only). `scripts/exome_lib.py` re-implements `count_fragments` to add
   orientation/position/soft-clip/indel/NM metrics and **asserts equality with the repo module** for every site x policy x sample.
4. Unfiltered pileup (every read filter disabled), +/-10 bp tumor-vs-normal non-reference scan, library-level noise with F1R2/F2R1
   orientation, exome depth-ratio + het-SNP allele balance (qualitative copy-number context), RNA allelic counts with an RNA noise baseline.

## Inputs (read-only; `results/input_objects.json` has size/ETag/VersionId)

Bucket `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/E019_S01/`
- `DNA_Pipeline/Alignments/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bam` (+ `.sorted.bai`; 330,909,042 mapped reads from idxstats)
- `DNA_Pipeline/Alignments/DNA_E019_S05_Vial1_normal_dna_aligned_recal.sorted.bam` (+ `.sorted.bai`; 137,130,618 mapped)
- `RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.sorted.bam` (raw STAR) and `...aligned.recal.sorted.bam` (GATK SplitNCigar/PrintReads), each `.bam.bai`
- Site list: `private/evee/deep-20261003/plan.json` (GRCh38); report text `source_reports/08-11-...pdf`; Altera table `source_reports/05-12-altera-tumor-profile.md`.

Header facts used: hs37d5 (86 contigs, `1..22,X,Y,MT,...`), 150 bp paired reads, Sentieon BWA + realigner, ACE4 capture regions, **no duplicate
flags anywhere and fragments essentially all coordinate-unique (dup_factor 1.000-1.0014)** -> duplicates appear to have been removed upstream.

## Environment

macOS arm64; samtools/htslib 1.23.1; aws-cli 2.34.63 (use `--region us-east-1`; this profile's default region is us-west-1 and produces
presigned URLs on the wrong host); uv; Python 3.11.15 with pysam 0.24.1, numpy 2.4.6, pandas 3.0.6, scipy 1.17.1, pyliftover 0.4.1.
`PYTHON="uv run --no-project --python 3.11 --with pysam --with numpy --with pandas --with scipy --with pyliftover python"`

## Exact commands (order; `P` = this directory, `S` = scratchpad/step3, `scripts/` = this repo-external script dir)

```bash
# 0. presigned URLs (12 h) + the four BAIs (the only whole-file downloads) -> $S/idx/{tumor_exome,normal_exome,rna_recal,rna_sorted}.bai, $S/urls.json
export AWS_DEFAULT_REGION=us-east-1
aws s3 cp $B/DNA_Pipeline/Alignments/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bai $S/idx/tumor_exome.bai   # likewise normal_exome / rna_recal / rna_sorted
aws s3 presign $B/<bam> --expires-in 43200 --region us-east-1                                                   # one per BAM -> urls.json
# 1. byte-counting local range proxy (streams; forwards only the four presigned URLs)
python3 scripts/range_counting_proxy.py $S/urls.json 18765 $S/bytes_counter.json &
# 2. liftover + validation
$PYTHON scripts/01_liftover.py $P                          # -> sites_grch37.csv|json
$PYTHON scripts/00b_derive_extra_sites.py $P               # -> extra_sites_grch37.json  (Ensembl REST + UCSC)
$PYTHON scripts/00c_vep_grch37_validation.py $P            # -> results/vep_grch37_validation.json
# 3. stream regions (samtools view -b "http://127.0.0.1:18765/<key>.bam##idx##$S/idx/<key>.bai" <regions>)
scripts/02_extract_regions.sh $P $S/idx 18765              # tumor/normal +/-50 kb, RNA +/-5 kb (10 sites)
KEYS="rna_recal rna_sorted" scripts/02b_extract_rna.sh $P $S/idx 18765   # retry wrapper (first RNA attempt hit a transient libcurl error 52)
scripts/02c_extract_extra.sh $P $S/idx 18765               # 4 extra loci, +/-5 kb, DNA + RNA
# 4. analysis (PYTHONPATH=scripts so exome_lib imports; repo module is imported read-only from /Users/.../diana-omics/src)
PYTHONPATH=scripts $PYTHON scripts/03_audit_dna.py $P            # ten sites, 3 policies, tumor+normal, parity assertions -> results/dna_site_results.json
PYTHONPATH=scripts $PYTHON scripts/03b_neighborhood_check.py $P  # +/-4 bp composition (coordinate-shift sanity check)
PYTHONPATH=scripts $PYTHON scripts/03c_extra_raw_scan.py $P      # extras + unfiltered pileups + +/-10 bp scans
PYTHONPATH=scripts $PYTHON scripts/03d_incidental_somatic_like.py $P
PYTHONPATH=scripts $PYTHON scripts/04_cn_noise.py $P             # copy-number context, noise/orientation, window somatic-like scan
PYTHONPATH=scripts $PYTHON scripts/05_rna.py $P; $PYTHON scripts/05b_rna_noise.py $P
# independent engine check: samtools mpileup -r <c>:<p>-<p> -Q0 -q0 -B -x -A --ff 0 -d 10000000 -O on the regional BAMs -> results/samtools_mpileup_crosscheck.json (matches pysam unfiltered pileup, 20/20)
$PYTHON scripts/06_build_tables.py $P                            # site_metrics.csv, site_summary.csv
$PYTHON scripts/07_write_report.py $P                            # exome_evee_audit.md
```

## Files

- `exome_evee_audit.md`, `site_metrics.csv`, `site_summary.csv`, `sites_grch37.csv|json`, `extra_sites_grch37.json`
- `regional_bams/`: `tumor_exome_sites_pm50kb.bam`, `normal_exome_sites_pm50kb.bam`, `rna_recal_sites_pm5kb.bam`, `rna_sorted_sites_pm5kb.bam`,
  and the `*_extra_sites_pm5kb.bam` counterparts (each + `.bai`; SHA-256 in `results/regional_bam_sha256.txt`, 94 MB total)
- `results/`: raw JSON per analysis, `input_objects.json`, `bytes_transferred_via_proxy.json`, idxstats, `exome_context.json`
- `scripts/`: everything above, including the counting proxy

## Bytes transferred (S3 -> this machine)

| item | bytes |
|---|---|
| 4 BAM indexes (tumor exome 6,226,096; normal exome 4,547,768; RNA recal 3,411,312; RNA sorted 12,571,960) | 26,757,136 |
| tumor exome BAM ranges (proxy-counted) | 79,495,280 |
| normal exome BAM ranges | 53,018,764 |
| RNA recal BAM ranges | 41,091,156 |
| RNA sorted BAM ranges | 42,270,776 |
| **counted total** | **242,633,112 (about 0.24 GB)** |

Also transferred but not counted: a first version of the counting proxy buffered an open-ended range response in memory until I killed it
(about 2-3 minutes; peak process RSS 225 MB), so well under 0.3 GB; four 28-byte curl probes. Total is far below the 5 GB budget; no whole BAM was
downloaded. External API calls (UCSC chain/sequence, Ensembl REST/VEP) carried only gene symbols, coordinates and alleles of public reference positions.

## Gotchas worth remembering

- The exome BAMs have **no duplicate flags** and are essentially coordinate-unique, so `is_duplicate` filtering is a no-op there; do not read that as 'duplicates are present'.
- The recal RNA BAM has BQSR-compressed base qualities (max ~Q33); Q30 policies drop most ALT bases there (BRCA2 control: primary 0/318 vs relaxed 239/586). Use the raw STAR BAM or BQ>=20.
- Strand-bias tests are unreliable in this exome (REF strand mix is skewed at exon edges; real BRCA1/BRCA2 controls fail them); use F1R2/F2R1 and read-position metrics.
- Library noise (C>T/G>A/G>T/C>A 3-8x normal, oxidation-style orientation bias) puts the practical calling floor near 1% VAF.
- `urls.json` (presigned URLs, 12 h) and the proxy were deleted/stopped at the end; nothing here needs S3 to re-run the analysis scripts (only steps 0-3 do).
