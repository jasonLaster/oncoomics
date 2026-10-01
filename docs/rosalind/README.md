# GPT-Rosalind Workflows

This directory collects the project plans for using GPT-Rosalind, Codex, the Life Sciences NGS Analysis plugin, and the Life Science Research plugin as a scientist-facing workbench around this repository.

The integration goal is practical: use GPT-Rosalind to route analysis, run validated tools, preserve provenance, add sourced biological context, and produce reviewer-ready packets. GPT-Rosalind should not replace the assay, the pipeline, clinical signoff, or the local verifiers.

## Integration Model

```mermaid
flowchart TD
    User["Scientist or operator"] --> Rosalind["GPT-Rosalind / Codex thread"]
    Rosalind --> Intake["Guided intake"]
    Intake --> NGS["Life Sciences NGS Analysis"]
    Intake --> Research["Life Science Research"]
    NGS --> Artifacts["Local artifacts and QC outputs"]
    Research --> Context["Sourced external context"]
    Artifacts --> Packet["Reviewer packet"]
    Context --> Packet
    Packet --> Iterate["Same-thread review and rerun"]
    Iterate --> Rosalind
```

The pattern is:

1. Inspect available files before asking questions.
2. Validate sample sheets, references, tools, and metadata before compute-heavy work.
3. Run or route public, reproducible workflows.
4. Return auditable artifacts, not just conclusions.
5. Add sourced external biological context only after sample evidence exists.
6. Keep no-call and blocker states explicit.
7. Let the user fix gaps and rerun in the same thread without losing provenance.

## What The Plugins Are Good At

| Capability | Best tool or skill family | Good for | Boundary |
| --- | --- | --- | --- |
| Top-level sequencing routing | `ngs-analysis-router` | Choosing the right NGS lane from FASTQ, BAM, CRAM, VCF, matrices, or mixed inputs. | It routes; it does not decide clinical meaning. |
| Runtime and reference readiness | `ngs-runtime-env` | Checking tools, package plans, references, indexes, databases, and install/resource blockers. | Should emit reviewable plans before installing or downloading. |
| WGS/WES DNA calling | `ngs-dna-variant-calling`, `ngs-dna-somatic-variants`, `ngs-dna-germline-variants` | Tumor-normal WES/WGS QC, somatic variants, germline context, compact BAM/CRAM checks, and nf-core/sarek handoff. | Full clinical interpretation still needs validated policy and signoff. |
| scRNA-seq post-count analysis | `scrna-seq-qc`, `ngs-scrna-seq` | Matrix-level QC, threshold justification, annotation, UMAPs, and review artifacts. | Tissue-specific annotation and malignant-cell calls need expert review. |
| Bulk RNA-seq FASTQ QC | `ngs-bulk-rnaseq-counts-qc`, `ngs-bulk-rnaseq` | FASTQ/sample-sheet/reference validation, MultiQC, Salmon matrices, and QC interpretation. | It prepares reusable count matrices; downstream biology still needs design-aware analysis. |
| Broad life-science research routing | `research-router-skill` | Classifying a research question, normalizing entities, selecting evidence lanes, and synthesizing findings. | It should not return an unsorted source dump or override failed sample QC. |
| Variant and genetics context | ClinVar, gnomAD, Ensembl, GWAS/OpenTargets-style skills | Variant normalization, pathogenicity context, population frequency, gene-disease evidence. | Public annotations can conflict and must be reconciled. |
| Cancer and translational context | CIViC, cBioPortal, ClinicalTrials.gov, literature skills | Cancer recurrence, clinical evidence, trial landscape, target context. | Not a treatment recommendation. |
| Expression and cell context | Human Protein Atlas, GTEx/Bgee/cellxgene-style skills | Normal-tissue expression, cell-type expression, off-tumor risk context. | RNA expression is not the same as surface protein abundance. |
| Pathway and protein context | UniProt, Reactome, STRING, GO, AlphaFold/PDB skills | Gene function, pathway role, protein context, mechanism summaries. | Mechanism supports interpretation; it does not prove sample-specific actionability. |
| Literature and dataset discovery | NCBI Entrez/PMC, BioStudies/ArrayExpress, NCBI Datasets | Finding papers, public datasets, validation candidates, and source evidence. | Currentness and study design quality must be checked each run. |

## Use Cases In This Directory

| Workflow | Use it when | Main output |
| --- | --- | --- |
| [Single-cell Modal/S3 platform](../scrna-platform.md) | You want reproducible public PBMC matrix QC, clustering, and calibration before using a larger cohort. | Preserved counts, QC and doublet decisions, UMAPs, calibration gates, and hash-verified S3 artifacts. |
| [HRD Workflow](hrd-workflow.md) | You want to assess HRD score readiness from WGS/WES tumor-normal data and integrate sample evidence with sourced HRR context. | HRD adapter status, no-call gates, evidence tables, and reviewer packet. |
| [Broad WGS Delta Workflow](broad-wgs-delta-workflow.md) | You want to ask what WGS adds beyond WES, including structural variants, breakpoints, allele-specific CNV/LOH, noncoding candidates, and mutational signatures. | WGS-vs-WES delta table, CNV/SV/signature boards, target-board updates, and reviewer packet. |
| [Pan-Target Discovery Workflow](target-discovery-workflow.md) | You want to rank ADC, bispecific, CDK12/13, CDK4/6, and other target hypotheses without overcalling WGS/WES evidence. | DNA target-locus evidence, candidate target board, orthogonal follow-up list, and reviewer packet. |
| [TROP-2 ADC Target Workflow](trop2-adc-workflow.md) | You want to evaluate whether TROP-2/`TACSTD2` is a plausible ADC target using bulk WES plus scRNA-seq. | WES target-locus evidence, scRNA target-expression evidence, external ADC context, and target-confidence class. |
| [Bulk RNA-seq TROP-2 Modal + S3](bulk-rna-trop2-modal-s3.md) | You want a custody-bound, single-sample `TACSTD2` transcript check on the Personalis ImmunoID tumor RNA data. | FastQC/MultiQC, BAM QA, two-BAM concordance, locus depth, review verdicts, a responsive evidence visualization, and an immutable S3 run envelope. |
| [Pan-cancer ADC Atlas v1](pan-cancer-adc-atlas-v1.md) | You want to rank ADC target hypotheses across harmonized TCGA tumors, GTEx normals, and public protein-context lanes. | A versioned target manifest, cohort aggregates, explicit evidence gates, and an interactive atlas. |
| [Modal + S3 + NGS plugin replication guide](modal-s3-ngs-plugin-replication.md) | You want to reproduce or extend the private TROP-2 analysis while preserving plugin routing, Workbench lifecycle, S3 custody, and Modal isolation. | Access prerequisites, direct and registered run procedures, recovery, verification, extension rules, and a reproducibility checklist. |
| [Modal + S3 + NGS prompt library](modal-s3-ngs-plugin-prompts.md) | You want copy-and-paste prompts for another analyst or Codex task using this repository and the authorized S3 inputs. | Prompts for intake, planning, execution, recovery, correction, new targets, transcript quantification, cohort comparison, optimization, visualization, and handoff. |
| [scRNA-seq Modal + S3 Kickoff](scrna-modal-s3-kickoff.md) | You want to prove the S3, Modal, Scanpy, and artifact-custody path on a small public 10x matrix before introducing cohort data. | H5AD, QC, clusters, markers, UMAP, checksummed artifact index, and run manifest. |

## Patterns From The Codex Life-Sciences Use Cases

The Codex life-sciences examples emphasize a consistent workflow shape:

- **Bulk RNA-seq FASTQ QC**: validate sample sheets, FASTQs, and references, then return MultiQC, quantification matrices, provenance, and a short QC interpretation before downstream analysis.
- **scRNA-seq post-count QC**: turn a matrix bundle into threshold-justified filtering summaries, annotations, UMAPs, and portable review artifacts that can be revised in the same thread.
- **Life Sciences collection**: use Codex/GPT-Rosalind to transform sequencing data into biological insights by connecting NGS execution with research synthesis.
- **GPT-Rosalind article**: combine sourced evidence retrieval, biological interpretation, and bioinformatics execution in one workspace while preserving artifacts and provenance for expert review.

For this project, those patterns translate into:

- never returning a bare score when an evidence board is needed;
- treating `ready`, `partial_evidence`, `no_call`, and `blocked` as first-class outputs;
- keeping sample-derived evidence separate from literature/database context;
- preserving run manifests, validation summaries, artifact indexes, and reviewer packets;
- using same-thread iteration to add missing files, metadata, references, or orthogonal validation.

## Project-Specific Boundaries

The current repo has strong public-data validation and reviewer-facing artifact patterns, but these Rosalind workflows are still operating guides.

Important boundaries:

- Diana-specific interpretation still requires Diana files, reference/pairing confirmation, tumor purity context, and reviewer signoff.
- WES can support small variants and limited copy-number hypotheses, but not genome-wide HRD signatures by itself.
- scRNA-seq can support target-expression and heterogeneity review, but ADC target suitability needs protein-level confirmation when possible.
- Public research evidence can support interpretation, but it cannot rescue failed sample QC or missing required inputs.
- High-cost WGS, large transfers, cloud execution, or package installation should require explicit approval.

## Recommended Output Layouts

Use consistent result roots so Rosalind-generated packets are easy to audit:

```text
results/rosalind_hrd/<sample_set>/<run_id>/
results/rosalind_targets/<sample_or_cohort>/<run_id>/
results/rosalind_trop2_adc/<sample_or_cohort>/<run_id>/
results/wgs_broad/<sample_or_cohort>/<run_id>/
```

Common files:

```text
run_manifest.json
input_evidence_index.json
sample_validation_summary.csv
research_context_sources.json
reviewer_packet.md
next_actions.md
```

The `input_evidence_index.json` should point back to existing `results/`, `manifests/`, and source URLs rather than copying large sequencing files.

## Source Material Read

These docs summarize patterns and details from:

- [Rosalind Workbench](https://developers.openai.com/blog/rosalind-workbench)
- [Codex Life Sciences collection](https://learn.chatgpt.com/use-cases/collections/life-sciences)
- [Bulk RNA-seq FASTQ QC use case](https://learn.chatgpt.com/use-cases/bulk-rna-seq-fastq-qc)
- [scRNA-seq post-count QC use case](https://learn.chatgpt.com/use-cases/scrna-seq-post-count-qc)
- [Life Science Research plugin](https://github.com/openai/plugins/tree/main/plugins/life-science-research)
- [Life Sciences NGS Analysis plugin](https://github.com/openai/plugins/tree/main/plugins/ngs-analysis)
- current project docs and artifacts under `docs/`, `manifests/`, and `results/`
