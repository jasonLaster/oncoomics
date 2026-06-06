# Source Map

This map records the online research inputs used to design the project. It favors primary publications, official portals, official documentation, and project repositories.

## Validation Datasets

| Source | Role in this project | Access posture | First verifier |
|---|---|---|---|
| [TCGA-BRCA / GDC publication page](https://gdc.cancer.gov/about-data/publications/brca_2012) | First breast-cancer multi-omics benchmark. Includes open processed mutation, RNA, copy-number, methylation, RPPA, subtype, and clinical artifacts, with controlled raw data. | Open processed data; controlled raw data. | Download only open publication-freeze artifacts first; verify file hashes or sizes, sample counts, barcode format, PAM50/subtype labels, and mutation/CNV overlap. |
| [GDC API download docs](https://docs.gdc.cancer.gov/API/Users_Guide/Downloading_Files/) | Programmatic manifest and file-download route for GDC-hosted files. | Open or token-gated depending on file. | Bun fetcher must emit a GDC manifest, access level, and no-token-required status for phase-1 files. |
| [UCSC Xena](https://xena.ucsc.edu/) | Fast processed TCGA matrix and phenotype access for RNA and clinical slices. | Open. | Verify dataset URL, matrix dimensions, sample ID intersection with TCGA barcodes, and no silent sample ID truncation. |
| [cBioPortal datasets](https://www.cbioportal.org/datasets) and [download docs](https://docs.cbioportal.org/downloads/) | Fast mutation, CNA, clinical, and subtype cross-checks for TCGA PanCancer Atlas. | Open. | Verify study ID, downloaded ZIP/staging files, sample count, and BRCA1/2/HRR alteration concordance with source labels. |
| [cBioPortal API docs](https://docs.cbioportal.org/web-api-and-clients/) | Programmatic lookup for clinical and molecular slices. | Open. | API smoke test must return studies and expected BRCA study identifiers before data fetchers rely on it. |
| [METABRIC / Synapse](https://www.synapse.org/Synapse%3Asyn1688369/wiki/) | Independent breast expression/CNV validation cohort. Useful for subtype and copy-number context after TCGA. | Registered/controlled depending on file. | Treat as phase-2 unless access is available; verifier records access state and avoids assuming fetchability. |
| [CPTAC via GDC](https://gdc.cancer.gov/about-gdc/contributed-genomic-data-cancer-research/clinical-proteomic-tumor-analysis-consortium-cptac) | Proteogenomic validation and protein/RNA context when needed. | Mixed open/controlled; protected data via dbGaP. | Confirm breast project files, data type, and access level before adding to a runnable benchmark. |
| [Landscape of somatic mutations in 560 breast cancer WGS](https://www.nature.com/articles/nature17676) | HRD/signature-positive WGS reference backbone used by HRDetect/CHORD-style work. | Publication plus ICGC access paths. | Freeze a small public positive/negative panel and verify sample IDs against publication/ICGC-derived labels. |
| [Hartwig Medical Database](https://www.hartwigmedicalfoundation.nl/en/data/database/) | Metastatic tumor-normal WGS/RNA validation and PURPLE/GRIDSS/LINX-style ecosystem context. | Access request. | Keep as phase-3 access-request source; verifier records access-request status, not downloadable data. |
| [DepMap / CCLE](https://depmap.org/portal/ccle/) | TNBC cell-line technical controls for expression and DNA/RNA sanity checks, not patient-tumor validation. | Open. | Verify cell-line lineage filter, expression matrix dimensions, and known TNBC cell-line marker sanity. |

## HRD And Variant Tools

| Tool or paper | Role | First verifier |
|---|---|---|
| [nf-core/sarek](https://nf-co.re/sarek) | Raw tumor-normal WGS/WES preprocessing, variant calling, annotation, and MultiQC aggregation if raw data is available. | Run only after containers/Nextflow are configured; phase verifier starts with `-profile test` or a tiny fixture. |
| [GATK Mutect2](https://gatk.broadinstitute.org/hc/en-us/articles/360036733771-Mutect2) | Somatic SNV/indel caller reference and raw workflow component. | Confirm input reference build, tumor-normal pairing, and VCF PASS filter handling. |
| [FACETS](https://github.com/mskcc/facets) | Purity/ploidy and allele-specific copy-number context. | Verify purity/ploidy output exists before biallelic claims. |
| [scarHRD](https://github.com/sztup/scarHRD) | Copy-number scar scoring from WES/WGS-derived copy-number segments. | Container/R setup must reproduce a known fixture before score interpretation. |
| [CHORD](https://github.com/UMCUGenetics/CHORD) | HRD classifier using somatic mutation contexts; useful for BRCA1-like versus BRCA2-like classifier evidence when SNV/indel/SV inputs exist. | Verify PASS variants only, supported SV caller/parsing, reference genome, and positive-control recovery. |
| [HRDetect Nature Medicine paper](https://www.nature.com/articles/nm.4292) | Conceptual benchmark for integrated mutational-signature HRD detection in breast cancer. | Use as a benchmark frame, not a direct clinical claim; verifier checks that six-feature/signature evidence is not collapsed into a single unsupported label. |
| [SigProfilerAssignment](https://github.com/SigProfilerSuite/SigProfilerAssignment) | Assignment of known mutational signatures, including SBS3-like signal, to samples. | Confirm genome build, mutation matrix type, minimum mutation count, and reported reconstruction error. |
| [SigProfilerExtractor](https://github.com/SigProfilerSuite/SigProfilerExtractor) | De novo signature extraction for larger validation panels. | Use only when panel size supports extraction; otherwise assignment/refitting is preferred. |

## RNA Context Tools

| Tool or source | Role | First verifier |
|---|---|---|
| [TNBCtype Vanderbilt/Pietenpol context](https://www.vumc.org/pietenpol-lab/node/100) | Reference behavior for Lehmann/TNBC subtype calls. | Verify classifier input normalization and expected subtype labels before use. |
| [Lehmann TNBCtype paper](https://journals.sagepub.com/doi/10.4137/CIN.S9983) | Original TNBCtype tool/paper reference. | Treat as subtype-context lane, not HRD primary endpoint. |
| [TNBCtype-4 refinement PubMed](https://pubmed.ncbi.nlm.nih.gov/27310713/) | Refined TNBCtype-4 classification context. | Verify whether labels are TNBCtype-6, TNBCtype-4, or another schema before comparing cohorts. |
| [genefu Bioconductor](https://bioconductor.org/packages/release/bioc/html/genefu.html) | PAM50/breast subtype cross-check. | Requires R/container setup; verify PAM50 fixture before interpretation. |
| [GSVA Bioconductor](https://bioconductor.org/packages/release/bioc/html/GSVA.html) | RNA module activity scoring for immune, proliferation, LAR/androgen, EMT/stroma, interferon, and antigen-presentation modules. | Requires R/container setup or Python substitute; verify gene-set identifier mapping. |

