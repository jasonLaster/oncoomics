import { createWriteStream, existsSync, statSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { createInterface } from "node:readline";
import { once } from "node:events";
import { ensureDir, parseCsv, pathFromRoot, readJson, readText, round, writeCsv, writeJson, writeText } from "./lib";

type ProductionSampleRow = {
  pair_id: string;
  sample: string;
  role: string;
  run_accession: string;
  source_fastq_1: string;
  source_fastq_2: string;
  read_pairs_per_end: string;
  fastq_1: string;
  fastq_2: string;
  reference_id: string;
  assembly: string;
  genome_build: string;
  reference_path: string;
  reference_fai_path: string;
  reference_dict_path: string;
  reference_sha256: string;
  brca_interval_bed_path: string;
  brca_interval_regions: string;
  brca_interval_genes: string;
  truth_snv_vcf_path: string;
  truth_indel_vcf_path: string;
  truth_high_confidence_bed_path: string;
  gatk_jar_path: string;
  java_path: string;
  production_caller: string;
  read_group_id: string;
  read_group_sample: string;
  read_group_library: string;
  read_group_platform: string;
  read_group_platform_unit: string;
  output_bam: string;
  output_bai: string;
  caller_interval_strategy: string;
  caveat: string;
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

type Interval = {
  contig: string;
  start: number;
  end: number;
  truthOverlap: boolean;
};

const resultsDir = "results/production_somatic_smoke";
const maxActiveIntervals = Number(process.env.PRODUCTION_SOMATIC_MAX_INTERVALS ?? "500");
const activeWindowPadding = Number(process.env.PRODUCTION_SOMATIC_ACTIVE_PADDING ?? "125");
const threads = Number(process.env.PRODUCTION_SOMATIC_THREADS ?? "4");

function sh(value: string) {
  return `'${value.replaceAll("'", "'\"'\"'")}'`;
}

function run(command: string, logPath: string) {
  const result = spawnSync("bash", ["-lc", command], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 100
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
  return result.stdout.trim();
}

function capture(command: string) {
  const result = spawnSync("bash", ["-lc", command], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 100
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command}\n${result.stderr}`);
  }
  return result.stdout.trim();
}

function captureAllowEmpty(command: string) {
  const result = spawnSync("bash", ["-lc", command], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 100
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command}\n${result.stderr}`);
  }
  return result.stdout.trim();
}

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

async function streamFastqSubset(
  runAccession: string,
  read: "R1" | "R2",
  sourceUrl: string,
  outputPath: string,
  readLimit: number
): Promise<FastqStats> {
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
    const record = validateRecord(current, `${runAccession} ${read}`, records);
    firstReadId ||= record.id;
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
    throw new Error(`${runAccession} ${read} produced ${records} records; expected ${readLimit}`);
  }
  if (current.length !== 0) {
    throw new Error(`${runAccession} ${read} ended mid-record`);
  }

  return {
    run: runAccession,
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

function readGroup(row: ProductionSampleRow) {
  return [
    "@RG",
    `ID:${row.read_group_id}`,
    `SM:${row.read_group_sample}`,
    `LB:${row.read_group_library}`,
    `PL:${row.read_group_platform}`,
    `PU:${row.read_group_platform_unit}`
  ].join("\\t");
}

function parseHeader(header: string, row: ProductionSampleRow) {
  const lines = header.split(/\r?\n/);
  const hd = lines.find((line) => line.startsWith("@HD")) ?? "";
  const sortOrder = hd.match(/\bSO:([^\t]+)/)?.[1] ?? "";
  const rgLines = lines.filter((line) => line.startsWith("@RG"));
  const sqLines = lines.filter((line) => line.startsWith("@SQ"));
  const contigs = sqLines.map((line) => line.match(/\bSN:([^\t]+)/)?.[1] ?? "").filter(Boolean);
  const readGroupPresent = rgLines.some(
    (line) => line.includes(`ID:${row.read_group_id}`) && line.includes(`SM:${row.read_group_sample}`)
  );
  return { sortOrder, readGroupPresent, readGroupCount: rgLines.length, contigs };
}

function parseIdxstats(text: string) {
  return text.split(/\r?\n/).filter(Boolean).map((line) => {
    const [contig, length, mapped, unmapped] = line.split("\t");
    return { contig, length: Number(length), mapped: Number(mapped), unmapped: Number(unmapped) };
  });
}

function count(command: string) {
  const text = capture(command);
  return Number(text || "0");
}

function toolVersion(tool: string) {
  const output = spawnSync("bash", ["-lc", `${tool} 2>&1 | head -n 8`], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024
  });
  return `${output.stdout}${output.stderr}`.trim();
}

function standardContig(contig: string) {
  return /^chr([1-9]|1[0-9]|2[0-2]|X|Y)$/.test(contig);
}

function readReferenceOrder(faiPath: string) {
  const order = new Map<string, number>();
  readText(pathFromRoot(faiPath))
    .split(/\r?\n/)
    .filter(Boolean)
    .forEach((line, index) => {
      order.set(line.split("\t")[0], index);
    });
  return order;
}

function loadTruthPositions(vcfPaths: string[]) {
  const positions = new Map<string, number[]>();
  for (const vcfPath of vcfPaths) {
    const rows = captureAllowEmpty(`gunzip -c ${sh(vcfPath)} | awk '!/^#/ {print $1 "\\t" $2}'`);
    for (const line of rows.split(/\r?\n/).filter(Boolean)) {
      const [contig, positionText] = line.split("\t");
      const position = Number(positionText);
      if (!standardContig(contig) || !Number.isFinite(position)) {
        continue;
      }
      const values = positions.get(contig) ?? [];
      values.push(position);
      positions.set(contig, values);
    }
  }
  for (const values of positions.values()) {
    values.sort((a, b) => a - b);
  }
  return positions;
}

function hasTruthOverlap(positions: Map<string, number[]>, contig: string, startZeroBased: number, endZeroBased: number) {
  const values = positions.get(contig) ?? [];
  if (values.length === 0) {
    return false;
  }
  const startOneBased = startZeroBased + 1;
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (values[middle] < startOneBased) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }
  return (values[low] ?? Number.POSITIVE_INFINITY) <= endZeroBased;
}

function mergeIntervals(intervals: Interval[], referenceOrder: Map<string, number>) {
  const sorted = [...intervals].sort((a, b) => {
    const contigDelta = (referenceOrder.get(a.contig) ?? 9999) - (referenceOrder.get(b.contig) ?? 9999);
    return contigDelta || a.start - b.start || a.end - b.end;
  });
  const merged: Interval[] = [];
  for (const interval of sorted) {
    const last = merged.at(-1);
    if (!last || last.contig !== interval.contig || interval.start > last.end + 50) {
      merged.push({ ...interval });
      continue;
    }
    last.end = Math.max(last.end, interval.end);
    last.truthOverlap ||= interval.truthOverlap;
  }
  return merged;
}

function pickEvenly<T>(items: T[], limit: number) {
  if (items.length <= limit) {
    return items;
  }
  if (limit <= 0) {
    return [];
  }
  const picked: T[] = [];
  const used = new Set<number>();
  for (let index = 0; index < limit; index += 1) {
    const sourceIndex = Math.round((index * (items.length - 1)) / Math.max(limit - 1, 1));
    if (!used.has(sourceIndex)) {
      picked.push(items[sourceIndex]);
      used.add(sourceIndex);
    }
  }
  return picked;
}

function buildActiveIntervals(
  rows: ProductionSampleRow[],
  truthPositions: Map<string, number[]>,
  referenceOrder: Map<string, number>,
  outputBedPath: string
) {
  const intervals: Interval[] = [];
  for (const row of rows) {
    const mappedRows = captureAllowEmpty(`samtools view -F 4 ${sh(row.output_bam)} | awk '{print $3 "\\t" $4 "\\t" length($10)}'`);
    for (const line of mappedRows.split(/\r?\n/).filter(Boolean)) {
      const [contig, startText, lengthText] = line.split("\t");
      const startOneBased = Number(startText);
      const readLength = Number(lengthText);
      if (!standardContig(contig) || !Number.isFinite(startOneBased) || !Number.isFinite(readLength) || readLength <= 0) {
        continue;
      }
      const start = Math.max(0, startOneBased - 1 - activeWindowPadding);
      const end = startOneBased - 1 + readLength + activeWindowPadding;
      intervals.push({
        contig,
        start,
        end,
        truthOverlap: hasTruthOverlap(truthPositions, contig, start, end)
      });
    }
  }

  const merged = mergeIntervals(intervals, referenceOrder);
  const truthOverlaps = merged.filter((interval) => interval.truthOverlap);
  const nonTruth = merged.filter((interval) => !interval.truthOverlap);
  const selected = mergeIntervals(
    [
      ...truthOverlaps.slice(0, Math.floor(maxActiveIntervals / 2)),
      ...pickEvenly(nonTruth, maxActiveIntervals - Math.min(truthOverlaps.length, Math.floor(maxActiveIntervals / 2)))
    ],
    referenceOrder
  ).slice(0, maxActiveIntervals);

  if (selected.length === 0) {
    throw new Error("No active intervals could be derived from mapped reads.");
  }

  ensureDir(pathFromRoot(outputBedPath.split("/").slice(0, -1).join("/")));
  writeFileSync(pathFromRoot(outputBedPath), `${selected.map((interval) => `${interval.contig}\t${interval.start}\t${interval.end}`).join("\n")}\n`);

  return {
    intervals,
    merged,
    selected,
    truthOverlapCount: selected.filter((interval) => interval.truthOverlap).length
  };
}

function ensureVcfIndex(vcfPath: string, label: string) {
  if (existsSync(pathFromRoot(`${vcfPath}.tbi`))) {
    return "existing";
  }
  const first = spawnSync("bash", ["-lc", `bcftools index -t -f ${sh(vcfPath)}`], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 20
  });
  if (first.status === 0) {
    return "created";
  }
  const tmpPath = `${vcfPath}.bgzip.tmp.vcf.gz`;
  run(
    `bcftools view -Oz -o ${sh(tmpPath)} ${sh(vcfPath)} && mv ${sh(tmpPath)} ${sh(vcfPath)} && bcftools index -t -f ${sh(vcfPath)}`,
    `${resultsDir}/logs/${label}.bgzip_and_index.log`
  );
  return "rebuilt";
}

function parseVcfSampleNames(vcfPath: string) {
  const header = capture(`bcftools view -h ${sh(vcfPath)}`);
  const sampleLine = header.split(/\r?\n/).find((line) => line.startsWith("#CHROM")) ?? "";
  return sampleLine.split("\t").slice(9);
}

function variantKeys(vcfPath: string, regionBedPath?: string) {
  const regionPart = regionBedPath ? `-R ${sh(regionBedPath)}` : "";
  const rows = captureAllowEmpty(`bcftools view ${regionPart} -H ${sh(vcfPath)}`);
  const keys = new Set<string>();
  const passKeys = new Set<string>();
  let snvCount = 0;
  let indelCount = 0;
  let passCount = 0;
  for (const line of rows.split(/\r?\n/).filter(Boolean)) {
    const [contig, position, , ref, altText, , filter] = line.split("\t");
    for (const alt of altText.split(",")) {
      const key = `${contig}:${position}:${ref}:${alt}`;
      keys.add(key);
      if (ref.length === 1 && alt.length === 1) {
        snvCount += 1;
      } else {
        indelCount += 1;
      }
      if (filter === "PASS") {
        passKeys.add(key);
        passCount += 1;
      }
    }
  }
  return { keys, passKeys, totalCount: keys.size, passCount, snvCount, indelCount };
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));

  const assetSummary = readJson<Record<string, unknown>>(pathFromRoot(`${resultsDir}/asset_summary.json`));
  if (assetSummary.status !== "ready") {
    throw new Error("Production somatic asset summary is not ready. Run fetch:production-somatic first.");
  }

  const rows = parseCsv(readText(pathFromRoot("manifests/production_somatic_smoke_samplesheet.csv"))) as ProductionSampleRow[];
  if (rows.length !== 2 || !rows.some((row) => row.role === "tumor") || !rows.some((row) => row.role === "normal")) {
    throw new Error("Expected tumor and normal rows in manifests/production_somatic_smoke_samplesheet.csv.");
  }
  const tumor = rows.find((row) => row.role === "tumor") as ProductionSampleRow;
  const normal = rows.find((row) => row.role === "normal") as ProductionSampleRow;
  const referenceId = tumor.reference_id;
  const readLimit = Number(tumor.read_pairs_per_end);
  const vcfDir = `data/raw/smoke/seqc2_hcc1395_production_somatic_smoke/${referenceId}/vcf`;
  const intervalDir = `data/raw/smoke/seqc2_hcc1395_production_somatic_smoke/${referenceId}/intervals`;
  const activeIntervalsPath = `${intervalDir}/mutect2_active_intervals.bed`;
  const unfilteredVcf = `${vcfDir}/hcc1395.mutect2.unfiltered.vcf.gz`;
  const filteredVcf = `${vcfDir}/hcc1395.mutect2.filtered.vcf.gz`;
  const f1r2Path = `${vcfDir}/hcc1395.mutect2.f1r2.tar.gz`;

  for (const row of rows) {
    for (const path of [row.reference_path, row.reference_fai_path, row.reference_dict_path, row.gatk_jar_path]) {
      if (!existsSync(pathFromRoot(path))) {
        throw new Error(`Required production somatic asset is missing: ${path}`);
      }
    }
  }

  const fastqStats: FastqStats[] = [];
  for (const row of rows) {
    const r1 = await streamFastqSubset(row.run_accession, "R1", row.source_fastq_1, pathFromRoot(row.fastq_1), readLimit);
    const r2 = await streamFastqSubset(row.run_accession, "R2", row.source_fastq_2, pathFromRoot(row.fastq_2), readLimit);
    assertPaired(r1, r2);
    fastqStats.push(r1, r2);
  }

  const fastqRows = rows.map((row) => {
    const r1 = fastqStats.find((stat) => stat.run === row.run_accession && stat.read === "R1") as FastqStats;
    const r2 = fastqStats.find((stat) => stat.run === row.run_accession && stat.read === "R2") as FastqStats;
    return {
      pair_id: row.pair_id,
      sample: row.sample,
      role: row.role,
      run_accession: row.run_accession,
      reads_per_end: r1.records,
      r1_mean_length: round(r1.meanLength, 2),
      r2_mean_length: round(r2.meanLength, 2),
      r1_gc_fraction: round(r1.gcFraction, 4),
      r2_gc_fraction: round(r2.gcFraction, 4),
      first_read_id: r1.firstReadId,
      last_read_id: r1.lastReadId,
      paired_id_check: "passed",
      local_fastq_1: row.fastq_1,
      local_fastq_2: row.fastq_2,
      caveat: "Downsampled FASTQ subset for Phase 2E production somatic smoke; not full WES depth."
    };
  });
  await writeCsv(pathFromRoot(`${resultsDir}/fastq_summary.csv`), fastqRows);
  await writeJson(pathFromRoot(`${resultsDir}/fastq_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "passed",
    readPairsPerEnd: readLimit,
    rows: fastqRows
  });

  if (!existsSync(pathFromRoot(`${tumor.reference_path}.bwt`))) {
    run(`bwa index ${sh(tumor.reference_path)}`, `${resultsDir}/logs/${referenceId}.bwa_index.log`);
  }

  const bamRows: Record<string, unknown>[] = [];
  for (const row of rows) {
    ensureDir(pathFromRoot(row.output_bam.split("/").slice(0, -1).join("/")));
    const alignCommand = `set -o pipefail; ${[
      `bwa mem -t ${threads} -R ${sh(readGroup(row))} ${sh(row.reference_path)} ${sh(row.fastq_1)} ${sh(row.fastq_2)}`,
      `samtools sort -@ ${threads} -o ${sh(row.output_bam)} -`
    ].join(" | ")}`;
    run(alignCommand, `${resultsDir}/logs/${referenceId}.${row.run_accession}.align.log`);
    run(`samtools index ${sh(row.output_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.index.log`);
    run(`samtools flagstat ${sh(row.output_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.flagstat.txt`);
    run(`samtools stats ${sh(row.output_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.stats.txt`);

    const quickcheck = spawnSync("samtools", ["quickcheck", "-v", pathFromRoot(row.output_bam)], {
      encoding: "utf8",
      maxBuffer: 1024 * 1024
    });
    const headerState = parseHeader(capture(`samtools view -H ${sh(row.output_bam)}`), row);
    const idxstatsRows = parseIdxstats(capture(`samtools idxstats ${sh(row.output_bam)}`));
    const totalAlignments = count(`samtools view -c ${sh(row.output_bam)}`);
    const mappedAlignments = count(`samtools view -c -F 4 ${sh(row.output_bam)}`);
    const properlyPairedAlignments = count(`samtools view -c -f 2 ${sh(row.output_bam)}`);
    const intervalAlignments = count(`samtools view -c -L ${sh(row.brca_interval_bed_path)} ${sh(row.output_bam)}`);
    const bamExists = existsSync(pathFromRoot(row.output_bam));
    const baiExists = existsSync(pathFromRoot(row.output_bai));
    const status =
      quickcheck.status === 0 &&
      bamExists &&
      baiExists &&
      headerState.sortOrder === "coordinate" &&
      headerState.readGroupPresent &&
      headerState.contigs.includes("chr13") &&
      headerState.contigs.includes("chr17") &&
      totalAlignments > 0 &&
      mappedAlignments > 0
        ? "passed"
        : "failed";
    bamRows.push({
      pair_id: row.pair_id,
      reference_id: row.reference_id,
      assembly: row.assembly,
      genome_build: row.genome_build,
      role: row.role,
      run_accession: row.run_accession,
      sample: row.sample,
      reference_sha256: row.reference_sha256,
      output_bam: row.output_bam,
      output_bai: row.output_bai,
      bam_exists: bamExists ? "yes" : "no",
      bai_exists: baiExists ? "yes" : "no",
      quickcheck: quickcheck.status === 0 ? "passed" : "failed",
      sort_order: headerState.sortOrder,
      read_group_present: headerState.readGroupPresent ? "yes" : "no",
      read_group_count: headerState.readGroupCount,
      reference_contig_count: headerState.contigs.length,
      expected_brca_contigs_present: headerState.contigs.includes("chr13") && headerState.contigs.includes("chr17") ? "yes" : "no",
      total_alignments: totalAlignments,
      mapped_alignments: mappedAlignments,
      mapped_fraction: round(mappedAlignments / totalAlignments, 4),
      properly_paired_alignments: properlyPairedAlignments,
      properly_paired_fraction: round(properlyPairedAlignments / totalAlignments, 4),
      brca_interval_alignments: intervalAlignments,
      mapped_standard_contigs: idxstatsRows.filter((row) => standardContig(row.contig) && row.mapped > 0).length,
      bam_size_bytes: bamExists ? statSync(pathFromRoot(row.output_bam)).size : "",
      status,
      caveat: row.caveat
    });
  }

  const bamStatus = bamRows.every((row) => row.status === "passed") ? "passed" : "failed";
  await writeCsv(pathFromRoot(`${resultsDir}/bam_validation_summary.csv`), bamRows);
  await writeJson(pathFromRoot(`${resultsDir}/bam_validation_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: bamStatus,
    rows: bamRows
  });
  if (bamStatus !== "passed") {
    throw new Error("Production somatic BAM validation failed.");
  }

  ensureVcfIndex(tumor.truth_snv_vcf_path, "seqc2_truth_snv");
  ensureVcfIndex(tumor.truth_indel_vcf_path, "seqc2_truth_indel");
  const referenceOrder = readReferenceOrder(tumor.reference_fai_path);
  const truthPositions = loadTruthPositions([tumor.truth_snv_vcf_path, tumor.truth_indel_vcf_path]);
  const activeState = buildActiveIntervals(rows, truthPositions, referenceOrder, activeIntervalsPath);

  ensureDir(pathFromRoot(vcfDir));
  const java = tumor.java_path;
  const gatkJar = tumor.gatk_jar_path;
  const mutect2Command = [
    `${sh(java)} -Xmx6g -jar ${sh(gatkJar)} Mutect2`,
    `-R ${sh(tumor.reference_path)}`,
    `-L ${sh(activeIntervalsPath)}`,
    `-I ${sh(tumor.output_bam)} -tumor ${sh(tumor.sample)}`,
    `-I ${sh(normal.output_bam)} -normal ${sh(normal.sample)}`,
    `--native-pair-hmm-threads ${Math.max(1, Math.min(threads, 4))}`,
    `--f1r2-tar-gz ${sh(f1r2Path)}`,
    `-O ${sh(unfilteredVcf)}`
  ].join(" ");
  run(mutect2Command, `${resultsDir}/logs/${referenceId}.mutect2.log`);
  const filterCommand = [
    `${sh(java)} -Xmx4g -jar ${sh(gatkJar)} FilterMutectCalls`,
    `-R ${sh(tumor.reference_path)}`,
    `-V ${sh(unfilteredVcf)}`,
    `-O ${sh(filteredVcf)}`
  ].join(" ");
  run(filterCommand, `${resultsDir}/logs/${referenceId}.filter_mutect_calls.log`);
  run(`bcftools index -t -f ${sh(filteredVcf)}`, `${resultsDir}/logs/${referenceId}.filtered_vcf_index.log`);
  run(`bcftools stats ${sh(filteredVcf)}`, `${resultsDir}/logs/${referenceId}.filtered_vcf_stats.txt`);

  const filteredSamples = parseVcfSampleNames(filteredVcf);
  const filteredCalls = variantKeys(filteredVcf);
  const filteredPass = filteredCalls.passKeys;
  const truthSnvActive = variantKeys(tumor.truth_snv_vcf_path, activeIntervalsPath);
  const truthIndelActive = variantKeys(tumor.truth_indel_vcf_path, activeIntervalsPath);
  const truthActiveKeys = new Set([...truthSnvActive.keys, ...truthIndelActive.keys]);
  const exactTruthMatches = [...filteredPass].filter((key) => truthActiveKeys.has(key));
  const comparisonStatus =
    truthActiveKeys.size === 0
      ? "not_assessable_no_truth_variants_in_active_intervals"
      : filteredPass.size === 0
        ? "assessed_no_passing_mutect2_calls"
        : "assessed_exact_key_overlap";
  const mutectStatus =
    existsSync(pathFromRoot(filteredVcf)) &&
    existsSync(pathFromRoot(`${filteredVcf}.tbi`)) &&
    filteredSamples.includes(tumor.sample) &&
    filteredSamples.includes(normal.sample)
      ? "passed"
      : "failed";

  const mutectRows = [
    {
      reference_id: referenceId,
      caller: "GATK Mutect2 + FilterMutectCalls",
      gatk_jar_path: gatkJar,
      java_path: java,
      input_tumor_bam: tumor.output_bam,
      input_normal_bam: normal.output_bam,
      active_interval_bed_path: activeIntervalsPath,
      active_interval_count: activeState.selected.length,
      active_interval_truth_overlap_count: activeState.truthOverlapCount,
      output_unfiltered_vcf: unfilteredVcf,
      output_filtered_vcf: filteredVcf,
      output_filtered_tbi: `${filteredVcf}.tbi`,
      filtered_vcf_exists: existsSync(pathFromRoot(filteredVcf)) ? "yes" : "no",
      filtered_tbi_exists: existsSync(pathFromRoot(`${filteredVcf}.tbi`)) ? "yes" : "no",
      sample_count: filteredSamples.length,
      samples: filteredSamples.join(";"),
      filtered_records: filteredCalls.totalCount,
      pass_records: filteredCalls.passCount,
      filtered_snv_records: filteredCalls.snvCount,
      filtered_indel_records: filteredCalls.indelCount,
      truth_snv_records_in_active_intervals: truthSnvActive.totalCount,
      truth_indel_records_in_active_intervals: truthIndelActive.totalCount,
      exact_pass_truth_matches: exactTruthMatches.length,
      comparison_status: comparisonStatus,
      status: mutectStatus,
      caveat:
        "Downsampled WES Mutect2 smoke validates production-style tumor-normal caller execution and VCF contracts. It is not a full-depth sensitivity benchmark, does not use PoN/germline-resource filtering, and does not assess WGS HRD signatures."
    }
  ];
  await writeCsv(pathFromRoot(`${resultsDir}/mutect2_smoke_summary.csv`), mutectRows);
  await writeJson(pathFromRoot(`${resultsDir}/mutect2_smoke_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: mutectStatus,
    rows: mutectRows
  });

  await writeJson(pathFromRoot(`${resultsDir}/tool_versions.json`), {
    generatedAt: new Date().toISOString(),
    bwa: { path: capture("command -v bwa"), version: toolVersion("bwa") },
    samtools: { path: capture("command -v samtools"), version: toolVersion("samtools") },
    bcftools: { path: capture("command -v bcftools"), version: toolVersion("bcftools") },
    java: { path: java, version: capture(`${sh(java)} -version 2>&1 | head -n 1`) },
    gatk: { jarPath: gatkJar, version: capture(`${sh(java)} -jar ${sh(gatkJar)} --version 2>&1 | head -n 1`) }
  });

  const status = fastqRows.every((row) => row.paired_id_check === "passed") && bamStatus === "passed" && mutectStatus === "passed" ? "passed" : "failed";
  await writeJson(pathFromRoot(`${resultsDir}/production_somatic_summary.json`), {
    generatedAt: new Date().toISOString(),
    status,
    phase: "2E",
    caller: "GATK Mutect2 + FilterMutectCalls",
    referenceId,
    assembly: tumor.assembly,
    genomeBuild: tumor.genome_build,
    pairId: tumor.pair_id,
    readPairsPerEnd: readLimit,
    sampleRows: rows.length,
    tumorSample: tumor.sample,
    normalSample: normal.sample,
    activeIntervalCount: activeState.selected.length,
    activeIntervalTruthOverlapCount: activeState.truthOverlapCount,
    filteredVcf,
    filteredRecords: filteredCalls.totalCount,
    passRecords: filteredCalls.passCount,
    truthSnvRecordsInActiveIntervals: truthSnvActive.totalCount,
    truthIndelRecordsInActiveIntervals: truthIndelActive.totalCount,
    exactPassTruthMatches: exactTruthMatches.length,
    comparisonStatus,
    boundary:
      "Phase 2E validates a production-style Mutect2 tumor-normal execution path on a larger downsampled HCC1395 WES pair. WES-limited small-variant evidence remains separate from WGS-grade HRD signature, CNV, and SV evidence."
  });
  await writeCsv(pathFromRoot(`${resultsDir}/production_somatic_summary.csv`), [
    {
      status,
      phase: "2E",
      caller: "GATK Mutect2 + FilterMutectCalls",
      reference_id: referenceId,
      assembly: tumor.assembly,
      genome_build: tumor.genome_build,
      read_pairs_per_end: readLimit,
      sample_rows: rows.length,
      active_interval_count: activeState.selected.length,
      active_interval_truth_overlap_count: activeState.truthOverlapCount,
      filtered_records: filteredCalls.totalCount,
      pass_records: filteredCalls.passCount,
      truth_records_in_active_intervals: truthActiveKeys.size,
      exact_pass_truth_matches: exactTruthMatches.length,
      comparison_status: comparisonStatus,
      boundary: "Production-style Mutect2 smoke; not full-depth WES/WGS sensitivity, CNV/SV, or HRD-signature evidence."
    }
  ]);
  await writeText(
    pathFromRoot(`${resultsDir}/README.md`),
    `# Production Somatic Smoke

Status: **${status}**.

Phase 2E caller path: \`GATK Mutect2 + FilterMutectCalls\`

Reference: \`${referenceId}\` (${tumor.genome_build}/${tumor.assembly})

Input: SEQC2/HCC1395 public WES tumor-normal pair, downsampled to \`${readLimit}\` read pairs per FASTQ end.

What this validates:

1. GATK is pinned locally and executable with Java 17+.
2. The full hg38 analysis-set reference has FASTA, \`.fai\`, and GATK sequence dictionary assets.
3. Tumor and matched normal FASTQs align to coordinate-sorted, indexed, read-grouped BAMs.
4. Active Mutect2 intervals are derived from real mapped reads and truth-overlap-prioritized where compatible.
5. Mutect2 and FilterMutectCalls produce an indexed, production-style somatic VCF.
6. SEQC2 high-confidence SNV/INDEL truth VCFs are available for exact-key overlap checks inside active intervals.

What this does not validate:

1. Full-depth WES sensitivity or specificity.
2. Production PoN, germline-resource, contamination, orientation-bias, BQSR, or duplicate-marking resource policy.
3. CNV/SV calling.
4. scarHRD/CHORD/HRDetect/SBS3 or other WGS-grade HRD signature evidence.
5. Clinical actionability for Diana.

Truth comparison status: \`${comparisonStatus}\`

Boundary: WES-limited Mutect2 smoke evidence is kept separate from WGS HRD signature evidence.
`
  );

  if (status !== "passed") {
    throw new Error("Production somatic smoke failed.");
  }

  console.log(`Production somatic smoke ${status}: ${filteredCalls.totalCount} filtered records, ${filteredCalls.passCount} PASS records.`);
}

await main();
