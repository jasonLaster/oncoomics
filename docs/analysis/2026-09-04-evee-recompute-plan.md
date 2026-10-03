# EVEE report recomputation plan

Status: scoring pipeline implemented; bounded public lookup completed; all nine
Evo 2 reference windows validated; full patient DNA/RNA recomputation requires
upstream cloud execution.

## Decision and scientific objective

Determine whether the reported mTOR, autophagy/proteostasis, PARP/HRD, and other
DNA-repair/recycling signals survive a reproducible reanalysis of the observed
tumor/normal WGS and tumor RNA data. The decision endpoint is whether each signal
is supported strongly enough to prioritize confirmatory testing or mechanistic
review. It is not a treatment recommendation.

## Observed starting point

- A checksummed private Personalis delivery contains matched DNA and tumor RNA.
  The ImmunoID BAM/FASTQ lane is `hs37d5`; the separately processed WGS early-
  look lane is GRCh38.
- The existing WGS early look called only 15 HRR genes. It is suitable for the
  observed BRCA1 splice-site evidence but cannot reproduce a 607-variant report.
- No delivered all-somatic VCF or RNA expression matrix was found.
- The EVEE PDF gives nine complete tier-1 SNV coordinates and one incomplete
  RB1CC1 splice coordinate, but no numeric EVEE scores, allele depths, caller
  filters, transcript table, or exact score-generation receipt.
- The public EVEE service contains precomputed records for ClinVar variants; it
  cannot recreate the proprietary EVEE probe score for arbitrary absent variants.
- The completed public lookup found only CUL3 p.Arg354Cys, with pathogenicity
  0.4003; the other eight fully specified highlights are absent, not benign.
- All nine highlighted SNVs match the pinned UCSC hg38 analysis-set FASTA and
  produce 8,192-base Evo 2 windows with the alternate at offset 4,096.

## Compound analysis

### A. DNA evidence generation

1. Reuse the validated GRCh38 tumor/normal BAMs already present in S3.
2. Run a whole-genome matched Mutect2/Parabricks call with the frozen reference,
   contamination resources, orientation-bias model, and filter parameters.
3. Normalize and split alleles; retain caller FILTER, tumor/normal AD/DP/VAF,
   callable-region status, and transcript consequences.
4. First acceptance gate: every PDF-highlighted locus must be represented as a
   PASS call, a filtered call with reason, or a callable no-call. Coordinates
   without REF/ALT remain unresolved.

### B. Variant effect scores

1. Exact public EVEE lookup for ClinVar-covered variants, pinned to Zenodo DOI
   `10.5281/zenodo.19701997` / release `2026-04-23`.
2. Open Evo 2 zero-shot SNV score using `evo2_1b_base`, an 8,192-base reference
   window, and alternate-minus-reference likelihood. Pin source revision
   `53f195997257c56c00e5ef8d33a54f5baad143a6` and record model-weight hashes.
3. Keep indels and complex alleles out of v1 zero-shot scoring until length-
   normalization and a known-answer calibration set are locked.
4. Calibrate score direction and operating thresholds on held-out ClinVar plus
   BRCA1/BRCA2 functional assays before using a high/medium/low label.

### C. RNA expression and pathway context

1. Quantify the checksummed tumor RNA FASTQs with a frozen GRCh38 transcriptome
   and strandedness/QC receipt. Do not mix the `hs37d5` vendor BAM directly with
   a GRCh38 reference matrix.
2. Freeze a TCGA-BRCA reference matrix, sample manifest, Basal and receptor-
   defined TNBC labels, identifier mapping, and gene-set snapshots.
3. Compute both a maintained GSVA/ssGSEA implementation and the transparent
   mean within-sample percentile-rank score in this workflow. Report raw scores,
   coverage, cohort N, percentiles, and sensitivity to preprocessing.
4. Keep these pathways separate: PI3K/AKT/mTOR, mTORC1, autophagy, proteasome,
   homologous recombination, Fanconi anemia, base-excision/PARP, NER, MMR, and
   replication-stress/ATR.

## Acceptance gates

- Input identities and builds are checksummed and compatible.
- Tumor/normal pairing and contamination estimates pass their existing gates.
- Variant findings include read evidence and filter status; an effect score is
  never substituted for somatic-call evidence.
- Pathway scores meet minimum gene coverage and are stable across the locked
  preprocessing sensitivity analysis.
- HRD remains a no-call until SBS3/scarHRD/CHORD/HRDetect adapters meet their
  own validation and QC contracts.
- Outputs support research prioritization only. Pathogenicity, oncogenicity,
  pathway direction, and actionability remain separate claims.

## Runtime state and next execution boundary

The local Workbench target completed the bounded public lookup but cannot run
CUDA Evo 2, whole-genome calling, or RNA quantification. The live Ohio AWS Batch
GPU queue is enabled, valid, and scale-to-zero, but currently permits only
eight-GPU `p5.48xlarge`, `p5e.48xlarge`, and `p5en.48xlarge` hosts. That is a
poor fit for nine 1B-model scores requiring one H100. AWS currently offers the
single-H100 `p5.4xlarge` in all three configured Ohio availability zones, so the
next infrastructure step is a separate, cost-capped, scale-to-zero Evo 2 queue,
a digest-pinned Evo 2 image, and a cached model-weight receipt. A cloud plan must
state expected transfer size, GPU/CPU shape, model and reference identities, and
estimated cost before execution. No sequence should be sent to a hosted model
API without a separate data-governance review.
