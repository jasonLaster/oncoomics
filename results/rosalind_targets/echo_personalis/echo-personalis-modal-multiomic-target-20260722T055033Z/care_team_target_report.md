# Research Target Discovery Summary for Care-Team Discussion

**Sample/cohort:** `echo_personalis`
**Run:** `echo-personalis-modal-multiomic-target-20260722T055033Z`
**Generated:** 2026-07-22 from public Personalis ImmunoID tumor/normal DNA BAMs and tumor RNA BAMs mounted from S3 in Modal

## Bottom Line

This research-use analysis found **DNA locus callability plus unnormalized tumor RNA support for TROP-2/TACSTD2** and for several other surface-antigen hypotheses. TROP-2 moved from a DNA-only signal to:

```text
expression_supported_protein_unconfirmed
```

That means:

- `TACSTD2` was readable in the tumor and matched-normal DNA BAMs.
- `TACSTD2` had reads in the indexed tumor RNA BAM.
- **TROP-2 cell-surface protein remains unconfirmed.**
- **Sacituzumab sensitivity is not predicted here.**
- IHC, reviewed RNA quantification, and ideally malignant-cell heterogeneity review are still needed.

Across the full 37-target board:

| Metric | Result |
| --- | ---: |
| Candidate rows | 37 |
| `partial_evidence` rows | 37 |
| `ready` rows | 0 |
| Protein-confirmed rows | 0 |
| Rows with RNA used by the board | 32 |

The RNA read counts below are **raw range counts over each hs37d5 gene locus**, not TPM, FPKM, z-score, percentile, or malignant-cell-specific expression. They are enough to show that the RNA BAM contains reads at the locus; they are not enough to compare absolute surface target abundance across genes.

## What This Run Can and Cannot Say

### Supported by this run

- The target loci were covered in the provided tumor/normal DNA BAMs.
- The ImmunoID tumor RNA BAM has reads over many surface-antigen, immune-context, CDK, and payload-context loci.
- RNA support can prioritize IHC or more formal RNA-seq follow-up.

### Still not answered

- No TROP-2, HER2, HER3, LIV-1, Nectin-4, B7-H3, FOLR1, EGFR, or Tissue factor IHC.
- No cell-surface protein abundance call.
- No malignant-cell versus immune/stromal attribution.
- No normalized RNA quantification.
- No focal amplification, copy gain, focal loss, or allele-specific LOH calls.
- No SNV/indel/splice VCF or MAF.
- No HLA typing, HLA loss, or B2M loss.
- No phospho-Rb, cyclin-E, cyclin-D1, p16, PTEN, TOP1, or SLFN11 protein evidence.
- No drug sensitivity or treatment recommendation.

The delivered S3 bundle for this pass contained FASTQ, BAM, and BAI sequence files only. It did not contain precomputed VCF, MAF, CNV/CNA/SEG, SV/BEDPE, HLA-loss, TMB/MSI, IHC, PDF, or vendor interpretation tables.

## TROP-2 / TACSTD2

| Lane | Result |
| --- | --- |
| Target | TROP-2 |
| Gene | `TACSTD2` |
| Family | ADC / surface antigen |
| DNA locus | hs37d5 `1:59041099-59043166` |
| Tumor DNA read count | 5,277 |
| Matched-normal DNA read count | 1,946 |
| Tumor RNA read count | 53,220 |
| Overall status | `partial_evidence` |
| Candidate class | `expression_supported_protein_unconfirmed` |
| DNA status | `partial_evidence` |
| RNA status | `partial_evidence` |
| Protein status | `no_call` |

**Interpretation:** there is sample-level DNA callability and unnormalized RNA support for `TACSTD2`. This supports TROP-2 as a rational follow-up hypothesis.

**What would move this forward:** TROP-2 IHC on a current tumor specimen, ideally paired with reviewed RNA quantification and assessment of malignant-cell heterogeneity by spatial or single-cell methods if available.

## ADC and Surface-Antigen Follow-Up

Every curated surface-antigen locus was callable in DNA and had detected RNA reads. All remain `partial_evidence` because none has protein confirmation.

| Target | Gene | Tumor DNA reads | Normal DNA reads | Tumor RNA reads | Status |
| --- | --- | ---: | ---: | ---: | --- |
| HER3 | `ERBB3` | 85,849 | 43,725 | 548,942 | `partial_evidence` |
| HER2 | `ERBB2` | 68,447 | 41,028 | 195,427 | `partial_evidence` |
| EGFR | `EGFR` | 110,790 | 58,518 | 181,595 | `partial_evidence` |
| B7-H3 | `CD276` | 23,751 | 15,487 | 86,790 | `partial_evidence` |
| FOLR1 | `FOLR1` | 22,485 | 7,794 | 57,349 | `partial_evidence` |
| TROP-2 | `TACSTD2` | 5,277 | 1,946 | 53,220 | `partial_evidence` |
| LIV-1 | `SLC39A6` | 10,810 | 4,297 | 24,508 | `partial_evidence` |
| Nectin-4 | `NECTIN4` | 11,045 | 4,326 | 11,392 | `partial_evidence` |
| Tissue factor | `F3` | 5,609 | 2,060 | 4,012 | `partial_evidence` |

**Best next evidence:** IHC for the most clinically relevant ADC antigens, especially TROP-2 and HER2 if they are not already in the clinical pathology record. RNA alone should not be used to call TROP-2 positive or HER2 positive.

## Bispecific and Immune-Context Markers

| Target | Gene | Tumor DNA reads | Normal DNA reads | Tumor RNA reads | Missing review |
| --- | --- | ---: | ---: | ---: | --- |
| HLA-A | `HLA-A` | 42,547 | 14,010 | 989,634 | HLA typing; HLA loss |
| HLA-B | `HLA-B` | 28,592 | 9,261 | 879,436 | HLA typing; HLA loss |
| HLA-C | `HLA-C` | 28,279 | 9,643 | 768,654 | HLA typing; HLA loss |
| B2M | `B2M` | 5,114 | 1,734 | 175,072 | B2M loss/disruption |
| CD3E | `CD3E` | 7,663 | 2,907 | 13,291 | Flow or scRNA-seq |
| PD-L1 | `CD274` | 32,754 | 10,883 | 3,869 | IHC; immune context |
| PD-1 | `PDCD1` | 10,114 | 5,506 | 2,664 | Immune-cell attribution |
| 4-1BB | `TNFRSF9` | 7,529 | 2,872 | 297 | Immune-cell attribution |

**Interpretation:** HLA and `B2M` expression are visible in the RNA BAM, but this run did not call HLA alleles, HLA LOH, or B2M SNVs/indels. T-cell marker RNA can reflect infiltrating immune cells rather than tumor-cell expression.

## CDK12/13 and Cyclin K

| Target | Gene | Tumor DNA reads | Normal DNA reads | Tumor RNA reads | Status |
| --- | --- | ---: | ---: | ---: | --- |
| CDK12 | `CDK12` | 22,872 | 9,729 | 48,333 | `ddr_transcriptional_cdk_followup` |
| Cyclin K | `CCNK` | 15,964 | 6,987 | 40,244 | `ddr_transcriptional_cdk_followup` |
| CDK13 | `CDK13` | 19,983 | 7,214 | 31,180 | `ddr_transcriptional_cdk_followup` |

**Interpretation:** CDK12/13/Cyclin K all have callable DNA and detected RNA. This is still only follow-up context. There is no CDK12 copy-number state, loss-of-function variant, tandem-duplication phenotype, or pathway-dependency result in this packet.

## CDK4/6 Resistance and Cell-Cycle Context

| Target | Gene | Tumor DNA reads | Normal DNA reads | Tumor RNA reads | Board RNA lane | Missing review |
| --- | --- | ---: | ---: | ---: | --- | --- |
| Cyclin E1 | `CCNE1` | 41,853 | 14,322 | 24,534 | `partial_evidence` | CCNE1 copy number; cyclin-E protein |
| RB1 | `RB1` | 119,012 | 43,562 | 225,783 | `no_call` | RB1 loss; Rb and phospho-Rb IHC |
| CDK4 | `CDK4` | 29,783 | 11,528 | 101,079 | `partial_evidence` | copy state; phospho-Rb |
| CDK6 | `CDK6` | 36,134 | 11,233 | 85,029 | `partial_evidence` | copy state; phospho-Rb |
| Cyclin D1 | `CCND1` | 38,815 | 9,668 | 232,214 | `partial_evidence` | copy state; cyclin-D1 protein |
| CDKN2A | `CDKN2A` | 32,645 | 13,385 | 6,954 | `partial_evidence` | deletion state; p16 IHC |
| CDKN2B | `CDKN2B` | 8,735 | 2,960 | 2,381 | `partial_evidence` | deletion state |
| FGFR1 | `FGFR1` | 63,124 | 34,881 | 143,028 | `partial_evidence` | copy state; FGFR/phospho-protein |
| FGFR2 | `FGFR2` | 101,809 | 37,108 | 515,832 | `partial_evidence` | copy state; FGFR/phospho-protein |
| ESR1 | `ESR1` | 49,204 | 20,502 | 8,426 | `partial_evidence` | ER IHC; endocrine context |

`RB1`, `PTEN`, `PIK3CA`, and `AKT1` had RNA reads in the raw RNA count table, but the candidate board keeps their RNA status as `no_call` unless RNA is part of that row's required evidence policy. RB1 still needs loss/protein/phospho-Rb review; PI3K and PTEN context needs variant, copy-number, and protein/pathway review.

## Payload and Drug-Context Markers

| Target | Gene | Tumor RNA reads | Board interpretation |
| --- | --- | ---: | --- |
| TOP1 | `TOP1` | 65,337 | Topoisomerase-I payload follow-up context |
| SLFN11 | `SLFN11` | 15,513 | Payload sensitivity follow-up context |
| ABCB1 | `ABCB1` | 8,902 | Resistance/transporter follow-up context |
| UGT1A1 | `UGT1A1` | 41 | Germline pharmacogenomics is required; tumor RNA is not used as the board lane |

These are not payload sensitivity or toxicity calls. `UGT1A1` in particular needs a germline pharmacogenomics assay or a reviewed clinical genotype.

## Suggested Questions For the Treating Team

1. Is TROP-2 IHC available on the most recent tumor block, and if so what scoring method and spatial heterogeneity were reported?
2. Has HER2 IHC/FISH been repeated recently, including HER2-low or HER2-ultralow scoring where relevant?
3. Does the Personalis or ImmunoID report provide normalized target expression, target antigen calls, HLA typing, B2M status, or HLA loss of heterozygosity?
4. Are there orthogonal copy-number calls for `ERBB2`, `CCNE1`, `FGFR1`, `FGFR2`, `CDK4`, `CDK6`, `CDKN2A`, `CDKN2B`, `RB1`, and `PTEN`?
5. Are there reviewed SNV/indel/splice calls for `RB1`, `B2M`, `CDK12`, `PIK3CA`, `AKT1`, `PTEN`, `ESR1`, and HR repair genes?
6. Is there tissue available for TROP-2, HER2, B7-H3, FOLR1, LIV-1, Nectin-4, EGFR, Tissue factor, PTEN, RB1, p16, phospho-Rb, cyclin-E, TOP1, and SLFN11 IHC if any of those hypotheses is clinically relevant?
7. Should any target-positive clinical trials be considered only after IHC or vendor-reported antigen positivity confirms the required entry criterion?

## Provenance

This packet was generated in Modal from mounted S3 storage. The packet source files include SHA-256 records in `input_evidence_index.json`.

| Artifact | Purpose |
| --- | --- |
| `target_dna_evidence.csv` | DNA locus read counts and no-call CNV/SNV/HLA placeholders |
| `rna_target_expression_summary.csv` | Tumor RNA BAM locus counts |
| `candidate_target_board.csv` | Consolidated target rows and conservative statuses |
| `orthogonal_followup.csv` | Follow-up assays required for each target |
| `modal_target_packet.json` | Modal runtime, mounted-input, and SHA-256 summary |

## Shareable Boundary Statement

This is a research-use prioritization summary. The results above should not be interpreted as TROP-2 positivity, HER2 positivity, CDK12 inhibitor sensitivity, CDK4/6 resistance, ADC eligibility, bispecific eligibility, or a treatment recommendation. Clinical interpretation requires the treating oncology team, the signed clinical molecular report, relevant pathology/IHC, and any trial-specific eligibility criteria.
