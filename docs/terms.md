# Terms

This glossary defines the project vocabulary used by commands, docs, manifests, and verifier outputs.

## Workflow Terms

- Command: a public CLI action such as `verify:outputs` or `fetch:phase3-wgs`.
- Command family: a group of related commands in `src/diana_omics/commands/`, mirrored in CLI help.
- Task alias: a higher-level command in `workflow_tasks.py` that may run one or more commands or external tools.
- Verifier: a command that checks required files, columns, statuses, and readiness fields, then exits nonzero on drift.
- Artifact: a generated file under `results/`, `manifests/`, or another documented output path.
- Manifest: a structured input or contract file, usually CSV or JSON, that declares samples, sources, policies, or gates.

## Evidence Terms

- Smoke check: a small bounded run that proves plumbing and file semantics, not biological sensitivity.
- Benchmark: a run against expected-answer data, performance data, or both.
- Known-answer dataset: a truth-set-backed sample where expected variants or properties are externally defined.
- Truth set: the authoritative expected answer used to measure recall, precision, or feature readiness.
- Orthogonal validation: independent public examples beyond the first SEQC2/HCC1395 workflow.
- Full-source run: a run that consumes the complete public source files required by the acceptance gate.
- Developer subset: a bounded run controlled by settings such as `PHASE3_WGS_READS`; useful for iteration, not acceptance.

## Domain Terms

- HRD: homologous recombination deficiency, inferred from multiple DNA repair and genomic-instability signals.
- HRR: homologous recombination repair genes and events, including BRCA1/BRCA2 and related pathway genes.
- WES: whole-exome sequencing, useful for coding SNVs/indels and limited copy-number evidence.
- WGS: whole-genome sequencing, preferred for genome-wide CNV, SV, mutational signatures, and MRD panel design.
- WTS or RNA-seq: transcriptome sequencing for expression, subtype, fusion, and context evidence.
- Tumor-normal: matched tumor DNA compared with normal DNA to separate somatic events from germline/background signal.
- ctDNA/MRD: circulating tumor DNA and molecular residual disease workflows, usually downstream of tumor-informed design.

## Project-Specific Terms

- Diana intake: template, validation, and staging work for future Diana raw files.
- Clinical readiness: gates that must pass before outputs could support a clinical validation packet.
- Clinicalization: the work of turning a research-capable workflow into controlled, reviewable clinical evidence.
- Phase 3 WGS: the full-source SEQC2/HCC1395 WGS acceptance gate and related resumable stage workflow.
- Phase 4: future Diana raw-file recompute after actual data arrive.
- Reviewer packet: the human-facing summary that collects evidence tables, caveats, and readiness status.
