# Diana HRD Omics

This project is the reproducible analysis workspace for Diana's HRD-focused omics validation work. It starts from the validation-atlas packet in `../diana-tnbc/obsidian/wiki/omics` and turns it into a project plan, source map, frozen benchmark manifest, and eventually runnable analyses.

The active scope is intentionally conservative:

1. HRD, biallelic BRCA/HRR state, and mutational-signature biology from tumor-normal DNA.
2. RNA subtype biology only as a context lane when it helps interpret TNBC biology or validate sample handling.
3. No treatment-changing claim without clinician review and orthogonal or companion-diagnostic validation.

## Stack Decision

- **Bun** is used for one-off project scripts: source checks, dataset-catalog fetchers, manifest generation, and validation utilities.
- **Python** is the primary local analysis language for the first phase because Python 3.9 is available here and R is not installed locally.
- **External workflow adapters** are planned for raw WGS or R-only HRD tools: nf-core/sarek, SigProfiler, CHORD, scarHRD, FACETS/ASCAT/PURPLE-style outputs, and containerized R when needed.

## Current Artifacts

- `docs/PROJECT_PLAN.md` - detailed milestones, deliverables, and verifiers.
- `docs/SOURCE_MAP.md` - researched datasets, tools, and access paths.
- `docs/WIKI_SOURCE_SUMMARY.md` - local wiki findings that drive the project boundary.
- `manifests/validation_atlases.json` - machine-readable source manifest for phase planning.
- `scripts/verify-plan.ts` - Bun verifier for the project plan, source manifest, and local wiki assumptions.

## Verify

Run the local plan checks:

```sh
bun run verify:plan
```

Optionally check the online source links too:

```sh
bun run verify:plan:online
```

