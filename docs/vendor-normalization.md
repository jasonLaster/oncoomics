# Vendor Normalization to the Common TCGA Format

Diana's WES/WGS deliverables arrive from vendors (Personalis NeXT Personal,
Natera Altera, and similar) in vendor-specific column layouts, on their own
reference build, and pre-filtered by their own caller policy. The public
reference panel and the HRD analysis (`analyze:hrd`, `build:panel`) are built on
the **cBioPortal-derived TCGA-BRCA schema**. Before a Diana sample can be scored
beside the TCGA reference panel, it must be mapped onto that schema and filtered
to the same somatic standard.

`normalize:vendor` does that mapping and filtering. It is deterministic,
stdlib-only, and writes an auditable normalization report alongside the
normalized tables.

## The Target Standard

The canonical contract is defined in
[py/src/diana_omics/tcga_standard.py](../py/src/diana_omics/tcga_standard.py)
and is what the TCGA samples already satisfy:

- **Reference build:** GRCh37/hg19 (the PanCancer Atlas build).
- **Genes:** the 15-gene HRR set, HUGO symbols.
- **Mutations:** MAF `Variant_Classification` vocabulary, HUGO gene, tumor
  allele counts, `ncbiBuild`.
- **Copy number:** GISTIC discrete `value` in `{-2,-1,0,1,2}`.
- **Clinical:** `FRACTION_GENOME_ALTERED`, `MUTATION_COUNT`,
  `TMB_NONSYNONYMOUS`, `ANEUPLOIDY_SCORE`, `SAMPLE_TYPE`,
  `CANCER_TYPE_DETAILED`.

## What Normalization Does

1. **Gene symbols** are upper-cased and remapped through a legacy-alias table
   (e.g. `MRE11A -> MRE11`, `NBS1 -> NBN`), then scoped to the HRR gene set.
2. **Consequences** from VEP (`CSQ`), SnpEff (`ANN`), or MAF columns are mapped
   to MAF `Variant_Classification`. Frameshift and inframe indels resolve
   Del vs Ins from ref/alt length.
3. **Somatic filters** matching the TCGA/MC3 spirit are applied: `PASS`-only,
   minimum tumor depth (14), minimum alt reads (3), minimum VAF (0.05),
   clean matched normal (VAF <= 0.02), standard contigs only.
4. **Copy number** (absolute copy number or log2 ratio) is discretized to
   GISTIC, and `FRACTION_GENOME_ALTERED` is computed from segment files.
5. **Burden metrics** (`MUTATION_COUNT`, `TMB_NONSYNONYMOUS`) are taken from
   vendor QC when supplied and normalized by capture size; HRR-only files do
   not reconstruct exome-wide burden and that is flagged.
6. **Reference build** is harmonized to canonical GRCh37/GRCh38 names, and any
   non-GRCh37 sample is flagged for position-level incompatibility (HUGO-level
   joins still hold).

Every drop is counted by rule in the per-sample report so the filtering is
auditable, not silent.

## Run It

Generate the manifest template:

```sh
PYTHONPATH=src /usr/bin/python3 -m diana_omics normalize:vendor
```

This writes `manifests/diana_vendor_inputs.template.csv`. Copy it:

```sh
cp manifests/diana_vendor_inputs.template.csv manifests/diana_vendor_inputs.csv
```

Fill in real vendor paths and metadata, then normalize:

```sh
DIANA_VENDOR_MANIFEST=manifests/diana_vendor_inputs.csv \
DIANA_VENDOR_REQUIRE_DATA=1 \
DIANA_VENDOR_ANALYSIS_ID=diana_vendor_recompute \
PYTHONPATH=src /usr/bin/python3 -m diana_omics normalize:vendor
```

Outputs land in `results/diana_vendor_normalized/<analysis_id>/`:

| File | Purpose |
| --- | --- |
| `mutations_hrr.json` / `.csv` | TCGA-shaped somatic HRR mutations. |
| `cna_hrr_gistic.json` / `.csv` | GISTIC-discretized HRR copy number. |
| `clinical_sample_selected.json` | TCGA clinical attributes. |
| `normalization_report.json` / `.csv` | Per-sample counts, dropped-by-rule, build flags, caveats. |
| `README.md` | Packet summary and boundary. |

## Manifest Columns

| Column | Meaning |
| --- | --- |
| `sample_id`, `patient_id` | Identifiers. |
| `vendor` | `personalis`, `natera`, ... (provenance only). |
| `assay` | `WGS` or `WES`. |
| `reference_build` | Vendor build (e.g. `GRCh38`). |
| `variant_file`, `variant_format` | Somatic variants; `vcf`, `maf`, `tsv`, or `csv` (auto-detected if blank). |
| `tumor_sample_column`, `normal_sample_column` | VCF sample names (auto-guessed if blank). |
| `cnv_gene_file` | Gene-level copy number (gene + copy_number/log2/gistic). |
| `cnv_seg_file` | Segment file for `FRACTION_GENOME_ALTERED`. |
| `ploidy` | Tumor ploidy for copy-number discretization (default 2.0). |
| `tumor_purity` | Recorded for downstream interpretation. |
| `capture_megabases` | WES capture size for TMB normalization. |
| `mutation_count`, `tmb_nonsynonymous`, `aneuploidy_score` | Vendor QC values, normalized as-is. |
| `sample_type`, `cancer_type_detailed` | Clinical context. |

## Boundary

Normalization standardizes and filters inputs so Diana data meets the same bar
as the TCGA samples. It does not assert an HRD result. WGS structural and
mutational signatures, allele-specific LOH, and reviewer sign-off remain
required before any interpretation.
