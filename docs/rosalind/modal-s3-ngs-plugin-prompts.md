# Prompt library for Modal + S3 + NGS Analysis

These prompts are designed for Codex with the NGS Analysis plugin and, where noted, NGS Analysis Workbench. They assume the operator is working in an authorized clone of this repository and has approved access to the Diana Modal workspace and private S3 prefixes.

Use the [replication guide](modal-s3-ngs-plugin-replication.md) for the underlying architecture, commands, security model, and evidence contract.

## How to use the prompts

1. Paste one prompt into a task opened at the repository root.
2. Replace every value in angle brackets. Do not paste API keys, AWS credentials, Modal tokens, or secret values.
3. Keep the prompt's no-overwrite and no-overclaim clauses intact.
4. If Workbench presents its native execution approval, review the plan there. Text in a prompt is not a replacement for that approval.
5. For a correction, use the correction prompt and a new run ID rather than rerunning or rewriting a historical result.

Common values for the reference analysis:

```text
REPO_ROOT=<absolute path to this diana-omics checkout>
INPUT_PREFIX=s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/
OUTPUT_ROOT=s3://diana-omics-private-results-172630973301-us-east-1/modal/rosalind-rnaseq-trop2/runs/
INPUT_MANIFEST=manifests/rosalind_trop2_rna_inputs.csv
RUNNER=scripts/modal/modal_s3_bulk_rna_trop2.py
HELPER=src/diana_omics/trop2_rna.py
WORKFLOW=workflows/trop2_modal_corrective
```

## 1. Read-only intake and route

Use this before choosing or running a workflow.

```text
Use the NGS Analysis plugin and NGS Analysis Workbench to assess this repository and input contract without executing a workflow or installing anything.

Repository: <REPO_ROOT>
Authorized private input prefix: s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-07-14-echo-personalis/data/immunoid/
Input manifest: manifests/rosalind_trop2_rna_inputs.csv

Inspect the repository, manifest, existing Rosalind docs, runner, and workflow wrapper before asking questions. Do not enumerate outside the authorized prefix, download large inputs, or print credentials or secret values.

Return:
1. observed input types, sample roles, assay, reference, and relationships;
2. the NGS route and confidence;
3. the scientific questions these inputs can and cannot support;
4. missing essential metadata;
5. the recommended workflow candidates, keeping found, suitable, and selected distinct;
6. runtime and reference readiness checks that would be needed;
7. a proposed evidence contract and no-call conditions;
8. the smallest safe next action.

Treat filenames and manifests as claims until verified. Keep single-sample locus presence separate from transcript-aware abundance, differential expression, surface protein, ADC response, and treatment benefit.
```

## 2. Plan the exact TROP-2 reproduction without running it

```text
Use NGS Analysis Workbench to design and prepare, but not execute, a new reproduction of the focused E019 TROP-2 RNA analysis.

Repository: <REPO_ROOT>
Input manifest: manifests/rosalind_trop2_rna_inputs.csv
Runner: scripts/modal/modal_s3_bulk_rna_trop2.py
Helper: src/diana_omics/trop2_rna.py
Workflow: workflows/trop2_modal_corrective
New proposed run ID: <NEW_UTC_RUN_ID>

Recover the scientific model from docs/rosalind/bulk-rna-trop2-modal-s3.md and inspect the implementation. Confirm that the input mount is read-only, the output is a new immutable run prefix, and run_manifest.json is written last. Compute current runner and helper SHA-256 values; do not reuse historical hashes or absolute paths.

Route the work as a focused bulk-RNA QC/report-only analysis. Differential expression must remain blocked because this is one tumor sample with no comparator or biological replicates. Check the local controller, authenticated Modal CLI, Nextflow workflow, parameter file, run directory, and reference assumptions. Build an immutable execution plan and report its workflow, target, run directory, parameter identities, plan ID, checksum, estimated expensive stages, and blockers.

Stop before execution. Do not create a historical run, reuse an old run ID, install software, or invoke the Modal analysis.
```

## 3. Run a new direct Modal reproduction

Use this when a Workbench registry entry is not required.

```text
Reproduce the focused E019 TROP-2 RNA analysis from this repository using its existing Modal + S3 runner.

Repository: <REPO_ROOT>
New run ID: <NEW_UTC_RUN_ID>
Local review directory: results/rosalind_trop2_adc/echo_personalis/<NEW_UTC_RUN_ID>

First inspect git status, record the exact commit and any runner/helper dirtiness, inspect manifests/rosalind_trop2_rna_inputs.csv, and compute current SHA-256 values for scripts/modal/modal_s3_bulk_rna_trop2.py and src/diana_omics/trop2_rna.py. Never print AWS or Modal credential values.

Run the runner's preflight-only mode. If preflight passes, execute exactly one new immutable run with the supplied run ID and download only the bounded review bundle to the requested directory. Do not reuse or overwrite an existing S3 prefix.

After execution, verify the run ID, status, evidence boundary, artifact-index identity, locally downloaded artifact sizes and SHA-256 values, and the artifact-index hash bound by the run manifest. Identify S3-only artifacts that were not independently re-hashed locally.

Interpret the actual qa_summary.json, differential_expression_status.json, tables, plots, and QC outputs. Return the four artifact groups: results, QC/visual reports, provenance, and model synthesis. Preserve partial_evidence and all source-QC warnings. Do not infer malignant-cell specificity, membrane protein, ADC eligibility, response, or treatment benefit.
```

## 4. Create and execute a registered Workbench run

```text
Use NGS Analysis Workbench to create and execute a new registered run of the repository-local corrective TROP-2 workflow.

Repository: <REPO_ROOT>
Workflow root: <REPO_ROOT>/workflows/trop2_modal_corrective
Workflow entrypoint: <REPO_ROOT>/workflows/trop2_modal_corrective/main.nf
Runner: <REPO_ROOT>/scripts/modal/modal_s3_bulk_rna_trop2.py
Helper: <REPO_ROOT>/src/diana_omics/trop2_rna.py
New Modal/S3 run ID: <NEW_UTC_RUN_ID>
New Workbench run directory: <NEW_ABSOLUTE_RUN_DIR>

Inspect the workflow README, entrypoint, current runner/helper contents, input manifest, and scientific guide. Use the current local controller only if Nextflow, Python, repository access, and authenticated Modal CLI readiness are verified. Compute and bind fresh source hashes. Create a fresh parameter file outside the workflow source tree with absolute paths, hashes, the new run ID, and recover_existing_run=false.

Run readiness, build the immutable plan, and present the native Workbench approval. Execute only through that approval surface. Monitor the durable registry run to a terminal state. Do not launch a second computation if observation is temporarily unavailable.

When terminal, inspect the projected result artifacts rather than relying on controller logs. Write and save a Workbench analysis summary that states the true lifecycle, QC findings, observed TACSTD2 values with units and denominators, unsupported claims, and smallest next evidence. Return the registered run ID, lineage/attempt information, plan identity, S3 prefix, local result path, and saved-review status.
```

## 5. Recover a completed S3 run without recomputing

```text
Recover the bounded review bundle for an already completed immutable Modal/S3 TROP-2 run. Do not rerun the analysis.

Repository: <REPO_ROOT>
Existing run ID: <EXISTING_RUN_ID>
Expected output prefix: s3://diana-omics-private-results-172630973301-us-east-1/modal/rosalind-rnaseq-trop2/runs/<EXISTING_RUN_ID>/
Local recovery directory: <NEW_EMPTY_LOCAL_DIRECTORY>

First verify read-only evidence that run_manifest.json exists, is the last-written completion marker for the expected run ID, and binds artifact_index.json. Then use the runner's --download-only mode with the existing run ID and requested local directory.

Verify every downloaded artifact represented in artifact_index.json by size and SHA-256 and verify the artifact-index hash against run_manifest.json. Do not claim that S3-only artifacts were re-hashed unless they were actually downloaded and checked. Report recovery separately from computation: the compute lifecycle is historical/completed, while this action only recovers a review projection.

If this is a Workbench recovery attempt, bind recover_existing_run=true to the same immutable Modal run ID, preserve lineage, and never create a replacement scientific result merely because transfer failed.
```

## 6. Interpret a completed or partial run

```text
Use NGS Analysis Workbench result interpretation to review this run against its original question and evidence contract.

Run directory or result bundle: <RUN_PATH>
Expected run ID: <RUN_ID>
Question: Does this bulk tumor RNA sample contain reproducible TACSTD2/TROP-2 transcript-aligned signal worth protein-level follow-up?

Begin with run_manifest.json and artifact_index.json. Verify containment, run identity, units, denominators, reference, method, and hashes before reading qa_summary.json, differential_expression_status.json, summary.md, the TACSTD2 tables, depth plot, FastQC/MultiQC outputs, BAM lineage evidence, and review JSON files.

Return:
- a one-sentence lifecycle-aware takeaway;
- scientific context and endpoint;
- observed findings with exact units and denominators;
- QC interpretation, including warnings and processing-state discordance;
- results, QC/visual reports, provenance, and model-synthesis artifacts;
- limitations and blockers;
- the smallest justified next step.

Completion does not prove valid QC. RNA does not prove malignant-cell surface protein. The locus-alignments-per-million value is a within-BAM diagnostic and must not be compared with TPM, pTPM, FPKM, RPKM, or another sample. Differential expression remains blocked without a valid replicated design.
```

## 7. Fix a discovered QA or methods issue and recompute

```text
Audit the latest TROP-2 run for this specific issue: <ISSUE>. Fix the implementation and create a new corrective run; do not edit, overwrite, or relabel the historical run.

Repository: <REPO_ROOT>
Superseded run: <OLD_RUN_ID>
New run ID: <NEW_UTC_RUN_ID>

Use the relevant NGS Analysis and Workbench skills. Trace the issue to the exact method, code, affected fields, and claims. Define an acceptance test before editing. Preserve unrelated dirty worktree changes.

Update the smallest coherent runner/helper/test surface. Run focused tests and source checks. Recompute fresh runner/helper hashes. Run preflight, then execute a new immutable Modal/S3 run or a new approved Workbench run as appropriate. Never use download-only if the scientific values must be recomputed.

Verify the new artifact envelope and compare old versus new values in a table. Mark only affected historical fields as superseded; preserve unaffected custody evidence and lifecycle history. Explain why values changed, which conclusions survive, which no longer do, and which remain unsupported. Save the corrected Workbench interpretation when a registered run exists.
```

## 8. Add another RNA-nominated ADC target

```text
Generalize the focused Modal/S3 analysis from TACSTD2/TROP-2 to <TARGET_DISPLAY_NAME> / <GENE_SYMBOL> without weakening provenance or claim boundaries.

Repository: <REPO_ROOT>
Authorized input prefix: <AUTHORIZED_S3_PREFIX>
Reference build: <REFERENCE_BUILD>
Annotation release: <ANNOTATION_RELEASE>
New run ID: <NEW_UTC_RUN_ID>

Use NGS Analysis to inspect the inputs and design the endpoint before changing code. Do not perform a global TROP-2 string replacement. Create or extend a versioned target manifest containing gene symbol, stable gene ID, target display name, reference, contig, annotated locus, canonical transcript, coding intervals, strand, and primary annotation source.

Validate reference compatibility, BAM contig presence, overlapping genes, pseudogenes/paralogs, multimapping risk, and whether the target requires isoform-specific rather than gene-level measurement. Parameterize output names and schemas so they identify the selected target. Keep all thresholds and evidence-state rules explicit and tested.

Run a new preflight and immutable run. Treat bulk RNA as target nomination only. Return separate lanes for RNA signal, DNA context if available, protein/localization evidence, normal-tissue risk, payload context, clinical context, and blockers. Do not infer surface abundance or ADC response from RNA.
```

## 9. Replace the locus diagnostic with transcript-aware RNA quantification

```text
Design a new transcript-aware bulk RNA-seq analysis for <SAMPLE_OR_COHORT>. Do not reuse the focused TACSTD2 locus-alignments-per-million metric as normalized expression.

Repository: <REPO_ROOT>
Authorized S3 prefix: <AUTHORIZED_S3_PREFIX>
Organism: human
Reference and annotation: <PINNED_MATCHED_RELEASE>
Desired output: gene- and transcript-level abundance plus QC

Use the NGS Analysis bulk-RNA counts/QC lane. Inspect FASTQ pairing, sample metadata, reference, GTF, transcriptome, gene-ID convention, strandedness, batches, and biological replicates. Infer unknown strandedness before final quantification and report disagreement.

Run the plugin preflight and create a resource plan before saying the workflow is runnable. Prefer a pinned nf-core/rnaseq workflow on a stable container runtime, or the plugin's local Salmon path only when its assumptions fit. Keep FASTA, GTF, transcriptome, and indexes from the same release. Preserve raw/estimated counts separately from TPM and carry sample metadata unchanged.

For Modal + S3 execution, stage computation through a repository-owned wrapper with a read-only exact input mount, local ephemeral writes, immutable output prefix, artifact index, and last-written run manifest. Do not place credentials in the plan. Do not start differential expression unless the count representation, metadata, replication, design formula, and contrast support it.
```

## 10. Build a harmonized TCGA or pan-cancer comparison

```text
Design a reproducible cohort comparison for <TARGET_GENE> in <PATIENT_SAMPLE> against <TCGA_OR_PUBLIC_COHORTS>.

Do not compare raw BAM locus counts or locus-alignments-per-million with TCGA TPM, pTPM, FPKM, or another processing pipeline. First establish whether the patient and cohort can be represented with compatible reference, annotation, identifiers, quantification, and transformation. If not, return blocked and specify the smallest harmonization step.

Freeze the GDC/public-data release, manifest, file IDs, sample IDs, phenotype fields, exclusions, primary/metastatic status, tumor type, molecular subtype, clinically defined subtype, and overlap among cohorts. Keep pan-cancer, lineage-matched, and subtype-specific comparisons separate.

Report cohort size, missing metadata, median, IQR, patient percentile, z-score where defensible, uncertainty or resampling sensitivity, purity/composition sensitivity, and RNA/CNV concordance when relevant. Preserve the full analysis code, environment, versioned data manifest, complete target table, and plots in a checksummed run envelope.

Interpret this as relative bulk-RNA context only. It is not evidence of malignant-cell surface localization, ADC binding/internalization, payload delivery, response, or treatment benefit.
```

## 11. Optimize cost and turnaround without changing results

```text
Audit the Modal + S3 NGS workflow for cost, throughput, retry safety, and QA. Do not execute a full data run.

Repository: <REPO_ROOT>
Runner: <RUNNER_PATH>
Reference run: <REFERENCE_RUN_PATH>

Measure or recover the stage-level wall time, CPU, memory, local disk, S3 bytes read/written, artifact sizes, and failure/retry history. Identify which stages are source QA, scientific computation, packaging, and review transfer.

Propose a content-addressed cache for expensive reusable QA stages using exact input VersionIds, tool versions, parameters, and code hashes. Every reused stage must have its own manifest and artifact index, and the final run must bind that stage by hash and state which artifacts were reused versus recomputed.

Prioritize read-only prefix narrowing, sequential large-file access, local ephemeral writes before S3 copy, bounded result projection, fail-fast reference checks, retry/recovery without recomputation, and right-sized resources. Reject optimizations that weaken checksums, overwrite run prefixes, mix accounting spaces, change scientific methods silently, or promote partial evidence.

Return a ranked optimization plan with expected benefit, scientific risk, implementation effort, validation test, and rollback condition.
```

## 12. Create a reviewer-facing visualization

```text
Use the visualization capability to create or update a self-contained reviewer-facing HTML page for <RUN_PATH>.

Read and verify the run manifest, artifact index, QA summary, primary tables, plots, and Workbench interpretation first. Show the scientific question, run lifecycle, QC gates, key measurements with units and denominators, source warnings, evidence ladder, unsupported claims, provenance, and smallest next evidence.

Do not present a within-BAM diagnostic as normalized expression or compare it with cohort TPM. Do not imply surface protein, ADC eligibility, response, or treatment benefit. Label the page as an interpretive companion rather than an immutable run artifact unless it was actually generated and hash-bound by the run.

Preserve privacy: do not embed credentials, signed URLs, raw reads, BAM contents, or unnecessary patient identifiers. Verify desktop, wide desktop, mobile, keyboard focus, contrast, overflow, and text reflow. Add focused tests for any systematic responsive-layout defect. Return the page path and the evidence files it summarizes.
```

## 13. Package a clean handoff for another analyst

```text
Prepare a reproducibility handoff for <RUN_ID> without copying raw human sequencing data out of approved storage.

Include:
- repository URL, exact commit, branch, and recorded dirty-state caveat;
- scientific question, sample/assay model, reference, endpoint, and no-call conditions;
- input manifest path with exact S3 VersionIds, sizes, and checksums;
- selected NGS route and workflow identity;
- current runner/helper hashes and configuration;
- Workbench plan/run identities and lifecycle when present;
- immutable S3 output prefix;
- local bounded review-bundle path;
- artifact verification result;
- observed findings, limitations, and next evidence;
- exact safe recovery command.

Do not include secret values, raw data, presigned URLs, or claims unsupported by the artifacts. Make clear which artifacts are complete, projected locally, S3-only, reused, recomputed, superseded, or unverified.
```

## 14. Extend the Pan-cancer ADC Atlas with a patient bridge

```text
Use NGS Analysis Workbench to run a new transcript-aware patient bridge into Pan-cancer ADC Atlas v1.

Repository: <REPO_ROOT>
Target manifest: manifests/adc_atlas_targets_v1.csv
Public breast reference: results/pan_cancer_adc_atlas/v1/cancer_expression_summary.csv
Runner: scripts/modal/modal_s3_adc_atlas_patient_bridge.py
Workflow: workflows/adc_atlas_patient_bridge
New run ID: <NEW_UTC_RUN_ID>
New Workbench run directory: <NEW_ABSOLUTE_RUN_DIR>

Verify the exact S3 FASTQ VersionIds and sizes without printing credentials. Bind the current runner, helper, target manifest, and public breast-reference hashes in a new immutable Workbench plan. Use the integrity-checked GENCODE v23/GRCh38.p3 full-genome-decoy Salmon reference, preserve automatic library inference plus sequence- and GC-bias correction, and fail unless mapping, transcript-to-gene, TPM-sum, and target-coverage gates pass.

Write a new private S3 result and copy the completion manifest last. If computation completes but bounded result projection fails, fix only the projection contract and recover that same newly computed run; do not recompute or overwrite it. Join the patient lane only through a hash-bound current-result pointer after verifying the local bundle.

Report all 23 targets, the within-sample protein-coding rank, TCGA-BRCA median ratio, and coarse quartile/tail band. Do not call the band an exact percentile because the patient uses Salmon and the public reference uses Toil/RSEM. Build an RNA-to-protein follow-up queue, but preserve partial_evidence and target-specific localization, normal-tissue, epitope, internalization, payload, and pathology gates.
```
