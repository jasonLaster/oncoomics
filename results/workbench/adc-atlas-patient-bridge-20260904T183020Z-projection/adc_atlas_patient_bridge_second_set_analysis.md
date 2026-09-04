Takeaway: The next eight ADC targets are RNA-positive but each needs a distinct protein or compartment gate.

This review asks which targets follow the first eight signals in Diana's frozen 23-target RNA panel. No new quantification was needed because the completed, QA-passed run already measured every target under one reference and method. The next set is MUC1, MET, Nectin-4, PTK7, LIV-1, PSMA, Glypican-3, and Tissue factor, spanning 70.929 to 11.490 TPM. MET and PSMA are at or above the public TCGA-BRCA p95 boundary, Nectin-4 is between Q3 and p90, and MUC1 and LIV-1 are below Q1. These cross-pipeline bands provide directional context only and do not establish exact patient percentiles, protein abundance, therapeutic eligibility, safety, or benefit. The smallest useful next step is a caveat-specific protein or compartment assay for each target rather than another bulk-RNA rerun.

## Scientific context

The completed Diana analysis used Salmon 1.10.3 with GENCODE v23 transcripts and the matching GRCh38.p3 full-genome-decoy reference. Its public comparator uses the UCSC Toil/RSEM GENCODE v23 matrix across 1,092 TCGA primary breast tumors. The shared feature model and TPM scale support coarse distribution bands, but different quantifiers, library preparation, preservation, tumor composition, purity, and batch preclude calibrated patient-to-cohort inference. This review therefore extends the RNA-to-protein work queue without changing the run's evidence ceiling.

## Lifecycle and quality control

- Scientific run: `adc-atlas-patient-bridge-20260904T183020Z`, projected into Workbench registry run `863f837e-e6fa-480b-a94c-886c6e9c3322`
- Status: completed on attempt 5; this interpretation adds no recomputation
- Salmon fragments: 150,003,699 processed; 108,676,737 mapped; 72.4494% mapping; ISR inferred
- Transcript-to-gene aggregation: all 197,671 quantified transcripts mapped to genes
- Gene TPM sum: 999,999.999917
- Target coverage: 23 of 23 target rows passed the directional-comparison contract
- Artifact custody: the projected artifact index and all 11 indexed artifacts matched their recorded sizes and SHA-256 hashes

## Key findings

The table is ordered by patient TPM within the fixed target panel. The order is for RNA evidence review, not predicted efficacy or safety.

| RNA rank | Target | Diana TPM | Within-sample protein-coding percentile | TCGA-BRCA median TPM | Descriptive ratio | Coarse TCGA-BRCA band | Smallest target-specific gate |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| 9 | MUC1 | 70.929 | 91.77 | 418.620 | 0.1694× | Below Q1 | Epitope-specific membrane assay |
| 10 | MET | 63.913 | 90.68 | 3.250 | 19.6636× | At or above p95 | Membrane IHC plus amplification review |
| 11 | Nectin-4 (`NECTIN4`; queried as `PVRL4`) | 63.097 | 90.48 | 29.303 | 2.1533× | Q3 to p90 | Membrane IHC on viable tumor |
| 12 | PTK7 | 61.064 | 90.03 | 58.060 | 1.0517× | Median to Q3 | Membrane IHC and internalization assay |
| 13 | LIV-1 (`SLC39A6`) | 32.292 | 79.55 | 253.527 | 0.1274× | Below Q1 | Membrane IHC on viable tumor |
| 14 | PSMA (`FOLH1`) | 27.029 | 75.37 | 2.065 | 13.0925× | At or above p95 | Membrane IHC with vascular review |
| 15 | Glypican-3 (`GPC3`) | 15.307 | 62.45 | 6.439 | 2.3774× | Median to Q3 | Membrane IHC with oncofetal review |
| 16 | Tissue factor (`F3`) | 11.490 | 56.51 | 9.256 | 1.2414× | Median to Q3 | Membrane IHC with coagulation-context review |

## Interpretation

MUC1 requires an epitope-specific assay because whole-gene RNA and total-protein IHC cannot resolve therapeutic glycoforms or epitopes. MET needs membrane protein, amplification or other genomic context, and construct-relevant internalization review because RNA cannot distinguish expression from pathway activation. Nectin-4 needs viable-tumor membrane confirmation, with its legacy public-matrix symbol retained for provenance. PTK7 requires both surface localization and internalization evidence.

LIV-1 is below the pan-BRCA Q1 boundary and broad RNA expression does not establish a therapeutic window. PSMA is high relative to the pan-BRCA distribution, but non-prostate signal can arise from tumor vasculature rather than malignant cells. Glypican-3 requires accessible surface-protein and oncofetal normal-tissue review. Tissue factor requires malignant-cell versus vascular or stromal compartment localization plus coagulation-context safety interpretation. Every row remains `partial_evidence`.

## Results and review artifacts

- `results/modal_result/tables/adc_target_breast_comparison.csv`: all 23 patient measurements and TCGA-BRCA bands
- `results/modal_result/tables/adc_target_expression.csv`: target values ordered by patient TPM
- `results/modal_result/qa_summary.json`: mapping, aggregation, TPM-sum, and target-coverage gates
- `results/modal_result/run_manifest.json`: scientific lifecycle, method, reference, comparator, and evidence boundary
- `results/modal_result/reference_manifest.json`: integrity-checked reference inputs and cached-index identity
- `results/modal_result/input_evidence_index.json`: exact source-object custody without raw human reads
- `results/modal_result/artifact_index.json`: S3 artifact identities and hashes

## Limitations

This is a single bulk-tumor sample without a replicated design, so it does not support differential-expression inference. Salmon and Toil/RSEM values were not generated in a single harmonized batch, so ratios and coarse bands are descriptive rather than calibrated cohort statistics. Bulk RNA cannot assign signal to malignant, stromal, vascular, immune, or normal epithelial compartments. Gene-level RNA cannot establish membrane localization, accessibility, epitope state, internalization, payload sensitivity, safety, or clinical benefit. Public HPA and CPTAC observations remain orthogonal reference context rather than patient protein evidence.

## Next evidence

Create a second, explicitly separate pathology and assay queue for ranks 9–16. Start with assays that can answer each target's specific failure mode: epitope-resolved membrane testing for MUC1; membrane IHC, genomic context, and internalization for MET; viable-tumor membrane IHC for Nectin-4 and LIV-1; surface and internalization testing for PTK7; vascular compartment review for PSMA; oncofetal context for Glypican-3; and cellular-compartment plus coagulation-safety review for Tissue factor. Retain ranks 1–8 as the primary RNA follow-up set and do not collapse the two queues into a single therapeutic score.
