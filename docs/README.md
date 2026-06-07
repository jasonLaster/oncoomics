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

- [PROJECT_PLAN.md](/Users/jasonlaster/src/projects/diana-omics/docs/PROJECT_PLAN.md): what remains to do.
- [PHASE_STATUS.md](/Users/jasonlaster/src/projects/diana-omics/docs/PHASE_STATUS.md): current completion status and evidence.
- [BUG_AUDIT.md](/Users/jasonlaster/src/projects/diana-omics/docs/BUG_AUDIT.md): bug risks, mitigations, and missing verifiers.
- [PYTHON_IMPLEMENTATION.md](/Users/jasonlaster/src/projects/diana-omics/docs/PYTHON_IMPLEMENTATION.md): command and package architecture.
- [DIANA_RAW_INPUTS.md](/Users/jasonlaster/src/projects/diana-omics/docs/DIANA_RAW_INPUTS.md): how to provide Diana's files.
- [RAW_DATA_READINESS.md](/Users/jasonlaster/src/projects/diana-omics/docs/RAW_DATA_READINESS.md): public representative raw-data ladder.
- [ORTHOGONAL_VALIDATION_SAMPLES.md](/Users/jasonlaster/src/projects/diana-omics/docs/ORTHOGONAL_VALIDATION_SAMPLES.md): next known-answer reference samples.
- [PHASE3_PARALLEL_COMPUTE.md](/Users/jasonlaster/src/projects/diana-omics/docs/PHASE3_PARALLEL_COMPUTE.md): local CPU and full-depth parallelization strategy.
- [SOURCE_MAP.md](/Users/jasonlaster/src/projects/diana-omics/docs/SOURCE_MAP.md): source datasets and external references.
- [WIKI_SOURCE_SUMMARY.md](/Users/jasonlaster/src/projects/diana-omics/docs/WIKI_SOURCE_SUMMARY.md): how the original Diana wiki packet shaped the project.

## New Reader Path

1. Read this file.
2. Run `bun run verify:outputs` to confirm generated artifacts are internally complete.
3. Read [PHASE_STATUS.md](/Users/jasonlaster/src/projects/diana-omics/docs/PHASE_STATUS.md) to see what has actually passed.
4. Read [BUG_AUDIT.md](/Users/jasonlaster/src/projects/diana-omics/docs/BUG_AUDIT.md) before trusting any biological interpretation.
5. Read [DIANA_RAW_INPUTS.md](/Users/jasonlaster/src/projects/diana-omics/docs/DIANA_RAW_INPUTS.md) before plugging in Diana's files.

## Command Pattern

Every workflow command is available through Python:

```sh
PYTHONPATH=py/src python3 -m diana_omics verify:outputs
```

The same command usually has a Bun alias:

```sh
bun run verify:outputs
```

Bun is only a task runner. It does not contain workflow logic.
