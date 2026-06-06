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
  "results/human_reference_smoke/reference_comparison_summary.json"
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
