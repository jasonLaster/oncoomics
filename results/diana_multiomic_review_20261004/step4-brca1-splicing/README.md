# step4-brca1-splicing: how this was produced

PRIVATE and git-ignored (`private/`). Never copy contents into tracked files. Read `brca1_splicing_report.md` first.

## Inputs (read-only S3; us-east-1)

Bucket prefix: `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/E019_S01/`

| Key | File | Size |
| --- | --- | --- |
| `RNA_Pipeline/Alignments/` | `RNA_E019_S01_tumor_rna_aligned.sorted.bam` (+`.bai`) = raw STAR 2.7.3a | 9.1 GiB (+12.0 MiB) |
| `RNA_Pipeline/Alignments/` | `RNA_E019_S01_tumor_rna_aligned.recal.sorted.bam` (+`.bai`) = STAR + GATK 3.4 IndelRealigner + SplitNCigarReads + PrintReads | 23.2 GiB (+3.3 MiB) |
| `DNA_Pipeline/Alignments/` | `DNA_E019_S01_tumor_dna_aligned_recal.sorted.bam` (+`.bai`) tumor exome | 41.7 GiB (+5.9 MiB) |
| `DNA_Pipeline/Alignments/` | `DNA_E019_S05_Vial1_normal_dna_aligned_recal.sorted.bam` (+`.bai`) normal exome | 19.6 GiB (+4.3 MiB) |

No whole BAM was downloaded. Only the four small index files (26,757,136 bytes in total) and the BRCA1 region `17:41190000-41290000` were streamed.

## Commands (exact)

```bash
export S=<scratchpad>/step4        # presigned URLs + indices; P=<repo>/private/analysis/step4-brca1-splicing
export AWS_DEFAULT_REGION=us-east-1   # IMPORTANT: the CLI default region here was us-west-1, which made presigned URLs fail (header read error)
B=s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/E019_S01
aws s3 cp $B/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.recal.sorted.bam.bai $S/idx/rna_recal.bam.bai
aws s3 cp $B/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.sorted.bam.bai       $S/idx/rna_raw.bam.bai
aws s3 cp $B/DNA_Pipeline/Alignments/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bai     $S/idx/tumor_wes.bai
aws s3 cp $B/DNA_Pipeline/Alignments/DNA_E019_S05_Vial1_normal_dna_aligned_recal.sorted.bai $S/idx/normal_wes.bai
aws s3 presign --region us-east-1 <bam s3 url> --expires-in 43200 > $S/urls_<name>.txt   # x4 (rna_raw, rna_recal, tumor_wes, normal_wes)
samtools view -H "<url>##idx##$S/idx/<name>.bai"                                          # headers only
S=$S OUT=$P/region_bams scripts/01_extract_regions.sh                                      # samtools view --no-PG -b ... 17:41190000-41290000
cd scripts && ./run_all.sh                                                                  # everything below, from the extracted region BAMs, ~40 s
```

`--no-PG` keeps the presigned URL (which embeds an access key id and signature) out of the output BAM headers; the four region BAMs were checked for `X-Amz` strings (none). The presigned URLs expire after 12 h and are not stored here.

`run_all.sh` runs: `00_build_reference.py` (bgzip FASTA, N except 17:41190000-41290000, filled from UCSC hg19 chr17 which equals GRCh37/hs37d5 chr17), `02_gene_model.py`, `04_variant_alleles.py`, `05a_genotype_normal.sh` (bcftools mpileup -q20 -Q20 | call -mv), `05_ase.py`, `03_junctions.py`, `03b_sequence_rescore.py`, `06_sashimi.py`, `07_evidence_text.py`, `09_summary_numbers.py`. `08_estimate_bytes.py` estimates S3 bytes from the BAI chunk spans.

Python: `uv run --no-project --python 3.11 --with pysam --with numpy --with pandas --with scipy --with pyliftover --with matplotlib` (Python 3.11.15, pysam 0.24.1, numpy 2.4.6, scipy 1.17.1, matplotlib 3.11.2, pandas 3.0.6). Tools: samtools 1.23.1 (htslib 1.23.1), bcftools 1.23.1, aws-cli 2.34.63. Public reference data pulled: UCSC `hg38ToHg19` chain (via pyliftover), UCSC REST `ncbiRefSeq` hg19 chr17:41190000-41290000 (saved in `reference/`), UCSC REST hg19 sequence for the same window.

## Bytes transferred (estimated; samtools does not report them)

| Item | Bytes |
| --- | --- |
| 4 BAM index files (exact) | 26,757,136 |
| Region data, rna_raw / rna_recal / tumor_wes / normal_wes (BAI chunk spans + one 64 KiB block per chunk; an upper bound) | <= 5.1 / 4.5 / 12.2 / 7.7 MB |
| BAM headers (2 `samtools view -H` calls plus the four region fetches) | < 1 MB |
| Public reference downloads (chain file, UCSC JSON ~0.3 MB, sequence 0.1 MB) | a few MB |
| **Total** | **about 56 MB for S3 (0.06 GB), far under the 4 GB budget** |

Extracted region BAMs on disk: 1.7 MB (rna_raw), 4.3 MB (rna_recal), 11.0 MB (tumor_wes), 6.6 MB (normal_wes).

## Layout

- `brca1_splicing_report.md` - headline, tables, limitations
- `junction_counts.csv` - every BRCA1-locus junction, classified vs the c.81-1 acceptor, fragments under six read policies (P1-P6)
- `allele_counts.csv` - somatic variant and germline het SNP allele counts, tumor RNA / tumor exome / normal exome, several policies
- `figures/brca1_exon3_sashimi.png` - sashimi-style arcs, acceptor zoom with sequence, per-exon calibration
- `evidence_igv_style.txt` - read-level text pileups at the variant and at each exon 3 junction class, strand/read-end statistics for ALT reads, spliced sequences, in silico translation of each product
- `results/` - `affected_junction_summary.csv`, `exon_psi_calibration.csv`, `boundary_unspliced.csv`, `raw_vs_recal_junction_crosscheck.csv`, `sequence_rescored_E2E3.csv`, `ase_rna_vs_dna.csv`, `variant_locus_allele_counts.csv`, `junction_reads_exon3.tsv`, `normal_wes/tumor_wes.brca1.calls.vcf`, `gene_model.json`, `gene_model_exons.tsv`, `summary_numbers.json`
- `region_bams/` - extracted region BAMs + indices (contain germline genotypes: keep private)
- `reference/` - region FASTA (bgzip, N outside the window), the UCSC RefSeq JSON
- `scripts/` - all code

## Read policies for junction counts (fragment = read pair; counted once per junction)

P1 unique (NH=1, MAPQ 255), primary, sense strand (library is dUTP-stranded: read1 antisense), anchors >= 8 bp each side, marked dups included (headline). P2 = P1 without duplicate-flagged fragments (flags transferred by read name from the recal BAM, because the raw STAR BAM has none). P3 = unstranded. P4/P5 = anchors >= 15 bp (with/without dups). P6 = all primary alignments (unique or not).

## Known caveats of the pipeline (see report section 6)

STAR mis-alignment of 30 fragments is reassigned (`STAR_MISALIGN_REMAP` in `scripts/common.py`; verified by exact-sequence rescoring in `03b`). No normal RNA, unphased, one informative exonic SNP.
