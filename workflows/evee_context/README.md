# EVEE / Evo 2 / pathway-context workflow

This workflow keeps three different scores in separate evidence lanes:

1. `evee_lookup`: retrieves published EVEE scores for variants present in the
   public 4.25-million-ClinVar service. A missing record is **not** scored as
   benign. SNVs are converted from 1-based VCF coordinates to EVEE's 0-based
   identifier. Indels require an explicitly supplied EVEE identifier.
2. `evo2_zero_shot`: optional CUDA execution of Arc Institute's public
   8,192-base zero-shot method. It reports alternate-minus-reference sequence
   likelihood, not an EVEE pathogenicity probability. Version 1 accepts SNVs
   only.
3. `pathway_ranks`: a transparent mean within-sample percentile-rank score and
   empirical percentile against each metadata-defined comparator group. It is
   not GSVA/ssGSEA and is not a clinical biomarker.

The workflow does not call somatic variants or quantify RNA. Those upstream
steps must provide a normalized tumor/normal VCF and a harmonized patient-plus-
reference expression matrix. This prevents caller and quantifier uncertainty
from being hidden inside the score.

## Inputs

- `--variants`: normalized GRCh38 VCF/VCF.GZ or a TSV/CSV with `chrom`, `pos`,
  `ref`, and `alt`. Optional columns include `gene`, `variant`, `report_claim`,
  and `evee_variant_id`.
- `--expression`: optional gene-by-sample TSV/CSV; the first column defaults to
  `gene`.
- `--metadata`: optional TSV/CSV with `sample_id` and `comparison_group`.
- `--gene_sets`: optional pinned GMT file.
- `--patient_sample`: required with expression inputs.
- `--reference`: indexed reference FASTA required only for the optional Evo 2
  lane.

## Bounded public-EVEE run

```sh
nextflow run workflows/evee_context/main.nf \
  --variants manifests/evee_report_highlights.tsv \
  --genome_build GRCh38 \
  --outdir results/evee_context/evee_report_highlights
```

## Evo 2 reference-window preflight

Before reserving a GPU, validate that every SNV agrees with the pinned FASTA
and yields the intended 8,192-base window:

```sh
uv run --no-project --with pyfaidx==0.8.1.4 python \
  workflows/evee_context/bin/score_evo2_zero_shot.py \
  --input manifests/evee_report_highlights.tsv \
  --reference /path/to/pinned-grch38.fa \
  --output-dir results/evee_context/evo2_reference_window_dry_run \
  --model evo2_1b_base \
  --window-size 8192 \
  --dry-run
```

The full 1B score requires an H100-class CUDA host. Do not use a hosted API
for patient sequence without a separately reviewed data-governance decision.

## Claim boundary

Variant pathogenicity, molecular mechanism, oncogenic direction, pathway state,
and treatment sensitivity are different endpoints. None of these outputs alone
establishes that a tumor pathway is activated, disabled, or drug-sensitive.
