import { ensureDir, fetchText, parseCsv, parseDelimited, pathFromRoot, writeCsv, writeJson } from "./lib";

type Candidate = {
  pair_id: string;
  role: "tumor" | "normal";
  run: string;
  assay: "WES" | "WGS";
  phase: string;
  priority: number;
  use_case: string;
  caveat: string;
};

const runInfoUrl = "https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo";
const enaRunReportUrl = "https://www.ebi.ac.uk/ena/portal/api/filereport";
const seqc2Study = "SRP162370";
const truthSetRoot = "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/";

const candidates: Candidate[] = [
  {
    pair_id: "seqc2_hcc1395_wes_minimal_smoke",
    role: "tumor",
    run: "SRR7890850",
    assay: "WES",
    phase: "phase-2a-local-smoke",
    priority: 1,
    use_case: "Smallest practical paired-end WES tumor run for FASTQ conversion, sample-sheet wiring, QC, alignment, and somatic-calling plumbing.",
    caveat: "Still multi-GB; use targeted/downsampled smoke locally before full WES."
  },
  {
    pair_id: "seqc2_hcc1395_wes_minimal_smoke",
    role: "normal",
    run: "SRR7890851",
    assay: "WES",
    phase: "phase-2a-local-smoke",
    priority: 1,
    use_case: "Matched normal for the minimal WES tumor smoke run.",
    caveat: "Still multi-GB; use targeted/downsampled smoke locally before full WES."
  },
  {
    pair_id: "seqc2_hcc1395_wes_ffpe_like",
    role: "tumor",
    run: "SRR7890945",
    assay: "WES",
    phase: "phase-2b-ffpe-stress",
    priority: 2,
    use_case: "FFPE/process-stress WES tumor run to exercise artifact/QC handling before Diana FFPE-derived data arrives.",
    caveat: "FFPE-like benchmark for plumbing and QC; not Diana tissue and not HRD clinical truth."
  },
  {
    pair_id: "seqc2_hcc1395_wes_ffpe_like",
    role: "normal",
    run: "SRR7890963",
    assay: "WES",
    phase: "phase-2b-ffpe-stress",
    priority: 2,
    use_case: "Matched normal for FFPE/process-stress WES run.",
    caveat: "FFPE-like benchmark for plumbing and QC; not Diana tissue and not HRD clinical truth."
  },
  {
    pair_id: "seqc2_hcc1395_wgs_hiseqx_full",
    role: "tumor",
    run: "SRR7890824",
    assay: "WGS",
    phase: "phase-2c-wgs-full",
    priority: 3,
    use_case: "HiSeq X Ten WGS tumor benchmark for raw WGS pipeline, SV/signature readiness, and HCC1395 truth-set comparison.",
    caveat: "About 65 GB SRA input for this run alone; use cloud/HPC or regional/downsampled smoke first."
  },
  {
    pair_id: "seqc2_hcc1395_wgs_hiseqx_full",
    role: "normal",
    run: "SRR7890827",
    assay: "WGS",
    phase: "phase-2c-wgs-full",
    priority: 3,
    use_case: "Matched normal for HiSeq X Ten WGS tumor benchmark.",
    caveat: "About 70 GB SRA input for this run alone; use cloud/HPC or regional/downsampled smoke first."
  },
  {
    pair_id: "seqc2_hcc1395_wgs_novaseq_full",
    role: "tumor",
    run: "SRR7890905",
    assay: "WGS",
    phase: "phase-2c-wgs-full",
    priority: 4,
    use_case: "NovaSeq WGS tumor benchmark to test modern platform behavior and cross-platform robustness.",
    caveat: "Large WGS run; not a local first pass."
  },
  {
    pair_id: "seqc2_hcc1395_wgs_novaseq_full",
    role: "normal",
    run: "SRR7890943",
    assay: "WGS",
    phase: "phase-2c-wgs-full",
    priority: 4,
    use_case: "Matched normal for NovaSeq WGS tumor benchmark.",
    caveat: "Large WGS run; not a local first pass."
  }
];

async function main() {
  ensureDir(pathFromRoot("data/processed/catalog"));
  ensureDir(pathFromRoot("manifests"));

  const runs = candidates.map((candidate) => candidate.run);
  const runInfoText = await fetchText(`${runInfoUrl}?acc=${runs.join(",")}`);
  const runInfo = parseCsv(runInfoText);
  const byRun = new Map(runInfo.map((row) => [row.Run, row]));
  const enaRows = [];
  for (const run of runs) {
    const enaText = await fetchText(
      `${enaRunReportUrl}?accession=${run}&result=read_run&fields=run_accession,fastq_ftp,fastq_md5,fastq_bytes,library_layout,library_strategy,instrument_platform,instrument_model,sample_alias&format=tsv`
    );
    enaRows.push(...parseDelimited(enaText, "\t"));
  }
  const enaByRun = new Map(enaRows.map((row) => [row.run_accession, row]));

  const manifestRows = candidates.map((candidate) => {
    const row = byRun.get(candidate.run);
    if (!row) {
      throw new Error(`Missing SRA runinfo row for ${candidate.run}`);
    }
    const ena = enaByRun.get(candidate.run);
    if (!ena) {
      throw new Error(`Missing ENA FASTQ row for ${candidate.run}`);
    }
    const fastqUrls = (ena.fastq_ftp ?? "").split(";").filter(Boolean).map((url) => `https://${url}`);
    const fastqMd5s = (ena.fastq_md5 ?? "").split(";").filter(Boolean);
    const fastqBytes = (ena.fastq_bytes ?? "").split(";").filter(Boolean);
    if (fastqUrls.length !== 2) {
      throw new Error(`Expected paired FASTQ URLs for ${candidate.run}, got ${fastqUrls.length}`);
    }
    return {
      pair_id: candidate.pair_id,
      role: candidate.role,
      run: candidate.run,
      assay: candidate.assay,
      phase: candidate.phase,
      priority: candidate.priority,
      sra_study: row.SRAStudy,
      bioproject: row.BioProject,
      experiment: row.Experiment,
      library_name: row.LibraryName,
      library_strategy: row.LibraryStrategy,
      library_layout: row.LibraryLayout,
      sample_name: row.SampleName,
      biosample: row.BioSample,
      platform: row.Platform,
      model: row.Model,
      spots: row.spots,
      bases: row.bases,
      avg_length: row.avgLength,
      size_mb: row.size_MB,
      consent: row.Consent,
      download_path: row.download_path,
      fastq_1_url: fastqUrls[0],
      fastq_2_url: fastqUrls[1],
      fastq_1_md5: fastqMd5s[0] ?? "",
      fastq_2_md5: fastqMd5s[1] ?? "",
      fastq_1_bytes: fastqBytes[0] ?? "",
      fastq_2_bytes: fastqBytes[1] ?? "",
      use_case: candidate.use_case,
      caveat: candidate.caveat
    };
  });

  await writeCsv(pathFromRoot("data/processed/catalog/seqc2_sra_runinfo_selected.csv"), runInfo);
  await writeCsv(pathFromRoot("data/processed/catalog/seqc2_ena_fastq_selected.csv"), enaRows);
  await writeCsv(pathFromRoot("manifests/raw_representative_panel.csv"), manifestRows);
  await writeJson(pathFromRoot("manifests/raw_representative_panel_summary.json"), {
    generatedAt: new Date().toISOString(),
    source: `${runInfoUrl}?acc=${runs.join(",")}`,
    study: seqc2Study,
    truthSetRoot,
    pairCount: new Set(candidates.map((candidate) => candidate.pair_id)).size,
    runCount: manifestRows.length,
    allPublic: manifestRows.every((row) => row.consent === "public"),
    phases: Array.from(new Set(candidates.map((candidate) => candidate.phase))),
    boundaries: [
      "These are representative raw-data candidates, not Diana data.",
      "SRA paths may point to SRA Lite objects; verify quality handling before sensitivity benchmarking.",
      "Use small regional/downsampled smoke runs locally before full WGS.",
      "Use SEQC2 truth-set FTP outputs for caller comparison when full raw calling is attempted."
    ]
  });

  console.log(`Wrote ${manifestRows.length} representative raw-data run candidates from ${seqc2Study}.`);
}

await main();
