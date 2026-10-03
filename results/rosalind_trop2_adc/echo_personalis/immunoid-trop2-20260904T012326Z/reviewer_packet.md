# TROP-2 bulk RNA reviewer packet

## Working conclusion

The Personalis ImmunoID tumor RNA data contain strong, reproducible `TACSTD2` transcript evidence. The appropriate manual disposition is `validated_for_narrower_claim_with_qc_warnings`: the transcript signal is real enough to justify protein-level follow-up, but this run does not establish tumor-cell origin, surface TROP-2 abundance, heterogeneity, ADC eligibility, or treatment benefit.

The automated run remains `review_required`. Its intentionally conservative whole-gene and cross-BAM gates expose two review issues rather than silently promoting the finding.

## Sample evidence

| Check | Result | Review meaning |
| --- | --- | --- |
| Input custody | Six RNA objects matched their expected size, mounted vendor MD5 record, parent-manifest SHA-256, and S3 VersionId | Passed; the raw prefix was read-only and all source versions were unchanged after the run |
| Paired FASTQs | 150,003,699 reads in each mate; 150 bp; zero reads flagged poor quality | Pair counts match and both complete files were parsed |
| Base quality | Per-base and per-sequence quality passed; mean quality remains approximately Q38.4-Q39.6 across 150 bases | Strong raw base-quality signal |
| Source-QC warnings | Roughly 75-76% FastQC duplication; 3-prime Illumina adapter content rises to roughly 22%; per-base composition, tile, GC, and one overrepresented poly-G sequence warnings/failures | Requires library/panel and preprocessing metadata; these warnings should not be dismissed merely because this is tumor RNA |
| BAM integrity/reference | Both BAM forms passed `samtools quickcheck`; chr1 length matches hs37d5/GRCh37 | Passed |
| Primary TACSTD2 overlap | 53,132 recalibrated versus 53,491 pre-BQSR reads; 0.67% relative difference | Concordant evidence that the locus signal is present in both BAM forms |
| Recalibrated filtered signal | 30,856 MAPQ 20 nonduplicate reads and 15,521 unique high-quality templates | Strong internal locus evidence after duplicate filtering |
| Whole-gene depth | Mean 2,083.3x; median 590.5x; 71.9% of the 2,068-bp transcript span at 10x; 58.0% at 100x | The conservative 90%-at-10x whole-span gate failed because coverage falls across untranslated flanks |
| Coding-region depth | Ensembl GRCh37 coding span 1:59041857-59042828, 972 bp; minimum 155x, median 4,439x, mean 4,104.6x; 100% at 100x | Coding sequence is completely and deeply covered |
| Diagnostic normalization | 124.526 primary locus reads per million mapped alignments; approximate fragment RPKM 35.180 | Within-run diagnostic only; not Salmon/tximport TPM and not comparable to external cohorts |

## Why the filtered BAM counts disagree

The pre-BQSR and recalibrated BAMs are not equivalent duplicate-marking states. Primary locus counts agree closely, but the recalibrated BAM has 148,771,041 primary alignments marked duplicate genome-wide and retains 58.1% of primary TACSTD2 reads after the MAPQ/nonduplicate filter. The pre-BQSR locus retains 53,424 of 53,491 primary reads under the same filter, consistent with duplicate flags not yet being applied there.

The 42.2% filtered-count difference is therefore a processing-state warning, not evidence that TACSTD2 disappears. Use the recalibrated BAM for the conservative nonduplicate estimate and primary counts only for cross-form presence concordance. Do not compare the two BAM-normalized rates as biological replicates.

## External context, kept separate

- [UniProt P09758](https://www.uniprot.org/uniprotkb/P09758/entry) identifies reviewed human TROP-2 as a 323-aa single-pass membrane protein. That makes protein localization biologically relevant, but RNA does not measure surface abundance.
- The [Human Protein Atlas TACSTD2 cancer page](https://www.proteinatlas.org/ENSG00000184292-TACSTD2/cancer) labels the TCGA cancer RNA pattern as low-specificity and reports normal respiratory and squamous epithelial expression. This reinforces the off-tumor boundary.
- The [HPA breast cancer page](https://www.proteinatlas.org/ENSG00000184292-TACSTD2/cancer/breast+cancer) reports TACSTD2 across 1,022 TCGA breast invasive carcinoma samples, with average expression 291.5 pTPM. That cohort mixes breast-cancer biology and is not a TNBC-specific comparator; pTPM must not be numerically compared with this run's approximate RPKM.

## Rosalind review verdicts

| Lane | Verdict | Reason |
| --- | --- | --- |
| Strategy | `promising_with_gaps` | Strong transcript evidence can prioritize the next assay, but cannot answer the surface-antigen or treatment question |
| Data custody | `usable_with_documented_gaps` | Hash/version custody, read-only input, private encrypted output, and BAM integrity passed; library metadata and a comparator are absent |
| Validation | `validated_for_narrower_claim_with_qc_warnings` | The coding region is deeply covered and primary counts reproduce; source-QC warnings and BAM processing asymmetry remain |
| Deployment/governance | `research_only` | Bioinformatics and pathology review remain required; no clinical or treatment-selection use |
| Differential expression | `blocked` | One tumor sample, no comparator, no biological replicates, no batch design |

## Smallest decisive next evidence

Run controlled TROP-2 membrane IHC, or another protein-localizing assay, on a lineage-matched specimen. Record malignant-cell percent positive, membrane intensity, H-score, spatial heterogeneity, internal controls, specimen date/site, and assay clone/platform. That directly addresses the question this bulk RNA result cannot.
