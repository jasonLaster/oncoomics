import { createHash } from "node:crypto";
import { copyFileSync, existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureDir, parseCsv, pathFromRoot, readJson, readText, writeCsv, writeJson } from "./lib";

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
  source_url: string;
  fasta_path: string;
  fasta_fai_path: string;
  fasta_sha256: string;
  interval_bed_path: string;
  interval_regions: string;
  interval_genes: string;
};

const pairId = "seqc2_hcc1395_wes_minimal_smoke";
const resultsDir = "results/full_wes_benchmark";
const fullWesRoot = "data/raw/full_wes/seqc2_hcc1395_wes_minimal";
const somaticResourceRoot = "data/raw/reference/gatk_best_practices/somatic-hg38";
const productionAssetSummaryPath = "results/production_somatic_smoke/asset_summary.json";
const resources = [
  {
    kind: "mutect2_panel_of_normals",
    url: "https://storage.googleapis.com/gatk-best-practices/somatic-hg38/1000g_pon.hg38.vcf.gz",
    path: `${somaticResourceRoot}/1000g_pon.hg38.vcf.gz`,
    indexUrl: "https://storage.googleapis.com/gatk-best-practices/somatic-hg38/1000g_pon.hg38.vcf.gz.tbi",
    indexPath: `${somaticResourceRoot}/1000g_pon.hg38.vcf.gz.tbi`
  },
  {
    kind: "common_biallelic_gnomad_resource",
    url: "https://downloads.sourceforge.net/project/mutect2-data/common_biallelic/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.gz",
    path: `${somaticResourceRoot}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.gz`,
    indexUrl: "https://downloads.sourceforge.net/project/mutect2-data/common_biallelic/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx",
    indexPath: `${somaticResourceRoot}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx`,
    usablePath: `${somaticResourceRoot}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf`,
    usableIndexPath: `${somaticResourceRoot}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx`
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

function md5File(relativePath: string) {
  return createHash("md5").update(readFileSync(pathFromRoot(relativePath))).digest("hex");
}

function sha256File(relativePath: string) {
  return createHash("sha256").update(readFileSync(pathFromRoot(relativePath))).digest("hex");
}

function ensureReadableGzip(relativePath: string, label: string) {
  run(`gzip -t ${sh(relativePath)}`, `${resultsDir}/logs/${label}.gzip_test.log`);
}

function downloadResume(url: string, relativePath: string, label: string) {
  ensureDir(pathFromRoot(relativePath.split("/").slice(0, -1).join("/")));
  const beforeBytes = existsSync(pathFromRoot(relativePath)) ? statSync(pathFromRoot(relativePath)).size : 0;
  run(`curl -L --fail --retry 5 --retry-delay 3 -C - -o ${sh(relativePath)} ${sh(url)}`, `${resultsDir}/logs/download.${label}.log`);
  const afterBytes = statSync(pathFromRoot(relativePath)).size;
  return { downloaded: afterBytes !== beforeBytes, beforeBytes, afterBytes };
}

function maybeDownloadIndex(url: string, relativePath: string, label: string) {
  const beforeBytes = existsSync(pathFromRoot(relativePath)) ? statSync(pathFromRoot(relativePath)).size : 0;
  if (beforeBytes > 0) {
    return { indexStatus: "cached", beforeBytes, afterBytes: beforeBytes };
  }
  const result = spawnSync("bash", ["-lc", `curl -L --fail --retry 3 --retry-delay 2 -C - -o ${sh(relativePath)} ${sh(url)}`], {
    cwd: pathFromRoot(""),
    encoding: "utf8",
    maxBuffer: 1024 * 1024 * 20
  });
  const log = [
    `$ curl -L --fail --retry 3 --retry-delay 2 -C - -o ${sh(relativePath)} ${sh(url)}`,
    "",
    "## stdout",
    result.stdout || "",
    "",
    "## stderr",
    result.stderr || "",
    "",
    `exit_status=${result.status}`
  ].join("\n");
  writeFileSync(pathFromRoot(`${resultsDir}/logs/download.${label}.log`), log.endsWith("\n") ? log : `${log}\n`);
  if (result.status === 0 && existsSync(pathFromRoot(relativePath)) && statSync(pathFromRoot(relativePath)).size > 0) {
    return { indexStatus: "downloaded_or_cached", beforeBytes, afterBytes: statSync(pathFromRoot(relativePath)).size };
  }
  return { indexStatus: "not_available_from_source", beforeBytes, afterBytes: 0 };
}

function ensureResourceIndex(vcfPath: string, indexPath: string, label: string, javaPath: string, gatkJar: string) {
  if (existsSync(pathFromRoot(indexPath)) && statSync(pathFromRoot(indexPath)).size > 0) {
    return "present";
  }
  if (indexPath.endsWith(".idx")) {
    run(`${sh(javaPath)} -jar ${sh(gatkJar)} IndexFeatureFile -I ${sh(vcfPath)}`, `${resultsDir}/logs/${label}.gatk_index_feature_file.log`);
    const alternateIndex = `${vcfPath}.idx`;
    if (!existsSync(pathFromRoot(indexPath)) && existsSync(pathFromRoot(alternateIndex))) {
      copyFileSync(pathFromRoot(alternateIndex), pathFromRoot(indexPath));
    }
    if (!existsSync(pathFromRoot(indexPath)) || statSync(pathFromRoot(indexPath)).size === 0) {
      throw new Error(`GATK did not create expected index ${indexPath} for ${vcfPath}.`);
    }
    return "created_with_gatk";
  }
  run(`bcftools index -t -f ${sh(vcfPath)}`, `${resultsDir}/logs/${label}.bcftools_index.log`);
  return "created_with_bcftools";
}

function ensureUncompressedVcf(gzipPath: string, vcfPath: string, label: string) {
  if (existsSync(pathFromRoot(vcfPath)) && statSync(pathFromRoot(vcfPath)).size > 0) {
    return "present";
  }
  run(`gunzip -c ${sh(gzipPath)} > ${sh(vcfPath)}`, `${resultsDir}/logs/${label}.uncompress_vcf.log`);
  return "created";
}

function commandPath(tool: string) {
  const result = spawnSync("bash", ["-lc", `command -v ${tool}`], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
}

async function main() {
  ensureDir(pathFromRoot(resultsDir));
  ensureDir(pathFromRoot(`${resultsDir}/logs`));
  ensureDir(pathFromRoot(fullWesRoot));
  ensureDir(pathFromRoot(somaticResourceRoot));

  if (!existsSync(pathFromRoot(productionAssetSummaryPath))) {
    throw new Error("Phase 2F requires Phase 2E production assets. Run fetch:production-somatic first.");
  }
  const productionAssets = readJson<Record<string, Record<string, string>>>(pathFromRoot(productionAssetSummaryPath));
  const gatkJar = productionAssets.gatk?.jarPath;
  const javaPath = productionAssets.java?.path;
  if (!gatkJar || !javaPath) {
    throw new Error("Production asset summary is missing GATK or Java paths.");
  }

  const fullReferences = parseCsv(readText(pathFromRoot("manifests/full_reference_smoke_references.csv"))) as FullReferenceRow[];
  const reference = fullReferences.find((row) => row.reference_id === "ucsc_hg38_analysis_set_full");
  if (!reference) {
    throw new Error("Expected ucsc_hg38_analysis_set_full in full-reference manifest.");
  }

  const rawPanel = parseCsv(readText(pathFromRoot("manifests/raw_representative_panel.csv"))) as RawPanelRow[];
  const selected = rawPanel
    .filter((row) => row.pair_id === pairId)
    .sort((a, b) => (a.role === "tumor" ? -1 : 1) - (b.role === "tumor" ? -1 : 1));
  if (selected.length !== 2 || !selected.some((row) => row.role === "tumor") || !selected.some((row) => row.role === "normal")) {
    throw new Error(`Expected tumor and normal rows for ${pairId}.`);
  }

  const fastqAssets: Record<string, unknown>[] = [];
  for (const row of selected) {
    for (const read of ["1", "2"] as const) {
      const url = read === "1" ? row.fastq_1_url : row.fastq_2_url;
      const expectedMd5 = read === "1" ? row.fastq_1_md5 : row.fastq_2_md5;
      const expectedBytes = Number(read === "1" ? row.fastq_1_bytes : row.fastq_2_bytes);
      const path = `${fullWesRoot}/${row.run}_R${read}.fastq.gz`;
      const cached =
        existsSync(pathFromRoot(path)) &&
        statSync(pathFromRoot(path)).size === expectedBytes &&
        md5File(path) === expectedMd5;
      const download = cached
        ? { downloaded: false, beforeBytes: expectedBytes, afterBytes: expectedBytes }
        : downloadResume(url, path, `${row.run}.R${read}`);
      const actualMd5 = md5File(path);
      if (actualMd5 !== expectedMd5) {
        throw new Error(`${path} md5 mismatch: ${actualMd5} !== ${expectedMd5}`);
      }
      const actualBytes = statSync(pathFromRoot(path)).size;
      if (actualBytes !== expectedBytes) {
        throw new Error(`${path} byte-size mismatch: ${actualBytes} !== ${expectedBytes}`);
      }
      ensureReadableGzip(path, `${row.run}.R${read}`);
      fastqAssets.push({
        pair_id: row.pair_id,
        sample: row.role === "tumor" ? "HCC1395" : "HCC1395BL",
        role: row.role,
        run_accession: row.run,
        read,
        url,
        path,
        expected_md5: expectedMd5,
        actual_md5: actualMd5,
        expected_bytes: expectedBytes,
        actual_bytes: actualBytes,
        downloaded: download.downloaded,
        gzip_test: "passed"
      });
    }
  }

  const resourceAssets = [];
  for (const resource of resources) {
    const download =
      existsSync(pathFromRoot(resource.path)) && statSync(pathFromRoot(resource.path)).size > 0
        ? { downloaded: false, beforeBytes: statSync(pathFromRoot(resource.path)).size, afterBytes: statSync(pathFromRoot(resource.path)).size }
        : downloadResume(resource.url, resource.path, resource.kind);
    ensureReadableGzip(resource.path, resource.kind);
    const indexDownload = maybeDownloadIndex(resource.indexUrl, resource.indexPath, `${resource.kind}.index`);
    const usablePath = resource.usablePath ?? resource.path;
    const usableIndexPath = resource.usableIndexPath ?? resource.indexPath;
    const uncompressedStatus = resource.usablePath ? ensureUncompressedVcf(resource.path, resource.usablePath, resource.kind) : "not_needed";
    const indexStatus = resource.usablePath
      ? existsSync(pathFromRoot(usableIndexPath)) && statSync(pathFromRoot(usableIndexPath)).size > 0
        ? "present_for_uncompressed_vcf"
        : ensureResourceIndex(usablePath, usableIndexPath, resource.kind, javaPath, gatkJar)
      : ensureResourceIndex(resource.path, resource.indexPath, resource.kind, javaPath, gatkJar);
    resourceAssets.push({
      kind: resource.kind,
      url: resource.url,
      path: resource.path,
      usable_path: usablePath,
      size_bytes: statSync(pathFromRoot(resource.path)).size,
      sha256: sha256File(resource.path),
      index_url: resource.indexUrl,
      index_path: resource.indexPath,
      usable_index_path: usableIndexPath,
      index_status: indexStatus,
      index_download_status: indexDownload.indexStatus,
      uncompressed_status: uncompressedStatus,
      usable_size_bytes: statSync(pathFromRoot(usablePath)).size,
      usable_sha256: sha256File(usablePath),
      index_size_bytes: statSync(pathFromRoot(resource.indexPath)).size,
      index_sha256: sha256File(resource.indexPath),
      downloaded: download.downloaded
    });
  }

  const smokeRoot = "data/raw/full_wes/seqc2_hcc1395_wes_minimal";
  const outputRoot = "data/raw/full_wes_benchmark/seqc2_hcc1395_wes_minimal";
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
      fastq_1: `${smokeRoot}/${row.run}_R1.fastq.gz`,
      fastq_2: `${smokeRoot}/${row.run}_R2.fastq.gz`,
      fastq_1_md5: row.fastq_1_md5,
      fastq_2_md5: row.fastq_2_md5,
      fastq_1_bytes: row.fastq_1_bytes,
      fastq_2_bytes: row.fastq_2_bytes,
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
      gatk_jar_path: gatkJar,
      java_path: javaPath,
      mutect2_germline_resource_path: "not_downloaded_for_phase_2f_local_gate_full_resource_is_3gb",
      mutect2_germline_resource_source_url: "https://storage.googleapis.com/gatk-best-practices/somatic-hg38/af-only-gnomad.hg38.vcf.gz",
      mutect2_panel_of_normals_path: `${somaticResourceRoot}/1000g_pon.hg38.vcf.gz`,
      common_biallelic_resource_path: `${somaticResourceRoot}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf`,
      common_biallelic_resource_index_path: `${somaticResourceRoot}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx`,
      bqsr_known_sites_policy: "deferred_until_capture_intervals_and_matching_known_sites_are_selected",
      contamination_policy: "estimate_with_common_biallelic_gnomad_sites_inside_phase_2f_benchmark_intervals_when_sites_overlap",
      duplicate_marking_tool: "GATK MarkDuplicates",
      production_caller: "GATK Mutect2 + FilterMutectCalls with hg38 PoN; common-biallelic gnomAD for contamination pileups",
      read_group_id: `${row.run}.${row.role}.full_wes`,
      read_group_sample: sampleName,
      read_group_library: row.run,
      read_group_platform: "ILLUMINA",
      read_group_platform_unit: row.run,
      raw_bam: `${outputRoot}/${reference.reference_id}/bam/${row.run}.${row.role}.raw.bam`,
      dedup_bam: `${outputRoot}/${reference.reference_id}/bam/${row.run}.${row.role}.dedup.bam`,
      dedup_bai: `${outputRoot}/${reference.reference_id}/bam/${row.run}.${row.role}.dedup.bai`,
      duplicate_metrics_path: `${outputRoot}/${reference.reference_id}/metrics/${row.run}.${row.role}.markduplicates.metrics.txt`,
      caveat:
        "Phase 2F uses full SEQC2/HCC1395 WES FASTQs and production-style resource-aware Mutect2 on covered truth-overlap intervals. It is not WGS HRD signature, CNV, or SV evidence."
    };
  });

  await writeCsv(pathFromRoot("manifests/full_wes_benchmark_samplesheet.csv"), sampleRows);
  await writeJson(pathFromRoot(`${resultsDir}/asset_summary.json`), {
    generatedAt: new Date().toISOString(),
    status: "ready",
    pairId,
    source: "ENA direct full FASTQ gzip files for SEQC2/HCC1395 minimal WES pair",
    fullWesFastqs: fastqAssets,
    resourcePolicy: {
      duplicateMarking: "run GATK MarkDuplicates on full WES BAMs",
      mutect2GermlineResource: "Broad gatk-best-practices somatic-hg38 af-only gnomAD",
      mutect2PanelOfNormals: "Broad gatk-best-practices somatic-hg38 1000g PoN",
      commonBiallelicResource: "common-biallelic af-only gnomAD chr1-22XY resource for GetPileupSummaries/contamination",
      bqsr: "deferred until matching known-sites and capture interval policy are selected",
      contamination: "run on benchmark intervals when common biallelic sites overlap",
      intervalStrategy:
        "derive covered SEQC2 truth-overlap intervals from full WES BAMs; report sensitivity/precision only inside the bounded interval set"
    },
    resources: resourceAssets,
    reference: {
      referenceId: reference.reference_id,
      assembly: reference.assembly,
      genomeBuild: reference.genome_build,
      fastaPath: reference.fasta_path,
      fastaSha256: reference.fasta_sha256,
      dictPath: reference.fasta_path.replace(/\.(fa|fasta)$/i, ".dict")
    },
    tools: {
      java: javaPath,
      gatkJar,
      bwa: commandPath("bwa"),
      samtools: commandPath("samtools"),
      bcftools: commandPath("bcftools")
    }
  });

  console.log(`Full WES benchmark assets ready: ${fastqAssets.length} FASTQ files and ${resourceAssets.length} Mutect2 resources.`);
}

await main();
