# SEQC2/HCC1395 WGS Evidence-Surface Artifact Root

This materialized artifact root supports bounded Rosalind HRD packet runs for
`hcc1395_wgs`.

It contains the small summaries and evidence tables from the June 12, 2026
full-source SEQC2/HCC1395 WGS validation. It is intended for cheap
post-deterministic experimentation: the packet builder can read these archived
outputs without touching the live Diana WGS AWS Batch run, rerunning FASTQ
alignment, or transferring large BAM/FASTQ files.

Allowed packet conclusion: HCC1395 WGS exercises WGS evidence surfaces for HRD
review. It remains a partial HRD evidence packet until allele-specific CNV/LOH,
production SV calls, signature thresholds, CHORD/scarHRD/HRDetect policy, and
known-answer performance are locked.

## Validation signals

- Full-source SEQC2/HCC1395 WGS FASTQs: `568040077` read pairs per end.
- BAM validation: passed.
- GATK Mutect2 WGS truth-interval comparison: `268` exact PASS truth matches
  across `300` depth-eligible SEQC2 truth variants.
- Coverage-CNV plumbing: `631` 5 Mb bins.
- SBS96 matrix plumbing: `265` usable SNV records.
- SV evidence plumbing: passed for both tumor and normal BAMs.
- HRD adapter readiness: all scalar or categorical HRD adapters stay `no_call`
  behind missing allele-specific CNV/LOH, missing production SV calls, and
  unlocked signature and integrated-model thresholds.

## Core files

| Path | SHA-256 |
| --- | --- |
| `results/phase3_wgs_smoke/phase3_wgs_summary.json` | `88c19f090cf2c96e585a4dff591d2ac2cb3c0d34b0ae39fe3e93fd53ec1c0686` |
| `results/phase3_wgs_smoke/bam_validation_summary.json` | `1aefb7242db5f2f52ed03093ea3e80f50fc355d591e0b323a118b2645e3d80b9` |
| `results/phase3_wgs_smoke/mutect2_wgs_summary.json` | `3b6f4f4bf86df99548890ffa2effa0c7842a99275316f7ff7f84877a86eba024` |
| `results/phase3_wgs_smoke/coverage_cnv_summary.json` | `1a34d97ee9fea675933ad7a2bac50b97ba7606412edffcbbc0a9965c89728a8a` |
| `results/phase3_wgs_smoke/signature_assignment_summary.json` | `81d7ef0ca68836c1bf8ccdeb767cf1fb5cbb176fcf2f301a9c20a552b028c56f` |
| `results/phase3_wgs_smoke/wgs_sbs96_matrix.csv` | `c49d40ce02449643c0c5b9d6bc5729fb56c8f831bdbb1dce49a7987ad7de53e5` |
| `results/phase3_wgs_smoke/sv_evidence_summary.json` | `b0bf2fbf6b37ba70e5b4548918b2bf2a6c51d8a6fd5dd2b21c7ce622f2039cb1` |
| `results/phase3_wgs_smoke/hrd_tool_readiness_summary.json` | `c7622b97569756bec76479e95792b482159f14e96a2fd0916115c8937b0b9bda` |
| `results/clinicalization/hrd_interpretation_readiness_summary.json` | `93b9a3e78635972fba2665e4fb7bd178f67ec193aae736d03780b834a3c50d20` |
| `results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json` | `ced5c0a4a01f2211e84d25a779c9291c750b4986b250eb20f339aac85500176a` |

## Local smoke

```sh
ROSALIND_HRD_SAMPLE_SET=hcc1395_wgs ROSALIND_HRD_ARTIFACT_ROOT=artifacts/phase3_wgs_selective5 ROSALIND_HRD_RUN_ID=hcc1395-wgs-selective5-YYYYMMDD PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet
```

Expected packet result: HCC1395 WGS has 7 evidence rows and 7 adapter rows.
The generated packet should have no missing source artifacts, should preserve
coverage-CNV and SV evidence as partial plumbing evidence, and should keep
scarHRD, CHORD, and HRDetect-style interpretation behind explicit no-call
boundaries.

## Useful follow-on experiments

Use this root to prepare post-deterministic work without launching new compute:

1. Rebuild the HCC1395 WGS Rosalind packet as a stand-in for the Diana WGS
   packet shape while preserving no-call HRD adapter boundaries.
2. Compare any new `phase3_wgs_fast` packet output to these archived
   evidence-surface counts before testing Parabricks on HG008 or COLO829.
3. Exercise blocked cross-check report generation against the archived
   `scarhrd`, `chord`, and `hrdetect` no-call rows before materializing Diana
   final artifacts.
