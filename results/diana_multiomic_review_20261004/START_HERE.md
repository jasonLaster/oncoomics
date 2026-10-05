# Diana multi-omic review: reports worth sharing

Research hypotheses for discussion with Diana's oncology team. Nothing here is a treatment recommendation, and RNA
findings need protein confirmation. Updated 2026-10-04.

There is a visual summary of the connect-the-dots report. It is shared by link and needs a claude.ai sign-in:
https://claude.ai/artifact/G4bVeHrbtmTgb2E3wiKzt8

## 1. Drug candidates and single-cell findings

| Report | What it answers |
|---|---|
| [Integrated drug targets](step14-integrated-targets/integrated_targets_report.md) | **Start here.** Candidate targets ranked across WGS, exome, single-nucleus RNA and proteomics, with a walkthrough of how we got there. Tier 1: HRD (PARP/platinum/POLQ), TROP-2 ADC, immune-rich. Tier 2: CD44 amplicon, B7-H4, PSMA, ENPP3 and others. |
| [Tumor vs her own normal cells](step18-tumor-vs-normal-epi/tumor_vs_normal_report.md) | Newest single-cell results:<br>- subtype: luminal-progenitor-like, with ELF5/EHF amplified;<br>- immune recognition: lowest antigen presentation in the sample, no interferon response;<br>- genes over-expressed by tumor cells, mostly on DNA gains;<br>- casein is background, not tumor;<br>- B7-H4 is also in normal duct cells. |
| [Genes high vs other TNBC](step15-tnbc-outliers/tnbc_outliers_report.md) | Diana's tumor cells compared with tumor cells from 8 public TNBC. CD44, SLC28A3, ATR, HORMAD1, SLC6A14, PSMA. TROP-2 is typical, not an outlier. |
| [Tumor-enriched targets](step13-targets/targets_report.md) | The first single-nucleus target screen, including the ADC antigen panel. |
| [Serova vaccine audit](step12-serova-vaccine/serova_audit.md) | Independent check of the personalized vaccine design:<br>- 22 of 22 missense antigens reproduce;<br>- the SHANK2 fusion window is an artifact;<br>- the truncal TP53/BRCA1 splice drivers are not encoded;<br>- the single-nucleus perspective. |
| [BRCA1 splicing](step4-brca1-splicing/brca1_splicing_report.md) | Direct RNA proof that the somatic BRCA1 mutation breaks splicing. 97% of BRCA1 pre-mRNA in tumor nuclei is mutant, and every mutant transcript truncates early. |

## 2. What the earlier reports got wrong

| Report | What it answers |
|---|---|
| [Problems report](step16-problems-report/problems_report.md) | **Start here.** Two separate problems:<br>- **EVEE report:** none of its 9 headline variants exist in the tumor.<br>- **Bulk RNA vs TCGA:** most genome-wide "outliers" are artifacts of a capture (exome-style) RNA library taken from a tumor-poor piece. |
| [Exome audit of the EVEE variants](step3-exome-evee/exome_evee_audit.md) | The deep exome was the tool that caught the problem. 0 supporting reads at every EVEE tier-1 site, while the real variants are found. |
| [Provenance of the EVEE and July 17 claims](step7-provenance/provenance_report.md) | Where "HRD 62", the EVEE variant list and the "pathogenic SHH" call came from, and why none can be traced to a callset. |
| [Bulk RNA report](step9-bulk-rna/bulk_rna_report.md) | The capture-library and tumor-poor-piece caveats in detail. |

## 3. Connecting the dots

| Report | What it answers |
|---|---|
| [Connect the dots](step17-kb-synthesis/connect_the_dots.md) | **Start here.** The omics read against the clinical record, imaging, lab reports and literature:<br>- a pregnancy-associated tumor;<br>- most tumor and immune data come from day-8 on-treatment tissue;<br>- a specific DNA-repair programme;<br>- one composite amplicon;<br>- "hot stroma, quiet tumor cells";<br>- corrections to earlier records. |
| [Visual summary](step17-kb-synthesis/visual_summary.md) | The same story with the timeline, gene charts (as tables), amplicon junctions, response curves and hypothesis table. Markdown version of the shared visual page; the original HTML is `visual_summary.html`. |

## 4. Foundations (for technical readers)

| Report | What it answers |
|---|---|
| [How unusual is her DNA?](step19-cbioportal-dna/dna_rarity_report.md) | Diana's copy-number and driver changes against ~5,000 public breast tumors. Her 11q13 + 22q12 + CD44 amplicon is found in none of ~3,200 genome-wide-profiled tumors; CD44 + ELF5/EHF co-amplification is a recognized pattern in ~6-9% of TNBC; B2M loss and 3q gain are common TNBC changes. |
| [WGS somatic calls](step8-wgs-somatic/wgs_somatic_report.md) | Consensus mutations, structural variants, signatures and TMB. |
| [Copy number, purity, HRD scars](step5-ascn/ascn_report.md) | Purity 0.35, ploidy 2.8, HRD scars 67-99, B2M single copy, no clonal HLA loss. |
| [Single-nucleus malignant calls](step6-scrna-malignant/scrna_malignant_report.md) | How tumor nuclei were identified, and target readouts. |
| [Germline cross-check](step11-germline/germline_report.md) | No inherited cancer-predisposition variant found; BRCA1 is somatic. |
| [Full index of all steps](README.md) | Every step 1-18. |
