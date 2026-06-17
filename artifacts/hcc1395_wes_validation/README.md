# HCC1395 WES Validation Artifact Root

This directory is a small materialized artifact root for the SEQC2/HCC1395 WES Rosalind HRD readiness packet. It contains only committed summary outputs used by the packet builder, not FASTQ, BAM, VCF, reference, or raw benchmark files.

## Contents

| Source artifact | SHA-256 |
| --- | --- |
| `results/full_wes_benchmark/full_wes_benchmark_summary.json` | `eee7a120d93a14769799d463087827c25ab211bd524cf597b947ad45c43cfd18` |
| `results/full_wes_benchmark/truth_overlap_benchmark_summary.json` | `8181f5b85543592315a1511517ef755f0d66efc0b726e2ab52279c3db8f555f0` |
| `results/full_wes_benchmark/full_wes_fastq_validation.csv` | `00b280d57d5eda6e808d332df046be45a829a7ec8af72d55234b29dadbe71e0e` |
| `results/full_wes_benchmark/full_wes_bam_validation.csv` | `ebd0045b1cb6e1b1ecc115c836d7afe09d18a58aa6cea8311a682e1380fe421a` |
| `results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wes_summary.json` | `6fcd346362f9b74932e1951f4d00dc9487bd907e251113bba624716130da6cee` |

## Local Smoke

```sh
ROSALIND_HRD_SAMPLE_SET=hcc1395_wes ROSALIND_HRD_ARTIFACT_ROOT=artifacts/hcc1395_wes_validation ROSALIND_HRD_RUN_ID=hcc1395-wes-materialized-20260617 PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

Expected packet result: HCC1395 WES has 5 evidence rows and 6 adapter rows. FASTQ/BAM validation and Mutect2 truth overlap are present, while genome-wide HRD adapters remain no-call because WES does not provide allele-specific CNV/LOH, SV, SBS3, scarHRD, CHORD, or HRDetect-style evidence.

## Cloud Smoke

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics aws:hrd-packet:cloud-submit -- --sample-set hcc1395_wes --artifact-root-rel artifacts/hcc1395_wes_validation --run-id cloud-hcc1395-wes-20260617
```

Use this root to prove the WES packet builder path in AWS Batch without uploading local generated sequencing outputs.
