# Diana multi-omic review and next steps (private, 2026-10-03)

Research prioritization only. Nothing here is a treatment recommendation; therapy decisions belong with the oncology
team. Keep this file under ignored `private/` (the repo is public).

## 1. What exists

| Layer | What we hold | Specimen / state | Status |
| --- | --- | --- | --- |
| Altera report (preliminary, 05-12) | BRCA1 c.81-1G>A, VAF 27%, depth 2,565; BRCA2 p.Ser2695Leu 12%; no HRD score | FFPE block SUS26-1600 A2, collected 2026-03-13 (per step-1 ledger) | source report only |
| In-house July 17 WGS summary (family/care-team document) | ~16,000 somatic mutations ("two methods agreed"), HRD 62 = LST 27 + TAI 26 + LOH 9, "biallelic BRCA1" | WGS DRF-PSN49561 | callset and intermediates not available; contamination/identity QC not run; score re-run after a setting change; likely source of the EVEE variant list |
| Personalis ImmunoID E019 | tumor exome BAM (330.9M mapped reads, 41.7 GiB), normal exome (137.1M reads), tumor RNA BAM/FASTQ; build hs37d5 | specimen/date unknown | exome never used for the EVEE alleles; bulk RNA quantified (Salmon, Sept 4) |
| WGS (DRF-PSN49561) | tumor ~46x / normal ~51x (5 Mb bins), GRCh38, contamination 0.16%; BAMs in the private bucket (versioned) | specimen/date unknown | 15-gene HRR early look; a July 22 Modal Sequenza->scarHRD run finished (purity 0.31, ploidy 1.6, HRD-LOH 24, TAI 20, LST 28, sum 72, labeled no_call) but the fit looks wrong (section 2, item 4); no full somatic VCF, SVs or signatures |
| Proteomics CP0216 | CLIA quantitative MS on laser-microdissected tumor; TROP2 1,705 amol/ug (median 1,891, LOQ 75), TOPO1 568 (LOQ 400), HER3/MET/FGFR/AXL not detected, SLFN11 ND | SP-26-027487-BR-VL3-A1, collected 2026-03-13 (pre-treatment) | single specimen, no phospho/autophagy readouts |
| H&E | two SVS slides: SP-26-022231, SP-26-027487 | 027487 matches the proteomics accession | not analyzed |
| EVEE (Goodfire) report | 9 complete tier-1 SNVs + incomplete RB1CC1/PPARD hits | derived from an unrecovered variant list | Codex reproduced REF + MANE consequences; read evidence thin |
| scRNA KH022 | 2 vendor libraries (38,994 + 37,805 barcodes), Cell Ranger 10.1.0, GEM-X 3' v4, GRCh38-2024-A, introns included | specimen, date, material, library relationship all unknown | Codex diagnostics done; metadata hold on |

## 2. Review of Codex's work

Solid:
- Custody is excellent: exact-version S3 receipts, independent barcode-level numeric audit, all 76,799 barcodes kept,
  libraries namespaced (1,184 shared barcode strings are not treated as shared cells), doublet flags and SoupX never
  applied to the primary counts, vendor labels never promoted to truth, `clinical_ready` false throughout.
- The EVEE review is careful: REF alleles match, MANE protein changes reproduce, overlapping mates collapsed, three
  quality policies, and it caught that ATG13's two "alt reads" are one supplementary-alignment fragment. It also
  corrects report errors (FGFR4 residue 106 is in Ig-like domain 1, not kinase-adjacent; BRD3 S676 is outside both
  bromodomains; VEP MODERATE is consequence severity, not a benign call).
- The cross-assay table refuses to divide TPM by UMI by amol/ug.

Concerns and gaps (new in this review, verified against the data):
1. **KH022 is probably nuclei, not whole cells, and nobody has said so.** Vendor QC: 49.6% / 49.3% of confidently
   mapped reads are intronic and only 37.7% / 38.4% exonic (introns included), with median mitochondrial reads
   0.87% / 0.95%. Whole dissociated tumor cells usually run far higher mitochondrial and lower intronic. Codex lists
   "whole cells or nuclei" as open and correctly skips whole-cell filters, but the evidence leans one way and it changes
   the reading of everything: detection of membrane/secreted genes such as TACSTD2 (32%) is nuclear-RNA detection;
   Azimuth/10x Cloud references are mostly whole-cell, which may explain 38% "goblet cell" labels; ambient and doublet
   behavior differ in nuclei. Strong indicator, not proof.
2. **The EVEE "insufficient depth" is partly copy loss.** Coarse WGS coverage (5 Mb bins, normalized to genome median,
   no purity/ploidy) puts seven of the nine audited loci in relative loss:
   MTOR -0.91, SCAP -0.78, RXRA and BRD3 -1.34, ATG4B -0.82, DLL4 -0.80, FGFR4 -1.12 (log2 tumor/normal);
   CUL3 +0.16 and ATG13 -0.20 are neutral. At those loci raw tumor reads are 2-4x below normal before any filter
   (MTOR: 18 vs 72 reads fetched). A clonal heterozygous variant on a retained allele in a loss region would show a
   *high* VAF; one alt fragment in 7-14 is too little to say, but it leans against clonal variants there.
3. **The deep exome was never used for these alleles.** The audit used ~46x WGS. The tumor exome has 330.9M mapped
   reads (roughly several hundred x over a typical exome target; estimated from the BAM index only, read length and
   target size assumed). The EVEE variants are exonic and likely came from this assay, so this is the decisive test.
   Beware FFPE-type C>T/G>A artifacts (most audited sites are transitions); check strand orientation.
4. **The only scar-based HRD number rests on a Sequenza fit that cannot explain its own data.** The July 22 run
   (purity 0.31, ploidy 1.6, posterior 0.19, one alternative solution recorded) gives HRD-sum 72, but: 15.0% of the
   genome is called homozygously deleted (CNt=0); 12.9% of the genome has depth ratios below the lowest ratio that
   purity 0.31 / ploidy 1.6 can produce for *any* copy state (0.736); 4,169 segments (3,394 under 1 Mb) inflate scar
   counts; and the BRCA1 segment is called CNt=0 although a somatic BRCA1 variant is seen at 21-27% VAF (a tumor with
   zero copies cannot carry it). Observed BAF there (0.348, 1,344 SNPs) is what copy-neutral LOH would give at this
   purity, which the depth dips contradict. Higher-purity/higher-ploidy solutions probably fit better. Codex's `no_call`
   label is correct; do not cite 72, or its rough agreement with the July 17 in-house summary's 62 (a separate, unavailable callset), as corroboration until an
   independent allele-specific caller (FACETS / ASCAT / PURPLE) agrees. The same fit also makes its per-locus copy
   states (CNt=0 at MTOR, RXRA, BRD3, FGFR4, DLL4, ATG13, ERBB3) unreliable; only the raw coverage dips are solid.
   Still missing entirely: a genome-wide somatic VCF (no Mutect2 shard checkpoints survive), SVs, SBS3/CHORD/HRDetect
   inputs. The cross-check pipelines (SigProfiler SBS3, Sequenza/scarHRD, FACETS, oncoanalyser/PURPLE/CHORD) are built
   and gated on "final primary WGS artifacts".
5. **The exploratory scRNA lane still uses one fixed resolution (0.5, seeds 42-44)**, the same fragile design replaced
   in the patient path (ARI 0.749 / 0.674 here). Port `stable_leiden` and add a nuclei QC profile
   (the intake guard says nuclei need separate calibration).
6. **Specimen identity is assumed, not tested.** Everything cross-assay presumes one patient and one tumor. We hold
   the normal WGS germline genotypes, so identity and pooled-donor status are directly checkable.
7. **Public exposure.** The KH022 delivery (232 GB incl. FASTQ/BAM, vendor dotfiles) sits in the public-read inbox "at
   the owner's explicit request". BAMs carry germline genotypes (re-identifiable). Fine if deliberate and consented;
   just irreversible once copied.

Coarse genome context (not allele-specific): 99/619 bins relative loss, 45 gain; chr17 -0.49, chr19 -0.88, chr22 -0.69,
chr15/16 about -0.36, chr3 +0.33. BRCA1 (17q21) -0.94 and SLFN11 (17q12) -0.67 are in loss; TACSTD2 (+0.18),
CUL3, ATG13, BRCA2 and TOP1 (-0.40) are neutral/mild. BRCA1 VAF 21% (WGS) / 27% (Altera) with 17q21 loss is
compatible with the reported biallelic model if purity is roughly 35-45% (variant on the sole retained copy:
VAF = p / (p + 2(1-p))). That is arithmetic, not a finding; it needs allele-specific CN.

## 3. Prioritized next steps (information gained per cost)

| # | Step | Layers | Cost / time | Unblocks | Stop/redirect if |
| --- | --- | --- | --- | --- | --- |
| 0.1 | Specimen ledger + vendor questions (section 5) | all | free, days | every cross-assay claim | KH022 not from this patient/tumor |
| 0.2 | Genotype identity + pooled-donor test: scRNA BAM (GRCh38) vs WGS normal germline SNPs (cellsnp-lite + vireo/souporcell); compare KH022-1 vs -1-1 | scRNA, WGS | hours, CPU; BAM is 29 GB | identity, pooling | discordant genotypes |
| 0.3 | Nuclei vs cells: per-barcode intronic fraction, MALAT1/NEAT1, MT; then set the QC profile | scRNA | hours | valid QC/annotation/target readouts | |
| 1.1 | EVEE allele audit on the deep tumor/normal exome (liftover to hs37d5), with strand-orientation metrics; add tumor RNA allelic reads | WES, RNA, EVEE | pennies, hours | confirms or retires 8 of 9 hypotheses | none supported -> deprioritize EVEE |
| 1.2 | BRCA1 splice evidence in the existing tumor RNA BAM: junction reads around the affected exon (skipping / cryptic acceptor), allelic imbalance | RNA, WES | pennies, hours | orthogonal function for the one best-supported variant | |
| 2.1 | Fix allele-specific CN first: re-fit with FACETS and PURPLE (plus an explicit Sequenza grid) on the existing BAMs; constrain purity with the BRCA1/clonal-SNV VAF peak and H&E. Then re-score scarHRD only from a fit the callers agree on | WGS | hours-1 day, CPU; the Sequenza checkpoints (seqz) are already in S3 | purity/ploidy, BRCA1 LOH state, trustworthy HRD scars | callers disagree -> keep HRD no_call |
| 2.2 | Complete WGS evidence: full somatic SNV/indel, SVs, SBS/ID signatures (BAMs exist). CPU scatter ~$10-22 / 1.5-3 h or P5 Parabricks ~$70-135 / 1-2 h (projections, not measured); gpu-p5en queue enabled, quota unknown | WGS | ~1 day incl. verification | somatic variants for scRNA/EVEE, SBS3/CHORD/HRDetect, TMB | HRD adapters stay no_call until known-answer qualified |
| 3.1 | scRNA re-analysis: nuclei QC profile, stable resolution, consensus doublets, nuclei-aware ambient removal, breast-specific labels (Wu 2021 / Pal 2021 plus the 8 TNBC captures already processed), vendor labels kept as evidence only | scRNA | days, Modal CPU | clean compartments | |
| 3.2 | Malignant-nuclei calls from independent evidence: allele-aware CNV (Numbat) checked against the WGS profile (17, 19, 22 loss, 3 gain), then somatic SNV tracking from 2.1 | scRNA, WGS | days | tumor-cell-restricted readouts; second identity check | CNV profile does not match WGS |
| 3.3 | Target readouts in malignant nuclei only: TACSTD2 distribution/heterogeneity, TOP1, SLFN11 (tumor vs T/B cells), ABCB1/ABCG2, ERBB3, MET, FOLR1, EGFR, NECTIN4, CD276, F3, HRR genes; immune: CD274, PDCD1, B2M/HLA; each with ambient/doublet sensitivity and depth-matched controls | scRNA, proteomics, bulk RNA | days | the 37 "blocked" target-board rows | |
| 4.1 | H&E (two slides ready): tumor cellularity, stromal TILs, necrosis; confirm which slide matches the proteomics block | pathology | days, pathologist review | purity cross-check, specimen anchor | |
| 4.2 | Orthogonal protein localization on remaining FFPE, via the treating team/pathology: TROP2 membranous, SLFN11 nuclear, HER2-low, PD-L1 (CPS), Ki67 | pathology | weeks, tissue-limited | what RNA cannot show: membrane TROP2, SLFN11 protein | |
| 5.1 | One evidence matrix per therapeutic question (TROP2/ADC payload, HR deficiency, immune, EVEE hypotheses) with specimen ID, assay, confidence, and open gates; for the oncology team | all | days | decisions made on verified evidence | |
| 6.1 | Code: port `stable_leiden` + nuclei profile to the exploratory lane; commit the specimen ledger schema | engineering | hours | | |

Parallelism: 0.1-0.3, 1.1, 1.2 can all start now. 2.1 and 2.2 can run alongside 3.1. 3.2 needs 2.2 for SNV tracking but can use
CNV alone first.

## 4. How the layers should be read together

- TROP2/ADC: protein (1,705 amol/ug in microdissected tumor, near the assay median) is the strongest presence evidence;
  bulk RNA agrees; scRNA's job is tumor-cell heterogeneity, which needs malignant-cell calls first. Membrane
  accessibility is IHC's job. Payload context: TOP1 protein is modest, SLFN11 protein is not detected while bulk RNA is
  20 TPM and only ~4.6% of barcodes detect it, so tumor-cell SLFN11 deficiency (possibly 17q12 loss) is a testable
  hypothesis, not a result.
- HR deficiency: somatic BRCA1 splice-acceptor variant (absent in normal, hereditary panel negative per the case
  summary), 17q21 relative coverage loss, ERCC1 protein not detected. Several independent signals point the same way
  (variant, loss, BAF imbalance at 17q21, the July 17 in-house HRD 62), but the scarHRD sum of 72 sits on a broken CN fit and
  the 62 comes from a callset that also produced the EVEE variants absent in the deep exome.
  Needs a trustworthy allele-specific CN fit (2.1), splice evidence (1.2) and genome-wide scars before "biallelic" or
  an HRD score is treated as verified. BRCA2 p.Ser2695Leu is provisional
  (ClinVar conflicting, likely benign).
- EVEE: only the BRCA1 control has convincing support. Rank the rest after 1.1; do not let the report's narrative set
  priorities. Autophagy/mTOR/lipid/NRF2 hypotheses need allele confirmation then functional assays Codex already lists.

## 5. Questions only you, the clinic, or vendors can answer

1. KH022: which specimen/accession (SP-26-...), collection date, source (core vs resection), pre- or post-therapy.
2. Whole cells vs nuclei; fresh vs frozen; dissociation/nuclei isolation protocol; viability.
3. What are KH022-1 and KH022-1-1 (replicate channels of one suspension, a re-run, different tissue)? Cells loaded,
   kit, hashing, vendor order 1012026.
4. Same specimen behind the Personalis DNA/RNA, WGS and Altera? Dates and tumor fractions.
5. Is public release of the KH022 raw data intended and consented?
6. Is tissue left from block VL3-A1 (or another block) for IHC?

## 6. Cautions

- A matched specimen is not established for scRNA vs proteomics vs DNA; if KH022 is post-treatment tissue, analyze it
  as a separate timepoint, not as confirmation of March findings.
- RNA detection percentages from ~38k nuclei at 25% flagged doublets are not tumor percent-positive.
- Do not tune QC thresholds or label panels until a gate passes; test any panel change on held-out data.

## 7. Results of steps 1-4 (run 2026-10-03; five agents, spot-checked)

| Step | Result | Spot-check |
| --- | --- | --- |
| 1 Specimen ledger | One tumor genome across exome, WGS, tumor RNA, Altera and KH022 (somatic BRCA1 c.81-1G>A and BRCA2 p.Ser2695Leu present in all tumor assays, absent in both normals; BRCA1 allele in reads of both scRNA libraries). Dated anchor: FFPE breast block collected 2026-03-13 (Altera SUS26-1600 A2 = proteomics SP-26-027487 = H&E slide B). KH022 specimen, date and treatment state still unknown. KH022-1 and KH022-1-1 are two distinct libraries sequenced together (FASTQs written 2026-09-24). Personalis exome BAMs were aligned from "downsampled" FASTQs | HRD 62 traced to the July 17 in-house summary (not Altera); "defective KH022-1-1 index" claim was WRONG (presign region issue; index verified working) |
| 2a Identity / pooling | Both libraries match the WGS normal (het-only log10 LR +863 / +823; 0 of 2,822 / 2,702 hom-alt sites read hom-ref); single donor (second genome >=5% rejected, 2% not excludable); libraries same individual (log10 LR +2,041); arm-level allele imbalance tracks tumor WGS (r 0.81-0.82, 17q highest) | numbers match identity_stats.json |
| 2b Nuclei vs cells | Nuclei / cytoplasm-depleted, ~95%: ribosomal-protein UMIs 1.0% (whole-cell TNBC 14.5-41.8%), intronic UMIs 56-57%, GAPDH detected in ~38% of barcodes (whole cells ~96-100%), ambient is cytoplasmic. TACSTD2 (single-exon) detection is mostly ambient-driven and capped; 25% doublet flags exceed ~15% expected | recomputed RP 1.01/1.00%, GAPDH 37-38% |
| 3 EVEE on deep exome | All nine highlighted SNVs absent: 0 alt in 172-740 tumor fragments each (95% upper AF 0.4-1.7%); BRCA1 control 126/573 (22.0%), normal 0/281. Same exome reproduces other Altera variants (BRCA2 14.8%, PIKFYVE 9.0%, MTOR P1125A 9.4%, PTPN23 16.2%). RB1CC1 donor+2 and PPARD Q415H candidate also absent | independent mpileup: 0 alt at all nine; BRCA1 134/595 reads; liftover confirmed by Ensembl, hg19 bases by UCSC |
| 4 BRCA1 splicing | Exon 3 (54 bp) acceptor: canonical only 16.8% (CI 13.5-20.5%); cryptic +7 nt acceptor dominant, plus +16/+10 and exon-3 skipping (in-frame length but creates TGA stop); background at 20 other acceptors 0.58%. Variant allele transcribed (48/60 RNA fragments); one exonic germline SNP shows tumor-haplotype allele 62% DNA vs 93% RNA (unphased) | independent junction count from region BAM: canonical 109, +7 cryptic 441, +16 62, skip 48 reads (fragment-vs-read differences only) |

Implications:
- EVEE hypotheses (autophagy, mTOR, lipid, CUL3/NRF2, DLL4, FGFR4, BET) lose their genetic premise in this tumor. Ask
  where the EVEE report's variant list came from; the likely source (the July 17 callset, ~16,000 mutations, no
  contamination/identity QC, intermediates deleted) also produced HRD 62, which should not be relied on until reproduced.
- BRCA1: strongest single finding. Somatic splice variant at 22% VAF with ~83% aberrant splicing at the acceptor and a
  tumor-haplotype-dominant RNA pattern: consistent with loss of normal BRCA1 splicing in tumor cells. Biallelic status
  still needs a trustworthy allele-specific CN fit (step 2.1).
- KH022: patient's tumor, single donor, but nuclei material and unknown timepoint. Re-analyze with a nuclei profile;
  do not use whole-cell references or read TACSTD2 detection as percent-positive.
- Privacy: H&E SVS label images in the public-read inbox show the patient's name with the accession.

## 8. Round 2 results (2026-10-03, spot-checked)

- Germline (step11): no P/LP or rare LoF in 29 genes; BRCA1/BRCA2 confirmed somatic. Clinical panel report still to obtain.
- Bulk RNA (step9): CAPTURE library (Personalis ACE4) — panel genes inflated ~3.4x; specimen tumor-poor (epithelial 7th pct);
  PAM50 basal-like; B/plasma (IgA) and macrophage rich, not T-cell inflamed.
- scRNA (step6): KH022 ~50% malignant nuclei (two genetic signals agree ~98%; BRCA1 mutant reads in malignant nuclei);
  TOP1 broad; SLFN11 ~5-10x lower in tumor than stroma/immune; ERBB3 tumor-specific RNA; TACSTD2 ambient-dominated;
  chr17 copy-neutral-looking LOH.
- Provenance (step7): July 17 summary and the EVEE "Soft Star"/K2 report are external; no callset found; 0/18 EVEE-only
  variants reproduce; EVEE hypotheses dropped. TP53 c.559+2T>G (Altera-listed, missed by both reports) confirmed:
  exome 439/1266 (34.7%), normal 0/836 (independently verified). TSC2 R59W 10.7%.
- Specimens: a subclone in Altera + WGS (e.g. F5 E2057* WGS 7/58, exome 0/561; OTUD4 5/39 vs 0/320, verified) is absent
  in the exome -> the exome came from a different tissue piece. Exome absence alone does not exclude a variant.
- Privacy: my 2026-10-02 WIP commit pushed `manifests/evee_report_highlights.tsv` (+workbench json, results/evee_context)
  to the public repo — pseudonymous variant list, no names/DOB/accessions (checked).

## 9. Round 3 results (2026-10-04, spot-checked)
- ASCN (step5): purity ~0.35, ploidy ~2.8, WGD likely; TP53 c.559+2T>G on all retained copies (17p LOH); BRCA1 wild-type
  haplotype lost (17q LOH), variant on retained copy; HRD scars 67-99 (>=42 in every plausible fit); B2M 1:0; no clonal
  HLA LOH (HLA-A weakest). Old Sequenza fit and FACETS zero-copy calls rejected.
- WGS somatic (step8, $10.33): consensus 16,967 (Mutect2 72,293 / Strelka2 53,798); TMB 6.1/Mb genome-wide (~3.7 clonal);
  controls BRCA1/BRCA2/TP53/PIKFYVE/PTPN23 PASS, MTOR P1125A strand-bias filtered by Mutect2; EVEE sites absent;
  Serova 16/22 missense sites consensus PASS (MAST1, RABL6, SDC3, NUMA1 exome-only); SBS3 0.41 (CI 0.38-0.44) with a
  fixed breast signature set but 0 with SigProfilerAssignment; 60% microhomology at larger deletions; 511 SVs (163 TDs).
- H&E (step10): slide B ~30% tumor nuclei (12-42% along core), sTIL ~6%; slide A mostly lymphoid (pathologist needed).
- Serova vaccine integration: subagent declined interpretive scope twice; narrower options offered to the user.

## 10. Correction (2026-10-04): pathologist sTIL
HistoWiz 40822 PC3152 (board-certified review): breast core SP-26-027487 (dated 4/10/2026) **sTIL 50%**, cellularity
50%, grade 3, Ki67 40-50%, HER2 IHC 0/ISH 0; axillary node SP-26-22231 (3/23/2026) metastatic carcinoma, sTIL ~10%.
The computational sTIL of ~6% (step 10) is withdrawn. High sTIL fits the B/plasma/macrophage-rich infiltrate seen in
RNA (sTIL counts all mononuclear cells); CD8/cytolytic signals were mid-range in a different, tumor-poor bulk piece.
Specimen-date conflict: proteomics lists SP-26-027487-BR-VL3-A1 as collected 3/13 (Sutter); HistoWiz dates
SP-26-027487 to 4/10 (Stanford).
