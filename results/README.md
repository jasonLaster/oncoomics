# Results

`results/` stores generated evidence, not raw source data. Most files can be regenerated from manifests, public downloads, and workflow commands.

## High-Signal Outputs

- `results/reviewer_packet.md`: current reviewer-facing summary.
- `results/diana_readiness_gate.md`: readiness boundary for Diana-specific interpretation.
- `results/full_wes_benchmark/full_wes_benchmark_summary.json`: SEQC2/HCC1395 WES benchmark summary.
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`: full-source WGS mechanics summary.
- `results/clinicalization/known_answer_expanded_cohort_execution.md`: expanded known-answer confirmations and gaps.
- `results/orthogonal_validation/public_examples_summary.json`: implemented/planned public validation examples.

## Reading Results Safely

- Treat generated summaries as evidence, not clinical conclusions.
- Prefer JSON/CSV summaries for machine checks and Markdown files for reviewer narrative.
- Check timestamps, status fields, and input paths before comparing runs.
- Run `PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs` after regenerating outputs.
