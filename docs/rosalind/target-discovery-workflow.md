# GPT-Rosalind Pan-Target Discovery Workflow

This workflow uses the existing Diana WES/WGS evidence lanes to build a ranked
follow-up board for ADC antigens, bispecific or immune-context markers,
DDR/transcriptional-CDK hypotheses, and CDK4/6 cell-cycle context.

## Boundary

WGS and WES can find genomic support or blockers: target-gene callability,
coding disruption, focal loss, copy gain, amplification, LOH/HLA-loss hints,
and pathway context. They cannot prove cell-surface target expression,
CDK-pathway dependency, phosphorylation state, antigen heterogeneity, or drug
response.

The packet must therefore preserve:

- `ready`: the lane's own required evidence passed.
- `partial_evidence`: useful sample evidence exists, but not enough for a
  claim.
- `no_call`: required evidence for that lane is missing or invalid.
- `blocked`: files, metadata, tools, approvals, or reviewer policy are
  missing.
- `not_supported`: reviewed sample evidence argues against the candidate.

## Target Families

| Family | Example genes | DNA questions | Missing v1 evidence |
| --- | --- | --- | --- |
| ADC / surface antigens | `TACSTD2`, `ERBB2`, `ERBB3`, `SLC39A6`, `NECTIN4`, `CD276`, `FOLR1`, `EGFR`, `F3` | callability, target disruption, focal loss, copy gain or amplification | RNA expression, IHC or other surface-protein confirmation, malignant-cell heterogeneity |
| Bispecific / immune context | `HLA-A`, `HLA-B`, `HLA-C`, `B2M`, `CD274`, `PDCD1`, `TNFRSF9`, `CD3E` | HLA loss, focal loss, coding disruption, immune-context copy state | cell-state expression, protein context, immune-pathology review |
| DDR / transcriptional CDK | `CDK12`, `CDK13`, `CCNK` | callability, disruption, loss, amplification, HRR context | expression, pathway dependency, trial-specific eligibility and reviewer policy |
| Cell-cycle / CDK4/6 context | `RB1`, `CCNE1`, `CDK4`, `CDK6`, `CCND1`, `CDKN2A`, `CDKN2B`, `PIK3CA`, `AKT1`, `PTEN`, `FGFR1`, `FGFR2`, `ESR1` | RB loss, cyclin-E/CDK2 bypass, PI3K or FGFR pathway context | clinical exposure, phospho-Rb/cyclin-E protein, endocrine context where relevant |

## Commands

Generate the curated target panel and an input template:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:target-template
```

Validate optional WGS/WES, RNA, protein, phospho-protein, pathology, or report
sidecars:

```sh
TARGET_DISCOVERY_INPUTS=manifests/target_discovery_inputs.csv \
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:target-inputs
```

Build the DNA-only board from validated per-gene target summaries:

```sh
TARGET_DISCOVERY_DNA_EVIDENCE=manifests/target_dna_evidence.csv \
PYTHONPATH=src /usr/bin/python3 -m diana_omics analyze:dna-targets
```

Build the Rosalind packet:

```sh
ROSALIND_TARGET_SAMPLE=diana ROSALIND_TARGET_RUN_ID=<run_id> \
PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-target-packet
```

## Output Contract

The packet is written under:

```text
results/rosalind_targets/<sample_or_cohort>/<run_id>/
```

Required outputs:

```text
run_manifest.json
input_evidence_index.json
sample_validation_summary.csv
dna_target_locus_summary.csv
candidate_target_board.csv
orthogonal_followup.csv
research_context_sources.json
reviewer_packet.md
next_actions.md
```

Each candidate row keeps `dna_status`, `rna_status`, and `protein_status`
separate. DNA-only surface-antigen rows may reach `partial_evidence`, but RNA
and protein stay `no_call` until supplied. CDK12/13 and CDK4/6 rows are
follow-up context unless the sample, pathway, clinical, and sourced evidence
lanes all pass a future locked policy.

## Research Enrichment

Public context is added after sample evidence exists and is recorded in
`research_context_sources.json`.

- Use UniProt, Ensembl, Reactome, STRING, and GO for target identity and
  pathway context.
- Use Human Protein Atlas, Bgee, GTEx, and cellxgene-style resources for tumor
  and normal expression context.
- Use cBioPortal, CIViC, ClinicalTrials.gov, PubMed, and PMC for cancer,
  clinical, and CDK12/13 or CDK4/6-resistance literature.

External ADC, bispecific, or CDK-drug context cannot override a failed sample
lane.
