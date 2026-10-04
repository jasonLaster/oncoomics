# Specimen ledger (private, step 1, 2026-10-03)

Research prioritization only; nothing here is clinical. Git-ignored (`private/`). Companion files: `ledger.csv` (one row per
dataset, per-field evidence), `vendor_questions.md` (drafts, nothing sent), `evidence/` (raw extractions), `he_labels/`
(slide label/macro images), `README.md` (commands, bytes transferred).

Tags: **[E]** established (direct evidence in a file or in reads), **[I]** inferred (reasoning stated), **[U]** unknown.

## 1. Bottom line

1. **One tumor genome across all DNA/RNA assays and KH022 [E].** Two rare somatic variants are present in the ImmunoID tumor
   exome, the WGS tumor, the ImmunoID tumor RNA, and (by report) Altera, and absent from both normals:
   BRCA1 c.81-1G>A (exome 201/862 = 23.3%, WGS 9/47 = 19.1%, Altera 27%) and BRCA2 c.8084C>T p.Ser2695Leu (exome 275/1860 =
   14.8%, WGS 10/65 = 15.4%, Altera VUS 12%). **Both KH022 libraries also carry the BRCA1 allele** (KH022-1: 91 T reads in
   62 cells; KH022-1-1: 31 T reads in 25 cells). So KH022 does contain this patient's tumor. What this does not tell us is
   *which tissue, when, or whether it was treated*.
2. **Specimen-level provenance is mostly NOT in the data.** Personalis (exome, RNA, WGS) delivered no accession, block,
   collection or receipt date; KH022 delivered none either (the vendor QC PDF is a FASTQ-quality report with no tissue/prep
   text). Only Altera, the proteomics report and the H&E slides carry specimen identifiers.
3. **Anchor specimen:** collected **2026-03-13**, breast, FFPE, before the first KEYNOTE-522 infusion (2026-04-02; this date
   comes only from a model-authored note that cites a clinical timeline not on disk). It appears under three labels:
   Altera block `SUS26-1600 A2`, proteomics `SP-26-027487-BR-VL3-A1` (UID CP0216), H&E slide B `SP-26-027487`. Same collection
   date; the numbering schemes and named institutions differ (section 5).
4. **"Altera reported HRD 62" is wrong.** The Altera report text contains no HRD/genomic-instability score (0 hits for HRD in the
   full text). 62 is the in-house WGS scar summary (LST 27 + TAI 26 + LOH 9, `07-17-drf-psn49561-hrd-analysis-summary.md`).
   Altera reports only the BRCA1 SNV (and focal CNVs <25 Mb); "apparent biallelic loss" is also in-house.
5. **New defect found:** the delivered `KH022-1-1/.../sample_alignments.bam.bai` does not index the delivered BAM (vendor MD5s
   match for both files). Region queries fail; the other library's pair is fine. Anything using BAM random access on -1-1
   (including identity tests) must re-index or bisect.

## 2. Merged timeline (dated events only)

| Date | Event | Source |
| --- | --- | --- |
| 2026-03-13 | Tumor collected (breast) | Altera header; proteomics p.1 |
| 2026-04-01 | Blood (Altera matched normal) | Altera header |
| 2026-04-02 | First KEYNOTE-522 infusion **(secondary note only)** | private-results/oncoomics_pretherapy_20260903/reviewer_packet.md |
| 2026-04-29 / 05-02 | Altera block retrieved / received | Altera header |
| 2026-05-12 | Altera preliminary report (final awaits IHC) | Altera header |
| 2026-07-09 | H&E slides A and B scanned (HistoWiz, Aperio GT450) | SVS ImageDescription |
| 2026-07-14 | Personalis delivery folder date; objects written to S3 2026-07-16T03:22-03:49Z | folder name; head-object |
| 2026-07-16/17 | In-house WGS BAM gather (hg38) | bam_qc_summary.json; head-object |
| 2026-07-30 | H&E slides uploaded | S3 LastModified |
| 2026-08-11 | EVEE report PDF created | pdfinfo |
| 2026-08-21 | Proteomics lab receives specimen (161 d after collection) | proteomics p.1 |
| 2026-09-03 | Proteomics reported | proteomics p.1 |
| 2026-09-04 | Private packet still treats surgery as future ("If surgery shows ...") | next_actions.md |
| by 2026-09-24 10:16 PDT | KH022 FASTQs written after three LH00707 runs (450, 454, 457) | arrival_receipt source mtime; BAM @RG |
| 2026-09-24 12:50 local | Cell Ranger 10.1.0 multi started; finished about 17:50 PDT | run dir 20260924_125002; mtimes |
| 2026-10-01/02 | Vendor folder copied to GCS bucket `kernis-kh022`, then to S3 | arrival_receipt |

Sequencing dates for every Personalis run are unrecoverable from headers (no DT tags). Run counters only give order:
LH00493 ran WGS-normal run 337, then exome-normal run 388 (51 runs later).

## 3. What is established, inferred, unknown

### Established [E]

| Fact | Evidence |
| --- | --- |
| Altera dates, block ID `SUS26-1600 A2`, FFPE, tumor content 30.0%, BRCA1 c.81-1G>A VAF 27% depth 2565, GRCh37 | `tmp/pdfs/altera-review/altera.txt` header, methods |
| Proteomics: ID SP-26-027487-BR-VL3-A1, UID CP0216, collected 03-13, received 08-21, reported 09-03, laser-microdissected tumor | proteomics-source.txt p.1 |
| Slide B accession = proteomics accession root; slide A is a different accession; both scanned 2026-07-09 on one scanner, one rack | `he_labels/*_label.png`; SVS tags |
| BRCA1 c.81-1G>A and BRCA2 p.Ser2695Leu shared by exome tumor, WGS tumor, tumor RNA; absent in exome normal (0/379, 0/934) and WGS normal (0/54, 0/91) | `evidence/brca1_site_counts.json`, `brca2_site_counts.json` |
| KH022-1 and KH022-1-1 each contain cells with the BRCA1 allele | `evidence/KH022-1_variant_site_counts.json`, `KH022-1-1_chr17_43115780_counts.json` |
| KH022-1 and -1-1 are two distinct dual-index libraries pooled and sequenced across the same three flowcell-lanes (not a re-sequencing of one library) | read names at 7 offsets/file; BAM @RG; I1/I2 index reads |
| Exome tumor and RNA share flowcell 255LYLLT4 / instrument LH01020 / run 177 (lanes 6, 8) and one Personalis order path; exome normal was a different run/instrument | BAM @PG; FASTQ names |
| WGS tumor (LH00696 run 273, flowcell 23YV5FLT4, lanes 5-8) and WGS normal (LH00493 run 337, flowcell 23WGWNLT4, lanes 1-4) were sequenced on different instruments/flowcells | FASTQ names |
| Tumor/normal WGS share a genetic background (matched-normal contamination 0.16%) | contamination_summary.json |
| KH022 chemistry GEM-X 3' v4 polyA, GRCh38-2024-A, introns included, no hashing, Cell Ranger 10.1.0 | qc_report.html parameters, design csv |
| Vendor QC PDF has no tissue/prep/loading statement | pdftotext of `2011765_qc.pdf` |

### Inferred [I]

| Inference | Why, and how weak |
| --- | --- |
| Altera and proteomics came from the same 2026-03-13 biopsy event (sibling blocks A2 / A1) | identical collection date and site; accession numbers differ, institutions differ; moderate |
| The 03-13 tissue is a **core biopsy** | slide B macro = one thin linear core; proteomics specimen image = thin linear fragments; needs pathologist confirmation |
| Slide B is the proteomics specimen (same accession; faint "A1" under the overlay; shapes compatible) | accession match is solid; "A1" is a moderate-confidence read of ghosted text |
| Personalis tumor DNA/RNA were drawn from the same 03-13 pre-treatment FFPE tissue | delivery dated 07-14 predates any known resection and no later biopsy is documented; tumor fragments shorter than normal (FFPE-compatible); weak, block unproven |
| Pre-treatment status of the anchor specimen | collection precedes the 04-02 infusion; the infusion date itself is secondary |
| KH022 is fresh/frozen material (nuclei or cells), not an FFPE block | 3' polyA chemistry; ~49-50% intronic reads; cannot be the March FFPE blocks |
| KH022 tissue was collected no later than early-to-mid September | three consecutive instrument runs finished before 2026-09-24; run durations not documented |
| Personalis normals (exome, WGS) are the same person as their tumors | no tumor-variant in normals; WGS contamination test; only 2 informative germline het sites checked across the exome and WGS normals (2/2 concordant) - not conclusive |
| Tumor content about 30% | Altera 30.0%; in-house Sequenza purity 0.31 (fit flagged unreliable); BRCA1/BRCA2 VAFs 12-27% |

### Unknown [U]

- Collection date, accession, block, type (core vs resection), and therapy state for **KH022**; whether it is the same physical
  source as the March tissue; whether -1 and -1-1 are replicate channels, aliquots, or different tissues; cells vs nuclei.
- Specimen, block, extraction and receipt dates for every **Personalis** dataset; what "Vial1" is; relationship of `E019` to
  `DRF-PSN49561`; whether the normal is the same draw as Altera's 04-01 blood.
- What slide A (`SP-26-022231`) is: date, procedure, therapy state. Its macro shows many separate fragments, unlike slide B.
- Mapping `SUS26-1600` to `SP-26-027487` / `SP-26-022231`; which blocks exist and where they went; tissue remaining.
- Primary documentation of the treatment timeline, surgery date, the hereditary germline panel, any Guardant360 report (only
  second-hand statements exist on disk).
- Provenance of the EVEE report's 607-variant list ("Personalis pipeline"); no VCF is in the Personalis delivery.

## 4. Relationship map (text)

```
PATIENT (single tumor genome confirmed by BRCA1 + BRCA2 somatic alleles in all DNA/RNA assays and KH022)

2026-03-13 biopsy (breast; FFPE; pre-treatment [I])
 |- path case "SUS26-1600" ---- block A2 --------> Altera DNA+RNA (30% tumor)               [E: dates/IDs]
 |- path case "SP-26-027487" --- block A1 --------> OncoOmicsDx LMD proteomics (CP0216)     [E: ID/dates]
 |                          '--- H&E slide B -----> HistoWiz scan 2026-07-09 (single core)  [E: accession; I: same section]
 |   link SUS26-1600 <-> SP-26-027487 : [U] (same date, different numbering/institution names)
 |- Personalis ImmunoID exome T (E019_S01) + RNA (E019_S01) + normal (E019_S05_Vial1)       [E: same tumor genome; U: specimen]
 '- Personalis WGS T/N (DRF-PSN49561)                                                       [E: same tumor genome; U: specimen]
     link E019 <-> DRF-PSN49561 : [E] same tumor genome, [U] same extraction/block

H&E slide A  SP-26-022231 (multi-fragment tissue, other accession)                          UNLINKED
KH022-1, KH022-1-1 (fresh/frozen; two UDI libraries, same 3 runs)                           same tumor genome [E]; tissue/date/therapy [U]
```

Plausibly sharing one specimen: Altera / proteomics / slide B (high); Personalis exome+RNA (high, vendor naming and
flowcell); Personalis WGS with exome (medium; same tumor genome, extraction unknown). Not plausibly the same physical tissue as
the March FFPE blocks: KH022 (chemistry). Unplaced: slide A.

## 5. Discrepancies and red flags

1. **HRD 62 misattributed to Altera** (section 1). Correct `next-steps-20261003.md` section 1 row 1; do not cite Altera as
   corroborating HRD or biallelic loss.
2. **Accession and institution mismatch.** Altera: block ID `SUS26-1600 A2`. Proteomics: `SP-26-027487-BR-VL3-A1` and
   "Pathology institution: Sutter Health - Alta Bates Summit". Slides: `SP-26-0xxxxx`, labels read "Stanford Pathology",
   underlying text "H&E INITIAL". Two stories fit (outside case re-accessioned as a consult vs two separate procedures); the
   data cannot choose. Pathology must map the three IDs.
3. **Slide A is unlinked** and visually different (many fragments). The next-steps table implies both slides are usable
   anchors; only slide B is tied to a dated specimen. SP-26-022231 < SP-26-027487, so slide A's case was accessioned earlier if
   one counter is used (accessioning date, not collection date).
4. **KH022 timing.** FASTQs were final 2026-09-24 after three sequential runs; a 2026-09-04 note still frames surgery as
   future. A surgical specimen would need collection within days of 09-04 and a very fast prep-to-run turnaround (possible,
   not documented). More likely a banked or earlier sample. Do not treat KH022 as the March biopsy or as post-treatment
   without the vendor/clinic answer.
5. **Tumor and normal WGS ran on different flowcells/instruments/times.** Any coverage-ratio copy-number analysis should check
   run-level batch/GC effects before blaming purity/ploidy for the odd Sequenza fit (15% genome homozygous deletion, depth
   ratios below the lowest ratio the fit allows). Not evidence either way; a cheap control for the CN agent.
6. **Personalis BAMs were aligned from `downsampled.*.fq`** (bwa @PG). Whether the delivered FASTQs are the full reads is
   unknown; this changes any depth estimate derived from "330.9M mapped reads".
7. **EVEE input provenance.** "607 somatic variants ... (Personalis pipeline)" but the Personalis delivery has no variant
   files. The report also says "TSC complex intact", while Altera lists TSC2 R59W (VAF 14%); PIKFYVE I1548T is in both. So
   the 607-variant list is neither the full Altera list nor the full in-house list.
8. **Tissue budget.** One thin core (slide B) is also cited as supporting Altera DNA+RNA, proteomics, and (if the same
   tissue) Personalis exome+RNA+WGS. Ask pathology what blocks exist and how much remains; the Personalis tumor material may
   have come from a different or larger sample.
9. **Public exposure.** The public-read inbox holds the SVS files; their embedded label images show the patient's name (and
   accession) in clear text. KH022 BAMs/FASTQ carry germline genotypes; the vendor dotfiles include an `.htaccess` that lists
   the vendor's basic-auth usernames. Git-tracked `results/diana_wgs_hrd/early-look-.../VARIANT_REVIEW.tsv` (pushed to
   origin/main) contains the patient's BRCA1/BRCA2 calls. Confirm this is intended and consented; irreversible once copied.
10. **KH022-1-1 BAM index defect** (section 1, item 5): both bytes match vendor MD5s. Bisection shows the BAM itself is
    valid (header, EOF block, coordinate order) while the BAI offsets land mid-block or in the wrong chromosome (e.g. BAI says
    chr13:32.4 Mb at byte 9,610,490,264; the BAM has chr13:99.8 Mb at the next block). Ask Signios to regenerate the .bai.
11. **Altera md file contains commentary not in the report** ("Guardant360 signal confirmed", "germline panel is negative",
    "KEYNOTE-522 rationale"). Treat as secondary; the hereditary panel and Guardant records are not on disk.
12. **Allele skew lead for the BRCA1 splice agent.** In tumor RNA the BRCA1 site is 66 T / 7 C (90% alt) and in KH022 reads that
    cover the site are 91 T / 4 C; spliced-over reads (569) carry no base at the site. Consistent with unspliced pre-mRNA
    enrichment of the mutant allele, but not interpreted here; the step 4 agent owns it.

## 6. Checks run here, and what would settle the rest

Run in this step (all read-only, range reads): BRCA1 and BRCA2 variant genotyping in five DNA/RNA BAMs and both KH022
libraries; hg19/hg38 offset validation; a BRCA1-window germline pilot; insert-size distributions; SVS metadata and label OCR
(by eye); FASTQ read-name/flowcell mapping; KH022 source-file mtimes.

Still needed, in value order:

1. **Genome-wide germline identity** over ~1-5k common SNPs among: WGS normal, exome normal, exome tumor, RNA, KH022-1, KH022-1-1
   (step 2a covers scRNA vs WGS normal; add exome normal and RNA, plus mtDNA haplotype and X/Y sex). The BRCA1-window pilot had
   only 2 informative het sites, which is not enough to prove the normals match.
2. **Shared-variant panel.** Genotype Altera's VUS list (e.g., MFI2 G197R 37%, TOR3A K286T 37%, OLIG2 A230D 35%, SLC46A3 L130F
   32%, TXNDC5 V305I 19%, PIKFYVE I1548T 12%, TSC2 R59W 14%) in exome tumor, WGS tumor and KH022 BAMs; compare VAFs
   per variant. Same-block/same-region samples should track proportionally (VAF ratio near the purity ratio); a subset
   diverging implies different tissue regions or time. Needs variant coordinates (Altera VCF, or VEP on the HGVS.p strings).
3. **Material by damage signature.** Genome-wide insert-size distribution and C>T/G>A orientation bias in the WGS/exome tumors
   to decide FFPE vs frozen (the BRCA1-window sizes already lean FFPE: tumor median 213-219 bp vs normal 242-266 bp).
4. **KH022 tumor-cell tracking.** Count BRCA1/BRCA2 and the high-VAF VUS alleles per barcode (cellsnp-lite on the KH022-1 BAM;
   re-index or bisect -1-1) to see which barcodes are tumor; this also gives a second, independent identity test.
5. **Allele-specific CN concordance** across WGS, exome and scRNA-inferred CNV (steps 2.1 and 3.2) as a tumor-cell-region check.

Open items only clinic or vendors can resolve are drafted in `vendor_questions.md`.

## 7. Method notes and limits

- Headers via `samtools view -H` on presigned URLs; FASTQ names from the first 1 MB of each file (and 7 offsets in the KH022
  R1 files); pileups via `samtools mpileup -X` over presigned BAM+BAI; SVS via `tifffile` with HTTP range reads.
- Pileup counts are unfiltered (MAPQ 0, base quality 0) for the single-site tables; the paired-read, duplicate and
  strand filters used by the other agents will give somewhat different numbers.
- The hs37d5 positions come from Altera's GRCh37 coordinate (BRCA1) and a 40-bp read-context match (BRCA2); the BRCA1
  offset (1,847,983) was validated by 100% homozygous-site concordance (19,944/19,944) between exome and WGS across the 81 kb
  gene window versus about 25% under shifted offsets.
- The H&E macro/label readings are by eye; the "A1" ghost text is moderate confidence. The flowcell prefix (23.. vs 25..) is
  not interpreted as a date.
