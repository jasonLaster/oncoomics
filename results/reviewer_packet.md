# Reviewer Packet: Diana HRD Omics Validation

## Bottom Line

The phase-1 validation pipeline is complete for open processed public TCGA-BRCA data. It builds a frozen HRD reference panel, separates causal HRR events from second-hit proxies and genome-scar proxies, and refuses to call WGS-specific signature evidence when WGS inputs are unavailable. This is not a clinical HRD truth set.

This is ready for reviewer sanity-check of the workflow mechanics. It is not yet ready to apply to Diana without the readiness gate in `results/diana_readiness_gate.md`.

## Dataset Audit

- cBioPortal mutation records fetched: 164
- cBioPortal CNA records fetched: 16050
- cBioPortal RNA marker records fetched: 20558
- Xena clinical rows: 1247
- GDC open files total from catalog query: 27931
- Human-reference smoke rows: 4
- Human-reference smoke builds: GRCh37, GRCh38
- Full-reference smoke reference: ucsc_hg38_analysis_set_full
- Full-reference caller smoke: passed
- Production somatic caller: GATK Mutect2 + FilterMutectCalls
- Production somatic smoke status: passed
- Production somatic read pairs/end: 50000
- Production somatic truth comparison: not_assessed_in_smoke
- Full WES benchmark status: passed
- Full WES benchmark ready for Phase 3: yes
- Full WES benchmark intervals: 1277
- Full WES depth-eligible truth variants: 1307
- Full WES contamination status: passed
- Phase 3 WGS mechanics status: passed
- Phase 3 WGS full-source acceptance: pending_full_source
- Phase 3 WGS complete: yes
- Phase 3 ready for Phase 4 setup: no
- Phase 3 WGS read pairs/end: 500000
- Phase 3 WGS read-pair mode: unknown
- Phase 3 coverage-CNV bins: 631
- Phase 3 SBS96 usable SNVs: 0
- Lehmann official TCGA TNBC samples: 180
- Lehmann official calls in current panel: 8
- Lehmann panel no-calls: 20
- Current RNA marker genes for subtype context: 19
- Lehmann signature expression records fetched: 719938
- Lehmann signature-scored TCGA TNBC controls: 179 / 180
- Lehmann local refined-call concordance: 142 / 179

## Frozen Panel

| category | count |
| --- | --- |
| ambiguous_control | 8 |
| mechanistic_control | 4 |
| negative_control | 8 |
| positive_control | 8 |

## HRD Prediction Classes

| prediction | count |
| --- | --- |
| ambiguous_or_incomplete | 7 |
| suggestive_hrd_like_candidate | 5 |
| low_evidence_negative_candidate | 8 |
| strong_hrd_like_candidate | 8 |

## Confusion Matrix

| expected_bucket | predicted_bucket | count |
| --- | --- | --- |
| expected_ambiguous | predicted_ambiguous_or_not_assessable | 7 |
| expected_ambiguous | predicted_hrd_like | 1 |
| expected_hrd_like | predicted_hrd_like | 12 |
| expected_negative | predicted_negative | 8 |

## What Passed

1. Public source fetches are reproducible through the Python CLI.
2. Sample identifiers cross cBioPortal and Xena without truncation in the selected clinical subset.
3. The reference panel includes positive, mechanistic, ambiguous, and negative controls.
4. HRR events, copy-loss proxies, scar proxies, and RNA context are written as separate evidence tables.
5. Official Lehmann TCGA TNBC subtype calls are imported and joined to the current panel without imputing missing or non-TNBC samples.
6. The non-dry Lehmann expression path fetches cBioPortal signature-gene expression and scores TCGA TNBC controls against official calls.
7. Ambiguous samples remain ambiguous instead of being forced into HRD-positive or HRD-negative buckets.
8. Raw-data smoke tests validate FASTQ pairing, local BAM contracts, and partial real-human-reference alignment against two reference builds.
9. Full-reference smoke validates one full hg38 analysis-set reference, BRCA interval metadata, caller-ready BAM contracts, and indexed VCF generation.
10. Production somatic smoke validates GATK Mutect2/FilterMutectCalls execution on a larger downsampled HCC1395 WES tumor-normal pair.
11. Full WES benchmark validates complete ENA FASTQ files, full-reference BAM contracts, duplicate marking, contamination estimation, PoN-aware Mutect2, and SEQC2 truth-overlap metrics.
12. Phase 3 bounded WGS developer validation has exercised the full-reference BAM, Mutect2, coverage-CNV, SBS96, and SV evidence lanes; full-source acceptance remains pending.

## Main Limitations

1. GISTIC copy loss is not allele-specific LOH.
2. Fraction genome altered and aneuploidy are scar proxies, not scarHRD.
3. SBS3, SV signatures, CHORD, and HRDetect are not assessable from the current processed phase-1 inputs.
4. Current RNA subtype context is a marker-module lane, not a genome-wide Lehmann/TNBCtype classifier.
5. The local Lehmann signature-score validation is not the locked Vanderbilt TNBCtype centroid/permutation implementation.
6. The Phase 2F Mutect2 VCF is WES small-variant benchmark evidence, not WGS HRD signature evidence.
7. The current Phase 3 WGS artifact is a bounded developer subset, not the full-source WGS acceptance run or a final HRD classifier.
8. The Phase 2F local gate uses the Broad 1000g PoN and common-biallelic contamination resource, but the full multi-GB af-only gnomAD resource remains documented as a production/cloud input rather than a local gating download.
9. BQSR, orientation-bias modeling, vendor capture intervals, allele-specific copy-number, validated SV calling, full-depth WGS scaling, and WGS signature calling remain Phase 4 or Diana-specific production decisions.
10. Clinical action still requires clinician-owned validation, companion diagnostics, or orthogonal confirmation.

## Output Tables

- `results/hrd_event_table.csv`
- `results/allele_state_table.csv`
- `results/scar_signature_table.csv`
- `results/hrd_confusion_matrix.csv`
- `results/hrd_failure_modes.csv`
- `results/rna_subtype_context.csv`
- `results/rna_module_context.csv`
- `results/lehmann_tnbc_tcga_panel.csv`
- `results/lehmann_signature_tcga_validation.csv`

## Summaries

- HRD summary: {"generatedAt":"2026-06-07T06:44:48.179Z","panelSampleCount":28,"eventRowCount":31,"alleleStateRowCount":31,"scarSignatureRowCount":28,"failureModeRowCount":63,"confusionMatrix":[{"expected_bucket":"expected_ambiguous","predicted_bucket":"predicted_ambiguous_or_not_assessable","count":7},{"expected_bucket":"expected_ambiguous","predicted_bucket":"predicted_hrd_like","count":1},{"expected_bucket":"expected_hrd_like","predicted_bucket":"predicted_hrd_like","count":12},{"expected_bucket":"expected_negative","predicted_bucket":"predicted_negative","count":8}],"boundary":"Phase-1 HRD classes are processed public-data candidates. WGS signatures, allele-specific LOH, CHORD, HRDetect, and companion diagnostics are not run."}
- RNA summary: {"generatedAt":"2026-06-07T06:44:48.289Z","panelSampleCount":28,"expressionRecordCount":20558,"moduleDefinitions":{"basal_marker":["KRT5","KRT14","KRT17","EGFR","FOXC1"],"lar_luminal_marker":["AR","FOXA1","GATA3","ESR1"],"proliferation_marker":["MKI67"],"immune_inflammation_marker":["CD8A","CD274","CXCL9","IFNG"],"epithelial_marker":["EPCAM","MUC1"],"stromal_emt_marker":["VIM"]},"boundary":"RNA context is a small marker-module lane and does not reproduce TNBCtype, TNBC-DX, or Reveal."}
- Lehmann summary: {"generatedAt":"2026-06-15T00:38:27.560Z","source":{"name":"Lehmann et al. 2016 PLOS One S1 Table","url":"https://doi.org/10.1371/journal.pone.0157368.s006","rawCache":"data/raw/lehmann/pone0157368s006.xlsx"},"classifierValidation":{"generatedAt":"2026-06-15T00:38:27.445Z","runMode":"non_dry_expression_classifier_validation","status":"completed","method":"Python port of the public BCTL Lehmann signature-score helper using cBioPortal PanCan Atlas RNA Seq V2 RSEM values.","boundary":"This validates expression acquisition and signature scoring, but it is not the Vanderbilt TNBCtype centroid/permutation web-tool implementation.","signatureSource":"https://github.com/BCTL-Bordet/TNBC_molecularsubtypes/blob/main/lehmann.RData","signatureCsv":"data/processed/lehmann/lehmann_signature_genes.csv","rawExpressionCache":"data/raw/lehmann/cbioportal_tcga_tnbc_lehmann_signature_expression.json.gz","officialTcgaTnbcSamples":180,"assessableSamples":179,"missingExpressionSamples":["TCGA-AR-A2LR-01"],"signatureRows":7799,"signatureUniqueEntrezRequested":4059,"expressionRecordsFetched":719938,"availableSignatureEntrez":4022,"availableExpressionSamples":179,"coverageBySubtype":{"basal_like_1":{"signatureEntrezCount":671,"availableEntrezCount":659,"coverage":0.9821},"basal_like_2":{"signatureEntrezCount":430,"availableEntrezCount":414,"coverage":0.9628},"immunomodulatory":{"signatureEntrezCount":1055,"availableEntrezCount":1034,"coverage":0.9801},"mesenchymal":{"signatureEntrezCount":836,"availableEntrezCount":816,"coverage":0.9761},"mesenchymal_stem_like":{"signatureEntrezCount":2346,"availableEntrezCount":2323,"coverage":0.9902},"luminal_ar":{"signatureEntrezCount":2220,"availableEntrezCount":2205,"coverage":0.9932}},"localTnbctypeMatches":124,"localTnbctypeMatchRate":0.6927,"localRefinedMatches":142,"localRefinedMatchRate":0.7933},"officialTcgaTnbcCount":180,"panelSampleCount":28,"panelWithOfficialLehmannCount":8,"panelMissingOfficialLehmannCount":20,"statusCounts":{"basal_context_but_not_official_lehmann_tnbc":2,"confirmed_from_lehmann_tcga_s1":8,"no_call_not_in_official_lehmann_tcga_tnbc":5,"not_applicable_not_tnbc_from_available_fields":13},"currentRnaMarkerGeneCount":19,"currentRnaBoundary":"Current RNA context is a marker-module lane, not a genome-wide TNBCtype classifier input.","dianaRequirements":["Clinical ER/PR/HER2 confirmation that the tumor is TNBC.","Genome-wide RNA expression from tumor RNA-seq/WTS or a validated expression assay.","Normalization on TNBC samples only, or an equivalent locked TNBCtype input contract.","Locked TNBCtype/TNBCtype-4 implementation or archived Vanderbilt web-tool run with coefficients and p-values.","TCGA positive controls from the official S1 table for regression testing."]}
