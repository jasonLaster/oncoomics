# Documentation

This directory is organized for a new reader who wants the project shape first and run details only when needed.

## Recommended Path

1. Read the top-level [README](../README.md) for the project summary and boundary.
2. Read [status/current-state.md](status/current-state.md) for the evidence gates, current results, and open gaps.
3. Read [validation/known-answer-datasets.md](validation/known-answer-datasets.md) for the public samples that prove or stress the pipeline.
4. Read [operations/analytics-sequence.md](operations/analytics-sequence.md) for the system sequence diagram and OSS call map.
5. Read [data/source-map.md](data/source-map.md) when you need provenance for datasets, tools, truth sets, or vendor context.
6. Read [operations/running-the-pipeline.md](operations/running-the-pipeline.md) only if you plan to run local, Docker, Nextflow, or AWS workflows.

## Folder Map

| Folder | Contents |
| --- | --- |
| `status/` | Current state, phase plan, pass/fail evidence, and next work. |
| `validation/` | Known-answer datasets and what each one can prove. |
| `operations/` | Running the pipeline, Diana raw input handoff, Nextflow, Docker, AWS, logs, and compute notes. |
| `data/` | Source provenance, wiki handoff, reference-panel label rules. |
| `clinical/` | Risk register, clinicalization notes, and validation-packet scaffolding. |

## Concepts

- **HRD:** homologous recombination deficiency. Useful evidence can include HRR gene damage, biallelic loss, copy-number scars, SBS3-like signatures, rearrangement patterns, and RNA context.
- **Tumor-normal analysis:** compares tumor DNA with matched normal DNA to separate somatic variants from germline variants and artifacts.
- **WES:** whole-exome sequencing. Good for coding SNVs/indels and limited copy-number context.
- **WGS:** whole-genome sequencing. Better for HRD signatures, CNV, SV, mutational signatures, and tumor-informed MRD panel design.
- **WTS/RNA-seq:** transcript context. Useful for subtype, expression, and fusions, but not a direct HRD truth source.
- **Truth set:** a known-answer dataset used to show the pipeline returns the expected answer, not just that it finishes.
