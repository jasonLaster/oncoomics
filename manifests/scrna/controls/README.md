# Public raw/filtered controls

`sources.lock.json` pins official source URLs, file sizes, SHA-256 values and donor grouping. The breast standard/LT libraries are from the **same sorted IDC donor**; subtype and treatment are unknown. Their reference fingerprints remain unresolved. These are custody/runtime controls, not held-out TNBC qualification data.

For a rerun, download the two matrices for a chosen control into a new protected delivery directory, copy its `*.metadata.json` to the `vendor-metadata.json` filename declared in the corresponding `*.intake.json`, and use the private arrival CLI. Source report snapshots can be retrieved from the official dataset page and checked against the metadata packet's `source_sha256`. The source packet is an operator attestation, not authenticated vendor identity.

The synthetic known-answer control is generated with `scripts/prepare_scrna_count_smoke.py NEW_PROTECTED_DIRECTORY`; inspect/stage it with the generated reference lock and assets, then count on Modal and collect. Compare with `scripts/audit_scrna_count_smoke.py --run-dir COLLECTED_RUN --expected GENERATED_DIRECTORY/expected_counts.json --report PROTECTED_REPORT.json`. This tests exact barcode/gene UMIs and PCR duplicate collapse. It does not qualify a human reference, cell caller or annotation model.
