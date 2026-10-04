# Problems found: the EVEE variant report and the bulk-RNA "bottom-up" comparison

Diana multi-omic review · 2026-10-04 · research use only

This report documents two sources of misleading results found during the review, and how each was caught:

1. **The EVEE variant-interpretation report** (dated 2026-08-11) built its therapeutic hypotheses on somatic variants
   that do not exist in the tumor.
2. **Genome-wide comparisons of Diana's bulk tumor RNA against TCGA** produce mostly technical artifacts, because the
   RNA library is capture-based and taken from a tumor-poor piece.

Neither invalidates the confirmed findings (biallelic BRCA1 and TP53 loss, HRD-high scars, TROP-2 protein, high sTIL).
Both explain why some earlier conclusions were withdrawn. Detailed evidence is in step 3 (exome audit), step 7
(provenance), step 8 (WGS controls), step 9 (bulk RNA) and step 15 (outlier analysis) of this review.

---

## Part 1. The EVEE report

### What it claimed
The report scored "607 somatic variants from matched tumor/normal WGS" with Goodfire's EVEE model and highlighted nine
"tier-1" variants as damaging. Each anchored a treatment hypothesis:

| Variant | Report claim | Hypothesis it supported |
|---|---|---|
| MTOR p.Gly98Ser | high disruption | mTOR activation, everolimus |
| SCAP p.Trp633Ter | loss of function confirmed | cholesterol dependency, statins |
| RXRA p.Ser96Ter | loss of function confirmed | RXR agonist (bexarotene) |
| CUL3 p.Arg354Cys | high disruption | NRF2 activation, ferroptosis |
| DLL4 p.Arg516Cys | high disruption | Notch, anti-DLL4 |
| ATG4B p.Trp142Ter | loss of function confirmed | autophagy collapse |
| ATG13 p.Asp213Gly | high disruption | autophagy collapse |
| FGFR4 p.Ser106Phe | moderate-high | FGFR inhibitors |
| BRD3 p.Ser676Gly | moderate | BET inhibitors |

It also named RB1CC1, PPARD, WNT2B, WNT6, LIN28A, FZD10, CBL, ARIH2 and SHH (one "pathogenic" call).

### Problem 1: none of its own variants are in the tumor
We re-genotyped every variant the report names in four independent read sets: deep tumor and normal exome
(~200-800x), tumor and normal WGS (~46x / ~51x), and tumor RNA.

- **All 9 tier-1 variants: 0 supporting reads in the deep exome** (172-793 tumor fragments each; 95% upper bound on
  allele fraction 0.4-1.7%). Results were identical under relaxed and strict read filters, and an independent
  `samtools mpileup` gave the same.
- **0 of 18 EVEE-only variants reproduce in any assay.** The one EVEE-named variant that is real (PIKFYVE I1548T) was
  already in the Altera clinical report.
- **The same exome finds the real variants:** BRCA1 c.81-1G>A at 22%, BRCA2 S2695L 15%, TP53 c.559+2T>G 35%,
  PIKFYVE 9%, MTOR P1125A 9.5%, all absent from the normal.
- **Our WGS somatic calls (Mutect2 + Strelka2 consensus, 16,967 PASS calls)** contain none of the nine. CUL3 passed
  Strelka2 alone, on 3 of 63 reads.

### Problem 2: the input list looks like a lenient, single-molecule call set
- **Every EVEE-only variant has exactly 1-2 WGS tumor fragments, at nominal 4-14% allele fraction.**
- **They cluster where tumor depth is low:** a median 11.5 fragments vs 29 at real (Altera) sites (p = 1.3e-4). These
  are copy-loss regions, where a single read pair looks like a 7-14% variant against a normal with no alternate reads.
- **At 7 of 9 tier-1 sites both mates of the one fragment carry the base,** so a read-counting caller sees "2 reads".
- **60% are C>T/G>A,** the damage class elevated in this tumor library.
- **CBL p.Asp460del is a repeat-stutter artifact** (GAT repeat) that also appears in the matched normal.
- **SHH p.Gln209Ter** (the report's single "pathogenic" call) has 0/686 exome reads. It is also the "pathogenic SHH"
  named in a separate July 17 analysis summary, which suggests both documents drew on the same unvalidated list.

### Problem 3: the stated method cannot have produced the labels
- **The report describes a coordinate lookup against EVEE's precomputed ClinVar table,** which it says covers only
  ClinVar SNVs.
- **Goodfire's public EVEE/ClinVar service has no entry for 8 of the 9 tier-1 variants.** The one hit, CUL3, scores
  0.40 and is a ClinVar VUS.
- **Seven of the nine have no dbSNP or ClinVar record at all.**
- **So "loss of function confirmed" and "high disruption" did not come from EVEE scores.** Their actual source is
  undocumented.

### Problem 4: internal and biological errors
- **Header contradiction:** three stop-gained variants are listed under a "VEP = MODERATE" selection header.
- **"TSC complex intact," but TSC2 p.Arg59Trp is present** (10.7% in exome, absent from the normal).
- **Domain claims are wrong:**
  - FGFR4 Ser106 is in an extracellular Ig-like domain, not "kinase-adjacent".
  - BRD3 Ser676 is outside both bromodomains.
- **VEP "MODERATE" is treated as "missed discoveries."** MODERATE is a consequence class (e.g. missense), not a
  pathogenicity call.
- **It missed the real drivers:**
  - TP53 c.559+2T>G (35%, truncal) is absent from the report.
  - The real mTOR-pathway variant (MTOR P1125A, 9.5%) is not discussed, while the non-existent G98S is the headline.

### Problem 5: provenance
- **No callset behind the report exists anywhere we could search:** repository history, local files, or the 12 cloud
  storage buckets.
- **The PDF is titled "Soft Star Report" and its disclaimer names "K2",** an AI-agent orchestration platform. It
  appears to have been generated by an agent run using Goodfire's public EVEE data, not by Goodfire. This is an
  inference from the document itself.
- **Its "Personalis pipeline" input is not a Personalis deliverable;** the delivery contains no VCF or MAF.

### Related claims that did not hold up
- **"HRD score 62" (July 17 summary).** No code, configuration or callset exists for it, and it was re-run after an
  undocumented "software setting" change. Our independent copy-number fit gives HRD scars of 67-99, so the
  HRD-high conclusion holds, but the 62 itself is unverifiable.
- **"HRD 72" (July 22 Sequenza fit).** The fit failed its own consistency checks. It called 15% of the genome
  zero-copy and placed BRCA1 on a zero-copy segment despite a 21% variant there. It was replaced by a fit that
  passes every check (purity 0.35, ploidy 2.8).

### What survives from EVEE
- **Nothing tumor-specific.** All EVEE-derived hypotheses lose their genetic basis: autophagy, mTOR G98S, lipid/SCAP,
  RXRA, CUL3/NRF2, Notch/Wnt, FGFR4, BET, Hedgehog.
- **The real pathway findings come from verified variants instead:** BRCA1/TP53 biallelic loss and HRD; MTOR P1125A,
  TSC2 R59W and PIKFYVE I1548T as mTOR-axis candidates of unknown function.

---

## Part 2. The bulk-RNA bottom-up comparison

### What was attempted
- Rank all ~19,700 protein-coding genes in Diana's bulk tumor RNA against 180 TCGA triple-negative tumors.
- Look for genes she expresses far above other patients.

### Problem 1: the library is capture-based, the reference is not
- **The tumor RNA was made with a hybrid-capture library (Personalis ACE4).** Its STAR genome is named
  `Cancer_Ace_V4` and the read names carry the ACE4 tag. TCGA used poly-A RNA-seq.
- **Cancer-panel genes are inflated a median of ~3.4x** (45% of them more than 4x, vs 4% of other genes,
  p ~ 1e-64). Replication-dependent histones are inflated ~26x.
- **Implausible raw values result,** e.g. ATM 709 TPM and ERBB3 711 TPM.
- **The whole profile is distorted:** correlation to TCGA TNBC is 0.76, lower than any TCGA tumor (0.84-0.93), with a
  compressed dynamic range (slope 0.77).

### Problem 2: the piece is tumor-poor
- **Epithelial markers are at the 7th percentile and proliferation at the 9th** among TNBC.
- **Benign-breast and fat transcripts are high,** and immunoglobulin transcripts are 22.6% of all TPM (IgA-dominant,
  plasma-cell rich).
- **Tumor-cell genes are diluted, and microenvironment genes look high.** The H&E core shows the same gradient: 12%
  to 42% tumor nuclei along its length.

### Problem 3: the outlier list is mostly artifact
- **2,061 genes came out at or above the 95th percentile** (z >= 2, TPM >= 5).
- **The top hits were technical signatures:** zinc-finger genes, ANKRD36/NBPF paralog families, very long genes
  (AKAP9, FRYL) and cancer-panel genes, many at the 100th percentile against every TCGA tumor.
- **A model of the deviation from gene structure alone explained 26% of it,** confirming a large technical component.
- **Even after correction, panel and paralog genes still led the list** (EWSR1, MDM4, MAP2K4, ASXL1, MLH1).
- **Key genes disagree with the single-nucleus data:**
  - POLQ: bulk low after correction, ~10x above other TNBC in tumor cells.
  - VTCN1/B7-H4: 22nd percentile in bulk, above all 8 public tumors in tumor cells.
  - ERBB4: off-scale in bulk because TCGA TNBC barely expresses it.

### Earlier conclusions this affected
- **Cross-assay tables built from bulk TPMs** (TACSTD2 108, ERBB3 711, MET, FOLR1, CD274 percentiles) overstated
  panel genes. "High RNA but protein not detected" for HER3, MET, AXL, FGFR and PD-L1 is largely this artifact.
- **The vaccine vendor's antigen-processing claim** (TAP2 0.05x, B2M 0.17x of normal breast) compared this bulk sample
  with normal breast. In tumor cells the reduction is real but milder: 0.3-0.6x of normal breast epithelium.
- **"T cells mid-range"** came from this tumor-poor piece. The pathologist's stromal TIL score is 50%.

### What replaced it
- **Tumor cells vs tumor cells.**
  - Diana's malignant nuclei (single-nucleus RNA) compared with tumor cells from 8 public TNBC tumors (4 sporadic, 4
    BRCA1).
  - A per-gene correction for nuclei-vs-whole-cell chemistry, learned from shared T-cell, myeloid and fibroblast
    populations, explains 60% of the technical difference.
- **Only concordant genes are trusted:** high in both comparisons, ideally backed by a DNA amplification.
  - That yields CD44 (amplified ~12 copies), the chr22q12 and 11q13 amplicon genes, SLC28A3, ATR, HORMAD1 and
    SLC6A14.
  - It shows TROP-2 to be typical for TNBC rather than an outlier.

### How to make bulk RNA usable
- Ask Personalis for the ACE4 bait design, so capture inflation can be modelled per gene.
- Compare against a reference processed with the same chemistry.
- Or obtain a whole-transcriptome (poly-A or rRNA-depleted) library from a tumor-rich region.

---

## Lessons for future analyses
1. **Re-genotype every variant a report relies on** in the deepest independent assay before using it. Include known
   real variants as positive controls in the same run.
2. **Treat single-fragment calls in low-coverage, copy-loss regions as suspect.** Check orientation, repeats and the
   matched normal.
3. **Ask for the callset.** A report without its input file is unverifiable, however confident its prose.
4. **Check the RNA library chemistry before comparing with a public cohort.** Capture and poly-A libraries are not
   comparable gene by gene.
5. **Prefer comparisons that cancel technical bias:** same cell type across datasets, concordance between methods
   with different biases, and DNA support.
