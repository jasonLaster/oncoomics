import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureDir, fetchText, parseCsv, pathFromRoot, readText, writeCsv, writeJson } from "./lib";

type FullReferenceSpec = {
  reference_id: string;
  assembly: "hg38";
  genome_build: "GRCh38";
  source_url: string;
  md5_url: string;
  source_file: string;
  interval_bed_path: string;
  interval_regions: string;
  interval_genes: string;
};

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

const references: FullReferenceSpec[] = [
  {
    reference_id: "ucsc_hg38_analysis_set_full",
    assembly: "hg38",
    genome_build: "GRCh38",
    source_url: "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/analysisSet/hg38.analysisSet.fa.gz",
    md5_url: "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/analysisSet/md5sum.txt",
    source_file: "hg38.analysisSet.fa.gz",
    interval_bed_path: "data/raw/reference/full_reference_smoke/ucsc_hg38_analysis_set_full/brca_chr13_chr17_smoke.bed",
    interval_regions: "chr13:32315086-32400266;chr17:43044295-43125482",
    interval_genes: "BRCA2;BRCA1"
  }
];

const smokePairId = "seqc2_hcc1395_wes_minimal_smoke";
const referenceRoot = "data/raw/reference/full_reference_smoke";
const smokeRoot = "data/raw/smoke/seqc2_hcc1395_full_reference_smoke";
const resultsDir = "results/full_reference_smoke";

function sh(value: string) {
  return `'${value.replaceAll("'", "'\"'\"'")}'`;
}

function run(command: string) {
  const result = spawnSync("bash", ["-lc", command], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 20
  });
  if (result.status !== 0) {
    throw new Error(`Command failed (${result.status}): ${command}\n${result.stderr}`);
  }
  return result.stdout;
}

function sha256File(relativePath: string) {
  return createHash("sha256").update(readFileSync(pathFromRoot(relativePath))).digest("hex");
}

function md5File(relativePath: string) {
  return createHash("md5").update(readFileSync(pathFromRoot(relativePath))).digest("hex");
}

function parseMd5(text: string, fileName: string) {
  for (const line of text.split(/\r?\n/)) {
    const match = line.trim().match(/^([0-9a-fA-F]{32})\s+(\S+)$/);
    if (match && match[2] === fileName) {
      return match[1].toLowerCase();
    }
  }
  throw new Error(`Could not find md5 for ${fileName}.`);
}

function sampleName(row: SmokeSampleRow) {
  return row.sample.replace(`_${row.run_accession}`, "");
}

async function main() {
  ensureDir(pathFromRoot("manifests"));
  ensureDir(pathFromRoot(resultsDir));

  const smokeRows = (parseCsv(readText(pathFromRoot("manifests/raw_smoke_samplesheet.csv"))) as SmokeSampleRow[])
    .filter((row) => row.pair_id === smokePairId)
    .sort((a, b) => a.role.localeCompare(b.role));
  if (smokeRows.length !== 2 || !smokeRows.some((row) => row.role === "tumor") || !smokeRows.some((row) => row.role === "normal")) {
    throw new Error(`Expected tumor and normal rows for ${smokePairId}.`);
  }

  const referenceRows: Record<string, unknown>[] = [];
  const samplesheetRows: Record<string, unknown>[] = [];

  for (const reference of references) {
    const referenceDir = `${referenceRoot}/${reference.reference_id}`;
    const sourcePath = `${referenceDir}/${reference.source_file}`;
    const fastaPath = `${referenceDir}/${reference.reference_id}.fa`;
    ensureDir(pathFromRoot(referenceDir));
    ensureDir(pathFromRoot(`${smokeRoot}/${reference.reference_id}/bam`));
    ensureDir(pathFromRoot(`${smokeRoot}/${reference.reference_id}/vcf`));

    const expectedMd5 = parseMd5(await fetchText(reference.md5_url), reference.source_file);
    if (!existsSync(pathFromRoot(sourcePath))) {
      run(`curl -fL --retry 3 --continue-at - ${sh(reference.source_url)} -o ${sh(sourcePath)}`);
    }
    const observedMd5 = md5File(sourcePath);
    if (observedMd5 !== expectedMd5) {
      throw new Error(`${sourcePath} md5 mismatch: expected ${expectedMd5}, observed ${observedMd5}.`);
    }

    if (!existsSync(pathFromRoot(fastaPath))) {
      run(`gzip -cd ${sh(sourcePath)} > ${sh(fastaPath)}`);
    }
    if (!existsSync(pathFromRoot(`${fastaPath}.fai`))) {
      run(`samtools faidx ${sh(fastaPath)}`);
    }

    await Bun.write(
      pathFromRoot(reference.interval_bed_path),
      [
        "chr13\t32315085\t32400266\tBRCA2_smoke_interval",
        "chr17\t43044294\t43125482\tBRCA1_smoke_interval"
      ].join("\n") + "\n"
    );

    const fastaSha256 = sha256File(fastaPath);
    referenceRows.push({
      reference_id: reference.reference_id,
      assembly: reference.assembly,
      genome_build: reference.genome_build,
      source: "UCSC hg38 analysisSet FASTA",
      source_url: reference.source_url,
      source_md5: expectedMd5,
      md5_status: "passed",
      fasta_path: fastaPath,
      fasta_fai_path: `${fastaPath}.fai`,
      fasta_sha256: fastaSha256,
      fasta_size_bytes: statSync(pathFromRoot(fastaPath)).size,
      interval_bed_path: reference.interval_bed_path,
      interval_regions: reference.interval_regions,
      interval_genes: reference.interval_genes,
      caller_smoke_tool: "bcftools mpileup/call",
      caveat:
        "Full hg38 analysis-set reference for local caller-readiness smoke. Uses tiny HCC1395 FASTQ subset and BRCA interval targets; not full-depth WES/WGS sensitivity validation."
    });

    for (const row of smokeRows) {
      const run = row.run_accession;
      const sample = sampleName(row);
      const bam = `${smokeRoot}/${reference.reference_id}/bam/${run}.coordinate_sorted.bam`;
      samplesheetRows.push({
        pair_id: row.pair_id,
        patient: row.patient,
        sample,
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
        reference_id: reference.reference_id,
        assembly: reference.assembly,
        genome_build: reference.genome_build,
        reference_path: fastaPath,
        reference_sha256: fastaSha256,
        interval_bed_path: reference.interval_bed_path,
        interval_regions: reference.interval_regions,
        interval_genes: reference.interval_genes,
        aligner: "bwa mem",
        aligner_threads: "4",
        read_group_id: `${run}_${reference.assembly}_full`,
        read_group_sample: sample,
        read_group_library: `${row.assay}_${row.role}_${reference.assembly}_full`,
        read_group_platform: "ILLUMINA",
        read_group_platform_unit: run,
        output_bam: bam,
        output_bai: `${bam}.bai`,
        caller_ready_scope: "full reference plus BRCA1/BRCA2 interval metadata",
        source: "Phase 2A local HCC1395 FASTQ subset aligned to full UCSC hg38 analysis set",
        caveat:
          "Full-reference caller-readiness smoke using tiny downsampled reads; not full-depth WES/WGS, not clinical somatic calling, and not HRD evidence."
      });
    }
  }

  await writeCsv(pathFromRoot("manifests/full_reference_smoke_references.csv"), referenceRows);
  await writeCsv(pathFromRoot("manifests/full_reference_smoke_samplesheet.csv"), samplesheetRows);
  await writeJson(pathFromRoot(`${resultsDir}/reference_assets_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "built",
    referenceCount: referenceRows.length,
    sampleRows: samplesheetRows.length,
    references: referenceRows,
    boundary:
      "Phase 2D uses a full UCSC hg38 analysis-set reference with BRCA1/BRCA2 smoke intervals. It validates full-reference plumbing and caller-readiness contracts, not full-depth WES/WGS sensitivity."
  });

  console.log(`Built ${referenceRows.length} full-reference smoke bundle and ${samplesheetRows.length} sample rows.`);
}

await main();
