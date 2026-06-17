---
name: pipeline-data-custody-audit
description: Audit the data foundation of an analytics, AI, or bioinformatics pipeline for provenance, metadata, bias, leakage, reference compatibility, label quality, and biological or operational fitness. Use before trusting model outputs, benchmark results, cohort summaries, clinical or translational claims, or any AI-assisted analysis that depends on curated data.
---

# Pipeline Data Custody Audit

## Core Stance

Data work is scientific work. A pipeline trained, benchmarked, or interpreted on biased, mislabeled, reference-mismatched, or poorly described data can produce polished output that is still wrong.

## Audit Workflow

1. Inventory the inputs.
   - Identify every input file, manifest, table, database, API, cohort, and derived artifact.
   - Capture source, acquisition method, version, date, reference build, assay/platform, sample role, patient or specimen identity rules, and access constraints.

2. Trace provenance.
   - Check for URLs, accession IDs, checksums, hashes, download commands, transformation scripts, and generated artifact manifests.
   - Flag manual edits, undocumented conversions, missing raw-to-derived lineage, and files whose origin cannot be reconstructed.

3. Test metadata adequacy.
   - For biomedical data, look for tumor/normal role, pair ID, tissue/source, disease context, assay type, library prep, read length, strandedness, batch/center, reference build, purity or contamination context, and clinical label source.
   - Report missing metadata as analysis risk, not clerical cleanup.

4. Look for quality and compatibility failures.
   - Check missingness, duplicated samples, swapped roles, FASTQ pair mismatch, lane drops, reference/contig mismatch, batch effects, class imbalance, outliers, contamination, label noise, and annotation inconsistency.
   - Ask whether the intended model or statistic can distinguish signal from these artifacts.

5. Check leakage and bias.
   - Verify patient-level splits, cohort overlap, feature leakage, train/test contamination, proxy outcome validity, and subgroup representation.
   - For clinical or population use, require stratified performance or feasibility review by relevant subgroups such as ancestry, age, sex, site, platform, and socioeconomic proxies when available.

6. Produce a custody verdict.
   - Use one of: `custody_pass`, `usable_with_documented_gaps`, `blocked_by_missing_provenance`, `blocked_by_quality_risk`, or `not_reviewable`.
   - Separate corrections made from unresolved risk.

## Diana Omics Adapter

When working in `diana-omics`, start with:

- `manifests/*.csv` and `manifests/*.json`
- `docs/data/source-map.md`
- `docs/data/reference-panel-label-rules.md`
- `docs/operations/diana-raw-inputs.md`
- `src/diana_omics/diana_raw.py`
- `docs/clinical/risk-register.md`

Prefer existing commands when they match the audit question:

```bash
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw
PYTHONPATH=src /usr/bin/python3 -m diana_omics audit:raw-tools
PYTHONPATH=src /usr/bin/python3 -m diana_omics smoke:raw
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:known-answer-asset-integrity
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:known-answer-checksum-policy
```

Do not print secrets, tokens, private URLs, or sensitive patient identifiers. Summarize their presence and validation status instead.

## Report Shape

Lead with data trustworthiness, then list:

- Inputs inspected
- Provenance evidence
- Metadata gaps
- Quality or compatibility risks
- Leakage and bias risks
- Corrective actions
- Blockers before interpretation
