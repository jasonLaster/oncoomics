# Reconciled somatic findings across Altera, the July 17 summary, the EVEE report and the WGS early look (PRIVATE)

Research prioritization only; nothing here is clinical. Git-ignored (`private/`); never commit. Generated 2026-10-03 (step 7).
Machine-readable: `results/reconciled_table.tsv` (per variant, chosen site, counts) and `results/audit_results.json` (every candidate site).

## How to read it

- Every SNV/indel named anywhere was re-genotyped in five BAMs from region-only reads: Personalis tumor/normal exome (hs37d5,
  ~200-1,400 fragments here), Personalis tumor RNA (raw STAR), and the DRF-PSN49561 tumor/normal WGS (GRCh38, ~10-60 fragments).
  Fragment-level counts: duplicates/secondary/supplementary/QC-fail out, MQ>=20, BQ>=20, overlapping mates collapsed (a fragment
  whose mates disagree is dropped). Protein changes were resolved to every possible genomic SNV over all Ensembl GRCh37 transcripts
  (Ensembl `variant_recoder`); the EVEE tier-1 sites use the report's exact GRCh38 alleles. Indels/frameshifts/splice deletions were
  tested by a +/-12 bp tumor-vs-normal scan. RNA is allelic-expression evidence only.
- Status rules: **CONFIRMED (exome)** >=5 tumor fragments, VAF >=2%, normal <=1 fragment (<1%). **Low VAF** same but 0.5-2%.
  **CONFIRMED in Altera + WGS; absent from exome** = Altera-reported, WGS >=3 tumor fragments with WGS normal 0, exome <3%.
  **NOT REPRODUCED** = 0 exome fragments at >=100 (one site 72) depth. **UNRESOLVED** = Altera-only, exome 0-1, WGS 0-2.
- The three tumor datasets are not one aliquot (new finding, section 3 of `provenance_report.md`): a subclone at ~10% VAF in Altera
  and WGS is absent or at 1-2% in the Personalis exome/RNA specimen. "Absent in exome" therefore does **not** by itself retire a
  variant; the EVEE retirements below rest on exome absence **plus** Altera absence **plus** single-molecule WGS support.

## Bottom line

| Claim set | Variants tested | Reproduced | Not reproduced | Unresolved / untested |
|---|---|---|---|---|
| EVEE-report variants not also in Altera (9 tier-1 + PPARD, RB1CC1, WNT2B, WNT6, LIN28A, FZD10, CBL, ARIH2, SHH) | 18 | **0** | 18 (RB1CC1 from step 3) | 0 |
| EVEE-report variants also in Altera (PIKFYVE I1548T) | 1 | 1 | 0 | 0 |
| July 17 named variants (BRCA1 splice, BRCA2 S2695L VUS, SHH "pathogenic") | 3 | 2 (BRCA1, BRCA2) | 1 (SHH Q209*) | 0 |
| WGS early-look coding PASS calls (BRCA1, BRCA2) | 2 | 2 | 0 | 0 |
| Altera small variants (incl. BRCA1, TP53 c.559+2T>G from its trials table) | 132 | 112 in exome (median exome/Altera VAF ratio 1.02, IQR 0.76-1.26) + 9 in WGS only | 0 called false | 9 unresolved, 2 coordinates unresolved |

Every EVEE-only allele that could be placed has the same signature: 0 exome fragments at 72-793x, absent from Altera's list,
and exactly 1 (WNT6, CUL3: 2) WGS tumor fragment at sites where the WGS tumor depth is low (median 11.5 vs 29 at Altera sites,
Mann-Whitney p=1e-4; tumor/normal depth ratio 0.24 vs 0.60, p=6e-4).

## Drop from the hypothesis list

Drop every hypothesis whose genetic premise is one of these alleles: MTOR G98S (mTOR inhibitor), SCAP W633* / RXRA S96* /
PPARD Q415H (statin, retinoid), ATG4B W142* / ATG13 D213G / RB1CC1 donor ("autophagy collapse", proteasome/ER stress), CUL3 R354C /
CBL D460del / ARIH2 E29del (NRF2/ferroptosis, ubiquitin), DLL4 R516C / WNT2B / WNT6 / LIN28A / FZD10 (Notch/Wnt), FGFR4 S106F (FGFR
inhibitor), BRD3 S676G (BET), SHH Q209* (Hedgehog; also the July 17 "pathogenic SHH" flag). Pathway activity was not tested; a
pathway can still matter for other reasons, but not because of these variants.

Keep / add (supported, still unevaluated functionally): **BRCA1 c.81-1G>A** (primary), **TP53 c.559+2T>G** (exome 34.8%, WGS
10/18, normal 0; the highest-VAF truncal event and canonical TNBC driver, mentioned by neither July 17 nor EVEE), and as the
real mTOR-axis variants **MTOR P1125A** (9.4%), **TSC2 R59W** (10.7%; contradicts EVEE's "TSC complex intact"), **PIKFYVE I1548T**
(8.7%). BRCA2 S2695L is real but ClinVar likely benign; not an HRD driver.

## Non-SNV claims

| Claim | Source | Status | Evidence / next step |
|---|---|---|---|
| ~16,000 somatic mutations "agreed on by two methods", ~5/Mb | July 17 | **Unverifiable**; callset not recovered | ~16,000 / ~3,100 Mb = 5.2/Mb is arithmetically consistent with a genome-wide count. Its derived coding list (if the EVEE 607 came from it) contains single-molecule calls and SHH Q209* (0/686 exome) |
| HRD 62 (LST 27, TAI 26, LOH 9) after a "software setting" correction | July 17 | **Unresolved**; code path not found anywhere on disk or S3 | the repo's own July 22 Sequenza->scarHRD (LST 28, TAI 20, LOH 24, sum 72) is from a fit flagged as broken; similar LST/TAI is not corroboration. Needs step 2.1 (FACETS/PURPLE) |
| BRCA1 second hit = deletion ("biallelic") | July 17 (EnJun), not Altera | **Unresolved** | 17q21 relative loss and BAF imbalance exist (steps 3/5); allele-specific CN pending |
| "TSC complex intact (no variants)" | EVEE | **Contradicted** | TSC2 R59W 123/1146 exome, normal 0/702 |
| "1 pathogenic (SHH Q209*)" | EVEE / July 17 | **Contradicted** | 0/686 exome, 0/535 normal, 1/14 WGS |
| Altera CNVs / fusions (DHCR7, FADD, NADSYN1, ORAOV1 amplification; A2M, CEP112, PAX3 ... breakpoints; FNBP1L::FAM129A) | Altera | **Not tested here** | needs WGS CN/SV calling |
| WGS early-look non-coding PASS calls (37 intronic/UTR in 15 HRR genes) | repo early look | **Not tested** (off exome); 28/37 have 2-3 tumor ALT reads | illustrates that a Mutect2 PASS set at this depth admits 2-read calls |

## Per-variant table (all 149 rows: EVEE/July 17 first, then Altera alphabetically)

ALT/frags = fragments carrying the ALT / informative fragments. RNA is reads (raw STAR, unique). For BRCA1 the site is the last
intronic base, so RNA counts mix unspliced and other reads; use step 4 for splicing.

Extra row not in the TSV (from step 3; reported coordinate only, no ALT given): RB1CC1 splice donor chr8:52624715 (GRCh37
8:53537275) - tumor exome 435 A / 0 non-reference reads, normal 124 / 0: NOT REPRODUCED, drop.

| Gene | Change | Source(s) | Altera VAF | Exome tumor ALT/frags (VAF) | Exome normal | WGS tumor ALT/frags | WGS normal ALT | Tumor RNA ALT/reads | Status | Note | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ARIH2 | E29del | EVEE |  | n/a | n/a | n/a | n/a | n/a | NOT REPRODUCED | no in-frame deletion in tumor exome or WGS in any transcript window | drop |
| ATG13 | D213G | EVEE |  | 0/285 (0.0%) | 0/124 (0.0%) | 0/25 (0.0%) | 0 | 0/778 (0.0%) | NOT REPRODUCED |  | drop |
| ATG4B | W142* | EVEE |  | 0/201 (0.0%) | 0/108 (0.0%) | 1/17 (5.9%) | 0 | 4/726 (0.6%) | NOT REPRODUCED |  | drop |
| BRCA1 | c.81-1G>A | Altera+July17+WGS_early_look | 27% | 134/598 (22.4%) | 0/292 (0.0%) | 4/23 (17.4%) | 0 | 48/570 (8.4%) | CONFIRMED (exome) |  | keep: primary finding |
| BRCA2 | S2695L | Altera+July17+WGS_early_look | 12% | 201/1362 (14.8%) | 0/778 (0.0%) | 5/37 (13.5%) | 0 | 344/914 (37.6%) | CONFIRMED (exome) |  | keep as VUS (ClinVar likely benign); not an HRD driver |
| BRD3 | S676G | EVEE |  | 0/372 (0.0%) | 0/177 (0.0%) | 1/11 (9.1%) | 0 | 0/520 (0.0%) | NOT REPRODUCED |  | drop |
| CBL | D460del | EVEE |  | n/a | n/a | 3/28 (10.7%) | 0 | n/a | NOT REPRODUCED: repeat-stutter artifact | GAT-repeat 3-bp deletion; exome tumor 38/2067 reads (1.8%) but matched normal 8/722 (1.1%); WGS 3/28 vs 0/44 | drop |
| CUL3 | R354C | EVEE |  | 0/190 (0.0%) | 0/36 (0.0%) | 2/47 (4.3%) | 0 | 2/728 (0.3%) | NOT REPRODUCED |  | drop |
| DLL4 | R516C | EVEE |  | 0/258 (0.0%) | 0/176 (0.0%) | 1/11 (9.1%) | 0 | 0/41 (0.0%) | NOT REPRODUCED |  | drop |
| FGFR4 | S106F | EVEE |  | 0/678 (0.0%) | 0/614 (0.0%) | 1/9 (11.1%) | 0 | 0/341 (0.0%) | NOT REPRODUCED |  | drop |
| FZD10 | A19V | EVEE |  | 0/72 (0.0%) | 0/84 (0.0%) | 1/8 (12.5%) | 0 | 0/17 (0.0%) | NOT REPRODUCED (exome depth <100) |  | drop |
| LIN28A | A24V | EVEE |  | 0/136 (0.0%) | 0/81 (0.0%) | 1/9 (11.1%) | 0 | 0/4 (0.0%) | NOT REPRODUCED |  | drop |
| MTOR | G98S | EVEE |  | 0/793 (0.0%) | 0/426 (0.0%) | 1/10 (10.0%) | 0 | 1/2188 (0.0%) | NOT REPRODUCED |  | drop |
| PIKFYVE | I1548T | Altera+EVEE | 12% | 15/173 (8.7%) | 0/61 (0.0%) | 7/45 (15.6%) | 0 | 61/294 (20.7%) | CONFIRMED (exome) |  | keep as unevaluated mTOR-axis candidate |
| PPARD | Q415H | EVEE |  | 0/653 (0.0%) | 0/290 (0.0%) | 1/16 (6.2%) | 0 | 3/2178 (0.1%) | NOT REPRODUCED |  | drop |
| RXRA | S96* | EVEE |  | 0/299 (0.0%) | 0/180 (0.0%) | 1/9 (11.1%) | 0 | 0/1706 (0.0%) | NOT REPRODUCED |  | drop |
| SCAP | W633* | EVEE |  | 0/293 (0.0%) | 0/214 (0.0%) | 1/12 (8.3%) | 0 | 0/992 (0.0%) | NOT REPRODUCED |  | drop |
| SHH | Q209* | EVEE+July17 |  | 0/686 (0.0%) | 0/535 (0.0%) | 1/14 (7.1%) | 0 | 0/6 (0.0%) | NOT REPRODUCED |  | drop |
| WNT2B | L39P | EVEE |  | 0/121 (0.0%) | 0/69 (0.0%) | 1/7 (14.3%) | 0 | 0/16 (0.0%) | NOT REPRODUCED |  | drop |
| WNT6 | S88P | EVEE |  | 0/422 (0.0%) | 0/211 (0.0%) | 2/15 (13.3%) | 0 | 0/43 (0.0%) | NOT REPRODUCED |  | drop |
| AASS | R445S | Altera | 14% | 30/223 (13.5%) | 0/78 (0.0%) | 9/63 (14.3%) | 0 | 21/102 (20.6%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ABHD2 | P38_L44del | Altera | 9% | 35/313 (11.2%) | 0/131 (0.0%) | n/a | n/a | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ADAD1 | L291I | Altera | 9% | 15/183 (8.2%) | 0/46 (0.0%) | 6/50 (12.0%) | 0 | 0/4 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ADAMTS2 | Q986R | Altera | 9% | 6/137 (4.4%) | 0/112 (0.0%) | 0/6 (0.0%) | 0 | 0/211 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| AKAP10 | P21A | Altera | 6% | 0/112 (0.0%) | 0/39 (0.0%) | 1/22 (4.5%) | 0 | 0/354 (0.0%) | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| ANO5 | G348V | Altera | 11% | 30/238 (12.6%) | 0/104 (0.0%) | 9/77 (11.7%) | 0 | 1/8 (12.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ANTXR2 | R427K | Altera | 13% | 14/132 (10.6%) | 0/41 (0.0%) | 4/56 (7.1%) | 0 | 9/281 (3.2%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| AP5M1 | V407A | Altera | 8% | 0/435 (0.0%) | 0/183 (0.0%) | 3/39 (7.7%) | 0 | 0/412 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| APEH | R693G | Altera | 14% | 39/283 (13.8%) | 0/186 (0.0%) | 2/16 (12.5%) | 0 | 98/397 (24.7%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ARAF | L527M | Altera | 9% | 37/1407 (2.6%) | 0/837 (0.0%) | 3/18 (16.7%) | 0 | 0/3335 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ARAF | L598I | Altera | 9% | 20/906 (2.2%) | 0/566 (0.0%) | 1/8 (12.5%) | 0 | 0/3442 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ARAF | S490* | Altera | 9% | 16/1103 (1.5%) | 0/598 (0.0%) | 2/9 (22.2%) | 0 | 0/2624 (0.0%) | CONFIRMED, low VAF in exome (<2%) | subclonal in the exome specimen | passenger/VUS unless functional data |
| ATAD2 | R1265T | Altera | 5% | 37/315 (11.7%) | 0/127 (0.0%) | 5/41 (12.2%) | 0 | 59/431 (13.7%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ATP13A3 | K1040T | Altera | 5% | 0/211 (0.0%) | 0/53 (0.0%) | 6/62 (9.7%) | 0 | 0/1016 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| BCL2L1 | E179Q | Altera | 7% | 31/344 (9.0%) | 0/129 (0.0%) | 1/28 (3.6%) | 0 | 127/705 (18.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| C1QTNF7 | V252I | Altera | 11% | 49/390 (12.6%) | 0/171 (0.0%) | 3/37 (8.1%) | 0 | 0/31 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| C1orf109 | P37S | Altera | 7% | 28/313 (8.9%) | 0/122 (0.0%) | 4/22 (18.2%) | 0 | 32/116 (27.6%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| CD84 | N269S | Altera | 9% | 19/247 (7.7%) | 0/86 (0.0%) | 3/52 (5.8%) | 0 | 0/385 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| CDKL5 | S450C | Altera | 6% | 1/416 (0.2%) | 0/183 (0.0%) | 2/29 (6.9%) | 0 | 0/195 (0.0%) | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| CDX4 | S51L | Altera | 12% | 49/377 (13.0%) | 0/270 (0.0%) | 2/13 (15.4%) | 0 | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| CLASP2 | T774K | Altera | 20% | 83/316 (26.3%) | 0/93 (0.0%) | 12/56 (21.4%) | 0 | 98/200 (49.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| COL15A1 | S1354Y | Altera | 14% | 69/687 (10.0%) | 0/190 (0.0%) | 2/36 (5.6%) | 0 | 4/1063 (0.4%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| COL4A6 | G1190* | Altera | 12% | 39/309 (12.6%) | 0/166 (0.0%) | 2/16 (12.5%) | 0 | 0/21 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| CPNE9 | A209G | Altera | 10% | 22/205 (10.7%) | 0/99 (0.0%) | 2/29 (6.9%) | 0 | 0/10 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| CREB3L1 | F19L | Altera | 9% | 1/279 (0.4%) | 0/165 (0.0%) | 0/17 (0.0%) | 0 | 0/322 (0.0%) | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| CRNN | K255N | Altera | 6% | 0/437 (0.0%) | 0/294 (0.0%) | 0/29 (0.0%) | 1 | n/a | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| CST5 | K61T | Altera | 13% | 30/319 (9.4%) | 0/207 (0.0%) | 3/18 (16.7%) | 0 | 0/3 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| CUBN | E62K | Altera | 9% | 68/547 (12.4%) | 0/134 (0.0%) | 4/52 (7.7%) | 0 | 3/27 (11.1%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| DCSTAMP | H110R | Altera | 8% | 39/370 (10.5%) | 0/150 (0.0%) | 5/27 (18.5%) | 0 | 0/1 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| DFNA5 | E375K | Altera | 11% | 38/264 (14.4%) | 0/152 (0.0%) | 5/29 (17.2%) | 0 | 7/56 (12.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| DNAAF1 | E25K | Altera | 9% | 19/189 (10.1%) | 0/82 (0.0%) | 3/16 (18.8%) | 0 | 1/8 (12.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| DST | R4789L | Altera | 11% | 44/364 (12.1%) | 0/134 (0.0%) | 4/52 (7.7%) | 0 | 222/1120 (19.8%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| DSTN | Q136E | Altera | 9% | 34/349 (9.7%) | 0/127 (0.0%) | 4/34 (11.8%) | 0 | 841/3432 (24.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ECT2 | G185V | Altera | 7% | 8/369 (2.2%) | 0/113 (0.0%) | 4/67 (6.0%) | 0 | 3/936 (0.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| EIF4A2 | E245Q | Altera | 12% | 59/646 (9.1%) | 0/180 (0.0%) | 9/81 (11.1%) | 0 | 1230/7868 (15.6%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ELAVL3 | L270V | Altera | 7% | 0/348 (0.0%) | 0/198 (0.0%) | 0/10 (0.0%) | 0 | 0/14 (0.0%) | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| EMX1 | A138V | Altera | 12% | 43/311 (13.8%) | 0/160 (0.0%) | 2/11 (18.2%) | 0 | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| EN1 | A274D | Altera | 7% | 42/230 (18.3%) | 0/85 (0.0%) | 3/16 (18.8%) | 0 | 233/664 (35.1%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ETV3 | E417Q | Altera | 21% | 47/463 (10.2%) | 0/169 (0.0%) | 8/32 (25.0%) | 0 | 75/464 (16.2%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| F5 | E2057* | Altera | 9% | 0/564 (0.0%) | 0/122 (0.0%) | 7/58 (12.1%) | 0 | 0/188 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| FAM229A | A30T | Altera | 8% | 10/68 (14.7%) | 0/34 (0.0%) | 2/11 (18.2%) | 0 | 6/18 (33.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| FASTK | R356L | Altera | 19% | 18/291 (6.2%) | 0/144 (0.0%) | 0/12 (0.0%) | 0 | 153/925 (16.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| FAT4 | P3870R | Altera | 11% | 35/260 (13.5%) | 0/115 (0.0%) | 5/37 (13.5%) | 0 | 2/65 (3.1%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| FBXO43 | E332K | Altera | 10% | 21/282 (7.4%) | 0/111 (0.0%) | 6/44 (13.6%) | 0 | 4/12 (33.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| GIF | E118Q | Altera | 12% | 28/232 (12.1%) | 0/96 (0.0%) | 8/40 (20.0%) | 0 | 0/4 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| HABP2 | D7A | Altera | 9% | 0/197 (0.0%) | 0/72 (0.0%) | 1/23 (4.3%) | 0 | 0/2 (0.0%) | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| HPN | R8fs | Altera | 14% | 24/263 (9.1%) | 0/129 (0.0%) | n/a | n/a | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| IGDCC4 | Q824* | Altera | 12% | 18/202 (8.9%) | 0/159 (0.0%) | 1/9 (11.1%) | 0 | 0/107 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| IL20 | D122E | Altera | 8% | 40/351 (11.4%) | 0/98 (0.0%) | 9/49 (18.4%) | 0 | 0/3 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| IL2RA | V148L | Altera | 11% | 248/1870 (13.3%) | 0/721 (0.0%) | 1/20 (5.0%) | 0 | 0/350 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| INTS2 | W576G | Altera | 20% | 19/148 (12.8%) | 0/66 (0.0%) | 5/22 (22.7%) | 0 | 40/142 (28.2%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ITGA8 | E252G | Altera | 12% | 22/278 (7.9%) | 0/87 (0.0%) | 5/41 (12.2%) | 0 | 0/27 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| JPH3 | E534D | Altera | 10% | 23/134 (17.2%) | 0/109 (0.0%) | 2/9 (22.2%) | 0 | 0/12 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| KBTBD3 | S188C | Altera | 12% | 35/203 (17.2%) | 0/91 (0.0%) | 6/49 (12.2%) | 0 | 0/6 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| KIAA1919 | K213fs | Altera | 9% | n/a | n/a | n/a | n/a | n/a | UNTESTED (coordinates unresolved) | symbol MFSD4B; Ensembl could not map | not a hypothesis |
| KRTAP6-2 | G24V | Altera | 10% | 41/442 (9.3%) | 0/173 (0.0%) | 4/25 (16.0%) | 0 | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| LPHN3 | E37V | Altera | 8% | 0/580 (0.0%) | 0/183 (0.0%) | 4/54 (7.4%) | 0 | 0/58 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| LRFN2 | P422fs | Altera | 9% | 49/439 (11.2%) | 0/208 (0.0%) | n/a | n/a | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MAN1A1 | L594F | Altera | 13% | 31/315 (9.8%) | 0/107 (0.0%) | 5/56 (8.9%) | 0 | 90/751 (12.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MAST1 | A617D | Altera | 11% | 40/297 (13.5%) | 0/177 (0.0%) | 0/7 (0.0%) | 0 | 0/11 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MBNL2 | D196A | Altera | 7% | 56/576 (9.7%) | 0/179 (0.0%) | 4/33 (12.1%) | 0 | 453/3714 (12.2%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MED15 | Q185del | Altera | 9% | n/a | n/a | n/a | n/a | n/a | UNRESOLVED (Altera only) | polyQ repeat; no tumor-only deletion in exome or WGS windows | not a hypothesis |
| MFI2 | G197R | Altera | 37% | 109/285 (38.2%) | 0/115 (0.0%) | 9/22 (40.9%) | 0 | 1713/2307 (74.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MGAM | S1844I | Altera | 9% | 26/315 (8.3%) | 0/134 (0.0%) | 7/55 (12.7%) | 0 | 0/9 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MRPS9 | G20A | Altera | 7% | 6/545 (1.1%) | 0/170 (0.0%) | 7/42 (16.7%) | 0 | 16/411 (3.9%) | CONFIRMED, low VAF in exome (<2%) | subclonal in the exome specimen | passenger/VUS unless functional data |
| MSH5 | WF273CI | Altera | 8% | n/a | n/a | n/a | n/a | n/a | UNTESTED (coordinates unresolved) | MNV/delins notation | not a hypothesis |
| MTOR | P1125A | Altera | 12% | 100/1061 (9.4%) | 0/433 (0.0%) | 4/38 (10.5%) | 0 | 436/2738 (15.9%) | CONFIRMED (exome) |  | keep as unevaluated mTOR-axis candidate |
| MTUS1 | L886V | Altera | 12% | 51/424 (12.0%) | 0/162 (0.0%) | 8/47 (17.0%) | 0 | 329/1060 (31.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MTUS1 | R879K | Altera | 10% | 48/392 (12.2%) | 0/145 (0.0%) | 8/44 (18.2%) | 0 | 316/1036 (30.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| MUC2 | T1668P | Altera | 7% | 11/643 (1.7%) | 0/629 (0.0%) | 1/12 (8.3%) | 0 | 0/430 (0.0%) | CONFIRMED, low VAF in exome (<2%) | subclonal in the exome specimen | passenger/VUS unless functional data |
| MXRA8 | R240H | Altera | 23% | 57/242 (23.6%) | 0/111 (0.0%) | 4/11 (36.4%) | 0 | 82/640 (12.8%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| NBEA | E1667G | Altera | 11% | 38/339 (11.2%) | 0/124 (0.0%) | 6/55 (10.9%) | 0 | 69/262 (26.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| NDFIP1 | E78K | Altera | 10% | 7/230 (3.0%) | 0/118 (0.0%) | 8/36 (22.2%) | 0 | 16/1824 (0.9%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| NDNF | L395I | Altera | 7% | 0/346 (0.0%) | 0/176 (0.0%) | 1/35 (2.9%) | 0 | 0/11 (0.0%) | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| NLRP9 | c.2150_2159+5delAAGAGCTGATGTAAG | Altera | 9% | 29/241 (12.0%) | 0/111 (0.0%) | n/a | n/a | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| NOX1 | L452F | Altera | 14% | 23/183 (12.6%) | 0/99 (0.0%) | 3/18 (16.7%) | 0 | 0/2 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| NT5C1B | K570Q | Altera | 15% | 63/557 (11.3%) | 0/144 (0.0%) | 9/45 (20.0%) | 0 | 10/56 (17.9%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| OLIG2 | A230D | Altera | 35% | 30/79 (38.0%) | 0/57 (0.0%) | 4/8 (50.0%) | 0 | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| OR51A4 | L65I | Altera | 7% | 7/517 (1.4%) | 0/279 (0.0%) | 2/66 (3.0%) | 0 | n/a | CONFIRMED, low VAF in exome (<2%) | subclonal in the exome specimen | passenger/VUS unless functional data |
| OTUD4 | T1049P | Altera | 10% | 0/322 (0.0%) | 0/148 (0.0%) | 5/39 (12.8%) | 0 | 0/326 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| PCDHA6 | A381G | Altera | 9% | 139/1231 (11.3%) | 0/655 (0.0%) | 5/26 (19.2%) | 0 | 13/91 (14.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PHKB | A5V | Altera | 19% | 32/134 (23.9%) | 0/60 (0.0%) | 3/21 (14.3%) | 0 | 46/142 (32.4%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PLD1 | V792fs | Altera | 12% | 19/189 (10.1%) | 0/66 (0.0%) | 3/47 (6.4%) | 0 | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PLEC | R3909H | Altera | 7% | 6/192 (3.1%) | 0/113 (0.0%) | 0/10 (0.0%) | 0 | 24/1166 (2.1%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PLOD2 | Y61fs | Altera | 6% | 21/212 (9.9%) | 0/78 (0.0%) | 6/64 (9.4%) | 0 | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PREX2 | S13C | Altera | 16% | 13/150 (8.7%) | 0/80 (0.0%) | 1/15 (6.7%) | 0 | 0/69 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PROC | L47Q | Altera | 10% | 46/416 (11.1%) | 0/215 (0.0%) | 1/9 (11.1%) | 0 | 4/17 (23.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PRRC2B | P1828L | Altera | 11% | 32/312 (10.3%) | 0/166 (0.0%) | 2/7 (28.6%) | 0 | 235/1429 (16.4%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PRRG1 | R20I | Altera | 7% | 0/225 (0.0%) | 0/76 (0.0%) | 3/41 (7.3%) | 0 | 1/209 (0.5%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| PTPN23 | P981A | Altera | 14% | 32/201 (15.9%) | 0/202 (0.0%) | 3/8 (37.5%) | 0 | 328/1697 (19.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| PTPRH | T490P | Altera | 24% | 26/114 (22.8%) | 0/97 (0.0%) | 7/16 (43.8%) | 0 | 2/15 (13.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| RABL6 | A432D | Altera | 11% | 57/349 (16.3%) | 0/189 (0.0%) | 0/8 (0.0%) | 0 | 172/751 (22.9%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| RAG1 | S382* | Altera | 14% | 47/235 (20.0%) | 0/120 (0.0%) | 7/41 (17.1%) | 0 | 0/2 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| RNPC3 | Y423D | Altera | 11% | 28/202 (13.9%) | 0/50 (0.0%) | 2/47 (4.3%) | 0 | 88/307 (28.7%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| RXFP4 | R238P | Altera | 6% | 7/388 (1.8%) | 0/189 (0.0%) | 2/28 (7.1%) | 0 | 0/15 (0.0%) | CONFIRMED, low VAF in exome (<2%) | subclonal in the exome specimen | passenger/VUS unless functional data |
| S1PR4 | V103M | Altera | 23% | 59/298 (19.8%) | 0/231 (0.0%) | 3/7 (42.9%) | 0 | 3/176 (1.7%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SCN11A | I1376M | Altera | 9% | 0/273 (0.0%) | 0/141 (0.0%) | 3/31 (9.7%) | 0 | 0/5 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| SCN11A | N822K | Altera | 11% | 26/237 (11.0%) | 0/92 (0.0%) | 3/38 (7.9%) | 0 | 0/6 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SEMA6C | R663H | Altera | 21% | 56/169 (33.1%) | 0/41 (0.0%) | 3/12 (25.0%) | 0 | 6/58 (10.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SLC22A10 | I407M | Altera | 13% | 37/531 (7.0%) | 0/204 (0.0%) | 3/41 (7.3%) | 0 | 2/4 (50.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SLC46A3 | L130F | Altera | 32% | 94/362 (26.0%) | 0/207 (0.0%) | 6/24 (25.0%) | 0 | 52/180 (28.9%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SNX14 | N649Y | Altera | 11% | 29/170 (17.1%) | 0/60 (0.0%) | 3/24 (12.5%) | 0 | 87/383 (22.7%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SNX15 | T148A | Altera | 8% | 34/411 (8.3%) | 0/211 (0.0%) | 5/18 (27.8%) | 0 | 36/250 (14.4%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SRPK3 | E547Q | Altera | 12% | 25/209 (12.0%) | 0/209 (0.0%) | 0/2 (0.0%) | 0 | 13/38 (34.2%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SRRM4 | T510N | Altera | 5% | 30/226 (13.3%) | 1/137 (0.7%) | 4/23 (17.4%) | 0 | 0/1 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| STK16 | E122D | Altera | 12% | 15/246 (6.1%) | 0/99 (0.0%) | 1/17 (5.9%) | 0 | 39/252 (15.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| SVOPL | L81P | Altera | 6% | 0/320 (0.0%) | 0/155 (0.0%) | 4/41 (9.8%) | 0 | 0/14 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| SYNJ1 | G22E | Altera | 7% | 0/163 (0.0%) | 0/61 (0.0%) | 3/21 (14.3%) | 0 | 0/16 (0.0%) | CONFIRMED in Altera + WGS; ABSENT from exome/RNA specimen | subclone not present in the Personalis exome/RNA specimen | passenger/VUS unless functional data |
| TAC4 | G96A | Altera | 24% | 30/242 (12.4%) | 0/115 (0.0%) | 2/16 (12.5%) | 0 | 14/65 (21.5%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TAF4B | P522T | Altera | 19% | 82/347 (23.6%) | 0/136 (0.0%) | 10/34 (29.4%) | 0 | 117/191 (61.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TELO2 | E430D | Altera | 14% | 21/154 (13.6%) | 0/109 (0.0%) | 1/7 (14.3%) | 0 | 91/328 (27.7%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TET2 | E1411D | Altera | 10% | 191/1527 (12.5%) | 0/610 (0.0%) | 6/43 (14.0%) | 0 | 549/1576 (34.8%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TEX36 | H43Q | Altera | 10% | 1/351 (0.3%) | 0/141 (0.0%) | 0/31 (0.0%) | 0 | n/a | UNRESOLVED (Altera only) | absent in exome; WGS 0-2 fragments (uninformative at this depth) | passenger/VUS unless functional data |
| TM7SF2 | T270I | Altera | 14% | 40/484 (8.3%) | 0/202 (0.0%) | 1/19 (5.3%) | 0 | 58/380 (15.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TOR3A | K286T | Altera | 37% | 80/229 (34.9%) | 0/70 (0.0%) | 20/35 (57.1%) | 0 | 353/621 (56.8%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TP53 | c.559+2T>G | Altera |  | 441/1269 (34.8%) | 0/837 (0.0%) | 10/18 (55.6%) | 0 | 319/2279 (14.0%) | CONFIRMED (exome) |  | keep: truncal driver (not discussed by July 17 or EVEE) |
| TP63 | C8F | Altera | 14% | 22/284 (7.7%) | 0/82 (0.0%) | 17/73 (23.3%) | 0 | 0/7 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TPO | H511Q | Altera | 25% | 45/316 (14.2%) | 0/170 (0.0%) | 1/14 (7.1%) | 0 | 0/18 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TSC2 | R59W | Altera | 14% | 123/1146 (10.7%) | 0/702 (0.0%) | 2/14 (14.3%) | 0 | 1140/4748 (24.0%) | CONFIRMED (exome) |  | keep as unevaluated mTOR-axis candidate |
| TXNDC5 | V305I | Altera | 19% | 97/462 (21.0%) | 0/155 (0.0%) | 5/20 (25.0%) | 0 | 1013/4980 (20.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| TYRP1 | P47L | Altera | 8% | 52/423 (12.3%) | 0/140 (0.0%) | 7/44 (15.9%) | 0 | 0/1 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| UBD | K143N | Altera | 11% | 28/321 (8.7%) | 0/155 (0.0%) | 2/26 (7.7%) | 0 | 10/371 (2.7%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| USH2A | L860M | Altera | 6% | 56/664 (8.4%) | 0/228 (0.0%) | 9/83 (10.8%) | 0 | 0/1 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| USP10 | N557I | Altera | 10% | 19/249 (7.6%) | 0/108 (0.0%) | 3/32 (9.4%) | 0 | 202/1105 (18.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| USP50 | C194Y | Altera | 8% | 32/370 (8.6%) | 0/133 (0.0%) | 3/40 (7.5%) | 0 | 0/22 (0.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| VPS35 | c.506+1G>C | Altera | 5% | 55/372 (14.8%) | 0/168 (0.0%) | 5/37 (13.5%) | 0 | 57/1357 (4.2%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| VWA3B | F1111L | Altera | 17% | 34/235 (14.5%) | 0/149 (0.0%) | 3/19 (15.8%) | 0 | n/a | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ZNF648 | Y250C | Altera | 8% | 13/197 (6.6%) | 0/158 (0.0%) | 1/17 (5.9%) | 0 | 1/5 (20.0%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
| ZNF83 | D496A | Altera | 12% | 59/316 (18.7%) | 0/163 (0.0%) | 5/28 (17.9%) | 0 | 292/904 (32.3%) | CONFIRMED (exome) |  | passenger/VUS unless functional data |
