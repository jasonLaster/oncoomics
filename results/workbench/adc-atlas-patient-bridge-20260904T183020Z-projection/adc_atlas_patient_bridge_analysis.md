Takeaway: QA passed; TROP-2 is 108.46 TPM and directionally between the TCGA-BRCA Q1 and median.

The fresh run quantified the exact paired E019_S01 tumor RNA FASTQs from the read-only S3 mount with Salmon 1.10.3 and a GENCODE v23/GRCh38.p3 full-genome-decoy reference. Salmon processed 150,003,699 fragments, mapped 108,676,737 (72.45%), and inferred an ISR library. All 197,671 quantified transcripts mapped to genes, the gene TPM sum was 999,999.999917, and all 23 ADC targets produced directionally comparable rows. TROP-2 (`TACSTD2`) measured 108.457 TPM, 0.6809 times the 1,092-sample TCGA-BRCA median of 159.288 TPM, placing it in the coarse Q1-to-median band. HER3, GPNMB, FOLR1, EGFR, and NaPi2b were at or above the TCGA-BRCA p95 boundary, but this cross-pipeline placement is descriptive rather than an exact patient percentile. Every target remains `partial_evidence` because bulk RNA does not establish malignant-cell membrane protein, accessibility, internalization, payload response, safety, or clinical benefit.

## Scientific context

The analysis asks how Diana's bulk-tumor RNA target measurements compare directionally with the public Pan-cancer ADC Atlas v1. The public comparator uses the UCSC Toil/RSEM GENCODE v23 matrix and includes 1,092 TCGA primary breast tumors. The private sample shares the feature model and TPM scale, but it differs in quantifier, library preparation, preservation, tumor composition, purity, and batch. The reported ratio and quartile/tail band are therefore hypothesis-ranking context, not a harmonized cohort percentile or a treatment-selection result.

## Observed target findings

The table is ordered by Diana TPM within the frozen 23-target panel. It is an RNA review queue, not a therapeutic score.

| Target | Diana TPM | TCGA-BRCA median TPM | Descriptive ratio | Coarse TCGA-BRCA band | Smallest target-specific next gate |
| --- | ---: | ---: | ---: | --- | --- |
| HER3 (`ERBB3`) | 710.853 | 114.920 | 6.1856× | At or above p95 | Membrane IHC with heterogeneity review |
| GPNMB | 485.048 | 100.252 | 4.8383× | At or above p95 | Membrane IHC with macrophage review |
| Folate receptor alpha (`FOLR1`) | 189.450 | 1.990 | 95.2010× | At or above p95 | Validated membrane IHC assay |
| HER2 (`ERBB2`) | 152.236 | 111.739 | 1.3624× | Median to Q3 | Validated quantitative HER2 protein assay |
| EGFR | 110.351 | 3.040 | 36.3010× | At or above p95 | Membrane IHC plus genomic context |
| TROP-2 (`TACSTD2`) | 108.457 | 159.288 | 0.6809× | Q1 to median | Membrane IHC on viable tumor |
| B7-H3 (`CD276`) | 91.474 | 94.647 | 0.9665× | Q1 to median | Membrane IHC with vascular and stromal review |
| NaPi2b (`SLC34A2`) | 80.720 | 1.850 | 43.6322× | At or above p95 | Membrane IHC with lung normal-tissue review |

TROP-2 is strongly expressed within this sample: its within-sample percentile among protein-coding gene TPM values is 95.19. That statistic is not the earlier report's transcript-rank percentile and should not be compared with it as if the denominators were identical. The new 108.457 TPM value is the preferred reproducible transcript-aware estimate for this FASTQ/reference/method combination. Its pan-BRCA band does not replace a subtype-specific Basal-like or receptor-defined TNBC analysis.

HER3 is the highest RNA signal in the panel, but accessible surface protein and heterogeneity remain unmeasured. GPNMB requires malignant-cell versus macrophage localization. FOLR1 and NaPi2b are high relative to the public BRCA distribution, but their normal-tissue and membrane-accessibility gates remain decisive. HER2 requires the validated clinical protein/ISH framework rather than an RNA-derived category. EGFR, B7-H3, and TROP-2 likewise need target-specific membrane review before any ADC inference.

## Payload context

The run also observed `TOP1` 37.772 TPM, `SLFN11` 20.362 TPM, `ABCB1` 5.947 TPM, `ABCG2` 1.117 TPM, and `TUBB3` 8.773 TPM, plus endosomal, lysosomal, and apoptosis-context genes. These are mechanistic context only. Their expression does not establish payload sensitivity, resistance, delivery, or cell killing.

## Quality control and provenance

- Run ID: `adc-atlas-patient-bridge-20260904T183020Z`
- Workbench completion attempt: registry run `863f837e-e6fa-480b-a94c-886c6e9c3322`
- Reference: GENCODE v23 annotation/transcripts plus matching GRCh38.p3 primary assembly, with 194 full-genome decoys
- Quantifier: Salmon 1.10.3 selective alignment, automatic library inference, mapping validation, sequence-bias correction, and GC-bias correction
- Mapping gate: 72.4494% observed, at least 50% required, passed
- Transcript-to-gene gate: 1.0000 observed, at least 0.999 required, passed
- Gene TPM-sum gate: 999,999.999917 observed, 999,000–1,001,000 required, passed
- Target coverage gate: 23/23, passed
- Artifact custody: the downloaded `artifact_index.json` matched the run-manifest hash; all 11 projected indexed artifacts matched their recorded sizes and SHA-256 hashes

The scientific computation wrote a new immutable private S3 result and copied `run_manifest.json` last. The first local projection expected Salmon's library-format file under `aux_info/`, while Salmon emitted it at the quantification root. The runner path was corrected and the completed new run was projected without recomputing or overwriting its scientific values.

## Results and review artifacts

- `results/modal_result/run_manifest.json`: completed scientific lifecycle, method, reference, comparator, and evidence boundary
- `results/modal_result/qa_summary.json`: mapping, aggregation, TPM-sum, and target-coverage gates
- `results/modal_result/tables/adc_target_breast_comparison.csv`: all 23 patient values and TCGA-BRCA bands
- `results/modal_result/tables/adc_target_expression.csv`: the same target rows ordered by patient TPM
- `results/modal_result/tables/payload_context_expression.csv`: bounded payload-mechanism context
- `results/modal_result/reference_manifest.json`: integrity-checked reference sources and cached-index identity
- `results/modal_result/input_evidence_index.json`: exact source-object custody without raw human reads
- `results/modal_result/artifact_index.json`: S3 artifact identities and hashes

## Limitations

This is one bulk tumor sample without a replicated design, so differential expression is not supported. Patient and public TCGA-BRCA TPM values were not generated by one quantifier and batch; an exact percentile, z-score, or calibrated effect size would overstate comparability. Bulk RNA cannot assign signal to malignant versus stromal, vascular, macrophage, or normal epithelial cells. Gene-level RNA cannot resolve epitopes or isoforms such as CLDN18.2 or MUC1 glycoforms. Public HPA/CPTAC rows are orthogonal reference context and do not validate the patient's protein state.

## Next evidence

Prioritize target-specific protein localization on viable tumor, led by HER3, GPNMB, FOLR1, HER2, EGFR, TROP-2, B7-H3, and NaPi2b because they are the highest RNA signals in the frozen panel. Preserve the caveat attached to each target: macrophage review for GPNMB, validated assay frameworks for FOLR1 and HER2, vascular/stromal review for B7-H3, and lung normal-tissue review for NaPi2b. For TROP-2 specifically, report malignant-cell membrane percent positive, 0–3+ intensity, H-score, complete versus incomplete membrane pattern, heterogeneity, assay clone/platform, and controls. Use residual viable tumor and the clinical pathology gate before interpreting any ADC rationale.
