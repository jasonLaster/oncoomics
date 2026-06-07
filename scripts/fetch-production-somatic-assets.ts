import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureDir, fetchJson, parseCsv, pathFromRoot, readText, writeCsv, writeJson } from "./lib";

type GitHubRelease = {
  tag_name: string;
  html_url: string;
  assets: Array<{
    name: string;
    size: number;
    browser_download_url: string;
  }>;
};

type RawPanelRow = {
  pair_id: string;
  role: string;
  run: string;
  assay: string;
  sample_name: string;
  library_strategy: string;
  library_layout: string;
  platform: string;
  model: string;
  fastq_1_url: string;
  fastq_2_url: string;
  use_case: string;
  caveat: string;
};

type FullReferenceRow = {
  reference_id: string;
  assembly: string;
  genome_build: string;
  source_url: string;
  fasta_path: string;
  fasta_fai_path: string;
  fasta_sha256: string;
  interval_bed_path: string;
  interval_regions: string;
  interval_genes: string;
};

const gatkVersion = process.env.GATK_VERSION ?? "4.6.2.0";
const pairId = "seqc2_hcc1395_wes_minimal_smoke";
const readPairsPerEnd = Number(process.env.PRODUCTION_SOMATIC_READS ?? "50000");
const resultsDir = "results/production_somatic_smoke";
const toolRoot = "data/raw/tools/gatk";
const gatkDir = `${toolRoot}/gatk-${gatkVersion}`;
const gatkZip = `${toolRoot}/gatk-${gatkVersion}.zip`;
const gatkJar = `${gatkDir}/gatk-package-${gatkVersion}-local.jar`;
const seqc2TruthRoot = "data/raw/reference/seqc2_hcc1395_truth/latest";
const truthAssets = [
  {
    kind: "snv",
    url: "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz",
    path: `${seqc2TruthRoot}/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz`
  },
  {
    kind: "indel",
    url: "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz",
    path: `${seqc2TruthRoot}/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz`
  },
  {
    kind: "high_confidence_regions",
    url: "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/High-Confidence_Regions_v1.2.bed",
    path: `${seqc2TruthRoot}/High-Confidence_Regions_v1.2.bed`
  },
  {
    kind: "readme",
    url: "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/README.md",
    path: `${seqc2TruthRoot}/README.md`
  }
];

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
  return result.stdout.trim();
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

function fileSummary(asset: { kind: string; url: string; path: string }) {
  return {
    kind: asset.kind,
    url: asset.url,
    path: asset.path,
    sizeBytes: statSync(pathFromRoot(asset.path)).size,
    sha256: sha256File(asset.path)
  };
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

function findJava() {
  const candidates = [
    process.env.GATK_JAVA ?? "",
    "/opt/homebrew/opt/openjdk@17/bin/java",
    "/opt/homebrew/bin/java",
    commandPath("java")
  ];
  const java = candidates.find(javaWorks);
  if (!java) {
    throw new Error("GATK Mutect2 smoke requires Java 17+. Install with `brew install openjdk@17` or set GATK_JAVA.");
  }
  return java;
}

function referenceDictPath(fastaPath: string) {
  return fastaPath.replace(/\.(fa|fasta)$/i, ".dict");
}

async function downloadIfMissing(url: string, relativePath: string, label: string) {
  ensureDir(pathFromRoot(relativePath.split("/").slice(0, -1).join("/")));
  if (existsSync(pathFromRoot(relativePath)) && statSync(pathFromRoot(relativePath)).size > 0) {
    return false;
  }
  const tmpPath = `${relativePath}.tmp`;
  run(
    `curl -L --fail --retry 3 --retry-delay 2 -o ${sh(tmpPath)} ${sh(url)} && mv ${sh(tmpPath)} ${sh(relativePath)}`,
    `${resultsDir}/logs/download.${label}.log`
  );
  return true;
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));
  ensureDir(pathFromRoot(toolRoot));
  ensureDir(pathFromRoot(seqc2TruthRoot));

  const javaPath = findJava();
  const release = await fetchJson<GitHubRelease>(`https://api.github.com/repos/broadinstitute/gatk/releases/tags/${gatkVersion}`);
  const asset = release.assets.find((item) => item.name === `gatk-${gatkVersion}.zip`);
  if (!asset) {
    throw new Error(`Could not find gatk-${gatkVersion}.zip in ${release.html_url}`);
  }

  const downloadedGatk = await downloadIfMissing(asset.browser_download_url, gatkZip, "gatk");
  if (!existsSync(pathFromRoot(gatkJar))) {
    run(`unzip -q -o ${sh(gatkZip)} -d ${sh(toolRoot)}`, `${resultsDir}/logs/unzip.gatk.log`);
  }
  if (!existsSync(pathFromRoot(gatkJar))) {
    throw new Error(`GATK jar not found after unzip: ${gatkJar}`);
  }

  const fullReferences = parseCsv(readText(pathFromRoot("manifests/full_reference_smoke_references.csv"))) as FullReferenceRow[];
  const reference = fullReferences.find((row) => row.reference_id === "ucsc_hg38_analysis_set_full");
  if (!reference) {
    throw new Error("Expected ucsc_hg38_analysis_set_full in manifests/full_reference_smoke_references.csv.");
  }
  if (!existsSync(pathFromRoot(reference.fasta_path))) {
    throw new Error(`Full reference FASTA is missing: ${reference.fasta_path}. Run fetch:full-reference-smoke first.`);
  }
  if (sha256File(reference.fasta_path) !== reference.fasta_sha256) {
    throw new Error(`Full reference FASTA sha256 changed for ${reference.reference_id}.`);
  }
  if (!existsSync(pathFromRoot(reference.fasta_fai_path))) {
    run(`samtools faidx ${sh(reference.fasta_path)}`, `${resultsDir}/logs/${reference.reference_id}.samtools_faidx.log`);
  }
  const dictPath = referenceDictPath(reference.fasta_path);
  const createdDict = !existsSync(pathFromRoot(dictPath));
  if (createdDict) {
    run(
      `${sh(javaPath)} -jar ${sh(gatkJar)} CreateSequenceDictionary -R ${sh(reference.fasta_path)} -O ${sh(dictPath)}`,
      `${resultsDir}/logs/${reference.reference_id}.create_sequence_dictionary.log`
    );
  }

  const downloadedTruthAssets = [];
  for (const truthAsset of truthAssets) {
    const downloaded = await downloadIfMissing(truthAsset.url, truthAsset.path, truthAsset.kind);
    downloadedTruthAssets.push({ ...fileSummary(truthAsset), downloaded });
  }

  const rawPanel = parseCsv(readText(pathFromRoot("manifests/raw_representative_panel.csv"))) as RawPanelRow[];
  const selected = rawPanel
    .filter((row) => row.pair_id === pairId)
    .sort((a, b) => (a.role === "tumor" ? -1 : 1) - (b.role === "tumor" ? -1 : 1));
  if (selected.length !== 2 || !selected.some((row) => row.role === "tumor") || !selected.some((row) => row.role === "normal")) {
    throw new Error(`Expected tumor and normal raw panel rows for ${pairId}.`);
  }

  const smokeRoot = "data/raw/smoke/seqc2_hcc1395_production_somatic_smoke";
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
      source_fastq_1: row.fastq_1_url,
      source_fastq_2: row.fastq_2_url,
      read_pairs_per_end: readPairsPerEnd,
      fastq_1: `${smokeRoot}/fastq/${row.run}_R1.${readPairsPerEnd}reads.fastq`,
      fastq_2: `${smokeRoot}/fastq/${row.run}_R2.${readPairsPerEnd}reads.fastq`,
      reference_id: reference.reference_id,
      assembly: reference.assembly,
      genome_build: reference.genome_build,
      reference_path: reference.fasta_path,
      reference_fai_path: reference.fasta_fai_path,
      reference_dict_path: dictPath,
      reference_sha256: reference.fasta_sha256,
      brca_interval_bed_path: reference.interval_bed_path,
      brca_interval_regions: reference.interval_regions,
      brca_interval_genes: reference.interval_genes,
      known_sites_resource_path: "not_supplied_for_phase_2e_smoke",
      germline_resource_path: "not_supplied_for_phase_2e_smoke",
      panel_of_normals_path: "not_supplied_for_phase_2e_smoke",
      truth_snv_vcf_path: truthAssets.find((asset) => asset.kind === "snv")?.path ?? "",
      truth_indel_vcf_path: truthAssets.find((asset) => asset.kind === "indel")?.path ?? "",
      truth_high_confidence_bed_path: truthAssets.find((asset) => asset.kind === "high_confidence_regions")?.path ?? "",
      gatk_jar_path: gatkJar,
      java_path: javaPath,
      production_caller: "GATK Mutect2 + FilterMutectCalls",
      read_group_id: `${row.run}.${row.role}`,
      read_group_sample: sampleName,
      read_group_library: row.run,
      read_group_platform: "ILLUMINA",
      read_group_platform_unit: row.run,
      output_bam: `${smokeRoot}/${reference.reference_id}/bam/${row.run}.${row.role}.bam`,
      output_bai: `${smokeRoot}/${reference.reference_id}/bam/${row.run}.${row.role}.bam.bai`,
      caller_interval_strategy: "mapped-read active intervals, truth-overlap-prioritized when compatible",
      caveat:
        "Phase 2E production-style somatic smoke uses a downsampled public SEQC2/HCC1395 WES pair. It validates Mutect2 plumbing and VCF/QC contracts, not full-depth sensitivity, HRD signatures, or clinical actionability."
    };
  });

  await writeCsv(pathFromRoot("manifests/production_somatic_smoke_samplesheet.csv"), sampleRows);
  await writeJson(pathFromRoot(`${resultsDir}/asset_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "ready",
    caller: "GATK Mutect2 + FilterMutectCalls",
    gatk: {
      version: gatkVersion,
      releaseApi: `https://api.github.com/repos/broadinstitute/gatk/releases/tags/${gatkVersion}`,
      releaseUrl: release.html_url,
      assetUrl: asset.browser_download_url,
      assetSizeBytes: asset.size,
      zipPath: gatkZip,
      zipSha256: sha256File(gatkZip),
      jarPath: gatkJar,
      jarSha256: sha256File(gatkJar),
      downloaded: downloadedGatk
    },
    java: {
      path: javaPath,
      version: capture(`${sh(javaPath)} -version 2>&1 | head -n 1`)
    },
    reference: {
      referenceId: reference.reference_id,
      assembly: reference.assembly,
      genomeBuild: reference.genome_build,
      sourceUrl: reference.source_url,
      fastaPath: reference.fasta_path,
      fastaSha256: reference.fasta_sha256,
      faiPath: reference.fasta_fai_path,
      dictPath,
      dictSha256: sha256File(dictPath),
      dictCreated: createdDict,
      brcaIntervalBedPath: reference.interval_bed_path,
      brcaIntervalRegions: reference.interval_regions,
      brcaIntervalGenes: reference.interval_genes
    },
    seqc2Truth: {
      sourceDirectory: "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/",
      reference: "GRCh38.d1.vd1.fa per VCF header",
      assets: downloadedTruthAssets
    },
    sampleRows: sampleRows.length,
    readPairsPerEnd,
    productionResourceCaveat:
      "Known-sites, germline-resource, contamination-estimation, and panel-of-normals resources are intentionally not supplied in this local smoke. They remain required for a full production clinical-grade workflow."
  });

  console.log(`Production somatic assets ready for ${sampleRows.length} samples with GATK ${gatkVersion}.`);
}

await main();
