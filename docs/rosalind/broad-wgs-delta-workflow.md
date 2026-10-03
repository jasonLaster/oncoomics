# Broad WGS Delta Workflow

## Summary

This workflow builds a reviewer-ready **whole-genome delta packet** from
tumor/normal WGS. Its central question is:

> What did WGS reveal that WES could not have shown?

The WGS delta packet sits next to the existing HRD and pan-target Rosalind
packets:

```text
results/wgs_broad/<sample_or_cohort>/<run_id>/
```

WGS can add evidence for full-genome somatic variants, structural variants,
breakpoints, allele-specific copy number, copy-neutral LOH, and mutational
signatures. It should not be treated as a clinical therapy selector by itself.

In Diana's current case, the first high-value questions are:

- Does the known somatic `BRCA1 NM_007294.4:c.81-1G>A` splice event have
  locus-specific LOH, focal loss, or an SV-supported second hit?
- Are there breakpoints, exon-level events, or complex rearrangements that WES
  could not have seen?
- Do target-discovery genes such as `TACSTD2`, `ERBB2`, HLA, `B2M`, `RB1`,
  `CCNE1`, `CDK12`, or `CDK13` show WGS-supported amplification, loss,
  LOH, or disruption?
- Is the genome-wide callset strong enough to attempt SBS96, SBS3, CHORD,
  HRDetect-style, or scarHRD adapters, or should those lanes remain
  explicit `no_call` outputs?

## Boundary

The packet is a **research-use evidence board**, not a clinical report.

- A WGS-supported `BRCA1` second hit can strengthen an HRD hypothesis, but
  HRD and PARP claims still require locked QC thresholds, known-answer
  performance, adapter validation, and reviewer signoff.
- A WGS-supported target copy gain or disruption updates the target board, but
  it does not prove RNA expression, cell-surface protein abundance, pathway
  dependence, or drug sensitivity.
- HLA loss, `B2M` disruption, `RB1` loss, and `CCNE1` amplification are
  routing or resistance-context findings until interpreted with orthogonal
  assays and clinical history.
- Any high-impact variant, focal CNA, SV, or noncoding candidate that could
  influence care must be manually reviewed before leaving the research lane.

## What WGS Adds

| Lane | WGS-only or WGS-strong evidence | WES limitation |
| --- | --- | --- |
| Full-genome SNV/indel | Coding, intronic, UTR, promoter, and intergenic somatic variants with a genome-wide callable denominator. | WES captures coding intervals and nearby splice regions; most regulatory and deep intronic regions are absent. |
| Allele-specific CNV/LOH | Total copy, minor copy, purity, ploidy, focal loss, high-level amplification, copy-neutral LOH, and HRD-compatible scar segments. | WES copy number is capture-biased and usually weaker for allele-specific LOH and scar metrics. |
| SV and breakpoints | Inversions, translocations, focal deletions, foldbacks, complex rearrangements, enhancer/promoter swaps, and exon disruptions. | Exomes generally miss intergenic breakpoints and cannot provide rearrangement signatures. |
| Mutational signatures | SBS96, indel spectra, rearrangement signatures, and integrated HRD features from the full genome. | WES can be underpowered or biased for full-genome signatures. |
| HLA and immune escape | HLA locus LOH, antigen-presentation gene disruption, `CD274` copy gain, and WGS-supported immune blockers. | HLA is difficult in WES and often needs specialized typing/LOH callers. |
| Target board delta | Amplification, focal deletion, LOH, or SV disruption across ADC, bispecific, immune, DDR, and cell-cycle genes. | WES may miss noncoding breakpoints and is weaker for focal copy context. |

## Inputs

The first production-shaped run should freeze:

- tumor and matched-normal WGS BAM/BAI or lane FASTQ inputs;
- SHA-256 for every materialized local object;
- S3 URI, byte count, ETag, and version ID where available;
- reference FASTA, `.fai`, `.dict`, and contig compatibility receipt;
- Mutect2 germline resource and panel of normals;
- known sample aliases, pair ID, assay, role, read group, and reference ID;
- optional WTS/RNA BAMs for expressed-junction support;
- optional WES or vendor reports for cross-assay concordance.

Mixed reference builds, mismatched sample IDs, absent indexes, or unpaired tumor
data block downstream interpretation. Public or vendor drug context must stay
separate from sample evidence.

## Evidence Stages

### 0. Input Freeze

Write an immutable intake envelope before compute-heavy work:

- `run_manifest.json`
- `input_evidence_index.json`
- `raw_object_inventory.csv`
- `sample_validation_summary.csv`
- `forbidden_token_inventory.json`

The run must bind every local CSV, JSON, VCF-derived table, and packet input to
a SHA-256 digest.

### 1. QC and Callability

Run whole-genome BAM QC before interpreting calls:

- `samtools flagstat`, `idxstats`, and `stats`
- depth distribution and callable intervals
- duplicate rate and insert-size review
- tumor/normal fingerprint concordance
- contamination and orientation-bias inputs for somatic filtering
- per-locus callability for HRR, HLA, `B2M`, ADC, CDK, and cell-cycle genes

Uncallable loci become `no_call`, not wild type.

### 2. Small Variants

Run full-genome tumor-normal Mutect2 or an equivalent locked somatic caller:

1. Scatter by contig or interval.
2. Use reference-matched germline resources and a panel of normals.
3. Estimate contamination.
4. Apply orientation-bias and `FilterMutectCalls` filters.
5. Normalize the filtered VCF.
6. Annotate transcript, splice, ClinVar, COSMIC, CIViC, population frequency,
   and target-manifest overlaps.

The output should include:

- `somatic_small_variants.vcf.gz`
- `somatic_small_variants.maf`
- `driver_variant_candidates.csv`
- `noncoding_variant_candidates.csv`
- `known_variant_concordance.csv`

The concordance table must explicitly reconcile the known `BRCA1` splice event
and any provisional prior calls, rather than silently replacing earlier
evidence.

### 3. Allele-Specific CNV and LOH

Run Sequenza first because the current Modal scarHRD path already executes that
model shape. Add FACETS or ASCAT as an orthogonal lane when feasible.

Required fields:

- purity and ploidy
- segment total copy and minor copy
- focal loss, homozygous deletion, high-level amplification, and copy-neutral
  LOH calls
- gene-overlap rows for HRR, HLA, ADC, DDR/CDK, and cell-cycle genes
- `BRCA1` and `BRCA2` second-hit status

Only allele-specific, QC-passing segments can feed scarHRD. Five-megabase
coverage bins cannot substitute for scarHRD inputs.

### 4. Structural Variants and Breakpoints

Run a locked tumor-normal SV caller and emit both VCF and BEDPE:

- Manta as the practical first pass
- GRIDSS, SvABA, or another caller only when a breakpoint needs arbitration
- AnnotSV, VEP structural-variant annotation, or equivalent gene-disruption
  annotation
- IGV snapshots for high-impact candidates

The first review queue should prioritize:

- `BRCA1`, `BRCA2`, `PALB2`, `RAD51C`, `RAD51D`
- HLA and `B2M`
- `RB1`, `CDKN2A`, `CDKN2B`
- `ERBB2`, `TACSTD2`, `FOLR1`, `CD276`
- expressed fusion or junction support in the ImmunoID RNA BAM

### 5. Mutational Signatures

Use the full filtered genome:

- SBS96 matrix from PASS SNVs
- SigProfilerAssignment or a locked equivalent
- CHORD only after SNV, indel, SV, and CNV feature inputs are present
- HRDetect-style scoring only after the complete calibrated feature vector is
  available
- scarHRD only after allele-specific segments pass their own gate

Every adapter reports `ready`, `partial_evidence`, `no_call`, `blocked`, or
`not_supported`. Missing SV, CNV, or signature inputs must stay `no_call`.

### 6. HLA and Immune Escape

Run HLA typing and HLA LOH when the input build and tool assumptions line up.
Review `B2M`, `JAK1`, `JAK2`, `TAP1`, `TAP2`, `ERAP1`, `ERAP2`, and `CD274`
across small variants, CNV, LOH, and SV.

Immune-escape rows should route bispecific and T-cell-engager hypotheses. They
should not be emitted as ADC antigen calls.

### 7. WGS-Versus-WES Delta

Normalize WES, WGS, and vendor report events into one table and label each
finding:

- `shared_with_wes`
- `wgs_only`
- `wes_only_not_callable`
- `wes_only_discordant`
- `orthogonal_report_match`
- `not_reviewed`

For every WGS-only event, state whether the WES miss is explained by a
noncoding locus, a breakpoint, capture limitations, a copy-neutral LOH event,
or missing assay evidence.

### 8. Target Update

Join the broad WGS evidence back to
`manifests/target_discovery_candidates.csv`.

Acceptable target updates include:

- `amplification`
- `copy_gain`
- `focal_loss`
- `copy_neutral_loh`
- `coding_disruption`
- `splice_disruption`
- `sv_disruption`
- `hla_loss`

Prohibited WGS-only updates include:

- `TROP-2 positive`
- `HER2 positive`
- `CDK12 inhibitor sensitive`
- `CDK4/6 resistant`
- `response predicted`
- `treatment recommendation`

## Packet Contract

`results/wgs_broad/<sample_or_cohort>/<run_id>/` writes:

```text
run_manifest.json
input_evidence_index.json
sample_validation_summary.csv
qc_callability_summary.csv
known_variant_concordance.csv
somatic_small_variant_summary.csv
noncoding_variant_candidates.csv
gene_cnv_loh_summary.csv
brca_second_hit_summary.csv
somatic_sv_summary.csv
breakpoint_review_queue.csv
mutational_signature_summary.csv
hla_immune_escape_summary.csv
wgs_vs_wes_delta.csv
target_discovery_wgs_delta.csv
manual_review_queue.csv
research_context_sources.json
reviewer_packet.md
care_team_summary.md
next_actions.md
```

## Runtime Plan

The first full run can execute on Modal with S3-mounted or S3-staged inputs:

1. Copy BAMs or FASTQs from S3 to local NVMe.
2. Run CPU-heavy BAM QC, CNV, SV, signature, annotation, and packet jobs in
   restartable shards.
3. Run full-genome small variants either CPU-scattered on Modal or on AWS P5
   with Parabricks once quota and the pinned image are available.
4. Persist every shard and final table back to private S3 with checksums.

Approximate cost and wall time:

| Run shape | Wall time | Cloud compute |
| --- | ---: | ---: |
| Existing validated BAMs | 8-20h | $150-$500 |
| Start from compressed WGS FASTQs | 18-36h | $300-$900 |
| AWS P5 plus Parabricks Mutect2 | 8-18h after quota | $250-$700 |
| Reviewer-grade known-answer validation | 3-6 days | $1,200-$3,500 |

The fastest useful slice should cap the run at roughly 24 hours and include:

1. input freeze;
2. BAM QC and callability;
3. small variants;
4. Sequenza CNV/LOH;
5. Manta SV;
6. `BRCA1`/`BRCA2` second-hit table;
7. target-gene CNV/SV delta;
8. packet assembly.

Signature, HLA, and integrated HRD adapters can remain explicit `no_call` lanes
until their required feature classes pass.

## Acceptance Gates

- Reject duplicate or mutable packet inputs.
- Reject missing or uncallable high-impact loci before interpretation.
- Reject SV conclusions without VCF/BEDPE evidence.
- Reject scarHRD if the segment file is not allele-specific.
- Reject CHORD and HRDetect-style calls unless small-variant, CNV/LOH, SV, and
  signature features all pass locked adapters.
- Reject target-board rows that launder DNA copy state into RNA or protein
  positivity.
- Require IGV/manual review for every candidate that could change clinical
  discussion.

## Follow-Up

After the first WGS delta packet exists:

1. run HG008 and COLO829 known-answer WGS through the same small-variant,
   SV, CNV, and signature contracts;
2. calculate small-variant precision/recall and SV/CNV reciprocal overlap;
3. tune no-call thresholds from validation behavior;
4. rerun the patient packet under the locked policy;
5. add the validated WGS delta into the HRD and pan-target Rosalind packets.
