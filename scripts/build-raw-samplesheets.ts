import { ensureDir, parseCsv, pathFromRoot, readText, writeCsv, writeJson } from "./lib";

type RawPanelRow = {
  pair_id: string;
  role: string;
  run: string;
  assay: string;
  phase: string;
  sample_name: string;
  fastq_1_url: string;
  fastq_2_url: string;
  library_layout: string;
  library_strategy: string;
  platform: string;
  model: string;
  size_mb: string;
};

const smokePairId = "seqc2_hcc1395_wes_minimal_smoke";
const smokeDir = "data/raw/smoke/seqc2_hcc1395_wes_minimal_smoke";

function nfCoreStatus(role: string) {
  return role === "tumor" ? 1 : 0;
}

async function main() {
  ensureDir(pathFromRoot("manifests"));
  ensureDir(pathFromRoot("results/raw_smoke"));

  const panel = parseCsv(readText(pathFromRoot("manifests/raw_representative_panel.csv"))) as RawPanelRow[];
  const rows = panel.map((row) => ({
    pair_id: row.pair_id,
    patient: "HCC1395_SEQC2",
    sample: `${row.sample_name}_${row.run}`,
    role: row.role,
    status: nfCoreStatus(row.role),
    assay: row.assay,
    library_strategy: row.library_strategy,
    library_layout: row.library_layout,
    platform: row.platform,
    model: row.model,
    run_accession: row.run,
    fastq_1: row.fastq_1_url,
    fastq_2: row.fastq_2_url,
    expected_size_mb: row.size_mb,
    source: "ENA direct FASTQ links derived from SEQC2/HCC1395 SRA metadata",
    caveat: "Remote full-run samplesheet; use smoke samplesheet or downsample before local full WES/WGS."
  }));

  const smokeRows = rows
    .filter((row) => row.pair_id === smokePairId)
    .map((row) => ({
      ...row,
      fastq_1: `${smokeDir}/${row.run_accession}_R1.fastq`,
      fastq_2: `${smokeDir}/${row.run_accession}_R2.fastq`,
      source: "Local first-read subset streamed from ENA direct FASTQ links",
      caveat: "Tiny raw-read smoke subset for pairing/QC/plumbing only; not variant-calling depth."
    }));

  await writeCsv(pathFromRoot("manifests/raw_samplesheet.csv"), rows);
  await writeCsv(pathFromRoot("manifests/raw_smoke_samplesheet.csv"), smokeRows);
  await writeJson(pathFromRoot("results/raw_smoke/samplesheet_summary.json"), {
    generatedAt: new Date().toISOString(),
    remoteRows: rows.length,
    smokeRows: smokeRows.length,
    smokePairId,
    nfCoreStatusConvention: "status 0 = normal, status 1 = tumor",
    boundaries: [
      "Remote samplesheet points to full public ENA FASTQ files.",
      "Smoke samplesheet points to local ignored first-read subsets created by scripts/run-raw-smoke.ts.",
      "These samplesheets are representative templates for Diana, not Diana data."
    ]
  });

  console.log(`Wrote ${rows.length} raw samplesheet rows and ${smokeRows.length} smoke rows.`);
}

await main();
