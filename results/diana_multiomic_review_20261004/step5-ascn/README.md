# step5-ascn: allele-specific copy number, purity/ploidy, HRD scars (subject01 WGS)

Private and git-ignored. Research use only. Read `ascn_report.md` first.

## Environment

Python 3.11 via uv:

```
uv run --no-project --python 3.11 --with numpy --with pandas --with scipy --with matplotlib --with pysam python SCRIPT
```

Other tools:

- bcftools 1.23 (local) for the Strelka/Manta VCFs.
- FACETS was run once on Modal (`07_facets_modal.py`; R 4.4 + bioconda r-facets). Only a de-identified count matrix was sent.

Inputs stay in temp scratch and are not copied here:

- binned seqz: S3 `.../modal-sequenza-scarhrd-checkpointed-20260722T083604Z/checkpoints/seqz/`;
- WGS/exome BAM byte ranges, held as sparse local copies;
- presigned URLs, regenerated with `aws s3 presign --region us-east-1`.

The earlier agent's scratch, still referenced by the scripts: `/private/tmp/claude-501/.../4fbd936b-.../scratchpad/step5/` (`tracks/`, `wgs_sparse/`, `exome_sparse/`, `prior/`).

## Pipeline (scripts/)

| script | does | key output |
|---|---|---|
| 01_parse_seqz.py, 02_tracks.py, 02b_gc_window.py | seqz -> GC-corrected depth tracks + het-SNP folded-binomial BAF likelihoods | scratch `tracks/` |
| 03_segment.py | joint logR+BAF multi-track PCF per arm | `sensitivity/segments_*.tsv` |
| 04_fit.py, plot_landscape.py | ASCAT-style purity/ploidy grid | `fit_landscape.csv`, `sensitivity/landscape_*.csv` |
| 08_assign_states.py | integer (nA, nB) per segment at a given purity/ploidy | `segments_fit_S1_*.tsv`, `segments_fit_S1b_*.tsv`, `segments_fit_S2_*.tsv` (+ `.diag.json`) |
| 05_pileup_sites.py, sparse_bam.py, range_counting_proxy.py | BAM range fetch (exact byte accounting) and site counts | scratch |
| 06_facets_input.py, 07_facets_modal.py | snp-pileup-format counts -> FACETS (cval 100/150/300, alternative dipLogR) | `facets/` |
| 09_hrd_scars.py | scarHRD-equivalent HRD-LOH / TAI / LST | `facets/facets_hrd_scars.jsonl`, `scarhrd_reimplementation_check.jsonl` |
| 10_arms_focal.py | arm summary, focal loci, scRNA comparison | `arm_summary_S1.tsv`, `arm_vs_scrna_S1.tsv`, `focal_loci_S1.tsv` |
| 11_exome_brca1_region.py, 19_exome_locus_region.py | deep-exome local BAF + purity-free all-copies test | `exome_brca1_local.json`, `exome_tp53_local.json` |
| 12_hrd_sensitivity.py | HRD over 6 segmentations x {S1, S2, p+/-0.03} | `sensitivity/hrd_sensitivity.tsv` |
| 13-15 (superseded) | seqz-candidate somatic VAFs. Low-VAF candidates are artifact-rich; replaced by Strelka in 16/18 | `vaf/`, `somatic_vaf_candidates.tsv.gz`, `known_variants.tsv` |
| **16_evaluate_fits.py** | every candidate fit (S1, S1b, S2, 8 FACETS, Sequenza Jul-22) scored against the same BAF/depth tracks and Strelka SNVs (checklist) | `eval/fit_diagnostics.tsv`, `eval/locus_states_by_fit.tsv`, `eval/eval_segments_*.tsv.gz` |
| **17_hla_b2m_local.py** | WGS BAM-based het-SNP BAF at HLA (chr6:28-35 Mb) and B2M (chr15:43.2-46.2 Mb) | `hla_b2m/` |
| **18_integrate.py** | variant expected-vs-observed VAF by fit, exome purity-free tests, HLA/B2M continuous CN, FACETS CN0-vs-BAF check, HRD table, scRNA correlations, standardized segment files, figures | `variant_states_by_fit.tsv`, `exome_purity_free_tests.tsv`, `hla_b2m_states_by_fit.tsv`, `facets_cn0_vs_baf.tsv`, `hrd_scars_all_fits.tsv`, `arm_vs_scrna_correlations.json`, `segments_fit_{S1,S1b,FACETS_c150,FACETS_c300_dip-0.133,S2_rejected}_p*_ploidy*.standardized.tsv` |
| **20_focal_table.py** | focal/driver loci across chosen fits | `focal_loci_by_fit.tsv` |
| **21_hla_gene_windows.py** | per-HLA-gene continuous total and minor CN | `hla_gene_windows_by_fit.tsv` |

Rerun order for the new parts, from this directory:

1. `16 <scratch>/tracks <strelka_pass.raw.tsv> eval`
2. `17 <wgs_urls.json> <scratch>/wgs_sparse hla_b2m`
3. `19 <exome_urls.json> <scratch>/exome_sparse exome_tp53_local.json 1500000 17 7578369 A C`
4. `18`
5. `20`
6. `21 <scratch>/tracks`

`strelka_pass.raw.tsv` is `bcftools query -i 'FILTER="PASS"' -f '%CHROM\t%POS\t%REF\t%ALT\t%INFO/SomaticEVS\t[%AU\t%CU\t%GU\t%TU\t%DP\t]\n'` on `../step8-wgs-somatic/results/cloud/strelka/results/variants/somatic.snvs.vcf.gz`.

## Fits

| fit | file | status |
|---|---|---|
| S1 (p 0.32, psi 2.92) | `segments_fit_S1_p0.32_ploidy2.92.tsv` (08 output, full columns) and `.standardized.tsv` (18) | **primary** |
| S1b (p 0.35, psi 2.80) | `segments_fit_S1b_p0.35_ploidy2.80.tsv` and `.standardized.tsv` | purity sensitivity (clonal SNV peak) |
| FACETS cval150 (0.39 / 2.64), cval300 dipLogR -0.133 (0.37 / 2.52) | `segments_fit_FACETS_*.standardized.tsv`, `facets/` | independent caller; CN0 calls unreliable |
| S2 (0.48 / 4.90) | `segments_fit_S2_*` | rejected |
| low-ploidy FACETS, Sequenza Jul-22, `diag_rejected_*.json` | | rejected |

Segment columns (`.standardized.tsv`):

- `nA`, `nB`: major and minor integer CN.
- `CN`: total integer CN.
- `logR_obs`/`b_obs`: data from our tracks.
- `logR_exp`/`b_exp`: the fit's expectation.
- `b_lo`/`b_hi`: 95% profile CI.

## Figures

- `genome_S1_p0.32_ploidy2.92.png`, `genome_S2_p0.48_ploidy4.90.png`: genome-wide fits.
- `segment_baf_logR_lattices.png`: segment clouds vs integer lattices.
- `fit_landscape_K20_g320.png`: purity/ploidy landscape.
- `hla_b2m_baf.png`: per-SNP tumor BAF at HLA and B2M.
- `brca1_tp53_vaf_vs_states.png`: WGS VAF vs clonal multiplicity.
- `hrd_sum_ranges.png`: HRD-sum across fits and settings.
- `somatic_vaf_by_segment_class.png`: superseded, seqz candidates.
