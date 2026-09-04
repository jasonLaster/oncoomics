# Rosalind bulk RNA-seq TROP-2 exploration

Run `immunoid-trop2-qafix-20260904T154652Z` evaluated the private Personalis ImmunoID tumor RNA inputs with FastQC, MultiQC, samtools BAM QA, and focused `TACSTD2` locus counting on hs37d5.

- QA status: `passed_for_narrow_transcript_presence_with_source_qc_warnings`
- Recalibrated BAM primary TACSTD2 reads: 53,132
- Recalibrated BAM HQ nonduplicate TACSTD2 reads: 30,856
- Unique HQ TACSTD2 templates: 15,521
- Primary nonduplicate TACSTD2 alignments per million primary nonduplicate BAM alignments: 127.453
- Whole annotated TACSTD2 locus bases with at least 10x corrected depth: 71.7%
- Canonical coding-region bases with at least 10x corrected depth: 100.0%
- Recalibrated versus pre-BQSR primary-count status: `concordant`
- BAM/FASTQ accounting status: `documented_non_equivalent_alignment_record_space`
- Raw FASTQ pair count status: `matched`
- FastQC failed modules: Adapter Content, Per base sequence content, Per tile sequence quality, Sequence Duplication Levels
- FastQC warning modules: Overrepresented sequences, Per base sequence content, Per sequence GC content, Per tile sequence quality

## Interpretation boundary

This run can support only the narrow claim that reproducible `TACSTD2`-aligned transcript signal is present in this bulk tumor RNA dataset if the QA gates pass. The alignment-rate diagnostic is not transcript-aware TPM/RPKM. There is one tumor sample, so differential expression is blocked. Bulk RNA cannot identify malignant-cell specificity, antigen heterogeneity, membrane localization, surface abundance, or treatment benefit.

The next decisive measurement is controlled TROP-2 membrane IHC (or another protein-localizing assay) on a lineage-matched specimen.
