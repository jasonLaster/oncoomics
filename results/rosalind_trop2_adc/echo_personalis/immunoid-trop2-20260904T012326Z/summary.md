# Rosalind bulk RNA-seq TROP-2 exploration

Run `immunoid-trop2-20260904T012326Z` evaluated the private Personalis ImmunoID tumor RNA inputs with FastQC, MultiQC, samtools BAM QA, and focused `TACSTD2` locus counting on hs37d5.

- QA status: `review_required`
- Recalibrated BAM primary TACSTD2 reads: 53,132
- Recalibrated BAM HQ nonduplicate TACSTD2 reads: 30,856
- Unique HQ TACSTD2 templates: 15,521
- Index-normalized TACSTD2 reads per million: 124.526
- Approximate fragment RPKM diagnostic: 35.180
- TACSTD2 bases with at least 10x depth: 71.9%
- Recalibrated versus pre-BQSR count status: `discordant_review_required`
- Raw FASTQ pair count status: `matched`
- FastQC failed modules: Adapter Content, Per base sequence content, Per tile sequence quality, Sequence Duplication Levels
- FastQC warning modules: Overrepresented sequences, Per base sequence content, Per sequence GC content, Per tile sequence quality

## Interpretation boundary

This run can support only the narrow claim that reproducible `TACSTD2`-aligned transcript signal is present in this bulk tumor RNA dataset if the QA gates pass. The RPKM value is an approximate single-gene diagnostic, not Salmon/tximport TPM. There is one tumor sample, so differential expression is blocked. Bulk RNA cannot identify malignant-cell specificity, antigen heterogeneity, membrane localization, surface abundance, or treatment benefit.

The next decisive measurement is controlled TROP-2 membrane IHC (or another protein-localizing assay) on a lineage-matched specimen.
