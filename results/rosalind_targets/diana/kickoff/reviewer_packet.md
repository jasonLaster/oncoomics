# Pan-Target Rosalind Discovery Packet

Sample or cohort: `diana`
Run ID: `kickoff`

## Boundary

WGS and WES are first-pass support or blocker lanes. RNA expression, cell-surface protein abundance, CDK-pathway dependency, and drug response stay `no_call` until their own evidence lanes pass.

## Sample Validation

| status | candidate_count | board_row_count | ready_count | partial_evidence_count | blocked_count | not_supported_count |
| --- | --- | --- | --- | --- | --- | --- |
| passed | 37 | 37 | 0 | 0 | 37 | 0 |

## Candidate Board

| target_id | gene_symbol | target_family | overall_status | candidate_class | sample_blockers |
| --- | --- | --- | --- | --- | --- |
| trop2 | TACSTD2 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| her2 | ERBB2 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| her3 | ERBB3 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| liv1 | SLC39A6 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| nectin4 | NECTIN4 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| b7h3 | CD276 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| folr1 | FOLR1 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| egfr | EGFR | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| tissue_factor | F3 | adc_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| hla_a | HLA-A | immune_context | blocked | blocked | Immune-cell expression and protein context are not confirmed. |
| hla_b | HLA-B | immune_context | blocked | blocked | Immune-cell expression and protein context are not confirmed. |
| hla_c | HLA-C | immune_context | blocked | blocked | Immune-cell expression and protein context are not confirmed. |
| b2m | B2M | bispecific_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| pdl1 | CD274 | immune_context | blocked | blocked | Immune-cell expression and protein context are not confirmed. |
| pd1 | PDCD1 | immune_context | blocked | blocked | Immune-cell expression and protein context are not confirmed. |
| 4_1bb | TNFRSF9 | immune_context | blocked | blocked | Immune-cell expression and protein context are not confirmed. |
| cd3e | CD3E | bispecific_antigen | blocked | blocked | Surface protein abundance and malignant-cell heterogeneity are not confirmed. |
| cdk12 | CDK12 | ddr_transcription_cdk | blocked | blocked | CDK12/13 dependency and DDR transcriptional context are not validated. |
| cdk13 | CDK13 | ddr_transcription_cdk | blocked | blocked | CDK12/13 dependency and DDR transcriptional context are not validated. |
| ccnk | CCNK | ddr_transcription_cdk | blocked | blocked | CDK12/13 dependency and DDR transcriptional context are not validated. |
| rb1 | RB1 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| ccne1 | CCNE1 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| cdk4 | CDK4 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| cdk6 | CDK6 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| ccnd1 | CCND1 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| cdkn2a | CDKN2A | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| cdkn2b | CDKN2B | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| pik3ca | PIK3CA | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| akt1 | AKT1 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| pten | PTEN | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| fgfr1 | FGFR1 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| fgfr2 | FGFR2 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| esr1 | ESR1 | cell_cycle_resistance | blocked | blocked | CDK-pathway dependence and resistance context are not clinically locked. |
| top1 | TOP1 | payload_context | blocked | blocked | Payload-specific sensitivity context is not validated. |
| slfn11 | SLFN11 | payload_context | blocked | blocked | Payload-specific sensitivity context is not validated. |
| abcb1 | ABCB1 | payload_context | blocked | blocked | Payload-specific sensitivity context is not validated. |
| ugt1a1 | UGT1A1 | payload_context | blocked | blocked | Payload-specific sensitivity context is not validated. |

## Research Context Sources

| source_family | status | skills | applies_to | boundary |
| --- | --- | --- | --- | --- |
| target_identity_pathway | no_call | UniProt;Ensembl;Reactome;STRING;GO | adc_antigen;bispecific_antigen;cell_cycle_resistance;ddr_transcription_cdk;immune_context;payload_context | Normalize identity and function after sample evidence exists. |
| expression_normal_tissue | no_call | Human Protein Atlas;Bgee;GTEx;cellxgene | adc_antigen;bispecific_antigen;immune_context | Normal expression cannot prove sample surface abundance. |
| cancer_clinical_context | no_call | cBioPortal;CIViC;ClinicalTrials.gov;PubMed;PMC | adc_antigen;bispecific_antigen;cell_cycle_resistance;ddr_transcription_cdk;immune_context;payload_context | Clinical or public tumor evidence cannot override sample no_call gates. |
