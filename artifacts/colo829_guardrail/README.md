# COLO829 Guardrail Artifact Root

This materialized artifact root supports bounded Rosalind HRD packet cloud runs for `colo829`.

It contains only small known-answer summary JSON files needed by `build:rosalind-hrd-packet` when `ROSALIND_HRD_ARTIFACT_ROOT` is set to this directory. It does not contain BAM, FASTQ, CRAM, VCF, BED, or raw human sequence data.

Allowed packet conclusion: COLO829 is an independent tumor-normal and driver-recovery guardrail. It does not establish HRD status until full SV/CNA/signature evidence is generated and benchmarked.

## Files

| Path | SHA-256 |
| --- | --- |
| `results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_hiseqx.json` | `77dc3e9f2d43529906d683452c27145243bc5c4c21c112fff7ba374da18ad9ab` |
| `results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_pacbio_sequel.json` | `543300e07c1bf353e5c26ae58ea9b8ade22a1aea42b62fd627e085a2b78d703f` |
| `results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_ont_minion.json` | `0bd1be0bee08ddaa51cc4f1997d3a734ebb4ffe94552b89c61519d67d2044d8a` |
| `results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_novaseq_phased.json` | `3908625ac1bae166b94ac960f130575f1cf0bd67d219bb15a72ba8307bb84cf3` |
| `results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json` | `006f2a783815a185c25056ed968bedaaee839e85c9b65fced9fb8ca0a79326b1` |
| `results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json` | `854808e69d1b7a13c25d8be794c746c7f5a6d69e8f6c0098ced5af19f029a717` |
| `results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_illumina.json` | `1dd54878d98c6a577a0b597d802155069114951d103f17d8cbe7cad9532bcd92` |
| `results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_long_read.json` | `a3905309717605277838a2248491e919aa8e27d0b72d35f12a82adace5c9ffa0` |
| `results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json` | `9885c77c61f453b7a1cad3dcf037c540563023017dcfecc590797c93e878bf13` |

## Local Smoke

```sh
ROSALIND_HRD_SAMPLE_SET=colo829 ROSALIND_HRD_ARTIFACT_ROOT=artifacts/colo829_guardrail ROSALIND_HRD_RUN_ID=colo829-guardrail-materialized-YYYYMMDD PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

## Cloud Smoke

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set colo829 --artifact-root-rel artifacts/colo829_guardrail --run-id cloud-colo829-guardrail-YYYYMMDD
```
