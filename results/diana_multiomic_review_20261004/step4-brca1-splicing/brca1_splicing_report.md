# BRCA1 c.81-1G>A: direct RNA evidence in the existing bulk tumor RNA-seq (step 4)

PRIVATE (git-ignored). Research prioritization only; not a clinical interpretation. 2026-10-03.
Genome build for everything below: hs37d5 / GRCh37, contig `17`, 1-based coordinates. Transcript NM_007294.4 (BRCA1, minus strand).

## 1. Headline

**Yes. The tumor RNA shows strong, specific, direct evidence that the exon 3 splice acceptor is not used normally.**
Of 453 fragments that cross the exon 2 donor toward exon 3, only 76 (16.8%, 95% CI 13.5-20.5%) use the canonical acceptor.
The rest are aberrant: 343 (75.7%) use cryptic acceptors inside exon 3, and 34 (7.5%) skip exon 3 entirely (exon 2 joined to exon 4).
The same metric is 0.58% (77/13,264; exact CI 0.46-0.73%) pooled over the other 20 testable BRCA1 exon acceptors, and at most 4.6% (exon 8) for any single other exon.
Exon 3 is therefore about 140-fold above the library background (one-sided Fisher/hypergeometric p < 1e-300).

What the data support, and what they do not:
- Supported: the tumor transcriptome contains abundant exon-3 mis-spliced BRCA1 RNA, dominated by the two AG dinucleotides that the sequence predicts become the next acceptor once the canonical AG is destroyed (+7 nt and +16 nt into exon 3). Every cryptic product and the skipping product is predicted to be a premature-stop transcript (section 4).
- Supported: the variant is in tumor DNA at 22.4% (134/598 exome fragments, CI 19.1-26.0%; 0/292 in the matched normal) and the variant allele is transcribed (48 of 60 informative RNA fragments carry it).
- Supported (model-dependent): allele-specific counts at a germline SNP imply that about 85% of BRCA1 RNA in this sample comes from the haplotype the tumor retained, and the canonical-acceptor fraction (about 17%) is about what is left for non-tumor cells. That is what you would expect if essentially all tumor-haplotype transcripts are mis-spliced.
- NOT shown: that the aberrant junction reads come from the mutant allele (the variant base lies inside the N gap of every junction read, no germline SNP is close enough to phase it, and there is no matched normal RNA). The link to the variant rests on sequence prediction (+7 and +16 are the next AGs), on the 20 internal control acceptors, and on the allelic-ratio consistency check, not on a read that carries both.
- NOT shown: NMD depletion, protein loss, biallelic status, HRD, or any treatment implication.

## 2. Gene model (task 1)

| Item | Value |
| --- | --- |
| Variant | hg38 chr17:43115780 C>T lifts (pyliftover, UCSC hg38ToHg19 chain) to hg19 17:41267797; hg19 plus-strand base is C (cDNA G), so REF validates; plus C>T = cDNA G>A |
| Position | intron 2, last base before exon 3 (c.81-1), acceptor AG of exon 3 |
| Affected exon | **exon 3**, hg19 17:41267743-41267796, **54 bp**, c.81_134 (RefSeq NM_007294.4 numbering AND legacy BIC numbering are both "exon 3"; they diverge after exon 3 because legacy numbering has no exon 4, so legacy = RefSeq + 1 for exons >= 4) |
| Neighbours | exon 2: 41276034-41276132 (99 bp, contains ATG at 41276113, c.1-80); exon 4 (legacy exon 5): 41258473-41258550 (78 bp) |
| Canonical exon 2 -> 3 junction (intron 2) | 17:41267797-41276033 (8,237 nt) |
| Exon 3 skipping junction (exon 2 -> 4) | 17:41258551-41276033 |
| Exon 3 -> 4 junction (intron 3) | 17:41258551-41267742 |
| Frame | 54 is a multiple of 3, but exon 2 ends at c.80 inside codon 27 (TG|T) and exon 4 starts with A, so the skipping joint reads TG|A = TGA (p.Cys27*, in silico). Skipping is "in frame" by length only |
| Candidate cryptic AGs | in the reference, AG dinucleotides at offsets from c.81-1 (+ = into exon 3): +7, +16, +34 inside exon 3 (+55, +59, +89 fall past the exon end, in intron 3) and -39, -64, -69, -87, -94 upstream in intron 2. Mutant sequence ...CTGCTA**A** replaces ...CTGCTA**G** |

Files: `results/gene_model.json`, `results/gene_model_exons.tsv`.

## 3. What the two RNA BAMs are

| BAM | Contents | Used for |
| --- | --- | --- |
| `...aligned.sorted.bam` (9.1 GiB) | STAR 2.7.3a alignments, coordinate-sorted, **N-CIGARs kept** (16,577 N-containing alignments in the 100 kb region), unique MAPQ 255, multi-mappers 3/1, no duplicate flags, no read group, no XS/jM tags | **all junction analysis** (primary) |
| `...aligned.recal.sorted.bam` (23.2 GiB) | STAR -> GATK 3.4 IndelRealigner -> **SplitNCigarReads** (maxMismatchesInOverhang=1, maxBasesInOverhang=40) -> PrintReads/BQSR. **Zero N-CIGARs** (junctions are split into hard-clipped segments), MAPQ 255 -> 60, MarkDuplicates flags (32.6% of fragments) | duplicate flags (by read name), SNP/variant allele counts, junction cross-check by reconstructing split segments |

Both agree. Reconstructing junctions from the recal BAM's split segments reproduces the raw-BAM fragment counts exactly for canonical (76), skipping (34), exon 3->4 (468), +7 (274) and +16 (38), and 13,496 vs 13,657 (-1.2%) summed over the 22 canonical introns. The one difference: the 30 "+10" fragments (section 3.2) are not recovered from the recal BAM (GATK overhang trimming removes reads with >1 mismatch in a short overhang), so the recal BAM slightly under-counts the aberrant species.
The library is dUTP-stranded (read 1 antisense): all 109 canonical-junction alignments are sense, and 60/60 variant-covering RNA fragments are sense; antisense reads at the locus are 0.

## 3.1 Junction counts (task 2)

Policy P1 (headline): STAR unique (NH=1, MAPQ 255), primary alignments, sense strand, anchors >= 8 bp each side, fragment level (a pair crossing the same junction counts once), marked duplicates included. Duplicate flags are transferred by read name from the recal BAM. Counts are sequencing fragments, not molecules (no UMIs).

Exon 3 acceptor, affected junctions (all numbers fragments):

| Class | P1 (with dups) | P2 (no marked dups) | P4 (anchor >= 15) |
| --- | --- | --- | --- |
| Canonical exon 2 -> 3 (17:41267797-41276033) | **76** | 54 | 72 |
| Skipping exon 2 -> 4 (17:41258551-41276033) | **34** | 22 | 28 |
| Cryptic acceptor, total (+/-100 bp of c.81-1, same exon 2 donor) | **343** | 246 | 324 |
|   +7 nt (17:41267790-41276033; r.81_87del, next AG) | 274 | 194 | 256 |
|   +16 nt (17:41267781-41276033; r.81_96del, second AG) | 38 | 29 | 37 |
|   +10 nt (17:41267787-41276033; r.81_90del, no AG; see 3.2) | 30 | 22 | 30 |
|   +5 nt (17:41267792-41276033) | 1 | 1 | 1 |
| Exon 3 -> 4 (downstream of the affected exon, all exon-3-containing transcripts) | 468 | 339 | 443 |
| Denominator (canonical + skipping + cryptic) | 453 | 322 | 424 |
| **PSI-style canonical fraction (95% exact CI)** | **16.8% (13.5-20.5)** | 16.8% (12.9-21.3) | 17.0% (13.5-20.9) |
| Skipping fraction | 7.5% (5.3-10.3) | 6.8% (4.3-10.2) | 6.6% (4.4-9.4) |
| Cryptic fraction | 75.7% (71.5-79.6) | 76.4% (71.4-80.9) | 76.4% (72.1-80.4) |
| Aberrant (skip + cryptic) | **83.2% (79.5-86.6)** | 83.2% (78.7-87.1) | 83.0% (79.1-86.5) |

Internal consistency: canonical + cryptic acceptor fragments (419) are about equal to the 468 exon 3 -> 4 fragments, as they should be (both count exon-3-containing transcripts). Unstranded counting (P3) and all-primary counting (P6) give 16.7% and 16.7%.

An alignment-independent check supports the same picture. Searching every read for the exact 24-mer that spans each possible exon 2 -> exon 3 junction (12 nt of exon 2 + 12 nt after the acceptor; `03b_sequence_rescore.py`) gives canonical 75, skipping 33, cryptic 322 (+7: 253, +16: 37, +10: 27, +4: 4, +5: 1), so PSI 17.4% (14.0-21.4%) and aberrant 82.6% (no-dup: 53/21/228, PSI 17.5%).

### 3.2 A STAR mis-alignment that was corrected

STAR aligned 30 fragments as junction 17:41267797-41276043 (canonical acceptor, "donor" 10 nt inside exon 2) with NM = 7 mismatches in the last 8-10 bases of the exon-3 block. Those reads contain the last 10 bases of exon 2 followed by exon 3 from c.91 with zero mismatches, i.e. exon 2 joined to exon 3 at +10 nt (r.81_90del). That junction has no AG (acceptor context ...GAGTTG|ATC), so it is a non-canonical product that STAR forced into a worse alignment. I reassigned them to the cryptic class (`STAR_MISALIGN_REMAP` in `scripts/common.py`; confirmed by sequence in `03b`). If they are dropped instead, canonical PSI is 18.0% and nothing changes qualitatively. The same artifact is what creates the 30 mismatching reads at c.81/c.82 in the RNA allele table at the flanks of the variant.

### 3.3 Background calibration (every other exon)

Same classification for every exon 2 and 4-22 (`results/exon_psi_calibration.csv`): canonical, skipping (exon k-1 -> k+1), and cryptic acceptor (same upstream donor, acceptor within +/-100 bp, not annotated in any BRCA1 RefSeq isoform).

| Quantity | Exon 3 | Other exons (2, 4-22) |
| --- | --- | --- |
| Aberrant fragments / total | 377 / 453 = 83.2% | 77 / 13,264 = 0.58% (0.46-0.73%) pooled |
| Single-exon median / max | n.a. | 0.17% / 4.6% (exon 8, 46 bp: 32 skipping vs 670 canonical fragments) |
| Cryptic-acceptor fragments | 343 | 5 across all other exons (exon 4: 2; exons 10, 13, 15: 1 each) |

Unspliced fragments that span the acceptor boundary (>= 8 bp each side) as a fraction of unspliced + spliced within +/-100 bp: exon 3 acceptor 42/479 = **8.8%**, versus median 2.9% (range 0.3-12.6%) over the other acceptors (`results/boundary_unspliced.csv`). So there is **no excess intron 2 retention beyond the background range**; the exon 3 acceptor is mis-spliced mostly by cryptic acceptor use, not by retention.

## 3.4 The variant locus (task 3)

c.81-1 = 17:41267797, plus-strand REF C, ALT T (BRCA1 is on the minus strand, so cDNA G>A).

| Assay | Policy | REF C | ALT T | Other | Fraction ALT (95% exact CI) |
| --- | --- | --- | --- | --- | --- |
| **Tumor exome** | fragments, MQ>=20, BQ>=20, mates collapsed | 464 | **134** | 0 | **22.4% (19.1-26.0)** |
| Tumor exome | BQ>=30 | 452 | 127 | 0 | 21.9% (18.6-25.5) |
| Tumor exome | all reads, no filter or collapse (reads, not fragments) | 664 | 201 | 1 G | 23.2% (20.5-26.2) |
| **Normal exome** | same as first | 292 | **0** | 0 | 0% (upper 97.5% bound 1.3%) |
| Tumor RNA (raw STAR BAM) | unique, sense, with dups | 12 | **48** | 0 | **80.0% (67.7-89.2)** |
| Tumor RNA | unique, sense, no marked dups | 8 | 36 | 0 | 81.8% (67.3-91.8) |
| Tumor RNA (recal BAM) | MQ 60 | 7 | 48 | 0 | 87.3% (75.5-94.7) |

- DNA: no strand bias (MQ>=20, BQ>=20 reads, not collapsed: ALT 81 forward / 114 reverse versus REF 280 / 384), same median distance from the read end (38 vs 39 bp), so no sign of an oxidation/deamination artifact. The exome BAMs contain no coordinate duplicates (they look duplicate-removed), so there is no separate de-duplicated count. 22.4% is consistent with the WGS value (about 21%, `review.md`) and the Altera report (27%) given the CIs.
- RNA: only unspliced reads can carry the variant base. All 89 alignments that cover it also cover the first exon 3 base, so they are reads that cross the exon 3 / intron 2 boundary (typically exon 4 -> exon 3 spliced via intron 3, then continuing into unspliced intron 2: partially processed or nascent RNA). The mutant allele is clearly transcribed (48/60). The 80% is not evidence of allele-specific retention: it is close to the 85% mutant-haplotype transcript share estimated below.
- Flanking bases (+/-2 bp) are in `results/variant_locus_allele_counts.csv`; the only mismatches are the 30 mis-aligned reads of section 3.2.

## 3.5 Allele-specific expression (task 4)

Germline het SNPs genotyped from the matched normal exome with bcftools mpileup/call (all SNV calls are in `results/normal_wes.brca1.calls.vcf`). Only **two** sites in the BRCA1 locus pass depth >= 20 and 0.3 <= AF <= 0.7; the exome simply does not cover more of the gene's common variants (the patient appears homozygous at the rest or they lie in poorly covered UTR).

| Site | Normal AD (ref,alt) | Tumor DNA, DNA-major allele | Tumor RNA, same allele (unique, sense, with dups) |
| --- | --- | --- | --- |
| 17:41246481 T>C, **exon 10** (legacy 11; the only exonic informative SNP) | 578, 546 | C: 1,094/1,755 = **62.3% (60.0-64.6)** | C: 669/722 = **92.7% (90.5-94.5)**; no marked dups 453/490 = 92.4% (89.7-94.6) |
| 17:41199638 C>G, intron 22 (22 bp from exon edge; unspliced RNA only) | 368, 354 | C: 728/1,087 = 67.0% (64.1-69.8) | C: 32/36 = 88.9% (73.9-96.9) |

RNA vs DNA at the exon SNP: Fisher p = 1.5e-60. The recal BAM gives the same counts (672/725).

Interpretation (hedged):
1. Tumor DNA is clearly allele-imbalanced at both sites (62-67% vs 50% in normal), i.e. LOH or allelic loss at 17q21, as the earlier BAF analysis suggested.
2. If the tumor kept one haplotype and the somatic variant sits on it, the extra fraction of that haplotype equals the variant allele fraction: 2 x 0.623 - 1 = 0.247 (0.200-0.292) versus the measured 22.4% (19.1-26.0%). That is consistent (the intronic SNP gives 0.34, 0.28-0.40, a little higher; the two sites differ at p = 0.013). It supports, but does not prove, a clonal variant on the retained haplotype.
3. RNA is far more imbalanced than DNA (92.7% vs 62.3%). If tumor cells express only the retained haplotype and non-tumor cells are 50:50, the tumor-derived share of BRCA1 RNA is 2 x 0.927 - 1 = **0.853 (0.810-0.889)**, versus a DNA-level tumor fraction of roughly 35-40% (VAF 22% on a single retained copy). Tumor cells therefore over-represent in BRCA1 RNA, or the retained haplotype is also more expressed in cis.
4. Joint check: with that share, the expected non-tumor ("wild-type spliced") fraction is 1 - 0.853 = 14.7% (11.1-19.0%), versus the observed canonical-acceptor fraction of 16.8% (13.5-20.5%) or 17.4% (14.0-21.4%) by sequence. The two independent measurements overlap, as expected if almost all tumor-haplotype transcripts are mis-spliced at exon 3. This does not by itself resolve NMD: it shows aberrant transcripts are abundant in the bulk RNA, not that they are or are not depleted relative to what they would be without NMD.

**Phasing: unphased.** No germline het SNP lies within +/-500 bp of the variant in the normal exome (726 positions with depth >= 10 in that 1 kb window, none heterozygous), the exon 10 SNP is 21 kb away, and every junction read has the variant inside its N gap. Which haplotype carries the variant is therefore inferred, not observed. No long reads or linked reads exist for this sample.

## 4. Predicted consequence of each observed product (in silico, from reference sequence)

| Product | Deletion | Predicted translation | NMD (50-nt rule) |
| --- | --- | --- | --- |
| +5 | r.81_85del | frameshift, stop at codon 27 (26 aa) | predicted |
| +7 | r.81_87del | frameshift, stop at codon 28 (27 aa) | predicted |
| +10 | r.81_90del | frameshift, stop at codon 27 (26 aa) | predicted |
| +16 | r.81_96del | frameshift, stop at codon 44 (43 aa) | predicted |
| exon 3 skipping | r.81_134del | joint TG\|A = stop, p.Cys27* (26 aa) | predicted |

All premature stops are very 5' (RING domain disrupted) and many exon junctions lie downstream of each. This is prediction only: NMD and translation re-initiation or NMD escape for 5' stops were not measured or modeled, and the residual canonical product is the only one that encodes full-length BRCA1.

## 5. Coverage

- BRCA1 locus (17:41196311-41277381): 24,987 primary fragments; 24,579 are unique sense fragments on NM_007294.4 exons; 9,342 are spliced; 16,523 remain after removing marked duplicates (32.6% of fragments are duplicate-flagged).
- Mean unique sense depth: exon 2 780x, exon 3 748x, exon 4 850x, exon 10 1,185x (matches the ~62 TPM expectation: not low coverage at all).
- Exome at the variant: 598 tumor and 292 normal fragments (MQ >= 20, BQ >= 20).
- Coverage is **sufficient** for the splicing conclusion (453 informative fragments at the affected junction), adequate for the DNA VAF, and **thin** for the allele-specific analysis (one exonic SNP; the variant-covering RNA reads number only 60).

## 6. Limitations

1. **No matched normal RNA or non-tumor control.** I cannot show that the +7/+16/skipping species are absent in normal breast tissue. Mitigations: 20 other BRCA1 acceptors show at most two cryptic fragments each, +7 and +16 are exactly the next two AGs after the destroyed AG, and the allelic-ratio check is consistent. A constitutive minor isoform at the +7 acceptor cannot be formally excluded without normal RNA or public control data (not pulled here).
2. **Allele linkage is missing.** Junction reads cannot show the variant allele; unphased. The statement that the aberrant junctions come from the mutant allele is an inference.
3. **Purity dilution and bulk mixing.** Tumor purity is uncertain (about 31-45% from DNA), and RNA is dominated by tumor cells (about 85% share estimated), so fractions are mixtures of tumor and non-tumor RNA, not per-allele penetrance. Wild-type-spliced reads come at least partly from non-tumor cells.
4. **Alignment and BAM handling.** STAR 2.7.3a (single sample, no XS tags); the recal BAM is GATK SplitNCigarReads-processed and loses junctions with mismatching short overhangs (-1.2% overall, all 30 of the "+10" reads). I corrected one systematic STAR mis-alignment (section 3.2) by hand, checked it by exact sequence, and cannot rule out other low-count mis-alignments. Anchor >= 8 bp and unique-only filters are conservative.
5. **Duplicates.** 32.6% of fragments are flagged duplicates; RNA duplicates are not necessarily artifacts and there are no UMIs, so counts are fragments and not molecules. All headline results hold without them.
6. **No isoform-resolved long reads.** Co-occurrence of events (for example +7 together with retained intron 2 or with exon 4 skipping) is unresolved. Skipping fragments cannot say whether other exons are also skipped.
7. **ASE rests on one exonic SNP** and a simple model (tumor cells express one haplotype, non-tumor 50:50, no cis-regulatory or NMD asymmetry). The 85% tumor share is model-based and much larger than the DNA tumor fraction; that discrepancy is itself unexplained.
8. **Specimen identity.** The RNA, exome and normal are from the same Personalis E019 delivery, and the variant is seen in the E019 tumor exome and absent in the E019 normal, so that is consistent. Whether this is the same specimen as the WGS, Altera and proteomics samples is still unknown (step 1).
9. Research prioritization only. No clinical, HRD, or treatment claims are made.

## 7. Files

All under `/Users/jasonlaster/src/projects/diana-omics/private/analysis/step4-brca1-splicing/`: `junction_counts.csv`, `allele_counts.csv`, `figures/brca1_exon3_sashimi.png`, `evidence_igv_style.txt`, `results/` (calibration, summaries, SNP calls, per-read junction list, cross-checks), `region_bams/` (four small BAMs + indices), `scripts/` (all code, `run_all.sh`), `README.md` (commands, versions, bytes transferred).
