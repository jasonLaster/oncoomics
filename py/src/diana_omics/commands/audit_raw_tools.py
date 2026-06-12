from __future__ import annotations

import os
import re
import subprocess
from typing import Any, cast

from ..paths import path_from_root
from ..utils import command_path, ensure_dir, iso_now, write_json, write_text

TOOL_GROUPS = [
    {
        "group": "baseline_streaming",
        "requiredFor": "Phase 2A direct FASTQ metadata and tiny read-subset smoke",
        "tools": ["curl", "gunzip", "gzip", "python3"],
    },
    {
        "group": "sra_conversion",
        "requiredFor": "NCBI SRA prefetch and local full-run conversion",
        "tools": ["prefetch", "fasterq-dump", "fastq-dump", "vdb-config"],
    },
    {"group": "qc", "requiredFor": "Standard FASTQ QC and aggregate reports", "tools": ["fastqc", "multiqc", "seqtk", "seqkit"]},
    {
        "group": "alignment_and_bam",
        "requiredFor": "Reference alignment and BAM/CRAM generation",
        "tools": ["bwa", "bwa-mem2", "minimap2", "samtools"],
    },
    {"group": "caller_smoke", "requiredFor": "Tiny local variant-caller smoke and VCF contract checks", "tools": ["bcftools"]},
    {
        "group": "production_somatic_caller",
        "requiredFor": "Phase 2E GATK Mutect2 production-style tumor-normal somatic smoke",
        "tools": ["java17", "unzip"],
    },
    {
        "group": "full_wes_benchmark",
        "requiredFor": "Phase 2F full WES benchmark download, duplicate marking, contamination, and truth-overlap calling",
        "tools": ["curl", "gzip", "bwa", "samtools", "bcftools", "java17"],
    },
    {
        "group": "phase3_wgs_smoke",
        "requiredFor": "Phase 3 representative WGS alignment, Mutect2, coverage-CNV bins, SBS96 matrix, and BAM-derived SV evidence",
        "tools": ["curl", "gunzip", "gzip", "bwa", "samtools", "bcftools", "java17"],
    },
    {
        "group": "phase3_wgs_optional_signature_callers",
        "requiredFor": "Full-depth WGS CHORD/scarHRD/HRDetect/SigProfiler production interpretation",
        "tools": ["R", "python3", "nextflow", "docker", "singularity", "apptainer"],
    },
    {
        "group": "workflow_runtime",
        "requiredFor": "nf-core/sarek or containerized raw-data workflow execution",
        "tools": ["nextflow", "docker", "singularity", "apptainer", "conda", "micromamba"],
    },
]


def java17_path() -> str:
    candidates = [
        os.environ.get("GATK_JAVA", ""),
        os.path.join(os.environ.get("JAVA_HOME", ""), "bin", "java") if os.environ.get("JAVA_HOME") else "",
        command_path("java"),
        "/usr/bin/java",
        "/opt/homebrew/opt/openjdk@17/bin/java",
        "/opt/homebrew/bin/java",
    ]
    for candidate in [candidate for candidate in candidates if candidate]:
        if not os.path.exists(candidate):
            continue
        result = subprocess.run([candidate, "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        output = f"{result.stdout}{result.stderr}"
        match = re.search(r'version "(\d+)', output)
        if result.returncode == 0 and match and int(match.group(1)) >= 17:
            return candidate
    return ""


def tool_path(tool: str) -> str:
    if tool == "java17":
        return java17_path()
    return command_path(tool)


def available_tools(group_name: str, groups: list[dict[str, Any]]) -> list[str]:
    for group in groups:
        if group["group"] == group_name:
            return [tool["tool"] for tool in group["tools"] if tool["available"]]
    return []


def main() -> None:
    ensure_dir(path_from_root("results/raw_smoke"))
    groups: list[dict[str, Any]] = []
    for group in TOOL_GROUPS:
        tools = [{"tool": tool, "path": tool_path(tool), "available": bool(tool_path(tool))} for tool in group["tools"]]
        groups.append({**group, "tools": tools, "allAvailable": all(tool["available"] for tool in tools)})

    phase2a_ready = next((group["allAvailable"] for group in groups if group["group"] == "baseline_streaming"), False)
    aligners = [tool for tool in available_tools("alignment_and_bam", groups) if tool in ["bwa", "bwa-mem2", "minimap2"]]
    bam_tools = [tool for tool in available_tools("alignment_and_bam", groups) if tool == "samtools"]
    alignment_ready = bool(aligners) and "samtools" in bam_tools
    full_alignment_toolbox_ready = next((group["allAvailable"] for group in groups if group["group"] == "alignment_and_bam"), False)
    workflow_ready = any(tool["available"] for group in groups if group["group"] == "workflow_runtime" for tool in group["tools"])
    full_workflow_ready = workflow_ready and any(tool["available"] for group in groups if group["group"] == "qc" for tool in group["tools"])
    human_reference_smoke_ready = phase2a_ready and alignment_ready
    caller_smoke_ready = next((group["allAvailable"] for group in groups if group["group"] == "caller_smoke"), False)
    full_reference_smoke_ready = human_reference_smoke_ready and caller_smoke_ready
    production_somatic_tool_ready = next(
        (group["allAvailable"] for group in groups if group["group"] == "production_somatic_caller"), False
    )
    production_somatic_smoke_ready = full_reference_smoke_ready and production_somatic_tool_ready
    full_wes_benchmark_tool_ready = next((group["allAvailable"] for group in groups if group["group"] == "full_wes_benchmark"), False)
    full_wes_benchmark_ready = production_somatic_smoke_ready and full_wes_benchmark_tool_ready
    phase3_wgs_tool_ready = next((group["allAvailable"] for group in groups if group["group"] == "phase3_wgs_smoke"), False)
    phase3_wgs_validation_ready = full_wes_benchmark_ready and phase3_wgs_tool_ready
    phase3_optional_signature_runtime_ready = any(
        tool["available"] for group in groups if group["group"] == "phase3_wgs_optional_signature_callers" for tool in group["tools"]
    )
    conclusion = (
        "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, Phase 2D full-reference caller-readiness smoke tests, Phase 2E GATK Mutect2 production-style somatic smoke tests, Phase 2F full WES benchmark mechanics, and Phase 3 full-source WGS validation mechanics. Final HRD interpretation still requires Diana data and reviewer-approved CNV/SV/signature policy."
        if phase3_wgs_validation_ready
        else "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, Phase 2D full-reference caller-readiness smoke tests, Phase 2E GATK Mutect2 production-style somatic smoke tests, and Phase 2F full WES benchmark mechanics. Full WGS signature phases still require WGS data and additional CNV/SV/signature tooling."
        if full_wes_benchmark_ready
        else "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, Phase 2D full-reference caller-readiness smoke tests, and Phase 2E GATK Mutect2 production-style somatic smoke tests. Full workflow/WGS signature phases still require additional tools, resources, or containers."
        if production_somatic_smoke_ready
        else "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, Phase 2C partial human-reference alignment smoke tests, and Phase 2D full-reference caller-readiness smoke tests. Phase 2E Mutect2 smoke requires Java 17 and unzip for the pinned GATK bundle."
        if full_reference_smoke_ready
        else "Local machine can run Phase 2A direct-FASTQ smoke tests, Phase 2B local BAM alignment smoke tests, and Phase 2C partial human-reference alignment smoke tests. Phase 2D caller smoke requires bcftools or another pinned caller."
        if human_reference_smoke_ready
        else "Local machine can run Phase 2A direct-FASTQ smoke tests. Phase 2B local BAM smoke requires at least one short-read aligner and samtools."
        if phase2a_ready
        else "Local machine is missing baseline streaming tools required for Phase 2A."
    )
    audit = {
        "generatedAt": iso_now(),
        "phase2aReady": phase2a_ready,
        "alignmentReady": alignment_ready,
        "humanReferenceSmokeReady": human_reference_smoke_ready,
        "callerSmokeReady": caller_smoke_ready,
        "fullReferenceSmokeReady": full_reference_smoke_ready,
        "productionSomaticToolReady": production_somatic_tool_ready,
        "productionSomaticSmokeReady": production_somatic_smoke_ready,
        "fullWesBenchmarkToolReady": full_wes_benchmark_tool_ready,
        "fullWesBenchmarkReady": full_wes_benchmark_ready,
        "phase3WgsToolReady": phase3_wgs_tool_ready,
        "phase3WgsSmokeReady": phase3_wgs_validation_ready,
        "phase3WgsValidationReady": phase3_wgs_validation_ready,
        "phase3OptionalSignatureRuntimeReady": phase3_optional_signature_runtime_ready,
        "fullAlignmentToolboxReady": full_alignment_toolbox_ready,
        "workflowReady": workflow_ready,
        "fullWorkflowReady": full_workflow_ready,
        "alignmentReadyDefinition": "At least one short-read aligner from bwa/bwa-mem2/minimap2 plus samtools.",
        "groups": groups,
        "conclusion": conclusion,
    }
    write_json(path_from_root("results/raw_smoke/tooling_audit.json"), audit)
    group_sections = []
    for group in groups:
        tools = cast(list[dict[str, Any]], group["tools"])
        rows = "\n".join(f"- {tool['tool']}: {tool['path'] if tool['available'] else 'missing'}" for tool in tools)
        group_sections.append(f"## {group['group']}\n\nRequired for: {group['requiredFor']}\n\n{rows}")
    group_markdown = "\n\n".join(group_sections)
    write_text(
        path_from_root("results/raw_smoke/tooling_audit.md"),
        f"""# Raw Tooling Audit

Phase 2A direct-FASTQ smoke ready: **{"yes" if phase2a_ready else "no"}**

Alignment/BAM ready locally: **{"yes" if alignment_ready else "no"}**

Full aligner toolbox available: **{"yes" if full_alignment_toolbox_ready else "no"}**

Workflow/container runtime available: **{"yes" if workflow_ready else "no"}**

Full QC/workflow runtime available: **{"yes" if full_workflow_ready else "no"}**

Alignment-ready definition: {audit["alignmentReadyDefinition"]}

Phase 2C partial human-reference smoke ready: **{"yes" if human_reference_smoke_ready else "no"}**

Phase 2D full-reference caller-readiness smoke ready: **{"yes" if full_reference_smoke_ready else "no"}**

Phase 2E production somatic Mutect2 smoke ready: **{"yes" if production_somatic_smoke_ready else "no"}**

Phase 2F full WES benchmark ready: **{"yes" if full_wes_benchmark_ready else "no"}**

Phase 3 WGS validation toolchain ready: **{"yes" if phase3_wgs_validation_ready else "no"}**

Phase 3 optional signature runtime available: **{"yes" if phase3_optional_signature_runtime_ready else "no"}**

{group_markdown}

## Conclusion

{conclusion}
""",
    )
    print(conclusion)


if __name__ == "__main__":
    main()
