import { createInterface } from "node:readline";
import { createReadStream, createWriteStream, existsSync, statSync } from "node:fs";
import { dirname } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { ensureDir, parseCsv, pathFromRoot, readText, round, writeCsv, writeJson, writeText } from "./lib";

type RawPanelRow = {
  pair_id: string;
  role: string;
  run: string;
  assay: string;
  library_strategy: string;
  library_layout: string;
  sample_name: string;
  platform: string;
  model: string;
  spots: string;
  bases: string;
  fastq_1_url: string;
  fastq_2_url: string;
  fastq_1_md5: string;
  fastq_2_md5: string;
  fastq_1_bytes: string;
  fastq_2_bytes: string;
  use_case: string;
  caveat: string;
};

type FullReferenceRow = {
  reference_id: string;
  assembly: string;
  genome_build: string;
  fasta_path: string;
  fasta_fai_path: string;
  fasta_sha256: string;
  interval_bed_path: string;
  interval_regions: string;
  interval_genes: string;
};

type FullWesRow = {
  gatk_jar_path: string;
  java_path: string;
  mutect2_panel_of_normals_path: string;
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
  source: "existing" | "streamed";
};

const pairId = process.env.PHASE3_WGS_PAIR_ID ?? "seqc2_hcc1395_wgs_hiseqx_full";
const readPairsPerEnd = Number(process.env.PHASE3_WGS_READS ?? "500000");
const fetchConcurrency = Math.max(1, Number(process.env.PHASE3_WGS_FETCH_CONCURRENCY ?? "2"));
const resultsDir = "results/phase3_wgs_smoke";
const smokeRoot = "data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full";
const seqc2TruthRoot = "data/raw/reference/seqc2_hcc1395_truth/latest";

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

async function summarizeFastq(
  runAccession: string,
  read: "R1" | "R2",
  sourceUrl: string,
  outputPath: string,
  source: "existing" | "streamed"
): Promise<FastqStats> {
  const rl = createInterface({ input: createReadStream(outputPath) });
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

  for await (const line of rl) {
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
  }

  if (current.length !== 0) {
    throw new Error(`${runAccession} ${read} ended mid-record`);
  }
  if (records !== readPairsPerEnd) {
    throw new Error(`${runAccession} ${read} has ${records} records; expected ${readPairsPerEnd}`);
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
    ids,
    source
  };
}

async function streamFastqSubset(
  runAccession: string,
  read: "R1" | "R2",
  sourceUrl: string,
  outputPath: string
): Promise<FastqStats> {
  ensureDir(dirname(outputPath));
  if (existsSync(outputPath) && statSync(outputPath).size > 0) {
    return summarizeFastq(runAccession, read, sourceUrl, outputPath, "existing");
  }

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
    if (records >= readPairsPerEnd) {
      await finish();
      break;
    }
  }

  await finish();

  if (records !== readPairsPerEnd) {
    throw new Error(`${runAccession} ${read} produced ${records} records; expected ${readPairsPerEnd}`);
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
    ids,
    source: "streamed"
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

function commandPath(tool: string) {
  const result = spawnSync("bash", ["-lc", `command -v ${tool}`], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
}

function javaWorks(candidate: string) {
  if (!candidate || !existsSync(candidate)) {
    return false;
  }
  const result = spawnSync(candidate, ["-version"], { encoding: "utf8" });
  const output = `${result.stdout}${result.stderr}`;
  const major = Number(output.match(/version "(\d+)/)?.[1] ?? "0");
  return result.status === 0 && major >= 17;
}

function findJava(fallback?: string) {
  const candidates = [
    process.env.GATK_JAVA ?? "",
    fallback ?? "",
    "/opt/homebrew/opt/openjdk@17/bin/java",
    "/opt/homebrew/bin/java",
    commandPath("java")
  ];
  const java = candidates.find(javaWorks);
  if (!java) {
    throw new Error("Phase 3 WGS smoke requires Java 17+ for GATK. Install openjdk@17 or set GATK_JAVA.");
  }
  return java;
}

async function mapLimit<T, R>(items: T[], concurrency: number, mapper: (item: T) => Promise<R>) {
  const results: R[] = [];
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await mapper(items[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker));
  return results;
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));

  const rawPanel = parseCsv(readText(pathFromRoot("manifests/raw_representative_panel.csv"))) as RawPanelRow[];
  const selected = rawPanel
    .filter((row) => row.pair_id === pairId)
    .sort((a, b) => (a.role === "tumor" ? -1 : 1) - (b.role === "tumor" ? -1 : 1));
  if (selected.length !== 2 || !selected.some((row) => row.role === "tumor") || !selected.some((row) => row.role === "normal")) {
    throw new Error(`Expected tumor and normal raw panel rows for ${pairId}.`);
  }

  const references = parseCsv(readText(pathFromRoot("manifests/full_reference_smoke_references.csv"))) as FullReferenceRow[];
  const reference = references.find((row) => row.reference_id === "ucsc_hg38_analysis_set_full");
  if (!reference) {
    throw new Error("Expected ucsc_hg38_analysis_set_full in manifests/full_reference_smoke_references.csv.");
  }
  for (const path of [reference.fasta_path, reference.fasta_fai_path, reference.interval_bed_path]) {
    if (!existsSync(pathFromRoot(path))) {
      throw new Error(`Required Phase 3 WGS reference asset is missing: ${path}`);
    }
  }

  const fullWesRows = existsSync(pathFromRoot("manifests/full_wes_benchmark_samplesheet.csv"))
    ? (parseCsv(readText(pathFromRoot("manifests/full_wes_benchmark_samplesheet.csv"))) as FullWesRow[])
    : [];
  const fullWesResourceRow = fullWesRows[0];
  const javaPath = findJava(fullWesResourceRow?.java_path);
  const gatkJar = fullWesResourceRow?.gatk_jar_path || "data/raw/tools/gatk/gatk-4.6.2.0/gatk-package-4.6.2.0-local.jar";
  if (!existsSync(pathFromRoot(gatkJar))) {
    throw new Error(`GATK jar is missing: ${gatkJar}. Run fetch:production-somatic or fetch:full-wes first.`);
  }

  const truthSnvPath = `${seqc2TruthRoot}/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz`;
  const truthIndelPath = `${seqc2TruthRoot}/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz`;
  const truthHighConfidenceBedPath = `${seqc2TruthRoot}/High-Confidence_Regions_v1.2.bed`;
  for (const path of [truthSnvPath, truthIndelPath, truthHighConfidenceBedPath]) {
    if (!existsSync(pathFromRoot(path))) {
      throw new Error(`SEQC2 truth asset is missing: ${path}. Run fetch:production-somatic first.`);
    }
  }

  const sampleRows = selected.map((row) => {
    const sampleName = row.role === "tumor" ? "HCC1395" : "HCC1395BL";
    return {
      pair_id: row.pair_id,
      patient: "HCC1395",
      sample: sampleName,
      role: row.role,
      status: row.role === "tumor" ? "tumor" : "matched_normal",
      run_accession: row.run,
      assay: row.assay,
      library_strategy: row.library_strategy,
      library_layout: row.library_layout,
      platform: row.platform,
      model: row.model,
      source_read_pairs: row.spots,
      source_bases: row.bases,
      source_fastq_1: row.fastq_1_url,
      source_fastq_2: row.fastq_2_url,
      source_fastq_1_md5: row.fastq_1_md5,
      source_fastq_2_md5: row.fastq_2_md5,
      source_fastq_1_bytes: row.fastq_1_bytes,
      source_fastq_2_bytes: row.fastq_2_bytes,
      read_pairs_per_end: readPairsPerEnd,
      fastq_1: `${smokeRoot}/fastq/${row.run}_R1.${readPairsPerEnd}reads.fastq`,
      fastq_2: `${smokeRoot}/fastq/${row.run}_R2.${readPairsPerEnd}reads.fastq`,
      reference_id: reference.reference_id,
      assembly: reference.assembly,
      genome_build: reference.genome_build,
      reference_path: reference.fasta_path,
      reference_fai_path: reference.fasta_fai_path,
      reference_dict_path: reference.fasta_path.replace(/\.(fa|fasta)$/i, ".dict"),
      reference_sha256: reference.fasta_sha256,
      brca_interval_bed_path: reference.interval_bed_path,
      brca_interval_regions: reference.interval_regions,
      brca_interval_genes: reference.interval_genes,
      truth_snv_vcf_path: truthSnvPath,
      truth_indel_vcf_path: truthIndelPath,
      truth_high_confidence_bed_path: truthHighConfidenceBedPath,
      gatk_jar_path: gatkJar,
      java_path: javaPath,
      mutect2_panel_of_normals_path: fullWesResourceRow?.mutect2_panel_of_normals_path ?? "",
      production_caller: "GATK Mutect2 + FilterMutectCalls",
      read_group_id: `${row.run}.${row.role}.phase3wgs`,
      read_group_sample: sampleName,
      read_group_library: row.run,
      read_group_platform: "ILLUMINA",
      read_group_platform_unit: row.run,
      output_bam: `${smokeRoot}/${reference.reference_id}/bam/${row.run}.${row.role}.bam`,
      output_bai: `${smokeRoot}/${reference.reference_id}/bam/${row.run}.${row.role}.bam.bai`,
      caller_interval_strategy: "covered SEQC2 WGS truth loci from tumor and normal downsampled BAM depth, fallback to mapped-read intervals if needed",
      cnv_strategy: "samtools bedcov over fixed-width standard-contig bins with tumor/normal log2 coverage ratios",
      sv_strategy: "samtools split-read, supplementary-read, discordant-pair, and interchromosomal-pair evidence counts",
      signature_strategy: "local SBS96 mutation matrix from actual filtered WGS smoke VCF records; signature classification deferred unless mutation count is sufficient",
      caveat:
        "Phase 3 WGS smoke uses a real WGS FASTQ subset from the full SEQC2/HCC1395 HiSeq X pair. It validates WGS-capable mechanics, not full-depth WGS HRD sensitivity or a clinical Diana interpretation."
    };
  });

  const tasks = sampleRows.flatMap((row) => [
    { row, read: "R1" as const, sourceUrl: row.source_fastq_1, outputPath: pathFromRoot(row.fastq_1) },
    { row, read: "R2" as const, sourceUrl: row.source_fastq_2, outputPath: pathFromRoot(row.fastq_2) }
  ]);
  const fastqStats = await mapLimit(tasks, fetchConcurrency, (task) =>
    streamFastqSubset(task.row.run_accession, task.read, task.sourceUrl, task.outputPath)
  );

  for (const row of sampleRows) {
    const r1 = fastqStats.find((stat) => stat.run === row.run_accession && stat.read === "R1") as FastqStats;
    const r2 = fastqStats.find((stat) => stat.run === row.run_accession && stat.read === "R2") as FastqStats;
    assertPaired(r1, r2);
  }

  const fastqRows = sampleRows.map((row) => {
    const r1 = fastqStats.find((stat) => stat.run === row.run_accession && stat.read === "R1") as FastqStats;
    const r2 = fastqStats.find((stat) => stat.run === row.run_accession && stat.read === "R2") as FastqStats;
    return {
      pair_id: row.pair_id,
      sample: row.sample,
      role: row.role,
      run_accession: row.run_accession,
      assay: row.assay,
      source_read_pairs: row.source_read_pairs,
      reads_per_end: r1.records,
      local_fastq_1: row.fastq_1,
      local_fastq_2: row.fastq_2,
      r1_mean_length: round(r1.meanLength, 2),
      r2_mean_length: round(r2.meanLength, 2),
      r1_gc_fraction: round(r1.gcFraction, 4),
      r2_gc_fraction: round(r2.gcFraction, 4),
      r1_n_fraction: round(r1.nFraction, 6),
      r2_n_fraction: round(r2.nFraction, 6),
      first_read_id: r1.firstReadId,
      last_read_id: r1.lastReadId,
      paired_id_check: "passed",
      fetch_state: `${r1.source}/${r2.source}`,
      caveat: "Downsampled real WGS FASTQ subset for Phase 3 WGS-capable HRD lane validation."
    };
  });

  await writeCsv(pathFromRoot("manifests/phase3_wgs_smoke_samplesheet.csv"), sampleRows);
  await writeCsv(pathFromRoot(`${resultsDir}/fastq_summary.csv`), fastqRows);
  await writeJson(pathFromRoot(`${resultsDir}/fastq_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "passed",
    pairId,
    readPairsPerEnd,
    fetchConcurrency,
    rows: fastqRows
  });
  await writeJson(pathFromRoot(`${resultsDir}/asset_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "ready",
    phase: "3",
    pairId,
    readPairsPerEnd,
    sampleRows: sampleRows.length,
    source: "SEQC2/HCC1395 public HiSeq X Ten WGS tumor-normal FASTQ pair",
    reference: {
      referenceId: reference.reference_id,
      assembly: reference.assembly,
      genomeBuild: reference.genome_build,
      fastaPath: reference.fasta_path,
      faiPath: reference.fasta_fai_path,
      dictPath: reference.fasta_path.replace(/\.(fa|fasta)$/i, ".dict")
    },
    gatk: {
      jarPath: gatkJar,
      javaPath
    },
    seqc2Truth: {
      snvVcfPath: truthSnvPath,
      indelVcfPath: truthIndelPath,
      highConfidenceBedPath: truthHighConfidenceBedPath
    },
    parallelism: {
      fetchConcurrency,
      note: "FASTQ end streams can be fetched concurrently; alignment/runtime thread controls live in smoke:phase3-wgs."
    },
    boundary:
      "This prepares a bounded WGS smoke subset from full public WGS FASTQs. It does not download the complete 198 GB compressed HiSeq X tumor-normal WGS pair."
  });
  await writeText(
    pathFromRoot(`${resultsDir}/README.md`),
    `# Phase 3 WGS Smoke Assets

Status: **ready**.

Representative pair: \`${pairId}\`

Reads per FASTQ end: \`${readPairsPerEnd}\`

This stage streams a bounded subset from the full public SEQC2/HCC1395 HiSeq X Ten WGS tumor-normal FASTQ pair. It validates real WGS FASTQ access and pairing while keeping the local Phase 3 run tractable.

Boundary: this is a WGS-capable smoke subset, not the complete compressed WGS pair and not a clinical HRD result.
`
  );

  console.log(`Phase 3 WGS smoke assets ready: ${sampleRows.length} samples, ${readPairsPerEnd} read pairs/end.`);
}

await main();
