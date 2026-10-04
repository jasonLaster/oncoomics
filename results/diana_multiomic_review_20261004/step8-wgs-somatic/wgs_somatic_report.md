# Step 8: tumor/normal WGS somatic calls, subject01

This is for research prioritization only. It is not a clinical result. The data are one FFPE tumor WGS (~40x) and a matched normal (~50x), on GRCh38. Run ID `wgs-somatic-20261003T221959Z`, finished 2026-10-04. A previous supervising agent died partway through. This report is from the agent that resumed the run: it took over the orphaned jobs and did all post-processing locally.

## Bottom line

| item | result |
|---|---|
| Consensus PASS (Mutect2 PASS AND Strelka2 PASS, exact allele) | **16,967** (16,190 SNV + 777 indel) |
| TMB, genome-wide | **6.1 / Mb** (SNV 5.8 + indel 0.3) over 2,776 Mb callable territory |
| Positive controls | 5 of 6 consensus PASS. **MTOR P1125A failed**: Strelka PASS, but Mutect2 filtered it as `strand_bias` (4 alt / 54 reads) |
| Negative controls (9 EVEE + 1 derived) | **none is consensus PASS**. CUL3 R354C is Strelka-PASS only (3/63 reads); Mutect2 filtered it as `orientation` |
| Serova's 22 missense sites (an external claim, not a target) | **16 of 22 consensus PASS**, 18 Strelka PASS, 16 Mutect2 PASS. 4 sites have no WGS evidence: Serova's own tumour-genome counts there are 0/7, 0/8, 0/15 and 1/17, so these are exome-only calls |
| SBS3 | **model-dependent.** Fixed-set NNLS gives **0.41 (bootstrap 95% CI 0.38-0.44)**. SigProfilerAssignment's de novo selection gives **0 (bootstrap CI 0-0.59; selected in 7.5% of 200 replicates)**, using SBS39/SBS8 instead |
| Other HRD-type evidence | 60% of non-repeat deletions >= 5 bp carry >= 2 bp microhomology (ID6-like). 163 tandem duplications, 136 of them 1-100 kb. 222 translocations |
| Contamination | 0.11% (CalculateContamination) |
| Cloud cost | **$10.33** (ledger, conservative), against a $40 cap |

## 1. What ran

| caller | version / setup | where |
|---|---|---|
| Mutect2 | GATK 4.6.2.0, 192 equal-territory shards over Broad wgs_calling_regions (chr1-22, X) | 3 workers, c7i.16xlarge on-demand |
| Mutect2 filtering | gnomAD AF-only germline resource, 1000G PoN, forced control alleles, F1R2 -> LearnReadOrientationModel, CalculateContamination with matched normal, FilterMutectCalls, `bcftools norm -m- -c x` | gather, c7g.8xlarge spot |
| Strelka2 | 2.9.7 (bioconda), using Manta indel candidates | c7i.16xlarge |
| Manta | 1.6.0 | m7g.8xlarge spot |

- The BAMs are the frozen, version-pinned July inputs: tumor VersionId `APPI0V_...`, normal VersionId `xXSOcf...`. Reference SHA-256 was verified on every worker.
- Every shard and job output carries a SHA-256 manifest. Local copies were re-verified against those manifests.
- No second SV caller was run.
- The resumed run did three things:
  - It waited out the three slow pericentromeric shards (08, 110, 174).
  - It submitted a 16-way split hedge for shard 08 on capacity that was already paid for. It terminated the hedge when the original shard finished, about 1 minute later; the hedge produced no outputs.
  - It confirmed that the gather job depended on all three workers.

## 2. Counts per caller

See `consensus_pass_summary.tsv`.

| set | SNV | indel | Ti/Tv | per Mb | median VAF |
|---|---|---|---|---|---|
| Mutect2 PASS | 66,201 | 6,092 | 0.82 | 26.0 | 0.082 |
| Strelka2 PASS | 49,317 | 4,481 | 1.60 | 19.4 | 0.079 |
| **consensus** | **16,190** | **777** | **0.89** | **6.1** | **0.139** |
| Mutect2-only | 50,011 | 5,315 | 0.79 | 19.9 | |
| Strelka2-only | 33,127 | 3,704 | 2.18 | 13.3 | |

- Each single-caller PASS set is dominated by calls below VAF 0.08 that the other caller does not make:
  - The Strelka-only set is 69% C>T/T>C. That pattern looks like FFPE or sequencing artifact.
  - The Mutect2-only set has a flat spectrum with median VAF 0.07.
- The consensus is the primary set. Its VAF distribution is in `results/final/vaf_hist.tsv`:

| quantile | q10 | q25 | q50 | q75 | q90 |
|---|---|---|---|---|---|
| consensus VAF | 0.07 | 0.09 | 0.14 | 0.21 | 0.29 |

- Only 2.7% of consensus calls have VAF > 0.40.
- **Consensus indels are under-counted.**
  - The consensus requires an identical normalized allele in both callers.
  - Repeat and homopolymer indels are represented differently by the two callers and are filtered differently, so few of them survive. Only 24 of 505 consensus deletions >= 2 bp are repeat-mediated.

**Orientation artifacts (FFPE).**
- FilterMutectCalls removed 173,069 of 795,116 records (21.8%) as `orientation`.
- Among the 16,794 Mutect2-PASS C>T/G>A SNVs, 2 (0.01%) still show F1R2/F2R1 bias (binomial p < 0.01, >= 5 alt reads).
- Among the 4,306 consensus C>T/G>A SNVs, 1 does.
- Residual orientation artifacts in the PASS sets are therefore negligible.

**Low-complexity contexts.** 1,474 consensus SNVs (9.1%) sit in low-complexity context and are excluded from the primary signature matrix.

## 3. TMB

- **Definition:** consensus PASS SNV + indel, genome-wide, divided by the callable territory.
  - Callable territory means calling-region positions with tumor >= 10 and normal >= 8 reads, at MAPQ >= 20 and BQ >= 20.
  - That is 2,776.2 Mb (`callable_total.json`).
- **Result: 6.1 / Mb.**
- It is not a coding-only TMB, and no gene annotation was applied.
- **Comparison with Serova's 3 / Mb:**
  - Serova's figure probably uses an exome/coding definition and a different VAF floor, so it is not directly comparable.
  - In this tumor, about 27% of consensus SNVs have a multiplicity estimate < 0.5 (low-VAF, subclonal-like; §7). Counting only the clonal-like calls (m >= 0.6) gives about 3.7 / Mb.
- The July early look estimated 16,000 mutations (5 / Mb). It agrees with the consensus count of 16,967.

## 4. Controls

See `results/final/controls.tsv`. Tumor read counts are ref,alt.

| control | expected | Mutect2 | Strelka2 | consensus |
|---|---|---|---|---|
| BRCA1 c.81-1G>A chr17:43115780 C>T | ~22% | PASS 26,7 (0.21) | PASS | **PASS** |
| BRCA2 S2695L chr13:32363286 C>T | ~15% | PASS 47,7 (0.15) | PASS | **PASS** |
| TP53 c.559+2T>G chr17:7675051 A>C | ~35% | PASS 13,14 (0.52) | PASS | **PASS** |
| MTOR P1125A chr1:11212821 G>C | ~9.5% | **strand_bias** 50,4 | PASS | **not PASS** |
| PIKFYVE I1548T | listed | PASS 53,10 | PASS | PASS |
| PTPN23 P981A | listed | PASS 8,4 | PASS | PASS |
| 9 EVEE SNVs + PPARD (derived) | not PASS | weak_evidence / orientation / haplotype | 8 LowEVS, 1 no record, **CUL3 PASS (60,3)** | **0 / 10 PASS** |

- **TP53 VAF 0.52** is above the ~0.35 expected, but consistent with step5's finding: 17p LOH with the variant on every retained copy.
- **MTOR P1125A** is a true positive, at 9.5% in the deep exome. At about 40x WGS it has 4 alt reads. Mutect2's strand filter rejects it, so the consensus is not sensitive at this VAF and depth.
- **EVEE negatives:** each has only 2-3 alt reads in WGS. None passes the consensus. CUL3 passes in Strelka alone, so it is not "not PASS in every caller".

## 5. External comparator: Serova's 22 missense calls

See `results/final/serova_concordance.tsv`; site extraction is in `results/serova_missense_sites.tsv`.

- Serova called these sites with DeepSomatic + Mutect2 + Strelka2, mostly on the deep tumor exome. Their own read-evidence PDF gives exome and tumour-genome counts.
- **16 of 22 sites are consensus PASS here.** The WGS VAFs track Serova's exome VAFs.
- The 6 that are not:
  - **MTOR P1125A** (Mutect2 strand_bias) and **PHKB A5V** (Mutect2 orientation, 4/31 reads) are Strelka PASS. They are real low-alt-count sites that the consensus misses.
  - **MAST1 A617D, RABL6 A431D, SDC3 V59M, NUMA1 G2060R** have no candidate record in either caller. Serova's own tumour-genome tracks show 0/7, 0/8, 0/15 and 1/17 alt reads there.
  - These four are therefore exome-only evidence. WGS depth at these GC-rich exons is too low to test them; the WGS does not contradict them.
- No Serova site was contradicted by evidence present in the WGS.
- The sibling agent's `serova_windows.csv` did not exist when this ran. The table was extracted directly from `Serova_DLaster_T0_read_evidence.pdf`.

## 6. Signatures (SBS96)

See `signatures.csv` and `results/final/signatures/`.

- **Input:** consensus SNVs, primary matrix = low-complexity excluded (n = 14,716). Plot: `results/final/signatures/sbs96.png`.
- **Spectrum:** flat. C>T 27%, T>C 20%, C>A 18%, C>G 15%, T>A 11%, T>G 9%. CpG C>T (SBS1) is small, about 5%. Cosine of the observed spectrum with single signatures:

| signature | SBS3 | SBS5 | SBS40a | SBS39 |
|---|---|---|---|---|
| cosine with observed | **0.884** (highest) | 0.879 | 0.852 | 0.692 |

- **SigProfilerAssignment 1.1.4** (COSMIC v3.5, GRCh38, 200 multinomial bootstraps, with signature selection re-run in each bootstrap):

| signature | exposure |
|---|---|
| SBS5 | 0.42 |
| SBS39 | 0.23 |
| SBS8 | 0.20 |
| SBS44 | 0.07 |
| SBS1 | 0.05 |
| SBS19 | 0.03 |
| **SBS3** | **0** (CI 0-0.59; selected in 7.5% of replicates) |

  The cosine of this fit is 0.966.
- **Fixed breast set NNLS** (SBS1, 2, 3, 5, 8, 13, 18, 40a) gives **SBS3 0.41 (95% CI 0.38-0.44)**, with a higher cosine of 0.977.
  - Adding SBS39 leaves SBS3 at 0.38 (0.34-0.43).
  - Dropping SBS3 lowers the cosine to 0.963.
  - Details: `results/final/signatures/sbs3_sensitivity.txt`.
- **Interpretation:** SBS3, SBS5, SBS39 and SBS40a are flat and collinear (cosine 0.76-0.79 with each other). From SNVs alone, SBS3 cannot be told apart from other flat signatures.
- **Known-answer tests.** SPA recovered a synthetic 50% SBS3 mixture as 0.52 and assigned 0 SBS3 to a synthetic mixture with none (`results/signature_known_answer/`). That shows the tool works on idealized data. It does not settle collinearity on real data.
- **Conclusion:** the SNV spectrum is compatible with a substantial SBS3 component but does not prove it. Read it together with the indel/SV evidence and step5's HRD scar score (>= 42 in every fit).

**Indels.** Among consensus deletions >= 5 bp that are not repeat-mediated, 267 of 446 (60%) have >= 2 bp microhomology (ID6-like). See `results/final/indel_mh_summary.json`. This is a known HRD feature. It is subject to the consensus bias against repeat indels described in §2.

## 7. Clonality vs step5 copy number

See `results/final/clonality_vs_step5.json`. It uses step5 fit S1b (p 0.35, ploidy 2.8, WGD), read-only.

- For consensus SNVs, median VAF is 0.64-0.91x the expected clonal single-copy VAF in every major state.
- 64% of SNVs have multiplicity estimate m >= 0.6; 27% have m < 0.5; 14% have m >= 1.6, which looks like a pre-WGD event.
- Overall this fits mostly clonal SNVs at purity about 0.35, plus a substantial low-VAF (subclonal or late) tail.
- The 1:1-segment VAF mode (0.07) reflects that low-VAF population, not a clonal peak, so it is not used for purity.
- Serova's ASCAT figures are purity 0.37 and ploidy 2.4. The purity is consistent with step5 (0.35); the ploidy is lower than step5's 2.8.
- **Re-running step5 `scripts/18_integrate.py` with the consensus set was not done.** It would write into step5's directory, which is outside this run's allowed outputs. To do it:
  1. `16_evaluate_fits.py` takes the SNV table as its 2nd CLI argument (`SR_RAW`; read at line 91, header-less, 15 columns in Strelka AU/CU/GU/TU layout). Pass it a table built from `consensus_pass.vcf.gz` with Mutect2 tumor and normal AD mapped into that layout (put the alt count in the alt base's column and the ref count in the ref base's column).
  2. Drop or relax the `evs >= 16` filter, since the consensus already removes those artifacts.
  3. Re-run `16` and then `18` from step5-ascn, ideally on a copy of the directory. `18` reads `eval/strelka_pass_filtered.tsv.gz`, which `16` writes.

## 8. Somatic SVs (Manta 1.6.0, PASS)

See `sv_summary.tsv` and `results/final/sv_pass.tsv`. There are 511 events: 781 PASS records, with BND pairs collapsed by event ID.

| class | events | notable |
|---|---|---|
| tandem duplication | 163 | 74 are 1-10 kb and 62 are 10-100 kb (RS3/RS1-like, the BRCA1-type pattern) |
| translocation | 222 | 187 have >= 2 bp microhomology. High; some may be mapping artifacts. Not orthogonally validated |
| deletion | 78 | 40 have MH >= 2 bp. Includes the 30.6 Mb chr15 deletion that step5 links to B2M 1:0 |
| inversion junction | 48 | 24 are > 10 Mb |

The SV section of `analysis.py` over-counted translocations (389 vs 222) because of coordinate-based de-duplication. That section is superseded by `scripts/sv_summary.py`.

## 9. Cost

`cost_ledger.csv` has 9 instances, priced as on-demand list price or spot price at launch, plus gp3 2000 GiB EBS, IPv4 and fixed S3/KMS/logs/egress allowances.

- **Total: $10.33.** The coordinator's earlier $8.81 left out the gather instance and the scale-down tail.
- Two purged instances were bracketed conservatively:
  - c7i.16xlarge end set to 00:40Z; its last job ended 00:22Z.
  - Gather c7g.8xlarge set to 00:20-00:55Z; the job ran 00:22:43-00:45:23Z.
- No step8 jobs or instances remain active.

## 10. Limitations

- FFPE tumor at about 40x WGS. Sensitivity is limited below roughly 10% VAF; MTOR, PHKB and the 4 exome-only Serova sites illustrate this.
- The consensus is conservative: indels are under-counted, and calls with low alt counts are lost.
- SBS3 cannot be separated from other flat signatures using SNVs alone.
- The translocation count is not orthogonally validated.
- TMB here is genome-wide, not coding.
- None of these findings are clinical.
