# Bug Audit

This is the risk register for a new reviewer. It lists where the project is most likely to be wrong, what currently catches the issue, and what should be added next.

## Highest-Risk Areas

### Reference Build Mismatch

Risk:

FASTQ, BAM, VCF, BED, and truth files may use different references: GRCh37, hg19, GRCh38, UCSC hg38 analysis set, GIAB GRCh38, or CHM13. A build mismatch can make correct calls look wrong or create false failures.

Current mitigations:

- Samplesheets carry reference IDs and paths.
- BAM validation checks headers and contigs.
- Full WES benchmark records reference ID.

Missing verifier:

- Add an explicit contig/order compatibility check between every BAM, VCF, BED, and reference FASTA before benchmarking.

### Tumor-Normal Swap

Risk:

Swapping tumor and normal can erase real somatic calls or turn germline variants into apparent somatic variants.

Current mitigations:

- Samplesheets include `role`, `pair_id`, and sample names.
- Diana raw validation requires tumor-normal pairing metadata.

Missing verifier:

- Add tumor/normal identity checks using shared germline variants, contamination estimates, and expected tumor-only signal.

### FASTQ Pairing and Lane Handling

Risk:

R1/R2 files can be mispaired, lanes can be dropped, or single-end files can be mistaken for paired-end files.

Current mitigations:

- FASTQ smoke validation checks paired reads.
- Manifest rows preserve run accession and role.

Missing verifier:

- Add per-lane read-group validation and explicit mate-name concordance summaries for all full-depth raw imports.

### Overconfidence From Downsampled Smoke Tests

Risk:

Bounded Phase 3 WGS subsets prove mechanics, not sensitivity. A small downsample can miss true variants, signatures, or CNV/SV events.

Current mitigations:

- Docs state that bounded Phase 3 runs are developer checks only.
- Full WES benchmark uses truth overlap and reports recall/precision.

Missing verifier:

- Keep the SEQC2/HCC1395 full-source WGS gate passing and add HG008 and COLO829 full or 30x truth benchmarks with explicit pass/fail thresholds.

### HRD Label Leakage or Weak Labels

Risk:

Processed public data can make HRD labels look more certain than they are. HRR mutation, copy loss, TMB, subtype, and FGA are not equivalent to functional HRD.

Current mitigations:

- Panel categories include positive, negative, and ambiguous controls.
- Caveats are carried into output tables.
- Reviewer packet states boundaries.

Missing verifier:

- Add a final `interpretation_level` field that separates `mechanical_validation`, `public_processed_evidence`, `truth_set_benchmark`, and `Diana_candidate_finding`.

### CNV and SV Smoke Outputs Are Not Production Callers

Risk:

Coverage bins and local SV evidence can detect obvious mechanics but are not a substitute for full CNV/SV callers.

Current mitigations:

- Phase 3 summary labels this as WGS-capable mechanics.
- Orthogonal validation plan calls for HG008 and COLO829 SV/CNV truth comparisons.

Missing verifier:

- Add `truvari` for SV benchmarking.
- Add a reciprocal-overlap CNV benchmark.
- Add adapters for FACETS, ASCAT, PURPLE, or equivalent outputs.

### RNA Is Currently Context, Not Truth

Risk:

RNA context may be mistaken for HRD status, or RNA FASTQs may pass basic validation without proving fusion/subtype correctness.

Current mitigations:

- RNA docs label outputs as context.
- Diana raw template separates DNA and RNA rows.

Missing verifier:

- Add STAR/Salmon or similar quantification.
- Add known fusion or known expression controls.
- Add strandedness and library-type detection.

### MRD Public Data Gap

Risk:

Tumor-purity dilution WGS is not the same as plasma cfDNA MRD. A pipeline that works on tissue WGS may still fail on UMI-rich, low-VAF ctDNA data.

Current mitigations:

- Seraseq ctDNA MRD is listed separately from COLO829 dilution.
- Docs state that Seraseq is request/purchase, not public FASTQ.

Missing verifier:

- Obtain Seraseq data/material or another true MRD positive/negative dataset.
- Add UMI-aware parsing if Diana receives UMI ctDNA files.

### Long-Running Commands With Sparse Progress

Risk:

Full WES/WGS commands can appear hung while processing large files.

Current mitigations:

- Output artifacts and logs are written under `results/*/logs`.
- Commands are resumable when existing BAM/VCF outputs pass quick checks.

Missing verifier:

- Add progress logging between expensive subprocesses.
- Add wall-time and CPU metrics to summary JSON.

### Tool Version Drift

Risk:

BWA, samtools, bcftools, Java, and GATK behavior can change across versions.

Current mitigations:

- Tool version JSON files are written in result folders.
- `verify:plan` checks core local tools.

Missing verifier:

- Add a machine-readable lockfile for external bioinformatics tools.
- Prefer containers for full-depth reproducibility once workflow policy stabilizes.

## Current Safety Boundary

The repository is safe for:

- Public-data validation.
- Raw-data intake validation.
- Reviewer packet generation.
- Planning Diana recompute.

It is not safe for:

- Standalone clinical treatment decisions.
- Companion-diagnostic replacement.
- Final HRD interpretation without Diana raw data, full-depth validation, and expert review.
