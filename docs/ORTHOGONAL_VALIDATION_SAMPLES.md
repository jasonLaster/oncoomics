# Orthogonal Validation Samples

This document lists the extra public or reference-material samples that should be run before trusting the pipeline on Diana's real files. The point is correctness, not just completion.

## Selection Criteria

A useful validation sample needs:

- Raw or near-raw data: FASTQ, BAM, or CRAM.
- A known answer: truth VCF, truth BED/BEDPE, known driver, known signature, known dilution, or validated positive/negative status.
- Similarity to expected Diana data: tumor-normal WGS/WES, RNA-seq, vendor VCF/report files, or MRD-like ctDNA.
- Public or practically obtainable access.

## Priority 1: GIAB HG008

Use this first.

Why:

- NIST Cancer Genome in a Bottle is designed for cancer genome benchmarking.
- HG008 has tumor and paired normal data.
- Current NIST benchmark files include small variants and SV/CNV truth.
- Public files include Illumina WGS, BAMs, long-read data, and RNA-seq.

Best use:

- Personalis NeXT Personal-like tumor/normal WGS validation.
- 30x WGS downsample testing.
- SNV/indel correctness.
- SV/CNV correctness.
- RNA-seq intake and quantification plumbing.

Known-answer gates:

- Compare SNV/indel calls with `HG008-T_somatic_smvar_benchmark_v0.3_somatic_tumornormal.vcf.gz` inside the provided benchmark BED.
- Compare SV/CNV calls with `GRCh38_HG008-T-V0.5_somatic-stvar-CNV_ALL.draftbenchmark.vcf.gz` and related PASS CNV BED/BEDPE files.
- Confirm reference-build compatibility before benchmarking.
- Treat RNA-seq as QC/quantification validation until a specific RNA truth target is chosen.

Key sources:

- NIST Cancer Genome in a Bottle: https://www.nist.gov/programs-projects/cancer-genome-bottle
- Small-variant benchmark: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/NIST_HG008-T_somatic-smvar_DraftBenchmark_V0.3-20260425/
- SV/CNV benchmark: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/NIST_HG008-T_somatic-stvar-CNV_DraftBenchmark_V0.5-20260318/
- NYGC Illumina WGS: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/NYGC_Illumina-WGS_20231023/
- HG008 RNA-seq: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/NIST/HG008-T_bulk/20240508p21/UMD_RNA-seq_20250925/

## Priority 2: COLO829 / COLO829BL

Use this as the second independent WGS benchmark.

Why:

- COLO829 tumor and COLO829BL matched normal are classic cancer reference samples.
- ENA project `PRJEB27698` exposes Illumina WGS FASTQs/BAMs plus long-read data.
- Zenodo provides curated somatic SV and CNA truth.
- Published literature describes a somatic mutation catalogue, BRAF V600E, UV-like mutational signature, and melanoma-specific biology.
- Public purity-series data allow sensitivity stress testing.

Best use:

- Independent tumor-normal WGS validation.
- SV/CNV truth comparison.
- HRD-negative or non-HRD-signature guardrail.
- Purity/dilution behavior.

Known-answer gates:

- Recover expected BRAF V600E or documented melanoma driver context.
- Show UV-like/SBS7 context rather than overcalling HRD-like signature.
- Compare SV calls against `truthset_somaticSVs_COLO829_hg38lifted.vcf`.
- Compare CNA outputs against Zenodo CNA files.
- Run at least one dilution level and confirm recall decreases as tumor purity decreases.

Key sources:

- ENA project: https://www.ebi.ac.uk/ena/browser/view/PRJEB27698
- Zenodo SV/CNA truth: https://zenodo.org/records/7515830
- COLO829 somatic mutation catalogue: https://www.nature.com/articles/nature08658
- Multi-platform SV reference: https://www.sciencedirect.com/science/article/pii/S2666979X22000726

## Priority 3: Seraseq ctDNA MRD Panel Mix

Use this only if we need an MRD-like answer before Diana plasma files arrive.

Why:

- It is closer to Signatera/NeXT Personal-style positive/negative MRD validation than tissue WGS dilution.
- It has matched normal background, tumor-derived variants, synthetic variants, and known dilution levels.
- It includes expected variants and VAF/dilution behavior.

Limitation:

This is not a freely downloadable public FASTQ dataset. The datasheet says variant lists are available by contacting LGC/SeraCare, and material may need to be purchased.

Known-answer gates:

- 0 percent tumor should be negative.
- 0.5 percent and 0.05 percent tumor should be positive if sequencing depth is adequate.
- 0.005 percent tumor should be treated as a limit-of-detection stress case.
- Expected variants include BRCA1 c.1961delA, BRAF V600E, EGFR T790M, KRAS G12D/G12C, NRAS Q61R, and PIK3CA H1047R.

Key source:

- Seraseq ctDNA MRD Panel Mix datasheet: https://www.seracare.com/globalassets/seracare-resources/ds-mkt-00626-0710-2146-seraseq-ctdna-mrd-panel-mix.pdf

## Implementation Plan

1. Add `fetch:hg008` and `benchmark:hg008` commands.
2. Add truth-file manifest rows for HG008 small variants and SV/CNV.
3. Add 30x downsample controls so local runs are feasible.
4. Add `fetch:colo829` and `benchmark:colo829` commands.
5. Add COLO829 driver/signature/SV/CNA assertions.
6. Add purity-series reporting.
7. Decide whether to request Seraseq data or material.

## Acceptance Criteria

Before Diana WGS interpretation:

- HG008 SNV/indel truth comparison passes defined recall/precision thresholds.
- HG008 SV/CNV truth comparison produces inspectable precision/recall summaries.
- COLO829 recovers expected driver/signature behavior and SV/CNA truth overlap.
- Public validation still passes `verify:outputs`.
- Documentation states which results are benchmarked truth and which are smoke evidence.
