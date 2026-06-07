# Wiki Source Summary

The starting point for this project was the Diana omics wiki content in:

```text
../diana-tnbc/obsidian/wiki/omics
```

The wiki packet established the project boundary:

- HRD is clinically relevant but should not be inferred casually.
- Tumor-normal DNA is central.
- RNA can add subtype, fusion, and expression context.
- Public validation must come before Diana-specific interpretation.
- Findings should be staged for expert review, not treated as direct treatment instructions.

## Translation Into This Repo

The wiki question became four engineering requirements:

1. Build a reproducible public validation workflow.
2. Keep raw-data and processed-data claims separate.
3. Make Diana's future file handoff explicit.
4. Document every caveat that could change interpretation.

## What The Wiki Did Not Provide

The wiki did not provide Diana's raw FASTQ/BAM/CRAM files. It also did not provide a clinical companion-diagnostic HRD result. Those remain external inputs.

## Current Handoff

Use:

- `docs/DIANA_RAW_INPUTS.md`
- `manifests/diana_raw_inputs.template.csv`
- `results/diana_raw_intake/input_contract.json`

The project is ready to validate and stage Diana raw paths when they arrive.
