import { createHash } from "node:crypto";
import { ensureDir, parseCsv, pathFromRoot, readText, writeCsv, writeJson, writeText } from "./lib";

type SmokeSampleRow = {
  pair_id: string;
  patient: string;
  sample: string;
  role: string;
  status: string;
  assay: string;
  library_strategy: string;
  library_layout: string;
  platform: string;
  model: string;
  run_accession: string;
  fastq_1: string;
  fastq_2: string;
};

type FastqRecord = {
  id: string;
  sequence: string;
  quality: string;
};

const smokePairId = "seqc2_hcc1395_wes_minimal_smoke";
const alignmentDir = "data/raw/smoke/seqc2_hcc1395_alignment_smoke";
const referenceId = "seqc2_hcc1395_readback_smoke_v1";
const referencePath = `${alignmentDir}/reference/${referenceId}.fa`;
const resultsDir = "results/alignment_smoke";
const gap = "N".repeat(100);

function normalizeReadId(header: string) {
  return header
    .replace(/^@/, "")
    .split(/\s+/)[0]
    .replace(/\/[12]$/, "");
}

function readFastq(path: string) {
  const lines = readText(pathFromRoot(path)).trimEnd().split(/\r?\n/);
  if (lines.length % 4 !== 0) {
    throw new Error(`${path} does not contain complete FASTQ records.`);
  }
  const records: FastqRecord[] = [];
  for (let index = 0; index < lines.length; index += 4) {
    const [header, sequence, plus, quality] = lines.slice(index, index + 4);
    if (!header.startsWith("@")) {
      throw new Error(`${path} record ${index / 4 + 1} does not start with @.`);
    }
    if (!plus.startsWith("+")) {
      throw new Error(`${path} record ${index / 4 + 1} plus line does not start with +.`);
    }
    if (sequence.length !== quality.length) {
      throw new Error(`${path} record ${index / 4 + 1} has sequence/quality length mismatch.`);
    }
    records.push({ id: normalizeReadId(header), sequence, quality });
  }
  return records;
}

function reverseComplement(sequence: string) {
  const complement: Record<string, string> = {
    A: "T",
    C: "G",
    G: "C",
    T: "A",
    N: "N",
    a: "t",
    c: "g",
    g: "c",
    t: "a",
    n: "n"
  };
  return sequence
    .split("")
    .reverse()
    .map((base) => complement[base] ?? "N")
    .join("")
    .toUpperCase();
}

function wrapFasta(sequence: string) {
  const lines: string[] = [];
  for (let index = 0; index < sequence.length; index += 80) {
    lines.push(sequence.slice(index, index + 80));
  }
  return lines.join("\n");
}

function sampleName(row: SmokeSampleRow) {
  return row.sample.replace(`_${row.run_accession}`, "");
}

async function main() {
  ensureDir(pathFromRoot(`${alignmentDir}/reference`));
  ensureDir(pathFromRoot(`${alignmentDir}/bam`));
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot("manifests"));

  const rows = (parseCsv(readText(pathFromRoot("manifests/raw_smoke_samplesheet.csv"))) as SmokeSampleRow[])
    .filter((row) => row.pair_id === smokePairId)
    .sort((a, b) => a.role.localeCompare(b.role));

  if (rows.length !== 2 || !rows.some((row) => row.role === "tumor") || !rows.some((row) => row.role === "normal")) {
    throw new Error(`Expected tumor and normal rows for ${smokePairId}.`);
  }

  const fastaParts: string[] = [];
  const sampleSummaries: Record<string, unknown>[] = [];
  let contigs = 0;
  let minContigLength = Number.POSITIVE_INFINITY;
  let maxContigLength = 0;

  for (const row of rows) {
    const r1 = readFastq(row.fastq_1);
    const r2 = readFastq(row.fastq_2);
    if (r1.length !== r2.length) {
      throw new Error(`${row.run_accession} R1/R2 record-count mismatch.`);
    }
    for (let index = 0; index < r1.length; index += 1) {
      if (r1[index].id !== r2[index].id) {
        throw new Error(`${row.run_accession} R1/R2 read-id mismatch at pair ${index + 1}.`);
      }
      const contigName = `${row.run_accession}_pair_${String(index + 1).padStart(6, "0")}`;
      const sequence = `${r1[index].sequence.toUpperCase()}${gap}${reverseComplement(r2[index].sequence)}`;
      contigs += 1;
      minContigLength = Math.min(minContigLength, sequence.length);
      maxContigLength = Math.max(maxContigLength, sequence.length);
      fastaParts.push(`>${contigName}\n${wrapFasta(sequence)}`);
    }
    sampleSummaries.push({
      run_accession: row.run_accession,
      role: row.role,
      sample: sampleName(row),
      read_pairs: r1.length,
      fastq_1: row.fastq_1,
      fastq_2: row.fastq_2
    });
  }

  const fastaText = `${fastaParts.join("\n")}\n`;
  await writeText(pathFromRoot(referencePath), fastaText);
  const referenceSha256 = createHash("sha256").update(fastaText).digest("hex");

  const alignmentRows = rows.map((row) => {
    const run = row.run_accession;
    const bam = `${alignmentDir}/bam/${run}.coordinate_sorted.bam`;
    return {
      pair_id: row.pair_id,
      patient: row.patient,
      sample: sampleName(row),
      role: row.role,
      status: row.status,
      assay: row.assay,
      library_strategy: row.library_strategy,
      library_layout: row.library_layout,
      platform: row.platform,
      model: row.model,
      run_accession: run,
      fastq_1: row.fastq_1,
      fastq_2: row.fastq_2,
      reference_id: referenceId,
      reference_path: referencePath,
      reference_sha256: referenceSha256,
      aligner: "bwa mem",
      aligner_threads: "2",
      read_group_id: run,
      read_group_sample: sampleName(row),
      read_group_library: `${row.assay}_${row.role}`,
      read_group_platform: "ILLUMINA",
      read_group_platform_unit: run,
      output_bam: bam,
      output_bai: `${bam}.bai`,
      source: "Phase 2A local HCC1395 FASTQ subset",
      caveat:
        "Read-backed synthetic smoke reference for local alignment and BAM contract validation only; not a human-reference or variant-calling result."
    };
  });

  await writeCsv(pathFromRoot("manifests/alignment_smoke_samplesheet.csv"), alignmentRows);
  await writeJson(pathFromRoot(`${resultsDir}/reference_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "built",
    referenceId,
    referencePath,
    referenceSha256,
    referenceType: "read-backed synthetic smoke reference",
    smokePairId,
    samples: sampleSummaries,
    contigs,
    minContigLength,
    maxContigLength,
    gapLength: gap.length,
    caveat:
      "This reference is intentionally built from the representative FASTQ subset to validate alignment mechanics locally. It is not GRCh37, GRCh38, or any biological reference."
  });

  console.log(`Built ${referenceId} with ${contigs} read-backed contigs and ${alignmentRows.length} alignment rows.`);
}

await main();
