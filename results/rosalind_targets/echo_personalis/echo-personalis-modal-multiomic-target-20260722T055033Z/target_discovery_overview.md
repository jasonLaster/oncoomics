# Target Discovery Overview

**Packet:** `echo-personalis-modal-multiomic-target-20260722T055033Z`
**Generated from:** Personalis ImmunoID tumor/normal DNA BAMs plus tumor RNA BAMs mounted from S3 in Modal
**Status:** research-use triage only

## Executive Summary

We built a 37-row target board to ask a narrow question:

> From WGS/WTS, which ADC, immune, CDK, DDR, cell-cycle, and payload hypotheses deserve orthogonal wet-lab follow-up?

The Modal run was useful for **visibility**, not for final drug selection.

- **37 / 37 target rows had partial evidence.**
- **0 / 37 were ready for a target claim.**
- **0 / 37 had protein confirmation.**
- Surface-antigen targets such as **TROP-2, HER2, HER3, EGFR, B7-H3, FOLR1, LIV-1, Nectin-4, and Tissue factor** were readable in DNA and visible in the RNA BAM, but remain unconfirmed at the cell-surface protein layer.
- **CDK12/CDK13/Cyclin K** were readable and visible, but there was no CDK12 loss, gain, tandem-duplication phenotype, or CDK12/13 dependency result.
- **RB1 / Cyclin E / CDK4/6 / PI3K / FGFR** rows stayed in cell-cycle context only. They need CNV/SNV review and protein/phospho-protein review before they can support or weaken a CDK4/6 hypothesis.

The clinically encouraging version of this result would be convergence:

1. tumor DNA shows the target locus is intact or amplified,
2. tumor RNA expresses the target,
3. OncoOmics or IHC confirms the protein,
4. Ignite or another assay confirms the pathway state if the target is a signaling dependency, and
5. spatial, single-cell, or pathology review shows the signal is on malignant cells rather than a bystander cell population.

The discouraging version would be a blocker:

- the target protein is absent despite RNA signal,
- the target is present only in a small or stromal/immune subpopulation,
- `RB1`, `B2M`, `HLA`, `PTEN`, or the surface-antigen locus is deleted or disrupted,
- a bypass pathway such as Cyclin E/CDK2, PI3K/AKT, FGFR, or MAPK is activated in a way that makes the proposed drug class biologically weak, or
- the needed trial requires a protein score that our sample does not meet.

## What Was Computed

### Inputs

The Modal target-discovery job used these local packet files:

| File | What it contributed |
| --- | --- |
| `target_dna_evidence.csv` | First-pass tumor/normal DNA read support over each curated target locus |
| `rna_target_expression_summary.csv` | Tumor RNA BAM read support over each curated target locus |
| `candidate_target_board.csv` | One conservative status row per target hypothesis |
| `orthogonal_followup.csv` | The missing protein, phospho-protein, HLA, IHC, RNA, or spatial follow-up for each row |
| `input_evidence_index.json` | SHA-256 provenance for each packet source |

The source BAMs were indexed, mounted from S3 inside Modal, and queried over hs37d5 gene intervals. That produced read counts over the target loci. Those counts are **raw range counts**, not TPM, FPKM, z-scores, percentiles, cell-surface calls, or malignant-cell-specific expression values.

### Board Rules

The board kept separate statuses for DNA, RNA, and protein:

| Status | Meaning |
| --- | --- |
| `ready` | That lane's required evidence passed |
| `partial_evidence` | Useful sample evidence exists, but not enough for a claim |
| `no_call` | Required evidence is missing or invalid |
| `blocked` | Required files, metadata, tools, approvals, or reviewer policy are missing |
| `not_supported` | Reviewed sample evidence argues against the candidate |

The key safety rule was: **DNA or RNA alone cannot prove an ADC target, CDK-pathway dependency, HLA integrity, or drug sensitivity.** Surface targets need protein; signaling targets need pathway state; immune/T-cell-engager hypotheses need HLA and `B2M` review.

## Target Board Findings

### ADC and Surface Targets

All curated surface-antigen genes were visible in the RNA BAM and callable in DNA. All remained `partial_evidence` because none had IHC, OncoOmics, flow, CITE-seq, or spatial confirmation in this packet.

| Candidate | Gene | Tumor RNA locus reads | What it would be good to see next | What would be bad news |
| --- | --- | ---: | --- | --- |
| TROP-2 | `TACSTD2` | 53,220 | TROP-2 membrane protein on most malignant cells | Low/absent protein or strong heterogeneity |
| HER2 | `ERBB2` | 195,427 | HER2 IHC in low, ultralow, or amplified range, depending on drug context | Repeat IHC 0 with no convincing membrane staining |
| HER3 | `ERBB3` | 548,942 | HER3 protein, with malignant-cell localization | RNA without HER3 protein |
| EGFR | `EGFR` | 181,595 | EGFR protein plus EGFR/MAPK/PI3K pathway context if an EGFR/HER3 ADC is considered | Normal-tissue risk or no tumor-cell protein |
| B7-H3 | `CD276` | 86,790 | B7-H3 IHC or multiplex IF on tumor cells | Stromal-only or immune-only signal |
| FOLR1 | `FOLR1` | 57,349 | FR-alpha IHC meeting a trial's entry threshold | Protein below the required trial score |
| LIV-1 | `SLC39A6` | 24,508 | LIV-1 protein on malignant cells | Protein absent or not tumor-localized |
| Nectin-4 | `NECTIN4` | 11,392 | Nectin-4 protein if an enfortumab-style trial is in scope | Low/absent Nectin-4 protein |
| Tissue factor | `F3` | 4,012 | Tissue-factor protein if a tissue-factor ADC trial is in scope | Low/absent protein or vascular/stromal ambiguity |

**Clinical read-through:** this was good news for prioritizing follow-up because several ADC genes are not silent in the RNA BAM. It did **not** establish ADC eligibility. The strongest next question is still simple: does the current tumor actually put the target protein on its surface?

### TROP-2

`TACSTD2` was readable in both DNA BAMs and had tumor RNA support:

| Lane | Result |
| --- | --- |
| DNA locus | hs37d5 `1:59041099-59043166` |
| Tumor DNA reads | 5,277 |
| Matched-normal DNA reads | 1,946 |
| Tumor RNA reads | 53,220 |
| Board class | `expression_supported_protein_unconfirmed` |
| Overall status | `partial_evidence` |
| Protein status | `no_call` |

This is enough to keep TROP-2 high on the IHC list. It is not enough to infer sacituzumab benefit or to know whether every lesion, every malignant clone, or enough of the residual tumor expresses TROP-2 protein.

TROP-2 is also a useful example of why the protein layer matters. If the TROP-2 IHC or OncoOmics row is strong and tumor-localized, the RNA result becomes more credible. If protein is absent, the RNA count should be treated as a failed hypothesis rather than rescued by the DNA result.

### Immune and Bispecific Context

HLA and `B2M` RNA were visible, but the job did not perform HLA typing, HLA loss, or coding-disruption calls.

| Candidate | Gene | Tumor RNA locus reads | Main missing evidence |
| --- | --- | ---: | --- |
| HLA-A | `HLA-A` | 989,634 | HLA type and HLA loss |
| HLA-B | `HLA-B` | 879,436 | HLA type and HLA loss |
| HLA-C | `HLA-C` | 768,654 | HLA type and HLA loss |
| B2M | `B2M` | 175,072 | `B2M` SNV/indel/focal loss |
| CD3E | `CD3E` | 13,291 | T-cell localization by flow, scRNA-seq, or spatial |
| PD-L1 | `CD274` | 3,869 | PD-L1 IHC and cell-type attribution |
| PD-1 | `PDCD1` | 2,664 | T-cell attribution |
| 4-1BB | `TNFRSF9` | 297 | Activated T-cell attribution |

**Good news would be** intact HLA and `B2M`, preserved tumor antigen presentation, and T cells that are spatially close to malignant cells. **Bad news would be** HLA loss, `B2M` loss, immune exclusion, or PD-1/4-1BB RNA coming from sparse bystander cells.

Ignite and OncoOmics are not the main assays for this blocker class. HLA callers, WGS/WES SNV+CNV review, PD-L1 IHC, and spatial immune profiling are better matched.

### CDK12, CDK13, and Cyclin K

| Candidate | Gene | Tumor RNA locus reads | Board class |
| --- | --- | ---: | --- |
| CDK12 | `CDK12` | 48,333 | `ddr_transcriptional_cdk_followup` |
| Cyclin K | `CCNK` | 40,244 | `ddr_transcriptional_cdk_followup` |
| CDK13 | `CDK13` | 31,180 | `ddr_transcriptional_cdk_followup` |

This is follow-up context only. We did not see a CDK12 loss-of-function call, a focal amplification call, a tandem-duplication phenotype, or a transcriptional-CDK dependency assay. CDK12/13 inhibitor follow-up should only become serious if the reviewed VCF/CNV/SV/RNA layers point in that direction.

Ignite could add DDR pathway activity if the panel contains relevant phospho-markers, but it is unlikely to be a standalone CDK12/13 test. OncoOmics could say whether CDK12, CDK13, Cyclin K, or adjacent DDR proteins are abundant if they are on the panel.

### CDK4/6 Resistance and Cell-Cycle Context

| Candidate | Gene | Tumor RNA locus reads | What we still need |
| --- | --- | ---: | --- |
| RB1 | `RB1` | 225,783 | RB1 loss, total Rb, phospho-Rb |
| Cyclin E1 | `CCNE1` | 24,534 | `CCNE1` copy gain, Cyclin E protein |
| CDK4 | `CDK4` | 101,079 | copy state, phospho-Rb |
| CDK6 | `CDK6` | 85,029 | copy state, phospho-Rb |
| Cyclin D1 | `CCND1` | 232,214 | copy state, Cyclin D1 protein |
| CDKN2A | `CDKN2A` | 6,954 | deletion state, p16 |
| PTEN | `PTEN` | 259,390 | PTEN loss, PTEN protein |
| PI3K alpha | `PIK3CA` | 149,678 | hotspot mutation review |
| AKT1 | `AKT1` | 387,709 | hotspot mutation review |
| FGFR1 | `FGFR1` | 143,028 | amplification, FGFR pathway activation |
| FGFR2 | `FGFR2` | 515,832 | amplification, FGFR pathway activation |

This is where Ignite could help the most. CDK4/6 sensitivity and resistance are not just "is `CDK4` expressed?" questions; the useful readout is whether the Rb gate is present and phosphorylated and whether Cyclin E/CDK2, PI3K/AKT, FGFR, MAPK, or mTOR signaling is providing a bypass route.

**Good news for a future cell-cycle hypothesis:** retained RB protein, phospho-Rb consistent with CDK4/6-driven cycling, no focal `RB1` loss, no marked Cyclin E/CDK2 bypass, and no dominant PI3K/FGFR escape signal.

**Bad news:** `RB1` loss, absent Rb protein, high Cyclin E with `CCNE1` amplification, or a strong activated bypass pathway. Those findings would make a direct CDK4/6 argument weaker.

### Payload Context

| Candidate | Gene | Tumor RNA locus reads | Why it matters |
| --- | --- | ---: | --- |
| TOP1 | `TOP1` | 65,337 | Topoisomerase-I payload context for several ADCs |
| SLFN11 | `SLFN11` | 15,513 | DNA-damage/payload sensitivity context |
| ABCB1 | `ABCB1` | 8,902 | Efflux/resistance context for some payloads |
| UGT1A1 | `UGT1A1` | 41 | Germline pharmacogenomics for irinotecan/SN-38 toxicity; tumor RNA is not useful here |

These rows are context, not predictions. A topoisomerase-I payload ADC can still work or fail for reasons unrelated to bulk `TOP1` reads: antibody binding, antigen density, internalization, bystander effect, efflux, DNA-damage response, and prior treatment all matter.

## Ignite and OncoOmics

### What Is Available Now

As of this packet, **no Ignite numeric report and no OncoOmics abundance table were present in the computational inputs.** Local July coordination notes show:

- Ignite phosphoproteomics was ordered through PHM.
- Sutter block A2 was selected first to preserve A1 as a reserve.
- Ignite was able to request slides rather than the whole A2 block.
- OncoOmics was expected to follow using the same A2-first plan.

That means the current Rosalind rows correctly leave:

- `protein_status = no_call`
- `research_context_status = no_call`
- surface-protein abundance unconfirmed
- phospho-protein pathway state unmeasured

### How Ignite Will Help

Ignite is the best fit for **activated signaling** questions.

| Target family | Useful Ignite readout |
| --- | --- |
| EGFR/HER2/HER3 | Are HER-family or downstream MAPK/AKT markers phosphorylated? |
| CDK4/6/RB | Is Rb phosphorylated? Is the cell-cycle gate active? |
| PI3K/PTEN/AKT | Are AKT, mTOR, S6, or related markers activated? |
| FGFR/MAPK | Is MAPK/ERK signaling active in a way that could be a bypass route? |
| DDR/CDK12 | Are any DDR phospho-markers abnormal, if the panel covers them? |

Ignite is **not** the primary answer for TROP-2, B7-H3, FOLR1, LIV-1, or Nectin-4. Those are surface-antigen abundance and localization questions.

### How OncoOmics Will Help

OncoOmics is the best fit for **total protein abundance**.

| Target family | Useful OncoOmics readout |
| --- | --- |
| ADC antigens | Does the RNA-nominated target protein exist in the specimen? |
| HER-family / EGFR | Are ERBB2/HER2, ERBB3/HER3, or EGFR proteins abundant enough to keep following? |
| CDK4/6/RB | Are Rb, Cyclin E, Cyclin D1, CDK4, CDK6, p16, or PTEN visible on the panel? |
| Payload | Are TOP1 or SLFN11 proteins measured and concordant with RNA? |

Panel membership is the first practical check. If OncoOmics does not include TROP-2, B7-H3, FOLR1, LIV-1, or Nectin-4, those targets still need single-marker IHC, multiplex IF, or spatial assays.

### Specimen Caution

The Modal board came from the Personalis ImmunoID DNA/RNA BAMs. Ignite/OncoOmics were being routed from Sutter A2. Those can be reconciled, but they are not automatically identical specimens.

When Ignite or OncoOmics results land, each imported row should record:

- specimen block,
- specimen date,
- anatomic site,
- tumor content,
- vendor assay ID,
- report date,
- raw value and reference distribution,
- report SHA-256, and
- whether the protein specimen is matched to, near, or distinct from the Personalis sequencing specimen.

## Drug and Trial Context

Public drug context can explain why a target is interesting, but it cannot rescue a failed sample lane.

The public context below was refreshed on **2026-07-23** and should be rechecked before any real eligibility discussion.

| Finding family | Drug or trial class | Current context |
| --- | --- | --- |
| TROP-2 | Sacituzumab govitecan | FDA approved sacituzumab for first-line unresectable locally advanced/metastatic TNBC in June 2026: as monotherapy for patients not eligible for PD-1/PD-L1 therapy, and with pembrolizumab for PD-L1 CPS >= 10 disease. This does not make a curative-stage WTS signal sufficient for use. |
| TROP-2 | Datopotamab deruxtecan | Phase 3 TNBC trials are testing Dato-DXd in neoadjuvant/adjuvant and residual-disease settings, including TROPION-Breast04 and TROPION-Breast03. Both were active-not-recruiting in ClinicalTrials.gov in July 2026. |
| HER2 | Trastuzumab deruxtecan | FDA labeling supports HER2-directed ADC therapy in HER2-positive and HER2-low metastatic breast cancer contexts, with HER2 IHC/ISH determined by an authorized test. Bulk `ERBB2` RNA alone does not establish HER2-low or HER2-ultralow pathology. |
| HER3 | Patritumab deruxtecan | HERTHENA-Breast03 is a recruiting phase 2 study testing HER3-DXd plus pembrolizumab and chemotherapy in high-risk early TNBC or HR-low/HER2-negative breast cancer. |
| EGFR/HER3 | Izalontamab brengitecan | IZABRIGHT-Breast01 is a recruiting phase 3 trial of an EGFR/HER3 bispecific ADC in first-line metastatic TNBC or ER-low/HER2-negative breast cancer for patients not eligible for anti-PD-(L)1 or endocrine therapy. |
| TROP-2 / Nectin-4 / HER2 | ADC MATCH | NCI-2024-01903 / NCT06311214 screens advanced solid tumors for high RNA/protein expression of TROP-2, Nectin-4, or HER2 and routes to sacituzumab govitecan, enfortumab vedotin, or trastuzumab deruxtecan substudies. |
| FOLR1 | FR-alpha ADCs | FOLR1-directed ADC trials exist for selected advanced solid tumors. A useful Diana-specific claim would need FR-alpha protein by the trial's required assay and cutoff. |
| CDK12/13 | Transcriptional-CDK inhibitors | Mostly investigational; the current WGS/WTS board did not show the kind of CDK12/13 alteration pattern that would make this a leading hypothesis. |
| CDK4/6/RB | CDK4/6 inhibitors | CDK4/6 inhibitors are not a standard TNBC target from expression alone. RB retention and Cyclin E/bypass review are prerequisites for a serious biology discussion. |

Key public references:

- FDA June 2026 sacituzumab approval: <https://www.fda.gov/drugs/resources-information-approved-drugs/fda-approves-sacituzumab-govitecan-hziy-monotherapy-and-combination-pembrolizumab-first-line>
- Current Enhertu label: <https://www.accessdata.fda.gov/drugsatfda_docs/label/2026/761139s041s043lbl.pdf>
- TROPION-Breast03 / Dato-DXd in residual early TNBC: <https://clinicaltrials.gov/study/NCT05629585>
- TROPION-Breast04 / neoadjuvant Dato-DXd: <https://clinicaltrials.gov/study/NCT06112379>
- HERTHENA-Breast03 / HER3-DXd in high-risk early TNBC: <https://clinicaltrials.gov/study/NCT06797635>
- IZABRIGHT-Breast01 / EGFR-HER3 bispecific ADC in metastatic TNBC: <https://clinicaltrials.gov/study/NCT06926868>
- ADC MATCH: <https://www.cancer.gov/research/participate/clinical-trials-search/v?id=NCI-2024-01903>

## What This Did Not Rule Out

Nothing in this Modal packet definitively ruled out a target. The run did not have the VCF, CNV, SV, HLA, IHC, Ignite, or OncoOmics evidence required to reject a row.

What could rule out or de-prioritize a row later:

| Candidate | Evidence that would weaken it |
| --- | --- |
| TROP-2 ADC/RLT | TROP-2 protein absent or restricted to too small a malignant-cell fraction |
| HER2 ADC | HER2 IHC remains 0 with no qualifying membrane staining |
| HER3 / EGFR | Protein absent, or EGFR/HER3 signaling absent when a pathway-active drug requires it |
| B7-H3 / FOLR1 / LIV-1 / Nectin-4 | Protein below the relevant trial threshold |
| T-cell engagers / HLA-restricted therapies | HLA loss, `B2M` loss, or no compatible HLA allele |
| CDK12/13 | No CDK12/13 alteration, no tandem-duplication phenotype, no DDR/transcriptional-CDK dependency |
| CDK4/6 | `RB1` loss, absent Rb protein, high Cyclin E/CDK2 bypass, or no Rb phosphorylation |
| TOP1 payload ADCs | Target antigen absent, TOP1/payload context unfavorable, or efflux/resistance markers concerning |
| UGT1A1/SN-38 toxicity | Germline UGT1A1 high-risk genotype, if clinically confirmed |

## Immediate Next Questions

1. Does the OncoOmics core panel include `TACSTD2`, `ERBB2`, `ERBB3`, `EGFR`, `CD276`, `FOLR1`, `SLC39A6`, or `NECTIN4`?
2. Does Ignite include phospho-Rb, total Rb, pAKT, pERK, pS6, PTEN, Cyclin D1, Cyclin E, EGFR, HER2, HER3, FGFR, or DDR markers?
3. Which tissue block did each protein assay actually receive, and how close is it to the Personalis ImmunoID specimen?
4. Does the signed Personalis report include normalized RNA expression, antigen calls, HLA typing, TMB/MSI, or HLA LOH?
5. Can we obtain VCF, MAF, CNV/SEG, and SV/BEDPE outputs to replace the current no-call DNA alteration columns?
6. Which surface targets are worth confirming by single-marker IHC because they are missing from OncoOmics or need a clinical trial score?
7. If residual disease is present after neoadjuvant therapy, which ADC or HER-family trials are actually open then, and what IHC/RNA criteria do they require?

## Bottom Line

This run moved us from "many plausible targets from literature" to a Diana-specific shortlist with auditable DNA/RNA support. The first-pass shortlist is strongest for **TROP-2, HER-family/EGFR, B7-H3, FOLR1**, and the **CDK4/6/RB/PI3K/FGFR pathway context** because those genes were visible enough to justify orthogonal testing.

The next decisive results are not more raw RNA counts. They are:

1. OncoOmics or IHC to confirm surface protein.
2. Ignite to check activated signaling, especially Rb/PI3K/FGFR/MAPK.
3. VCF/CNV/SV/HLA review to identify genomic blockers.
4. Spatial or single-cell review when bulk protein cannot tell which cells carry the signal.

Until those arrive, every target remains a candidate, a blocker check, or a trial-screening hypothesis rather than a therapy-selection result.
