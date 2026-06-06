# HRD Reference Panel Label Rules

This frozen phase-1 panel uses open processed TCGA-BRCA PanCancer Atlas data from cBioPortal. It is a validation panel for workflow mechanics, not a clinical HRD truth set.

## Positive Controls

Positive controls require all of the following:

1. A likely damaging BRCA1/2 event in the fetched HRR mutation table.
2. A GISTIC copy-loss proxy for the same gene.
3. Elevated fraction genome altered in sample clinical data.

These are labeled expected HRD-like, but still carry a caveat that WGS structural-signature and companion-diagnostic evidence are not available in this phase.

## Mechanistic Controls

Mechanistic controls use likely damaging non-BRCA HRR events with copy-loss proxy and elevated fraction genome altered. These are useful stress tests, but less direct than BRCA1/2 controls.

## Ambiguous Controls

Ambiguous controls include HRR alterations without enough second-hit or scar-proxy support. They are intentionally included so the workflow can prove it does not force hard cases into binary labels.

## Negative Controls

Negative controls require no fetched HRR mutation, neutral BRCA1/2 GISTIC calls, low fraction genome altered, and modest mutation count. They are processed-data negative candidates, not proof of homologous-recombination proficiency.

## Boundary

No phase-1 label is based on WGS rearrangement signatures, SBS3 assignment, HRDetect, CHORD, Myriad myChoice, or clinician-owned companion-diagnostic review. Those remain future or external validation lanes.
