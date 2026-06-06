import { createWriteStream, existsSync, statSync } from "node:fs";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { once } from "node:events";
import {
  ensureDir,
  parseCsv,
  pathFromRoot,
  readText,
  round,
  writeCsv,
  writeJson,
  writeText
} from "./lib";

type RawPanelRow = {
  pair_id: string;
  role: string;
  run: string;
  assay: string;
  phase: string;
  sample_name: string;
  fastq_1_url: string;
  fastq_2_url: string;
  fastq_1_bytes: string;
  fastq_2_bytes: string;
  library_layout: string;
  library_strategy: string;
};

type FastqStats = {
  run: string;
  read: "R1" | "R2";
  sourceUrl: string;
  outputPath: string;
  records: number;
  minLength: number;
  maxLength: number;
  meanLength: number;
  gcFraction: number;
  nFraction: number;
  qualityAsciiMin: number;
  qualityAsciiMax: number;
  firstReadId: string;
  lastReadId: string;
  ids: string[];
};

const smokePairId = "seqc2_hcc1395_wes_minimal_smoke";
const readLimit = Number(process.env.RAW_SMOKE_READS ?? "1000");
const smokeDir = pathFromRoot("data/raw/smoke/seqc2_hcc1395_wes_minimal_smoke");
const reportDir = pathFromRoot("results/raw_smoke");

function normalizeReadId(header: string) {
  return header
    .replace(/^@/, "")
    .split(/\s+/)[0]
    .replace(/\/[12]$/, "");
}

function validateRecord(lines: string[], source: string, recordNumber: number) {
  const [header, sequence, plus, quality] = lines;
  if (!header.startsWith("@")) {
    throw new Error(`${source} record ${recordNumber} does not start with @`);
  }
  if (!plus.startsWith("+")) {
    throw new Error(`${source} record ${recordNumber} plus line does not start with +`);
  }
  if (sequence.length !== quality.length) {
    throw new Error(`${source} record ${recordNumber} sequence/quality length mismatch`);
  }
  return { id: normalizeReadId(header), sequence, quality };
}

async function streamFastqSubset(run: string, read: "R1" | "R2", sourceUrl: string, outputPath: string): Promise<FastqStats> {
  ensureDir(outputPath.split("/").slice(0, -1).join("/"));

  const curl = spawn("curl", ["-fsSL", sourceUrl], { stdio: ["ignore", "pipe", "pipe"] });
  const gunzip = spawn("gunzip", ["-c"], { stdio: ["pipe", "pipe", "pipe"] });
  curl.stdout.pipe(gunzip.stdin);

  const output = createWriteStream(outputPath);
  const rl = createInterface({ input: gunzip.stdout });

  let current: string[] = [];
  let records = 0;
  let totalLength = 0;
  let minLength = Number.POSITIVE_INFINITY;
  let maxLength = 0;
  let gc = 0;
  let n = 0;
  let bases = 0;
  let qMin = Number.POSITIVE_INFINITY;
  let qMax = 0;
  let firstReadId = "";
  let lastReadId = "";
  const ids: string[] = [];

  let done = false;
  const finish = async () => {
    if (done) {
      return;
    }
    done = true;
    rl.close();
    output.end();
    curl.kill("SIGTERM");
    gunzip.kill("SIGTERM");
    await once(output, "finish");
  };

  for await (const line of rl) {
    output.write(`${line}\n`);
    current.push(line);
    if (current.length !== 4) {
      continue;
    }
    records += 1;
    const record = validateRecord(current, `${run} ${read}`, records);
    if (!firstReadId) {
      firstReadId = record.id;
    }
    lastReadId = record.id;
    ids.push(record.id);

    const length = record.sequence.length;
    totalLength += length;
    minLength = Math.min(minLength, length);
    maxLength = Math.max(maxLength, length);
    for (const base of record.sequence.toUpperCase()) {
      if (base === "G" || base === "C") {
        gc += 1;
      }
      if (base === "N") {
        n += 1;
      }
      bases += 1;
    }
    for (const char of record.quality) {
      const code = char.charCodeAt(0);
      qMin = Math.min(qMin, code);
      qMax = Math.max(qMax, code);
    }
    current = [];
    if (records >= readLimit) {
      await finish();
      break;
    }
  }

  await finish();

  if (records !== readLimit) {
    throw new Error(`${run} ${read} produced ${records} records; expected ${readLimit}`);
  }
  if (current.length !== 0) {
    throw new Error(`${run} ${read} ended mid-record`);
  }

  return {
    run,
    read,
    sourceUrl,
    outputPath,
    records,
    minLength,
    maxLength,
    meanLength: totalLength / records,
    gcFraction: gc / bases,
    nFraction: n / bases,
    qualityAsciiMin: qMin,
    qualityAsciiMax: qMax,
    firstReadId,
    lastReadId,
    ids
  };
}

function assertPaired(r1: FastqStats, r2: FastqStats) {
  if (r1.records !== r2.records) {
    throw new Error(`${r1.run} R1/R2 record-count mismatch`);
  }
  for (let index = 0; index < r1.ids.length; index += 1) {
    if (r1.ids[index] !== r2.ids[index]) {
      throw new Error(`${r1.run} R1/R2 read-id mismatch at ${index}: ${r1.ids[index]} vs ${r2.ids[index]}`);
    }
  }
}

function publicStats(stats: FastqStats) {
  const { ids: _ids, ...rest } = stats;
  return {
    ...rest,
    outputPath: rest.outputPath.replace(pathFromRoot(""), "").replace(/^\//, ""),
    meanLength: round(rest.meanLength, 2),
    gcFraction: round(rest.gcFraction, 4),
    nFraction: round(rest.nFraction, 6),
    fileSizeBytes: existsSync(stats.outputPath) ? statSync(stats.outputPath).size : ""
  };
}

async function main() {
  ensureDir(smokeDir);
  ensureDir(reportDir);

  const rawPanel = parseCsv(readText(pathFromRoot("manifests/raw_representative_panel.csv"))) as RawPanelRow[];
  const selected = rawPanel.filter((row) => row.pair_id === smokePairId).sort((a, b) => a.role.localeCompare(b.role));
  if (selected.length !== 2 || !selected.some((row) => row.role === "tumor") || !selected.some((row) => row.role === "normal")) {
    throw new Error(`Expected tumor and normal rows for ${smokePairId}`);
  }

  const stats: FastqStats[] = [];
  for (const row of selected) {
    const r1Path = `${smokeDir}/${row.run}_R1.fastq`;
    const r2Path = `${smokeDir}/${row.run}_R2.fastq`;
    const r1 = await streamFastqSubset(row.run, "R1", row.fastq_1_url, r1Path);
    const r2 = await streamFastqSubset(row.run, "R2", row.fastq_2_url, r2Path);
    assertPaired(r1, r2);
    stats.push(r1, r2);
  }

  const summaryRows = selected.map((row) => {
    const r1 = stats.find((item) => item.run === row.run && item.read === "R1") as FastqStats;
    const r2 = stats.find((item) => item.run === row.run && item.read === "R2") as FastqStats;
    return {
      pair_id: row.pair_id,
      sample_name: row.sample_name,
      role: row.role,
      run: row.run,
      assay: row.assay,
      library_strategy: row.library_strategy,
      library_layout: row.library_layout,
      reads_per_end: r1.records,
      r1_mean_length: round(r1.meanLength, 2),
      r2_mean_length: round(r2.meanLength, 2),
      r1_gc_fraction: round(r1.gcFraction, 4),
      r2_gc_fraction: round(r2.gcFraction, 4),
      r1_n_fraction: round(r1.nFraction, 6),
      r2_n_fraction: round(r2.nFraction, 6),
      first_read_id: r1.firstReadId,
      last_read_id: r1.lastReadId,
      paired_id_check: "passed",
      local_fastq_1: `${smokeDir}/${row.run}_R1.fastq`.replace(pathFromRoot(""), "").replace(/^\//, ""),
      local_fastq_2: `${smokeDir}/${row.run}_R2.fastq`.replace(pathFromRoot(""), "").replace(/^\//, "")
    };
  });

  await writeCsv(pathFromRoot("results/raw_smoke/fastq_smoke_summary.csv"), summaryRows);
  await writeJson(pathFromRoot("results/raw_smoke/fastq_smoke_summary.json"), {
    generatedAt: new Date().toISOString(),
    status: "passed",
    pairId: smokePairId,
    readLimit,
    source: "ENA direct paired FASTQ links for SEQC2/HCC1395 minimal WES pair",
    stats: stats.map(publicStats),
    limitations: [
      "This is a tiny first-read subset, not variant-calling depth.",
      "No alignment or somatic caller was run locally because aligner/BAM tools are not installed in the current environment.",
      "Use the remote samplesheet for full WES/WGS on a genomics-ready machine or container runtime."
    ]
  });

  await writeText(
    pathFromRoot("results/raw_smoke/README.md"),
    `# Raw FASTQ Smoke Test

Status: **passed**.

Smoke pair: \`${smokePairId}\`

Source: ENA direct paired FASTQ files derived from SEQC2/HCC1395 SRA run metadata.

Reads streamed per FASTQ end: \`${readLimit}\`

What this validates:

1. Public raw-data source metadata resolves to direct paired FASTQ URLs.
2. Tumor and normal sample rows can be represented in a Diana-ready tumor-normal samplesheet shape.
3. R1/R2 files are stream-readable, have valid FASTQ structure, and preserve matching read IDs.
4. Tiny local FASTQ subsets are present under \`data/raw/smoke/\` for immediate parser/QC development.

What this does not validate yet:

1. Full-depth WES or WGS download.
2. Alignment to GRCh37/GRCh38.
3. BAM/CRAM generation.
4. Somatic variant calling.
5. scarHRD/CHORD/HRDetect/SBS3 or SV signature calling.

Next raw-readiness step:

Install or containerize a genomics stack, then run the minimal WES pair through alignment and somatic-caller input validation.
`
  );

  console.log(`Raw FASTQ smoke passed for ${selected.length} samples with ${readLimit} read pairs each.`);
}

await main();

