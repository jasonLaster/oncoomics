import { spawnSync } from "node:child_process";
import { ensureDir, pathFromRoot, writeJson, writeText } from "./lib";

const toolGroups = [
  {
    group: "baseline_streaming",
    requiredFor: "Phase 2A direct FASTQ metadata and tiny read-subset smoke",
    tools: ["bun", "curl", "gunzip", "gzip", "python3"]
  },
  {
    group: "sra_conversion",
    requiredFor: "NCBI SRA prefetch and local full-run conversion",
    tools: ["prefetch", "fasterq-dump", "fastq-dump", "vdb-config"]
  },
  {
    group: "qc",
    requiredFor: "Standard FASTQ QC and aggregate reports",
    tools: ["fastqc", "multiqc", "seqtk", "seqkit"]
  },
  {
    group: "alignment_and_bam",
    requiredFor: "Reference alignment and BAM/CRAM generation",
    tools: ["bwa", "bwa-mem2", "minimap2", "samtools"]
  },
  {
    group: "caller_smoke",
    requiredFor: "Tiny local variant-caller smoke and VCF contract checks",
    tools: ["bcftools"]
  },
  {
    group: "production_somatic_caller",
    requiredFor: "Phase 2E GATK Mutect2 production-style tumor-normal somatic smoke",
    tools: ["java17", "unzip"]
  },
  {
    group: "full_wes_benchmark",
    requiredFor: "Phase 2F full WES benchmark download, duplicate marking, contamination, and truth-overlap calling",
    tools: ["curl", "gzip", "bwa", "samtools", "bcftools", "java17"]
  },
  {
    group: "workflow_runtime",
    requiredFor: "nf-core/sarek or containerized raw-data workflow execution",
    tools: ["nextflow", "docker", "singularity", "apptainer", "conda", "micromamba"]
  }
];

function java17Path() {
  const candidates = [
    process.env.GATK_JAVA ?? "",
    "/opt/homebrew/opt/openjdk@17/bin/java",
    "/opt/homebrew/bin/java",
    spawnSync("bash", ["-lc", "command -v java"], { encoding: "utf8" }).stdout.trim()
  ].filter(Boolean);
  for (const candidate of candidates) {
    const result = spawnSync(candidate, ["-version"], { encoding: "utf8" });
    const output = `${result.stdout}${result.stderr}`;
    const major = Number(output.match(/version "(\d+)/)?.[1] ?? "0");
    if (result.status === 0 && major >= 17) {
      return candidate;
    }
  }
  return "";
}

function commandPath(tool: string) {
  if (tool === "bun" && process.argv[0]) {
    return process.argv[0];
  }
  if (tool === "java17") {
    return java17Path();
  }
  const result = spawnSync("bash", ["-lc", `command -v ${tool}`], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
}

function availableTools(groupName: string, groups: Array<{ group: string; tools: Array<{ tool: string; available: boolean }> }>) {
  return groups.find((group) => group.group === groupName)?.tools.filter((tool) => tool.available).map((tool) => tool.tool) ?? [];
}

async function main() {
  ensureDir(pathFromRoot("results/raw_smoke"));

  const groups = toolGroups.map((group) => {
    const tools = group.tools.map((tool) => ({
      tool,
      path: commandPath(tool),
      available: Boolean(commandPath(tool))
    }));
    return {
      ...group,
      tools,
      allAvailable: tools.every((tool) => tool.available)
    };
  });

  const phase2aReady = groups.find((group) => group.group === "baseline_streaming")?.allAvailable ?? false;
  const aligners = availableTools("alignment_and_bam", groups).filter((tool) => ["bwa", "bwa-mem2", "minimap2"].includes(tool));
  const bamTools = availableTools("alignment_and_bam", groups).filter((tool) => tool === "samtools");
  const alignmentReady = aligners.length > 0 && bamTools.includes("samtools");
  const fullAlignmentToolboxReady = groups.find((group) => group.group === "alignment_and_bam")?.allAvailable ?? false;
  const workflowReady = groups.find((group) => group.group === "workflow_runtime")?.tools.some((tool) => tool.available) ?? false;
  const fullWorkflowReady = workflowReady && groups.find((group) => group.group === "qc")?.tools.some((tool) => tool.available) === true;
  const humanReferenceSmokeReady = phase2aReady && alignmentReady;
  const callerSmokeReady = groups.find((group) => group.group === "caller_smoke")?.allAvailable ?? false;
  const fullReferenceSmokeReady = humanReferenceSmokeReady && callerSmokeReady;
  const productionSomaticToolReady = groups.find((group) => group.group === "production_somatic_caller")?.allAvailable ?? false;
  const productionSomaticSmokeReady = fullReferenceSmokeReady && productionSomaticToolReady;
  const fullWesBenchmarkToolReady = groups.find((group) => group.group === "full_wes_benchmark")?.allAvailable ?? false;
  const fullWesBenchmarkReady = productionSomaticSmokeReady && fullWesBenchmarkToolReady;

  const audit = {
    generatedAt: new Date().toISOString(),
    phase2aReady,
    alignmentReady,
    humanReferenceSmokeReady,
    callerSmokeReady,
    fullReferenceSmokeReady,
    productionSomaticToolReady,
    productionSomaticSmokeReady,
    fullWesBenchmarkToolReady,
    fullWesBenchmarkReady,
    fullAlignmentToolboxReady,
    workflowReady,
    fullWorkflowReady,
    alignmentReadyDefinition: "At least one short-read aligner from bwa/bwa-mem2/minimap2 plus samtools.",
    groups,
    conclusion: fullWesBenchmarkReady
      ? "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, Phase 2D full-reference caller-readiness smoke tests, Phase 2E GATK Mutect2 production-style somatic smoke tests, and Phase 2F full WES benchmark mechanics. Full WGS signature phases still require WGS data and additional CNV/SV/signature tooling."
      : productionSomaticSmokeReady
        ? "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, Phase 2D full-reference caller-readiness smoke tests, and Phase 2E GATK Mutect2 production-style somatic smoke tests. Phase 2F full WES benchmark requires curl, gzip, bwa, samtools, bcftools, and Java 17."
      : fullReferenceSmokeReady
        ? "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, and Phase 2D full-reference caller-readiness smoke tests. Phase 2E Mutect2 smoke requires Java 17 and unzip for the pinned GATK bundle."
      : humanReferenceSmokeReady
        ? "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, and Phase 2C partial human-reference alignment smoke tests. Phase 2D caller smoke requires bcftools or another pinned caller."
      : phase2aReady
        ? "Local machine can run Phase 2A direct-FASTQ smoke tests. Phase 2B local BAM smoke requires at least one short-read aligner and samtools."
        : "Local machine is missing baseline streaming tools required for Phase 2A."
  };

  await writeJson(pathFromRoot("results/raw_smoke/tooling_audit.json"), audit);
  await writeText(
    pathFromRoot("results/raw_smoke/tooling_audit.md"),
    `# Raw Tooling Audit

Phase 2A direct-FASTQ smoke ready: **${phase2aReady ? "yes" : "no"}**

Alignment/BAM ready locally: **${alignmentReady ? "yes" : "no"}**

Full aligner toolbox available: **${fullAlignmentToolboxReady ? "yes" : "no"}**

Workflow/container runtime available: **${workflowReady ? "yes" : "no"}**

Full QC/workflow runtime available: **${fullWorkflowReady ? "yes" : "no"}**

Alignment-ready definition: ${audit.alignmentReadyDefinition}

Phase 2C partial human-reference smoke ready: **${humanReferenceSmokeReady ? "yes" : "no"}**

Phase 2D full-reference caller-readiness smoke ready: **${fullReferenceSmokeReady ? "yes" : "no"}**

Phase 2E production somatic Mutect2 smoke ready: **${productionSomaticSmokeReady ? "yes" : "no"}**

Phase 2F full WES benchmark ready: **${fullWesBenchmarkReady ? "yes" : "no"}**

${groups
  .map((group) => {
    const rows = group.tools.map((tool) => `- ${tool.tool}: ${tool.available ? tool.path : "missing"}`).join("\n");
    return `## ${group.group}\n\nRequired for: ${group.requiredFor}\n\n${rows}`;
  })
  .join("\n\n")}

## Conclusion

${audit.conclusion}
`
  );

  console.log(audit.conclusion);
}

await main();
