# Diana WGS Blocked HRD Cross-Check Packets

This directory contains three alias-only blocked method packets generated on
2026-07-17 for the Diana WGS seven-method HRD report inventory.

These packets are descriptive placeholders, not patient results. Each report
binds an exact `method_spec.json` and preserves:

- `execution_status: not_run`
- `evidence_status: blocked`
- `authorized_hrd_state: no_call`
- `classification_authorized: false`
- `patient_result: none`

## Packets

| Method | Report | Current boundary |
| --- | --- | --- |
| FACETS to scarHRD | [facets_scarhrd_blocked/report.md](facets_scarhrd_blocked/report.md) | Blocked until the common-SNP VCF, FACETS/facets-suite/snp-pileup/scarHRD runtime, allele-specific segment gates, and known-answer thresholds are locked. |
| Oncoanalyser and CHORD | [oncoanalyser_chord_blocked/report.md](oncoanalyser_chord_blocked/report.md) | Blocked until HMF resources, original lane hashes, mirrored digest-pinned process images, a CHORD parser, x86 Batch runtime, and WGTS known-answer gates are locked. |
| HRDetect | [hrdetect_blocked/report.md](hrdetect_blocked/report.md) | Blocked until the GRCh38 implementation, six-feature model inputs, signature resources, SV/CNV/microhomology features, and calibration policy are locked. |

## Validation

Each packet has exactly three files:

```text
method_spec.json
report.md
report_manifest.json
```

The private-publication dry run accepted all three packet inventories:

```sh
python3 scripts/publish_private_report.py \
  --packet-dir results/diana_wgs_hrd/blocked-crosschecks-20260717/<method_id> \
  --method-id <method_id> \
  --receipt-output .codex-tmp/blocked-crosschecks-dry/<method_id>.json
```
