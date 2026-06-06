import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureDir, parseCsv, pathFromRoot, readText, round, writeCsv, writeJson, writeText } from "./lib";

type FullReferenceSampleRow = {
  pair_id: string;
  sample: string;
  role: string;
  run_accession: string;
  fastq_1: string;
  fastq_2: string;
  reference_id: string;
  assembly: string;
  genome_build: string;
  reference_path: string;
  reference_sha256: string;
  interval_bed_path: string;
  interval_regions: string;
  interval_genes: string;
  aligner_threads: string;
  read_group_id: string;
  read_group_sample: string;
  read_group_library: string;
  read_group_platform: string;
  read_group_platform_unit: string;
  output_bam: string;
  output_bai: string;
  caller_ready_scope: string;
  caveat: string;
};

const resultsDir = "results/full_reference_smoke";

function sh(value: string) {
  return `'${value.replaceAll("'", "'\"'\"'")}'`;
}

function run(command: string, logPath: string) {
  const result = spawnSync("bash", ["-lc", command], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 50
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
    maxBuffer: 1024 * 1024 * 50
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command}\n${result.stderr}`);
  }
  return result.stdout.trim();
}

function sha256File(relativePath: string) {
  return createHash("sha256").update(readFileSync(pathFromRoot(relativePath))).digest("hex");
}

function toolVersion(tool: "bwa" | "samtools" | "bcftools") {
  const output = spawnSync("bash", ["-lc", `${tool} 2>&1 | head -n 8`], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024
  });
  return `${output.stdout}${output.stderr}`.trim();
}

function readGroup(row: FullReferenceSampleRow) {
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

function parseHeader(header: string, row: FullReferenceSampleRow) {
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
  return text.split(/\r?\n/).filter(Boolean).map((line) => {
    const [contig, length, mapped, unmapped] = line.split("\t");
    return { contig, length: Number(length), mapped: Number(mapped), unmapped: Number(unmapped) };
  });
}

function parseVcfStats(text: string) {
  const rows = text.split(/\r?\n/).filter((line) => line.startsWith("SN"));
  const get = (label: string) => {
    const row = rows.find((line) => line.includes(label));
    return Number(row?.split("\t").at(-1) ?? 0);
  };
  return {
    records: get("number of records:"),
    snps: get("number of SNPs:"),
    indels: get("number of indels:")
  };
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));

  const rows = parseCsv(readText(pathFromRoot("manifests/full_reference_smoke_samplesheet.csv"))) as FullReferenceSampleRow[];
  if (rows.length !== 2 || !rows.some((row) => row.role === "tumor") || !rows.some((row) => row.role === "normal")) {
    throw new Error("Expected tumor and normal rows in manifests/full_reference_smoke_samplesheet.csv.");
  }

  const referenceId = rows[0].reference_id;
  const referencePath = rows[0].reference_path;
  const referenceSha256 = sha256File(referencePath);
  for (const row of rows) {
    if (row.reference_path !== referencePath || row.reference_sha256 !== referenceSha256) {
      throw new Error(`Full-reference samplesheet has inconsistent reference state for ${row.run_accession}.`);
    }
  }
  const indexedReference = ensureBwaIndex(referencePath, referenceId);

  const validationRows: Record<string, unknown>[] = [];
  for (const row of rows) {
    ensureDir(pathFromRoot(row.output_bam.split("/").slice(0, -1).join("/")));
    const threads = Number(row.aligner_threads) || 4;
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
    const idxstatsRows = parseIdxstats(capture(`samtools idxstats ${sh(row.output_bam)}`));
    const totalAlignments = count(`samtools view -c ${sh(row.output_bam)}`);
    const mappedAlignments = count(`samtools view -c -F 4 ${sh(row.output_bam)}`);
    const intervalAlignments = count(`samtools view -c -L ${sh(row.interval_bed_path)} ${sh(row.output_bam)}`);
    const properlyPairedAlignments = count(`samtools view -c -f 2 ${sh(row.output_bam)}`);
    const chr13Mapped = idxstatsRows.find((idx) => idx.contig === "chr13")?.mapped ?? 0;
    const chr17Mapped = idxstatsRows.find((idx) => idx.contig === "chr17")?.mapped ?? 0;
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

    validationRows.push({
      pair_id: row.pair_id,
      reference_id: row.reference_id,
      assembly: row.assembly,
      genome_build: row.genome_build,
      role: row.role,
      run_accession: row.run_accession,
      sample: row.sample,
      reference_sha256: row.reference_sha256,
      interval_bed_path: row.interval_bed_path,
      interval_regions: row.interval_regions,
      interval_genes: row.interval_genes,
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
      interval_alignments: intervalAlignments,
      mapped_by_key_contig: `chr13:${chr13Mapped};chr17:${chr17Mapped}`,
      bam_size_bytes: bamExists ? statSync(pathFromRoot(row.output_bam)).size : "",
      caller_ready_scope: row.caller_ready_scope,
      status,
      caveat: row.caveat
    });
  }

  const tumor = rows.find((row) => row.role === "tumor");
  const normal = rows.find((row) => row.role === "normal");
  if (!tumor || !normal) {
    throw new Error("Missing tumor or normal row for caller smoke.");
  }
  const vcfPath = `data/raw/smoke/seqc2_hcc1395_full_reference_smoke/${referenceId}/vcf/${referenceId}.bcftools_smoke.vcf.gz`;
  const callerCommand = `set -o pipefail; ${[
    `bcftools mpileup -Ou -f ${sh(referencePath)} -R ${sh(tumor.interval_bed_path)} ${sh(normal.output_bam)} ${sh(tumor.output_bam)}`,
    "bcftools call -mv -Oz",
    `tee ${sh(vcfPath)} >/dev/null`
  ].join(" | ")}`;
  run(callerCommand, `${resultsDir}/logs/${referenceId}.bcftools_call.log`);
  run(`bcftools index -t ${sh(vcfPath)}`, `${resultsDir}/logs/${referenceId}.bcftools_index.log`);
  run(`bcftools stats ${sh(vcfPath)}`, `${resultsDir}/logs/${referenceId}.bcftools_stats.txt`);
  const vcfHeader = capture(`bcftools view -h ${sh(vcfPath)}`);
  const vcfStats = parseVcfStats(readText(pathFromRoot(`${resultsDir}/logs/${referenceId}.bcftools_stats.txt`)));
  const vcfSampleLine = vcfHeader.split(/\r?\n/).find((line) => line.startsWith("#CHROM")) ?? "";
  const vcfSamples = vcfSampleLine.split("\t").slice(9);
  const callerStatus = existsSync(pathFromRoot(vcfPath)) && existsSync(pathFromRoot(`${vcfPath}.tbi`)) ? "passed" : "failed";
  const callerRows = [
    {
      reference_id: referenceId,
      caller: "bcftools mpileup/call",
      caller_scope: "tiny germline-style variant-caller smoke over BRCA1/BRCA2 intervals using tumor and normal BAM inputs",
      reference_path: referencePath,
      interval_bed_path: tumor.interval_bed_path,
      input_bams: `${normal.output_bam};${tumor.output_bam}`,
      output_vcf: vcfPath,
      output_tbi: `${vcfPath}.tbi`,
      vcf_exists: existsSync(pathFromRoot(vcfPath)) ? "yes" : "no",
      tbi_exists: existsSync(pathFromRoot(`${vcfPath}.tbi`)) ? "yes" : "no",
      sample_count: vcfSamples.length,
      samples: vcfSamples.join(";"),
      records: vcfStats.records,
      snps: vcfStats.snps,
      indels: vcfStats.indels,
      status: callerStatus,
      caveat:
        "This is a caller execution and VCF contract smoke only. bcftools call is not a tumor-normal somatic caller and this tiny downsample is not interpreted biologically."
    }
  ];

  const status = validationRows.every((row) => row.status === "passed") && callerRows.every((row) => row.status === "passed") ? "passed" : "failed";

  await writeCsv(pathFromRoot(`${resultsDir}/bam_validation_summary.csv`), validationRows);
  await writeJson(pathFromRoot(`${resultsDir}/bam_validation_summary.json`), {
    generatedAt: new Date().toISOString(),
    status,
    rows: validationRows
  });
  await writeCsv(pathFromRoot(`${resultsDir}/caller_smoke_summary.csv`), callerRows);
  await writeJson(pathFromRoot(`${resultsDir}/caller_smoke_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: callerRows.every((row) => row.status === "passed") ? "passed" : "failed",
    rows: callerRows
  });
  await writeJson(pathFromRoot(`${resultsDir}/tool_versions.json`), {
    generatedAt: new Date().toISOString(),
    bwa: { path: capture("command -v bwa"), version: toolVersion("bwa") },
    samtools: { path: capture("command -v samtools"), version: toolVersion("samtools") },
    bcftools: { path: capture("command -v bcftools"), version: toolVersion("bcftools") }
  });
  await writeJson(pathFromRoot(`${resultsDir}/full_reference_alignment_summary.json`), {
    generatedAt: new Date().toISOString(),
    status,
    referenceId,
    assembly: rows[0].assembly,
    genomeBuild: rows[0].genome_build,
    sampleRows: validationRows.length,
    tumorRows: validationRows.filter((row) => row.role === "tumor").length,
    normalRows: validationRows.filter((row) => row.role === "normal").length,
    callerSmokeStatus: callerRows[0].status,
    indexedReference,
    boundary:
      "Phase 2D validates one full hg38 analysis-set reference, BRCA interval metadata, caller-ready BAM contracts, and a tiny bcftools VCF smoke. It does not validate full-depth WES/WGS coverage, clinical somatic calling, CNV/SV calling, or HRD signatures."
  });
  await writeCsv(pathFromRoot(`${resultsDir}/full_reference_alignment_summary.csv`), [
    {
      status,
      reference_id: referenceId,
      assembly: rows[0].assembly,
      genome_build: rows[0].genome_build,
      sample_rows: validationRows.length,
      tumor_rows: validationRows.filter((row) => row.role === "tumor").length,
      normal_rows: validationRows.filter((row) => row.role === "normal").length,
      caller_smoke_status: callerRows[0].status,
      boundary:
        "Full hg38 analysis-set reference smoke with BRCA intervals and bcftools VCF contract check; not full-depth WES/WGS or clinical somatic calling."
    }
  ]);
  await writeText(
    pathFromRoot(`${resultsDir}/README.md`),
    `# Full-Reference Caller-Readiness Smoke

Status: **${status}**.

Reference: \`${referenceId}\` / ${rows[0].genome_build} / ${rows[0].assembly}

Input: Phase 2A local SEQC2/HCC1395 FASTQ subset.

Tools:

1. \`bwa mem\`
2. \`samtools sort/index/quickcheck/stats/faidx\`
3. \`bcftools mpileup/call/index/stats\`

What this validates:

1. Full UCSC hg38 analysis-set FASTA download and md5 validation.
2. Full-reference \`.fai\` and BWA index creation.
3. BRCA1/BRCA2 interval metadata is present in the samplesheet.
4. Tumor and normal FASTQs align to the full reference.
5. BAMs are coordinate-sorted, indexed, read-grouped, and pass \`samtools quickcheck\`.
6. A tiny VCF caller smoke runs over the BRCA interval BED and produces an indexed VCF.

What this does not validate yet:

1. Full-depth WES/WGS coverage or sensitivity.
2. Vendor capture interval compatibility.
3. A true tumor-normal somatic caller such as Mutect2/Strelka2.
4. CNV/SV calling.
5. scarHRD/CHORD/HRDetect/SBS3 evidence.

Boundary: this is full-reference and caller-readiness plumbing, not biological interpretation.
`
  );

  if (status !== "passed") {
    throw new Error("Full-reference smoke failed. See results/full_reference_smoke/.");
  }

  console.log(`Full-reference smoke ${status} for ${validationRows.length} BAM validations and ${callerRows.length} caller smoke.`);
}

await main();
