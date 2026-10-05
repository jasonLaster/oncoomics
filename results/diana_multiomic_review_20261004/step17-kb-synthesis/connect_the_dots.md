# Connecting the dots: the knowledge base and the omics review (step 17)

Diana multi-omic review · 2026-10-04 · research hypotheses for discussion with the oncology team, not treatment recommendations.

**Inputs**
- Four readers covered the family knowledge base (`~/src/projects/diana-tnbc`): clinical/imaging timeline (A), lab and
  genomic reports (B), literature/ASCO/trials (C), and wiki beliefs vs evidence (D). Their full reports stay in private storage.
- Each was briefed with our verified findings (`findings_brief.md`).
- I spot-checked the load-bearing claims against primary files and our data; the checks are listed at the end.

---

## The short version

1. **This is a pregnancy-associated TNBC, and none of our omics work accounted for it.**
   - Diana was about 9 weeks pregnant at diagnosis. The pregnancy ended about 3/25, and treatment started 4/2.
   - It may contribute to three findings we had treated as tumor-intrinsic: the luminal-progenitor
     (ELF5/PRLR/ERBB4) tumor state, the IgA-dominant plasma-cell infiltrate, and part of the MRI "response".
   - Update (step 18): the luminal-progenitor master regulators ELF5 and EHF sit on a 9-copy DNA segment next to the
     CD44 amplicon, so that state is at least partly genetic. Casein in the single-nucleus data turned out to be
     background RNA, not tumor expression.
2. **The datasets come from two biopsy events, and most of the tumor-cell and immune data are on-treatment.**
   - **3/13 block (pregnant, untreated):** WGS, Altera, Signatera and NeXT Personal.
   - **4/10 core (day 8 of chemo-immunotherapy, the morning after the second carboplatin/paclitaxel):** exome/RNA,
     proteomics, the 50% sTIL score and very likely the single-nucleus sample.
   - So "baseline immune state" has never been measured.
3. **The DNA-repair programme in the tumor cells is specific, not proliferation.**
   - POLQ, ATR, HORMAD1, RAD51, BRCA2, BLM and FANCD2 are up versus other TNBC tumor cells.
   - Proliferation genes are typical or low, and p21 is about 20x lower than in other TNBC tumor cells, which fits
     TP53 loss.
   - That strengthens the HRD/POLQ/ATR axis. Carboplatin-induced transcription remains the main alternative.
4. **The three amplicons are physically one structure.** Junctions in the WGS join 11q13 to 22q12, and CD44 (11p13) to
   11q13. The expressed driver candidates in it are SHANK2, PPFIA1, CTTN and CD44, not CCND1.
5. **The trial the family filtered out may fit better than the one they searched for.**
   - The BLUESTAR arm pairs a B7-H4 ADC with a PARP inhibitor. It was set aside because it does not target TROP-2.
   - B7-H4 is tumor-enriched in Diana's cells, TROP-2 is only typical, and HRD is verified.
   - That arm is for advanced disease, so it is relevant mainly as a reference point.
   - Caution (step 18): B7-H4 is about as high in her normal duct cells as in tumor, so on-target, off-tumor effects
     need weighing.
6. **Immune escape: "hot stroma, quiet tumor cells, one hit from invisible".**
   - B2M is single-copy and the antigen-processing genes are low in tumor cells.
   - In the corpus there is a TNBC vaccine patient who relapsed by losing B2M.
   - Putting the remaining B2M allele on ctDNA monitoring is a cheap early warning.

---

## 1. Pregnancy: a single explanation for three "odd" findings

**Facts (verified).**
- The KB wiki records the pregnancy and the termination around 3/25 (`wiki/updates/week-1-march-13-21.md`,
  `week-2-march-22-28.md`).
- Stanford's 4/10 pathology history line calls it "pregnancy-associated triple-negative".
- hCG was 1,472 IU/L on 4/2, falling to 3 by 5/26.

**What our data show (checked today).**
- **Milk protein (corrected in step 18):** CSN3 (casein-kappa) appears in 99% of malignant nuclei, but empty droplets
  contain more of it (3,790-5,460 CPM) than any cell type, and β-casein and α-lactalbumin are absent. It is background
  RNA and says nothing about the tumor cells.
- **Tumor-intrinsic programme:** the following genes have low ambient share (<0.12) and are at least 4x higher than in
  non-malignant nuclei.

  | Gene | Excess vs public TNBC | Gene | Excess vs public TNBC |
  |---|---|---|---|
  | ERBB4 | ~77x | ELF5 | ~8x |
  | ESRRG | ~60x | XDH (milk-fat) | ~12x |
  | MECOM | ~50x | PRLR | ~3x |
  | EHF | ~20x | | |

  This is the alveolar programme that pregnancy hormones expand. But ELF5 and EHF are on a 9-copy segment
  (chr11:34.4-35.1 Mb, 6:3) adjacent to the CD44 amplicon, so their high expression is at least partly genetic.
  Against her own normal luminal cells, PRLR and ERBB4 are not higher (step 18), so neither is clearly tumor-selective.
- **IgA:** IgA dominates IgG in both bulk RNA and the single-nucleus data. The epithelial chemokine CCL28 is expressed;
  it is linked in the literature to IgA plasma-cell homing to the lactating gland.

**Two readings, not mutually exclusive.**
- **(a) Cell of origin:** BRCA1-null tumors arise from luminal progenitors, so the state is intrinsic.
- **(b) Hormonal state:** the state was induced by the pregnancy and should fade after termination and Lupron.

**Why it matters.**
- If (b), PRLR- or ERBB4-directed ideas lose their driver over time. Either way, step 18 finds neither clearly above her
  normal luminal cells.
- The IgA infiltrate may be gestational and involution physiology rather than an anti-tumor response.
- The 50% sTIL score, taken at day 8 post-pregnancy and on treatment, may overstate cytotoxic engagement.

**Corpus link.**
- The only lineage vaccine in the KB targets α-lactalbumin (NCT04674306).
- LALBA is essentially absent from Diana's tumor nuclei (0.19 CPM, 0% of nuclei). That premise is not supported here.

**Cheapest test.** Compare ELF5, PRLR, ERBB4 and IgA/IgG in the **9/24 surgical tissue** (six months after the
pregnancy) against the 4/10 core.
- **If the state persists:** it reflects cell of origin.
- **If it fades:** it was hormonal.
- Requesting the Altera 3/13 RNA raw data would add the in-pregnancy, untreated timepoint.

## 2. Specimen map: what each result actually describes

| Specimen | Treatment and pregnancy state | Datasets |
|---|---|---|
| 3/13 Sutter `SUS-26-01600` block A2 | Pregnant (~8 wk), untreated | Altera; Signatera and NeXT Personal panels; **our WGS** (NeXT accession `PSN49561A2` = WGS `DRF-PSN49561`) |
| 3/23 Stanford node `SP-26-022231` | Pregnant, untreated | HistoWiz node sTIL 10% |
| 4/10 Stanford core `SP-26-027487` | 16 d after termination; day 8 after pembrolizumab #1; the morning after carboplatin/paclitaxel #2 | Personalis exome/RNA (Echo requested this block on 6/10 with the E019 form; Personalis returned its DNA/RNA extractions and the block to Kernis); **proteomics** (`SP-26-027487-BR-VL3-A1`, header "3/13 Sutter" is wrong); HistoWiz breast sTIL 50%; Ki67 61-70%; **KH022 snRNA** (medium-high confidence: Kernis customer ID, flash-frozen 4/10 vials, breast composition) |

**Consequences.**
- **The ~10% subclone in Altera and WGS but absent from the exome is explained:** the WGS and Altera came from the same
  physical block, while the exome came from a different needle pass four weeks later.
- **Every immune readout is on-treatment** (sTIL 50%, IgA, low antigen processing, PD-L1 not detected). The untreated
  3/13 breast slide has never been scored for sTIL.
- **Breast vs node sTIL (50% vs 10%)** compares on-treatment post-pregnancy breast against pregnant untreated node. It
  is not a like-for-like contrast.
- **Our own ledger is wrong in two places:** step 1 calls 3/13 the anchor specimen, and step 12 treats the proteomics
  as pre-treatment. These need correcting.
- **HER2:** Stanford 4/10 scored "Negative (Score 0)" with the qualifier "0+ / with membrane staining". That is the
  **HER2-ultralow** category, so our "HER2 IHC 0 / ISH 0" should read "HER2 0 (ultralow on the 4/10 core)". Proteomics
  HER2 was not detected.

## 3. The DNA-repair programme is specific (new analysis today)

Diana's malignant nuclei compared with tumor cells of 8 public TNBC, chemistry-corrected:

| Higher than other TNBC tumor cells | Excess | Typical or lower | Excess |
|---|---|---|---|
| HORMAD1 | ~27x (8/8) | MKI67 | ~0.9x |
| POLQ | ~10x (8/8) | TOP2A | ~0.6x |
| ATR | ~5x (8/8) | CDK1 / CCNB1 / PCNA | ~0.5x |
| RAD51 | ~3x (8/8) | WEE1 / CHEK1 | ~0.5x / ~1.1x |
| BRCA2, BLM, FANCD2 | ~3x (5-6/8) | **CDKN1A (p21)** | **~0.05x** |

**Reading.**
- Reader A suspected the POLQ/ATR signal came from paclitaxel mitotic arrest 24 h after a dose. It did not:
  proliferation genes are not raised.
- The pattern is an HR-deficient tumor up-regulating its backup end-joining and replication-stress machinery:
  - POLQ: microhomology-mediated end joining (60% of large deletions carry microhomology);
  - ATR: replication-stress checkpoint;
  - HORMAD1: a meiotic protein linked to HR-deficient TNBC and to carboplatin resistance in a BRCA1 PDX.
- Near-absent p21 is a functional readout of the TP53 splice allele.

**Remaining alternative.** Carboplatin 24 h earlier may have induced DNA-damage-response transcription. HORMAD1 is
usually activated epigenetically rather than by damage, which argues against this for HORMAD1.

**Test.** POLQ, ATR and HORMAD1 in the 3/13 untreated RNA (Altera raw data) and in the surgical residuum.

**Connected hypotheses from the corpus.** These are research hypotheses, mostly preclinical or early-clinical.
- POLQ inhibitor plus PARP inhibitor. NCT07156253 (SYN818 + olaparib) accepts HRD as well as BRCA and includes HER2-
  breast. It is for advanced disease.
- **SLFN11 is low and ATR is high in tumor cells.**
  - This combination is published as a route to resistance to TOP1-payload ADCs (sacituzumab, Dato-DXd).
  - ATR inhibition is the published way to re-sensitize such cells.
  - This is a caution for TOP1-ADC expectations, not a gate.
- **HORMAD1 as an antigen:** a cancer-testis antigen in 53% of tumor nuclei. It is a non-mutated, potentially shared
  vaccine antigen, if the HLA typing supports binders.

## 4. BRCA1: near-null, and what escape would look like

- **Every observed mutant transcript truncates within the first ~30 codons.**
  - This includes exon-3 skipping, which looks in-frame by length.
  - The joint TG|A creates p.Cys27* (step 4), so reader D's "in-frame RING deletion" is incorrect.
- **"Exon-11 escape" does not apply.**
- **Plausible escapes, from the corpus and published literature:**
  - re-initiation downstream to make a RING-less protein. Only mild PARP-inhibitor resistance was reported in cell
    lines (Irving 2025, in corpus).
  - a POLQ-mediated reversion deletion that restores the acceptor or the reading frame.
- **This supports the KB's PARP lane** (Esserman, Munster, Vahdat), which now rests on much stronger evidence than the
  untraceable "HRD 62".
- **Tests:**
  - RAD51 foci (intoDNA) on residual tumor.
  - N- vs C-terminal BRCA1 IHC.
  - Long-read exon 2-5 cDNA from residual tumor.
  - A BRCA1 exon-3 reversion assay added to ctDNA monitoring.

## 5. One composite amplicon (11q13 + 22q12 + CD44)

- **Our Manta WGS calls contain four PASS chr11-chr22 junctions**, each sitting on a copy-number step:
  - 69,117,506 to chr22:37.74 Mb;
  - 69,282,452 to chr22:29.05 Mb;
  - 69,540,177 to chr22:25.16 Mb;
  - 71,796,556 to chr22:31.50 Mb.
- **A further junction joins the CD44 amplicon edge** (chr11:36,269,951) to the 11q13 gain edge (75.13 Mb).
- **So these behave as one structure,** probably a breakage-fusion-bridge or extrachromosomal unit.
- **Altera's named genes (DHCR7, FADD, NADSYN1, ORAOV1) are inside it,** but DHCR7 and FADD are not over-expressed.
- **The expressed genes** are SHANK2 (~2,900 CPM), PPFIA1, CTTN, NADSYN1 and CD44.
- **CCND1 is not over-expressed,** and p16 protein is expressed. Both argue against a CDK4/6 rationale.
- **Why it matters:**
  - If the amplicon is extrachromosomal, CD44 copy number may vary cell to cell and change under treatment.
  - CD44 (12 copies) remains the only surface target concordant on every axis, and it is HLA-independent.
- **Tests:**
  - AmpliconArchitect on the WGS (local, cheap).
  - Per-nucleus copy-number heterogeneity of the amplicon in KH022.
  - CD44v6 isoform junction reads in the bulk RNA.

## 6. Immune state: hot stroma, quiet tumor cells

**Converging facts.**
- sTIL 50% (on-treatment).
- IgA plasma cells and macrophages dominate.
- CXCL12 is high from fibroblasts and endothelium. CXCL12 is the classic plasma-cell retention chemokine, also linked
  to CD8 exclusion.
- Tumor cells:
  - PD-L1 protein not detected;
  - antigen-processing genes at 0.3-0.6x;
  - B2M single-copy.
- **The 6/10 granzyme-B research PET showed no focal uptake** in breast or nodes, despite signs of systemic immune
  activation (bilateral reactive nodes, possible pneumonitis). Low confidence: it was taken at week 10, when ctDNA was
  near zero.
- **A speculative mechanism from the corpus:** ELF5 drives degradation of the IFN-γ receptor (IFNGR1). This would link
  the pregnancy/luminal-progenitor state to the low interferon-driven antigen processing, even though JAK/STAT genes
  are intact. If true, the pregnancy-induced state would also be an immune-evasion state.

**Implications for the vaccine.**
- **B2M:** Serova's 9/3 comment ("B2M within normal range") misses the fact that B2M is down to one copy.
- **HLA typing:** Serova's typing is unaccredited and conflicted with an earlier typing at the A and B genes, which
  present 24 of the 27 windows. No clinical HLA typing exists in the KB.

**Tests.**
- B2M and HLA-I IHC on residual tumor.
- Accredited HLA typing (OptiType or arcasHLA on our normal WGS as a free first check).
- Put the remaining B2M allele on ctDNA monitoring.
- Spatial: CD8-to-tumor distance vs CXCL12+ fibroblasts; IgA vs IgG plasma cells by region.

## 7. Imaging and response, reconsidered

- **Low tumor density:**
  - Diffuse non-mass enhancement (87 mm) together with low FDG (SUVmax 4.1), low ctDNA (tumor fraction 0.3%) and purity
    0.35 describe a sparse, diffusely infiltrating tumor in a pregnancy-proliferated gland.
  - The "8.7 cm" extent probably overstates the tumor cell mass. Medium-low confidence.
- **Part of the MRI response is physiological:**
  - The left (non-cancer) breast's enhancement fell from 125% to 24% over the same period.
  - A right-minus-left normalized trajectory would isolate the tumor-specific part.
- **Response was front-loaded:**
  - Most change happened by 6/26 (carboplatin phase), then plateaued at 57 mm through 8/24.
  - That fits HRD platinum sensitivity followed by a truncated AC phase.
  - Whether the plateau is residual tumor or scar is for surgical pathology (RCB) to decide.
- **ctDNA is counted in single molecules:**
  - Signatera values correspond to about 9, then 5, then about 2 molecules.
  - The 4/3 Guardant tumor fraction (0.3%) may be inflated by residual placental cfDNA (hCG 1,472 at the time). Low
    confidence.

## 8. Corrections to carry into the KB and our reports

| Item | Correction |
|---|---|
| "HRD 62" | Replace with "HRD-high across fits (67-99), research grade". Not Altera. |
| TP53 c.559+2T>G | Already in Altera's trials table and Guardant (4/3). Our pipeline confirmed it; it did not discover it. |
| HER2 | Ultralow wording on the 4/10 core ("0+ with membrane staining"), not plain 0. |
| Proteomics date | 4/10 Stanford core (on-treatment), not 3/13 pre-treatment. |
| SLFN11 "discordance" | Resolved: tumor cells are SLFN11-low, and the high bulk signal was stroma. |
| VIM "mesenchymal" | Stromal, not tumor EMT. |
| ADC atlas queue (HER3/MET/EGFR) | Capture-library artifact. Replace with B7-H4, PSMA, CD44, ENPP3, PRLR, HORMAD1, pending IHC. |
| Altera fusions | 5/11 reproduce in WGS. PTPN2 break is probably one copy only. IGKV::IGKJ is normal antibody rearrangement. A2M, PAX3, FNBP1L::FAM129A not supported. |
| PD-L1 CPS | Never resulted. |
| hENT1 / TYMP proteomics labels | Mostly from stroma in this tumor; the tumor's nucleoside transporter is CNT3 (not on the panel). |

## 9. Ranked next steps (value of information per cost)

1. **Surgical-specimen panel (9/24 tissue, one block, many questions):**
   - RCB per region, with radiology-pathology mapping of the non-mass enhancement.
   - RAD51 foci.
   - B2M/HLA-I.
   - B7-H4, CD44, PSMA (tumor vs vessel), TROP-2 membrane.
   - ELF5/PRLR and IgA/IgG (the pregnancy test).
   - SLFN11 (tumor vs stroma).
   - BRCA1 re-sequencing for reversions.
2. **Free, local, computational:**
   - HLA typing from our normal WGS/exome.
   - AmpliconArchitect on the WGS.
   - Per-nucleus amplicon heterogeneity.
   - CD44v6 junction reads.
   - Genotype the 9 subclonal SNVs in KH022, which would confirm its specimen.
   - Right-minus-left MRI kinetics.
3. **Records to request (no tissue needed):**
   - Altera 3/13 RNA raw data (the untreated, in-pregnancy timepoint).
   - Kernis/Signios KH022 manifest.
   - OncoOmics corrected requisition.
   - Altera final PD-L1 report.
   - Guardant VUS page and HGVS.
   - HistoWiz sTIL on the 3/13 breast slide.
4. **For the vaccine conversation:**
   - Accredited HLA typing before manufacture.
   - Drop the SHANK2 window.
   - Ask about the truncal TP53/BRCA1 splice junctions and HORMAD1.
   - B2M second-hit monitoring.

## Verification log (what I checked myself)

- **Pregnancy:** confirmed in the KB weekly updates and the Stanford history line ("pregnancy-associated").
- **Casein and luminal-progenitor genes:** recomputed from `step15-tnbc-outliers/tumor_cells_vs_public_tnbc.csv.gz`.
- **LALBA:** absent in tumor nuclei (0.19 CPM, 0%).
- **HER2 wording:** read in the Stanford 4/10 report (`04-10-kernis-path-report.md` lines 80-81).
- **chr11-chr22 and CD44-11q13 junctions:** confirmed in `step8-wgs-somatic/results/cloud/manta/somaticSV.vcf.gz` at
  the stated positions.
- **BRCA1 exon-3 skip = p.Cys27*:** confirmed in the step 4 report. This corrects reader D.
- **DNA-repair vs proliferation table:** computed today from the step 15 table.
- **Not independently re-checked:**
  - KH022 = 4/10 (an inference from the KB; needs the manifest);
  - the Signatera molecule arithmetic;
  - the corpus paper claims marked "outside corpus" in reader C.
