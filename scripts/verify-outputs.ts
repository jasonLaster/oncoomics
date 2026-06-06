import { existsSync } from "node:fs";
import { parseCsv, pathFromRoot, readJson, readText } from "./lib";

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
  "results/raw_smoke/tooling_audit.md"
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
