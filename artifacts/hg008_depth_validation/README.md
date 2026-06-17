# HG008 Depth Validation Artifact Root

This materialized artifact root supports bounded Rosalind HRD packet cloud runs for `hg008`.

It contains only small known-answer summary JSON files needed by `build:rosalind-hrd-packet` when `ROSALIND_HRD_ARTIFACT_ROOT` is set to this directory. It does not contain BAM, FASTQ, CRAM, VCF, BED, or raw human sequence data.

Allowed packet conclusion: HG008 is a truth-set validation sample. It can improve confidence in caller correctness and CNV/SV benchmarking, but it must not produce a Diana-style HRD interpretation.

## Files

| Path | SHA-256 |
| --- | --- |
| `results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json` | `4f838974d39688e48f4d2e5db322154cd2a4b52a1a15309b7d535f6001358120` |
| `results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json` | `b6b0366bcb9607e8ee2f2cf63fc59f62ddf0a0987a0ea229a223371c64fe4c46` |
| `results/clinicalization/known_answer_runs/expanded_cohort/hg008_sv_truth_asset.json` | `19bfce3c3927bc15b76b254e0e88018f198a35dd5c4f8e72aa6d5d72eb5dee20` |
| `results/clinicalization/known_answer_runs/expanded_cohort/hg008_rna_stats.json` | `8216356006c09e48a2fcd34be2ddfc63ef1fdcd51cbe89ef3acc04361a5b2a54` |
| `results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json` | `28db0e7af234656cb1267710d373c0f5efe0fdedadf44791fc7bd3e10e855a9b` |

## Local Smoke

```sh
ROSALIND_HRD_SAMPLE_SET=hg008 ROSALIND_HRD_ARTIFACT_ROOT=artifacts/hg008_depth_validation ROSALIND_HRD_RUN_ID=hg008-depth-materialized-YYYYMMDD PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

## Cloud Smoke

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set hg008 --artifact-root-rel artifacts/hg008_depth_validation --run-id cloud-hg008-depth-YYYYMMDD
```
