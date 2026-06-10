# Documentation Guide

This directory explains what the Diana HRD omics project does, why it exists, how to run it, and where it can be wrong.

## One-Sentence Summary

The project validates a Python tumor-normal omics workflow on public reference data now, so Diana's future raw DNA/RNA files can be plugged in later without inventing the analysis under time pressure.

## Concepts

HRD means homologous recombination deficiency. In practice, this project looks for evidence that DNA double-strand break repair is impaired. Useful signals can include damaging BRCA1/BRCA2/HRR events, biallelic loss, scar-like copy-number patterns, SBS3-like mutational signatures, rearrangement patterns, and related RNA context.

Tumor-normal analysis compares tumor DNA against matched normal DNA. This is critical because many variants in a tumor file are inherited germline variants or technical artifacts. A matched normal helps remove those.

WES is whole-exome sequencing. It is useful for coding SNVs/indels and some copy-number inference, but it is limited for genome-wide signatures and structural variation.

WGS is whole-genome sequencing. It is the better input for HRD signatures, CNV, SV, mutational signatures, and tumor-informed MRD panel design, but it is more expensive to compute.

WTS or RNA-seq measures transcript abundance and expressed rearrangements. It can support subtype/fusion/context interpretation, but RNA alone should not be treated as a direct HRD truth source.

ctDNA/MRD analysis looks for tumor-derived DNA in plasma. Tumor-informed assays use tumor/normal sequencing first to select patient-specific variants, then test plasma for those variants. Public, open MRD truth data are much harder to find than public tumor-normal WGS truth data.

Truth sets are known-answer datasets. They are the only way to show that a pipeline is not just finishing, but returning the expected answer.

For command, evidence, and domain vocabulary, see [terms.md](terms.md).

## Documentation Map

| Document | Use it when you need to... |
| --- | --- |
| [terms.md](terms.md) | Decode command names, evidence gates, and domain vocabulary. |
| [status/current-state.md](status/current-state.md) | Check what has passed, what is partial, and what is blocked. |
| [validation/known-answer-datasets.md](validation/known-answer-datasets.md) | Choose public truth-set datasets and understand validation priorities. |
| [clinical/risk-register.md](clinical/risk-register.md) | Review likely bugs or failure modes before trusting results. |
| [clinical/orchestration.md](clinical/orchestration.md) | Understand the clinical-readiness gates and sequencing. |
| [clinical/validation-packet-template.md](clinical/validation-packet-template.md) | Draft or review the clinical validation packet structure. |
| [operations/diana-raw-inputs.md](operations/diana-raw-inputs.md) | Prepare Diana's real raw files for validation and staging. |
| [operations/vendor-normalization.md](operations/vendor-normalization.md) | Normalize Personalis/Natera WES/WGS deliverables into the common TCGA format and filter to TCGA standards. |
| [rosalind/README.md](rosalind/README.md) | Understand how GPT-Rosalind, NGS Analysis, and Life Science Research would integrate with this project. |
| [rosalind/hrd-workflow.md](rosalind/hrd-workflow.md) | Review the GPT-Rosalind workflow for HRD evidence and score readiness from WGS/WES. |
| [rosalind/trop2-adc-workflow.md](rosalind/trop2-adc-workflow.md) | Review the GPT-Rosalind workflow for TROP-2 ADC target assessment from bulk WES and scRNA-seq. |
| [operations/running-the-pipeline.md](operations/running-the-pipeline.md) | Run local, Docker, Nextflow, and AWS workflows. |
| [operations/analytics-sequence.md](operations/analytics-sequence.md) | See the systems architecture for analytics orchestration and OSS tool calls. |
| [data/source-map.md](data/source-map.md) | Audit dataset, truth-set, tool, and vendor-context sources. |
| [data/wiki-source-summary.md](data/wiki-source-summary.md) | Understand the original Diana wiki scope. |
| [data/reference-panel-label-rules.md](data/reference-panel-label-rules.md) | Review Phase 1 label rules and caveats. |
| [../src/README.md](../src/README.md) | Work on the Python package, command modules, tests, and verifier contracts. |

## New Reader Path

1. Read this file.
2. Skim [terms.md](terms.md) for project vocabulary.
3. Run `PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs` to confirm generated artifacts are internally complete.
4. Read [status/current-state.md](status/current-state.md) to see what has actually passed.
5. Read [clinical/risk-register.md](clinical/risk-register.md) before trusting any biological interpretation.
6. Read [operations/diana-raw-inputs.md](operations/diana-raw-inputs.md) before plugging in Diana's files.

## Command Pattern

Every workflow command is available through Python:

```sh
PYTHONPATH=src python3 -m diana_omics verify:outputs
```

Task aliases use the same Python entry point:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
```

There is no separate JavaScript task runner in this repository.
