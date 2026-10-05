# Deep-exome audit of the ten EVEE-report alleles (Personalis ImmunoID tumor/normal exome, hs37d5 / GRCh37)

Research prioritization only; no clinical claim. Generated 2026-10-03.

## Bottom line

1. **None of the nine highlighted EVEE SNVs is present in the deep tumor exome.** Primary-policy tumor fragments carrying the ALT: 0 of 172-740 at every site (MTOR 0/740, SCAP 0/274, RXRA 0/290, CUL3 0/172, DLL4 0/232, ATG4B 0/197, ATG13 0/272, FGFR4 0/631, BRD3 0/360); zero in the matched normal; identical under the relaxed and strict policies; and **zero ALT bases among 4,654 unfiltered tumor pileup reads** (every flag/MQ/BQ filter disabled). One-sided 95% upper bounds on the allele fraction are 0.40%-1.73%. No non-reference allele with >=3 tumor and 0 normal fragments exists within +/-10 bp of any of them.
2. **The same exome reproduces the control and four other independently reported variants at the expected size**, so this is not a sensitivity or specimen problem: BRCA1 c.81-1G>A 126/573 = 21.99% (18.66%-25.61%) (normal 0/281; Altera 27%, WGS Mutect2 20.8%); BRCA2 p.Ser2695Leu 191/1291 = 14.8% (Altera 12%); PIKFYVE p.Ile1548Thr 15/166 = 9.0% (Altera 12%); MTOR p.Pro1125Ala 96/1021 = 9.4% (Altera 12%); PTPN23 p.Pro981Ala 30/185 = 16.2% (Altera 14%). All are absent from the normal exome and have balanced F1R2/F2R1 orientation.
3. **The earlier WGS 'support' does not replicate.** Seven loci had exactly one alternate fragment (both mates concordant) at 7-14 tumor WGS fragments; the exome, 14-74x deeper at those seven loci, shows none. Those WGS observations come from a call list whose caller metrics were never recovered (EVEE report: '607 somatic variants'), are single molecules, and are not corroborated by the Altera DNA table (132 small variants at 5-37% VAF), which lists none of the nine protein changes (it lists MTOR P1125A, not G98S). The singletons are best read as low-level artifact/noise selected into a lenient call list; a specimen difference is unlikely because the WGS also carries the BRCA1 and BRCA2 calls seen in the exome and Altera. The data cannot fully separate these explanations.
4. **RNA gives no allelic support** for any of the nine (0-4 alt reads, <=0.56%, at or below the same-class RNA noise; RNA depth at the site is thin for DLL4 (40 fragments) and FGFR4 (322)). RNA is allelic-expression evidence only.
5. **Evidence state: 9/9 'absent with an upper bound' (module gate: `alternate_not_observed_at_this_depth` under all three policies, also on coordinate-unique molecules); BRCA1 control `tumor_enriched_read_support`.** This removes the genetic premise of every EVEE hypothesis that rests on these alleles *in this exome specimen*; it says nothing about pathway activity.

## 1. Liftover (GRCh38 -> GRCh37/hs37d5) and REF validation

Method: `pyliftover` 0.4.1 with the UCSC `hg38ToHg19.over.chain.gz`; REF checked against hg19 sequence from the UCSC REST API (`genome=hg19`, 0-based start, 21 bp window); then an independent check with Ensembl VEP on the GRCh37 REST server (must reproduce the reported protein change / HGVSc). hs37d5 contigs are `1..22,X,Y,MT`; chr1-22/X/Y sequence is identical between hg19 and GRCh37 primary assembly.

| Gene | GRCh38 | GRCh37 (hs37d5) | strand | REF>ALT (GRCh37) | hg19 base | REF valid | 21-bp hg19 window (center = site) | VEP GRCh37 (canonical) |
|---|---|---|---|---|---|---|---|---|
| MTOR (p.Gly98Ser) | chr1:11257145 | 1:11317202 | + | C>T | C | yes | `GCATTCCCAC[C]TTCCACTCCT` | c.292G>A p.Gly98Ser (missense_variant) |
| SCAP (p.Trp633Ter) | chr3:47419370 | 3:47460860 | + | C>T | C | yes | `GAGCGTCGGC[C]AGTGGCGGAA` | c.1898G>A p.Trp633Ter (stop_gained) |
| RXRA (p.Ser96Ter) | chr9:134408156 | 9:137300002 | + | C>A | C | yes | `CAGCTCAGCT[C]ACCTATGAAC` | c.287C>A p.Ser96Ter (stop_gained) |
| CUL3 (p.Arg354Cys) | chr2:224506102 | 2:225370819 | + | G>A | G | yes | `AGGAGGAAGC[G]ATCGAACCTA` | c.1060C>T p.Arg354Cys (missense_variant) |
| DLL4 (p.Arg516Cys) | chr15:40936533 | 15:41228731 | + | C>T | C | yes | `TGTGGGCAGC[C]GCTGCGAGTT` | c.1546C>T p.Arg516Cys (missense_variant) |
| ATG4B (p.Trp142Ter) | chr2:241655311 | 2:242594726 | + | G>A | G | yes | `TAGGCCAGTG[G]TACGGGCCCA` | c.426G>A p.Trp142Ter (stop_gained) |
| ATG13 (p.Asp213Gly) | chr11:46657565 | 11:46679115 | + | A>G | A | yes | `ATTATTATTG[A]TCACTTTGTG` | c.638A>G p.Asp213Gly (missense_variant) |
| FGFR4 (p.Ser106Phe) | chr5:177090615 | 5:176517616 | + | C>T | C | yes | `GCACGAGGCT[C]CATGATCGTC` | c.317C>T p.Ser106Phe (missense_variant) |
| BRD3 (p.Ser676Gly) | chr9:134034740 | 9:136899862 | + | T>C | T | yes | `AGCTGCCCGC[T]GACATCCTGC` | c.2026A>G p.Ser676Gly (missense_variant) |
| BRCA1 (c.81-1G>A) | chr17:43115780 | 17:41267797 | + | C>T | C | yes | `CAACTCCAGA[C]TAGCAGGGTA` | c.81-1G>A (splice_acceptor_variant) |
| PPARD (p.Gln415His) | chr6:35425998 | 6:35393775 | + | G>C | G | yes | `AGCACGCCCA[G]ATGATGCAGC` | c.1245G>C p.Gln415His (missense_variant) |
| PIKFYVE (p.Ile1548Thr) | chr2:208338539 | 2:209203263 | + | T>C | T | yes | `CCACGGAATA[T]TTCTCCAGGA` | c.4643T>C p.Ile1548Thr (missense_variant) |
| BRCA2 (p.Ser2695Leu) | chr13:32363286 | 13:32937423 | + | C>T | C | yes | `GACATAATTT[C]ATTGAGCGCA` | c.8084C>T p.Ser2695Leu (missense_variant) |
| RB1CC1 (reported splice donor, no alleles) | chr8:52624715 | 8:53537275 | + | REF A (ALT unknown) | A | yes | `TGTCGTTTTT[A]CCTTTTTGGC` | Ensembl ENST00000025008 (minus strand): exon ends at 52624717, so 52624715 is intron position +2 of a donor |

All ten sites lift uniquely (one chain hit, strand +, no mismatches); the nine protein changes and BRCA1 c.81-1G>A reproduce on GRCh37 transcripts. The BRCA1 control lifts to **17:41267797 C>T, exactly Altera's reported coordinate `chr17:41267797` (ENST00000357654, c.81-1G>A)**; on the minus-strand gene the genomic C>T is the sense G>A, with exon 3 starting at 41267796 (Ensembl GRCh37). Extra loci: PPARD Gln415His is derived from the protein change (CAG codon position 3, G>C; codon verified as CAG, one candidate SNV); PIKFYVE Ile1548Thr likewise (ATT, T>C); BRCA2 Ser2695Leu from the recorded WGS Mutect2 call (chr13:32363286 C>T GRCh38). The `RB1CC1` coordinate is the +2 base of a canonical-transcript splice donor on the minus-strand gene (sense T = genomic A).

## 2. Per-site summary (one row per site)

Counts are fragment-level under the repo rules (duplicates/secondary/supplementary/QC-fail out, overlapping mates collapsed, discordant mates removed). The exome BAMs carry no duplicate flags and fragments are essentially all coordinate-unique (dup_factor 1.000-1.001; one coincident pair across all 78 site x sample x policy sets), so duplicates appear to have been removed upstream; coordinate-unique counts equal fragment counts (+/-1). VAF 95% CI is exact Clopper-Pearson; 'upper' is the one-sided 95% bound (zero ALT: 1-0.05^(1/n)). Policies: relaxed MQ>=20/BQ>=20/end>=0; primary MQ>=30/BQ>=30/end>=5; strict MQ>=40/BQ>=30/end>=10. The 'unfiltered pileup' column is the raw base count with every read filter disabled; an independent `samtools mpileup -Q0 -q0 -B -A --ff 0` text pileup reproduces it exactly for all 20 site x sample pairs (`results/samtools_mpileup_crosscheck.json`). Non-ALT non-reference bases do occur (e.g. 2 C>A reads at SCAP, 1 C>G at FGFR4) but never the EVEE ALT.

| Gene (protein) | GRCh37 | Tumor ALT/depth: relaxed \| primary \| strict | Tumor VAF (95% CI): relaxed \| primary \| strict | Upper95 (primary) | Normal ALT/depth: relaxed \| primary \| strict | Unfiltered tumor pileup (ALT/total) | State (module gate, all 3 policies) |
|---|---|---|---|---|---|---|---|
| MTOR (p.Gly98Ser) | 1:11317202 C>T | 0/793 \| 0/740 \| 0/696 | 0.00% (0.00%-0.46%) \| 0.00% (0.00%-0.50%) \| 0.00% (0.00%-0.53%) | 0.40% | 0/426 \| 0/402 \| 0/389 | 0/1065 | `alternate_not_observed_at_this_depth` |
| SCAP (p.Trp633Ter) | 3:47460860 C>T | 0/293 \| 0/274 \| 0/256 | 0.00% (0.00%-1.25%) \| 0.00% (0.00%-1.34%) \| 0.00% (0.00%-1.43%) | 1.09% | 0/214 \| 0/202 \| 0/188 | 0/403 | `alternate_not_observed_at_this_depth` |
| RXRA (p.Ser96Ter) | 9:137300002 C>A | 0/299 \| 0/290 \| 0/280 | 0.00% (0.00%-1.23%) \| 0.00% (0.00%-1.26%) \| 0.00% (0.00%-1.31%) | 1.03% | 0/180 \| 0/165 \| 0/157 | 0/434 | `alternate_not_observed_at_this_depth` |
| CUL3 (p.Arg354Cys) | 2:225370819 G>A | 0/190 \| 0/172 \| 0/165 | 0.00% (0.00%-1.92%) \| 0.00% (0.00%-2.12%) \| 0.00% (0.00%-2.21%) | 1.73% | 0/36 \| 0/35 \| 0/32 | 0/264 | `alternate_not_observed_at_this_depth` |
| DLL4 (p.Arg516Cys) | 15:41228731 C>T | 0/258 \| 0/232 \| 0/228 | 0.00% (0.00%-1.42%) \| 0.00% (0.00%-1.58%) \| 0.00% (0.00%-1.60%) | 1.28% | 0/176 \| 0/166 \| 0/157 | 0/351 | `alternate_not_observed_at_this_depth` |
| ATG4B (p.Trp142Ter) | 2:242594726 G>A | 0/201 \| 0/197 \| 0/190 | 0.00% (0.00%-1.82%) \| 0.00% (0.00%-1.86%) \| 0.00% (0.00%-1.92%) | 1.51% | 0/108 \| 0/105 \| 0/101 | 0/295 | `alternate_not_observed_at_this_depth` |
| ATG13 (p.Asp213Gly) | 11:46679115 A>G | 0/285 \| 0/272 \| 0/265 | 0.00% (0.00%-1.29%) \| 0.00% (0.00%-1.35%) \| 0.00% (0.00%-1.38%) | 1.10% | 0/124 \| 0/119 \| 0/114 | 0/415 | `alternate_not_observed_at_this_depth` |
| FGFR4 (p.Ser106Phe) | 5:176517616 C>T | 0/678 \| 0/631 \| 0/592 | 0.00% (0.00%-0.54%) \| 0.00% (0.00%-0.58%) \| 0.00% (0.00%-0.62%) | 0.47% | 0/614 \| 0/577 \| 0/541 | 0/885 | `alternate_not_observed_at_this_depth` |
| BRD3 (p.Ser676Gly) | 9:136899862 T>C | 0/372 \| 0/360 \| 0/345 | 0.00% (0.00%-0.99%) \| 0.00% (0.00%-1.02%) \| 0.00% (0.00%-1.06%) | 0.83% | 0/177 \| 0/165 \| 0/161 | 0/542 | `alternate_not_observed_at_this_depth` |
| BRCA1 (c.81-1G>A) | 17:41267797 C>T | 134/598 \| 126/573 \| 121/555 | 22.41% (19.13%-25.97%) \| 21.99% (18.66%-25.61%) \| 21.80% (18.43%-25.47%) | 25.03% | 0/292 \| 0/281 \| 0/270 | 201/866 | `tumor_enriched_read_support` |

Extra loci (same method; PPARD, PIKFYVE and BRCA2 from section 1; the last two rows are tumor-only somatic-like positions found incidentally inside the +/-50 kb windows):

| Locus | GRCh37 | Tumor ALT/depth: relaxed \| primary \| strict | Tumor VAF (95% CI), primary | Normal ALT/depth (primary) | State |
|---|---|---|---|---|---|
| PIKFYVE (p.Ile1548Thr) | 2:209203263 T>C | 15/173 \| 15/166 \| 15/161 | 9.04% (5.15%-14.47%) | 0/57 | `tumor_enriched_read_support` |
| BRCA2 (p.Ser2695Leu) | 13:32937423 C>T | 201/1362 \| 191/1291 \| 186/1226 | 14.79% (12.90%-16.85%) | 0/744 | `tumor_enriched_read_support` |
| PPARD (p.Gln415His) | 6:35393775 G>C | 0/653 \| 0/623 \| 0/602 | 0.00% (0.00%-0.59%) | 0/263 | `alternate_not_observed_at_this_depth` |
| MTOR p.Pro1125Ala (incidental) | 1:11272878 G>C | 100/1061 \| 96/1021 \| 94/989 | 9.40% (7.68%-11.36%) | 0/416 | tumor-only, not an EVEE site (found by the window scan; Altera table lists both) |
| PTPN23 p.Pro981Ala (incidental) | 3:47452229 C>G | 32/201 \| 30/185 \| 27/169 | 16.22% (11.22%-22.33%) | 0/187 | tumor-only, not an EVEE site (found by the window scan; Altera table lists both) |

BRCA1 (last row of the main table) is `tumor_enriched_read_support`; its VAF under each policy is repeated below. All sites are depth-adequate (>=172 tumor fragments; normal >=35), so none is 'unresolved'. CUL3 has the thinnest normal depth (35 fragments).

| Gene | GRCh37 | Tumor ALT/depth: relaxed \| primary \| strict | Tumor VAF (95% CI): relaxed \| primary \| strict | Normal ALT/depth: relaxed \| primary \| strict | State |
|---|---|---|---|---|---|
| BRCA1 c.81-1G>A control | 17:41267797 C>T | 134/598 \| 126/573 \| 121/555 | 22.41% (19.13%-25.97%) \| 21.99% (18.66%-25.61%) \| 21.80% (18.43%-25.47%) | 0/292 \| 0/281 \| 0/270 | `tumor_enriched_read_support` |

## 3. Orientation / artifact assessment (FFPE and oxidation-style damage)

**The nine EVEE sites have no alternate reads to assess**: the tumor exome shows zero ALT bases at every one of them, including unfiltered. Orientation/position metrics are only defined when ALT fragments exist, so the question for these sites is moot; what matters is whether the library's damage background could hide a low-VAF allele. It could not hide anything above about 1% (see the noise table), and the true clonal VAF for a heterozygous variant would be 15-30% (section 5).

What a *real* variant looks like in this exome (controls, primary policy, fragment-level):

| Control | ALT F1R2 / F2R1 | REF F1R2 / F2R1 | p orientation (Fisher) | ALT median end-distance vs REF (MWU p) | ALT within 10 bp of read end | median BQ ALT/REF | median MQ ALT/REF | soft-clip ALT/REF | indel <=10 bp ALT/REF | trinucleotide (pyrimidine ref) | CpG |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BRCA1 c.81-1G>A | 60 / 66 | 226 / 220 | 0.61 | 38.5 vs 42.0 (0.47) | 6.3% (REF 4.5%) | 32/34 | 60/60 | 10.3%/7.0% | 0.0%/0.0% | A[C>T]T | no |
| BRCA2 p.Ser2695Leu | 88 / 103 | 520 / 580 | 0.81 | 40.0 vs 39.0 (0.82) | 4.2% (REF 6.9%) | 32/34 | 60/60 | 1.0%/5.4% | 0.0%/0.0% | T[C>T]A | no |
| PIKFYVE p.Ile1548Thr | 7 / 8 | 63 / 88 | 0.79 | 50.0 vs 45.0 (0.96) | 0.0% (REF 5.3%) | 34/32 | 60/60 | 0.0%/3.3% | 0.0%/0.0% | A[T>C]T | no |
| MTOR P1125A | 42 / 54 | 408 / 517 | 1.00 | 44.0 vs 45.0 (0.93) | 3.1% (REF 4.2%) | 34/32 | 60/60 | 2.1%/6.5% | 0.0%/0.0% | n/a | n/a |
| PTPN23 P981A | 17 / 13 | 83 / 72 | 0.84 | 28.0 vs 40.0 (0.11) | 13.3% (REF 10.3%) | 34/34 | 60/60 | 6.7%/8.4% | 0.0%/0.0% | n/a | n/a |

All five controls show balanced F1R2/F2R1 orientation matching the REF reads, ALT reads that are not concentrated at read ends, no extra soft-clipping/indels, and normal 0: none is artifact-like. Strand note: ALT-vs-REF strand differs significantly at BRCA1 (Fisher p=1e-4) and BRCA2 (p=5e-7) even though both are real (the REF strand mix is itself skewed at BRCA1: 94 forward vs 352 reverse, an exon-edge/capture geometry effect), so in this assay strand bias alone is not a reliable rejection criterion; orientation and position-in-read are the informative metrics.

Library-level damage context (tumor vs normal exome, the ten +/-50 kb windows, positions where the normal is homozygous and both samples have depth >=100, tumor alt fraction <2%, BQ>=30, MQ>=30):

| class | tumor noise rate | normal noise rate | tumor/normal | ALT reads in F1R2 | per-position tumor alt fraction q99 |
|---|---|---|---|---|---|
| C>T | 0.024% | 0.005% | 4.8x | 63% | 0.57% |
| G>A | 0.029% | 0.009% | 3.3x | 39% | 0.64% |
| C>A | 0.020% | 0.004% | 5.5x | 17% | 0.54% |
| G>T | 0.018% | 0.002% | 7.9x | 84% | 0.53% |
| T>C | 0.011% | 0.007% | 1.6x | 47% | 0.39% |
| A>G | 0.011% | 0.006% | 1.8x | 51% | 0.38% |

The tumor library carries a damage signature: C>T/G>A noise is 3-6x the normal's, and C>A/G>T noise is 5-8x with the classic oxidation orientation bias (G>T ALT reads 84% F1R2; C>A 17% F1R2; C>T 63%, G>A 39%). Typical per-base rates are 0.02-0.03% and the 99th-percentile single-position fraction is about 0.5-0.6%. Consequently a single ALT read in this tumor at a C>T/G>A/G>T site would need orientation/position support before it could be believed, and nothing below roughly 1% VAF could be called here at ~200-700 fragments; nothing like that is needed, because the nine sites show zero ALT reads.

## 4. WGS vs exome comparison (same alleles)

WGS = the earlier ~46x tumor / ~51x normal GRCh38 audit (`variant_evidence.csv`, primary policy). Exome = this audit, primary policy.

| Gene | WGS tumor ALT/depth | WGS normal ALT/depth | WGS state | Exome tumor ALT/depth (upper95) | Exome normal ALT/depth | depth gain (tumor) | P(>=1 WGS ALT fragment) if true VAF = exome upper95 (the seven single-ALT loci) | WGS ALT observations (raw, from the earlier regional-BAM read proof) |
|---|---|---|---|---|---|---|---|---|
| MTOR | 1/10 | 0/48 | insufficient_depth | 0/740 (0.40%) | 0/402 | 74x | 4.0% | 1 counted fragment(s), mates carrying ALT: 2 (BQ40/MQ60) |
| SCAP | 1/11 | 0/52 | insufficient_depth | 0/274 (1.09%) | 0/202 | 25x | 11.3% | 1 counted fragment(s), mates carrying ALT: 2 (BQ40/MQ60) |
| RXRA | 1/7 | 0/51 | insufficient_depth | 0/290 (1.03%) | 0/165 | 41x | 7.0% | 1 counted fragment(s), mates carrying ALT: 2 (BQ40/MQ60) |
| CUL3 | 2/44 | 0/25 | ambiguous_read_support | 0/172 (1.73%) | 0/35 | 4x | n/a | 2 counted fragment(s), mates carrying ALT: 2,1 (BQ40/MQ60); 1 not counted (duplicate-flagged or supplementary-only) |
| DLL4 | 1/11 | 0/43 | insufficient_depth | 0/232 (1.28%) | 0/166 | 21x | 13.2% | 1 counted fragment(s), mates carrying ALT: 2 (BQ40/MQ60) |
| ATG4B | 1/14 | 0/38 | insufficient_depth | 0/197 (1.51%) | 0/105 | 14x | 19.2% | 1 counted fragment(s), mates carrying ALT: 2 (BQ40/MQ60) |
| ATG13 | 0/22 | 0/46 | alternate_not_observed_at_this_depth | 0/272 (1.10%) | 0/119 | 12x | n/a | 0 counted fragment(s), mates carrying ALT: - (BQ40/MQ60); 1 not counted (duplicate-flagged or supplementary-only) |
| FGFR4 | 1/9 | 0/43 | insufficient_depth | 0/631 (0.47%) | 0/577 | 70x | 4.2% | 1 counted fragment(s), mates carrying ALT: 2 (BQ40/MQ60) |
| BRD3 | 1/9 | 0/42 | insufficient_depth | 0/360 (0.83%) | 0/165 | 40x | 7.2% | 1 counted fragment(s), mates carrying ALT: 2 (BQ40/MQ60) |
| BRCA1 | 4/21 | 0/40 | tumor_enriched_read_support | 126/573 (n/a) | 0/281 | 27x | n/a | 4 counted fragment(s), mates carrying ALT: 2,2,2,1 (BQ40/MQ60); 1 not counted (duplicate-flagged or supplementary-only) |

How to read this. Seven WGS loci (MTOR, SCAP, RXRA, DLL4, ATG4B, FGFR4, BRD3) had exactly one ALT fragment at 7-14 tumor fragments, with both mates concordant (a template-level observation, not an independent per-read error); CUL3 had 2 at 44; ATG13's two raw reads were one supplementary fragment. If a clone carrying one of them sat at the WGS point estimate (7-14%), the exome would show 20-100 ALT fragments; it shows none. The WGS 95% CIs (e.g. 1/10: 0.25-44.5%) and the exome one-sided upper bounds (0.4-1.7%) overlap only at true VAFs of about 0.2-1.7%, where the chance of seeing >=1 ALT fragment in 7-14 WGS fragments is only 4-19% per locus (column 'P(>=1 WGS ALT)'). Seeing it at all seven loci by chance would be a joint probability below 1e-7, but the sites came from a call list and the WGS ALT is what put them there, so selection (C>T/G>A damage-type singletons are the commonest noise class in this tumor library, section 3) readily explains them. BRCA1 is the exception: WGS 4/21 and exome 126/573 agree.

## 5. Copy-number context (qualitative only)

Exome tumor/normal depth ratio in the +/-50 kb window (capture targets only, positions with >=100x in both; normalized by mapped reads 330.9M vs 137.1M; **not** purity/ploidy corrected, capture and duplicate-removal differences not modelled) and tumor allele balance at normal-heterozygous SNPs (unphased: tumor minor-allele fraction; 0.5 = balanced). WGS log2 values are the 5 Mb-bin numbers from the next-steps review.

| Gene | WGS log2 (5 Mb bins) | exome log2, +/-50 kb | exome log2, +/-2 kb | het SNPs informative | tumor minor-allele fraction (median) | SNPs <0.40 |
|---|---|---|---|---|---|---|
| MTOR | -0.91 | -0.16 | -0.21 | 1 | 0.460 | 0% |
| SCAP | -0.78 | -0.59 | -0.58 | 6 | 0.331 | 100% |
| RXRA | -1.34 | -0.40 | -0.32 | 4 | 0.353 | 100% |
| CUL3 | +0.16 | +0.29 | +0.19 | 2 | 0.378 | 50% |
| DLL4 | -0.80 | -0.61 | -0.62 | 2 | 0.421 | 50% |
| ATG4B | -0.82 | -0.03 | -0.05 | 8 | 0.360 | 88% |
| ATG13 | -0.20 | -0.13 | +0.07 | 1 | 0.443 | 0% |
| FGFR4 | -1.12 | -0.88 | -0.91 | 21 | 0.348 | 90% |
| BRD3 | -1.34 | -0.30 | -0.15 | 9 | 0.337 | 89% |
| BRCA1 | -0.94 | -0.41 | -0.10 | 1 | 0.402 | 0% |

Reading: allelic imbalance in the tumor (minor-allele fraction 0.33-0.36 at 4-21 SNPs) near SCAP, RXRA, FGFR4, BRD3 and ATG4B is what LOH would give at purity about 0.45-0.5 (minor fraction = (1-p)/(2-p); p = (1-2m)/(1-m)), and SCAP, DLL4, FGFR4 and RXRA also show lower relative depth; ATG4B shows imbalance without a depth drop (copy-neutral LOH or too few SNPs). MTOR, ATG13, CUL3, DLL4 and BRCA1 have only 1-2 informative SNPs, so allele balance there is uninformative; the exome MTOR ratio (-0.16) is much shallower than the WGS bin (-0.91) and the two have not been reconciled. The exome ratios are systematically shallower than the WGS bins, consistent with different normalization.

Expected tumor VAF of a *clonal heterozygous* variant, for purity p (the case's estimate is 0.31-0.45; the SNP balance above suggests ~0.45): copy-neutral p/2 = 0.155 (p=0.31) to 0.23 (p=0.46); on the single retained allele of a 1-copy loss p/(2-p) = 0.18 to 0.30; on the lost allele 0. The BRCA1 22% fits p about 0.36 on a single retained copy. Against that, the nine alleles are at 0/172-740 (upper bound 0.4-1.7%): the exome excludes (95%) any clone carrying one of them in more than about 3-11% of tumor cells (2 x upper bound / 0.31, heterozygous copy-neutral; smaller at higher purity). Copy loss therefore cannot explain the absence, because a retained clonal allele would have a *higher* VAF; only loss of the variant-bearing allele could, and that would make the variant absent rather than low.

## 6. RNA-level allelic support (tumor RNA, both BAMs)

Both BAMs are the same reads processed twice (STAR raw `sorted`: MAPQ 255 = unique, no duplicate flags; GATK SplitNCigar/`recal`: MAPQ 60, duplicates flagged ~30%, base qualities BQSR-compressed to <=Q33 so Q30 policies are unusable there). Uniquely mapped only (NH=1, MAPQ>=30); policy shown is relaxed (BQ>=20), the one comparable across both BAMs; spliced reads over the site cannot be genotyped. Agreement of the two BAMs is **not** independent replication. RNA is allelic-expression evidence only, never DNA evidence; stop-gained alleles (SCAP, RXRA, ATG4B) may be depleted by NMD, so zero ALT RNA there would not disprove a DNA allele (but DNA already shows none).

| Gene | bulk RNA TPM (earlier review table) | raw STAR ALT/depth (VAF) | recal ALT/depth | agree | same-class RNA noise: this site vs q99 | note |
|---|---|---|---|---|---|---|
| MTOR | 114.4 | 1/2101 (0.05%) | 1/1300 (0.08%) | yes | 0.05% vs q99 0.87% | 1 ALT read of 2,101; below noise |
| SCAP | 33.6 | 0/982 (0.00%) | 0/745 (0.00%) | yes | 0.00% vs q99 0.87% | none; stop-gain may be NMD-depleted but DNA already absent |
| RXRA | 31.8 | 0/1700 (0.00%) | 0/1203 (0.00%) | yes | 0.00% vs q99 0.55% | none; stop-gain |
| CUL3 | 64.2 | 2/722 (0.28%) | 2/507 (0.39%) | yes | 0.28% vs q99 1.00% | 2 reads; noise-level |
| DLL4 | 2.58 | 0/40 (0.00%) | 0/30 (0.00%) | yes | 0.00% vs q99 0.87% | RNA depth 40: gene barely expressed in bulk tumor (TPM 2.6); uninformative |
| ATG4B | 92.8 | 4/710 (0.56%) | 3/545 (0.55%) | yes | 0.56% vs q99 1.00% | 4 reads (0.56%), 95th percentile of G>A noise; stop-gain; not support |
| ATG13 | 46.8 | 0/777 (0.00%) | 0/616 (0.00%) | yes | 0.00% vs q99 0.42% | none; thin local depth |
| FGFR4 | 12.0 | 0/322 (0.00%) | 0/227 (0.00%) | yes | 0.00% vs q99 0.87% | none |
| BRD3 | 31.5 | 0/515 (0.00%) | 0/399 (0.00%) | yes | 0.00% vs q99 0.46% | none |
| BRCA1 | 62.0 | 48/60 (80.00%) | 36/40 (90.00%) | yes | n/a | intronic last base: only unspliced/retained reads cover it (743 reads splice across it and cannot be genotyped); ALT dominates the 60 covering reads - splice-disruption observation, not DNA genotyping (see step 1.2) |
| PPARD | 18.7 | 3/2167 (0.14%) | 3/1496 (0.20%) | yes | n/a | 3 reads (0.14%) |
| PIKFYVE | 23.5 | 61/291 (20.96%) | 43/215 (20.00%) | yes | n/a | ALT 21% in RNA vs 9% DNA (DNA CI 5-14%) |
| BRCA2 | 61.7 | 344/900 (38.22%) | 239/586 (40.78%) | yes | n/a | ALT 38% in RNA vs 15% DNA: allele-skewed expression/LOH possible |

At the nine EVEE sites RNA shows 0-4 ALT reads and none exceeds the same-class single-position noise (q99 0.4-1.0%). RNA depth at the site (raw STAR, unique, BQ>=20) is deep for MTOR (2,101) and RXRA (1,700), moderate for SCAP (982), ATG13 (777), CUL3 (722), ATG4B (710) and BRD3 (515), thin for FGFR4 (322) and DLL4 (40, uninformative). The two BAMs agree everywhere, but they are one data set.

## 7. Optional scan: RB1CC1 and PPARD

- **RB1CC1** (report: splice donor chr8:52624715, GRCh38; alleles absent). GRCh37 8:53537275, REF A, = +2 of the donor of the canonical transcript's exon (gene on minus strand; sense T). Tumor exome: unfiltered pileup 435 A and 0 non-A; normal 124 A, 0 non-A. Within +/-10 bp no non-reference allele reaches tumor >=3 / normal 0 (the best position has 1 alt fragment). No splice-donor variant is present at the reported coordinate in the exome. In RNA, 18/43 reads covering this intronic base show G while DNA is homozygous A: RNA editing or an exon-edge alignment artifact, not a DNA variant.
- **PPARD p.Gln415His** (no allele in the report). The only SNV that gives Gln->His at codon 415 of the canonical transcript (CAG, ENST00000360694) is GRCh38 chr6:35425998 G>C = GRCh37 6:35393775 G>C. Tumor 0/623 (upper95 0.48%), normal 0/263; unfiltered tumor pileup 945 G / 0 C. No flagged neighbor within +/-10 bp (best 2 fragments). The codon change cannot occur via another single-base change, so this candidate is exhaustive for a SNV; a different alteration (e.g. an MNV/indel) would not be detected by this scan.

## 8. What this means for the nine hypotheses (within what the data show)

| Hypothesis (EVEE report axis) | Allele premise | Exome result | Status |
|---|---|---|---|
| Autophagy / proteasome (ATG4B W142*, ATG13 D213G, RB1CC1 donor) | three hits | ATG4B 0/197 (<= 1.51%), ATG13 0/272 (<= 1.10%); RB1CC1 reported donor base is reference, no flagged allele nearby | genetic premise not supported in this exome |
| mTOR (MTOR G98S) | one activating-candidate allele | G98S 0/740 (<= 0.40%). A different MTOR missense, **P1125A, is present at 9.4% (7.7-11.4%)**, normal 0/416, and is in the Altera table (12%); function not assessed here. PIKFYVE I1548T (named in the report's mTOR/PI3K bullet list) is also present, 9.0% | G98S absent; the real MTOR event is a different allele that the report does not discuss |
| Lipid / retinoid (SCAP W633*, RXRA S96*, PPARD Q415H) | loss alleles | SCAP 0/274 (<= 1.09%), RXRA 0/290 (<= 1.03%), PPARD candidate 0/623 (<= 0.48%) | premise not supported |
| CUL3 / NRF2 / ferroptosis (R354C) | loss allele | 0/172 (<= 1.73%); the earlier WGS 2/44 is not reproduced | premise not supported (normal depth only 35) |
| DLL4 / Notch-Wnt (R516C) | ligand allele | 0/232 (<= 1.28%); DLL4 barely expressed in bulk tumor RNA (40 fragments at the site) | premise not supported |
| FGFR4 (S106F) | extracellular Ig-domain-1 allele | 0/631 (<= 0.47%) | premise not supported |
| BRD3 / BET (S676G) | tail allele | 0/360 (<= 0.83%) | premise not supported |
| BRCA1 control | splice acceptor | 22.0% (18.7-25.6%), normal 0/281, balanced orientation | supported (clonal-range VAF); biallelic/HRD status still needs allele-specific CN |

What the data show: 0 of 9 highlighted SNVs is detectable in the deep tumor exome from the specimen that carries the BRCA1 variant and four other independently reported variants at their expected frequencies. Each hypothesis that rests solely on one of these alleles has no genetic premise in this specimen. What the data do *not* show: that the pathways are intact (no allele test addresses activity), that a sub-1% subclone is absent, that the WGS specimen is the same physical sample as the exome, or why the EVEE call list contained these sites. Plausible but untested explanations are low-support WGS calls (damage-type singletons selected into a lenient call set) or a different specimen/aliquot for the WGS; the exome is concordant with Altera at 5 of 5 shared variants, and the WGS also carries the BRCA1 and BRCA2 calls, which argues against a specimen mix-up and favors the former. Suggested handling: retire the nine as variant-driven hypotheses unless an orthogonal assay or the original call set with caller metrics restores them; keep BRCA1; consider MTOR P1125A and PIKFYVE I1548T as the exome-supported variants nearest the report's mTOR/PI3K narrative, as unevaluated candidates, not as findings.

## 9. Limits

- Specimen identity across exome, WGS and Altera is inferred from five concordant variants, not proven; the exome tumor/normal pair (E019_S01 / S05) was not independently genotype-matched here.
- Exome capture/duplicate removal: the BAMs carry no duplicate flags and are essentially coordinate-unique (dup_factor <=1.0014), so depth is post-removal; no UMIs exist to confirm molecule independence.
- Only SNVs (and the +/-10 bp window) were tested; indels/MNVs/structural events and RB1CC1's unknown ALT beyond any single-base change were not.
- No somatic caller was run; counts are diagnostic triage, never a PASS. Library noise implies nothing below ~1% VAF is callable in this tumor.
- Copy-number context is crude (library-size-normalized depth ratio; unphased het SNPs, few per locus); purity is uncertain (31-45% stated; ~0.46 suggested by SNP balance).
- RNA agreement between the two BAMs is not replication; stop-gained alleles may be NMD-depleted; the recal RNA BAM has compressed base qualities.
- Regional BAMs contain germline genotypes (re-identifiable) and read names; keep them private.

