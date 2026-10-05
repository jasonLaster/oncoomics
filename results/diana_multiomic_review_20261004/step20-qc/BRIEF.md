# Step 19: QC framework for single-nucleus target claims (shared brief)

**Goal.** Make every target or biology claim from KH022 defensible to a team of computational biologists. Each module
produces quantitative evidence that answers one question: can this specific gene-level claim be trusted, and with what
caveats? Report nulls and failures plainly. A claim that fails a gate is a result, not a problem to hide.

## Data (all local unless noted)

**Libraries.** Two KH022 snRNA libraries, KH022-1 (L1) and KH022-1-1 (L2).
- Chemistry: 10x GEM-X 3' v4 polyA, Cell Ranger 10.1.0, GRCh38-2024-A, introns included.
- Size: ~38-39k called nuclei per library.
- They are technical replicates: one suspension, two channels.

**Matrices.** `/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/4fbd936b-233c-45a5-9c20-5ff0fee4d763/scratchpad/step2b/data/<lib>/{filtered,raw}_feature_bc_matrix.h5`

**Per-barcode annotations.** `/Users/jasonlaster/src/projects/diana-omics/private/analysis/step6-scrna-malignant/barcode_annotations_<lib>.csv.gz`
- QC: qc_pass, dbl_union.
- Labels: compartment, malignant_label (malignant / non_malignant / unresolved).
- Tumor evidence: cnv_*, hap_post_tumor, som_alt_mol.
- Read step6's `scrna_malignant_report.md` sections 1-2 first.

**BAMs (remote).**
- `s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox/2026-10-02-scrna-seq-kh022/data/signios/1012026/<lib>/per_sample_outs/<lib>/sample_alignments.bam`
- Local .bai files sit next to the matrices.
- Presign with `aws s3 presign --region us-east-1 --expires-in 21600 <s3 url>`, then use
  `samtools view "URL##idx##/local/path.bai" region`. The default region breaks this.
- For a working example, see `step6-scrna-malignant/scripts/05_fetch_regions.sh`.
- The KH022-1-1 delivered .bai does not index its BAM correctly at some offsets; step 2a reported success with it, so
  verify. If a region fails, regenerate the index only for the regions you need, or stream and filter.
- **Never download whole BAMs. Cap total transfer at ~5 GB per module and report bytes moved.**
- BAM tags (Cell Ranger): CB, UB, xf (25 = counted), RE (E exonic / N intronic / I intergenic), GX/GN (gene), MAPQ 255 = unique.

**Somatic truth.** `step8-wgs-somatic/results/final/consensus_pass.vcf.gz` holds the WGS Mutect2+Strelka2 consensus,
16,967 PASS calls on GRCh38. The tumor WGS is the 3/13 block; KH022 is probably the 4/10 core, so allow for ~10%
subclone differences.

**Copy number.** `step5-ascn/segments_fit_S1b_p0.35_ploidy2.80.standardized.tsv` gives chrom, start, end, nA, nB, CN
(purity 0.35, ploidy 2.8).

**Gene coordinates.** `/private/tmp/claude-501/-Users-jasonlaster-src-projects-diana-omics/f61c14bf-e23e-4829-a09a-24be63d09400/scratchpad/gene_coords.tsv`
(GENCODE v23 genes, GRCh38), with the GTF next to it at `step15/g23.gtf.gz` and gene features at
`step15/gene_features.csv`.

**Gene-level tables.**
- `step13-targets/all_genes_tumor_vs_other.csv.gz`: tumor vs non-malignant and vs normal epithelium, ambient share.
- `step15-tnbc-outliers/tumor_cells_vs_public_tnbc.csv.gz` and `scripts/03_tumor_cells_vs_public_tnbc.py`: Diana vs
  8 public TNBC tumors with the nuclei-vs-cell bias model.
- `step18-tumor-vs-normal-epi/de_v2_tumor_vs_luminal.csv.gz`.

**Public TNBC.** `/Users/jasonlaster/src/projects/diana-omics/private/scrna/runs/tnbc-*/public-*/analysis.h5ad` holds the
GSE161529 whole cells, with layers['counts'] and obs.coarse_label_hint.

**Candidate genes and controls.** `step19-qc/candidate_genes.tsv`. Every module must report on all of them.

## Rules

- **Public repo.** `/Users/jasonlaster/src/projects/diana-omics` is public. Write only under
  `private/analysis/step19-qc/<your module>/`; scratch files go in the session scratchpad. No git, no push, no Artifact.
- **No outbound contact.** Nothing to anyone: no email, no uploads of patient data. Public reference downloads are OK
  if small (<500 MB) and named in your README.
- **Cost.** Local compute only (18 cores, 36 GB RAM). S3 reads are allowed under the transfer cap. No cloud jobs.
- **Environments.** Use `uv run --no-project --python 3.11 --with <pkgs> python script.py`; the repo .venv lacks
  pandas. Pin versions in your README.
- **Reproducibility.** Every number must come from a script saved in your module folder. Write a README with the exact
  commands, inputs (with checksums for small inputs), runtime, bytes transferred and versions.
- **Calibration.** Give confidence intervals or replicate (L1 vs L2) agreement for every headline number. Say what
  would falsify each conclusion.
- **Final reply.** At most 300 words: key numbers, which candidate claims passed or failed, and anything surprising.
