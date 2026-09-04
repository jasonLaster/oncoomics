# Pan-cancer ADC Atlas v1

## Biological question

Across adult solid-tumor lineages, which cell-surface ADC targets have a useful public RNA-expression pattern, limited normal-tissue RNA exposure, and enough orthogonal protein context to justify specimen-level follow-up?

The unit of reasoning is the **target or epitope in a payload context**, not just a gene symbol. Version 1 is a target-screening atlas; it is not a live registry of drugs, approvals, trials, or patient eligibility.

## Workbench analysis model

1. **Understand the inputs.** Freeze a target manifest and one harmonized expression source. Keep tumor, normal tissue, public protein context, and Diana evidence in separate lanes.
2. **Design before execution.** Define cohorts, transformations, aggregation statistics, missingness, evidence states, and stop conditions before querying data.
3. **Run reproducibly.** Query only the frozen gene panel from the UCSC Toil TCGA/TARGET/GTEx matrix, invert `log2(TPM + 0.001)` to TPM, filter to TCGA primary tumors and GTEx normal tissues, and hash every downloaded source.
4. **Interpret against gates.** RNA supports target ranking. HPA IHC and CPTAC are orthogonal public context. Neither lane proves accessible membrane antigen, internalization, payload sensitivity, or benefit.
5. **Iterate through a new run.** The patient bridge adds a separately versioned Diana transcript quantification without rewriting its private inputs. Later runs may add specimen protein assays, cell-compartment resolution, or an ADC-program registry without overwriting prior evidence.

## Frozen v1 inputs

- Target manifest: [`manifests/adc_atlas_targets_v1.csv`](../../manifests/adc_atlas_targets_v1.csv)
- RNA matrix: UCSC Xena `TcgaTargetGtex_rsem_gene_tpm`, the Toil/RSEM hg38 GENCODE v23 recompute
- Phenotype table: UCSC Xena `TcgaTargetGTEX_phenotype.txt.gz`
- Protein context: Human Protein Atlas v25.1 cancer IHC, normal-tissue IHC, and CPTAC downloads
- Builder: `python3 -m diana_omics build:pan-cancer-adc-atlas`

The generated [`source_manifest.json`](../../results/pan_cancer_adc_atlas/v1/source_manifest.json) records source URLs, versions, SHA-256 hashes, sample filters, and exclusions.

## Cohort and metric policy

- Include TCGA samples whose study is `TCGA` and sample type is `Primary Tumor`.
- Include GTEx samples whose study is `GTEX` and sample type is `Normal Tissue`.
- Exclude TARGET, TCGA non-primary samples, and other studies from the primary v1 comparison.
- Report sample count, median, quartiles, p90, p95, and fractions at or above 1 and 10 TPM.
- Do not call a tumor-to-normal ratio a therapeutic-window score.
- Do not compare Diana's current interval-depth values with TPM or assign a cohort percentile.
- Preserve legacy query aliases explicitly; for example, UCSC Toil is queried with `PVRL4` and reported as `NECTIN4`.

## Evidence gates

| Gate | v1 status | What would advance it |
| --- | --- | --- |
| Harmonized public tumor RNA | `public_processed_evidence` | Frozen cohort and provenance already present |
| Harmonized public normal RNA | `public_processed_evidence` | Frozen cohort and provenance already present |
| Public protein context | `reference_available` or `not_available` | HPA/CPTAC row presence, interpreted as context only |
| Diana-to-cohort comparison | `directionally_comparable` after patient-bridge QA | Same annotation and TPM scale support coarse TCGA-BRCA bands; matched quantification and batch-aware modeling would be required for exact cohort placement |
| Surface localization | `no_call` | Viable-tumor membrane IHC, flow cytometry, or suitable spatial/proteomic evidence |
| Internalization | `no_call` | Target- and construct-relevant internalization assay |
| Payload sensitivity | `no_call` | Payload-mechanism and resistance evidence in the relevant model/specimen |
| Overall | `partial_evidence` | Cannot become `ready` from public RNA/protein-reference data alone |

Gene-level RNA is especially insufficient for epitope-specific targets such as CLDN18.2 and MUC1 glycoforms. Bulk signal can also be compartment-confounded—for example, GPNMB by macrophages, CD276 by stromal/vascular cells, and FOLH1 by tumor vasculature.

## Outputs

The builder writes versioned artifacts to [`results/pan_cancer_adc_atlas/v1/`](../../results/pan_cancer_adc_atlas/v1/):

- tumor and normal-tissue RNA summaries;
- HPA cancer IHC, normal IHC, and CPTAC subsets;
- target and candidate evidence matrices;
- an eight-row RNA-to-protein follow-up queue with target-specific localization gates;
- embedded visualization payload;
- source manifest and run summary;
- Workbench-style run manifest and checksummed artifact index;
- standalone [interactive atlas](visualizations/pan-cancer-adc-atlas-v1.html).

## Runtime strategy

The public v1 reference is intentionally built with narrow Xena queries and small HPA tables on the local runner. That avoids moving the full pan-cancer matrix or paying for unnecessary cloud compute. Modal plus S3 remains the execution lane for the expensive next steps: same-annotation Diana transcript quantification, larger matrix materialization, bootstrap or batch-sensitivity analyses, and specimen-level workflows. Those results should be written as a new run and joined only after their measurement scale and provenance match this reference.

## Diana patient bridge

The new patient lane quantifies the paired E019 tumor RNA FASTQs directly from the exact read-only S3 prefix with Salmon 1.10.3. It uses GENCODE v23 transcripts and the matching GRCh38.p3 primary assembly as full-genome decoys, then aggregates transcript TPM and estimated reads to GENCODE genes. The reference download is size- and MD5-checked against the official release records before indexing; the completed index is cached in a named Modal Volume so later target panels do not repeat that one-time build.

The comparison deliberately stops short of an exact patient percentile. Diana and the public TCGA/GTEx atlas share GENCODE v23 and a TPM scale, but the private sample uses Salmon while the public Toil recompute uses RSEM, and the library preparation, specimen preservation, tumor composition, and batch differ. Version 1 therefore reports the patient's TPM, within-sample protein-coding rank, descriptive ratio to the TCGA-BRCA median, and a coarse TCGA-BRCA quartile/tail band. Those are directional bulk-RNA context only.

The execution path is a saved Workbench Nextflow wrapper around a repository-owned Modal runner. The wrapper hash-binds the runner, helper, target manifest, and public breast-cancer aggregate before execution. Modal keeps the raw input mount read-only, writes a new run-specific prefix to private S3, copies the completion manifest last, and returns only a bounded review bundle to Workbench.

## Observed v1 result

The newly recomputed run is [`adc-atlas-patient-bridge-20260904T183020Z`](../../results/workbench/adc-atlas-patient-bridge-20260904T183020Z-projection/). Salmon processed 150,003,699 fragments, mapped 108,676,737 (72.45%), inferred ISR, mapped all 197,671 quantified transcripts to GENCODE genes, and produced a gene TPM sum of 999,999.999917. All 23 targets passed the directional-comparison contract.

| RNA review order | Diana TPM | TCGA-BRCA band | Target-specific protein gate |
| --- | ---: | --- | --- |
| HER3 (`ERBB3`) | 710.853 | At or above p95 | Membrane IHC with heterogeneity review |
| GPNMB | 485.048 | At or above p95 | Membrane IHC with macrophage review |
| Folate receptor alpha (`FOLR1`) | 189.450 | At or above p95 | Validated membrane IHC assay |
| HER2 (`ERBB2`) | 152.236 | Median to Q3 | Validated quantitative HER2 protein assay |
| EGFR | 110.351 | At or above p95 | Membrane IHC plus genomic context |
| TROP-2 (`TACSTD2`) | 108.457 | Q1 to median | Membrane IHC on viable tumor |
| B7-H3 (`CD276`) | 91.474 | Q1 to median | Membrane IHC with vascular and stromal review |
| NaPi2b (`SLC34A2`) | 80.720 | At or above p95 | Membrane IHC with lung normal-tissue review |

This is ordered by patient TPM within the frozen panel, not by predicted efficacy or safety. TROP-2's descriptive patient-to-TCGA-BRCA-median ratio is 0.6809, and its within-sample percentile among protein-coding gene TPM values is 95.19. Those two statistics use different denominators and neither proves membrane protein. The pan-BRCA band also does not replace a Basal-like or receptor-defined TNBC subtype analysis.

Implementation references:

- [GENCODE human release 23](https://www.gencodegenes.org/human/release_23.html)
- [Salmon selective alignment and decoy-aware index guidance](https://salmon.readthedocs.io/en/stable/salmon.html)
- [Modal cloud bucket mounts](https://modal.com/docs/guide/cloud-bucket-mounts)
- [Modal resource and disk guidance](https://modal.com/docs/guide/resources)

## Validity and QA strategy

- Unit-test the UCSC inverse transform, quantiles, cohort filters, and evidence ceiling.
- Fail if Xena returns a missing gene or a score vector with the wrong sample length.
- Keep raw-source SHA-256 hashes and file sizes in the run manifest.
- Require a unique target id and explicit query symbol for every manifest row.
- Require the current S3 object sizes and recorded VersionIds to match the versioned intake contract before interpreting the patient run.
- Require at least 50% Salmon fragment mapping, at least 99.9% transcript-to-gene mapping, a gene-level TPM sum between 999,000 and 1,001,000, and all 23 target rows before enabling the directional patient lane.
- Preserve Salmon library-type inference, mapping metadata, logs, software versions, reference hashes, input evidence, and artifact hashes in the run envelope.
- Cache only the immutable, integrity-checked reference index; never cache or overwrite a patient result prefix.
- Verify the generated page without network fetches at desktop and mobile widths.
- Treat missing protein rows as `not_available`, not negative evidence.
- Keep every v1 candidate at `partial_evidence`; zero `ready` rows is the intended safety invariant.

## Interpretation boundary

The atlas supports research prioritization. It does not establish ADC eligibility, predict response, or recommend treatment. The translational chain remains: DNA and RNA context → protein abundance → membrane localization and accessibility → binding and internalization → payload delivery → cell killing and clinical benefit.

## Scientific context

Two published pan-cancer analyses motivate the atlas shape without serving as input data. Bosi et al. profiled 54 targets and highlighted target distributions, co-expression, patient heterogeneity, and payload-response determinants. Fang et al. integrated transcriptomic, proteomic, genomic, and membrane-protein annotations and argued for multi-facet target assessment. v1 deliberately implements the narrower reproducible core first and leaves program-level and functional biology for later versioned lanes.

- [Pan-cancer analysis of ADC targets and putative predictors of treatment response](https://pubmed.ncbi.nlm.nih.gov/37913680/)
- [The target atlas for antibody-drug conjugates across solid cancers](https://pubmed.ncbi.nlm.nih.gov/38129681/)
- [UCSC Xena data downloads](https://xena.ucsc.edu/download-data/)
- [Human Protein Atlas downloadable data](https://www.proteinatlas.org/about/download)
