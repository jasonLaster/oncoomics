# Step 2a: KH022 scRNA genotype identity, pooled-donor and cross-library test (private)

Research prioritization only; no clinical claims. Analysis date 2026-10-03. Keep this file in the git-ignored `private/` tree.

## Verdicts

| Question | Verdict | Key evidence |
| --- | --- | --- |
| (a) KH022-1 genotype vs matched-normal WGS | **Match** | 2,800/2,822 normal hom-alt sites called hom-alt in scRNA, 0 called hom-ref; 0 of 321,004 callable random hom-ref sites called non-ref; conservative het-only log10 LR = +863 (4,525 het sites); permutation z = 83 (0/2,000 permutations reached the observed value) |
| (a) KH022-1-1 genotype vs matched-normal WGS | **Match** | 2,678/2,702 hom-alt sites concordant, 0 called hom-ref; het-only log10 LR = +823 (4,376 het sites); permutation z = 79 (0/2,000) |
| (b) One donor or pooled? | **Single donor; no second genome detected.** A second unrelated genome contributing about 5% or more of molecules is excluded under the stated model; 2% cannot be excluded | UMI-level discordance at sites not selected on RNA: hom-alt 16/2,822 (L1), 15/2,702 (L2) vs 82-87 expected at f=5% (Poisson P < 1e-19); random hom-ref 10/321k and 2/309k vs 25-26 expected at f=5% (P = 3e-4 and 6e-9). Vireo ELBO is highest for K=1 in L1, L2 and L1+L2 pooled |
| (c) KH022-1 vs KH022-1-1 from the same individual? | **Consistent with the same individual** | 5,698/5,853 (97.4%) jointly called het/hom-alt sites identical, 0 RR-vs-AA flips; L2 data given L1 calls log10 LR = +2,041 (6,099 sites); het allele fractions r = 0.96 (2,801 sites); per-arm allele imbalance r = 0.99 |

A tumor-origin cross-check from the specimen-ledger agent, not re-derived here: the somatic BRCA1 c.81-1G>A allele (absent from normal) appears in reads from both libraries (KH022-1: 91 reads/62 cells; KH022-1-1: 31 reads/25 cells). Separately, scRNA allele imbalance by chromosome arm tracks the tumor WGS (below). Both point to these nuclei coming from this patient's tumor, not just from this patient.

The test cannot tell a monozygotic twin apart from the patient. A first-degree relative is effectively ruled out: they would carry the reference allele at roughly 40-60% of the patient's hom-alt sites, and the observed rate is 0/2,822 hom-ref calls (0.6% of sites with any minor signal).

## Data and design

- Inputs: scRNA BAMs (Cell Ranger 10.1.0, GRCh38-2024-A, `chr` contigs). Matched-normal WGS BAM (UCSC hg38 analysis set, median depth 50 in the tiles). Tumor WGS BAM (batch-0 tiles only). Reference FASTA slices for the tiles.
- Region sampling: 1,500 random 16-kb autosomal tiles whose scRNA density, estimated from BAI leaf-bin chunk spans, was 0.5-2 MB compressed per tile. 13,092 tiles were eligible; MHC, IG and TCR loci were excluded. The proxy agreed across libraries (Spearman 0.997). The tiles were drawn in two random batches of 750. Only these tiles were streamed (`samtools view -M -L`, presigned URL plus local .bai) into local subset BAMs, so no whole BAM was downloaded.
- scRNA reads: STAR-unique MAPQ 255, called-cell barcodes only (38,994 / 37,805), UB present, nM <= 4, base quality >= 20, >= 3 bp from read ends. UMI dedup uses (CB, UB, position) with a >= 60% majority base.
- Positions in reference soft-masked (repeat) sequence were excluded. Normal calls (depth 20-150): HOMREF (<= 1 non-ref read), HET (alt fraction 0.25-0.75, >= 5 reads each allele), HOMALT (>= 0.92). Everything else was dropped.
- Site classes: HET and HOMALT were selected on normal data only. HOMREF_C is a random 4% of hom-ref positions with scRNA depth >= 20, an unbiased baseline. HOMREF_B are hom-ref positions picked because RNA showed a non-ref base; they are enriched for artefacts and editing and are excluded from the LR.
- Assembled table: 384,720 candidate sites (7,008 HET, 4,247 HOMALT, 368,339 HOMREF). There are 33.2M (L1) and 31.8M (L2) per-cell molecule observations.

## (a) Identity numbers (UMI depth >= 10; depth >= 20 in identity_stats.json)

| | KH022-1 | KH022-1-1 |
| --- | --- | --- |
| HOMALT sites / UMIs | 2,822 / 259,385 | 2,702 / 248,805 |
| discordant UMI rate at HOMALT | 0.175% | 0.183% |
| HOMALT called AA / RA / RR / no call | 2,800 / 11 / 0 / 11 | 2,678 / 9 / 0 / 15 |
| HOMREF_C sites / discordant UMI rate | 321,158 / 0.041% | 309,223 / 0.037% |
| HOMREF_C sites with >=3 discordant UMIs and >=5% | 10 | 2 |
| HET sites (median UMI depth 32) | 4,525 | 4,376 |
| HET with both alleles (each >=2 UMIs, minor >=5%) | 3,665 (81.0%) | 3,531 (80.7%) |
| same, at depth >=50 | 86.9% | 88.1% |
| HET one allele only (minor <=1 UMI) | 741 | 740 |
| log10 LR, HET only (conservative, p=0.5) | +863 | +823 |
| log10 LR, HET+HOMALT (p=0.5) | +2,388 | +2,275 |
| permutation (HET/HOMALT labels shuffled), z | 82.7 | 79.1 |

Models:
- Beta-binomial noise fitted on the data, with hom-error eps of about 4e-4 and het mu 0.49, kappa 1.9.
- Each hypothesis is mixed with a 1% flat outlier component, so no single site gives unbounded evidence.
- The unrelated-person alternative draws the genotype from HWE at allele frequency 0.5 (0.25/0.5/0.25). At het sites this is the least favourable unrelated person, so the het-only LR is a lower bound for unrelated individuals.
- The HOMALT-inclusive LR is not conservative, because for common alleles P(hom-alt) can exceed 0.25.
- The null "fraction both alleles" for an unrelated person is at most 0.5; the observed 0.81 gives binomial p < 1e-300.

**The 19% of normal-het sites that look monoallelic are explained by tumor allele imbalance, not by a different genome.** They are 20% of sites in the high-imbalance arms (17q, 9, 13, 14, 15) vs 5.7% in chr2/4/12/20, and they match between libraries. The heavy dispersion (kappa about 1.9) reflects this LOH/CNV plus allele-specific expression in nuclei.

## (b) Pooled-donor tests

1. **UMI-level pseudobulk (07b_pooled_umi.py, primary).** This test counts discordant sites among sites not selected on RNA, then compares them with the expected count if an unrelated genome contributed a fraction f of molecules. Expected counts are signal only (background errors are ignored), which is conservative.
   - Assumptions: donor-2 non-ref density 0.0007/site, from this individual's het+hom-alt density x 0.75; hom-alt-site donor-2 alt allele frequency 0.75.

   | f | expected HOMALT disc (L1/L2) | expected HOMREF_C disc (L1/L2) |
   | --- | --- | --- |
   | 2% | 7.2 / 6.8 | 2.1 / 2.0 |
   | 5% | 87 / 82 | 26 / 25 |
   | 10% | 369 / 348 | 86 / 81 |
   | 50% | 1,124 / 1,072 | 212 / 203 |

   Observed: HOMALT 16 / 15, HOMREF_C 10 / 2. f >= 5% is rejected (P <= 3e-4 in every test). f = 2% is not.
   - The read-level version (07_pooled_pseudobulk.py) is too noisy to use for exclusion. It has PCR duplicates and a 3% threshold: 6,245 non-editing discordant sites in 6.56M hom positions at depth >= 40, which exceeds even the pooled expectation. It is kept only as a descriptive file.
2. **Per-cell discordance at normal HOMALT sites (08_percell.py).** LOH cannot create these discordances.
   - Cells with >= 8 observations and >= 1 discordant: 2.2% (L1) / 2.5% (L2), consistent with the 0.18% per-observation error rate.
   - Cells with >= 2 discordant: 47 / 56, vs 12.6 / 15.0 under a within-site permutation (z = 11 / 12). 43/47 and 50/56 of these involve two discordant sites within 1 kb, which points to one mis-mapped molecule or locus rather than a donor.
   - Even counted as donor-2 cells, they are <= 0.2% of cells.
3. **Vireo 0.5.9, K = 1/2/3** (15,000 cells, about 17 obs per cell, 5,900-9,600 RNA-polymorphic sites).

   | | ELBO K=1 | K=2 | K=3 |
   | --- | --- | --- | --- |
   | L1 | -162,149 | -162,831 | -164,340 |
   | L2 | -159,519 | -159,536 | -160,965 |
   | L1+L2 | -165,668 | -166,970 | -169,045 |

   K=1 is best in all three. K=2 gives about a 50/50 split with only 51-58% of cells at posterior >= 0.9, i.e. no real structure. In the joint run, K=2 clusters do not separate the libraries (3,971/3,697 vs 3,835/3,497).
   - Spike-in at the real L1 observation structure (8,000 cells; 08b): ΔELBO(K2-K1) is -3,625 at f=0, -1,468 at 5%, +1,064 at 10% and +8,795 at 25%.
   - So vireo alone detects a second donor at about 10% or more. The real-data ΔELBO (-682 for L1 on 15,000 cells) is not directly comparable in scale, so test 1 is the sharper bound.
4. **LOH vs donor mixing (09_loh.py).** Allele imbalance at normal-het sites is arm-specific and reproducible:
   - Highest: 17q mean |AF-0.5| 0.43; then chr9, 17p, 13, 15, 14.
   - Lowest: chr20 0.10, chr4 0.11.
   - Per-arm L1 vs L2 r = 0.99; per-arm scRNA vs tumor-WGS imbalance r = 0.81 (L1) / 0.82 (L2), 23 arms. Tumor DNA is highest at chr17p/q (0.23).

   This is the pattern expected from tumor LOH/CNV in a single genome. Donor mixing would raise imbalance at random sites genome-wide and create hom-site discordance, which is not seen.

## (c) Cross-library

- At sites with confident calls in both libraries (thresholds: RA if minor >= 3 UMIs and >= 10%; RR/AA if the other allele <= max(1, 2%)):
  - HET: 3,185/3,336 identical, 0 RR-vs-AA; disagreements are RA vs hom at threshold edges.
  - HOMALT: 2,513/2,517 identical.
  - HOMREF_C: 292,834/292,834 identical.
- L2 UMIs scored against L1 genotype calls: log10 LR = +2,041 (6,099 sites); het-only +846.
- Not assessed: whether the libraries are technical replicates. Their near-identical allele imbalance (r = 0.96 site level, 0.99 arm level) says they come from the same tumor cell population.

## KH022-1-1 index check (response to the ledger agent's report)

All KH022-1-1 region queries here used the delivered `sample_alignments.bam.bai`, MD5 c057e1b9d8e2a988c82b18098b3103ee, which matches the vendor md5sum.txt. In this analysis the index worked:
- **It did not return empty or misplaced regions.** All 736 batch-0 regions returned reads, 0 of 308,194 chr5 reads fell outside the requested tiles, and per-region read counts correlated with KH022-1 at r = 0.994 (log).
- **An indexed query matched an index-free read.** For chr1:16,385-32,768, the indexed query and a sequential read of the first 60 MB of the BAM gave the same 267 reads, with an identical name/position set.

One plausible cause of the other agent's failure: a URL presigned with the CLI default region (us-west-1 endpoint) fails to read the header. Presign with `--region us-east-1`. KH022-1-1 results are therefore reported in full, with the caveat that only this bounded check was possible.

## Limitations

- Sampled tiles only: 1,500 of 13,092 eligible expressed tiles, about 2-4% of reads per library. Autosomes only, so there is no X-heterozygosity check.
- Sex is consistent but this is descriptive: normal WGS X/autosome coverage is 0.99 (female), and scRNA chrY is 0.016% of reads in both libraries.
- Tumor WGS was used only for batch-0 tiles.
- The pooled-donor bound depends on stated assumptions (donor-2 variant density, allele frequency 0.75 at hom-alt sites, unrelated donor). A related second donor would be harder to detect. Mixing below about 2-5% (e.g. small contamination) is not excluded.
- Vireo runs used 15,000-cell subsamples with about 17 informative observations per cell. Per-cell donor assignment is weak; the ELBO comparison and the spike-in carry the inference.
- A twin cannot be excluded. Specimen, date, and nuclei-vs-cells questions are not addressed by genotype.
