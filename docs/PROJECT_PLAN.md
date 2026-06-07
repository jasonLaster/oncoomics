# Diana HRD Omics Project Plan

## Mission

Build a reproducible, reviewer-ready HRD omics validation project before applying any open-source workflow to Diana's own files. The project should answer one narrow question first:

Can we reproduce known-enough HRD biology on public breast-cancer validation datasets, with clear failures and confidence labels, before using the same evidence table for Diana?

The output should be an auditable evidence packet, not a black-box score. Each sample-level result should state the input files, source dataset, tool version, reference build, score or finding, agreement with known labels, confidence, caveats, and action boundary.

## Scope

Primary scope:

1. BRCA1/2 and HRR causal alteration evidence.
2. Biallelic or functional second-hit evidence: LOH, deletion, allele-specific copy number, methylation/expression context if available.
3. Genome-wide HRD scar/signature evidence: LOH/LST/TAI style copy-number scars, SBS3-like mutational signature, indel/microhomology, structural-variant patterns, and CHORD/HRDetect-style classifier evidence where inputs support it.
4. Conservative confidence calls: strong, suggestive, incomplete, discordant, not assessable.

Secondary context lane:

1. TNBC RNA subtype, PAM50/basal-like status, and immune/stromal/proliferation modules only when they help validate sample handling or interpret HRD-adjacent biology.
2. This lane should not delay the first HRD validation panel.

Out of scope for this project start:

1. ctDNA/MRD assay reproduction.
2. Vaccine antigen ranking or immunogenicity adjudication.
3. Proprietary recurrence-score reproduction.
4. Functional drug testing.
5. Treatment recommendations.

## Technology Plan

Bun is the project scripting layer. Use it for source checks, API probes, dataset catalog fetchers, manifest creation, and one-off reproducibility utilities.

Python is the first local analysis layer because Python 3.9 is available in this checkout and R is not installed locally. Use Python for tabular joins, source manifests, sample-panel freezing, summary statistics, plots, confusion matrices, and report generation.

External adapters are reserved for specialized raw-genomics tools:

1. nf-core/sarek for raw WGS/WES tumor-normal workflows when FASTQ/BAM/CRAM access exists.
2. SigProfiler tools for mutation-matrix generation and signature assignment.
3. Containerized R or Conda for CHORD, scarHRD, genefu, and GSVA when those become necessary.
4. FACETS/ASCAT/PURPLE-style outputs for allele-specific copy number and purity/ploidy; do not claim biallelic loss without this evidence or an explicit caveat.

## Research Takeaways

TCGA-BRCA is the phase-1 anchor because GDC exposes a publication-linked breast multi-omics freeze with open processed artifacts, subtype labels, mutation files, RNA matrices, copy-number segments, methylation, RPPA, and clinical data. Controlled raw data should be treated as later work.

cBioPortal and UCSC Xena are fast cross-check sources. They are useful for mutation/CNA/clinical and expression/phenotype slices, but the plan must record processing differences and avoid silently mixing matrices from different pipelines.

The 560 breast cancer WGS cohort, HRDetect, and CHORD literature are the HRD signature backbone. They are better suited for WGS-style positive controls than TCGA exomes alone because structural-variant and genome-wide signature patterns matter.

METABRIC, CPTAC Breast, Hartwig, and DepMap/CCLE are staged sources. They are valuable, but the project should not block phase 1 on controlled access, access requests, or cell-line-only biology.

HRD is not one number. The project must keep causal alteration, allele state, and genome-wide scar/signature evidence separate. A sample can be BRCA-altered without being confidently HRD-callable from the available data.

## Milestones

## Phase status

Phase 1 is complete as of the committed workflow in `9938d1f Initial HRD omics validation workflow`.

Completed Phase 1 scope:

1. Source audit and validation-atlas manifest.
2. Public processed-data fetches from cBioPortal/TCGA-BRCA, GDC open catalog metadata, and UCSC Xena.
3. Frozen HRD reference panel.
4. HRR event, allele-state proxy, scar-proxy, RNA-context, and failure-mode evidence tables.
5. Reviewer packet and Diana readiness gate.
6. End-to-end validation with `bun run run:all` and `bun run verify:outputs`.

Phase 1 was intentionally processed-data-only. The next phase must prove representative raw-data ingestion and tumor-normal workflow mechanics before Diana's FASTQ/BAM/CRAM files arrive.

Phase 2A is complete as of `6d930ea Add raw-data readiness smoke workflow`: the project streams and validates a real SEQC2/HCC1395 tumor-normal FASTQ subset.

Phase 2B is complete for local file-contract validation: the project builds a read-backed synthetic smoke reference, aligns the HCC1395 tumor-normal FASTQ subset with `bwa mem`, produces coordinate-sorted/indexed BAMs with `samtools`, and validates read groups, shared reference hash, mapped reads, and BAM/BAI presence.

Phase 2C is complete for partial real-human-reference validation: the project downloads checksum-verified UCSC hg38 and hg19 chr13+chr17 FASTA references, indexes them, aligns HCC1395 tumor-normal reads to both builds, and validates BAM contracts and build comparison summaries.

Phase 2D is complete for one full-reference caller-readiness smoke: the project downloads and md5-validates the UCSC hg38 analysis set, builds `.fai` and BWA indexes, aligns HCC1395 tumor-normal reads to the full reference, validates caller-ready BAM contracts with BRCA interval metadata, and produces an indexed bcftools VCF smoke.

Phase 2E is complete for one downsampled production-style somatic smoke: the project pins GATK 4.6.2.0, adds the GATK sequence dictionary for the full hg38 analysis-set reference, fetches SEQC2/HCC1395 v1.2.1 SNV/INDEL truth VCFs, aligns a 50,000 read-pair/end HCC1395 WES downsample, runs Mutect2 and FilterMutectCalls, and validates an indexed filtered somatic VCF. The bounded downsample produced zero PASS calls, so it validates execution/file contracts rather than sensitivity.

The next gate is Phase 2F: production resources and full-depth WES benchmark behavior. This requires known-sites/germline-resource/PoN/contamination/orientation-bias/duplicate/BQSR policy, capture intervals, richer QC, and a full WES or materially larger WES truth-set comparison.

### Milestone 0: Project Baseline And Source Audit

Goal: Freeze what the Diana wiki says, what the project will analyze, and which sources are valid enough for the first benchmark.

Deliverables:

1. `docs/WIKI_SOURCE_SUMMARY.md` with the local wiki path, source pages read, and scope guardrails.
2. `docs/SOURCE_MAP.md` with official dataset/tool links and access posture.
3. `manifests/validation_atlases.json` with machine-readable dataset/tool metadata.
4. `scripts/verify-plan.ts` as the first verifier.

Verifier:

1. `bun run verify:plan` passes locally.
2. Required wiki pages exist under `/Users/jasonlaster/src/projects/diana-tnbc/obsidian/wiki/omics`.
3. Every validation source in the manifest has an access posture, primary use, source URL, expected artifact, and first verifier.
4. The plan contains explicit milestone-level verifiers.

Exit criteria:

1. No missing source pages.
2. No phase-1 source depends on controlled-access raw data.
3. R absence is recorded as a runtime warning, not a hidden blocker.

### Milestone 1: Dataset Catalog Fetchers

Goal: Build small Bun fetchers that collect metadata, not large omics payloads.

Deliverables:

1. `scripts/fetch-gdc-catalog.ts` for GDC project/file metadata and manifests.
2. `scripts/fetch-cbioportal-study.ts` for cBioPortal study metadata, sample lists, mutation/CNA profile availability, and clinical fields.
3. `scripts/fetch-xena-catalog.ts` for TCGA-BRCA matrix and phenotype availability.
4. `data/processed/catalog/*.json` with normalized source metadata.

Verifier:

1. Each fetcher supports `--dry-run` and emits a deterministic JSON summary.
2. GDC catalog rows include project, data type, workflow type, access level, file ID, size, md5 when available, and source URL.
3. cBioPortal rows include study ID, sample count, molecular profile IDs, and sample-list IDs.
4. Xena rows include hub, dataset ID, cohort, unit or transform, and dimensions if available.
5. No controlled-access file download is attempted in phase 1.

Exit criteria:

1. TCGA-BRCA, cBioPortal BRCA PanCancer Atlas, and UCSC Xena BRCA metadata can be refreshed.
2. Source metadata is reproducible across two runs except timestamp fields.
3. Fetch logs clearly distinguish open, registered, controlled, and access-request sources.

### Milestone 2: Frozen HRD Reference Panel

Goal: Select a small known-enough panel before running any scoring workflow.

Panel design:

1. Positive controls: BRCA1/2-deficient or strong HRD-signature breast tumors.
2. Mechanistic controls: BRCA1-methylated, PALB2/RAD51C-like, or HRR-defective cases where public evidence supports HRD.
3. Negative controls: BRCA/HRR-wildtype tumors with low scar/signature evidence.
4. Ambiguous controls: one HRR alteration, weak scar, low purity, WES-only, or conflicting source labels.

Deliverables:

1. `manifests/hrd_reference_panel.csv`.
2. `docs/reference-panel-label-rules.md`.
3. A crosswalk from source sample IDs to TCGA barcodes, ICGC IDs, cBioPortal sample IDs, and Xena IDs where relevant.

Verifier:

1. Each sample has a label source and at least one machine-readable data source.
2. Positive, negative, and ambiguous labels are frozen before running tools.
3. No sample is labeled positive solely because of a single unreviewed BRCA/HRR variant.
4. The panel contains enough cases to compute a small confusion matrix and enough ambiguous cases to test conservative labeling.

Exit criteria:

1. Reviewer could read the label rule and understand why each sample is a benchmark.
2. Sample ID crosswalk has no unresolved duplicate or truncated IDs.
3. The panel has a "do not over-read" note for WES-only and low-purity cases.

### Milestone 3: Open Data Fetch And Integrity Checks

Goal: Fetch only the data needed for the frozen panel and baseline TCGA cross-checks.

Deliverables:

1. Raw fetched files under `data/raw/<source>/`.
2. Immutable file manifest with URL, fetched timestamp, file size, checksum if available, access level, and script version.
3. Normalized tables under `data/processed/<source>/`.

Verifier:

1. File hashes or sizes match the source manifest.
2. Parsed tables have expected row/column counts.
3. TCGA/cBioPortal/Xena sample intersections are reported explicitly.
4. Clinical, mutation, CNA, expression, and subtype tables are not merged until sample barcodes are normalized and logged.
5. No PHI, token, or controlled raw file is committed or written into tracked docs.

Exit criteria:

1. The benchmark panel can be rebuilt from `data/raw` plus fetch manifests.
2. Every processed table includes source provenance columns.
3. A failed fetch leaves a visible failure record rather than a partial silent table.

### Milestone 4: HRR Event And Allele-State Evidence

Goal: Build the first evidence table for causal alteration and second-hit state.

Deliverables:

1. `results/hrd_event_table.csv`: gene, alteration, consequence, source, VAF/depth when available, germline/somatic status, and annotation confidence.
2. `results/allele_state_table.csv`: copy-number, LOH/deletion, purity/ploidy context, methylation/expression note if available, and second-hit status.
3. `notebooks/01_event_and_allele_state.ipynb` or equivalent script/report.

Verifier:

1. BRCA1/2/HRR event calls match cBioPortal/GDC labels for known examples or discrepancies are logged.
2. Biallelic claims require allele-state evidence or are downgraded to incomplete.
3. Purity/ploidy availability is explicit for every sample.
4. A sample cannot advance to "strong HRD" from variant evidence alone.

Exit criteria:

1. Each reference-panel sample has a causal-event status: supported, absent, ambiguous, or not assessable.
2. Each reference-panel sample has a second-hit status: supported, absent, ambiguous, or not assessable.
3. Discordant sources are captured in a reviewer-readable note.

### Milestone 5: Scar, Signature, And HRD Classifier Evidence

Goal: Add genome-wide evidence while respecting input limitations.

Deliverables:

1. `results/scar_signature_table.csv`: scarHRD-style scores if inputs support them, SBS3/signature assignment, indel/microhomology/SV features where available, CHORD/HRDetect-style class when inputs support it.
2. `results/hrd_confusion_matrix.csv`: expected label versus predicted class.
3. `results/hrd_failure_modes.csv`: low purity, WES-only limitations, missing SVs, missing methylation, insufficient mutation count, copy-number ambiguity, or discordant signatures.

Verifier:

1. Positive controls mostly land HRD-like when the required data types are available.
2. Negative controls mostly remain HRD-negative or low-confidence.
3. Ambiguous controls are allowed to remain ambiguous and should not be forced into a clean binary.
4. WES-only samples are never reported as equivalent to WGS for structural/rearrangement evidence.
5. Signature tools report genome build, matrix type, minimum mutation count, and reconstruction or quality metrics.

Exit criteria:

1. The validation report names which tools are mechanically trustworthy and where they fail.
2. The project has a conservative decision rule for "strong HRD", "suggestive HRD", "discordant", and "not assessable".
3. The evidence table is ready for reviewer sanity-check before Diana data is touched.

### Milestone 6: RNA Context Lane

Goal: Add TNBC subtype and RNA module context only after the HRD validation harness is stable.

Deliverables:

1. `results/rna_subtype_context.csv`: TNBCtype or reproduced subtype label, runner-up score, PAM50/basal-like call, and confidence.
2. `results/rna_module_context.csv`: immune, proliferation, LAR/androgen, EMT/stroma, interferon, and antigen-presentation modules.
3. A note separating RNA subtype biology from proprietary TNBC-DX/Reveal-style scores.

Verifier:

1. Input normalization is recorded for every classifier.
2. TNBCtype-6, TNBCtype-4, PAM50, and module labels are not mixed without schema labels.
3. Known LAR/basal/mesenchymal controls behave as expected or the failure mode is recorded.
4. Batch-sensitive or borderline calls are labeled borderline.

Exit criteria:

1. RNA context can be shown next to HRD evidence without turning into a treatment claim.
2. The lane can be skipped cleanly if RNA data is unavailable.

### Milestone 7: Reviewer Packet And Diana-Readiness Gate

Goal: Package the benchmark output and decide whether it is ready to apply to Diana's files.

Deliverables:

1. `results/reviewer_packet.md`.
2. `results/evidence_tables/` with event, allele-state, scar/signature, classifier, and failure-mode tables.
3. `results/methods.md` with tool versions, inputs, reference builds, and caveats.
4. `results/diana_readiness_gate.md` with a go/no-go checklist.

Verifier:

1. One command rebuilds the benchmark report from the current manifests.
2. All evidence tables have source, tool, version, sample, data-layer, confidence, and caveat columns.
3. The report contains no treatment recommendation and no unvalidated clinical claim.
4. The Diana-readiness gate requires raw-file inventory, sample timing, matched normal status, purity/tumor content, reference build, and reviewer sign-off.

Exit criteria:

1. A reviewer can tell what was run, what agreed, what failed, and what would be needed to make the result clinically actionable.
2. Applying the workflow to Diana's data is a separate intentional step, not an accidental continuation of validation.

## Completed Phase 1 Slice

This slice has been completed:

1. Kept the current plan verifier.
2. Added a Bun cBioPortal/GDC/Xena phase-1 fetcher.
3. Generated a TCGA-BRCA open-data catalog without downloading controlled raw data.
4. Created the first candidate reference panel from metadata and public labels.
5. Verified the panel and evidence tables.

This gives us a clean foundation: source truth first, labels second, scoring third.

## Remaining Phases

### Phase 2A: Representative Raw-Data FASTQ Smoke

Status: complete and validated.

Goal: use public raw tumor-normal data now, before Diana's files arrive, to prove the project can resolve representative raw-read sources, build tumor-normal samplesheets, and validate FASTQ pairing/QC.

Representative source:

1. SEQC2/HCC1395 under SRA study `SRP162370`.
2. Tumor-normal breast/TNBC cell-line pair: HCC1395 tumor and HCC1395BL matched normal.
3. WES and WGS runs, including FFPE/process-stress and cross-platform WGS options.
4. SEQC2 benchmark/truth-set artifacts under the NCBI ReferenceSamples FTP tree.

Deliverables:

1. `manifests/raw_representative_panel.csv`.
2. `docs/RAW_DATA_READINESS.md`.
3. `manifests/raw_samplesheet.csv`.
4. `manifests/raw_smoke_samplesheet.csv`.
5. `results/raw_smoke/README.md`.
6. `results/raw_smoke/fastq_smoke_summary.csv`.
7. `results/raw_smoke/tooling_audit.md`.

Verifier:

1. `bun run fetch:raw-candidates` refreshes the selected SRA run metadata.
2. `bun run verify:outputs` confirms every raw representative pair has public tumor and normal runs.
3. `bun run smoke:raw` streams 1,000 read pairs per end from the SEQC2/HCC1395 minimal WES pair and validates paired FASTQ structure.
4. `bun run run:all` includes the Phase 2A smoke and passes.

### Phase 2B: Alignment And Somatic-Caller Input Readiness

Status: complete and validated for local file-contract validation.

Goal: take the Phase 2A smoke FASTQs or a larger downsample through alignment/BAM generation and somatic-caller input validation.

Completed deliverables:

1. `manifests/alignment_smoke_samplesheet.csv`.
2. Read-backed synthetic smoke reference.
3. Coordinate-sorted/indexed tumor and normal BAMs from the minimal WES pair.
4. `results/alignment_smoke/bam_validation_summary.csv`.

Verifier:

1. `bun run smoke:alignment` produces coordinate-sorted BAMs with indexes and read groups.
2. `bun run verify:outputs` confirms the Phase 2B file contracts and caveats.

### Phase 2C: Partial Human-Reference Smoke

Status: complete and validated.

Goal: validate real-human-reference alignment handling before full reference bundles.

Verifier:

1. `bun run fetch:human-reference-smoke` downloads checksum-verified UCSC hg38/hg19 chr13+chr17 references.
2. `bun run smoke:human-reference` aligns tumor/normal reads to both builds and validates BAM contracts.
3. `bun run verify:outputs` confirms partial-reference boundaries remain explicit.

### Phase 2D: Full-Reference Caller-Readiness Smoke

Status: complete and validated.

Goal: validate one full analysis-set reference and an indexed VCF caller contract.

Verifier:

1. `bun run fetch:full-reference-smoke` downloads and md5-validates the UCSC hg38 analysis-set FASTA.
2. `bun run smoke:full-reference` aligns tumor/normal reads to the full reference and produces an indexed bcftools VCF smoke.
3. `bun run verify:outputs` confirms BRCA interval metadata, full-reference BAM contracts, and caller-readiness caveats.

### Phase 2E: Production Somatic Caller Smoke

Status: complete and validated for one downsampled Mutect2 smoke.

Goal: validate production-style tumor-normal somatic caller execution before Diana raw files arrive.

Deliverables:

1. `manifests/production_somatic_smoke_samplesheet.csv`.
2. `results/production_somatic_smoke/asset_summary.json`.
3. `results/production_somatic_smoke/bam_validation_summary.csv`.
4. `results/production_somatic_smoke/mutect2_smoke_summary.csv`.
5. `results/production_somatic_smoke/production_somatic_summary.csv`.

Verifier:

1. `bun run fetch:production-somatic` pins GATK, creates the sequence dictionary, and fetches SEQC2 truth materials.
2. `bun run smoke:production-somatic` runs a 50,000 read-pair/end HCC1395 WES downsample through BWA/samtools and GATK Mutect2/FilterMutectCalls.
3. `bun run verify:outputs` confirms the indexed filtered VCF, truth-comparison status, and WES-versus-WGS evidence boundary.

### Phase 2F: Production Resources And Full-Depth WES Benchmark

Status: planned.

Goal: move from production-style execution smoke to full-depth WES benchmark behavior.

Required deliverables:

1. Production known-sites, germline resource, panel-of-normals, contamination, orientation-bias, duplicate-marking, BQSR, and interval policy.
2. Full WES or materially larger HCC1395 WES run.
3. Depth/coverage/QC reports.
4. Production-resource-filtered somatic VCFs.
5. SEQC2 truth-set sensitivity/specificity report where compatible.

### Phase 3: WGS Signature And Allele-Specific HRD

Goal: replace Phase 1 proxy evidence with real WGS-capable outputs where inputs allow.

Deliverables:

1. Raw-derived SNV/indel VCFs.
2. Allele-specific copy-number/purity-ploidy outputs.
3. SV/rearrangement outputs.
4. Mutation matrices and SBS3/signature assignment.
5. CHORD/scarHRD/HRDetect-style evidence tables where tool inputs support them.

Verifier:

1. Full WES/WGS or explicit subset run has reproducible logs and versions.
2. Tool outputs are ingested into the evidence table without collapsing distinct evidence classes.
3. WES-only and WGS-capable results remain clearly separated.

### Phase 4: Diana Data

Goal: apply only the validated raw-data workflow to Diana's files.

Gate:

1. Raw-file inventory is available.
2. Matched normal status and reference build are known.
3. Tissue timing, tumor purity/content, fixation, and extraction context are recorded.
4. Reviewer sign-off is obtained for the representative-data smoke tests and caveats.
5. Clinical action remains clinician-owned and requires orthogonal validation when needed.
