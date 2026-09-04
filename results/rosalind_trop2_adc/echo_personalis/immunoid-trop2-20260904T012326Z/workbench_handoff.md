# Rosalind Workbench handoff

Review the immutable private run at:

```text
s3://diana-omics-private-results-172630973301-us-east-1/modal/rosalind-rnaseq-trop2/runs/immunoid-trop2-20260904T012326Z/
```

Start with `run_manifest.json` (SHA-256 `5f07adccc8465e4001df4d08b813d6244eecedf1c4c0f72883aa1fc7e0385dab`, VersionId `2Qcf4Re3r5sZa6T10R8lwEedhldvyYtQ`), then verify all 46 entries in `artifact_index.json`.

## Starter prompt

```text
Review this completed private bulk RNA-seq TROP-2 exploration as a Rosalind Workbench evidence packet. Begin with run_manifest.json, artifact_index.json, qa_summary.json, the FastQC/MultiQC outputs, tacstd2_expression.csv, tacstd2_depth.tsv, and tacstd2_depth.png. Then read reviewer_packet.md and research_context_sources.json as post-run expert context.

Question: Does sample E019_S01 contain reproducible TACSTD2 transcript evidence worth a controlled protein-level follow-up, and which QA findings limit that conclusion?

Preserve the distinction between primary cross-BAM count concordance and the expected non-equivalence of duplicate-filtered pre-BQSR versus recalibrated BAMs. Review the Ensembl coding interval separately from untranslated flanks. Return a claim/evidence/limitation table and a smallest-next-evidence recommendation. Do not infer tumor-cell specificity, surface-protein abundance, ADC eligibility, response, or treatment benefit from bulk RNA. Differential expression is blocked because no comparator or replicates are present.
```

If the Workbench storage integration cannot open the private prefix directly, attach the two manifests, `qa_summary.json`, the two small CSVs, the depth plot, MultiQC HTML, reviewer packet, and source-context JSON. Keep raw FASTQs and BAMs in approved S3/Modal storage rather than placing their contents in model context.
