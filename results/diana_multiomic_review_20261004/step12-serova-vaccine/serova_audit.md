# Serova SRV-DL-T0: transcription and data audit (2026-10-04)

Research audit of the vendor's stated evidence against our independent data. It is input for discussion with
Serova and the clinical team, not a design recommendation. KH022 (single-nucleus) is a different, undated
specimen from Serova's T0.

Files: `serova_windows.csv` (27 windows, transcribed), `serova_construct_claims.csv` (17 claims),
`site_recounts.csv`, `gene_readouts_malignant_vs_other.csv`, `scripts/01-06`.

## 1. Missense windows (22): read evidence reproduces

- **Our deep-exome counts match Serova's essentially exactly at all 22 sites.** Examples: MTOR 100/1,061 vs
  their 100/1,057; BRCA2 201/1,362 vs 201/1,354. The normal exome is 0 at every site. Their exome BAM is very likely
  our Personalis exome, realigned.
- **Our WGS consensus (Mutect2 and Strelka2 both PASS) contains 16 of 22.**
  - MTOR is Strelka-only (Mutect2 strand-bias filter) and PHKB is Strelka-only (Mutect2 orientation filter).
  - MAST1, RABL6, SDC3 and NUMA1 have 0–1 WGS alt reads in both our data and Serova's. These rest on exome evidence
    only.
  - The exome and WGS sample different tissue pieces (step 7).
- **Tumor RNA:** fractions match Serova's read-evidence pages.
  - REST: our 8/33 (24%) agrees with their read-evidence page (6/26, 23%). **Their construct text and Fig. 4 say
    1.4%,** which is an internal inconsistency.
  - SDC3: our RNA 11/170 (6.5%, 3f/8r) is less strand-skewed than their 6/6 reverse.
  - MAST1 and TP63 have no RNA coverage.
- **KH022 single nuclei:**
  - Mutant molecules were seen in malignant nuclei for TAF4B (43/46 and 57/60 UMIs, ~94% mutant), ZNF83, SLC46A3,
    MELTF, APEH, NUMA1, TXNDC5, USP10, MAN1A1, ANTXR2, PHKB, HERC1, RABL6 and DSTN.
  - No informative coverage at PTPRH, TAC4, MAST1, TP63, SDC3 or BRCA2 (3' chemistry), and REST had 0/7.
  - Abundant short transcripts (DSTN, TXNDC5, MELTF) also show mutant molecules in non-malignant nuclei. That is the
    expected tumor-derived ambient RNA, so those per-nucleus fractions are not cell-level.
- **Gene expression in KH022 malignant nuclei (CPM).** TP63 is ~3, against 345–567 in normal epithelium and 845–935
  in myoepithelial nuclei. PTPRH is ~0, MAST1 ~2, TAC4 ~2, APEH ~3, SDC3 ~3.5 and SLC46A3 ~8: these windows' genes
  are barely expressed in malignant nuclei of this specimen. Expressed: NUMA1 ~320, SHANK2 ~2,900, NCKAP1 ~180,
  HERC1 ~174, ZNF83 ~132, USP10 ~121, MELTF ~105, BRCA2 ~71 and MTOR ~71.

## 2. Non-missense windows

- **NCKAP1 SV (W7/W15/W18):** our Manta independently calls a somatic tandem duplication at exactly Serova's
  breakpoints (chr2:183,009,642–183,025,236; 15.6 kb). The DNA is confirmed. In tumor RNA our check finds 0 junction
  reads, matching Serova's own 0 split reads against 1,057 intact. RNA evidence that the rearranged sequence is
  transcribed is absent in both analyses.
- **SHANK2 fusion (W8): our data do not support a fusion.**
  - No DNA breakpoint: Serova's genome shows 0 clipped reads, and our Manta calls nothing.
  - In tumor RNA the reported breakpoint (hg19 chr11:70,644,548) is an exon start used by 5,314 normally spliced
    reads.
  - Of the 326 reads clipped there:
    - 110 carry the upstream SHANK2 exon (normal splicing soft-clipped by the aligner);
    - 36 carry Illumina primer/adapter sequence;
    - 90 clips are too short to classify;
    - most of the remaining 90 recurrent motifs map to the chr21 ribosomal-RNA array (rRNA chimeras; rRNA is about 9%
      of this library).
  - SHANK2 itself is highly expressed in malignant nuclei (~2,900 CPM), but the fusion junction is the question.
- **MSH6 splice junction (W9):** reproduced in our tumor RNA. The reported 56-nt intron has 200 junction reads
  against 3,933 unspliced, about 5%, versus Serova's 4.4%. Whether it also occurs in normal tissue was not resolved
  here (Serova also has no normal RNA).

## 3. Other claims

| Claim | Our evidence | Status |
|---|---|---|
| Purity 0.37 / ploidy 2.4 (ASCAT) | Purity 0.35 (0.32–0.39), ploidy ~2.8 with likely WGD; a FACETS alternative reproduces 0.37/2.5; H&E ~30% tumor nuclei | Purity agrees; ploidy differs |
| TMB 3 /Mb | 6.1 /Mb genome-wide consensus; ~3.7 /Mb clonal-looking | Definition-dependent; consistent |
| Tumour DNA and RNA fresh-frozen; no fixation-artefact flag | Mutect2 filtered 21.8% of WGS records as orientation artefacts; the dated block is FFPE (ledger) | Conflicts with our data; needs specimen confirmation |
| B2M single-copy loss | B2M 1:0 in every plausible fit; 30.6-Mb somatic deletion | Confirmed |
| HLA allele loss unresolved | No clonal loss of either HLA haplotype; HLA-A lowest minor CN (~0.6–1.0); subclonal loss not excluded | Partially resolved; typing still unaccredited |
| APM low vs normal breast (TAP2 0.05x, B2M 0.17x, PSMB8 0.25x, PSMB9 0.26x, IRF1 0.27x) | Bulk RNA is capture (panel genes inflated ~3.4x) from a tumor-poor specimen, so magnitudes are unreliable. In KH022 malignant vs normal-epithelial nuclei, TAP1 0.37–0.47x, TAP2 0.30–0.62x, PSMB8 0.33–0.63x, PSMB9 0.26–0.42x, NLRC5 0.28–0.37x, IRF1 0.38–0.54x, ERAP2 0.27–0.31x (B2M/HLA ~0.3x but ambient-confounded) | Direction supported at tumor-cell level; magnitude milder |
| Clonality: 8 windows at full CCF, 14 at CCF 0.43 | Not re-derived window by window; our fit is 64% clonal-looking SNVs overall; TAF4B ~94% mutant molecules in malignant nuclei | Open |
| Board "exclude" windows retained without override | Vendor's own record | Question for vendor |

## 4. Not in the cassette (factual)

Our confirmed truncal drivers TP53 c.559+2T>G (all retained copies mutant) and BRCA1 c.81-1G>A (biallelic; ~83%
aberrant exon-3 acceptor splicing, documented junctions in step 4) are splice variants, not missense, and are not
encoded.

## 5. Questions for Serova and the clinical team

1. SHANK2 (W8): what partner and junction sequence did the fusion caller report? Our read-level review attributes
   the clipped reads to soft-clipped normal splicing, adapters and rRNA chimeras, with no DNA breakpoint.
2. NCKAP1 (W7/W15/W18): with no RNA junction reads, what evidence shows the duplicated sequence is transcribed and
   translated? These windows also carry 21 of the cassette's 29 strong self-binders (vendor's own screen).
3. Specimen: their report says fresh-frozen T0. Which specimen and date? Our WGS shows a strong orientation-artefact
   signature and the dated block is FFPE.
4. REST RNA fraction: 1.4% (construct text and Fig. 4) or 23% (read-evidence page)?
5. Windows whose genes are barely expressed in malignant nuclei of a second specimen (TP63, PTPRH, MAST1, TAC4,
   APEH, SDC3, SLC46A3), and windows with exome-only DNA support (MAST1, RABL6, SDC3, NUMA1): how were expression
   and tissue heterogeneity weighed?
6. HLA: plan for accredited typing; our copy-number data find no clonal loss of either haplotype, with HLA-A the
   weakest region. Will they run an allele-specific (e.g. LOHHLA-type) assessment on the final genotype?
7. MSH6 junction: is it present in normal-tissue RNA references?
8. Were splice-derived neoantigens from TP53 c.559+2T>G or the BRCA1 aberrant transcripts evaluated?
9. The four board-"exclude" windows: what was the rationale for keeping them?

Limitations: KH022 is a different specimen; single-nucleus 3' coverage is sparse; bulk RNA is a capture library from
a tumor-poor region; no normal RNA; HLA region mapping is error-prone.

## 6. What the single-nucleus data change (summary, 2026-10-04)

Evidence for discussion with Serova and the clinical team, not a design judgment. KH022 is a different, undated
specimen (possibly another timepoint). It is nuclei-based 3' data, so some sites are not covered.

- **Second-specimen confirmation:** mutant molecules are seen in malignant nuclei for 14 of 22 missense windows
  (e.g. TAF4B ~94% mutant), which supports their presence beyond the T0 piece.
- **Drivers absent from the cassette are active in tumor cells:** BRCA1 pre-mRNA in malignant nuclei is 97% mutant
  (100/103). TP53 c.559+2 and the BRCA1 splice products are real but are not encoded. Were splice-derived antigens
  evaluated?
- **Antigen processing is reduced in tumor cells, more mildly than the vendor's bulk estimate:** TAP1/2, PSMB8/9,
  NLRC5, IRF1 and ERAP2 at 0.3-0.6x of normal breast epithelium (vendor 0.05-0.27x from capture, tumor-poor bulk RNA).
  The direction matches the vendor's "low interferon" reading.
- **Several window genes are barely expressed in tumor nuclei:** TP63 (expressed in myoepithelial cells, not tumor),
  PTPRH, MAST1, TAC4, SDC3 and SLC46A3. Nuclear RNA is not protein, and low detection is not proof of absence.
- **SHANK2 expression is high because 11q13 is amplified (~9 copies),** but the encoded fusion junction is
  unsupported (section 2).
- **HLA/B2M presentation cannot be measured per nucleus** (ambient-dominated). Combined with DNA, there is no clonal
  HLA haplotype loss; HLA-A is the weakest region.
- **Immune context:** pathologist sTIL 50%, with T/NK, B/plasma cells and macrophages present in the nuclei data.
