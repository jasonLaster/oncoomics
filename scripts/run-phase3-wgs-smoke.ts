import { existsSync, statSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { ensureDir, parseCsv, pathFromRoot, readJson, readText, round, writeCsv, writeJson, writeText } from "./lib";

type Phase3WgsRow = {
  pair_id: string;
  sample: string;
  role: string;
  run_accession: string;
  source_read_pairs: string;
  fastq_1: string;
  fastq_2: string;
  read_pairs_per_end: string;
  reference_id: string;
  assembly: string;
  genome_build: string;
  reference_path: string;
  reference_fai_path: string;
  reference_dict_path: string;
  reference_sha256: string;
  truth_snv_vcf_path: string;
  truth_indel_vcf_path: string;
  truth_high_confidence_bed_path: string;
  gatk_jar_path: string;
  java_path: string;
  mutect2_panel_of_normals_path: string;
  production_caller: string;
  read_group_id: string;
  read_group_sample: string;
  read_group_library: string;
  read_group_platform: string;
  read_group_platform_unit: string;
  output_bam: string;
  output_bai: string;
  caveat: string;
};

type TruthVariant = {
  key: string;
  type: "snv" | "indel";
  contig: string;
  position: number;
  ref: string;
  alt: string;
};

type Interval = {
  contig: string;
  start: number;
  end: number;
};

const resultsDir = "results/phase3_wgs_smoke";
const force = process.env.PHASE3_WGS_FORCE === "1";
const availableCpus = Number(spawnSync("bash", ["-lc", "sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 8"], { encoding: "utf8" }).stdout.trim() || "8");
const totalThreads = Math.max(2, Number(process.env.PHASE3_WGS_THREADS ?? String(Math.min(16, availableCpus))));
const parallelAlign = process.env.PHASE3_WGS_PARALLEL_ALIGN !== "0";
const perSampleThreads = parallelAlign ? Math.max(2, Math.floor(totalThreads / 2)) : totalThreads;
const gatkThreads = Math.max(1, Math.min(Number(process.env.PHASE3_WGS_GATK_THREADS ?? String(Math.floor(totalThreads / 2))), 8));
const minTruthDepth = Number(process.env.PHASE3_WGS_MIN_TRUTH_DEPTH ?? "1");
const maxTruthVariants = Number(process.env.PHASE3_WGS_MAX_TRUTH_VARIANTS ?? "300");
const intervalPadding = Number(process.env.PHASE3_WGS_INTERVAL_PADDING ?? "100");
const binSize = Number(process.env.PHASE3_WGS_CNV_BIN_SIZE ?? "5000000");
const matrixRecordPolicy = process.env.PHASE3_WGS_MATRIX_RECORD_POLICY ?? "pass_preferred_all_filtered_fallback";

const mutationTypes = ["C>A", "C>G", "C>T", "T>A", "T>C", "T>G"];
const bases = ["A", "C", "G", "T"];
const complementBase: Record<string, string> = { A: "T", C: "G", G: "C", T: "A" };

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

function runOptional(command: string, logPath: string) {
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
  return { ok: result.status === 0, status: result.status, stdout: result.stdout.trim(), stderr: result.stderr.trim() };
}

async function runAsync(command: string, logPath: string) {
  ensureDir(pathFromRoot(logPath.split("/").slice(0, -1).join("/")));
  return new Promise<string>((resolve, reject) => {
    const child = spawn("bash", ["-lc", command], {
      cwd: pathFromRoot(""),
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("close", (status) => {
      const log = [
        `$ ${command}`,
        "",
        "## stdout",
        stdout,
        "",
        "## stderr",
        stderr,
        "",
        `exit_status=${status}`
      ].join("\n");
      writeFileSync(pathFromRoot(logPath), log.endsWith("\n") ? log : `${log}\n`);
      if (status !== 0) {
        reject(new Error(`Command failed (${status}): ${command}. See ${logPath}.`));
      } else {
        resolve(stdout.trim());
      }
    });
  });
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

function fileNonEmpty(relativePath: string) {
  return existsSync(pathFromRoot(relativePath)) && statSync(pathFromRoot(relativePath)).size > 0;
}

function quickcheck(bamPath: string) {
  if (!existsSync(pathFromRoot(bamPath))) {
    return false;
  }
  const result = spawnSync("samtools", ["quickcheck", "-v", pathFromRoot(bamPath)], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024
  });
  return result.status === 0;
}

function readGroup(row: Phase3WgsRow) {
  return [
    "@RG",
    `ID:${row.read_group_id}`,
    `SM:${row.read_group_sample}`,
    `LB:${row.read_group_library}`,
    `PL:${row.read_group_platform}`,
    `PU:${row.read_group_platform_unit}`
  ].join("\\t");
}

function parseHeader(header: string, row: Phase3WgsRow) {
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

function count(command: string) {
  const text = capture(command);
  return Number(text || "0");
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

function loadTruthVariants(vcfPath: string, type: "snv" | "indel") {
  const rows = captureAllowEmpty(`gunzip -c ${sh(vcfPath)} | awk '!/^#/ {print $1 "\\t" $2 "\\t" $4 "\\t" $5}'`);
  const variants: TruthVariant[] = [];
  for (const line of rows.split(/\r?\n/).filter(Boolean)) {
    const [contig, positionText, ref, altText] = line.split("\t");
    const position = Number(positionText);
    if (!standardContig(contig) || !Number.isFinite(position)) {
      continue;
    }
    for (const alt of altText.split(",")) {
      variants.push({
        key: `${contig}:${position}:${ref}:${alt}`,
        type,
        contig,
        position,
        ref,
        alt
      });
    }
  }
  return variants;
}

function writeTruthPositionBed(variants: TruthVariant[], outputPath: string) {
  ensureDir(pathFromRoot(outputPath.split("/").slice(0, -1).join("/")));
  const rows = variants.map((variant) => `${variant.contig}\t${variant.position - 1}\t${variant.position}\t${variant.key}`);
  writeFileSync(pathFromRoot(outputPath), `${rows.join("\n")}\n`);
}

function pickCoveredTruthVariants(variants: TruthVariant[], depthText: string) {
  const byPosition = new Map<string, TruthVariant[]>();
  for (const variant of variants) {
    const positionKey = `${variant.contig}:${variant.position}`;
    const group = byPosition.get(positionKey) ?? [];
    group.push(variant);
    byPosition.set(positionKey, group);
  }
  const covered: Array<TruthVariant & { tumorDepth: number; normalDepth: number; minDepth: number }> = [];
  for (const line of depthText.split(/\r?\n/).filter(Boolean)) {
    const [contig, positionText, tumorText, normalText] = line.split("\t");
    const position = Number(positionText);
    const tumorDepth = Number(tumorText ?? 0);
    const normalDepth = Number(normalText ?? 0);
    if (!Number.isFinite(position) || tumorDepth < minTruthDepth || normalDepth < minTruthDepth) {
      continue;
    }
    for (const variant of byPosition.get(`${contig}:${position}`) ?? []) {
      covered.push({ ...variant, tumorDepth, normalDepth, minDepth: Math.min(tumorDepth, normalDepth) });
    }
  }
  const unique = new Map<string, TruthVariant & { tumorDepth: number; normalDepth: number; minDepth: number }>();
  for (const variant of covered) {
    unique.set(variant.key, variant);
  }
  return Array.from(unique.values())
    .sort((a, b) => b.minDepth - a.minDepth || a.contig.localeCompare(b.contig) || a.position - b.position)
    .slice(0, maxTruthVariants);
}

function writeIntervals(
  variants: Array<TruthVariant & { tumorDepth: number; normalDepth: number; minDepth: number }>,
  referenceOrder: Map<string, number>,
  outputBedPath: string
) {
  const intervals = variants
    .map((variant) => ({
      contig: variant.contig,
      start: Math.max(0, variant.position - 1 - intervalPadding),
      end: variant.position + intervalPadding
    }))
    .sort((a, b) => {
      const contigDelta = (referenceOrder.get(a.contig) ?? 9999) - (referenceOrder.get(b.contig) ?? 9999);
      return contigDelta || a.start - b.start || a.end - b.end;
    });
  const merged: Interval[] = [];
  for (const interval of intervals) {
    const last = merged.at(-1);
    if (!last || last.contig !== interval.contig || interval.start > last.end + 50) {
      merged.push({ ...interval });
      continue;
    }
    last.end = Math.max(last.end, interval.end);
  }
  ensureDir(pathFromRoot(outputBedPath.split("/").slice(0, -1).join("/")));
  writeFileSync(pathFromRoot(outputBedPath), `${merged.map((interval) => `${interval.contig}\t${interval.start}\t${interval.end}`).join("\n")}\n`);
  return merged;
}

function writeFallbackMappedIntervals(rows: Phase3WgsRow[], referenceOrder: Map<string, number>, outputBedPath: string) {
  const intervals: Interval[] = [];
  for (const row of rows) {
    const mappedRows = captureAllowEmpty(`samtools view -F 4 ${sh(row.output_bam)} | awk 'NR<=10000 {print $3 "\\t" $4 "\\t" length($10)}'`);
    for (const line of mappedRows.split(/\r?\n/).filter(Boolean)) {
      const [contig, startText, lengthText] = line.split("\t");
      const startOneBased = Number(startText);
      const readLength = Number(lengthText);
      if (!standardContig(contig) || !Number.isFinite(startOneBased) || !Number.isFinite(readLength) || readLength <= 0) {
        continue;
      }
      intervals.push({
        contig,
        start: Math.max(0, startOneBased - 1 - intervalPadding),
        end: startOneBased - 1 + readLength + intervalPadding
      });
    }
  }
  const sorted = intervals.sort((a, b) => {
    const contigDelta = (referenceOrder.get(a.contig) ?? 9999) - (referenceOrder.get(b.contig) ?? 9999);
    return contigDelta || a.start - b.start || a.end - b.end;
  });
  const picked = sorted.filter((_, index) => index % Math.max(1, Math.floor(sorted.length / maxTruthVariants)) === 0).slice(0, maxTruthVariants);
  if (picked.length === 0) {
    throw new Error("No mapped-read fallback intervals could be built for Phase 3 WGS smoke.");
  }
  writeFileSync(pathFromRoot(outputBedPath), `${picked.map((interval) => `${interval.contig}\t${interval.start}\t${interval.end}`).join("\n")}\n`);
  return picked;
}

function ensureVcfIndex(vcfPath: string, label: string) {
  if (existsSync(pathFromRoot(`${vcfPath}.tbi`))) {
    return "existing";
  }
  const first = runOptional(`bcftools index -t -f ${sh(vcfPath)}`, `${resultsDir}/logs/${label}.vcf_index.log`);
  if (first.ok) {
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

function toolVersion(tool: string) {
  const output = spawnSync("bash", ["-lc", `${tool} 2>&1 | head -n 8`], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024
  });
  return `${output.stdout}${output.stderr}`.trim();
}

function buildBins(faiPath: string, outputBedPath: string) {
  const intervals: Interval[] = [];
  for (const line of readText(pathFromRoot(faiPath)).split(/\r?\n/).filter(Boolean)) {
    const [contig, lengthText] = line.split("\t");
    const length = Number(lengthText);
    if (!standardContig(contig) || !Number.isFinite(length)) {
      continue;
    }
    for (let start = 0; start < length; start += binSize) {
      intervals.push({ contig, start, end: Math.min(length, start + binSize) });
    }
  }
  ensureDir(pathFromRoot(outputBedPath.split("/").slice(0, -1).join("/")));
  writeFileSync(pathFromRoot(outputBedPath), `${intervals.map((interval) => `${interval.contig}\t${interval.start}\t${interval.end}`).join("\n")}\n`);
  return intervals;
}

function median(values: number[]) {
  const clean = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (clean.length === 0) {
    return null;
  }
  const middle = Math.floor(clean.length / 2);
  return clean.length % 2 === 0 ? (clean[middle - 1] + clean[middle]) / 2 : clean[middle];
}

async function buildCoverageCnv(tumor: Phase3WgsRow, normal: Phase3WgsRow, binsPath: string) {
  const rows: Record<string, unknown>[] = [];
  const bedcov = captureAllowEmpty(`samtools bedcov ${sh(binsPath)} ${sh(tumor.output_bam)} ${sh(normal.output_bam)}`);
  for (const line of bedcov.split(/\r?\n/).filter(Boolean)) {
    const [contig, startText, endText, tumorSumText, normalSumText] = line.split("\t");
    const start = Number(startText);
    const end = Number(endText);
    const length = Math.max(1, end - start);
    const tumorDepth = Number(tumorSumText ?? 0) / length;
    const normalDepth = Number(normalSumText ?? 0) / length;
    const log2Ratio = Math.log2((tumorDepth + 0.0001) / (normalDepth + 0.0001));
    rows.push({
      contig,
      start,
      end,
      length,
      tumor_depth_sum: Number(tumorSumText ?? 0),
      normal_depth_sum: Number(normalSumText ?? 0),
      tumor_mean_depth: round(tumorDepth, 6),
      normal_mean_depth: round(normalDepth, 6),
      log2_tumor_normal: round(log2Ratio, 4),
      coverage_class: log2Ratio >= 0.5 ? "relative_gain" : log2Ratio <= -0.5 ? "relative_loss" : "neutral_or_low_signal"
    });
  }
  await writeCsv(pathFromRoot(`${resultsDir}/coverage_cnv_bins.csv`), rows);
  const numericLog2 = rows.map((row) => Number(row.log2_tumor_normal)).filter(Number.isFinite);
  const summaryRows = [
    {
      status: rows.length > 0 ? "passed" : "failed",
      tool: "samtools bedcov",
      bin_size: binSize,
      bin_count: rows.length,
      median_log2_tumor_normal: round(median(numericLog2), 4),
      relative_gain_bins: rows.filter((row) => row.coverage_class === "relative_gain").length,
      relative_loss_bins: rows.filter((row) => row.coverage_class === "relative_loss").length,
      output_bins: "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
      scarhrd_input_status: "not_assessable_low_depth_smoke_no_allele_specific_segments",
      caveat:
        "Real WGS BAM coverage-derived CNV bins from samtools bedcov. This validates CNV feature plumbing but is not allele-specific segmentation or scarHRD."
    }
  ];
  await writeCsv(pathFromRoot(`${resultsDir}/coverage_cnv_summary.csv`), summaryRows);
  await writeJson(pathFromRoot(`${resultsDir}/coverage_cnv_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: summaryRows[0].status,
    rows: summaryRows
  });
  return summaryRows[0];
}

function reverseComplement(sequence: string) {
  return sequence
    .toUpperCase()
    .split("")
    .reverse()
    .map((base) => complementBase[base] ?? "N")
    .join("");
}

function normalizedContext(context: string, ref: string, alt: string) {
  const upperContext = context.toUpperCase();
  const upperRef = ref.toUpperCase();
  const upperAlt = alt.toUpperCase();
  if (upperContext.length !== 3 || !upperContext.split("").every((base) => bases.includes(base))) {
    return null;
  }
  if (upperRef === "C" || upperRef === "T") {
    return {
      mutationType: `${upperRef}>${upperAlt}`,
      trinucleotide: `${upperContext[0]}[${upperRef}>${upperAlt}]${upperContext[2]}`
    };
  }
  const rc = reverseComplement(upperContext);
  const normalizedRef = complementBase[upperRef];
  const normalizedAlt = complementBase[upperAlt];
  return {
    mutationType: `${normalizedRef}>${normalizedAlt}`,
    trinucleotide: `${rc[0]}[${normalizedRef}>${normalizedAlt}]${rc[2]}`
  };
}

function allSbs96Rows() {
  const rows: Record<string, unknown>[] = [];
  for (const mutationType of mutationTypes) {
    for (const left of bases) {
      for (const right of bases) {
        rows.push({
          sample: "HCC1395",
          mutation_type: mutationType,
          trinucleotide: `${left}[${mutationType}]${right}`,
          count: 0,
          source_records: 0,
          source_vcf_policy: matrixRecordPolicy
        });
      }
    }
  }
  return rows;
}

async function buildSbs96Matrix(filteredVcf: string, referencePath: string) {
  const passRows = captureAllowEmpty(`bcftools view -f PASS -v snps -H ${sh(filteredVcf)}`);
  const allFilteredRows = captureAllowEmpty(`bcftools view -v snps -H ${sh(filteredVcf)}`);
  const selectedRows = passRows.trim() ? passRows : allFilteredRows;
  const selectedPolicy = passRows.trim() ? "pass_only" : "all_filtered_fallback";
  const matrixRows = allSbs96Rows();
  const rowByTrinucleotide = new Map(matrixRows.map((row) => [String(row.trinucleotide), row]));
  let usableSnvs = 0;
  let skippedSnvs = 0;

  for (const line of selectedRows.split(/\r?\n/).filter(Boolean)) {
    const [contig, positionText, , ref, altText] = line.split("\t");
    const position = Number(positionText);
    if (!standardContig(contig) || !Number.isFinite(position) || ref.length !== 1) {
      skippedSnvs += 1;
      continue;
    }
    for (const alt of altText.split(",")) {
      if (alt.length !== 1 || !bases.includes(ref.toUpperCase()) || !bases.includes(alt.toUpperCase())) {
        skippedSnvs += 1;
        continue;
      }
      const context = captureAllowEmpty(`samtools faidx ${sh(referencePath)} ${sh(`${contig}:${position - 1}-${position + 1}`)} | awk 'NR>1 {printf "%s", $0}'`);
      const normalized = normalizedContext(context, ref, alt);
      if (!normalized || !mutationTypes.includes(normalized.mutationType)) {
        skippedSnvs += 1;
        continue;
      }
      const row = rowByTrinucleotide.get(normalized.trinucleotide);
      if (!row) {
        skippedSnvs += 1;
        continue;
      }
      row.count = Number(row.count) + 1;
      row.source_records = Number(row.source_records) + 1;
      usableSnvs += 1;
    }
  }

  await writeCsv(pathFromRoot(`${resultsDir}/wgs_sbs96_matrix.csv`), matrixRows);
  const summaryRows = [
    {
      status: "passed",
      tool: "local_sbs96_matrix_builder",
      source_vcf: filteredVcf,
      source_record_policy: selectedPolicy,
      sbs96_rows: matrixRows.length,
      usable_snv_records: usableSnvs,
      skipped_snv_records: skippedSnvs,
      total_matrix_count: matrixRows.reduce((sum, row) => sum + Number(row.count), 0),
      sigprofiler_assignment_status: usableSnvs >= 50 ? "input_ready_threshold_met" : "not_assessable_low_mutation_count",
      output_matrix: "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
      caveat:
        "SBS96 matrix is built from actual Phase 3 WGS smoke VCF records. Signature assignment is not interpreted when the downsample has too few mutations."
    }
  ];
  await writeCsv(pathFromRoot(`${resultsDir}/signature_assignment_summary.csv`), summaryRows);
  await writeJson(pathFromRoot(`${resultsDir}/signature_assignment_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "passed",
    rows: summaryRows
  });
  return summaryRows[0];
}

async function buildSvEvidence(rows: Phase3WgsRow[]) {
  const summaryRows: Record<string, unknown>[] = [];
  const candidateRows: Record<string, unknown>[] = [];
  for (const row of rows) {
    const totalAlignments = count(`samtools view -c ${sh(row.output_bam)}`);
    const supplementary = count(`samtools view -c -f 2048 ${sh(row.output_bam)}`);
    const discordantMappedPairs = count(`samtools view -c -f 1 -F 14 ${sh(row.output_bam)}`);
    const interchromPairs = count(`samtools view -f 1 -F 14 ${sh(row.output_bam)} | awk '$7!="=" && $7!="*" {n++} END {print n+0}'`);
    const largeInsertPairs = count(`samtools view -f 1 -F 14 ${sh(row.output_bam)} | awk '$7=="=" && ($9>100000 || $9<-100000) {n++} END {print n+0}'`);
    const candidates = captureAllowEmpty(
      `samtools view -f 1 -F 14 ${sh(row.output_bam)} | awk 'BEGIN{OFS="\\t"} NR<=100 {print $1,$3,$4,$7,$8,$9,$5,$6}'`
    );
    for (const line of candidates.split(/\r?\n/).filter(Boolean)) {
      const [readName, chrom1, pos1, chrom2, pos2, templateLength, mapq, cigar] = line.split("\t");
      candidateRows.push({
        sample: row.sample,
        role: row.role,
        run_accession: row.run_accession,
        read_name: readName,
        chrom1,
        pos1,
        chrom2,
        pos2,
        template_length: templateLength,
        mapq,
        cigar
      });
    }
    summaryRows.push({
      status: "passed",
      tool: "samtools view flag/evidence counters",
      sample: row.sample,
      role: row.role,
      run_accession: row.run_accession,
      input_bam: row.output_bam,
      total_alignments: totalAlignments,
      supplementary_alignments: supplementary,
      discordant_mapped_pairs: discordantMappedPairs,
      interchromosomal_pairs: interchromPairs,
      large_insert_pairs: largeInsertPairs,
      sv_candidate_rows_written: Math.min(100, candidates.split(/\r?\n/).filter(Boolean).length),
      chord_input_status: "not_assessable_low_depth_smoke_requires_full_depth_sv_caller_vcf",
      caveat:
        "Real BAM-derived split/discordant/interchromosomal evidence counts. This is a WGS SV evidence smoke, not a validated full-depth SV caller VCF."
    });
  }
  await writeCsv(pathFromRoot(`${resultsDir}/sv_evidence_candidates.csv`), candidateRows);
  await writeCsv(pathFromRoot(`${resultsDir}/sv_evidence_summary.csv`), summaryRows);
  await writeJson(pathFromRoot(`${resultsDir}/sv_evidence_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: summaryRows.every((row) => row.status === "passed") ? "passed" : "failed",
    rows: summaryRows
  });
  return summaryRows;
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));

  const assetSummary = readJson<Record<string, unknown>>(pathFromRoot(`${resultsDir}/asset_summary.json`));
  if (assetSummary.status !== "ready") {
    throw new Error("Phase 3 WGS asset summary is not ready. Run fetch:phase3-wgs first.");
  }

  const rows = parseCsv(readText(pathFromRoot("manifests/phase3_wgs_smoke_samplesheet.csv"))) as Phase3WgsRow[];
  if (rows.length !== 2 || !rows.some((row) => row.role === "tumor") || !rows.some((row) => row.role === "normal")) {
    throw new Error("Expected tumor and normal rows in manifests/phase3_wgs_smoke_samplesheet.csv.");
  }
  const tumor = rows.find((row) => row.role === "tumor") as Phase3WgsRow;
  const normal = rows.find((row) => row.role === "normal") as Phase3WgsRow;
  const referenceId = tumor.reference_id;
  const outputRoot = `data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/${referenceId}`;
  const intervalDir = `${outputRoot}/intervals`;
  const vcfDir = `${outputRoot}/vcf`;
  const binsPath = `${intervalDir}/standard_contig_${binSize}bp_bins.bed`;
  const truthPositionBed = `${intervalDir}/seqc2_truth_positions.bed`;
  const mutectIntervals = `${intervalDir}/phase3_wgs_mutect2_intervals.bed`;
  const coveredTruthCsv = `${resultsDir}/covered_truth_variants.csv`;
  const unfilteredVcf = `${vcfDir}/hcc1395.phase3_wgs_smoke.mutect2.unfiltered.vcf.gz`;
  const filteredVcf = `${vcfDir}/hcc1395.phase3_wgs_smoke.mutect2.filtered.vcf.gz`;
  const f1r2Path = `${vcfDir}/hcc1395.phase3_wgs_smoke.mutect2.f1r2.tar.gz`;

  for (const row of rows) {
    for (const path of [row.fastq_1, row.fastq_2, row.reference_path, row.reference_fai_path, row.reference_dict_path, row.gatk_jar_path]) {
      if (!existsSync(pathFromRoot(path))) {
        throw new Error(`Required Phase 3 WGS input is missing: ${path}`);
      }
    }
  }
  if (!existsSync(pathFromRoot(`${tumor.reference_path}.bwt`))) {
    run(`bwa index ${sh(tumor.reference_path)}`, `${resultsDir}/logs/${referenceId}.bwa_index.log`);
  }

  const alignCommands = rows.map((row) => {
    ensureDir(pathFromRoot(row.output_bam.split("/").slice(0, -1).join("/")));
    return {
      row,
      command: `set -o pipefail; ${[
        `bwa mem -t ${perSampleThreads} -R ${sh(readGroup(row))} ${sh(row.reference_path)} ${sh(row.fastq_1)} ${sh(row.fastq_2)}`,
        `samtools sort -@ ${perSampleThreads} -o ${sh(row.output_bam)} -`
      ].join(" | ")}`
    };
  });

  if (parallelAlign) {
    await Promise.all(
      alignCommands.map(async ({ row, command }) => {
        if (!force && quickcheck(row.output_bam)) {
          return;
        }
        await runAsync(command, `${resultsDir}/logs/${referenceId}.${row.run_accession}.align.log`);
      })
    );
  } else {
    for (const { row, command } of alignCommands) {
      if (!force && quickcheck(row.output_bam)) {
        continue;
      }
      run(command, `${resultsDir}/logs/${referenceId}.${row.run_accession}.align.log`);
    }
  }

  await Promise.all(
    rows.map(async (row) => {
      if (force || !existsSync(pathFromRoot(row.output_bai))) {
        await runAsync(`samtools index -@ ${perSampleThreads} -o ${sh(row.output_bai)} ${sh(row.output_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.index.log`);
      }
      await runAsync(`samtools flagstat ${sh(row.output_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.flagstat.txt`);
      await runAsync(`samtools stats ${sh(row.output_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.stats.txt`);
    })
  );

  const bamRows: Record<string, unknown>[] = [];
  for (const row of rows) {
    const headerState = parseHeader(capture(`samtools view -H ${sh(row.output_bam)}`), row);
    const totalAlignments = count(`samtools view -c ${sh(row.output_bam)}`);
    const mappedAlignments = count(`samtools view -c -F 4 ${sh(row.output_bam)}`);
    const properlyPairedAlignments = count(`samtools view -c -f 2 ${sh(row.output_bam)}`);
    const standardMappedContigs = count(`samtools idxstats ${sh(row.output_bam)} | awk '$1 ~ /^chr([1-9]|1[0-9]|2[0-2]|X|Y)$/ && $3 > 0 {n++} END {print n+0}'`);
    const status =
      quickcheck(row.output_bam) &&
      existsSync(pathFromRoot(row.output_bai)) &&
      headerState.sortOrder === "coordinate" &&
      headerState.readGroupPresent &&
      headerState.contigs.length > 20 &&
      mappedAlignments > 0 &&
      standardMappedContigs > 0
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
      read_pairs_per_end: row.read_pairs_per_end,
      reference_sha256: row.reference_sha256,
      output_bam: row.output_bam,
      output_bai: row.output_bai,
      bam_exists: existsSync(pathFromRoot(row.output_bam)) ? "yes" : "no",
      bai_exists: existsSync(pathFromRoot(row.output_bai)) ? "yes" : "no",
      quickcheck: quickcheck(row.output_bam) ? "passed" : "failed",
      sort_order: headerState.sortOrder,
      read_group_present: headerState.readGroupPresent ? "yes" : "no",
      read_group_count: headerState.readGroupCount,
      reference_contig_count: headerState.contigs.length,
      total_alignments: totalAlignments,
      mapped_alignments: mappedAlignments,
      mapped_fraction: round(mappedAlignments / totalAlignments, 4),
      properly_paired_alignments: properlyPairedAlignments,
      properly_paired_fraction: round(properlyPairedAlignments / totalAlignments, 4),
      mapped_standard_contigs: standardMappedContigs,
      bam_size_bytes: existsSync(pathFromRoot(row.output_bam)) ? statSync(pathFromRoot(row.output_bam)).size : "",
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
    throw new Error("Phase 3 WGS BAM validation failed.");
  }

  ensureDir(pathFromRoot(intervalDir));
  ensureDir(pathFromRoot(vcfDir));
  const bins = buildBins(tumor.reference_fai_path, binsPath);
  const cnvSummary = await buildCoverageCnv(tumor, normal, binsPath);

  ensureVcfIndex(tumor.truth_snv_vcf_path, "seqc2_truth_snv");
  ensureVcfIndex(tumor.truth_indel_vcf_path, "seqc2_truth_indel");
  const truthVariants = [...loadTruthVariants(tumor.truth_snv_vcf_path, "snv"), ...loadTruthVariants(tumor.truth_indel_vcf_path, "indel")];
  writeTruthPositionBed(truthVariants, truthPositionBed);
  const truthDepthText = captureAllowEmpty(`samtools depth -a -b ${sh(truthPositionBed)} ${sh(tumor.output_bam)} ${sh(normal.output_bam)}`);
  const coveredTruthVariants = pickCoveredTruthVariants(truthVariants, truthDepthText);
  const referenceOrder = readReferenceOrder(tumor.reference_fai_path);
  const intervalRows = coveredTruthVariants.length > 0
    ? writeIntervals(coveredTruthVariants, referenceOrder, mutectIntervals)
    : writeFallbackMappedIntervals(rows, referenceOrder, mutectIntervals);
  await writeCsv(
    pathFromRoot(coveredTruthCsv),
    coveredTruthVariants.map((variant) => ({
      key: variant.key,
      type: variant.type,
      contig: variant.contig,
      position: variant.position,
      ref: variant.ref,
      alt: variant.alt,
      tumor_depth: variant.tumorDepth,
      normal_depth: variant.normalDepth,
      min_depth: variant.minDepth
    }))
  );

  const ponPart = fileNonEmpty(tumor.mutect2_panel_of_normals_path) ? `--panel-of-normals ${sh(tumor.mutect2_panel_of_normals_path)}` : "";
  if (force || !existsSync(pathFromRoot(unfilteredVcf)) || !existsSync(pathFromRoot(`${unfilteredVcf}.tbi`))) {
    const mutect2Command = [
      `${sh(tumor.java_path)} -Xmx10g -jar ${sh(tumor.gatk_jar_path)} Mutect2`,
      `-R ${sh(tumor.reference_path)}`,
      `-L ${sh(mutectIntervals)}`,
      `-I ${sh(tumor.output_bam)} -tumor ${sh(tumor.sample)}`,
      `-I ${sh(normal.output_bam)} -normal ${sh(normal.sample)}`,
      ponPart,
      `--native-pair-hmm-threads ${gatkThreads}`,
      `--f1r2-tar-gz ${sh(f1r2Path)}`,
      `-O ${sh(unfilteredVcf)}`
    ].filter(Boolean).join(" ");
    run(mutect2Command, `${resultsDir}/logs/${referenceId}.phase3_wgs.mutect2.log`);
  }
  if (force || !existsSync(pathFromRoot(filteredVcf)) || !existsSync(pathFromRoot(`${filteredVcf}.tbi`))) {
    const filterCommand = [
      `${sh(tumor.java_path)} -Xmx6g -jar ${sh(tumor.gatk_jar_path)} FilterMutectCalls`,
      `-R ${sh(tumor.reference_path)}`,
      `-V ${sh(unfilteredVcf)}`,
      `-O ${sh(filteredVcf)}`
    ].join(" ");
    run(filterCommand, `${resultsDir}/logs/${referenceId}.phase3_wgs.filter_mutect_calls.log`);
    run(`bcftools index -t -f ${sh(filteredVcf)}`, `${resultsDir}/logs/${referenceId}.phase3_wgs.filtered_vcf_index.log`);
  }
  run(`bcftools stats ${sh(filteredVcf)}`, `${resultsDir}/logs/${referenceId}.phase3_wgs.filtered_vcf_stats.txt`);

  const filteredSamples = parseVcfSampleNames(filteredVcf);
  const filteredCalls = variantKeys(filteredVcf, mutectIntervals);
  const truthActiveSnv = variantKeys(tumor.truth_snv_vcf_path, mutectIntervals);
  const truthActiveIndel = variantKeys(tumor.truth_indel_vcf_path, mutectIntervals);
  const truthActiveKeys = new Set([...truthActiveSnv.keys, ...truthActiveIndel.keys]);
  const exactTruthMatches = [...filteredCalls.passKeys].filter((key) => truthActiveKeys.has(key));
  const mutectStatus =
    existsSync(pathFromRoot(filteredVcf)) &&
    existsSync(pathFromRoot(`${filteredVcf}.tbi`)) &&
    filteredSamples.includes(tumor.sample) &&
    filteredSamples.includes(normal.sample)
      ? "passed"
      : "failed";
  const comparisonStatus =
    coveredTruthVariants.length === 0
      ? "not_assessable_no_depth_covered_truth_variants_in_wgs_smoke"
      : filteredCalls.passCount === 0
        ? "assessed_no_passing_mutect2_calls"
        : "assessed_exact_key_overlap";
  const mutectRows = [
    {
      status: mutectStatus,
      phase: "3",
      caller: tumor.production_caller,
      reference_id: referenceId,
      pair_id: tumor.pair_id,
      tumor_sample: tumor.sample,
      normal_sample: normal.sample,
      tumor_run: tumor.run_accession,
      normal_run: normal.run_accession,
      read_pairs_per_end: tumor.read_pairs_per_end,
      interval_strategy: coveredTruthVariants.length > 0 ? "covered_seqc2_truth_variants" : "mapped_read_fallback_intervals",
      mutect_interval_bed_path: mutectIntervals,
      mutect_interval_count: intervalRows.length,
      truth_variants_total: truthVariants.length,
      truth_variants_depth_eligible: coveredTruthVariants.length,
      truth_snv_records_in_intervals: truthActiveSnv.totalCount,
      truth_indel_records_in_intervals: truthActiveIndel.totalCount,
      filtered_vcf: filteredVcf,
      filtered_tbi: `${filteredVcf}.tbi`,
      filtered_records_in_intervals: filteredCalls.totalCount,
      pass_records_in_intervals: filteredCalls.passCount,
      exact_pass_truth_matches: exactTruthMatches.length,
      comparison_status: comparisonStatus,
      panel_of_normals_used: ponPart ? tumor.mutect2_panel_of_normals_path : "",
      caveat:
        "Real GATK Mutect2 WGS-smoke small-variant output. Downsample depth limits sensitivity and signature interpretability."
    }
  ];
  await writeCsv(pathFromRoot(`${resultsDir}/mutect2_wgs_summary.csv`), mutectRows);
  await writeJson(pathFromRoot(`${resultsDir}/mutect2_wgs_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: mutectStatus,
    rows: mutectRows
  });

  const signatureSummary = await buildSbs96Matrix(filteredVcf, tumor.reference_path);
  const svSummaryRows = await buildSvEvidence(rows);

  const hrdToolRows = [
    {
      tool: "SigProfilerAssignment",
      evidence_input: "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
      local_phase3_output: "results/phase3_wgs_smoke/signature_assignment_summary.csv",
      real_output_status: "real_sbs96_matrix_output",
      interpretability_status: signatureSummary.sigprofiler_assignment_status,
      caveat: "Classification is deferred for low mutation count; the matrix is a real VCF-derived output, not a proxy."
    },
    {
      tool: "scarHRD",
      evidence_input: "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
      local_phase3_output: "results/phase3_wgs_smoke/coverage_cnv_summary.csv",
      real_output_status: "real_coverage_cnv_bin_output",
      interpretability_status: cnvSummary.scarhrd_input_status,
      caveat: "scarHRD needs allele-specific segmented CN calls; this smoke validates WGS coverage-bin plumbing only."
    },
    {
      tool: "CHORD",
      evidence_input: "results/phase3_wgs_smoke/sv_evidence_summary.csv",
      local_phase3_output: "results/phase3_wgs_smoke/sv_evidence_summary.csv",
      real_output_status: "real_bam_sv_evidence_output",
      interpretability_status: "not_assessable_low_depth_smoke_requires_full_depth_sv_caller_vcf",
      caveat: "CHORD-style interpretation needs full-depth SNV/indel/SV/CNV feature inputs; this smoke validates the feature lanes."
    }
  ];
  await writeCsv(pathFromRoot(`${resultsDir}/hrd_tool_readiness_summary.csv`), hrdToolRows);
  await writeJson(pathFromRoot(`${resultsDir}/hrd_tool_readiness_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "passed",
    rows: hrdToolRows
  });

  await writeJson(pathFromRoot(`${resultsDir}/tool_versions.json`), {
    generatedAt: new Date().toISOString(),
    bwa: { path: capture("command -v bwa"), version: toolVersion("bwa") },
    samtools: { path: capture("command -v samtools"), version: toolVersion("samtools") },
    bcftools: { path: capture("command -v bcftools"), version: toolVersion("bcftools") },
    java: { path: tumor.java_path, version: capture(`${sh(tumor.java_path)} -version 2>&1 | head -n 1`) },
    gatk: { jarPath: tumor.gatk_jar_path, version: capture(`${sh(tumor.java_path)} -jar ${sh(tumor.gatk_jar_path)} --version 2>&1 | head -n 1`) }
  });

  const phase3Complete =
    bamStatus === "passed" &&
    mutectStatus === "passed" &&
    cnvSummary.status === "passed" &&
    signatureSummary.status === "passed" &&
    svSummaryRows.every((row) => row.status === "passed");
  const summaryRows = [
    {
      status: phase3Complete ? "passed" : "failed",
      phase: "3",
      pair_id: tumor.pair_id,
      reference_id: referenceId,
      read_pairs_per_end: tumor.read_pairs_per_end,
      available_cpus: availableCpus,
      total_threads: totalThreads,
      parallel_align: parallelAlign ? "yes" : "no",
      per_sample_threads: perSampleThreads,
      gatk_threads: gatkThreads,
      bam_validation_status: bamStatus,
      mutect2_status: mutectStatus,
      mutect_interval_count: intervalRows.length,
      truth_variants_depth_eligible: coveredTruthVariants.length,
      pass_records_in_intervals: filteredCalls.passCount,
      exact_pass_truth_matches: exactTruthMatches.length,
      coverage_cnv_status: cnvSummary.status,
      coverage_cnv_bins: cnvSummary.bin_count,
      sbs96_matrix_status: signatureSummary.status,
      sbs96_usable_snv_records: signatureSummary.usable_snv_records,
      sv_evidence_status: svSummaryRows.every((row) => row.status === "passed") ? "passed" : "failed",
      phase3_complete: phase3Complete ? "yes" : "no",
      ready_for_phase4_when_diana_raw_arrives: phase3Complete ? "yes" : "no",
      boundary:
        "Phase 3 validates WGS-capable mechanics with real representative WGS FASTQ, BAM, small-variant VCF, coverage-CNV bins, SBS96 matrix, and SV evidence outputs. Full-depth Diana interpretation still needs Diana raw data and production CNV/SV/signature policy."
    }
  ];
  await writeCsv(pathFromRoot(`${resultsDir}/phase3_wgs_summary.csv`), summaryRows);
  await writeJson(pathFromRoot(`${resultsDir}/phase3_wgs_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: phase3Complete ? "passed" : "failed",
    phase: "3",
    pairId: tumor.pair_id,
    referenceId,
    readPairsPerEnd: Number(tumor.read_pairs_per_end),
    availableCpus,
    totalThreads,
    parallelAlign,
    perSampleThreads,
    gatkThreads,
    bamValidationStatus: bamStatus,
    mutect2Status: mutectStatus,
    mutectIntervalCount: intervalRows.length,
    truthVariantsDepthEligible: coveredTruthVariants.length,
    passRecordsInIntervals: filteredCalls.passCount,
    exactPassTruthMatches: exactTruthMatches.length,
    coverageCnvStatus: cnvSummary.status,
    coverageCnvBins: cnvSummary.bin_count,
    sbs96MatrixStatus: signatureSummary.status,
    sbs96UsableSnvRecords: signatureSummary.usable_snv_records,
    svEvidenceStatus: svSummaryRows.every((row) => row.status === "passed") ? "passed" : "failed",
    phase3Complete,
    readyForPhase4WhenDianaRawArrives: phase3Complete,
    boundary: String(summaryRows[0].boundary)
  });
  await writeText(
    pathFromRoot(`${resultsDir}/README.md`),
    `# Phase 3 WGS HRD Capability Smoke

Status: **${phase3Complete ? "passed" : "failed"}**.

Representative pair: \`${tumor.pair_id}\`

Reference: \`${referenceId}\` (${tumor.genome_build}/${tumor.assembly})

Reads per FASTQ end: \`${tumor.read_pairs_per_end}\`

Parallelism:

1. Available CPUs detected: \`${availableCpus}\`
2. Total thread budget: \`${totalThreads}\`
3. Tumor/normal alignment in parallel: \`${parallelAlign ? "yes" : "no"}\`
4. Per-sample alignment/sort threads: \`${perSampleThreads}\`
5. GATK PairHMM threads: \`${gatkThreads}\`

What this validates:

1. Real representative HCC1395 WGS FASTQ subset alignment to the full hg38 analysis-set reference.
2. Coordinate-sorted, indexed, read-grouped tumor and matched-normal WGS BAM contracts.
3. Real GATK Mutect2/FilterMutectCalls tumor-normal WGS-smoke VCF output.
4. Real coverage-derived tumor/normal CNV bin output from \`samtools bedcov\`.
5. Real SBS96 mutation matrix output from the actual WGS-smoke VCF.
6. Real BAM-derived SV evidence counts from split/supplementary/discordant/interchromosomal read evidence.
7. A clear boundary between WES small-variant evidence, WGS-capable smoke outputs, and full-depth WGS HRD interpretation.

What remains Diana-specific:

1. Full-depth WGS or WES input inventory, reference policy, and production compute target.
2. Allele-specific CNV segmentation for scarHRD.
3. Validated SV caller VCF for CHORD/HRDetect-style feature extraction.
4. Stable SBS signature assignment only when mutation count and coverage are adequate.
5. Reviewer sign-off before any treatment-changing interpretation.
`
  );

  if (!phase3Complete) {
    throw new Error("Phase 3 WGS smoke failed.");
  }

  console.log(`Phase 3 WGS smoke passed: ${intervalRows.length} intervals, ${filteredCalls.passCount} PASS calls, ${cnvSummary.bin_count} CNV bins.`);
}

await main();
