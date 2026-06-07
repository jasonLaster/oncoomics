# Source Map

This file lists the external data sources and why each one is used. It is not a literature review; it is a provenance map for the workflow.

## Diana Wiki Packet

Local source:

- `../diana-tnbc/obsidian/wiki/omics`

Use:

- Defines the clinical/research question.
- Motivates HRD, tumor-normal DNA, RNA context, and validation-first workflow design.

Project summary:

- [WIKI_SOURCE_SUMMARY.md](/Users/jasonlaster/src/projects/diana-omics/docs/WIKI_SOURCE_SUMMARY.md)

## cBioPortal TCGA-BRCA

Use:

- Processed mutation, copy-number, and clinical context for Phase 1 reference-panel construction.

Artifacts:

- `data/processed/catalog/cbioportal_tcga_brca_summary.json`
- `manifests/hrd_reference_panel.csv`
- `results/hrd_event_table.csv`

Limits:

- Processed data are useful for triage and examples.
- They do not replace raw WGS/WES HRD analysis.

## GDC TCGA-BRCA Open Metadata

Use:

- Open file and project metadata for public data awareness.

Artifacts:

- `data/processed/catalog/gdc_tcga_brca_open_summary.json`

Limits:

- Controlled raw files may require access.
- Open metadata do not provide Diana-like raw tumor-normal recompute inputs by themselves.

## UCSC Xena TCGA-BRCA

Use:

- Clinical/subtype context for RNA and public-panel interpretation.

Artifacts:

- `data/raw/xena/brca_clinical_matrix.tsv`
- `data/processed/catalog/xena_tcga_brca_clinical_summary.json`

Limits:

- Context only. Not a raw sequencing truth set.

## SEQC2 / HCC1395

Use:

- Representative breast tumor/normal WES and WGS data.
- Current Phase 2F full WES benchmark.
- Current Phase 3 WGS smoke mechanics.

Artifacts:

- `manifests/full_wes_benchmark_samplesheet.csv`
- `results/full_wes_benchmark/*`
- `manifests/phase3_wgs_smoke_samplesheet.csv`
- `results/phase3_wgs_smoke/*`

Strength:

- Good for proving raw FASTQ, alignment, GATK, and truth-overlap mechanics.

Limits:

- Current WGS use is downsampled smoke.
- Full WGS truth-set correctness still needs HG008/COLO829 expansion.

## NIST Cancer Genome in a Bottle HG008

Use:

- Next highest-priority full WGS known-answer validation.
- Personalis-like tumor-normal WGS mechanics.
- Somatic SNV/indel/SV/CNV truth benchmarking.
- RNA-seq intake and quantification plumbing.

Key sources:

- https://www.nist.gov/programs-projects/cancer-genome-bottle
- https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/NIST_HG008-T_somatic-smvar_DraftBenchmark_V0.3-20260425/
- https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/NIST_HG008-T_somatic-stvar-CNV_DraftBenchmark_V0.5-20260318/
- https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/NYGC_Illumina-WGS_20231023/
- https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/NIST/HG008-T_bulk/20240508p21/UMD_RNA-seq_20250925/

Limits:

- Draft benchmarks require careful version labeling.
- Reference compatibility must be checked before benchmarking.

## COLO829 / COLO829BL

Use:

- Independent tumor-normal WGS truth set.
- Melanoma BRAF/UV-signature sanity check.
- SV/CNA truth benchmarking.
- Purity-series stress testing.

Key sources:

- https://www.ebi.ac.uk/ena/browser/view/PRJEB27698
- https://zenodo.org/records/7515830
- https://www.nature.com/articles/nature08658
- https://www.sciencedirect.com/science/article/pii/S2666979X22000726

Limits:

- Small-variant truth source needs to be wired precisely before SNV recall assertions.
- COLO829 is melanoma, so it is a negative/orthogonal biology guardrail rather than a breast HRD positive control.

## Seraseq ctDNA MRD Panel Mix

Use:

- Potential true MRD positive/negative dilution validation.

Key source:

- https://www.seracare.com/globalassets/seracare-resources/ds-mkt-00626-0710-2146-seraseq-ctdna-mrd-panel-mix.pdf

Limits:

- Not a freely downloadable public FASTQ source.
- Variant lists/data are request-only or material may need to be purchased.

## Vendor Context

Natera Altera:

- Uses whole-exome DNA sequencing and whole-transcriptome RNA sequencing for tumor genomic profiling.
- Source: https://www.natera.com/oncology/altera/

Personalis NeXT Personal:

- Uses tumor-normal WGS to design a personalized ctDNA panel.
- Source: https://investors.personalis.com/news-releases/news-release-details/personalis-launches-next-personaltm-tumor-informed-liquid-biopsy
- Analytical validation PDF: https://www.personalis.com/wp-content/uploads/2024/05/NeXT-Personal-Analytical-Validation-with-supplementary-materials.pdf

Use in this project:

- These vendor workflows shape the expected Diana file types and validation strategy.
- They are not copied directly, and proprietary algorithms are not reproduced.
