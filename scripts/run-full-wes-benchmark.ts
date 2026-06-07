import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureDir, parseCsv, pathFromRoot, readText, round, writeCsv, writeJson, writeText } from "./lib";

type FullWesSampleRow = {
  pair_id: string;
  sample: string;
  role: string;
  run_accession: string;
  source_read_pairs: string;
  source_bases: string;
  fastq_1: string;
  fastq_2: string;
  fastq_1_md5: string;
  fastq_2_md5: string;
  fastq_1_bytes: string;
  fastq_2_bytes: string;
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
  gatk_jar_path: string;
  java_path: string;
  mutect2_germline_resource_path: string;
  mutect2_germline_resource_source_url: string;
  mutect2_panel_of_normals_path: string;
  common_biallelic_resource_path: string;
  common_biallelic_resource_index_path: string;
  bqsr_known_sites_policy: string;
  contamination_policy: string;
  duplicate_marking_tool: string;
  production_caller: string;
  read_group_id: string;
  read_group_sample: string;
  read_group_library: string;
  read_group_platform: string;
  read_group_platform_unit: string;
  raw_bam: string;
  dedup_bam: string;
  dedup_bai: string;
  duplicate_metrics_path: string;
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

const resultsDir = "results/full_wes_benchmark";
const force = process.env.PHASE2F_FORCE === "1";
const threads = Number(process.env.PHASE2F_THREADS ?? "8");
const minTruthDepth = Number(process.env.PHASE2F_MIN_TRUTH_DEPTH ?? "10");
const maxTruthVariants = Number(process.env.PHASE2F_MAX_TRUTH_VARIANTS ?? "5000");
const intervalPadding = Number(process.env.PHASE2F_INTERVAL_PADDING ?? "100");

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

function md5File(relativePath: string) {
  return createHash("md5").update(readFileSync(pathFromRoot(relativePath))).digest("hex");
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

function readGroup(row: FullWesSampleRow) {
  return [
    "@RG",
    `ID:${row.read_group_id}`,
    `SM:${row.read_group_sample}`,
    `LB:${row.read_group_library}`,
    `PL:${row.read_group_platform}`,
    `PU:${row.read_group_platform_unit}`
  ].join("\\t");
}

function parseHeader(header: string, row: FullWesSampleRow) {
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

function parseDuplicateMetrics(relativePath: string) {
  const text = readText(pathFromRoot(relativePath));
  const lines = text.split(/\r?\n/);
  const headerIndex = lines.findIndex((line) => line.startsWith("LIBRARY\t"));
  if (headerIndex === -1 || !lines[headerIndex + 1]) {
    return {};
  }
  const headers = lines[headerIndex].split("\t");
  const values = lines[headerIndex + 1].split("\t");
  const row: Record<string, string> = {};
  headers.forEach((header, index) => {
    row[header] = values[index] ?? "";
  });
  return row;
}

function parseDepthSummary(depthText: string) {
  let bases = 0;
  let tumorDepth = 0;
  let normalDepth = 0;
  let bothAt10 = 0;
  for (const line of depthText.split(/\r?\n/).filter(Boolean)) {
    const [, , tumorText, normalText] = line.split("\t");
    const tumor = Number(tumorText ?? 0);
    const normal = Number(normalText ?? 0);
    bases += 1;
    tumorDepth += tumor;
    normalDepth += normal;
    if (tumor >= 10 && normal >= 10) {
      bothAt10 += 1;
    }
  }
  return {
    bases,
    tumorMeanDepth: bases ? round(tumorDepth / bases, 2) : "",
    normalMeanDepth: bases ? round(normalDepth / bases, 2) : "",
    basesBothDepthAtLeast10: bothAt10,
    fractionBothDepthAtLeast10: bases ? round(bothAt10 / bases, 4) : ""
  };
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

function writeBenchmarkIntervals(
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
  const merged: Array<{ contig: string; start: number; end: number }> = [];
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

function fileNonEmpty(relativePath: string) {
  return existsSync(pathFromRoot(relativePath)) && statSync(pathFromRoot(relativePath)).size > 0;
}

function parseContaminationTable(relativePath: string) {
  if (!fileNonEmpty(relativePath)) {
    return { contamination: "", error: "" };
  }
  const rows = readText(pathFromRoot(relativePath))
    .split(/\r?\n/)
    .filter((line) => line && !line.startsWith("#"));
  const headerIndex = rows.findIndex((line) => line.split("\t").includes("contamination"));
  if (headerIndex === -1 || !rows[headerIndex + 1]) {
    return { contamination: "", error: "" };
  }
  const headers = rows[headerIndex].split("\t");
  const values = rows[headerIndex + 1].split("\t");
  const contaminationIndex = headers.indexOf("contamination");
  const errorIndex = headers.indexOf("error");
  return {
    contamination: contaminationIndex >= 0 ? values[contaminationIndex] ?? "" : "",
    error: errorIndex >= 0 ? values[errorIndex] ?? "" : ""
  };
}

function toolVersion(tool: string) {
  const output = spawnSync("bash", ["-lc", `${tool} 2>&1 | head -n 8`], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024
  });
  return `${output.stdout}${output.stderr}`.trim();
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));

  const rows = parseCsv(readText(pathFromRoot("manifests/full_wes_benchmark_samplesheet.csv"))) as FullWesSampleRow[];
  if (rows.length !== 2 || !rows.some((row) => row.role === "tumor") || !rows.some((row) => row.role === "normal")) {
    throw new Error("Expected tumor and normal rows in manifests/full_wes_benchmark_samplesheet.csv.");
  }
  const tumor = rows.find((row) => row.role === "tumor") as FullWesSampleRow;
  const normal = rows.find((row) => row.role === "normal") as FullWesSampleRow;
  const referenceId = tumor.reference_id;
  const outputRoot = `data/raw/full_wes_benchmark/seqc2_hcc1395_wes_minimal/${referenceId}`;
  const intervalDir = `${outputRoot}/intervals`;
  const metricsDir = `${outputRoot}/metrics`;
  const vcfDir = `${outputRoot}/vcf`;
  const truthPositionBed = `${intervalDir}/seqc2_truth_positions.bed`;
  const benchmarkIntervals = `${intervalDir}/covered_truth_benchmark_intervals.bed`;
  const contaminationIntervals = tumor.brca_interval_bed_path;
  const coveredTruthTsv = `${intervalDir}/covered_truth_variants.tsv`;
  const unfilteredVcf = `${vcfDir}/hcc1395.full_wes.resource_aware.mutect2.unfiltered.vcf.gz`;
  const filteredVcf = `${vcfDir}/hcc1395.full_wes.resource_aware.mutect2.filtered.vcf.gz`;
  const filterLogPath = `${resultsDir}/logs/${referenceId}.full_wes.resource_aware.filter_mutect_calls.log`;
  const f1r2Path = `${vcfDir}/hcc1395.full_wes.resource_aware.mutect2.f1r2.tar.gz`;
  const tumorPileups = `${metricsDir}/${tumor.run_accession}.tumor.getpileupsummaries.table`;
  const normalPileups = `${metricsDir}/${normal.run_accession}.normal.getpileupsummaries.table`;
  const contaminationTable = `${metricsDir}/hcc1395.calculate_contamination.table`;

  const fastqRows: Record<string, unknown>[] = [];
  for (const row of rows) {
    for (const read of ["1", "2"] as const) {
      const path = read === "1" ? row.fastq_1 : row.fastq_2;
      const expectedMd5 = read === "1" ? row.fastq_1_md5 : row.fastq_2_md5;
      const expectedBytes = Number(read === "1" ? row.fastq_1_bytes : row.fastq_2_bytes);
      const actualMd5 = md5File(path);
      const actualBytes = statSync(pathFromRoot(path)).size;
      if (actualMd5 !== expectedMd5 || actualBytes !== expectedBytes) {
        throw new Error(`${path} failed md5/byte validation.`);
      }
      fastqRows.push({
        pair_id: row.pair_id,
        sample: row.sample,
        role: row.role,
        run_accession: row.run_accession,
        read,
        fastq_path: path,
        expected_md5: expectedMd5,
        actual_md5: actualMd5,
        expected_bytes: expectedBytes,
        actual_bytes: actualBytes,
        source_read_pairs: row.source_read_pairs,
        status: "passed"
      });
    }
  }
  await writeCsv(pathFromRoot(`${resultsDir}/full_wes_fastq_validation.csv`), fastqRows);
  await writeJson(pathFromRoot(`${resultsDir}/full_wes_fastq_validation.json`), {
    generatedAt: new Date().toISOString(),
    status: "passed",
    rows: fastqRows
  });

  for (const row of rows) {
    ensureDir(pathFromRoot(row.raw_bam.split("/").slice(0, -1).join("/")));
    ensureDir(pathFromRoot(row.duplicate_metrics_path.split("/").slice(0, -1).join("/")));
    const shouldAlign = force || !quickcheck(row.raw_bam);
    if (shouldAlign) {
      const alignCommand = `set -o pipefail; ${[
        `bwa mem -t ${threads} -R ${sh(readGroup(row))} ${sh(row.reference_path)} ${sh(row.fastq_1)} ${sh(row.fastq_2)}`,
        `samtools sort -@ ${threads} -o ${sh(row.raw_bam)} -`
      ].join(" | ")}`;
      run(alignCommand, `${resultsDir}/logs/${referenceId}.${row.run_accession}.full_wes_align.log`);
    }
    const shouldMarkDuplicates = force || !quickcheck(row.dedup_bam) || !existsSync(pathFromRoot(row.duplicate_metrics_path));
    if (shouldMarkDuplicates) {
      run(
        [
          `${sh(row.java_path)} -Xmx12g -jar ${sh(row.gatk_jar_path)} MarkDuplicates`,
          `-I ${sh(row.raw_bam)}`,
          `-O ${sh(row.dedup_bam)}`,
          `-M ${sh(row.duplicate_metrics_path)}`,
          "--VALIDATION_STRINGENCY SILENT"
        ].join(" "),
        `${resultsDir}/logs/${referenceId}.${row.run_accession}.mark_duplicates.log`
      );
      run(`samtools index -@ ${threads} -o ${sh(row.dedup_bai)} ${sh(row.dedup_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.dedup_index.log`);
    } else if (!existsSync(pathFromRoot(row.dedup_bai))) {
      run(`samtools index -@ ${threads} -o ${sh(row.dedup_bai)} ${sh(row.dedup_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.dedup_index.log`);
    }
    run(`samtools flagstat ${sh(row.dedup_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.dedup_flagstat.txt`);
    run(`samtools stats ${sh(row.dedup_bam)}`, `${resultsDir}/logs/${referenceId}.${row.run_accession}.dedup_stats.txt`);
  }

  const bamRows: Record<string, unknown>[] = [];
  for (const row of rows) {
    const headerState = parseHeader(capture(`samtools view -H ${sh(row.dedup_bam)}`), row);
    const totalAlignments = count(`samtools view -c ${sh(row.dedup_bam)}`);
    const mappedAlignments = count(`samtools view -c -F 4 ${sh(row.dedup_bam)}`);
    const properlyPairedAlignments = count(`samtools view -c -f 2 ${sh(row.dedup_bam)}`);
    const duplicateAlignments = count(`samtools view -c -f 1024 ${sh(row.dedup_bam)}`);
    const brcaIntervalAlignments = count(`samtools view -c -L ${sh(row.brca_interval_bed_path)} ${sh(row.dedup_bam)}`);
    const duplicateMetrics = parseDuplicateMetrics(row.duplicate_metrics_path);
    const status =
      quickcheck(row.dedup_bam) &&
      existsSync(pathFromRoot(row.dedup_bai)) &&
      headerState.sortOrder === "coordinate" &&
      headerState.readGroupPresent &&
      mappedAlignments > 0 &&
      brcaIntervalAlignments > 0
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
      source_read_pairs: row.source_read_pairs,
      raw_bam: row.raw_bam,
      dedup_bam: row.dedup_bam,
      dedup_bai: row.dedup_bai,
      dedup_bam_exists: existsSync(pathFromRoot(row.dedup_bam)) ? "yes" : "no",
      dedup_bai_exists: existsSync(pathFromRoot(row.dedup_bai)) ? "yes" : "no",
      quickcheck: quickcheck(row.dedup_bam) ? "passed" : "failed",
      sort_order: headerState.sortOrder,
      read_group_present: headerState.readGroupPresent ? "yes" : "no",
      read_group_count: headerState.readGroupCount,
      reference_contig_count: headerState.contigs.length,
      total_alignments: totalAlignments,
      mapped_alignments: mappedAlignments,
      mapped_fraction: round(mappedAlignments / totalAlignments, 4),
      properly_paired_alignments: properlyPairedAlignments,
      properly_paired_fraction: round(properlyPairedAlignments / totalAlignments, 4),
      duplicate_alignments: duplicateAlignments,
      duplicate_fraction: round(duplicateAlignments / totalAlignments, 4),
      picard_percent_duplication: duplicateMetrics.PERCENT_DUPLICATION ?? "",
      brca_interval_alignments: brcaIntervalAlignments,
      bam_size_bytes: statSync(pathFromRoot(row.dedup_bam)).size,
      duplicate_metrics_path: row.duplicate_metrics_path,
      status,
      caveat: row.caveat
    });
  }
  const bamStatus = bamRows.every((row) => row.status === "passed") ? "passed" : "failed";
  await writeCsv(pathFromRoot(`${resultsDir}/full_wes_bam_validation.csv`), bamRows);
  await writeJson(pathFromRoot(`${resultsDir}/full_wes_bam_validation.json`), {
    generatedAt: new Date().toISOString(),
    status: bamStatus,
    rows: bamRows
  });
  if (bamStatus !== "passed") {
    throw new Error("Full WES BAM validation failed.");
  }

  const brcaDepth = captureAllowEmpty(`samtools depth -a -b ${sh(tumor.brca_interval_bed_path)} ${sh(tumor.dedup_bam)} ${sh(normal.dedup_bam)}`);
  const brcaDepthSummary = parseDepthSummary(brcaDepth);

  const truthSnvPath = "data/raw/reference/seqc2_hcc1395_truth/latest/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz";
  const truthIndelPath = "data/raw/reference/seqc2_hcc1395_truth/latest/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz";
  const truthVariants = [...loadTruthVariants(truthSnvPath, "snv"), ...loadTruthVariants(truthIndelPath, "indel")];
  writeTruthPositionBed(truthVariants, truthPositionBed);
  const truthDepthText = captureAllowEmpty(`samtools depth -a -b ${sh(truthPositionBed)} ${sh(tumor.dedup_bam)} ${sh(normal.dedup_bam)}`);
  const coveredTruthVariants = pickCoveredTruthVariants(truthVariants, truthDepthText);
  if (coveredTruthVariants.length === 0) {
    throw new Error("No covered truth variants passed the Phase 2F depth threshold.");
  }
  const referenceOrder = readReferenceOrder(tumor.reference_fai_path);
  const benchmarkIntervalRows = writeBenchmarkIntervals(coveredTruthVariants, referenceOrder, benchmarkIntervals);
  await writeCsv(
    pathFromRoot(coveredTruthTsv.replace(/\.tsv$/, ".csv")),
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
  writeFileSync(
    pathFromRoot(coveredTruthTsv),
    [
      "key\ttype\tcontig\tposition\tref\talt\ttumor_depth\tnormal_depth\tmin_depth",
      ...coveredTruthVariants.map((variant) =>
        [
          variant.key,
          variant.type,
          variant.contig,
          variant.position,
          variant.ref,
          variant.alt,
          variant.tumorDepth,
          variant.normalDepth,
          variant.minDepth
        ].join("\t")
      )
    ].join("\n") + "\n"
  );

  ensureDir(pathFromRoot(metricsDir));
  const contaminationInputsReady =
    fileNonEmpty(tumor.common_biallelic_resource_path) &&
    fileNonEmpty(tumor.common_biallelic_resource_index_path) &&
    fileNonEmpty(contaminationIntervals);
  let contaminationStatus = "not_run";
  let contaminationReason = "";
  if (contaminationInputsReady) {
    const tumorPileupResult =
      !force && fileNonEmpty(tumorPileups)
        ? { ok: true, status: 0, stdout: "", stderr: "" }
        : runOptional(
            [
              `${sh(tumor.java_path)} -Xmx8g -jar ${sh(tumor.gatk_jar_path)} GetPileupSummaries`,
              `-R ${sh(tumor.reference_path)}`,
              `-I ${sh(tumor.dedup_bam)}`,
              `-V ${sh(tumor.common_biallelic_resource_path)}`,
              `-L ${sh(contaminationIntervals)}`,
              `-O ${sh(tumorPileups)}`
            ].join(" "),
            `${resultsDir}/logs/${referenceId}.${tumor.run_accession}.tumor.get_pileup_summaries.log`
          );
    const normalPileupResult =
      !force && fileNonEmpty(normalPileups)
        ? { ok: true, status: 0, stdout: "", stderr: "" }
        : runOptional(
            [
              `${sh(normal.java_path)} -Xmx8g -jar ${sh(normal.gatk_jar_path)} GetPileupSummaries`,
              `-R ${sh(normal.reference_path)}`,
              `-I ${sh(normal.dedup_bam)}`,
              `-V ${sh(normal.common_biallelic_resource_path)}`,
              `-L ${sh(contaminationIntervals)}`,
              `-O ${sh(normalPileups)}`
            ].join(" "),
            `${resultsDir}/logs/${referenceId}.${normal.run_accession}.normal.get_pileup_summaries.log`
          );
    if (tumorPileupResult.ok && normalPileupResult.ok && fileNonEmpty(tumorPileups) && fileNonEmpty(normalPileups)) {
      const contaminationResult =
        !force && fileNonEmpty(contaminationTable)
          ? { ok: true, status: 0, stdout: "", stderr: "" }
          : runOptional(
              [
                `${sh(tumor.java_path)} -Xmx8g -jar ${sh(tumor.gatk_jar_path)} CalculateContamination`,
                `-I ${sh(tumorPileups)}`,
                `-matched ${sh(normalPileups)}`,
                `-O ${sh(contaminationTable)}`
              ].join(" "),
              `${resultsDir}/logs/${referenceId}.calculate_contamination.log`
            );
      contaminationStatus = contaminationResult.ok && fileNonEmpty(contaminationTable) ? "passed" : "failed";
      contaminationReason = contaminationResult.ok ? "" : `CalculateContamination exited ${contaminationResult.status}`;
    } else {
      contaminationStatus = "not_assessable";
      contaminationReason = `GetPileupSummaries failed or yielded no table: tumor=${tumorPileupResult.status}, normal=${normalPileupResult.status}`;
    }
  } else {
    contaminationStatus = "not_assessable";
    contaminationReason = "Common-biallelic resource, index, or contamination intervals were unavailable.";
  }
  const contaminationEstimate = parseContaminationTable(contaminationTable);

  ensureDir(pathFromRoot(vcfDir));
  const unfilteredReady = !force && existsSync(pathFromRoot(unfilteredVcf)) && existsSync(pathFromRoot(`${unfilteredVcf}.tbi`));
  const filteredUsedContamination =
    contaminationStatus !== "passed" ||
    (existsSync(pathFromRoot(filterLogPath)) && readText(pathFromRoot(filterLogPath)).includes("--contamination-table"));
  const filteredReady =
    !force && existsSync(pathFromRoot(filteredVcf)) && existsSync(pathFromRoot(`${filteredVcf}.tbi`)) && filteredUsedContamination;
  if (!unfilteredReady) {
    const mutect2Command = [
      `${sh(tumor.java_path)} -Xmx12g -jar ${sh(tumor.gatk_jar_path)} Mutect2`,
      `-R ${sh(tumor.reference_path)}`,
      `-L ${sh(benchmarkIntervals)}`,
      `-I ${sh(tumor.dedup_bam)} -tumor ${sh(tumor.sample)}`,
      `-I ${sh(normal.dedup_bam)} -normal ${sh(normal.sample)}`,
      `--panel-of-normals ${sh(tumor.mutect2_panel_of_normals_path)}`,
      `--native-pair-hmm-threads ${Math.max(1, Math.min(threads, 8))}`,
      `--f1r2-tar-gz ${sh(f1r2Path)}`,
      `-O ${sh(unfilteredVcf)}`
    ].join(" ");
    run(mutect2Command, `${resultsDir}/logs/${referenceId}.full_wes.resource_aware.mutect2.log`);
  }
  if (!filteredReady) {
    const filterCommand = [
      `${sh(tumor.java_path)} -Xmx8g -jar ${sh(tumor.gatk_jar_path)} FilterMutectCalls`,
      `-R ${sh(tumor.reference_path)}`,
      `-V ${sh(unfilteredVcf)}`,
      contaminationStatus === "passed" ? `--contamination-table ${sh(contaminationTable)}` : "",
      `-O ${sh(filteredVcf)}`
    ].filter(Boolean).join(" ");
    run(filterCommand, filterLogPath);
    run(`bcftools index -t -f ${sh(filteredVcf)}`, `${resultsDir}/logs/${referenceId}.full_wes.filtered_vcf_index.log`);
  }
  run(`bcftools stats ${sh(filteredVcf)}`, `${resultsDir}/logs/${referenceId}.full_wes.filtered_vcf_stats.txt`);

  const filteredCalls = variantKeys(filteredVcf, benchmarkIntervals);
  const truthKeys = new Set(coveredTruthVariants.map((variant) => variant.key));
  const passTruthMatches = [...filteredCalls.passKeys].filter((key) => truthKeys.has(key));
  const allTruthMatches = [...filteredCalls.keys].filter((key) => truthKeys.has(key));
  const falsePositivePass = [...filteredCalls.passKeys].filter((key) => !truthKeys.has(key));
  const falseNegativeTruth = [...truthKeys].filter((key) => !filteredCalls.passKeys.has(key));
  const truthSnvCount = coveredTruthVariants.filter((variant) => variant.type === "snv").length;
  const truthIndelCount = coveredTruthVariants.filter((variant) => variant.type === "indel").length;
  const recall = truthKeys.size ? passTruthMatches.length / truthKeys.size : null;
  const precision = filteredCalls.passKeys.size ? passTruthMatches.length / filteredCalls.passKeys.size : null;
  const mutectStatus = existsSync(pathFromRoot(filteredVcf)) && existsSync(pathFromRoot(`${filteredVcf}.tbi`)) ? "passed" : "failed";
  const readyForPhase3 =
    mutectStatus === "passed" &&
    bamStatus === "passed" &&
    fastqRows.length === 4 &&
    contaminationStatus === "passed" &&
    coveredTruthVariants.length > 0;

  const benchmarkRows = [
    {
      status: mutectStatus,
      phase: "2F",
      caller: tumor.production_caller,
      reference_id: referenceId,
      pair_id: tumor.pair_id,
      tumor_sample: tumor.sample,
      normal_sample: normal.sample,
      tumor_run: tumor.run_accession,
      normal_run: normal.run_accession,
      source_tumor_read_pairs: tumor.source_read_pairs,
      source_normal_read_pairs: normal.source_read_pairs,
      duplicate_marking_tool: tumor.duplicate_marking_tool,
      germline_resource: tumor.mutect2_germline_resource_path,
      germline_resource_source_url: tumor.mutect2_germline_resource_source_url,
      panel_of_normals: tumor.mutect2_panel_of_normals_path,
      common_biallelic_resource: tumor.common_biallelic_resource_path,
      bqsr_known_sites_policy: tumor.bqsr_known_sites_policy,
      contamination_policy: tumor.contamination_policy,
      contamination_status: contaminationStatus,
      contamination_table: contaminationStatus === "passed" ? contaminationTable : "",
      contamination_interval_bed_path: contaminationIntervals,
      contamination_estimate: contaminationEstimate.contamination,
      contamination_error: contaminationEstimate.error,
      contamination_reason: contaminationReason,
      benchmark_interval_bed_path: benchmarkIntervals,
      benchmark_interval_count: benchmarkIntervalRows.length,
      truth_variants_total: truthVariants.length,
      truth_variants_depth_eligible: coveredTruthVariants.length,
      truth_snv_depth_eligible: truthSnvCount,
      truth_indel_depth_eligible: truthIndelCount,
      min_truth_depth: minTruthDepth,
      max_truth_variants: maxTruthVariants,
      filtered_vcf: filteredVcf,
      filtered_records_in_benchmark_intervals: filteredCalls.totalCount,
      pass_records_in_benchmark_intervals: filteredCalls.passCount,
      exact_pass_truth_matches: passTruthMatches.length,
      exact_all_filter_truth_matches: allTruthMatches.length,
      false_positive_pass_records: falsePositivePass.length,
      false_negative_truth_records: falseNegativeTruth.length,
      exact_pass_recall: round(recall, 4),
      exact_pass_precision: round(precision, 4),
      brca_tumor_mean_depth: brcaDepthSummary.tumorMeanDepth,
      brca_normal_mean_depth: brcaDepthSummary.normalMeanDepth,
      brca_fraction_both_depth_at_least_10: brcaDepthSummary.fractionBothDepthAtLeast10,
      boundary:
        "Full WES FASTQs and resource-aware Mutect2 were run on covered SEQC2 truth-overlap intervals. This is full-depth WES small-variant benchmark evidence, not WGS HRD signature, CNV, or SV evidence."
    }
  ];

  await writeCsv(pathFromRoot(`${resultsDir}/truth_overlap_benchmark_summary.csv`), benchmarkRows);
  await writeJson(pathFromRoot(`${resultsDir}/truth_overlap_benchmark_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: mutectStatus,
    rows: benchmarkRows,
    truthMatchExamples: passTruthMatches.slice(0, 20),
    falsePositiveExamples: falsePositivePass.slice(0, 20),
    falseNegativeExamples: falseNegativeTruth.slice(0, 20)
  });
  await writeJson(pathFromRoot(`${resultsDir}/tool_versions.json`), {
    generatedAt: new Date().toISOString(),
    bwa: { path: capture("command -v bwa"), version: toolVersion("bwa") },
    samtools: { path: capture("command -v samtools"), version: toolVersion("samtools") },
    bcftools: { path: capture("command -v bcftools"), version: toolVersion("bcftools") },
    java: { path: tumor.java_path, version: capture(`${sh(tumor.java_path)} -version 2>&1 | head -n 1`) },
    gatk: { jarPath: tumor.gatk_jar_path, version: capture(`${sh(tumor.java_path)} -jar ${sh(tumor.gatk_jar_path)} --version 2>&1 | head -n 1`) }
  });
  await writeJson(pathFromRoot(`${resultsDir}/full_wes_benchmark_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: mutectStatus,
    phase: "2F",
    caller: tumor.production_caller,
    referenceId,
    pairId: tumor.pair_id,
    tumorRun: tumor.run_accession,
    normalRun: normal.run_accession,
    fullWesFastqsValidated: fastqRows.length,
    bamValidationStatus: bamStatus,
    benchmarkIntervalCount: benchmarkIntervalRows.length,
    truthVariantsDepthEligible: coveredTruthVariants.length,
    passRecordsInBenchmarkIntervals: filteredCalls.passCount,
    exactPassTruthMatches: passTruthMatches.length,
    exactPassRecall: round(recall, 4),
    exactPassPrecision: round(precision, 4),
    contaminationStatus,
    contaminationTable: contaminationStatus === "passed" ? contaminationTable : "",
    contaminationIntervalBedPath: contaminationIntervals,
    contaminationEstimate: contaminationEstimate.contamination,
    bqsrKnownSitesPolicy: tumor.bqsr_known_sites_policy,
    contaminationPolicy: tumor.contamination_policy,
    readyForPhase3: readyForPhase3 && String(benchmarkRows[0].boundary).includes("not WGS HRD signature"),
    boundary:
      "Phase 2F closes raw WES readiness with full FASTQ download, full-reference alignment, duplicate marking, resource-aware Mutect2, and bounded SEQC2 truth comparison. Phase 3 starts WGS HRD signature/CNV/SV capability."
  });
  await writeCsv(pathFromRoot(`${resultsDir}/full_wes_benchmark_summary.csv`), [
    {
      status: mutectStatus,
      phase: "2F",
      caller: tumor.production_caller,
      reference_id: referenceId,
      full_wes_fastqs_validated: fastqRows.length,
      bam_validation_status: bamStatus,
      benchmark_interval_count: benchmarkIntervalRows.length,
      truth_variants_depth_eligible: coveredTruthVariants.length,
      pass_records_in_benchmark_intervals: filteredCalls.passCount,
      exact_pass_truth_matches: passTruthMatches.length,
      exact_pass_recall: round(recall, 4),
      exact_pass_precision: round(precision, 4),
      contamination_status: contaminationStatus,
      contamination_table: contaminationStatus === "passed" ? contaminationTable : "",
      contamination_interval_bed_path: contaminationIntervals,
      contamination_estimate: contaminationEstimate.contamination,
      ready_for_phase3: readyForPhase3 ? "yes" : "no",
      boundary: "Full-depth WES small-variant benchmark complete; WGS HRD signature/CNV/SV evidence remains Phase 3."
    }
  ]);
  await writeText(
    pathFromRoot(`${resultsDir}/README.md`),
    `# Full WES Benchmark

Status: **${mutectStatus}**.

Phase 2F caller path: \`${tumor.production_caller}\`

Reference: \`${referenceId}\` (${tumor.genome_build}/${tumor.assembly})

Input: full ENA FASTQ gzip files for SEQC2/HCC1395 WES tumor-normal pair.

What this validates:

1. Full WES FASTQ downloads match source MD5 and byte counts.
2. Full WES tumor and matched normal reads align to the full hg38 analysis-set reference.
3. BAMs are coordinate-sorted, duplicate-marked, indexed, read-grouped, and pass \`samtools quickcheck\`.
4. Mutect2 runs with the Broad hg38 1000g panel of normals; the full af-only gnomAD resource is documented as a production-scale input.
5. GetPileupSummaries and CalculateContamination run with the common-biallelic gnomAD resource inside the bounded BRCA interval set.
6. The filtered VCF is indexed and compared to SEQC2 high-confidence truth variants inside covered benchmark intervals.
7. The output separates full-depth WES small-variant readiness from WGS HRD signature/CNV/SV readiness.

Benchmark interval count: \`${benchmarkIntervalRows.length}\`

Depth-eligible truth variants: \`${coveredTruthVariants.length}\`

PASS truth matches: \`${passTruthMatches.length}\`

Exact PASS recall: \`${round(recall, 4)}\`

Exact PASS precision: \`${round(precision, 4)}\`

Contamination status: \`${contaminationStatus}\`

Contamination estimate: \`${contaminationEstimate.contamination || "not_available"}\`

Deferred production policies:

1. BQSR is documented but not run until matching known-sites and capture intervals are selected.
2. The full Broad af-only gnomAD germline resource is documented but not downloaded into the local Phase 2F gate because the canonical file is multi-GB.
3. Capture-interval behavior is inferred from full WES coverage and SEQC2 truth-overlap intervals, not from a vendor BED.

Boundary: this closes Phase 2 raw WES readiness; Phase 3 is WGS HRD signature, CNV, and SV capability.
`
  );

  if (!readyForPhase3) {
    throw new Error("Full WES benchmark failed the Phase 2F ready-for-Phase-3 gate.");
  }

  console.log(
    `Full WES benchmark ${mutectStatus}: ${coveredTruthVariants.length} depth-eligible truth variants, ${passTruthMatches.length} exact PASS truth matches.`
  );
}

await main();
