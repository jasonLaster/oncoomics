import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureDir, fetchText, parseCsv, pathFromRoot, readText, writeCsv, writeJson } from "./lib";

type ReferenceSpec = {
  reference_id: string;
  assembly: "hg38" | "hg19";
  genome_build: "GRCh38" | "GRCh37";
  source_base_url: string;
  chromosomes: string[];
  genes_covered: string[];
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

const references: ReferenceSpec[] = [
  {
    reference_id: "ucsc_hg38_chr13_chr17",
    assembly: "hg38",
    genome_build: "GRCh38",
    source_base_url: "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes",
    chromosomes: ["chr13", "chr17"],
    genes_covered: ["BRCA2", "BRCA1"]
  },
  {
    reference_id: "ucsc_hg19_chr13_chr17",
    assembly: "hg19",
    genome_build: "GRCh37",
    source_base_url: "https://hgdownload.soe.ucsc.edu/goldenPath/hg19/chromosomes",
    chromosomes: ["chr13", "chr17"],
    genes_covered: ["BRCA2", "BRCA1"]
  }
];

const smokePairId = "seqc2_hcc1395_wes_minimal_smoke";
const referenceRoot = "data/raw/reference/human_reference_smoke";
const smokeRoot = "data/raw/smoke/seqc2_hcc1395_human_reference_smoke";
const resultsDir = "results/human_reference_smoke";

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

function parseMd5s(text: string) {
  const md5s = new Map<string, string>();
  for (const line of text.split(/\r?\n/)) {
    const match = line.trim().match(/^([0-9a-fA-F]{32})\s+(\S+)$/);
    if (match) {
      md5s.set(match[2], match[1].toLowerCase());
    }
  }
  return md5s;
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
    const fastaPath = `${referenceDir}/${reference.reference_id}.fa`;
    ensureDir(pathFromRoot(referenceDir));
    ensureDir(pathFromRoot(`${smokeRoot}/${reference.reference_id}/bam`));

    const md5s = parseMd5s(await fetchText(`${reference.source_base_url}/md5sum.txt`));
    const sourceUrls: string[] = [];
    const md5Values: string[] = [];
    const localGzPaths: string[] = [];

    for (const chromosome of reference.chromosomes) {
      const fileName = `${chromosome}.fa.gz`;
      const sourceUrl = `${reference.source_base_url}/${fileName}`;
      const gzPath = `${referenceDir}/${fileName}`;
      sourceUrls.push(sourceUrl);
      localGzPaths.push(gzPath);
      const expectedMd5 = md5s.get(fileName) ?? "";
      md5Values.push(expectedMd5);

      if (!existsSync(pathFromRoot(gzPath))) {
        run(`curl -fsSL ${sh(sourceUrl)} -o ${sh(gzPath)}`);
      }

      if (expectedMd5) {
        const observed = md5File(gzPath);
        if (observed !== expectedMd5) {
          throw new Error(`${gzPath} md5 mismatch: expected ${expectedMd5}, observed ${observed}.`);
        }
      }
    }

    if (!existsSync(pathFromRoot(fastaPath))) {
      run(`gzip -cd ${localGzPaths.map(sh).join(" ")} > ${sh(fastaPath)}`);
    }
    if (!existsSync(pathFromRoot(`${fastaPath}.fai`))) {
      run(`samtools faidx ${sh(fastaPath)}`);
    }
    const fastaSha256 = sha256File(fastaPath);

    referenceRows.push({
      reference_id: reference.reference_id,
      assembly: reference.assembly,
      genome_build: reference.genome_build,
      source: "UCSC Genome Browser per-chromosome FASTA",
      source_base_url: reference.source_base_url,
      chromosomes: reference.chromosomes.join(";"),
      genes_covered: reference.genes_covered.join(";"),
      source_urls: sourceUrls.join(";"),
      source_md5s: md5Values.join(";"),
      md5_status: md5Values.every(Boolean) ? "passed" : "not_available",
      fasta_path: fastaPath,
      fasta_fai_path: `${fastaPath}.fai`,
      fasta_sha256: fastaSha256,
      fasta_size_bytes: statSync(pathFromRoot(fastaPath)).size,
      caveat:
        "Partial human-reference smoke containing chr13 and chr17 only. Validates real-reference alignment mechanics, not whole-genome/full-exome performance."
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
        chromosomes: reference.chromosomes.join(";"),
        genes_covered: reference.genes_covered.join(";"),
        reference_path: fastaPath,
        reference_sha256: fastaSha256,
        aligner: "bwa mem",
        aligner_threads: "2",
        read_group_id: `${run}_${reference.assembly}`,
        read_group_sample: sample,
        read_group_library: `${row.assay}_${row.role}_${reference.assembly}`,
        read_group_platform: "ILLUMINA",
        read_group_platform_unit: run,
        output_bam: bam,
        output_bai: `${bam}.bai`,
        source: "Phase 2A local HCC1395 FASTQ subset aligned to partial UCSC human reference",
        caveat:
          "Partial chr13/chr17 human-reference smoke for reference-build and BAM contract validation only; not full-depth WES/WGS, somatic calling, or HRD evidence."
      });
    }
  }

  await writeCsv(pathFromRoot("manifests/human_reference_smoke_references.csv"), referenceRows);
  await writeCsv(pathFromRoot("manifests/human_reference_smoke_samplesheet.csv"), samplesheetRows);
  await writeJson(pathFromRoot(`${resultsDir}/reference_assets_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "built",
    referenceCount: referenceRows.length,
    sampleRows: samplesheetRows.length,
    references: referenceRows,
    boundary:
      "Phase 2C uses partial UCSC hg38/hg19 chromosome references for local validation. Full-depth Diana or SEQC2 calling still requires full reference bundles, intervals, known-sites resources, and caller configuration."
  });

  console.log(`Built ${referenceRows.length} partial human-reference smoke bundles and ${samplesheetRows.length} sample rows.`);
}

await main();
