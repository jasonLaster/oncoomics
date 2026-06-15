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

## Documentation Map

| Document | Use it when you need to... |
| --- | --- |
| [project-plan.md](/Users/jasonlaster/src/projects/diana-omics/docs/project-plan.md) | Understand the evidence-gate plan and remaining work. |
| [phase-status.md](/Users/jasonlaster/src/projects/diana-omics/docs/phase-status.md) | Check what has passed, what is partial, and what is blocked. |
| [bug-audit.md](/Users/jasonlaster/src/projects/diana-omics/docs/bug-audit.md) | Review likely bugs before trusting results. |
| [diana-raw-inputs.md](/Users/jasonlaster/src/projects/diana-omics/docs/diana-raw-inputs.md) | Prepare Diana's real raw files for validation and staging. |
| [raw-data-readiness.md](/Users/jasonlaster/src/projects/diana-omics/docs/raw-data-readiness.md) | See the public FASTQ/WES/WGS readiness ladder. |
| [orthogonal-validation-samples.md](/Users/jasonlaster/src/projects/diana-omics/docs/orthogonal-validation-samples.md) | Choose additional known-answer datasets and inspect the 10-target pull plan. |
| [phase3-parallel-compute.md](/Users/jasonlaster/src/projects/diana-omics/docs/phase3-parallel-compute.md) | Tune CPU/thread usage for large WGS runs. |
| [python-implementation.md](/Users/jasonlaster/src/projects/diana-omics/docs/python-implementation.md) | Work on Python commands, tests, and verifier contracts. |
| [source-map.md](/Users/jasonlaster/src/projects/diana-omics/docs/source-map.md) | Audit dataset, tool, truth-set, and vendor-context sources. |
| [wiki-source-summary.md](/Users/jasonlaster/src/projects/diana-omics/docs/wiki-source-summary.md) | Understand the original Diana wiki scope. |
| [reference-panel-label-rules.md](/Users/jasonlaster/src/projects/diana-omics/docs/reference-panel-label-rules.md) | Review Phase 1 label rules and caveats. |

## New Reader Path

1. Read this file.
2. Run `PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs` to confirm generated artifacts are internally complete.
3. Read [phase-status.md](/Users/jasonlaster/src/projects/diana-omics/docs/phase-status.md) to see what has actually passed.
4. Read [bug-audit.md](/Users/jasonlaster/src/projects/diana-omics/docs/bug-audit.md) before trusting any biological interpretation.
5. Read [diana-raw-inputs.md](/Users/jasonlaster/src/projects/diana-omics/docs/diana-raw-inputs.md) before plugging in Diana's files.

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
