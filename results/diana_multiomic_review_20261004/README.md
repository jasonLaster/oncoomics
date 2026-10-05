# Diana multi-omic review, 2026-10-02 to 2026-10-04

**Sharing? Start with [START_HERE.md](START_HERE.md)** for the curated reports (drug candidates, what went wrong, connect the dots).

Research analysis of Diana's TNBC data, published at the data owner's direction. It is not a clinical report or a
treatment recommendation. Every finding needs review by her oncology team and, where noted, confirmation by a
CLIA-certified assay.

**Start here:** [`step14-integrated-targets/integrated_targets_report.md`](step14-integrated-targets/integrated_targets_report.md).
It has the full process walkthrough and the tiered candidate list. `next-steps-20261003.md` is the running plan.
Sections 7-10 hold round-by-round results and corrections.

| Step | Folder | Question |
|---|---|---|
| 1 | step1-specimen-ledger | Which specimen/date/prep each dataset came from |
| 2a | step2a-identity | Is KH022 this patient, from one donor? |
| 2b | step2b-nuclei | Nuclei or whole cells? |
| 3 | step3-exome-evee | Are the EVEE variants in the deep exome? |
| 4 | step4-brca1-splicing | Does BRCA1 c.81-1G>A disrupt splicing? |
| 5 | step5-ascn | Purity, ploidy, allele-specific CN, HRD scars, HLA/B2M |
| 6 | step6-scrna-malignant | Malignant nuclei and target readouts |
| 7 | step7-provenance | Where the EVEE and July-17 claims came from |
| 8 | step8-wgs-somatic | WGS consensus somatic calls, SVs, signatures, TMB |
| 9 | step9-bulk-rna | Bulk RNA subtype and immune context (capture caveat) |
| 10 | step10-he | Computational H&E (sTIL estimate superseded by HistoWiz pathology) |
| 11 | step11-germline | Germline predisposition cross-check |
| 12 | step12-serova-vaccine | Serova vaccine construct transcription and audit |
| 13 | step13-targets | Tumor-enriched druggable genes from single-nucleus RNA |
| 14 | step14-integrated-targets | Integrated candidate targets |
| 15 | step15-tnbc-outliers | Genes Diana's tumor expresses above other TNBC tumors (bulk vs TCGA plus tumor nuclei vs public TNBC tumor cells) |
| 16 | step16-problems-report | Problems found in the EVEE report and the bulk-RNA bottom-up comparison |
| 17 | step17-kb-synthesis | Connecting the omics with the clinical record, imaging, lab reports and literature (`connect_the_dots.md`) |
| 18 | step18-tumor-vs-normal-epi | Tumor cells vs her own normal cells: subtype, immune recognition, over-expressed genes, casein, CDH1 |
| 19 | step19-cbioportal-dna | How unusual Diana's DNA changes are across ~5,000 public breast tumors (TCGA, METABRIC, MSK) |

Only reports and small tables are included. Read data (BAM slices), VCFs, images, slide labels, vendor PDFs and
analysis scripts stay in private storage.
