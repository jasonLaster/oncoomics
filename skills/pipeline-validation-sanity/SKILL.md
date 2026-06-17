---
name: pipeline-validation-sanity
description: Sanity check analytics, AI, and bioinformatics pipeline validation evidence, including known-answer benchmarks, controls, acceptance thresholds, reproducibility, uncertainty, explainability, and whether generated reports overclaim what the artifacts prove. Use when reviewing results, verifier output, benchmark claims, model performance, pipeline readiness, or reviewer-facing packets.
---

# Pipeline Validation Sanity

## Core Stance

Acceleration is not validation. Treat every impressive output as a claim that needs evidence, controls, reproducibility, and a clear interpretation boundary.

## Review Workflow

1. Name the exact claim.
   - State what the output is being used to prove.
   - Classify the evidence level: `mechanical_smoke`, `internal_qc`, `known_answer`, `external_cohort`, `orthogonal_validation`, `clinical_ready`, or `unsupported_claim`.

2. Inspect or run the available gates.
   - Prefer existing verifiers, tests, manifests, run logs, summary JSON/CSV, and generated reports.
   - If a check is too expensive or unavailable, say that and inspect the most relevant existing artifacts.

3. Require controls and known answers.
   - Look for positive controls, negative controls, truth sets, benchmark cohorts, external validation, and orthogonal assays.
   - Treat internal held-out performance as insufficient for clinical or high-stakes deployment unless paired with external or known-answer evidence.

4. Check reproducibility.
   - Verify tool versions, reference builds, prompt/model versions, seeds, manifests, environment files, logs, input hashes, and output contracts.
   - Ask whether another operator could rerun the analysis and know whether it still passed.

5. Interrogate biological or domain plausibility.
   - Check whether top features, variants, genes, clusters, signatures, or model explanations make sense in context.
   - Treat XAI outputs, feature importance, and attention as leads for expert review, not as explanations by themselves.
   - Require uncertainty, confidence, calibration, or out-of-distribution handling when predictions guide decisions.

6. Compare reports to artifacts.
   - Read reviewer-facing language against machine-checkable CSV/JSON/log evidence.
   - Downgrade claims that confuse smoke mechanics with sensitivity, RNA context with truth, processed-public evidence with Diana-specific findings, or partial readiness with completion.

7. Return a validation verdict.
   - Use one of: `validated_for_claim`, `validated_for_narrower_claim`, `partial`, `blocked`, `overclaimed`, or `not_reproducible`.
   - Include the smallest next check that would most improve confidence.

## Diana Omics Adapter

When working in `diana-omics`, prefer these gates when relevant:

```bash
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:plan
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:outputs
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:phase3-outputs
PYTHONPATH=src /usr/bin/python3 -m diana_omics benchmark:full-wes
PYTHONPATH=src /usr/bin/python3 -m diana_omics validate:phase3-wgs
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:orthogonal
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:known-answer-readiness
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:hrd-interpretation-readiness
```

Use `docs/validation/known-answer-datasets.md` and `docs/clinical/risk-register.md` to keep known-answer evidence and remaining risks aligned.

## Report Shape

Lead with findings ordered by severity:

- Overclaims or blocked claims
- Failed or missing gates
- Evidence that supports a narrower claim
- Reproducibility gaps
- Recommended next validation step

Do not say "green", "ready", or "validated" without naming the command, artifact, run ID, or reviewer evidence that supports it.
