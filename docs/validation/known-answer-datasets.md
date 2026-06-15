# Orthogonal Validation Samples

This page answers the practical question: what have we already done to show that the pipeline works before Diana's real files arrive?

The short version is that we are no longer just collecting candidate datasets. We have run public tumor-normal data through real pipeline paths, compared outputs against known answers, recovered expected biology, and identified the remaining gaps that need full caller-level validation.

## What We Have Proven

| Validation result | Input | What the pipeline did | Why it matters |
| --- | --- | --- | --- |
| Recovered the expected melanoma driver in COLO829 | Public indexed BAMs for COLO829 tumor and COLO829BL normal | Read the BRAF V600E locus directly from tumor-normal BAMs across Illumina HiSeq X, PacBio Sequel, Oxford Nanopore MinION, and Illumina NovaSeq/phased submissions | Shows that the pipeline can interrogate public cancer BAMs and recover a clinically recognizable expected driver while the matched normal remains reference-like. |
| Passed a full public WES truth benchmark | SEQC2/HCC1395 tumor-normal WES FASTQs | Validated 4 FASTQs, aligned, marked duplicates, ran GATK Mutect2/FilterMutectCalls, estimated contamination, and compared calls to SEQC2 truth-overlap variants | Shows the end-to-end WES path can go from raw public FASTQ to a truth-comparison result, not just a completed run. |
| Passed full-source WGS mechanics on a public tumor-normal pair | SEQC2/HCC1395 full WGS FASTQs | Produced BAM validation, filtered VCF output, truth-depth checks, coverage-CNV bins, SBS96 mutation context, and SV evidence summaries | Shows the WGS pipeline can generate the major evidence surfaces we need before applying it to Diana. |
| Confirmed HG008 tumor-normal SNV truth signals | GIAB HG008-T tumor and HG008-N-D normal public BAMs plus NIST small-variant truth | Tested 40 simple somatic SNV truth loci by remote pileup; all 40 had tumor ALT support and normal REF support | Shows the pipeline can use the first public Cancer GIAB tumor-normal benchmark for bounded somatic correctness checks. |
| Confirmed HG008 CNV depth direction signals | GIAB HG008 public BAMs plus NIST SV/CNV truth | Tested four CNV truth intervals and saw the expected normalized tumor-normal depth direction | Shows the public HG008 truth set can exercise copy-number behavior before full segment-level caller comparison exists. |
| Ran the expanded validation in AWS Batch | Same 29-target expanded cohort | Built an arm64 ECR image, fetched small public assets in the task, ran non-dry remote-read probes, and published reports to S3 | Shows the validation workflow is portable to cloud execution, not just a local developer exercise. |

Current expanded cohort result:

- `29` validation targets across `5` sample groups.
- `19` non-dry confirmations.
- `1` partial confirmation: HG008 RNA paired FASTQ stats are consistent, but quantification has not run.
- `3` strict-validation gaps: HG008 SV overlap, COLO829 SV overlap, and COLO829 CNA overlap still need Diana-generated callsets.
- `6` blocked targets: COLO829 purity levels need local indexing or full transfer; Seraseq MRD requires request or purchase access.

Primary generated report:

```sh
results/clinicalization/known_answer_expanded_cohort_execution.md
```

## Dataset Map

| Dataset | Current use | What it is best for | Current evidence | Remaining gap |
| --- | --- | --- | --- | --- |
| SEQC2/HCC1395 WES | Implemented benchmark | Raw WES FASTQ to BAM to Mutect2 to truth comparison | `1122` exact PASS truth matches, recall `0.8585`, precision `0.9842`, contamination status passed | Keep as a regression gate; broaden intervals or add more WES datasets if we want more exome diversity. |
| SEQC2/HCC1395 full WGS | Implemented benchmark | Full-source WGS mechanics: BAM, VCF, CNV bins, SBS96, SV evidence | `268` exact truth matches, `631` CNV bins, `265` SBS96 SNVs, SV evidence status passed | This proves mechanics, but full HRD interpretation still needs Diana-like WGS policy and production CNV/SV/signature thresholds. |
| GIAB HG008 | Bounded non-dry validation | Personalis NeXT Personal-like whole-genome tumor-normal validation for SNV/indel, SV, CNV, and RNA intake plumbing | `40/40` truth SNVs passed tumor-normal pileup gates; `4/4` CNV truth intervals passed depth-direction checks | Generate Diana callsets and run formal small-variant recall/precision plus SV/CNV reciprocal overlap. RNA needs FASTQ transfer and quantification target selection. |
| COLO829/COLO829BL | Bounded non-dry validation | Independent melanoma tumor-normal guardrail, multi-platform BAM handling, known driver recovery, future SV/CNA benchmarking | BRAF V600E recovered in tumor and not normal across four public sequencing-platform BAM pairs | Generate build-matched Diana SV/CNA calls and compare with Zenodo truth assets; add UV/SBS7 guardrail when mutation-count context is sufficient. |
| COLO829 purity series | Metadata and blocker identified | Sensitivity stress testing across tumor fractions | ENA metadata exposes Illumina and long-read dilution levels at 10, 20, 25, 50, and 75 percent | Remote BAMs lack submitted BAI files, so we need full transfer or local indexing before monotonic recall can be tested. |
| Seraseq ctDNA MRD Panel Mix | Request/purchase target | MRD-like positive/negative and dilution validation before Diana plasma files arrive | Public docs describe 0, 0.005, 0.05, and 0.5 percent tumor fractions | Not freely downloadable as FASTQ/BAM/VCF. We need to buy/request material or variant files and define assay-specific acceptance ranges. |

## Priority Samples

### 1. COLO829 / COLO829BL

This is the most persuasive user-facing example because the expected result is concrete: a melanoma tumor should carry BRAF V600E and the matched normal should not.

Use it for:

- Independent tumor-normal WGS validation outside breast cancer.
- Driver-recovery sanity checks.
- Multi-platform input handling across Illumina, PacBio, Oxford Nanopore, and phased NovaSeq BAMs.
- Future SV/CNA truth-overlap benchmarking.
- Future HRD-negative or non-HRD-signature guardrails.

What we have already shown:

- Illumina HiSeq X tumor ALT fraction: `0.670968`; normal ALT fraction: `0.0`.
- PacBio Sequel tumor ALT fraction: `0.568182`; normal ALT fraction: `0.018868`.
- Oxford Nanopore MinION tumor ALT fraction: `0.610169`; normal ALT fraction: `0.04`.
- Illumina NovaSeq phased tumor ALT fraction: `0.753846`; normal ALT fraction: `0.0`.

Best next step:

Run full COLO829 tumor-normal calling, reconcile GRCh37 submitted BAMs with hg38-lifted truth assets, and produce SV/CNA reciprocal-overlap reports.

Key sources:

- ENA project: https://www.ebi.ac.uk/ena/browser/view/PRJEB27698
- COLO829 SV/CNA truth: https://zenodo.org/records/7515830
- Multi-platform SV reference: https://pmc.ncbi.nlm.nih.gov/articles/PMC9903816/

### 2. GIAB HG008

This is the highest-value Diana-like validation sample because it is a public tumor-normal cancer benchmark from NIST GIAB. It is the right anchor for a Personalis NeXT Personal-like whole-genome sequencing validation ladder.

Use it for:

- Tumor-normal WGS small-variant correctness.
- SV/CNV correctness.
- Reference-build compatibility checks.
- Downsampled WGS validation before full-transfer runs.
- RNA intake and quantification plumbing.

What we have already shown:

- `40/40` simple somatic SNV truth loci had tumor ALT support and normal REF support.
- `4/4` CNV truth intervals had the expected normalized tumor-normal depth direction.
- HG008 RNA public stats are paired and internally consistent.

Best next step:

Generate actual Diana HG008 callsets, then compare small variants, SVs, and CNVs to NIST truth files. Treat the existing pileup/depth checks as bounded confirmation, not as a substitute for full recall and precision.

Key sources:

- NIST Cancer Genome in a Bottle: https://www.nist.gov/programs-projects/cancer-genome-bottle
- HG008 small-variant benchmark: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/NIST_HG008-T_somatic-smvar_DraftBenchmark_V0.3-20260425/
- HG008 SV/CNV benchmark: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/NIST_HG008-T_somatic-stvar-CNV_DraftBenchmark_V0.5-20260318/
- HG008 WGS: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/NYGC_Illumina-WGS_20231023/
- HG008 RNA-seq: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/NIST/HG008-T_bulk/20240508p21/UMD_RNA-seq_20250925/

### 3. SEQC2/HCC1395

This is our strongest end-to-end raw-data benchmark because it already exercises real FASTQs, alignment, somatic calling, and truth comparison.

Use it for:

- Regression testing the FASTQ-to-BAM-to-VCF path.
- WES truth-overlap validation.
- Full WGS mechanics across VCF, CNV, SBS96, and SV evidence outputs.
- Proving that the repo can produce auditable metrics from public tumor-normal data.

What we have already shown:

- WES: `4` FASTQs validated, BAM validation passed, `1307` depth-eligible truth variants, `1122` exact PASS truth matches, recall `0.8585`, precision `0.9842`.
- WGS: full-source FASTQs, `268` exact truth matches, `631` CNV bins, `265` SBS96 usable SNV records, and SV evidence output.

Best next step:

Keep HCC1395 as a release regression gate. It is not a perfect Diana surrogate, but it is the cleanest proof that core mechanics work from raw public data.

Key sources:

- SEQC2 high-confidence somatic SNV/indel truth: https://sites.google.com/view/seqc2/home/data-analysis/high-confidence-somatic-snv-and-indel-v1-2
- SEQC2 community reference paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC8532138/

### 4. COLO829 Purity Series

This is the most useful next stress test once we are ready to transfer larger public files. It can tell us whether detection behaves sensibly as tumor fraction drops.

Use it for:

- Sensitivity degradation testing.
- Monotonic recall checks by tumor purity.
- Dilution-series behavior before plasma/MRD data are available.

What we have already shown:

- ENA metadata exposes selected purity levels for Illumina and long-read data.
- The selected submitted BAMs do not expose BAI indexes, so remote slicing cannot test recall yet.

Best next step:

Transfer selected BAMs or FASTQs, index locally, and run a monotonic recall table against COLO829 truth assets.

### 5. Seraseq ctDNA MRD Panel Mix

This is the closest currently identified target to the MRD/plasma question, but it is not an open public FASTQ dataset.

Use it for:

- Positive/negative MRD-like validation.
- Limit-of-detection stress cases.
- Tumor-fraction dilution behavior closer to Signatera or NeXT Personal-style plasma use.

What public docs say:

- The mix includes 0 percent, 0.5 percent, 0.05 percent, and 0.005 percent tumor fractions.
- It is designed around matched normal background, tumor-derived variants, and biosynthetic spike-ins.

Best next step:

Buy or request the material or variant files. Once obtained, define acceptance ranges before running it, especially for the 0.005 percent limit-of-detection case.

Key source:

- Product page: https://www.seracare.com/Seraseq-ctDNA-MRD-Panel-Mix-0710-2146/

## How To Run The Evidence

Current implemented public examples:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:orthogonal
```

Expanded known-answer cohort:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics run:known-answer-expanded-cohort
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:known-answer-expanded-cohort
```

Cloud execution:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics nf:aws:known-answer-expanded-cohort
```

The most recent AWS Batch run succeeded with:

- Job: `0b1141b8-59b9-4797-8ea1-6e1c0c6d6dba`
- Image: `172630973301.dkr.ecr.us-east-1.amazonaws.com/diana-omics:knownanswer-expanded-arm64-wesfix-20260615T014259Z`
- S3 report: `s3://diana-omics-results-172630973301-us-east-1/runs/known_answer_expanded_cohort/workspace/results/clinicalization/known_answer_expanded_cohort_execution.json`

## How To Make The Validation Stronger

1. Promote HG008 from bounded pileup/depth checks to full caller benchmarking.

   Generate Diana small-variant, SV, and CNV callsets from HG008 tumor-normal data. Report recall, precision, callable-region denominator, and reciprocal-overlap summaries against NIST truth.

2. Promote COLO829 from driver guardrail to full tumor-normal benchmark.

   Keep BRAF V600E as the easy-to-explain sanity check, then add build-matched SV/CNA truth comparisons and a UV/SBS7 signature guardrail.

3. Transfer and index selected COLO829 purity files.

   Start with a small number of levels, such as 75, 50, 25, and 10 percent. The result should be a monotonic recall table that makes sensitivity limits visible.

4. Buy or request Seraseq ctDNA MRD material/files.

   This is the cleanest way to test positive/negative and low-fraction MRD-like behavior before Diana plasma files arrive.

5. Add another breast/TNBC-oriented public benchmark only after confirming raw access and a known answer.

   HCC1395 is useful, but it should not be the only breast-cancer-like regression. The next candidate should have raw or near-raw data, a tumor-normal pairing, explicit truth labels, and permissive access.

6. Add vendor-style fixtures.

   If we can obtain representative VCF/report fixtures from Signatera, NeXT Personal, Tempus, Caris, Foundation, or similar assays, add parser and reconciliation tests. These should complement the raw sequencing benchmarks rather than replace them.

## Historical Manifests

The older acquisition-facing manifests still exist and are useful for provenance:

- `manifests/known_answer_sample_pull_plan.csv`
- `manifests/known_answer_public_finding_checks.csv`
- `results/clinicalization/known_answer_public_finding_execution.md`
- `results/clinicalization/known_answer_public_finding_confirmation.md`

Those files are intentionally conservative about execution and clinical use. For an outcome-oriented view of what we have actually validated, start with this page and the expanded cohort report instead.

## Boundary

These validations show that the public-data pipeline can ingest, analyze, and compare known samples in meaningful ways. They do not make a clinical claim about Diana. Before Diana interpretation, we still need Diana's real files, reference-build and pairing confirmation, tumor purity context, full HG008/COLO829 truth comparisons, and reviewer signoff on HRD interpretation policy.
