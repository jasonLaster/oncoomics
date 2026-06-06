import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureDir, groupBy, parseCsv, pathFromRoot, readText, round, writeCsv, writeJson, writeText } from "./lib";

type HumanReferenceSampleRow = {
  pair_id: string;
  patient: string;
  sample: string;
  role: string;
  status: string;
  assay: string;
  run_accession: string;
  fastq_1: string;
  fastq_2: string;
  reference_id: string;
  assembly: string;
  genome_build: string;
  chromosomes: string;
  genes_covered: string;
  reference_path: string;
  reference_sha256: string;
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

const resultsDir = "results/human_reference_smoke";

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

function sha256File(relativePath: string) {
  return createHash("sha256").update(readFileSync(pathFromRoot(relativePath))).digest("hex");
}

function toolVersion(tool: "bwa" | "samtools") {
  const output = spawnSync("bash", ["-lc", `${tool} 2>&1 | head -n 6`], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024
  });
  return `${output.stdout}${output.stderr}`.trim();
}

function readGroup(row: HumanReferenceSampleRow) {
  return [
    "@RG",
    `ID:${row.read_group_id}`,
    `SM:${row.read_group_sample}`,
    `LB:${row.read_group_library}`,
    `PL:${row.read_group_platform}`,
    `PU:${row.read_group_platform_unit}`
  ].join("\\t");
}

function ensureBwaIndex(referencePath: string, referenceId: string) {
  const rootReference = pathFromRoot(referencePath);
  if (existsSync(`${rootReference}.bwt`)) {
    return false;
  }
  run(`bwa index ${sh(referencePath)}`, `${resultsDir}/logs/${referenceId}.bwa_index.log`);
  return true;
}

function parseHeader(header: string, row: HumanReferenceSampleRow) {
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
  return Number(capture(command));
}

function parseIdxstats(text: string) {
  const rows = text.split(/\r?\n/).filter(Boolean).map((line) => {
    const [contig, length, mapped, unmapped] = line.split("\t");
    return {
      contig,
      length: Number(length),
      mapped: Number(mapped),
      unmapped: Number(unmapped)
    };
  });
  return rows;
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));

  const rows = parseCsv(readText(pathFromRoot("manifests/human_reference_smoke_samplesheet.csv"))) as HumanReferenceSampleRow[];
  if (rows.length < 4) {
    throw new Error("Expected at least four human-reference smoke sample rows: two samples across two references.");
  }

  const validationRows: Record<string, unknown>[] = [];
  const indexedReferences = new Set<string>();

  for (const row of rows) {
    const observedReferenceSha256 = sha256File(row.reference_path);
    if (observedReferenceSha256 !== row.reference_sha256) {
      throw new Error(`${row.reference_id} sha256 mismatch: expected ${row.reference_sha256}, observed ${observedReferenceSha256}.`);
    }
    if (!indexedReferences.has(row.reference_id)) {
      ensureBwaIndex(row.reference_path, row.reference_id);
      indexedReferences.add(row.reference_id);
    }

    ensureDir(pathFromRoot(row.output_bam.split("/").slice(0, -1).join("/")));
    const threads = Number(row.aligner_threads) || 2;
    const alignCommand = `set -o pipefail; ${[
      `bwa mem -t ${threads} -R ${sh(readGroup(row))} ${sh(row.reference_path)} ${sh(row.fastq_1)} ${sh(row.fastq_2)}`,
      `samtools sort -@ ${threads} -o ${sh(row.output_bam)} -`
    ].join(" | ")}`;
    run(alignCommand, `${resultsDir}/logs/${row.reference_id}.${row.run_accession}.align.log`);
    run(`samtools index ${sh(row.output_bam)}`, `${resultsDir}/logs/${row.reference_id}.${row.run_accession}.index.log`);
    run(`samtools flagstat ${sh(row.output_bam)}`, `${resultsDir}/logs/${row.reference_id}.${row.run_accession}.flagstat.txt`);
    run(`samtools stats ${sh(row.output_bam)}`, `${resultsDir}/logs/${row.reference_id}.${row.run_accession}.stats.txt`);

    const quickcheck = spawnSync("samtools", ["quickcheck", "-v", pathFromRoot(row.output_bam)], {
      encoding: "utf8",
      maxBuffer: 1024 * 1024
    });
    const headerState = parseHeader(capture(`samtools view -H ${sh(row.output_bam)}`), row);
    const totalAlignments = count(`samtools view -c ${sh(row.output_bam)}`);
    const mappedAlignments = count(`samtools view -c -F 4 ${sh(row.output_bam)}`);
    const properlyPairedAlignments = count(`samtools view -c -f 2 ${sh(row.output_bam)}`);
    const idxstatsRows = parseIdxstats(capture(`samtools idxstats ${sh(row.output_bam)}`));
    const expectedContigs = row.chromosomes.split(";").filter(Boolean);
    const contigChecks = expectedContigs.map((contig) => ({
      contig,
      present: headerState.contigs.includes(contig),
      mapped: idxstatsRows.find((idx) => idx.contig === contig)?.mapped ?? 0
    }));
    const mappedByContig = contigChecks.map((check) => `${check.contig}:${check.mapped}`).join(";");
    const expectedContigsPresent = contigChecks.every((check) => check.present);
    const bamExists = existsSync(pathFromRoot(row.output_bam));
    const baiExists = existsSync(pathFromRoot(row.output_bai));
    const status =
      quickcheck.status === 0 &&
      bamExists &&
      baiExists &&
      headerState.sortOrder === "coordinate" &&
      headerState.readGroupPresent &&
      expectedContigsPresent &&
      totalAlignments > 0 &&
      mappedAlignments > 0
        ? "passed"
        : "failed";

    validationRows.push({
      pair_id: row.pair_id,
      reference_id: row.reference_id,
      assembly: row.assembly,
      genome_build: row.genome_build,
      chromosomes: row.chromosomes,
      genes_covered: row.genes_covered,
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
      expected_contigs_present: expectedContigsPresent ? "yes" : "no",
      reference_contigs: headerState.contigs.join(";"),
      total_alignments: totalAlignments,
      mapped_alignments: mappedAlignments,
      mapped_fraction: round(mappedAlignments / totalAlignments, 4),
      properly_paired_alignments: properlyPairedAlignments,
      properly_paired_fraction: round(properlyPairedAlignments / totalAlignments, 4),
      mapped_by_contig: mappedByContig,
      bam_size_bytes: bamExists ? statSync(pathFromRoot(row.output_bam)).size : "",
      status,
      caveat: row.caveat
    });
  }

  const comparisons = Array.from(groupBy(validationRows, (row) => String(row.run_accession)).entries()).map(([run, runRows]) => {
    const passedBuilds = runRows.filter((row) => row.status === "passed").map((row) => String(row.assembly)).sort();
    return {
      run_accession: run,
      sample: runRows[0]?.sample ?? "",
      role: runRows[0]?.role ?? "",
      tested_builds: runRows.map((row) => row.assembly).sort().join(";"),
      passed_builds: passedBuilds.join(";"),
      mapped_alignment_range: `${Math.min(...runRows.map((row) => Number(row.mapped_alignments)))}-${Math.max(
        ...runRows.map((row) => Number(row.mapped_alignments))
      )}`,
      status: passedBuilds.includes("hg19") && passedBuilds.includes("hg38") ? "passed" : "failed",
      caveat: "Build comparison validates that the same HCC1395 FASTQ subset can align to two partial human references; it is not build-liftover validation."
    };
  });

  const status =
    validationRows.every((row) => row.status === "passed") && comparisons.every((row) => row.status === "passed")
      ? "passed"
      : "failed";

  await writeCsv(pathFromRoot(`${resultsDir}/bam_validation_summary.csv`), validationRows);
  await writeJson(pathFromRoot(`${resultsDir}/bam_validation_summary.json`), {
    generatedAt: new Date().toISOString(),
    status,
    rows: validationRows
  });
  await writeCsv(pathFromRoot(`${resultsDir}/reference_comparison_summary.csv`), comparisons);
  await writeJson(pathFromRoot(`${resultsDir}/reference_comparison_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: comparisons.every((row) => row.status === "passed") ? "passed" : "failed",
    comparisons
  });
  await writeJson(pathFromRoot(`${resultsDir}/tool_versions.json`), {
    generatedAt: new Date().toISOString(),
    bwa: { path: capture("command -v bwa"), version: toolVersion("bwa") },
    samtools: { path: capture("command -v samtools"), version: toolVersion("samtools") }
  });
  await writeJson(pathFromRoot(`${resultsDir}/human_reference_alignment_summary.json`), {
    generatedAt: new Date().toISOString(),
    status,
    sampleRows: validationRows.length,
    references: Array.from(new Set(validationRows.map((row) => row.reference_id))),
    assemblies: Array.from(new Set(validationRows.map((row) => row.assembly))),
    genomeBuilds: Array.from(new Set(validationRows.map((row) => row.genome_build))),
    tumorRows: validationRows.filter((row) => row.role === "tumor").length,
    normalRows: validationRows.filter((row) => row.role === "normal").length,
    boundary:
      "Phase 2C validates partial real-human-reference alignment across hg38 and hg19 chr13/chr17. It does not validate full-depth WES/WGS performance, target capture intervals, somatic calling, CNV/SV calling, or HRD signatures."
  });
  await writeCsv(pathFromRoot(`${resultsDir}/human_reference_alignment_summary.csv`), [
    {
      status,
      sample_rows: validationRows.length,
      references: Array.from(new Set(validationRows.map((row) => row.reference_id))).join(";"),
      assemblies: Array.from(new Set(validationRows.map((row) => row.assembly))).join(";"),
      genome_builds: Array.from(new Set(validationRows.map((row) => row.genome_build))).join(";"),
      tumor_rows: validationRows.filter((row) => row.role === "tumor").length,
      normal_rows: validationRows.filter((row) => row.role === "normal").length,
      boundary:
        "Partial hg38/hg19 chr13/chr17 human-reference smoke only; not full-depth WES/WGS, somatic calling, or HRD evidence."
    }
  ]);
  await writeText(
    pathFromRoot(`${resultsDir}/README.md`),
    `# Human-Reference Smoke Test

Status: **${status}**.

Smoke pair: \`seqc2_hcc1395_wes_minimal_smoke\`

Input: Phase 2A local SEQC2/HCC1395 FASTQ subset.

References:

1. \`ucsc_hg38_chr13_chr17\` / GRCh38 / hg38 / chr13 + chr17.
2. \`ucsc_hg19_chr13_chr17\` / GRCh37 / hg19 / chr13 + chr17.

Why these chromosomes:

1. chr13 contains BRCA2.
2. chr17 contains BRCA1.
3. Two real reference builds validate build-specific samplesheet and BAM-contract handling without requiring a full local genome bundle.

What this validates:

1. Real UCSC human-reference FASTA download and checksum validation.
2. FASTA indexing with \`samtools faidx\`.
3. BWA indexing for multiple reference builds.
4. Tumor and normal FASTQ alignment to hg38 and hg19 partial references.
5. Coordinate-sorted/indexed BAMs with read groups and mapped reads.
6. Shared reference-hash tracking in the samplesheet and result summaries.

What this does not validate yet:

1. Full GRCh37/GRCh38/hs37d5 genome bundles.
2. Capture intervals and known-sites resources.
3. Full-depth WES/WGS runtime, coverage, or storage behavior.
4. Somatic SNV/indel, CNV, or SV calling.
5. scarHRD/CHORD/HRDetect/SBS3 evidence.

Boundary: this is a real-human-reference alignment smoke for plumbing and reference-build validation, not a biological HRD result.
`
  );

  if (status !== "passed") {
    throw new Error("Human-reference smoke failed. See results/human_reference_smoke/.");
  }

  console.log(`Human-reference smoke ${status} for ${validationRows.length} BAM validations across ${comparisons.length} samples.`);
}

await main();
