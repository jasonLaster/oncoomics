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
- Human-reference smoke builds: GRCh38, GRCh37

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

1. Public source fetches are reproducible with Bun.
2. Sample identifiers cross cBioPortal and Xena without truncation in the selected clinical subset.
3. The reference panel includes positive, mechanistic, ambiguous, and negative controls.
4. HRR events, copy-loss proxies, scar proxies, and RNA context are written as separate evidence tables.
5. Ambiguous samples remain ambiguous instead of being forced into HRD-positive or HRD-negative buckets.
6. Raw-data smoke tests validate FASTQ pairing, local BAM contracts, and partial real-human-reference alignment against two reference builds.

## Main Limitations

1. GISTIC copy loss is not allele-specific LOH.
2. Fraction genome altered and aneuploidy are scar proxies, not scarHRD.
3. SBS3, SV signatures, CHORD, and HRDetect are not assessable from the current processed phase-1 inputs.
4. Clinical action still requires clinician-owned validation, companion diagnostics, or orthogonal confirmation.

## Output Tables

- `results/hrd_event_table.csv`
- `results/allele_state_table.csv`
- `results/scar_signature_table.csv`
- `results/hrd_confusion_matrix.csv`
- `results/hrd_failure_modes.csv`
- `results/rna_subtype_context.csv`
- `results/rna_module_context.csv`

## Summaries

- HRD summary: {"generatedAt":"2026-06-06T22:06:57.373Z","panelSampleCount":28,"eventRowCount":31,"alleleStateRowCount":31,"scarSignatureRowCount":28,"failureModeRowCount":63,"confusionMatrix":[{"expected_bucket":"expected_ambiguous","predicted_bucket":"predicted_ambiguous_or_not_assessable","count":7},{"expected_bucket":"expected_ambiguous","predicted_bucket":"predicted_hrd_like","count":1},{"expected_bucket":"expected_hrd_like","predicted_bucket":"predicted_hrd_like","count":12},{"expected_bucket":"expected_negative","predicted_bucket":"predicted_negative","count":8}],"boundary":"Phase-1 HRD classes are processed public-data candidates. WGS signatures, allele-specific LOH, CHORD, HRDetect, and companion diagnostics are not run."}
- RNA summary: {"generatedAt":"2026-06-06T22:06:57.424Z","panelSampleCount":28,"expressionRecordCount":20558,"moduleDefinitions":{"basal_marker":["KRT5","KRT14","KRT17","EGFR","FOXC1"],"lar_luminal_marker":["AR","FOXA1","GATA3","ESR1"],"proliferation_marker":["MKI67"],"immune_inflammation_marker":["CD8A","CD274","CXCL9","IFNG"],"epithelial_marker":["EPCAM","MUC1"],"stromal_emt_marker":["VIM"]},"boundary":"RNA context is a small marker-module lane and does not reproduce TNBCtype, TNBC-DX, or Reveal."}
