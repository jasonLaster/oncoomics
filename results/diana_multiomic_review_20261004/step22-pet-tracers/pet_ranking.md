# PET tracers: which ones Diana's tumour biology supports (private, 2026-10-09)

**Status.** Research prioritization to discuss with her oncology and nuclear-medicine team. It is not a recommendation to
image or treat. Most tracers below are available only in trials, and none replaces standard staging.

**Inputs**
- **Her biology:** step 22 re-run on Yuga's QC'd KH022 nuclei (`pet_biology.csv`, `tme_vs_public.csv`).
- **Protein:** the OncoOmicsDx panel (step 19 m5). These are microdissected tumour-area proteins from the same 4/10
  biopsy event.
- **Literature:** `tracer_evidence.csv` / `.md`. Every PMID abstract was read, and the key titles were re-checked
  against PubMed.

**How to read the evidence.** PET needs **target protein** on the cell surface (or retained tracer) at high density,
relative to the tissue around the lesion. Her nuclear RNA tells us which cells make the target and how she compares
with other TNBC tumours. Step 19 showed RNA presence and absence agrees with protein, but RNA *levels* do not
(rho 0.17). So each "her data" call below is graded, and the cheap confirmatory test is named.

## Ranking

| # | Tracer (target) | Her tumour data | Human breast / TNBC evidence | Fit |
|---|---|---|---|---|
| 0 | **18F-FDG** (glucose metabolism) | Ki67 40-50%; about 1 in 3 tumour nuclei in a cycling phase. Glycolysis RNA in nuclei is not informative. | Standard of care. TNBC is typically FDG-avid. An early drop in SUV during neoadjuvant therapy predicts pCR. | **Baseline that every other tracer must beat** |
| 1 | **68Ga-FZ-NR-1 (Nectin-4)**; dual Nectin-4/FAP probe 68Ga-FZ-NF-1 | RNA in 29% of tumour nuclei, uniform across subclones. Her level is **typical TNBC** (atlas fold 0.96; HTAPP 0.55x) and close to her normal luminal cells (1.2x), but normal breast is mostly fat. Not on the protein panel. | Best **TNBC-specific** data: 40 patients with recurrent or metastatic TNBC, sensitivity 98% vs 93% and specificity 69% vs 27% against FDG (PMID 42730763). A 225Ac therapy partner is in phase 1b with a TNBC cohort. The dual Nectin-4/FAP probe was first tested in 13 TNBC patients: uptake comparable to FDG, plus extra lesions (42711843; its therapy data are from mice). This fits her, since Nectin-4 is in tumour cells and FAP is in CAFs. | **Strong.** Her expression matches the cohort in which it worked. |
| 2 | **68Ga-MY6349 (TROP-2)** | **Protein high: 1,705 amol/µg**, the 7th highest of 26 detected proteins and 10x EGFR. Nuclear RNA is low and mostly ambient. TACSTD2 is a single-exon gene, which nuclei under-capture, so RNA understates it. | 73 breast patients: more lesions found and fewer false positives than FDG (42559486), plus three other tracer cohorts. No human TROP-2 radioligand therapy yet. | **Strong**, carried by protein. Confirm tumour-cell membrane IHC, because the microdissected sample includes stroma. |
| 3 | **PSMA PET** (68Ga-PSMA-11, 18F-piflufolastat; FDA-approved for prostate) (FOLH1) | **Unusual:** PSMA RNA sits in **tumour cells**, at 30-39x the typical TNBC tumour cell (100th percentile vs 118 whole-cell and 11 nuclei references). Present in 53% of tumour nuclei, with heterogeneity: 27% in subclone CNV-3. Endothelial PSMA is typical. Her normal luminal cells also express it (tumour/normal 1.5x). | Weak in TNBC overall, because breast PSMA is usually vascular only: PRISMA (20 patients, half above liver), and an 18F-PSMA-1007 study where no patient met the threshold for radioligand therapy. 177Lu-PSMA in breast: a single case report. | **Conditional, potentially high.** She may be the exception the cohorts lacked. **PSMA IHC on the 4/10 block decides it.** Accessible tracers; theranostic partner exists. |
| 4 | **FAPI PET** (68Ga-FAPI-46 / 18F-FAPI-74) (FAP) | FAP is in CAFs, which are 9% of nuclei (55th percentile vs TNBC nuclei biopsies). Per-CAF FAP is 99th percentile vs whole-cell references but 0th vs nuclei references, so call it typical. | Largest breast data: 50, 22 (TNBC), 38 and 66 patients. Tumour SUV is about 2x FDG, but detection gains are mostly not significant. 177Lu-FAP-2286 has finished phase 1. | **Good generic choice.** Biopsy and surgical healing and treatment-related fibrosis also light up, so timing matters. |
| 5 | **18F-FluorThanatrace** (PARP1) | RNA in 34% of tumour nuclei. **Not clearly elevated, and the references disagree:** 0.22-0.51x vs whole-cell TNBC (these comparisons depend on the fragile bias model), but above all 11 HTAPP nuclei biopsies (1.6x, like-for-like). B cells and plasma cells express it at similar levels. | Uptake tracks PARP-1 protein and is linked to PFS on PARP inhibitors (34 breast patients; a separate study of 7 patients with a germline BRCA variant). It does not measure HRD. | **Medium-low.** Relevant only if the question is PARP target binding. Her BRCA1 loss does not raise PARP1. |
| 6 | **CD8 immunoPET** (89Zr-crefmirlimab) | T cells are 14% of nuclei (82nd percentile vs TNBC nuclei biopsies; sTIL 50% on H&E). CD8 is a minority within them (library 1: CD4 2,030 vs CD8 1,177 nuclei). | Pan-tumour only (49 patients; PET vs IHC r 0.49). No breast data. | **Research only.** Possibly interesting for immunotherapy response, but unproven. |

## Low fit or ruled out by her data

| Target / tracer | Her data | Why it is ruled out |
|---|---|---|
| PD-L1 PET | Tumour RNA about 0; myeloid only. Protein ND. | In a 3-patient TNBC study, PET-avid lesions were IHC-negative. |
| HER2 PET | IHC 0, protein ND, low RNA. | |
| FES / FFNP | ER and PR negative. | |
| αvβ6 (trivehexin) | Higher in her **normal** luminal cells than in tumour (ITGB6 0.07x). | |
| CA-IX (89Zr-girentuximab) | RNA essentially absent (0.04% of tumour nuclei). | A hypoxic region could be missed by one core, but there is no support. |
| B7-H3 | RNA low and typical. | |
| EGFR | Mostly in stromal and fat cells. | No breast PET data. |
| Integrin αvβ8 (68Ga-Triveoctin) | ITGB8 in 60% of tumour nuclei, but **higher** in her pericytes (347 vs 179 CPM) and normal luminal cells (213), and 0.6x vs HTAPP nuclei. | Human data are one biodistribution subject (33128636). |
| CXCR4, uPAR | Immune-cell targets; her levels are low vs references. | |
| GRPR, SSTR2 | | Uptake tracks ER positivity. |
| CD44 immunoPET | Expressed on immune and normal cells too. | Large normal-organ sink. |
| 18F-fluciclovine | LAT1 and ASCT2 RNA low-typical. | Could still be avid; low priority. |
| 18F-FSPG (xCT) | | Weak breast data. |

**Her strongest tumour-cell outliers have no usable tracer:**
- **SLC6A14**: 91% of tumour nuclei; 23x TNBC; 7x her normal epithelium.
  - AMT PET does not measure it, because α-methyltryptophan *blocks* ATB0,+ (PMID 18522536).
  - Selective probes such as [18F]FEMAET are preclinical.
- **SLC28A3 (CNT3)**: FLT can use CNT3, but cancer-cell uptake runs mainly through ENT1 (18669604). Her tumour ENT1 RNA
  is low, so FLT is not specifically favoured.
- **ENPP3, HORMAD1, KIF18A, POLQ**: no PET or SPECT agent exists.
- If imaging agents against SLC6A14 or ENPP3 appear, she would be an unusually strong candidate.

## Cheapest decisive next step

Run IHC on the 4/10 FFPE block (SP-26-027487) for **PSMA, TROP-2 and Nectin-4**, adding FAP if FAPI is under
consideration. Score tumour-cell membrane staining separately from vessels and stroma.
- PSMA is the swing call: tumour-cell membrane PSMA would move it from "weak in TNBC" to a possible
  imaging-plus-therapy target.
- TROP-2 and Nectin-4 IHC would confirm the two best-evidenced TNBC tracers.

## Comparison with an earlier same-day screen (Codex; not published)

That screen ranked Nectin-4 > PSMA > FAP > TROP-2 > PARP1 > EGFR on tumour-nucleus RNA detection alone. This analysis
changes it in five ways:
1. **TROP-2 moves up** on protein evidence, because nuclear RNA under-captures this single-exon gene.
2. **PSMA becomes conditional.** Her tumour-cell expression is exceptional vs other TNBC, but the published TNBC
   cohorts failed because breast PSMA is usually vascular.
3. **PARP1 stays mid-to-low.** An earlier draft of this note called it "low vs other TNBC". That was an overstatement: nuclei-to-nuclei comparison puts it at about 1.6x (step 22 audit).
4. **EGFR drops out.** Its RNA is mostly stromal and fat, and there is no breast PET data.
5. **AMT and FLT are not routes to her SLC6A14 or SLC28A3 outliers.**

## Caveats

- One biopsy and one time point (day 8 of KEYNOTE-522 chemo-immunotherapy). Treatment may change target expression.
- Nuclei are not whole cells. Protein data exist for TROP-2 and EGFR (detected) and for PD-L1 and HER2 (ND) only.
- Most novel-tracer cohorts are single-centre with n ≤ 75 and from 2025-26, and not yet replicated.
- Lesion-to-background for liver, bone or nodal disease depends on each tracer's normal biodistribution (see
  `tracer_evidence.csv`, background_organs), not on the breast data.
