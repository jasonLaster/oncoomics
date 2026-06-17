---
name: pipeline-deployment-governance
description: Review deployment readiness, monitoring, change control, human oversight, ethics, implementation fit, and governance for analytics, AI, or bioinformatics pipelines. Use when a validated-looking pipeline may be moved into production, clinical, translational, institutional, vendor, or repeated operational use, or when deciding whether current evidence supports scaling beyond research exploration.
---

# Pipeline Deployment Governance

## Core Stance

A method that works in a controlled analysis is not automatically usable in practice. Deployment readiness depends on people, workflow fit, documentation, monitoring, change control, equity, and the ability to stop or no-call when evidence is inadequate.

## Review Workflow

1. Classify the deployment context.
   - Use one of: `research_only`, `reviewer_packet`, `translational_pilot`, `clinical_support`, `production_operations`, or `vendor_institutional_decision`.
   - Identify who will use the output, what they will decide, and what harm follows from an incorrect or overconfident result.

2. Write the implementation brief.
   - Ask who operates the pipeline, where inputs enter, where outputs land, what documentation exists, what training is required, and how non-experts could misread the output.
   - Check interoperability with existing systems, naming conventions, artifact storage, and review workflows.

3. Require human oversight and no-call states.
   - Identify required reviewers, signoff roles, escalation paths, override handling, and rollback authority.
   - Require explicit blocked/no-call language for missing inputs, failed QC, out-of-distribution samples, unsupported modalities, or incomplete validation.

4. Review monitoring.
   - Check for post-deployment monitoring of data drift, model drift, prompt or foundation-model drift, tool-version changes, subgroup performance, failures, and incident review.
   - Treat prompt libraries, agent instructions, and AI-generated interpretation text as versioned assets that need regression tests.

5. Check ethics, privacy, and regulatory exposure.
   - Review consent, PHI/PII handling, audit trails, subgroup performance, proxy outcomes, and population mismatch.
   - For legal or regulated clinical claims, verify current requirements from primary sources before giving definitive guidance. Consider HIPAA, GDPR, the EU AI Act, FDA guidance, CLIA/CAP, and local institutional policy only as applicable.

6. Review change control.
   - Require version locks for references, tools, prompts/models, thresholds, report templates, and manifests.
   - Require release notes, validation deltas, acceptance criteria, rollback plans, and preserved previous outputs when changes affect interpretation.

7. Return a governance verdict.
   - Use one of: `deployable_with_controls`, `pilot_only`, `research_only`, `blocked_pending_validation`, `blocked_pending_governance`, or `not_reviewable`.
   - Name the highest-leverage governance artifact to create next.

## Diana Omics Adapter

When working in `diana-omics`, inspect:

- `docs/clinical/orchestration.md`
- `docs/clinical/validation-packet-template.md`
- `docs/clinical/risk-register.md`
- `manifests/clinical_validation_packet_sections.csv`
- `manifests/clinical_validation_evidence_links.csv`
- `manifests/clinical_change_control_triggers.csv`
- `manifests/clinical_signoff_workflow.csv`

Prefer these commands for deployment-readiness evidence:

```bash
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-assay-boundaries
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-qc-thresholds
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-validation-packet
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-validation-evidence-links
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-change-control
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinical-signoff-workflow
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:clinicalization-readiness-rollup
```

Keep public validation, future Diana raw-data readiness, and clinical deployment separate. A reviewer packet is not a clinical assay launch.

## Report Shape

Lead with deployability, then include:

- Deployment context
- Human oversight requirements
- Monitoring gaps
- Change-control gaps
- Privacy, equity, or regulatory concerns
- Required no-call states
- Next governance artifact
