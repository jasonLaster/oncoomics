---
name: pipeline-strategy-sanity
description: Review whether an analytics, AI, or bioinformatics pipeline has a sound underlying strategy before implementation or interpretation. Use when asked to sanity check an analysis plan, decide whether a pipeline answers the right question, evaluate method-to-question fit, review an AI-assisted workflow strategy, or identify the smallest evidence needed before trusting or scaling a pipeline.
---

# Pipeline Strategy Sanity

## Core Stance

Treat automation and AI as accelerants, not validators. The strategy is sound only if a knowledgeable reviewer can connect the decision, biological or operational question, data modalities, method choices, validation plan, and interpretation boundary.

## Review Workflow

1. State the decision under review.
   - Name the user or stakeholder, the action the output should support, and the claim the pipeline is expected to make.
   - If the decision is vague, make that the first finding instead of reviewing implementation details prematurely.

2. Map the chain from question to output.
   - Write the chain as: question -> data -> method -> validation -> output -> decision.
   - Flag any missing link, especially where a statistical output is being treated as a biological, clinical, or business conclusion without justification.

3. Test method-to-question fit.
   - Ask whether the input modality can actually carry the signal being claimed.
   - Check for obvious alternatives, simpler baselines, and negative controls.
   - Look for confounders the strategy must address before method choice matters: batch, ancestry, tumor purity, reference build, platform, label noise, leakage, cohort overlap, or proxy objectives.

4. Define what would change your mind.
   - Require falsifiable success criteria: known-answer samples, external cohorts, orthogonal assays, negative controls, acceptance thresholds, or reviewer signoff.
   - Include an explicit no-call or blocked state when evidence is incomplete.

5. Audit the AI or automation role.
   - Separate generated code, prompts, agents, and deterministic tools.
   - Require versioned prompts or agent instructions when they materially affect outputs.
   - Treat prompts, model choices, and tool parameters as living methodological assets that need regression checks after model, data, or dependency changes.

6. Return a strategy verdict.
   - Use one of: `sound`, `promising_with_gaps`, `high_risk`, `unsound`, or `insufficient_context`.
   - Name the smallest next evidence unit that would reduce the most risk.

## Diana Omics Adapter

When working in `diana-omics`, inspect the local strategy surfaces before inventing a new frame:

- `README.md`
- `docs/operations/analytics-sequence.md`
- `docs/clinical/orchestration.md`
- `docs/clinical/risk-register.md`
- `docs/validation/known-answer-datasets.md`

Favor the repo's existing command surface for evidence:

```bash
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinicalization-readiness-rollup
```

Do not convert public-data validation, smoke-test mechanics, or RNA context into a Diana-specific clinical interpretation. Keep `mechanical_validation`, `public_processed_evidence`, `truth_set_benchmark`, and `Diana_candidate_finding` separate.

## Report Shape

Lead with the verdict and the most important risk. Then include:

- Decision reviewed
- Chain map
- Strategy gaps
- Evidence already present
- Smallest next validation step
- Claims that must not be made yet
