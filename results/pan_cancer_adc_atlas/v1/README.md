# Pan-cancer ADC Atlas v1

Generated: 2026-09-04T20:47:11.654Z

This run profiles 23 ADC targets across 32 TCGA primary-tumor cohorts and 32 GTEx normal-tissue groups using the UCSC Toil harmonized RNA-seq recompute. HPA v25.1 cancer IHC, normal-tissue IHC, and CPTAC rows provide separate protein-context lanes.

## Status

- Candidate rows: 23
- `partial_evidence`: 23
- `ready`: 0
- Patient comparison: `directionally_comparable` across 23 targets. The same GENCODE v23 feature model and TPM scale support directional TCGA-BRCA bands, but Salmon versus Toil/RSEM and other technical/specimen differences preclude exact cohort percentiles.
- Protein follow-up queues: 8 targets in ranks 1–8 and 8 targets in ranks 9–16.

## Interpretation boundary

This atlas ranks research hypotheses. RNA abundance is not surface-protein abundance, and public HPA/CPTAC context does not establish accessible membrane antigen, internalization, payload sensitivity, safety, or benefit in a patient. The exact source URLs, versions, hashes, query genes, filters, and sample counts are in `source_manifest.json`.
