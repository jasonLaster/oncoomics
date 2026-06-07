# Reference Panel Label Rules

The Phase 1 reference panel uses processed public data to create examples for reviewer triage. These labels are deliberately conservative.

## Positive Control

A sample may be a positive control when processed data show strong HRR evidence and a second-hit proxy such as copy loss.

Interpretation:

- Useful for pipeline behavior and table generation.
- Not a clinical HRD truth label.

## Ambiguous Control

A sample is ambiguous when it has an HRR alteration but processed data do not prove functional HRD.

Examples:

- Damaging HRR event without copy-loss proxy.
- Copy-number context that does not support biallelic loss.
- Incomplete subtype or scar evidence.

Interpretation:

- Should remain caveated in reviewer outputs.

## Negative Control

A sample may be a negative control when processed data lack the selected HRR evidence and do not show the positive-control pattern.

Interpretation:

- Useful as a contrast group.
- Not proof of homologous recombination proficiency.

## Required Output Behavior

Every derived table should keep:

- `expected_hrd_label`
- `panel_category`
- `label_source`
- `second_hit_proxy`
- `caveat`

If a downstream command drops these fields or presents a label without caveat, treat that as a documentation and analysis bug.
