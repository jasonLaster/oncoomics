# TROP-2 corrective RNA-seq interpretation

## Outcome

The corrective run supports a narrow, reproducible finding: `TACSTD2`-aligned RNA signal is present at high depth in the E019 ImmunoID bulk-tumor RNA data. The corrected depth is materially lower than the earlier estimate, but the canonical coding region remains completely covered at at least 100x.

This is not a differential-expression result and does not establish malignant-cell specificity, TROP-2 membrane localization, surface-protein abundance, ADC eligibility, response, or treatment benefit.

## Corrections applied

- Depth was recomputed with samtools 1.16.1 using MAPQ at least 20, base quality at least 20, exclusion mask `0xF04` (`UNMAP|SECONDARY|QCFAIL|DUP|SUPPLEMENTARY`), unlimited depth, and paired-overlap suppression: `samtools depth -aa -d 0 -Q 20 -q 20 -G 0xF04 -s`.
- BAM comparisons now use primary locus alignments as the cross-processing-state concordance gate. High-quality nonduplicate counts are retained as an informational processing-state comparison because the pre-BQSR BAM has no reads marked duplicate while the recalibrated BAM has 148,771,041 primary duplicates.
- FASTQ reads, pre-BQSR primary alignments, and recalibrated post-`SplitNCigarReads` primary records are reported as different accounting spaces. They are not treated as interchangeable read totals.
- The former approximate fragment RPKM was removed. The replacement, 127.453 primary-nonduplicate locus alignments per million primary-nonduplicate BAM alignments, is explicitly a within-BAM diagnostic and is not transcript-aware TPM or RPKM.

## Recomputed results

| Metric | Earlier method | Corrected method | Change |
| --- | ---: | ---: | ---: |
| Canonical coding mean depth | 4,104.561 | 2,878.121 | -29.9% |
| Canonical coding median depth | 4,439.0 | 3,149.5 | -29.1% |
| Canonical coding minimum depth | 155 | 131 | -15.5% |
| Canonical coding maximum depth | 6,781 | 4,687 | -30.9% |
| Canonical coding bases at least 100x | 100.0% | 100.0% | unchanged |
| Whole annotated locus mean depth | 2,083.260 | 1,467.968 | -29.5% |
| Whole annotated locus median depth | 590.5 | 515.0 | -12.8% |
| Whole annotated locus bases at least 10x | 71.86% | 71.71% | -0.15 percentage points |

Focused recalibrated-BAM counts were 53,132 primary `TACSTD2` region alignments, 30,904 primary nonduplicate region alignments, 30,856 MAPQ-20 nonduplicate alignments, and 15,521 unique high-quality templates. The pre-BQSR BAM contained 53,491 primary region alignments, a 0.671% relative difference from the recalibrated BAM and within the locked 2% concordance threshold.

## Read-accounting resolution

The paired FASTQs contain 150,003,699 reads each, or 300,007,398 total reads. The pre-BQSR aligned-only BAM contains 251,685,736 primary records, 83.89% of the FASTQ read total. The recalibrated BAM contains 391,245,559 primary records, 91,238,161 more records than the FASTQ total, and its header records `SplitNCigarReads`. GATK `SplitNCigarReads` can emit multiple alignment records from one spliced RNA read, so this is documented as a non-equivalent record space rather than an impossible read surplus. One-to-one read identity across the stages was not verified.

## QA interpretation

- Both indexed BAMs passed `samtools quickcheck`; the paired FASTQ sequence counts match.
- The reference check passed for hs37d5/GRCh37 chromosome 1, and the target interval is bound to the Ensembl GRCh37 `TACSTD2` annotation and canonical transcript `ENST00000371225.2`.
- FastQC passed per-base quality and reported zero reads flagged poor quality, but adapter content, sequence duplication, base-composition, tile-quality, GC, and overrepresented-sequence warnings or failures remain. The run therefore passes only for narrow transcript-presence evidence with source-QC warnings.
- The downloaded review bundle contains 16 artifacts represented in the 49-record S3 artifact index. All 16 downloaded artifacts match their indexed SHA-256 values, and the artifact index itself matches the SHA-256 recorded in the run manifest. The 33 non-downloaded artifacts were not independently re-hashed locally.
- Large FASTQs and BAMs were bound to the versioned intake manifest by vendor MD5, SHA-256, S3 VersionId, and size. Only both BAM indexes were directly re-hashed during this run; the large objects were not re-read solely to recompute hashes.

## Scientific interpretation and next evidence

The corrected result increases confidence that `TACSTD2` transcript-aligned signal is genuinely present in this bulk sample: the primary locus count is concordant across two BAM processing states, the canonical coding region remains deeply covered after strict filtering, and the conclusion no longer depends on duplicate-inflated depth or an invalid pseudo-RPKM.

The strength of this evidence is nevertheless limited to internal alignment QC for a single bulk specimen. Differential expression is blocked because there is no contrast, biological replication, batch design, or comparator. For normalized RNA abundance or cohort placement, rerun with a transcript-aware quantifier and a declared stranded gene model, then compare against lineage-matched samples under a locked design. For the clinically relevant target question, the decisive next artifact is lineage-matched TROP-2 membrane IHC with malignant-cell percent positive, intensity, H-score, heterogeneity, and controls.

## Run provenance

- Workbench registry run: `59a88946-fa34-430a-9a5b-bc38698e2f85`
- Workbench workflow run: `nextflow-diana-trop2-modal-corrective-20260904-160549-b8ae1cb3`
- Lineage root: `nextflow-diana-trop2-modal-corrective-20260904-154746-320809e8`
- Attempt: 2
- Immutable Modal/S3 run ID: `immunoid-trop2-qafix-20260904T154652Z`
- Results prefix: `s3://diana-omics-private-results-172630973301-us-east-1/modal/rosalind-rnaseq-trop2/runs/immunoid-trop2-qafix-20260904T154652Z/`
- Runner SHA-256: `addf200733a00e8fcef1187e5337f5e56dfc9e5af867f5d2bce257d3d93a38b9`
- Helper SHA-256: `061d0c5a0f17f31577a6166a8e67ff25f48b7c44c0e79624fdb1c7f4b52f3745`

## Method references

- Samtools depth 1.16 documentation: <https://www.htslib.org/doc/1.16/samtools-depth.html>
- GATK SplitNCigarReads documentation: <https://gatk.broadinstitute.org/hc/en-us/articles/360037069592-SplitNCigarReads>
