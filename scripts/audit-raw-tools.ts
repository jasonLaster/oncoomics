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
    group: "workflow_runtime",
    requiredFor: "nf-core/sarek or containerized raw-data workflow execution",
    tools: ["nextflow", "docker", "singularity", "apptainer", "conda", "micromamba"]
  }
];

function commandPath(tool: string) {
  if (tool === "bun" && process.argv[0]) {
    return process.argv[0];
  }
  const result = spawnSync("bash", ["-lc", `command -v ${tool}`], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
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
  const alignmentReady = groups.find((group) => group.group === "alignment_and_bam")?.allAvailable ?? false;
  const workflowReady = groups.find((group) => group.group === "workflow_runtime")?.tools.some((tool) => tool.available) ?? false;

  const audit = {
    generatedAt: new Date().toISOString(),
    phase2aReady,
    alignmentReady,
    workflowReady,
    groups,
    conclusion: phase2aReady
      ? "Local machine can run Phase 2A direct-FASTQ smoke tests. Alignment/caller phases require additional tools or containers."
      : "Local machine is missing baseline streaming tools required for Phase 2A."
  };

  await writeJson(pathFromRoot("results/raw_smoke/tooling_audit.json"), audit);
  await writeText(
    pathFromRoot("results/raw_smoke/tooling_audit.md"),
    `# Raw Tooling Audit

Phase 2A direct-FASTQ smoke ready: **${phase2aReady ? "yes" : "no"}**

Alignment/BAM ready locally: **${alignmentReady ? "yes" : "no"}**

Workflow/container runtime available: **${workflowReady ? "yes" : "no"}**

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

