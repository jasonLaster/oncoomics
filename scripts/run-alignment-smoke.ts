import { existsSync, statSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { ensureDir, parseCsv, pathFromRoot, readText, round, writeCsv, writeJson, writeText } from "./lib";

type AlignmentSampleRow = {
  pair_id: string;
  patient: string;
  sample: string;
  role: string;
  status: string;
  run_accession: string;
  fastq_1: string;
  fastq_2: string;
  reference_id: string;
  reference_path: string;
  reference_sha256: string;
  aligner: string;
  aligner_threads: string;
  read_group_id: string;
  read_group_sample: string;
  read_group_library: string;
  read_group_platform: string;
  read_group_platform_unit: string;
  output_bam: string;
  output_bai: string;
  caveat: string;
};

const resultsDir = "results/alignment_smoke";

function sh(value: string) {
  return `'${value.replaceAll("'", "'\"'\"'")}'`;
}

function run(command: string, logPath: string) {
  const result = spawnSync("bash", ["-lc", command], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 20
  });
  const log = [
    `$ ${command}`,
    "",
    "## stdout",
    result.stdout || "",
    "",
    "## stderr",
    result.stderr || "",
    "",
    `exit_status=${result.status}`
  ].join("\n");
  writeFileSync(pathFromRoot(logPath), log.endsWith("\n") ? log : `${log}\n`);
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command}. See ${logPath}.`);
  }
  return result.stdout;
}

function capture(command: string) {
  const result = spawnSync("bash", ["-lc", command], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 20
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command}\n${result.stderr}`);
  }
  return result.stdout.trim();
}

function commandPath(tool: string) {
  return capture(`command -v ${sh(tool)}`);
}

function toolVersion(tool: "bwa" | "samtools") {
  const output = spawnSync("bash", ["-lc", `${tool} 2>&1 | head -n 6`], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024
  });
  return `${output.stdout}${output.stderr}`.trim();
}

function readGroup(row: AlignmentSampleRow) {
  return [
    "@RG",
    `ID:${row.read_group_id}`,
    `SM:${row.read_group_sample}`,
    `LB:${row.read_group_library}`,
    `PL:${row.read_group_platform}`,
    `PU:${row.read_group_platform_unit}`
  ].join("\\t");
}

function ensureBwaIndex(referencePath: string) {
  const rootReference = pathFromRoot(referencePath);
  if (existsSync(`${rootReference}.bwt`)) {
    return false;
  }
  run(`bwa index ${sh(referencePath)}`, `${resultsDir}/logs/bwa_index.log`);
  return true;
}

function fileSha256(relativePath: string) {
  return createHash("sha256").update(readText(pathFromRoot(relativePath))).digest("hex");
}

function parseHeader(header: string, row: AlignmentSampleRow) {
  const lines = header.split(/\r?\n/);
  const hd = lines.find((line) => line.startsWith("@HD")) ?? "";
  const sortOrder = hd.match(/\bSO:([^\t]+)/)?.[1] ?? "";
  const rgLines = lines.filter((line) => line.startsWith("@RG"));
  const sqLines = lines.filter((line) => line.startsWith("@SQ"));
  const readGroupPresent = rgLines.some(
    (line) => line.includes(`ID:${row.read_group_id}`) && line.includes(`SM:${row.read_group_sample}`)
  );
  return { sortOrder, readGroupPresent, readGroupCount: rgLines.length, referenceContigs: sqLines.length };
}

function count(command: string) {
  return Number(capture(command));
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));

  const bwaPath = commandPath("bwa");
  const samtoolsPath = commandPath("samtools");
  const rows = parseCsv(readText(pathFromRoot("manifests/alignment_smoke_samplesheet.csv"))) as AlignmentSampleRow[];
  if (rows.length !== 2 || !rows.some((row) => row.role === "tumor") || !rows.some((row) => row.role === "normal")) {
    throw new Error("Expected tumor and normal rows in manifests/alignment_smoke_samplesheet.csv.");
  }

  const referencePaths = new Set(rows.map((row) => row.reference_path));
  if (referencePaths.size !== 1) {
    throw new Error("Alignment smoke samplesheet must use exactly one reference.");
  }
  const referencePath = rows[0].reference_path;
  const observedReferenceSha256 = fileSha256(referencePath);
  for (const row of rows) {
    if (row.reference_sha256 !== observedReferenceSha256) {
      throw new Error(`${row.run_accession} expected reference sha256 ${row.reference_sha256}; observed ${observedReferenceSha256}.`);
    }
  }

  const indexedReference = ensureBwaIndex(referencePath);
  const validationRows: Record<string, unknown>[] = [];

  for (const row of rows) {
    ensureDir(pathFromRoot(row.output_bam.split("/").slice(0, -1).join("/")));
    const command = `set -o pipefail; ${[
      `bwa mem -t ${Number(row.aligner_threads) || 2} -R ${sh(readGroup(row))} ${sh(row.reference_path)} ${sh(row.fastq_1)} ${sh(row.fastq_2)}`,
      `samtools sort -@ ${Number(row.aligner_threads) || 2} -o ${sh(row.output_bam)} -`
    ].join(" | ")}`;
    run(command, `${resultsDir}/logs/${row.run_accession}.align.log`);
    run(`samtools index ${sh(row.output_bam)}`, `${resultsDir}/logs/${row.run_accession}.index.log`);
    run(`samtools flagstat ${sh(row.output_bam)}`, `${resultsDir}/logs/${row.run_accession}.flagstat.txt`);
    run(`samtools stats ${sh(row.output_bam)}`, `${resultsDir}/logs/${row.run_accession}.stats.txt`);

    const quickcheck = spawnSync("samtools", ["quickcheck", "-v", pathFromRoot(row.output_bam)], {
      encoding: "utf8",
      maxBuffer: 1024 * 1024
    });
    const header = capture(`samtools view -H ${sh(row.output_bam)}`);
    const headerState = parseHeader(header, row);
    const totalAlignments = count(`samtools view -c ${sh(row.output_bam)}`);
    const mappedAlignments = count(`samtools view -c -F 4 ${sh(row.output_bam)}`);
    const properlyPairedAlignments = count(`samtools view -c -f 2 ${sh(row.output_bam)}`);
    const idxstats = capture(`samtools idxstats ${sh(row.output_bam)}`);
    const idxstatsMapped = idxstats
      .split(/\r?\n/)
      .filter(Boolean)
      .reduce((sum, line) => sum + Number(line.split("\t")[2] ?? 0), 0);
    const bamExists = existsSync(pathFromRoot(row.output_bam));
    const baiExists = existsSync(pathFromRoot(row.output_bai));
    const status =
      quickcheck.status === 0 &&
      bamExists &&
      baiExists &&
      headerState.sortOrder === "coordinate" &&
      headerState.readGroupPresent &&
      totalAlignments > 0 &&
      mappedAlignments > 0
        ? "passed"
        : "failed";

    validationRows.push({
      pair_id: row.pair_id,
      role: row.role,
      run_accession: row.run_accession,
      sample: row.sample,
      reference_id: row.reference_id,
      reference_sha256: row.reference_sha256,
      output_bam: row.output_bam,
      output_bai: row.output_bai,
      bam_exists: bamExists ? "yes" : "no",
      bai_exists: baiExists ? "yes" : "no",
      quickcheck: quickcheck.status === 0 ? "passed" : "failed",
      sort_order: headerState.sortOrder,
      read_group_present: headerState.readGroupPresent ? "yes" : "no",
      read_group_count: headerState.readGroupCount,
      reference_contigs: headerState.referenceContigs,
      total_alignments: totalAlignments,
      mapped_alignments: mappedAlignments,
      mapped_fraction: round(mappedAlignments / totalAlignments, 4),
      properly_paired_alignments: properlyPairedAlignments,
      properly_paired_fraction: round(properlyPairedAlignments / totalAlignments, 4),
      idxstats_mapped_alignments: idxstatsMapped,
      bam_size_bytes: bamExists ? statSync(pathFromRoot(row.output_bam)).size : "",
      status,
      caveat: row.caveat
    });
  }

  const status = validationRows.every((row) => row.status === "passed") ? "passed" : "failed";
  await writeCsv(pathFromRoot(`${resultsDir}/bam_validation_summary.csv`), validationRows);
  await writeJson(pathFromRoot(`${resultsDir}/bam_validation_summary.json`), {
    generatedAt: new Date().toISOString(),
    status,
    rows: validationRows
  });
  await writeJson(pathFromRoot(`${resultsDir}/tool_versions.json`), {
    generatedAt: new Date().toISOString(),
    bwa: { path: bwaPath, version: toolVersion("bwa") },
    samtools: { path: samtoolsPath, version: toolVersion("samtools") }
  });
  await writeJson(pathFromRoot(`${resultsDir}/alignment_smoke_summary.json`), {
    generatedAt: new Date().toISOString(),
    status,
    pairId: rows[0].pair_id,
    referenceId: rows[0].reference_id,
    referencePath,
    referenceSha256: observedReferenceSha256,
    indexedReference,
    aligner: "bwa mem",
    bamTool: "samtools",
    samples: validationRows.length,
    tumorRows: validationRows.filter((row) => row.role === "tumor").length,
    normalRows: validationRows.filter((row) => row.role === "normal").length,
    boundary:
      "Phase 2B local BAM smoke validates FASTQ-to-coordinate-sorted-BAM mechanics and caller-input file contracts against a read-backed synthetic reference. It does not validate GRCh37/GRCh38 alignment, coverage, somatic calls, or HRD signatures."
  });
  await writeCsv(pathFromRoot(`${resultsDir}/alignment_smoke_summary.csv`), [
    {
      status,
      pair_id: rows[0].pair_id,
      reference_id: rows[0].reference_id,
      aligner: "bwa mem",
      bam_tool: "samtools",
      samples: validationRows.length,
      tumor_rows: validationRows.filter((row) => row.role === "tumor").length,
      normal_rows: validationRows.filter((row) => row.role === "normal").length,
      boundary:
        "Local file-contract smoke only; not human-reference alignment, somatic calling, or HRD signature evidence."
    }
  ]);
  await writeText(
    pathFromRoot(`${resultsDir}/README.md`),
    `# Alignment Smoke Test

Status: **${status}**.

Smoke pair: \`${rows[0].pair_id}\`

Input: Phase 2A local SEQC2/HCC1395 FASTQ subset.

Reference: \`${rows[0].reference_id}\`

Tools:

1. \`bwa mem\`
2. \`samtools sort/index/quickcheck/stats\`

What this validates:

1. Tumor and normal FASTQs can be aligned locally.
2. BAMs are coordinate-sorted and indexed.
3. Read groups are present with sample identifiers.
4. Tumor and normal BAMs use the same reference dictionary.
5. BAM files pass \`samtools quickcheck\` and expose mapped reads.

What this does not validate yet:

1. GRCh37/GRCh38 or hs37d5 alignment.
2. Full WES/WGS depth or capture interval performance.
3. Somatic SNV/indel calling.
4. CNV/SV calling.
5. scarHRD/CHORD/HRDetect/SBS3 evidence.

Boundary: this is a local file-contract smoke against a read-backed synthetic reference, not a biological result.
`
  );

  if (status !== "passed") {
    throw new Error("Alignment smoke failed. See results/alignment_smoke/.");
  }

  console.log(`Alignment smoke ${status} for ${validationRows.length} BAMs.`);
}

await main();
