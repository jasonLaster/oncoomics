import { existsSync } from "node:fs";
import { groupBy, parseCsv, pathFromRoot, readJson, readText } from "./lib";

const errors: string[] = [];
const warnings: string[] = [];

function requireFile(relativePath: string) {
  const path = pathFromRoot(relativePath);
  if (!existsSync(path)) {
    errors.push(`Missing ${relativePath}`);
  }
}

function requireRows(relativePath: string, minimumRows: number) {
  requireFile(relativePath);
  if (!existsSync(pathFromRoot(relativePath))) {
    return [];
  }
  const rows = parseCsv(readText(pathFromRoot(relativePath)));
  if (rows.length < minimumRows) {
    errors.push(`${relativePath} has ${rows.length} rows; expected at least ${minimumRows}.`);
  }
  return rows;
}

function requireColumns(relativePath: string, rows: Record<string, string>[], columns: string[]) {
  const actual = new Set(Object.keys(rows[0] ?? {}));
  for (const column of columns) {
    if (!actual.has(column)) {
      errors.push(`${relativePath} is missing required column ${column}.`);
    }
  }
}

const requiredFiles = [
  "data/processed/catalog/cbioportal_tcga_brca_summary.json",
  "data/processed/catalog/gdc_tcga_brca_open_summary.json",
  "data/processed/catalog/xena_tcga_brca_clinical_summary.json",
  "manifests/file_manifest.json",
  "manifests/hrd_reference_panel.csv",
  "manifests/raw_representative_panel.csv",
  "manifests/raw_representative_panel_summary.json",
  "manifests/raw_samplesheet.csv",
  "manifests/raw_smoke_samplesheet.csv",
  "manifests/alignment_smoke_samplesheet.csv",
  "manifests/human_reference_smoke_references.csv",
  "manifests/human_reference_smoke_samplesheet.csv",
  "manifests/full_reference_smoke_references.csv",
  "manifests/full_reference_smoke_samplesheet.csv",
  "manifests/production_somatic_smoke_samplesheet.csv",
  "manifests/full_wes_benchmark_samplesheet.csv",
  "manifests/reference_panel_validation.json",
  "docs/reference-panel-label-rules.md",
  "results/hrd_event_table.csv",
  "results/allele_state_table.csv",
  "results/scar_signature_table.csv",
  "results/hrd_confusion_matrix.csv",
  "results/hrd_failure_modes.csv",
  "results/hrd_predictions.csv",
  "results/rna_subtype_context.csv",
  "results/rna_module_context.csv",
  "results/methods.md",
  "results/reviewer_packet.md",
  "results/diana_readiness_gate.md",
  "results/raw_smoke/README.md",
  "results/raw_smoke/fastq_smoke_summary.csv",
  "results/raw_smoke/fastq_smoke_summary.json",
  "results/raw_smoke/samplesheet_summary.json",
  "results/raw_smoke/tooling_audit.json",
  "results/raw_smoke/tooling_audit.md",
  "results/alignment_smoke/README.md",
  "results/alignment_smoke/reference_summary.json",
  "results/alignment_smoke/tool_versions.json",
  "results/alignment_smoke/alignment_smoke_summary.csv",
  "results/alignment_smoke/alignment_smoke_summary.json",
  "results/alignment_smoke/bam_validation_summary.csv",
  "results/alignment_smoke/bam_validation_summary.json",
  "results/human_reference_smoke/README.md",
  "results/human_reference_smoke/reference_assets_summary.json",
  "results/human_reference_smoke/tool_versions.json",
  "results/human_reference_smoke/human_reference_alignment_summary.csv",
  "results/human_reference_smoke/human_reference_alignment_summary.json",
  "results/human_reference_smoke/bam_validation_summary.csv",
  "results/human_reference_smoke/bam_validation_summary.json",
  "results/human_reference_smoke/reference_comparison_summary.csv",
  "results/human_reference_smoke/reference_comparison_summary.json",
  "results/full_reference_smoke/README.md",
  "results/full_reference_smoke/reference_assets_summary.json",
  "results/full_reference_smoke/tool_versions.json",
  "results/full_reference_smoke/full_reference_alignment_summary.csv",
  "results/full_reference_smoke/full_reference_alignment_summary.json",
  "results/full_reference_smoke/bam_validation_summary.csv",
  "results/full_reference_smoke/bam_validation_summary.json",
  "results/full_reference_smoke/caller_smoke_summary.csv",
  "results/full_reference_smoke/caller_smoke_summary.json",
  "results/production_somatic_smoke/README.md",
  "results/production_somatic_smoke/asset_summary.json",
  "results/production_somatic_smoke/tool_versions.json",
  "results/production_somatic_smoke/fastq_summary.csv",
  "results/production_somatic_smoke/fastq_summary.json",
  "results/production_somatic_smoke/bam_validation_summary.csv",
  "results/production_somatic_smoke/bam_validation_summary.json",
  "results/production_somatic_smoke/mutect2_smoke_summary.csv",
  "results/production_somatic_smoke/mutect2_smoke_summary.json",
  "results/production_somatic_smoke/production_somatic_summary.csv",
  "results/production_somatic_smoke/production_somatic_summary.json",
  "results/full_wes_benchmark/README.md",
  "results/full_wes_benchmark/asset_summary.json",
  "results/full_wes_benchmark/tool_versions.json",
  "results/full_wes_benchmark/full_wes_fastq_validation.csv",
  "results/full_wes_benchmark/full_wes_fastq_validation.json",
  "results/full_wes_benchmark/full_wes_bam_validation.csv",
  "results/full_wes_benchmark/full_wes_bam_validation.json",
  "results/full_wes_benchmark/truth_overlap_benchmark_summary.csv",
  "results/full_wes_benchmark/truth_overlap_benchmark_summary.json",
  "results/full_wes_benchmark/full_wes_benchmark_summary.csv",
  "results/full_wes_benchmark/full_wes_benchmark_summary.json"
];

for (const file of requiredFiles) {
  requireFile(file);
}

const panel = requireRows("manifests/hrd_reference_panel.csv", 16);
requireColumns("manifests/hrd_reference_panel.csv", panel, [
  "sample_id",
  "panel_category",
  "expected_hrd_label",
  "label_source",
  "second_hit_proxy",
  "caveat"
]);

const panelCategories = new Set(panel.map((row) => row.panel_category));
for (const category of ["positive_control", "ambiguous_control", "negative_control"]) {
  if (!panelCategories.has(category)) {
    errors.push(`Reference panel is missing category ${category}.`);
  }
}

const eventRows = requireRows("results/hrd_event_table.csv", panel.length);
requireColumns("results/hrd_event_table.csv", eventRows, ["sample_id", "source", "tool", "tool_version", "gene", "event_class", "confidence", "caveat"]);

const alleleRows = requireRows("results/allele_state_table.csv", panel.length);
requireColumns("results/allele_state_table.csv", alleleRows, ["sample_id", "source", "tool", "gene", "second_hit_status", "caveat"]);

const scarRows = requireRows("results/scar_signature_table.csv", panel.length);
requireColumns("results/scar_signature_table.csv", scarRows, [
  "sample_id",
  "source",
  "tool",
  "fraction_genome_altered",
  "scar_proxy_class",
  "sbs3_signature_status",
  "structural_variant_signature_status",
  "predicted_hrd_class",
  "caveat"
]);

for (const row of scarRows) {
  if (row.sbs3_signature_status !== "not_assessable_from_phase1_processed_data") {
    errors.push(`Unexpected SBS3 status for ${row.sample_id}: ${row.sbs3_signature_status}`);
  }
  if (row.structural_variant_signature_status !== "not_assessable_from_phase1_processed_data") {
    errors.push(`Unexpected SV signature status for ${row.sample_id}: ${row.structural_variant_signature_status}`);
  }
}

const predictions = requireRows("results/hrd_predictions.csv", panel.length);
requireColumns("results/hrd_predictions.csv", predictions, ["sample_id", "expected_hrd_label", "predicted_hrd_class"]);

const positiveStrong = predictions.filter((row) => row.predicted_hrd_class === "strong_hrd_like_candidate");
if (positiveStrong.length === 0) {
  warnings.push("No strong HRD-like candidates were identified; check whether the public panel is too conservative.");
}

const rnaSubtype = requireRows("results/rna_subtype_context.csv", panel.length);
requireColumns("results/rna_subtype_context.csv", rnaSubtype, ["sample_id", "source", "tool", "inferred_context", "confidence", "caveat"]);

const rnaModules = requireRows("results/rna_module_context.csv", panel.length);
requireColumns("results/rna_module_context.csv", rnaModules, ["sample_id", "source", "tool", "basal_marker_z", "immune_inflammation_marker_z", "caveat"]);

const rawPanel = requireRows("manifests/raw_representative_panel.csv", 8);
requireColumns("manifests/raw_representative_panel.csv", rawPanel, [
  "pair_id",
  "role",
  "run",
  "assay",
  "phase",
  "library_strategy",
  "library_layout",
  "sample_name",
  "size_mb",
  "consent",
  "download_path",
  "fastq_1_url",
  "fastq_2_url",
  "fastq_1_md5",
  "fastq_2_md5",
  "fastq_1_bytes",
  "fastq_2_bytes",
  "use_case",
  "caveat"
]);

const rolesByPair = new Map<string, Set<string>>();
for (const row of rawPanel) {
  if (Object.values(row).some((value) => value === "undefined")) {
    errors.push(`Raw representative panel row contains undefined: ${JSON.stringify(row)}`);
  }
  if (row.consent !== "public") {
    errors.push(`Raw representative run is not public: ${row.run}`);
  }
  if (!row.download_path.startsWith("http")) {
    errors.push(`Raw representative run is missing download path: ${row.run}`);
  }
  if (!row.fastq_1_url.startsWith("https://") || !row.fastq_2_url.startsWith("https://")) {
    errors.push(`Raw representative run is missing ENA FASTQ URLs: ${row.run}`);
  }
  const roles = rolesByPair.get(row.pair_id) ?? new Set<string>();
  roles.add(row.role);
  rolesByPair.set(row.pair_id, roles);
}

for (const [pairId, roles] of rolesByPair.entries()) {
  if (!roles.has("tumor") || !roles.has("normal")) {
    errors.push(`Raw representative pair ${pairId} does not have both tumor and normal roles.`);
  }
}

const rawSummary = readJson<Record<string, unknown>>(pathFromRoot("manifests/raw_representative_panel_summary.json"));
if (rawSummary.allPublic !== true) {
  errors.push("Raw representative panel summary does not validate all runs as public.");
}

const rawSamplesheet = requireRows("manifests/raw_samplesheet.csv", 8);
requireColumns("manifests/raw_samplesheet.csv", rawSamplesheet, [
  "pair_id",
  "patient",
  "sample",
  "role",
  "status",
  "run_accession",
  "fastq_1",
  "fastq_2",
  "source",
  "caveat"
]);
for (const row of rawSamplesheet) {
  if (Object.values(row).some((value) => value === "undefined")) {
    errors.push(`Raw samplesheet row contains undefined: ${JSON.stringify(row)}`);
  }
}

const smokeSamplesheet = requireRows("manifests/raw_smoke_samplesheet.csv", 2);
requireColumns("manifests/raw_smoke_samplesheet.csv", smokeSamplesheet, [
  "pair_id",
  "patient",
  "sample",
  "role",
  "status",
  "run_accession",
  "fastq_1",
  "fastq_2",
  "source",
  "caveat"
]);
for (const row of smokeSamplesheet) {
  if (Object.values(row).some((value) => value === "undefined")) {
    errors.push(`Raw smoke samplesheet row contains undefined: ${JSON.stringify(row)}`);
  }
  if (!row.fastq_1.includes(row.run_accession) || !row.fastq_2.includes(row.run_accession)) {
    errors.push(`Raw smoke samplesheet paths do not include run accession for ${row.run_accession}`);
  }
}
if (!smokeSamplesheet.some((row) => row.role === "tumor") || !smokeSamplesheet.some((row) => row.role === "normal")) {
  errors.push("Raw smoke samplesheet must include tumor and normal rows.");
}

const rawSmokeRows = requireRows("results/raw_smoke/fastq_smoke_summary.csv", 2);
requireColumns("results/raw_smoke/fastq_smoke_summary.csv", rawSmokeRows, [
  "pair_id",
  "sample_name",
  "role",
  "run",
  "reads_per_end",
  "paired_id_check",
  "local_fastq_1",
  "local_fastq_2"
]);
for (const row of rawSmokeRows) {
  if (Object.values(row).some((value) => value === "undefined")) {
    errors.push(`Raw smoke result row contains undefined: ${JSON.stringify(row)}`);
  }
  if (row.paired_id_check !== "passed") {
    errors.push(`Raw smoke paired-id check failed for ${row.run}`);
  }
  if (Number(row.reads_per_end) < 100) {
    errors.push(`Raw smoke read count too low for ${row.run}: ${row.reads_per_end}`);
  }
}

const rawSmokeSummary = readJson<Record<string, unknown>>(pathFromRoot("results/raw_smoke/fastq_smoke_summary.json"));
if (rawSmokeSummary.status !== "passed") {
  errors.push("Raw FASTQ smoke summary did not pass.");
}

const rawToolingAudit = readJson<Record<string, unknown>>(pathFromRoot("results/raw_smoke/tooling_audit.json"));
if (rawToolingAudit.phase2aReady !== true) {
  errors.push("Raw tooling audit says Phase 2A is not ready.");
}
if (rawToolingAudit.alignmentReady !== true) {
  errors.push("Raw tooling audit says Phase 2B local alignment smoke is not ready.");
}
if (rawToolingAudit.humanReferenceSmokeReady !== true) {
  errors.push("Raw tooling audit says Phase 2C partial human-reference smoke is not ready.");
}
if (rawToolingAudit.fullReferenceSmokeReady !== true) {
  errors.push("Raw tooling audit says Phase 2D full-reference smoke is not ready.");
}
if (rawToolingAudit.callerSmokeReady !== true) {
  errors.push("Raw tooling audit says caller smoke tooling is not ready.");
}
if (rawToolingAudit.productionSomaticSmokeReady !== true) {
  errors.push("Raw tooling audit says Phase 2E production somatic smoke is not ready.");
}
if (rawToolingAudit.fullWesBenchmarkReady !== true) {
  errors.push("Raw tooling audit says Phase 2F full WES benchmark is not ready.");
}

const alignmentSamplesheet = requireRows("manifests/alignment_smoke_samplesheet.csv", 2);
requireColumns("manifests/alignment_smoke_samplesheet.csv", alignmentSamplesheet, [
  "pair_id",
  "patient",
  "sample",
  "role",
  "status",
  "run_accession",
  "fastq_1",
  "fastq_2",
  "reference_id",
  "reference_path",
  "reference_sha256",
  "aligner",
  "read_group_id",
  "read_group_sample",
  "output_bam",
  "output_bai",
  "caveat"
]);
if (!alignmentSamplesheet.some((row) => row.role === "tumor") || !alignmentSamplesheet.some((row) => row.role === "normal")) {
  errors.push("Alignment smoke samplesheet must include tumor and normal rows.");
}
const alignmentReferenceHashes = new Set(alignmentSamplesheet.map((row) => row.reference_sha256));
if (alignmentReferenceHashes.size !== 1) {
  errors.push("Alignment smoke samplesheet must use one shared reference hash.");
}
for (const row of alignmentSamplesheet) {
  if (Object.values(row).some((value) => value === "undefined")) {
    errors.push(`Alignment smoke samplesheet row contains undefined: ${JSON.stringify(row)}`);
  }
  if (!row.output_bam.endsWith(".bam") || !row.output_bai.endsWith(".bam.bai")) {
    errors.push(`Alignment smoke outputs are not BAM/BAI paths for ${row.run_accession}`);
  }
  if (!row.caveat.includes("not a human-reference")) {
    errors.push(`Alignment smoke caveat must preserve non-human-reference boundary for ${row.run_accession}`);
  }
}

const alignmentReferenceSummary = readJson<Record<string, unknown>>(pathFromRoot("results/alignment_smoke/reference_summary.json"));
if (alignmentReferenceSummary.status !== "built") {
  errors.push("Alignment smoke reference summary was not built.");
}
if (alignmentReferenceSummary.referenceType !== "read-backed synthetic smoke reference") {
  errors.push("Alignment smoke reference summary must identify the synthetic smoke reference.");
}
if (Number(alignmentReferenceSummary.contigs) < 1000) {
  errors.push("Alignment smoke reference has too few contigs for the HCC1395 read-pair smoke.");
}
if (!String(alignmentReferenceSummary.caveat ?? "").includes("not GRCh37, GRCh38")) {
  errors.push("Alignment smoke reference summary must preserve reference-build caveat.");
}

const alignmentSummaryRows = requireRows("results/alignment_smoke/alignment_smoke_summary.csv", 1);
requireColumns("results/alignment_smoke/alignment_smoke_summary.csv", alignmentSummaryRows, [
  "status",
  "pair_id",
  "reference_id",
  "aligner",
  "bam_tool",
  "samples",
  "tumor_rows",
  "normal_rows",
  "boundary"
]);
if (alignmentSummaryRows[0]?.status !== "passed") {
  errors.push("Alignment smoke summary CSV did not pass.");
}
if (!alignmentSummaryRows[0]?.boundary.includes("not human-reference alignment")) {
  errors.push("Alignment smoke summary CSV must preserve human-reference boundary.");
}

const alignmentSummary = readJson<Record<string, unknown>>(pathFromRoot("results/alignment_smoke/alignment_smoke_summary.json"));
if (alignmentSummary.status !== "passed") {
  errors.push("Alignment smoke summary JSON did not pass.");
}
if (alignmentSummary.tumorRows !== 1 || alignmentSummary.normalRows !== 1) {
  errors.push("Alignment smoke summary must include one tumor and one normal BAM.");
}
if (!String(alignmentSummary.boundary ?? "").includes("does not validate GRCh37/GRCh38 alignment")) {
  errors.push("Alignment smoke summary JSON must preserve GRCh37/GRCh38 boundary.");
}

const bamRows = requireRows("results/alignment_smoke/bam_validation_summary.csv", 2);
requireColumns("results/alignment_smoke/bam_validation_summary.csv", bamRows, [
  "pair_id",
  "role",
  "run_accession",
  "sample",
  "reference_id",
  "reference_sha256",
  "output_bam",
  "output_bai",
  "bam_exists",
  "bai_exists",
  "quickcheck",
  "sort_order",
  "read_group_present",
  "total_alignments",
  "mapped_alignments",
  "mapped_fraction",
  "properly_paired_alignments",
  "status",
  "caveat"
]);
for (const row of bamRows) {
  if (row.status !== "passed") {
    errors.push(`Alignment smoke BAM validation failed for ${row.run_accession}.`);
  }
  if (row.quickcheck !== "passed") {
    errors.push(`Alignment smoke quickcheck failed for ${row.run_accession}.`);
  }
  if (row.sort_order !== "coordinate") {
    errors.push(`Alignment smoke BAM is not coordinate sorted for ${row.run_accession}.`);
  }
  if (row.read_group_present !== "yes") {
    errors.push(`Alignment smoke BAM is missing read group for ${row.run_accession}.`);
  }
  if (row.bam_exists !== "yes" || row.bai_exists !== "yes") {
    errors.push(`Alignment smoke BAM/BAI paths were not present when validated for ${row.run_accession}.`);
  }
  if (Number(row.total_alignments) <= 0 || Number(row.mapped_alignments) <= 0) {
    errors.push(`Alignment smoke BAM has no mapped alignments for ${row.run_accession}.`);
  }
  if (!row.caveat.includes("not a human-reference")) {
    errors.push(`Alignment smoke BAM caveat must preserve non-human-reference boundary for ${row.run_accession}.`);
  }
}
const bamSummary = readJson<Record<string, unknown>>(pathFromRoot("results/alignment_smoke/bam_validation_summary.json"));
if (bamSummary.status !== "passed") {
  errors.push("Alignment smoke BAM validation JSON did not pass.");
}

const humanReferenceRows = requireRows("manifests/human_reference_smoke_references.csv", 2);
requireColumns("manifests/human_reference_smoke_references.csv", humanReferenceRows, [
  "reference_id",
  "assembly",
  "genome_build",
  "source",
  "source_base_url",
  "chromosomes",
  "genes_covered",
  "source_urls",
  "source_md5s",
  "md5_status",
  "fasta_path",
  "fasta_fai_path",
  "fasta_sha256",
  "fasta_size_bytes",
  "caveat"
]);
const humanReferenceAssemblies = new Set(humanReferenceRows.map((row) => row.assembly));
if (!humanReferenceAssemblies.has("hg38") || !humanReferenceAssemblies.has("hg19")) {
  errors.push("Human-reference smoke must include hg38 and hg19 references.");
}
for (const row of humanReferenceRows) {
  if (row.md5_status !== "passed") {
    errors.push(`Human-reference source MD5 validation did not pass for ${row.reference_id}.`);
  }
  if (!row.chromosomes.includes("chr13") || !row.chromosomes.includes("chr17")) {
    errors.push(`Human-reference smoke ${row.reference_id} must include chr13 and chr17.`);
  }
  if (!row.genes_covered.includes("BRCA2") || !row.genes_covered.includes("BRCA1")) {
    errors.push(`Human-reference smoke ${row.reference_id} must document BRCA1/BRCA2 chromosome coverage.`);
  }
  if (!row.source_urls.split(";").every((url) => url.startsWith("https://hgdownload.soe.ucsc.edu/"))) {
    errors.push(`Human-reference smoke ${row.reference_id} has unexpected source URLs.`);
  }
  if (row.fasta_sha256.length < 32) {
    errors.push(`Human-reference smoke ${row.reference_id} is missing a reference sha256.`);
  }
  if (!row.caveat.includes("Partial human-reference smoke")) {
    errors.push(`Human-reference smoke ${row.reference_id} must preserve partial-reference caveat.`);
  }
}

const humanReferenceSamplesheet = requireRows("manifests/human_reference_smoke_samplesheet.csv", 4);
requireColumns("manifests/human_reference_smoke_samplesheet.csv", humanReferenceSamplesheet, [
  "pair_id",
  "patient",
  "sample",
  "role",
  "status",
  "run_accession",
  "fastq_1",
  "fastq_2",
  "reference_id",
  "assembly",
  "genome_build",
  "chromosomes",
  "genes_covered",
  "reference_path",
  "reference_sha256",
  "read_group_id",
  "read_group_sample",
  "output_bam",
  "output_bai",
  "caveat"
]);
for (const row of humanReferenceSamplesheet) {
  if (!["hg38", "hg19"].includes(row.assembly)) {
    errors.push(`Unexpected human-reference assembly in samplesheet: ${row.assembly}`);
  }
  if (!row.caveat.includes("not full-depth WES/WGS")) {
    errors.push(`Human-reference samplesheet caveat must preserve full-depth boundary for ${row.run_accession} ${row.reference_id}.`);
  }
}
const sampleRowsByReference = groupBy(humanReferenceSamplesheet, (row) => row.reference_id);
for (const [referenceId, rows] of sampleRowsByReference.entries()) {
  if (!rows.some((row) => row.role === "tumor") || !rows.some((row) => row.role === "normal")) {
    errors.push(`Human-reference samplesheet ${referenceId} must include tumor and normal rows.`);
  }
}

const humanReferenceAssets = readJson<Record<string, unknown>>(pathFromRoot("results/human_reference_smoke/reference_assets_summary.json"));
if (humanReferenceAssets.status !== "built") {
  errors.push("Human-reference asset summary was not built.");
}
if (humanReferenceAssets.referenceCount !== 2) {
  errors.push("Human-reference asset summary must include two references.");
}
if (!String(humanReferenceAssets.boundary ?? "").includes("Full-depth Diana or SEQC2 calling still requires full reference bundles")) {
  errors.push("Human-reference asset summary must preserve full-reference boundary.");
}

const humanReferenceSummaryRows = requireRows("results/human_reference_smoke/human_reference_alignment_summary.csv", 1);
requireColumns("results/human_reference_smoke/human_reference_alignment_summary.csv", humanReferenceSummaryRows, [
  "status",
  "sample_rows",
  "references",
  "assemblies",
  "genome_builds",
  "tumor_rows",
  "normal_rows",
  "boundary"
]);
if (humanReferenceSummaryRows[0]?.status !== "passed") {
  errors.push("Human-reference alignment summary CSV did not pass.");
}
if (!humanReferenceSummaryRows[0]?.assemblies.includes("hg38") || !humanReferenceSummaryRows[0]?.assemblies.includes("hg19")) {
  errors.push("Human-reference alignment summary CSV must include hg38 and hg19.");
}
if (!humanReferenceSummaryRows[0]?.boundary.includes("not full-depth WES/WGS")) {
  errors.push("Human-reference alignment summary CSV must preserve full-depth boundary.");
}

const humanReferenceSummary = readJson<Record<string, unknown>>(pathFromRoot("results/human_reference_smoke/human_reference_alignment_summary.json"));
if (humanReferenceSummary.status !== "passed") {
  errors.push("Human-reference alignment summary JSON did not pass.");
}
if (humanReferenceSummary.sampleRows !== 4 || humanReferenceSummary.tumorRows !== 2 || humanReferenceSummary.normalRows !== 2) {
  errors.push("Human-reference alignment summary must include four rows: tumor and normal across two references.");
}
if (!String(humanReferenceSummary.boundary ?? "").includes("does not validate full-depth WES/WGS")) {
  errors.push("Human-reference alignment summary JSON must preserve full-depth boundary.");
}

const humanReferenceBamRows = requireRows("results/human_reference_smoke/bam_validation_summary.csv", 4);
requireColumns("results/human_reference_smoke/bam_validation_summary.csv", humanReferenceBamRows, [
  "pair_id",
  "reference_id",
  "assembly",
  "genome_build",
  "chromosomes",
  "genes_covered",
  "role",
  "run_accession",
  "sample",
  "reference_sha256",
  "output_bam",
  "output_bai",
  "bam_exists",
  "bai_exists",
  "quickcheck",
  "sort_order",
  "read_group_present",
  "expected_contigs_present",
  "reference_contigs",
  "total_alignments",
  "mapped_alignments",
  "mapped_fraction",
  "mapped_by_contig",
  "status",
  "caveat"
]);
for (const row of humanReferenceBamRows) {
  if (row.status !== "passed") {
    errors.push(`Human-reference BAM validation failed for ${row.run_accession} ${row.reference_id}.`);
  }
  if (row.quickcheck !== "passed" || row.sort_order !== "coordinate" || row.read_group_present !== "yes") {
    errors.push(`Human-reference BAM contract failed for ${row.run_accession} ${row.reference_id}.`);
  }
  if (row.bam_exists !== "yes" || row.bai_exists !== "yes") {
    errors.push(`Human-reference BAM/BAI paths were not present when validated for ${row.run_accession} ${row.reference_id}.`);
  }
  if (row.expected_contigs_present !== "yes" || !row.reference_contigs.includes("chr13") || !row.reference_contigs.includes("chr17")) {
    errors.push(`Human-reference BAM header is missing expected contigs for ${row.run_accession} ${row.reference_id}.`);
  }
  if (Number(row.total_alignments) <= 0 || Number(row.mapped_alignments) <= 0) {
    errors.push(`Human-reference BAM has no mapped alignments for ${row.run_accession} ${row.reference_id}.`);
  }
  if (!row.mapped_by_contig.includes("chr13:") || !row.mapped_by_contig.includes("chr17:")) {
    errors.push(`Human-reference mapped-by-contig summary is incomplete for ${row.run_accession} ${row.reference_id}.`);
  }
  if (!row.caveat.includes("not full-depth WES/WGS")) {
    errors.push(`Human-reference BAM caveat must preserve full-depth boundary for ${row.run_accession} ${row.reference_id}.`);
  }
}
const humanReferenceBamSummary = readJson<Record<string, unknown>>(pathFromRoot("results/human_reference_smoke/bam_validation_summary.json"));
if (humanReferenceBamSummary.status !== "passed") {
  errors.push("Human-reference BAM validation JSON did not pass.");
}

const humanReferenceComparisons = requireRows("results/human_reference_smoke/reference_comparison_summary.csv", 2);
requireColumns("results/human_reference_smoke/reference_comparison_summary.csv", humanReferenceComparisons, [
  "run_accession",
  "sample",
  "role",
  "tested_builds",
  "passed_builds",
  "mapped_alignment_range",
  "status",
  "caveat"
]);
for (const row of humanReferenceComparisons) {
  if (row.status !== "passed") {
    errors.push(`Human-reference build comparison failed for ${row.run_accession}.`);
  }
  if (!row.passed_builds.includes("hg38") || !row.passed_builds.includes("hg19")) {
    errors.push(`Human-reference build comparison must pass hg38 and hg19 for ${row.run_accession}.`);
  }
}
const humanReferenceComparisonSummary = readJson<Record<string, unknown>>(pathFromRoot("results/human_reference_smoke/reference_comparison_summary.json"));
if (humanReferenceComparisonSummary.status !== "passed") {
  errors.push("Human-reference comparison summary JSON did not pass.");
}

const fullReferenceRows = requireRows("manifests/full_reference_smoke_references.csv", 1);
requireColumns("manifests/full_reference_smoke_references.csv", fullReferenceRows, [
  "reference_id",
  "assembly",
  "genome_build",
  "source",
  "source_url",
  "source_md5",
  "md5_status",
  "fasta_path",
  "fasta_fai_path",
  "fasta_sha256",
  "fasta_size_bytes",
  "interval_bed_path",
  "interval_regions",
  "interval_genes",
  "caller_smoke_tool",
  "caveat"
]);
const fullReference = fullReferenceRows[0] ?? {};
if (fullReference.reference_id !== "ucsc_hg38_analysis_set_full") {
  errors.push("Full-reference smoke must include ucsc_hg38_analysis_set_full.");
}
if (fullReference.assembly !== "hg38" || fullReference.genome_build !== "GRCh38") {
  errors.push("Full-reference smoke must use hg38/GRCh38 for the first Phase 2D reference.");
}
if (fullReference.md5_status !== "passed") {
  errors.push("Full-reference source MD5 validation did not pass.");
}
if (!fullReference.source_url?.includes("/analysisSet/hg38.analysisSet.fa.gz")) {
  errors.push("Full-reference smoke must use the UCSC hg38 analysisSet FASTA.");
}
if (!fullReference.interval_genes?.includes("BRCA1") || !fullReference.interval_genes?.includes("BRCA2")) {
  errors.push("Full-reference smoke must document BRCA1/BRCA2 interval targets.");
}
if (Number(fullReference.fasta_size_bytes) < 1_000_000_000) {
  errors.push("Full-reference FASTA size is unexpectedly small.");
}
if (!fullReference.caveat?.includes("not full-depth WES/WGS")) {
  errors.push("Full-reference caveat must preserve full-depth boundary.");
}

const fullReferenceSamplesheet = requireRows("manifests/full_reference_smoke_samplesheet.csv", 2);
requireColumns("manifests/full_reference_smoke_samplesheet.csv", fullReferenceSamplesheet, [
  "pair_id",
  "patient",
  "sample",
  "role",
  "status",
  "run_accession",
  "fastq_1",
  "fastq_2",
  "reference_id",
  "assembly",
  "genome_build",
  "reference_path",
  "reference_sha256",
  "interval_bed_path",
  "interval_regions",
  "interval_genes",
  "read_group_id",
  "read_group_sample",
  "output_bam",
  "output_bai",
  "caller_ready_scope",
  "caveat"
]);
if (!fullReferenceSamplesheet.some((row) => row.role === "tumor") || !fullReferenceSamplesheet.some((row) => row.role === "normal")) {
  errors.push("Full-reference samplesheet must include tumor and normal rows.");
}
for (const row of fullReferenceSamplesheet) {
  if (row.reference_id !== "ucsc_hg38_analysis_set_full") {
    errors.push(`Unexpected full-reference samplesheet reference ${row.reference_id}.`);
  }
  if (!row.interval_genes.includes("BRCA1") || !row.interval_genes.includes("BRCA2")) {
    errors.push(`Full-reference samplesheet must include BRCA1/BRCA2 intervals for ${row.run_accession}.`);
  }
  if (!row.caller_ready_scope.includes("full reference")) {
    errors.push(`Full-reference samplesheet must record caller-ready scope for ${row.run_accession}.`);
  }
  if (!row.caveat.includes("not full-depth WES/WGS")) {
    errors.push(`Full-reference samplesheet caveat must preserve full-depth boundary for ${row.run_accession}.`);
  }
}

const fullReferenceAssets = readJson<Record<string, unknown>>(pathFromRoot("results/full_reference_smoke/reference_assets_summary.json"));
if (fullReferenceAssets.status !== "built") {
  errors.push("Full-reference asset summary was not built.");
}
if (fullReferenceAssets.referenceCount !== 1 || fullReferenceAssets.sampleRows !== 2) {
  errors.push("Full-reference asset summary must include one reference and two sample rows.");
}
if (!String(fullReferenceAssets.boundary ?? "").includes("caller-readiness contracts")) {
  errors.push("Full-reference asset summary must preserve caller-readiness boundary.");
}

const fullReferenceSummaryRows = requireRows("results/full_reference_smoke/full_reference_alignment_summary.csv", 1);
requireColumns("results/full_reference_smoke/full_reference_alignment_summary.csv", fullReferenceSummaryRows, [
  "status",
  "reference_id",
  "assembly",
  "genome_build",
  "sample_rows",
  "tumor_rows",
  "normal_rows",
  "caller_smoke_status",
  "boundary"
]);
if (fullReferenceSummaryRows[0]?.status !== "passed" || fullReferenceSummaryRows[0]?.caller_smoke_status !== "passed") {
  errors.push("Full-reference alignment summary CSV did not pass.");
}
if (!fullReferenceSummaryRows[0]?.boundary.includes("not full-depth WES/WGS")) {
  errors.push("Full-reference alignment summary CSV must preserve full-depth boundary.");
}
const fullReferenceSummary = readJson<Record<string, unknown>>(pathFromRoot("results/full_reference_smoke/full_reference_alignment_summary.json"));
if (fullReferenceSummary.status !== "passed" || fullReferenceSummary.callerSmokeStatus !== "passed") {
  errors.push("Full-reference alignment summary JSON did not pass.");
}
if (fullReferenceSummary.sampleRows !== 2 || fullReferenceSummary.tumorRows !== 1 || fullReferenceSummary.normalRows !== 1) {
  errors.push("Full-reference alignment summary must include one tumor and one normal row.");
}
if (!String(fullReferenceSummary.boundary ?? "").includes("clinical somatic calling")) {
  errors.push("Full-reference alignment summary must preserve clinical-calling boundary.");
}

const fullReferenceBamRows = requireRows("results/full_reference_smoke/bam_validation_summary.csv", 2);
requireColumns("results/full_reference_smoke/bam_validation_summary.csv", fullReferenceBamRows, [
  "pair_id",
  "reference_id",
  "assembly",
  "genome_build",
  "role",
  "run_accession",
  "sample",
  "reference_sha256",
  "interval_bed_path",
  "interval_regions",
  "interval_genes",
  "output_bam",
  "output_bai",
  "bam_exists",
  "bai_exists",
  "quickcheck",
  "sort_order",
  "read_group_present",
  "reference_contig_count",
  "expected_brca_contigs_present",
  "total_alignments",
  "mapped_alignments",
  "mapped_fraction",
  "interval_alignments",
  "mapped_by_key_contig",
  "caller_ready_scope",
  "status",
  "caveat"
]);
for (const row of fullReferenceBamRows) {
  if (row.status !== "passed") {
    errors.push(`Full-reference BAM validation failed for ${row.run_accession}.`);
  }
  if (row.quickcheck !== "passed" || row.sort_order !== "coordinate" || row.read_group_present !== "yes") {
    errors.push(`Full-reference BAM contract failed for ${row.run_accession}.`);
  }
  if (row.bam_exists !== "yes" || row.bai_exists !== "yes") {
    errors.push(`Full-reference BAM/BAI paths were not present when validated for ${row.run_accession}.`);
  }
  if (row.expected_brca_contigs_present !== "yes" || Number(row.reference_contig_count) < 20) {
    errors.push(`Full-reference BAM header does not look like a full human reference for ${row.run_accession}.`);
  }
  if (Number(row.total_alignments) <= 0 || Number(row.mapped_alignments) <= 0) {
    errors.push(`Full-reference BAM has no mapped alignments for ${row.run_accession}.`);
  }
  if (!row.mapped_by_key_contig.includes("chr13:") || !row.mapped_by_key_contig.includes("chr17:")) {
    errors.push(`Full-reference mapped-by-contig summary is incomplete for ${row.run_accession}.`);
  }
  if (!row.caller_ready_scope.includes("full reference")) {
    errors.push(`Full-reference BAM row must preserve caller-ready scope for ${row.run_accession}.`);
  }
  if (!row.caveat.includes("not full-depth WES/WGS")) {
    errors.push(`Full-reference BAM caveat must preserve full-depth boundary for ${row.run_accession}.`);
  }
}
const fullReferenceBamSummary = readJson<Record<string, unknown>>(pathFromRoot("results/full_reference_smoke/bam_validation_summary.json"));
if (fullReferenceBamSummary.status !== "passed") {
  errors.push("Full-reference BAM validation JSON did not pass.");
}

const callerRows = requireRows("results/full_reference_smoke/caller_smoke_summary.csv", 1);
requireColumns("results/full_reference_smoke/caller_smoke_summary.csv", callerRows, [
  "reference_id",
  "caller",
  "caller_scope",
  "reference_path",
  "interval_bed_path",
  "input_bams",
  "output_vcf",
  "output_tbi",
  "vcf_exists",
  "tbi_exists",
  "sample_count",
  "samples",
  "records",
  "snps",
  "indels",
  "status",
  "caveat"
]);
const callerRow = callerRows[0] ?? {};
if (callerRow.status !== "passed" || callerRow.vcf_exists !== "yes" || callerRow.tbi_exists !== "yes") {
  errors.push("Full-reference caller smoke did not produce an indexed VCF.");
}
if (callerRow.caller !== "bcftools mpileup/call") {
  errors.push("Full-reference caller smoke must use bcftools mpileup/call.");
}
if (Number(callerRow.sample_count) !== 2 || !callerRow.samples.includes("HCC1395") || !callerRow.samples.includes("HCC1395BL")) {
  errors.push("Full-reference caller smoke VCF must contain tumor and normal sample columns.");
}
if (!callerRow.caveat.includes("not a tumor-normal somatic caller")) {
  errors.push("Full-reference caller smoke caveat must preserve non-somatic-caller boundary.");
}
const callerSummary = readJson<Record<string, unknown>>(pathFromRoot("results/full_reference_smoke/caller_smoke_summary.json"));
if (callerSummary.status !== "passed") {
  errors.push("Full-reference caller smoke JSON did not pass.");
}

const productionSamplesheet = requireRows("manifests/production_somatic_smoke_samplesheet.csv", 2);
requireColumns("manifests/production_somatic_smoke_samplesheet.csv", productionSamplesheet, [
  "pair_id",
  "patient",
  "sample",
  "role",
  "status",
  "run_accession",
  "source_fastq_1",
  "source_fastq_2",
  "read_pairs_per_end",
  "fastq_1",
  "fastq_2",
  "reference_id",
  "assembly",
  "genome_build",
  "reference_path",
  "reference_fai_path",
  "reference_dict_path",
  "reference_sha256",
  "brca_interval_bed_path",
  "brca_interval_regions",
  "brca_interval_genes",
  "known_sites_resource_path",
  "germline_resource_path",
  "panel_of_normals_path",
  "truth_snv_vcf_path",
  "truth_indel_vcf_path",
  "truth_high_confidence_bed_path",
  "gatk_jar_path",
  "java_path",
  "production_caller",
  "read_group_id",
  "read_group_sample",
  "output_bam",
  "output_bai",
  "caller_interval_strategy",
  "caveat"
]);
if (!productionSamplesheet.some((row) => row.role === "tumor") || !productionSamplesheet.some((row) => row.role === "normal")) {
  errors.push("Production somatic samplesheet must include tumor and normal rows.");
}
for (const row of productionSamplesheet) {
  if (row.reference_id !== "ucsc_hg38_analysis_set_full") {
    errors.push(`Production somatic samplesheet must use ucsc_hg38_analysis_set_full, not ${row.reference_id}.`);
  }
  if (row.production_caller !== "GATK Mutect2 + FilterMutectCalls") {
    errors.push(`Production somatic samplesheet has unexpected caller: ${row.production_caller}`);
  }
  if (Number(row.read_pairs_per_end) < 10000) {
    errors.push(`Production somatic read subset is too small for ${row.run_accession}: ${row.read_pairs_per_end}`);
  }
  if (!row.reference_dict_path.endsWith(".dict")) {
    errors.push(`Production somatic samplesheet is missing a GATK sequence dictionary path for ${row.run_accession}.`);
  }
  if (!row.truth_snv_vcf_path.includes("high-confidence_sSNV") || !row.truth_indel_vcf_path.includes("high-confidence_sINDEL")) {
    errors.push(`Production somatic samplesheet must reference SEQC2 high-confidence truth VCFs for ${row.run_accession}.`);
  }
  if (!row.known_sites_resource_path.includes("not_supplied") || !row.germline_resource_path.includes("not_supplied")) {
    errors.push(`Production somatic samplesheet must explicitly mark omitted production resources for ${row.run_accession}.`);
  }
  if (!row.caveat.includes("not full-depth sensitivity")) {
    errors.push(`Production somatic caveat must preserve full-depth boundary for ${row.run_accession}.`);
  }
}

const productionAssets = readJson<Record<string, unknown>>(pathFromRoot("results/production_somatic_smoke/asset_summary.json"));
const productionGatk = productionAssets.gatk as Record<string, unknown> | undefined;
const productionReference = productionAssets.reference as Record<string, unknown> | undefined;
const productionTruth = productionAssets.seqc2Truth as Record<string, unknown> | undefined;
if (productionAssets.status !== "ready") {
  errors.push("Production somatic asset summary is not ready.");
}
if (productionGatk?.version !== "4.6.2.0" || !String(productionGatk?.jarPath ?? "").includes("gatk-package-4.6.2.0-local.jar")) {
  errors.push("Production somatic GATK asset summary must pin GATK 4.6.2.0.");
}
if (!String(productionReference?.dictPath ?? "").endsWith(".dict") || productionReference?.referenceId !== "ucsc_hg38_analysis_set_full") {
  errors.push("Production somatic asset summary must include the full-reference GATK sequence dictionary.");
}
if (!String(productionTruth?.sourceDirectory ?? "").includes("ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest")) {
  errors.push("Production somatic asset summary must point to the SEQC2 HCC1395 truth-set source.");
}
if (!String(productionAssets.productionResourceCaveat ?? "").includes("Known-sites")) {
  errors.push("Production somatic asset summary must preserve omitted production-resource caveat.");
}

const productionFastqRows = requireRows("results/production_somatic_smoke/fastq_summary.csv", 2);
requireColumns("results/production_somatic_smoke/fastq_summary.csv", productionFastqRows, [
  "pair_id",
  "sample",
  "role",
  "run_accession",
  "reads_per_end",
  "paired_id_check",
  "local_fastq_1",
  "local_fastq_2",
  "caveat"
]);
for (const row of productionFastqRows) {
  if (row.paired_id_check !== "passed") {
    errors.push(`Production somatic FASTQ pairing failed for ${row.run_accession}.`);
  }
  if (Number(row.reads_per_end) < 10000) {
    errors.push(`Production somatic FASTQ read count too low for ${row.run_accession}: ${row.reads_per_end}`);
  }
  if (!row.caveat.includes("not full WES depth")) {
    errors.push(`Production somatic FASTQ caveat must preserve downsample boundary for ${row.run_accession}.`);
  }
}
const productionFastqSummary = readJson<Record<string, unknown>>(pathFromRoot("results/production_somatic_smoke/fastq_summary.json"));
if (productionFastqSummary.status !== "passed") {
  errors.push("Production somatic FASTQ summary JSON did not pass.");
}

const productionBamRows = requireRows("results/production_somatic_smoke/bam_validation_summary.csv", 2);
requireColumns("results/production_somatic_smoke/bam_validation_summary.csv", productionBamRows, [
  "pair_id",
  "reference_id",
  "assembly",
  "genome_build",
  "role",
  "run_accession",
  "sample",
  "reference_sha256",
  "output_bam",
  "output_bai",
  "bam_exists",
  "bai_exists",
  "quickcheck",
  "sort_order",
  "read_group_present",
  "reference_contig_count",
  "expected_brca_contigs_present",
  "total_alignments",
  "mapped_alignments",
  "mapped_fraction",
  "brca_interval_alignments",
  "mapped_standard_contigs",
  "status",
  "caveat"
]);
for (const row of productionBamRows) {
  if (row.status !== "passed") {
    errors.push(`Production somatic BAM validation failed for ${row.run_accession}.`);
  }
  if (row.quickcheck !== "passed" || row.sort_order !== "coordinate" || row.read_group_present !== "yes") {
    errors.push(`Production somatic BAM contract failed for ${row.run_accession}.`);
  }
  if (row.bam_exists !== "yes" || row.bai_exists !== "yes") {
    errors.push(`Production somatic BAM/BAI missing for ${row.run_accession}.`);
  }
  if (Number(row.total_alignments) <= 0 || Number(row.mapped_alignments) <= 0 || Number(row.mapped_standard_contigs) <= 0) {
    errors.push(`Production somatic BAM has insufficient mapped alignments for ${row.run_accession}.`);
  }
  if (!row.caveat.includes("Mutect2 plumbing")) {
    errors.push(`Production somatic BAM caveat must preserve caller-plumbing boundary for ${row.run_accession}.`);
  }
}
const productionBamSummary = readJson<Record<string, unknown>>(pathFromRoot("results/production_somatic_smoke/bam_validation_summary.json"));
if (productionBamSummary.status !== "passed") {
  errors.push("Production somatic BAM validation JSON did not pass.");
}

const mutectRows = requireRows("results/production_somatic_smoke/mutect2_smoke_summary.csv", 1);
requireColumns("results/production_somatic_smoke/mutect2_smoke_summary.csv", mutectRows, [
  "reference_id",
  "caller",
  "gatk_jar_path",
  "java_path",
  "input_tumor_bam",
  "input_normal_bam",
  "active_interval_bed_path",
  "active_interval_count",
  "active_interval_truth_overlap_count",
  "output_unfiltered_vcf",
  "output_filtered_vcf",
  "output_filtered_tbi",
  "filtered_vcf_exists",
  "filtered_tbi_exists",
  "sample_count",
  "samples",
  "filtered_records",
  "pass_records",
  "truth_snv_records_in_active_intervals",
  "truth_indel_records_in_active_intervals",
  "exact_pass_truth_matches",
  "comparison_status",
  "status",
  "caveat"
]);
const mutectRow = mutectRows[0] ?? {};
if (mutectRow.status !== "passed" || mutectRow.filtered_vcf_exists !== "yes" || mutectRow.filtered_tbi_exists !== "yes") {
  errors.push("Production somatic Mutect2 smoke did not produce an indexed filtered VCF.");
}
if (mutectRow.caller !== "GATK Mutect2 + FilterMutectCalls") {
  errors.push(`Production somatic Mutect2 summary has unexpected caller: ${mutectRow.caller}`);
}
if (Number(mutectRow.active_interval_count) <= 0) {
  errors.push("Production somatic Mutect2 smoke did not build active intervals.");
}
if (Number(mutectRow.sample_count) !== 2 || !mutectRow.samples.includes("HCC1395") || !mutectRow.samples.includes("HCC1395BL")) {
  errors.push("Production somatic Mutect2 VCF must contain tumor and normal sample columns.");
}
if (!mutectRow.comparison_status) {
  errors.push("Production somatic Mutect2 summary must include truth comparison status.");
}
if (!mutectRow.caveat.includes("not a full-depth sensitivity benchmark")) {
  errors.push("Production somatic Mutect2 caveat must preserve full-depth benchmark boundary.");
}
const mutectSummary = readJson<Record<string, unknown>>(pathFromRoot("results/production_somatic_smoke/mutect2_smoke_summary.json"));
if (mutectSummary.status !== "passed") {
  errors.push("Production somatic Mutect2 summary JSON did not pass.");
}

const productionSummaryRows = requireRows("results/production_somatic_smoke/production_somatic_summary.csv", 1);
requireColumns("results/production_somatic_smoke/production_somatic_summary.csv", productionSummaryRows, [
  "status",
  "phase",
  "caller",
  "reference_id",
  "assembly",
  "genome_build",
  "read_pairs_per_end",
  "sample_rows",
  "active_interval_count",
  "filtered_records",
  "pass_records",
  "truth_records_in_active_intervals",
  "exact_pass_truth_matches",
  "comparison_status",
  "boundary"
]);
const productionSummaryRow = productionSummaryRows[0] ?? {};
if (productionSummaryRow.status !== "passed" || productionSummaryRow.phase !== "2E") {
  errors.push("Production somatic summary CSV did not pass Phase 2E.");
}
if (Number(productionSummaryRow.read_pairs_per_end) < 10000 || Number(productionSummaryRow.active_interval_count) <= 0) {
  errors.push("Production somatic summary CSV does not show a larger downsample with active intervals.");
}
if (!productionSummaryRow.boundary.includes("not full-depth WES/WGS sensitivity")) {
  errors.push("Production somatic summary CSV must preserve WES/WGS boundary.");
}
const productionSummary = readJson<Record<string, unknown>>(pathFromRoot("results/production_somatic_smoke/production_somatic_summary.json"));
if (productionSummary.status !== "passed" || productionSummary.phase !== "2E") {
  errors.push("Production somatic summary JSON did not pass Phase 2E.");
}
if (Number(productionSummary.readPairsPerEnd) < 10000 || Number(productionSummary.activeIntervalCount) <= 0) {
  errors.push("Production somatic summary JSON does not show a larger downsample with active intervals.");
}
if (!String(productionSummary.boundary ?? "").includes("WES-limited small-variant evidence remains separate")) {
  errors.push("Production somatic summary JSON must separate WES evidence from WGS HRD signatures.");
}

const fullWesSamplesheet = requireRows("manifests/full_wes_benchmark_samplesheet.csv", 2);
requireColumns("manifests/full_wes_benchmark_samplesheet.csv", fullWesSamplesheet, [
  "pair_id",
  "patient",
  "sample",
  "role",
  "status",
  "run_accession",
  "source_read_pairs",
  "source_bases",
  "fastq_1",
  "fastq_2",
  "fastq_1_md5",
  "fastq_2_md5",
  "fastq_1_bytes",
  "fastq_2_bytes",
  "reference_id",
  "assembly",
  "genome_build",
  "reference_path",
  "reference_fai_path",
  "reference_dict_path",
  "gatk_jar_path",
  "java_path",
  "mutect2_germline_resource_path",
  "mutect2_germline_resource_source_url",
  "mutect2_panel_of_normals_path",
  "common_biallelic_resource_path",
  "common_biallelic_resource_index_path",
  "bqsr_known_sites_policy",
  "contamination_policy",
  "duplicate_marking_tool",
  "production_caller",
  "raw_bam",
  "dedup_bam",
  "dedup_bai",
  "duplicate_metrics_path",
  "caveat"
]);
if (!fullWesSamplesheet.some((row) => row.role === "tumor") || !fullWesSamplesheet.some((row) => row.role === "normal")) {
  errors.push("Full WES benchmark samplesheet must include tumor and normal rows.");
}
for (const row of fullWesSamplesheet) {
  if (row.reference_id !== "ucsc_hg38_analysis_set_full") {
    errors.push(`Full WES benchmark samplesheet must use ucsc_hg38_analysis_set_full, not ${row.reference_id}.`);
  }
  if (!row.mutect2_panel_of_normals_path.includes("1000g_pon.hg38.vcf.gz")) {
    errors.push(`Full WES benchmark samplesheet must include the Broad 1000g PoN for ${row.run_accession}.`);
  }
  if (!row.common_biallelic_resource_path.includes("common_biallelic")) {
    errors.push(`Full WES benchmark samplesheet must include the common-biallelic contamination resource for ${row.run_accession}.`);
  }
  if (!row.mutect2_germline_resource_source_url.includes("gatk-best-practices/somatic-hg38/af-only-gnomad.hg38.vcf.gz")) {
    errors.push(`Full WES benchmark must document the full production af-only gnomAD resource for ${row.run_accession}.`);
  }
  if (Number(row.fastq_1_bytes) < 1_000_000_000 || Number(row.fastq_2_bytes) < 1_000_000_000) {
    errors.push(`Full WES FASTQ byte counts look too small for ${row.run_accession}.`);
  }
  if (!row.caveat.includes("full SEQC2/HCC1395 WES FASTQs")) {
    errors.push(`Full WES benchmark caveat must preserve full-WES boundary for ${row.run_accession}.`);
  }
}

const fullWesAssets = readJson<Record<string, unknown>>(pathFromRoot("results/full_wes_benchmark/asset_summary.json"));
if (fullWesAssets.status !== "ready") {
  errors.push("Full WES asset summary is not ready.");
}
const fullWesFastqAssets = (fullWesAssets.fullWesFastqs as Record<string, unknown>[] | undefined) ?? [];
const fullWesResources = (fullWesAssets.resources as Record<string, unknown>[] | undefined) ?? [];
if (fullWesFastqAssets.length !== 4) {
  errors.push("Full WES asset summary must validate four FASTQ files.");
}
if (!fullWesResources.some((row) => String(row.kind) === "mutect2_panel_of_normals")) {
  errors.push("Full WES asset summary is missing the Mutect2 panel of normals.");
}
if (!fullWesResources.some((row) => String(row.kind) === "common_biallelic_gnomad_resource")) {
  errors.push("Full WES asset summary is missing the common-biallelic resource.");
}

const fullWesFastqRows = requireRows("results/full_wes_benchmark/full_wes_fastq_validation.csv", 4);
requireColumns("results/full_wes_benchmark/full_wes_fastq_validation.csv", fullWesFastqRows, [
  "pair_id",
  "sample",
  "role",
  "run_accession",
  "read",
  "fastq_path",
  "expected_md5",
  "actual_md5",
  "expected_bytes",
  "actual_bytes",
  "source_read_pairs",
  "status"
]);
for (const row of fullWesFastqRows) {
  if (row.status !== "passed" || row.expected_md5 !== row.actual_md5 || row.expected_bytes !== row.actual_bytes) {
    errors.push(`Full WES FASTQ validation failed for ${row.run_accession} read ${row.read}.`);
  }
}
const fullWesFastqSummary = readJson<Record<string, unknown>>(pathFromRoot("results/full_wes_benchmark/full_wes_fastq_validation.json"));
if (fullWesFastqSummary.status !== "passed") {
  errors.push("Full WES FASTQ validation JSON did not pass.");
}

const fullWesBamRows = requireRows("results/full_wes_benchmark/full_wes_bam_validation.csv", 2);
requireColumns("results/full_wes_benchmark/full_wes_bam_validation.csv", fullWesBamRows, [
  "pair_id",
  "reference_id",
  "role",
  "run_accession",
  "sample",
  "raw_bam",
  "dedup_bam",
  "dedup_bai",
  "dedup_bam_exists",
  "dedup_bai_exists",
  "quickcheck",
  "sort_order",
  "read_group_present",
  "reference_contig_count",
  "total_alignments",
  "mapped_alignments",
  "properly_paired_alignments",
  "duplicate_alignments",
  "duplicate_fraction",
  "brca_interval_alignments",
  "duplicate_metrics_path",
  "status",
  "caveat"
]);
for (const row of fullWesBamRows) {
  if (row.status !== "passed" || row.quickcheck !== "passed" || row.sort_order !== "coordinate" || row.read_group_present !== "yes") {
    errors.push(`Full WES BAM contract failed for ${row.run_accession}.`);
  }
  if (row.dedup_bam_exists !== "yes" || row.dedup_bai_exists !== "yes") {
    errors.push(`Full WES BAM/BAI missing for ${row.run_accession}.`);
  }
  if (Number(row.mapped_alignments) <= 0 || Number(row.brca_interval_alignments) <= 0) {
    errors.push(`Full WES BAM lacks mapped/BRCA alignments for ${row.run_accession}.`);
  }
  if (!row.caveat.includes("full SEQC2/HCC1395 WES FASTQs")) {
    errors.push(`Full WES BAM caveat must preserve full-WES boundary for ${row.run_accession}.`);
  }
}
const fullWesBamSummary = readJson<Record<string, unknown>>(pathFromRoot("results/full_wes_benchmark/full_wes_bam_validation.json"));
if (fullWesBamSummary.status !== "passed") {
  errors.push("Full WES BAM validation JSON did not pass.");
}

const fullWesTruthRows = requireRows("results/full_wes_benchmark/truth_overlap_benchmark_summary.csv", 1);
requireColumns("results/full_wes_benchmark/truth_overlap_benchmark_summary.csv", fullWesTruthRows, [
  "status",
  "phase",
  "caller",
  "reference_id",
  "pair_id",
  "tumor_sample",
  "normal_sample",
  "duplicate_marking_tool",
  "germline_resource",
  "germline_resource_source_url",
  "panel_of_normals",
  "common_biallelic_resource",
  "contamination_status",
  "contamination_table",
  "contamination_interval_bed_path",
  "benchmark_interval_bed_path",
  "benchmark_interval_count",
  "truth_variants_total",
  "truth_variants_depth_eligible",
  "filtered_vcf",
  "pass_records_in_benchmark_intervals",
  "exact_pass_truth_matches",
  "exact_pass_recall",
  "exact_pass_precision",
  "boundary"
]);
const fullWesTruthRow = fullWesTruthRows[0] ?? {};
if (fullWesTruthRow.status !== "passed" || fullWesTruthRow.phase !== "2F") {
  errors.push("Full WES truth-overlap benchmark did not pass Phase 2F.");
}
if (fullWesTruthRow.contamination_status !== "passed" || !fullWesTruthRow.contamination_table) {
  errors.push("Full WES benchmark must pass contamination estimation.");
}
if (Number(fullWesTruthRow.benchmark_interval_count) <= 0 || Number(fullWesTruthRow.truth_variants_depth_eligible) <= 0) {
  errors.push("Full WES benchmark did not produce covered truth intervals.");
}
if (!fullWesTruthRow.boundary.includes("not WGS HRD signature")) {
  errors.push("Full WES truth-overlap benchmark must preserve WGS HRD boundary.");
}

const fullWesSummaryRows = requireRows("results/full_wes_benchmark/full_wes_benchmark_summary.csv", 1);
requireColumns("results/full_wes_benchmark/full_wes_benchmark_summary.csv", fullWesSummaryRows, [
  "status",
  "phase",
  "caller",
  "reference_id",
  "full_wes_fastqs_validated",
  "bam_validation_status",
  "benchmark_interval_count",
  "truth_variants_depth_eligible",
  "pass_records_in_benchmark_intervals",
  "exact_pass_truth_matches",
  "exact_pass_recall",
  "exact_pass_precision",
  "contamination_status",
  "contamination_table",
  "ready_for_phase3",
  "boundary"
]);
const fullWesSummaryRow = fullWesSummaryRows[0] ?? {};
if (fullWesSummaryRow.status !== "passed" || fullWesSummaryRow.phase !== "2F" || fullWesSummaryRow.ready_for_phase3 !== "yes") {
  errors.push("Full WES benchmark summary CSV did not pass the Phase 2F ready-for-Phase-3 gate.");
}
if (Number(fullWesSummaryRow.full_wes_fastqs_validated) !== 4 || fullWesSummaryRow.bam_validation_status !== "passed") {
  errors.push("Full WES benchmark summary does not show four validated FASTQs and passed BAM validation.");
}
const fullWesSummary = readJson<Record<string, unknown>>(pathFromRoot("results/full_wes_benchmark/full_wes_benchmark_summary.json"));
if (fullWesSummary.status !== "passed" || fullWesSummary.phase !== "2F" || fullWesSummary.readyForPhase3 !== true) {
  errors.push("Full WES benchmark summary JSON did not pass the Phase 2F ready-for-Phase-3 gate.");
}
if (!String(fullWesSummary.boundary ?? "").includes("Phase 3 starts WGS HRD signature")) {
  errors.push("Full WES benchmark summary JSON must point to Phase 3 WGS HRD signature work.");
}

const cbioSummary = readJson<Record<string, unknown>>(pathFromRoot("data/processed/catalog/cbioportal_tcga_brca_summary.json"));
if ((cbioSummary.mutationCount as number) < 10) {
  errors.push("Fetched mutation count is unexpectedly low.");
}
if ((cbioSummary.cnaRecordCount as number) < 1000) {
  errors.push("Fetched CNA record count is unexpectedly low.");
}
if ((cbioSummary.expressionRecordCount as number) < 1000) {
  errors.push("Fetched RNA marker expression count is unexpectedly low.");
}

const packet = readText(pathFromRoot("results/reviewer_packet.md"));
for (const phrase of ["not yet ready to apply to Diana", "not a clinical HRD truth set", "WGS-specific signature evidence"]) {
  if (!packet.includes(phrase)) {
    errors.push(`Reviewer packet is missing boundary phrase: ${phrase}`);
  }
}

for (const warning of warnings) {
  console.warn(`warning: ${warning}`);
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`error: ${error}`);
  }
  process.exit(1);
}

console.log("Output verification passed.");
console.log(`Panel samples: ${panel.length}`);
console.log(`Strong HRD-like candidates: ${positiveStrong.length}`);
