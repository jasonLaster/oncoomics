# Target-specific PET tracers relevant to TNBC: evidence summary

Companion to `tracer_evidence.csv`. This is a literature evidence table for **research prioritization only**. It is not a clinical recommendation. Only generic literature and registry queries were used, and no patient-level information is included.

Sources (checked 2026-10-09):
- Local PubMed XML and ClinicalTrials.gov API captures (not published)
- Live PubMed E-utilities (abstracts read for every PMID cited)
- ClinicalTrials.gov API v2
- Targeted web searches for regulatory status

Anything not confirmed from a primary abstract or registry record is marked UNVERIFIED in the CSV.

## Strongest human breast/TNBC evidence (ranked)

1. **FAP (FAPI PET).** This target has the largest breast datasets.
   - Prospective 68Ga-FAPI vs FDG in 50 patients: primary-lesion SUVmax 13.3 vs 6.9; management changed in 12% ([PMID 42710423](https://pubmed.ncbi.nlm.nih.gov/42710423/)).
   - TNBC subgroup of 22 patients: detection 93% vs 93% ([42618586](https://pubmed.ncbi.nlm.nih.gov/42618586/)).
   - 18F-FAPI staging in 38 patients ([39242298](https://pubmed.ncbi.nlm.nih.gov/39242298/)) and NAC monitoring in 66 patients ([41904503](https://pubmed.ncbi.nlm.nih.gov/41904503/)).
   - Theranostic partner: 177Lu-FAP-2286. Phase 1 of LuMIERE treated 27 patients and set the RP2D at 9.25 GBq ([42223513](https://pubmed.ncbi.nlm.nih.gov/42223513/)).
   - Caveat: FAP is a stromal target, and scars and fibrosis also take up the tracer.
2. **TROP-2.**
   - 68Ga-MY6349 in 73 breast patients: 564 vs 436 lesions and 2 vs 40 false positives compared with FDG ([42559486](https://pubmed.ncbi.nlm.nih.gov/42559486/)).
   - Pan-cancer cohort: breast SUVmax 7.2 vs FDG 5.4, with uptake tracking IHC ([39509246](https://pubmed.ncbi.nlm.nih.gov/39509246/)).
   - 68Ga-NOTA-T4 in 42 patients ([41781717](https://pubmed.ncbi.nlm.nih.gov/41781717/)) and 18F-RESCA-RT4 in 35 patients ([42134979](https://pubmed.ncbi.nlm.nih.gov/42134979/)).
   - 89Zr-sacituzumab is **preclinical only** ([39878898](https://pubmed.ncbi.nlm.nih.gov/39878898/)).
   - No human TROP-2 radioligand therapy was found.
3. **Nectin-4.** This target has the strongest **TNBC-specific** cohort.
   - 68Ga-FZ-NR-1 vs FDG in 40 patients with recurrent or metastatic TNBC: sensitivity 98.1% vs 93.5% and specificity 68.6% vs 27.5% ([42730763](https://pubmed.ncbi.nlm.nih.gov/42730763/)).
   - Earlier work: first-in-human study in 9 TNBC patients ([39947908](https://pubmed.ncbi.nlm.nih.gov/39947908/)) and 68Ga-N188 in 62 patients across 16 cancer types ([38719240](https://pubmed.ncbi.nlm.nih.gov/38719240/)).
   - Theranostic partner: 225Ac-AKY-1189 is in a phase 1b trial with a planned TNBC expansion cohort (NCT07020117). This comes from web and registry sources, not PubMed.
4. **PARP1 (18F-FluorThanatrace).**
   - Uptake correlates with PARP-1 protein ([39477499](https://pubmed.ncbi.nlm.nih.gov/39477499/)).
   - In 24 primary plus 10 metastatic patients on a PARP inhibitor, baseline uptake and its change on treatment correlated with PFS ([40133542](https://pubmed.ncbi.nlm.nih.gov/40133542/)).
   - A talazoparib study in 7 gBRCA patients showed target engagement ([39208372](https://pubmed.ncbi.nlm.nih.gov/39208372/)).
   - 18F-ATD001 was compared with FDG in 37 TNBC patients ([42722436](https://pubmed.ncbi.nlm.nih.gov/42722436/)).
5. **PSMA.**
   - PRISMA, 20 patients with metastatic TNBC: only half had uptake above liver in most lesions, and 65% had at least one lesion below liver ([41309999](https://pubmed.ncbi.nlm.nih.gov/41309999/)).
   - 18F-PSMA-1007 in 20 patients with metastatic TNBC: FDG uptake was higher, and no patient met an SUV threshold for radioligand therapy ([41964062](https://pubmed.ncbi.nlm.nih.gov/41964062/)).
   - Breast PSMA is **predominantly tumour neovasculature**. Endothelium was positive in 74% of primaries and 100% of brain metastases, with no carcinoma-cell staining in 106 cases ([24304465](https://pubmed.ncbi.nlm.nih.gov/24304465/)). In a 315-case series, 60% had positive endothelium, highest in TNBC ([29455299](https://pubmed.ncbi.nlm.nih.gov/29455299/)). One series also reports tumour-cell staining ([29426963](https://pubmed.ncbi.nlm.nih.gov/29426963/)).
   - 177Lu-PSMA in breast cancer: one case report only ([29455299](https://pubmed.ncbi.nlm.nih.gov/29455299/)).

Close behind:
- **CXCR4 (68Ga-pentixafor):** 51 breast patients including 18 TNBC; uptake was higher in TNBC, but SUVmax was 7.3 vs FDG 18.8 ([40075611](https://pubmed.ncbi.nlm.nih.gov/40075611/)).
- **CA-IX (89Zr-girentuximab):** OPALESCENCE, 12 patients with metastatic TNBC, 87.5% lesion sensitivity ([41174094](https://pubmed.ncbi.nlm.nih.gov/41174094/)).

## Baseline and control tracers

- **FDG:** TNBC is typically avid. Mean SUVmax was 6.97 in TNBC vs 3.41 in luminal A ([25947575](https://pubmed.ncbi.nlm.nih.gov/25947575/)).
  - Early SUVmax drop during neoadjuvant therapy predicts pCR and relapse ([22241914](https://pubmed.ncbi.nlm.nih.gov/22241914/), [26697967](https://pubmed.ncbi.nlm.nih.gov/26697967/)).
  - The randomized TNPET01 trial chose FDG over FLT ([42048392](https://pubmed.ncbi.nlm.nih.gov/42048392/)).
- **FES and FFNP** are relevant only as ER/PR negative controls. FFNP data: [22331216](https://pubmed.ncbi.nlm.nih.gov/22331216/), [33531464](https://pubmed.ncbi.nlm.nih.gov/33531464/). FES approval status was not re-checked in this session.
- **HER2:**
  - ZEPHIR, 56 patients ([26598545](https://pubmed.ncbi.nlm.nih.gov/26598545/)).
  - 68Ga-ABY-025 in HER2-low disease: 8 of 10 patients confirmed HER2-low ([38548353](https://pubmed.ncbi.nlm.nih.gov/38548353/)).
  - Earlier 89Zr-trastuzumab "false positives" turned out to be HER2-low lesions ([40341092](https://pubmed.ncbi.nlm.nih.gov/40341092/)).

## Transporter targets

- **SLC6A14 (ATB0,+):** No ATB0,+-selective tracer has been used in humans. [18F]FEMAET is preclinical ([24307544](https://pubmed.ncbi.nlm.nih.gov/24307544/)).
  - AMT PET in 9 breast cancers gave SUV 2.6–9.8 ([22444239](https://pubmed.ncbi.nlm.nih.gov/22444239/)).
  - **However, α-methyltryptophan is an ATB0,+ blocker, not a substrate. 1-methyltryptophan is the substrate** ([18522536](https://pubmed.ncbi.nlm.nih.gov/18522536/)).
- **SLC28A3 (CNT3):** FLT is transported by hENT1, hENT2, hCNT1 and hCNT3, but uptake in cancer cells is mostly through hENT1 ([18669604](https://pubmed.ncbi.nlm.nih.gov/18669604/)).
  - ACRIN 6688 (51 patients in the primary analysis): AUC 0.68 for predicting pCR ([26359256](https://pubmed.ncbi.nlm.nih.gov/26359256/)).
- **Fluciclovine (ASCT2/LAT1):** all 27 locally advanced breast cancers were avid ([26940766](https://pubmed.ncbi.nlm.nih.gov/26940766/)). In an exploratory study, uptake was highest in TNBC and grade 3 tumours ([27056619](https://pubmed.ncbi.nlm.nih.gov/27056619/)).
- **FSPG (xCT):** detected only 41% of FDG-avid breast lesions in 5 breast patients ([22893629](https://pubmed.ncbi.nlm.nih.gov/22893629/)).

## Immune and other targets

- **CD8:** iCorrelate, 49 patients with solid tumours: PET-to-IHC correlation r = 0.49 ([41895717](https://pubmed.ncbi.nlm.nih.gov/41895717/)). **No breast-specific data were found.**
- **PD-L1:** 89Zr-atezolizumab first-in-human study in 22 patients, including some with TNBC ([30478423](https://pubmed.ncbi.nlm.nih.gov/30478423/)). In a 3-patient metastatic TNBC study, 2 of 3 PET-avid lesions were PD-L1-negative on IHC ([41611476](https://pubmed.ncbi.nlm.nih.gov/41611476/)).
- **CD44:** 89Zr-RG7356 showed a large normal-organ sink ([29356983](https://pubmed.ncbi.nlm.nih.gov/29356983/)). No breast data.
- **uPAR:** 5 breast patients in total across the two first-in-human studies ([26516369](https://pubmed.ncbi.nlm.nih.gov/26516369/), [27609788](https://pubmed.ncbi.nlm.nih.gov/27609788/)).
- **αvβ3:**
  - 18F-fluciclatide in 7 patients ([18483090](https://pubmed.ncbi.nlm.nih.gov/18483090/)).
  - 18F-alfatide II in 44 patients: sensitivity similar to FDG ([29700127](https://pubmed.ncbi.nlm.nih.gov/29700127/)).
- **αvβ6:** breast evidence is a single case report ([40458979](https://pubmed.ncbi.nlm.nih.gov/40458979/)).
- **B7-H3:** 68Ga-B7H3-BCH in 20 patients with mixed tumour types; none were breast-specific ([39847434](https://pubmed.ncbi.nlm.nih.gov/39847434/)).
- **GRPR and SSTR2:** uptake is tied to ER positivity ([27446498](https://pubmed.ncbi.nlm.nih.gov/27446498/), [39078299](https://pubmed.ncbi.nlm.nih.gov/39078299/)), so these have low expected relevance for TNBC.
- **EGFR, MET and TFRC:** no human breast PET data were found.
- **ENPP3, HORMAD1, KIF18A, POLQ, and any CNT3-selective probe:** no PET or SPECT imaging agent was found.

## Caveats

- Most novel-tracer breast data come from single centres, often in China, with n ≤ 75. Many are 2025–2026 publications that have not yet been replicated.
- Some numbers come from abstracts only. The full texts were not reviewed.
- Regulatory and trial statuses come from registry and web sources as of the check date.
