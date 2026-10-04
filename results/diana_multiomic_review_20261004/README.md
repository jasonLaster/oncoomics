# Diana multi-omic review, 2026-10-02 to 2026-10-04

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

Only reports and small tables are included. Read data (BAM slices), VCFs, images, slide labels, vendor PDFs and
analysis scripts stay in private storage.
