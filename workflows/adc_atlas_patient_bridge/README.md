# Diana ADC Atlas patient bridge

This Nextflow wrapper creates the durable NGS Analysis Workbench run for the
new Diana patient lane in Pan-cancer ADC Atlas v1. Modal performs the large-file
work against the exact read-only S3 prefix. Complete outputs remain in the
private results bucket; the Workbench receives a bounded, checksummed review
bundle.

The selected method quantifies the paired E019 tumor RNA FASTQs with Salmon
1.10.3, a GENCODE v23 GRCh38 primary-assembly full-genome-decoy index, automatic
library inference, sequence-bias correction, and GC-bias correction. Transcript
TPM and estimated read counts are summed to GENCODE genes. The 23 atlas targets
are compared descriptively with TCGA-BRCA quartiles from the public
Toil/RSEM/GENCODE-v23 matrix.

## Evidence boundary

The patient and public cohort share a feature model and TPM scale, but they do
not share a quantifier, library preparation, specimen composition, or batch.
The patient-to-cohort ratio and quantile band are therefore directional checks,
not exact percentiles. This single bulk sample cannot support differential
expression, malignant-cell localization, membrane-protein abundance, ADC
eligibility, response prediction, or treatment recommendation.

## Runtime and custody

The local controller requires Nextflow, Python, and an authenticated Modal CLI.
The Modal function uses its named AWS secret. Credentials are not written to
workflow parameters, logs, repository files, or the Workbench registry. Source
and output paths are immutable per run; recovery mode downloads an existing
run and never recomputes or overwrites it.
