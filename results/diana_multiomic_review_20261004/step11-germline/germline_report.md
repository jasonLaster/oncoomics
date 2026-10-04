# Step 11: germline cancer-predisposition cross-check from the matched normals (private, 2026-10-03)

**Research cross-check only. This is NOT a clinical germline test.** It uses research-grade short-read data and local
methods with no clinical validation. A negative result here does **not** exclude a pathogenic variant. Any finding, and any
decision that depends on germline status (including PARP-inhibitor eligibility, cascade testing of relatives, risk-reducing
surgery), requires a CLIA/CAP-certified germline test and genetic counseling. The hereditary panel that was reportedly negative
is not on disk; this analysis does not replace it, and its report should be obtained.

Git-ignored directory (`private/`); never commit. Machine-readable outputs: `variants_annotated.tsv`, `coverage_by_gene.csv`,
`results/`. Methods, versions, commands and bytes: `README.md`.

## 1. Bottom line

1. **No pathogenic/likely pathogenic germline variant and no rare loss-of-function variant was found** in 29 hereditary
   breast/ovarian, Lynch and HR-repair genes (MANE coding exons +/-20 bp, 115,589 bp), in either normal assay.
   All 38 SNVs are concordant between the normal WGS (GRCh38, ~40x usable) and the deep normal exome (hs37d5, ~100-800x);
   every called variant is in ClinVar as benign/likely benign and common (gnomAD AF >=1.8%). No VUS was called.
2. **Two ClinVar "conflicting (includes P/LP)" calls were examined and rejected as artifacts**: MSH2 c.942+2_942+4del (A27
   homopolymer at the intron-5 donor, exome-only, reverse-strand post-homopolymer errors) and PALB2 c.212-10del (WGS 1 fragment,
   exome 0/129).
3. **An independent allele-forced scan of all ~39,400 ClinVar P/LP (and conflicting-with-P/LP) alleles** in the target found no
   allele with >=2 reads at >=5% VAF in the WGS normal; in the exome normal only the MSH2 homopolymer artifact (5.5%); every other
   exome hit was <=2.9% and the >=5-read ones were reverse-strand/low-quality only. 15 founder/recurrent variants (incl. CHEK2
   c.1100delC, BRCA1 185delAG/5382insC, BRCA2 6174delT, PALB2 c.1592delT, ATM c.7271T>G) were absent.
4. **No exon-level BRCA1/BRCA2/PALB2 deletion or duplication was detected** by WGS depth (the one rule-based flag, BRCA1 exons
   21-22 high, is not supported by the intervening intronic bins). Resolution is limited (section 5).
5. **BRCA1 c.81-1G>A and BRCA2 c.8084C>T are somatic**: 0 alt in 333 / 832 pooled normal fragments (95% upper bound on a
   germline-mosaic VAF 0.9% / 0.36%), present in both tumors. Tumor allelic imbalance at germline-het SNPs across BRCA1
   (and BRCA2) is consistent with LOH at ~30-40% purity (context, not an allele-specific CN call).

## 2. Method (summary)

- Genes: NCCN Genetic/Familial High-Risk Assessment (Breast, Ovarian, Pancreatic) high/moderate-penetrance genes (BRCA1, BRCA2,
  PALB2, TP53, PTEN, CDH1, STK11, CHEK2, ATM, BARD1, RAD51C, RAD51D, BRIP1, NF1), Lynch genes (MLH1, MSH2, MSH6, PMS2, EPCAM),
  plus requested HR/Fanconi genes (RAD51B, FANCA, FANCC, FANCM, NBN, MRE11, RAD50, XRCC2, ABRAXAS1, BAP1). Transcripts: Ensembl
  canonical = MANE Select for all 29 (RefSeq IDs in `coverage_by_gene.csv`); GRCh37 via liftover of every exon boundary
  (lengths asserted). Target = coding part of each exon +/-20 bp, UTR-only exons +/-20 bp. Exon numbering is sequential MANE
  numbering (BRCA1 has 23 exons; legacy BRCA1 numbering skips "exon 4").
- Data: only gene windows streamed (exons +/-300 bp; BRCA1/BRCA2/PALB2 gene bodies +/-20 kb) from the four BAMs.
- Calling: `bcftools mpileup -q20 -Q20 -a AD,DP` + `call -m`, pass A (default indel model) and pass B (`--indels-cns`),
  `norm -m -both`; per-sample, separately for WGS and exome. The exome's default indel depth cap (-L 250) silently suppressed
  indel calls at >250x and was lifted (-L 100000). Union of passes and platforms (exome lifted to GRCh38 and REF-checked), then
  every union site re-genotyped in all four BAMs (forced SNV alleles; read-level counting for indels).
- Annotation: local MANE consequence/HGVS (`scripts/txlib.py`, validated on 17 known variants: `results/txlib_selftest.json`),
  ClinVar VCF 2026-09-28, gnomAD v4.1 exome frequencies (downloaded by gene region, not by patient variant). No patient-derived
  variant or sequence was sent to any external service (VEP REST was not needed).

## 3. Callable coverage (depth >=20 at MAPQ>=20, BQ>=20; `coverage_by_gene.csv`, per exon in `results/coverage_by_exon.csv`)

Overall: WGS 97.1%, exome 99.84%, either 99.84% of 115,589 target bp.

| Gene | WGS mean | WGS >=20 | Exome mean | Exome >=20 | Notes |
|---|---|---|---|---|---|
| BRCA1 | 44 | 99.9% | 810 | 100% | |
| BRCA2 | 38 | 99.5% | 684 | 100% | |
| PALB2 | 41 | 98.1% | 614 | 100% | |
| TP53 / CDH1 / STK11 / RAD51D / BAP1 / XRCC2 | 42-53 | 100% | 112-650 | 100% | |
| PTEN / EPCAM / FANCA / FANCC | 34-49 | 99.6-100% | 438-612 | 100% | |
| CHEK2 | 41 | 94.3% | 509 | 100% | CHEK2 exons 10-14 have pseudogene copies; short-read calling there is less reliable |
| ATM / NF1 / MSH6 / BARD1 / RAD51C / MRE11 / ABRAXAS1 | 35-45 | 97.0-98.7% | 108-749 | 100% | BARD1, ABRAXAS1, XRCC2, NBN exome depth only ~110-140x |
| BRIP1 / MLH1 / MSH2 / FANCM | 35-43 | 94.4-95.7% | 491-654 | 100% | |
| NBN / RAD50 | 35 | 91.8-92.0% | 115-483 | 100% | |
| RAD51B | 34 | 81.6% | 444 | 100% | |
| **PMS2** | 31 | **86.0%** | 549 | **94.2%** | exon 15 (and the PMS2CL-homologous 3' exons generally) loses MAPQ>=20 reads in both assays; not callable by this method |

Every gene except PMS2 is >=99.99% callable at >=20x in at least one assay (the exome). PMS2 needs a pseudogene-aware assay.

## 4. Findings

### 4a. ClinVar P/LP: none

| Check | Result |
|---|---|
| De novo calls with ClinVar P/LP | 0 of 54 called alleles (38 SNV, 16 indel) |
| Allele-forced scan of all ClinVar P/LP + conflicting-with-P/LP alleles in target | WGS 39,400 alleles (38,361 at >=20x): none with >=2 alt reads at >=5%. Exome 39,399 (39,179 at >=20x): one at >=5% (MSH2 homopolymer artifact, below); all others <=2.9% |
| Founder / recurrent variants (15) | all absent (WGS 0 alt in 22-43 fragments each; exome 0 alt in 56-858, except CHEK2 c.1100delC 2/481 = 0.4%, background) (`results/founder_check.json`) |

### 4b. Rare LoF (stop, frameshift, canonical splice +/-1/2, start loss; gnomAD AF <0.1%): none after review

| Call | Evidence | Verdict |
|---|---|---|
| MSH2 c.942+2_942+4del (chr2:47414419 GTAA>G; ClinVar conflicting incl. P/LP; gnomAD 1.1e-5) | exome pass-B only; sits in the intron-5 A27 tract. Read-sequence check without alignment: forward reads (which read +2 before the tract) show T at +2 in 167/167 exome and 15/15 WGS fragments; every non-T base at +2 is on reverse-strand reads that traverse the A27 first, mostly BQ<30; same 22% pattern in the tumor exome. MSH2 c.942+3A>T was not seen in forward reads | artifact (`results/msh2_c942_tract_reads.json`) |

### 4c. Other flagged / reviewed calls

| Call | Evidence | Verdict |
|---|---|---|
| PALB2 c.212-10del (chr16:23636343 GA>G; ClinVar conflicting) | WGS pass B only, QUAL 15.6, 1 alt fragment; exome 0/129; tumor exome ~0 | not supported (homopolymer artifact) |
| ATM c.1236-18 insTT (C>CTT) | 4-6% in all four assays alongside the real common +T het | slippage artifact |
| ATM hg19 11:108183167 A>G (exome hom) | GRCh38 reference is G at this site (GRCh37 carries the minor allele) | hom-ref on GRCh38; not a variant |
| Exome-only low-fraction P/LP SNV hits with >=5 reads (NF1 chr17:31181787 T>G 1.7%, MSH2 chr2:47414420 T>G 2.9%, MSH2 chr2:47475272 T>G 2.0%) | all alt reads reverse strand, nearly all BQ<30, adjacent to homopolymers; same fraction in tumor exome | sequencing artifacts (`results/lowvaf_followup.json`) |

### 4d. VUS: none called

All 54 called alleles are in ClinVar: Benign 32, Benign/Likely benign 19, Likely benign 1, Conflicting 2 (the two artifacts
above). No rare (gnomAD <0.1%) missense, in-frame or splice-region variant was called. Notable common benign variants present
(no interpretation implied): TP53 p.Pro72Arg het, BRCA1 p.Gln356Arg het, BRCA2 p.Val2466Ala hom, FANCM p.Thr1600Ile het
(gnomAD 2.0%). Full list: `variants_annotated.tsv`.

### 4e. WGS vs exome concordance (`results/concordance_summary.json`)

SNVs: 38/38 called in both, 38/38 genotype-concordant (24 het, 14 hom). Indels: 16 alleles, 7 concordant, 8 not evaluable
(WGS <20 informative fragments in homopolymers) and 1 discordant (the ATM CTT slippage allele); all indel discordance sits in
homopolymer tracts.

## 5. Large rearrangement screen (normal WGS depth; `results/cn_*`)

- Exon depth / median exon depth of the 26 other genes (baseline 39.7x): BRCA1 exon ratios 0.68-1.41 (median 1.15), BRCA2
  0.63-1.32 (0.95), PALB2 0.76-1.36 (0.99).
- Rule ">=2 consecutive exons outside 0.65-1.35": one flag, **BRCA1 exons 21-22 "high" (1.37, 1.41)**. Not supported: within-
  gene ratios 1.20/1.23, the six 1-kb intronic bins spanning exons 21-22 are 0.90-1.14, and there is no split/discordant read
  cluster there. Interpreted as noise.
- Calibration: the same rule applied to the 26 comparator genes flags 22.8% of exons singly and >=1 adjacent pair in 11/26
  genes, so exon-level ratios from ~40x WGS are noisy for short exons (no GC correction, no panel of normals).
- 1-kb bins across gene bodies +/-20 kb (SD 0.16-0.17): no run of >=2 consecutive bins <0.65 or >1.35 inside BRCA1, BRCA2 or
  PALB2. One high pair (1.47, 1.38) at chr17:43,027-43,029 kb lies ~15 kb beyond the BRCA1 3' end, next to a split/discordant
  read cluster at 43,024-43,025 kb; outside the gene, of unclear meaning (likely a repeat/polymorphic insertion).
- Sensitivity: a heterozygous deletion/duplication of >=~2 kb (e.g. multi-exon BRCA1 deletions, BRCA1 exon 13 legacy /
  MANE exon 12 duplication ~6 kb) should produce >=2 consecutive outlying bins and was not seen; single small exons,
  sub-kb events, balanced rearrangements and Alu insertions are not reliably excluded. Not done for the other 26 genes, except
  as comparators. Clinical MLPA/NGS-CNV remains the standard.

## 6. Somatic vs germline confirmation (`results/somatic_confirmation.json`)

Fragments, MAPQ>=20, BQ>=20, overlapping mates collapsed. 95% upper bound for 0 alt = 1-0.05^(1/n).

| Variant | WGS normal | Exome normal | Pooled normals (95% upper VAF) | WGS tumor | Exome tumor |
|---|---|---|---|---|---|
| BRCA1 c.81-1G>A (chr17:43115780 C>T) | 0/41 | 0/292 | 0/333 (<0.9%) | 4/23 (17%) | 134/598 (22.4%) |
| BRCA2 c.8084C>T p.Ser2695Leu (chr13:32363286) | 0/54 | 0/778 | 0/832 (<0.36%) | 5/37 (14%) | 201/1362 (14.8%) |

Without any read filter: 0 T reads in 54 (WGS) and 379 (exome) normal reads at BRCA1; 0 in 91 / 936 at BRCA2. A germline
heterozygous variant (expected ~50%) is excluded; low-level germline mosaicism above ~1% (BRCA1) is unlikely in blood-derived
normal DNA (tissue mosaicism elsewhere cannot be tested).

LOH context: at 9 WGS-normal het SNPs across BRCA1 +/-20 kb, the tumor median minor-allele fraction is 0.33 (normal 0.46);
in the deep exome, BRCA1 p.Gln356Arg shows 62.3% C in tumor (1094/1755) vs 48.9% in normal, and
chr17:43047621 C>G 33% G in tumor vs 49% in normal. Allelic imbalance of this size fits LOH in a ~30-40% pure tumor (it is also
seen at BRCA2: 0.31 vs 0.44, 34 SNPs). Phasing of the somatic splice variant to the retained haplotype was not attempted here;
allele-specific copy number belongs to step 2.1/5.

## 7. Limitations

- Research pipeline (bcftools on regional BAMs), not a validated clinical assay; no orthogonal (Sanger/MLPA) confirmation.
- Coverage gaps: PMS2 3' exons (pseudogene PMS2CL), CHEK2 exons 10-14 (pseudogenes) and any MAPQ<20 sequence; deep intronic and
  promoter variants (target is coding +/-20 bp); BRCA1/BRCA2 promoter methylation; genes outside the panel (e.g. other
  hereditary syndromes).
- Homopolymer/STR loci (e.g. MSH2 intron-5 A27, MSH6/PMS2 poly-T) cannot be genotyped reliably from these short reads.
- Copy-number screen: WGS only, ~40x, no GC correction or panel of normals; single-exon and sub-kb events not excluded;
  structural variants assessed only by coarse split/discordant counts in BRCA1/BRCA2/PALB2.
- The exome FASTQs were described as "downsampled" (step 1); WGS normal and exome normal are assumed to be the same blood/normal
  source (not individually documented; 38/38 SNV concordance supports same individual).
- ClinVar/gnomAD snapshots dated 2026-09-28 / v4.1; classifications change.
- Anything significant must be confirmed in a CLIA lab with genetic counseling; this cross-check cannot clear the patient.
