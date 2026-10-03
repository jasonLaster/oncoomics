# Rosalind bulk RNA-seq TROP-2 exploration on Modal and S3

This workflow asks a deliberately narrow question: does the Personalis ImmunoID bulk tumor RNA dataset contain reproducible `TACSTD2`/TROP-2 transcript evidence worth protein-level follow-up?

It follows the Rosalind Workbench pattern: attach a biological question to a reviewable plan, validate custody and runtime before expensive work, execute with traceable artifacts, and keep the sample evidence separate from sourced biological context.

## Evidence and access boundary

- Private input prefix: `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/`
- Private output prefix: `s3://diana-omics-private-results-172630973301-us-east-1/modal/rosalind-rnaseq-trop2/runs/<run_id>/`
- Modal AWS secret: `onco-omics-use1`; credentials remain in Modal and never enter source, logs, or arguments.
- Input mount: read-only and limited to the exact user-authorized prefix.
- Output bucket: versioned and KMS-encrypted by bucket policy.
- Input custody: object sizes, vendor MD5 records, parent-manifest SHA-256 records, and S3 VersionIds are bound in [the checked-in manifest](../../manifests/rosalind_trop2_rna_inputs.csv).
- Data class: private human tumor RNA. The runner uses restricted Modal access and single-use containers.

## Why this is a focused BAM analysis

The intake contains one paired tumor RNA FASTQ set plus two indexed vendor BAM forms on `hs37d5`, but no normal RNA, biological replicates, contrast, strandedness record, or locked transcriptome/index bundle. A general differential-expression analysis is therefore blocked.

The runner uses the indexed BAMs for fast locus evidence and preserves the raw FASTQs for independent FastQC/MultiQC. It does not realign roughly 19 GB of reads merely to answer whether signal is present. This avoids an unnecessary reference/pipeline change while still testing the source FASTQs and cross-checking recalibrated and pre-BQSR BAM forms.

This choice matches the current nf-core guidance: arbitrary vendor BAM reprocessing is not a drop-in substitute for a pipeline-produced BAM, reference components must be mutually compatible, and cached indices plus pinned versions should be used when full cohort quantification is warranted.

## Execution plan

1. Preflight every required object against the intake manifest and mounted vendor checksum ledger.
2. Run `samtools quickcheck`, whole-BAM `flagstat`, the chr1/hs37d5 reference gate, and indexed `TACSTD2` counts on both BAM forms.
3. Stream both full FASTQs through FastQC while the BAM accounting checks run concurrently.
4. Aggregate FastQC with MultiQC and verify paired total-read counts.
5. Count primary and MAPQ 20 nonduplicate reads at the one-exon GRCh37 `TACSTD2` locus, collapse high-quality alignments to unique templates, and compute depth at MAPQ and base quality 20 while excluding unmapped, secondary, QC-fail, duplicate, and supplementary records and suppressing paired overlap.
6. Require primary locus counts from the two BAM processing states to agree within 2%, at least 90% of the canonical coding region to reach 10x, matched FASTQ mate counts, and documented BAM/FASTQ record-space lineage before allowing the narrow “transcript signal present” result.
7. Write all artifacts locally on the Modal worker, then copy them sequentially to S3. Upload `run_manifest.json` last as the completion marker.

The single-gene pseudo-RPKM has been removed. The remaining locus-alignments-per-million value is explicitly a within-BAM diagnostic; it is not transcript-aware TPM/RPKM and must not be compared across samples or studies.

## Next optimization after the baseline

This first private run deliberately performs full-file source QA. The next runner revision should split source QA from interpretation and cache the completed FastQC/MultiQC stage under a content-addressed key derived from the two FASTQ VersionIds plus the FastQC/MultiQC versions. A later code-only plot or packet change could then reuse a verified QA-stage manifest without rereading immutable inputs. The final analysis run should still bind that stage manifest by hash and retain its own last-written completion marker.

If cohort-level or cross-sample expression is needed, add a separately validated Salmon/tximport route with declared strandedness, a pinned Ensembl GRCh37 transcriptome, cached indices, and biological replicates. Do not promote this focused BAM diagnostic into that role.

## Run

Run the inexpensive read-only gate first:

```sh
modal run scripts/modal/modal_s3_bulk_rna_trop2.py --preflight-only
```

Then create an immutable run:

```sh
modal run scripts/modal/modal_s3_bulk_rna_trop2.py \
  --run-id immunoid-trop2-<UTC timestamp>
```

The runner refuses to overwrite an existing run prefix.

## Output contract

```text
run_manifest.json
input_evidence_index.json
artifact_index.json
qa_summary.json
differential_expression_status.json
summary.md
reviews/strategy_review.json
reviews/custody_review.json
reviews/validation_review.json
reviews/governance_review.json
qc/fastqc/*
qc/multiqc/multiqc_report.html
qc/bam/*
tables/tacstd2_expression.csv
tables/tacstd2_depth.tsv
plots/tacstd2_depth.png
```

## Interpretation boundary

A passing run can support only: reproducible `TACSTD2`-aligned RNA reads are present in this bulk tumor RNA dataset under the recorded internal-QC rules.

It cannot establish which cells express the transcript, malignant-cell specificity, antigen heterogeneity, membrane localization, surface-protein abundance, ADC eligibility, response, or treatment benefit. The smallest decisive next measurement is controlled TROP-2 membrane IHC or another protein-localizing assay on a lineage-matched specimen, recording malignant-cell percent positive, intensity, H-score, heterogeneity, and controls.

## Corrective Workbench run

Run `immunoid-trop2-qafix-20260904T154652Z` recomputed the affected values on 2026-09-04 and completed with automated status `passed_for_narrow_transcript_presence_with_source_qc_warnings`. The earlier run `immunoid-trop2-20260904T012326Z` is superseded for depth and normalization interpretation because it excluded only supplementary alignments from depth, did not suppress mate overlap, compared processing-state-sensitive nonduplicate counts as if they were a biological concordance gate, and reported a non-transcript-aware pseudo-RPKM.

The corrected run excludes flags `0xF04`, applies MAPQ and base quality 20, suppresses paired overlap, and separates raw FASTQ reads from pre-BQSR primary alignments and post-`SplitNCigarReads` records. Corrected mean coding-region depth is 2,878.1x, median depth is 3,149.5x, minimum depth is 131x, and all 972 coding bases remain at least 100x. The two BAM processing states agree on primary TACSTD2 overlap within 0.67%; the recalibrated BAM contains 30,856 MAPQ 20 nonduplicate locus alignments and 15,521 unique high-quality templates.

Workbench registry run `59a88946-fa34-430a-9a5b-bc38698e2f85` is attempt 2 of lineage `nextflow-diana-trop2-modal-corrective-20260904-154746-320809e8`. Attempt 1 completed the Modal compute and immutable S3 write but failed while returning the oversized MultiQC HTML through Modal; attempt 2 recovered a bounded review bundle from the same immutable S3 run without recomputing or overwriting it. The Workbench-authored interpretation is saved with the completed run.

The interpretation remains `validated_for_narrower_claim`: reproducible TACSTD2 transcript-aligned signal is present and merits protein-level follow-up. The source warnings are high duplicate estimates, 3-prime adapter accumulation, other FastQC composition/tile findings, and non-equivalent duplicate marking between the pre-BQSR and recalibrated BAMs.

The responsive [TROP-2 RNA evidence visualization](visualizations/trop2-rna-evidence.html) presents the coding-depth profile, QC gates, interpretation boundary, and protein-localization follow-up in one review surface. It is a checked-in interpretive companion to the immutable run envelope, not an additional hash-bound run artifact.

The immutable compute run contains 48 versioned KMS-encrypted objects and all 46 indexed artifact hashes passed after download. A separate five-object review prefix preserves the expert packet and its own last-written manifest. Exact VersionIds, hashes, failed zero-output attempts, and validation checks are in the [kickoff receipt](../../results/rosalind_trop2_adc/echo_personalis/immunoid-trop2-20260904T012326Z/kickoff_receipt.json). The [reviewer packet](../../results/rosalind_trop2_adc/echo_personalis/immunoid-trop2-20260904T012326Z/reviewer_packet.md) contains the full evidence synthesis, and the [Workbench handoff](../../results/rosalind_trop2_adc/echo_personalis/immunoid-trop2-20260904T012326Z/workbench_handoff.md) provides the exact review prompt.

The preceding paragraph documents the superseded baseline run only. For the corrective run, S3 contains a 49-record artifact index. The bounded local review bundle contains 16 indexed artifacts; all 16 match their indexed SHA-256 values, and the artifact index matches the hash recorded in the run manifest. The 33 S3-only artifacts were not independently re-hashed locally. The complete corrective interpretation and run provenance are in the [Workbench analysis](../../results/workbench/immunoid-trop2-qafix-20260904T154652Z-recovery/trop2_workbench_analysis.md); affected depth and pseudo-RPKM values in the earlier artifacts are superseded.

## Optimization and QA sources

- [OpenAI Rosalind Workbench](https://developers.openai.com/blog/rosalind-workbench): biological-question-first plans and traceable, reviewable outputs.
- [OpenAI Life Sciences collection](https://learn.chatgpt.com/use-cases/collections/life-sciences): the wider Codex pattern for connecting repository work, benchmarks, and iterative scientific review.
- [OpenAI bulk RNA-seq FASTQ QC use case](https://learn.chatgpt.com/use-cases/bulk-rna-seq-fastq-qc): preflight, FastQC/MultiQC, quantification readiness, and QC interpretation before downstream claims.
- [Modal CloudBucketMount guide](https://modal.com/docs/guide/cloud-bucket-mounts): co-located sequential reads, read-only mounts, and local temporary writes before an object-store copy.
- [Samtools depth 1.16](https://www.htslib.org/doc/1.16/samtools-depth.html): exclusion-mask, quality-threshold, unlimited-depth, and paired-overlap semantics used by the correction.
- [GATK SplitNCigarReads](https://gatk.broadinstitute.org/hc/en-us/articles/360037069592-SplitNCigarReads): why post-split RNA BAM records cannot be compared one-for-one with raw FASTQ reads.
- [nf-core/rnaseq usage guidance](https://nf-co.re/rnaseq/latest/docs/usage/): sample design, strandedness inference, reference compatibility, pinned versions, cached indices, resume behavior, and resource retries.
- [Ensembl GRCh37 TACSTD2 annotation](https://grch37.rest.ensembl.org/lookup/symbol/homo_sapiens/TACSTD2?expand=1): the exact gene locus and canonical transcript used by the focused count.
- [UniProt P09758](https://www.uniprot.org/uniprotkb/P09758/entry): reviewed TROP-2 protein identity and topology.
- [Human Protein Atlas TACSTD2 breast cancer page](https://www.proteinatlas.org/ENSG00000184292-TACSTD2/cancer/breast+cancer): breast-cancer cohort context, paired with the broader [TACSTD2 cancer page](https://www.proteinatlas.org/ENSG00000184292-TACSTD2/cancer) for normal-expression and off-tumor boundaries.
