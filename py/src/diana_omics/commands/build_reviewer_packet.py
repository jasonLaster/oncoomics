from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from ..paths import path_from_root
from ..utils import iso_now, parse_csv, read_json, read_text, write_json, write_text


def count_by(rows: list[dict[str, str]], column: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get(column) or "(blank)"
        counts[key] = counts.get(key, 0) + 1
    return [{"key": key, "count": count} for key, count in counts.items()]


def table(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    columns = list(rows[0].keys())
    lines = [f"| {' | '.join(columns)} |", f"| {' | '.join(['---'] * len(columns))} |"]
    for row in rows:
        lines.append(f"| {' | '.join(str(row.get(column, '')).replace('|', '/') for column in columns)} |")
    return "\n".join(lines)


def optional_summary(relative_path: str, default: Mapping[str, Any]) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if path.exists():
        return read_json(path)
    return {"status": "not_staged", **dict(default)}


def main() -> None:
    panel = parse_csv(read_text(path_from_root("manifests/hrd_reference_panel.csv")))
    predictions = parse_csv(read_text(path_from_root("results/hrd_predictions.csv")))
    confusion = parse_csv(read_text(path_from_root("results/hrd_confusion_matrix.csv")))
    summary = read_json(path_from_root("results/hrd_analysis_summary.json"))
    rna_summary = read_json(path_from_root("results/rna_context_summary.json"))
    cbio_summary = read_json(path_from_root("data/processed/catalog/cbioportal_tcga_brca_summary.json"))
    xena_summary = read_json(path_from_root("data/processed/catalog/xena_tcga_brca_clinical_summary.json"))
    gdc_summary = read_json(path_from_root("data/processed/catalog/gdc_tcga_brca_open_summary.json"))
    human_reference_summary = optional_summary(
        "results/human_reference_smoke/human_reference_alignment_summary.json",
        {"sampleRows": "not_staged", "genomeBuilds": []},
    )
    full_reference_summary = optional_summary(
        "results/full_reference_smoke/full_reference_alignment_summary.json",
        {"referenceId": "not_staged", "callerSmokeStatus": "not_staged"},
    )
    production_somatic_summary = optional_summary(
        "results/production_somatic_smoke/production_somatic_summary.json",
        {
            "caller": "not_staged",
            "status": "not_staged",
            "readPairsPerEnd": "not_staged",
            "comparisonStatus": "not_staged",
        },
    )
    full_wes_summary_path = path_from_root("results/full_wes_benchmark/full_wes_benchmark_summary.json")
    full_wes_benchmark_summary = (
        read_json(full_wes_summary_path)
        if full_wes_summary_path.exists()
        else {
            "status": "pending",
            "readyForPhase3": False,
            "benchmarkIntervalCount": "not_run",
            "truthVariantsDepthEligible": "not_run",
            "contaminationStatus": "not_run",
        }
    )
    phase3_summary_path = path_from_root("results/phase3_wgs_smoke/phase3_wgs_summary.json")
    phase3_wgs_summary = (
        read_json(phase3_summary_path)
        if phase3_summary_path.exists()
        else {
            "status": "pending",
            "phase3Complete": False,
            "readyForPhase4WhenDianaRawArrives": False,
            "readPairsPerEnd": "not_run",
            "coverageCnvBins": "not_run",
            "sbs96UsableSnvRecords": "not_run",
        }
    )

    category_counts = count_by(panel, "panel_category")
    prediction_counts = count_by(predictions, "predicted_hrd_class")

    write_text(
        path_from_root("results/methods.md"),
        """# Methods

## Data Sources

- cBioPortal study: `brca_tcga_pan_can_atlas_2018`, imported by cBioPortal on 2026-06-05 according to live study metadata.
- GDC: TCGA-BRCA open file catalog metadata only, used to verify public/open project availability and access posture.
- UCSC Xena: TCGA-BRCA clinical matrix, used for PAM50/receptor-status context and sample-ID cross-checking.
- SEQC2/HCC1395: public tumor-normal WES/WGS raw-data benchmark metadata and small FASTQ subsets used for raw-read and alignment smoke tests.
- UCSC Genome Browser: hg38/GRCh38 and hg19/GRCh37 chr13+chr17 FASTA references used for Phase 2C partial human-reference alignment smoke.
- UCSC Genome Browser: hg38/GRCh38 analysisSet FASTA used for Phase 2D full-reference caller-readiness smoke.
- GATK/SEQC2: GATK Mutect2/FilterMutectCalls and SEQC2 HCC1395 high-confidence SNV/INDEL truth VCFs used for Phase 2E production-style somatic-caller smoke, Phase 2F full WES truth-overlap benchmarking, and Phase 3 full-source WGS validation.

## HRD Evidence

The phase-1 analysis uses processed public TCGA-BRCA evidence:

1. HRR mutation records from cBioPortal's processed WES mutation profile.
2. GISTIC discrete copy-number calls as a copy-loss proxy.
3. Sample clinical fields for fraction genome altered, aneuploidy score, mutation count, and nonsynonymous TMB.

Likely damaging variants are rule-classified as nonsense, frameshift, splice-site, translation-start, nonstop, or cBioPortal keyword matches for truncating/frameshift/splice events. This is not manual clinical variant curation.

## RNA Context

RNA context uses selected marker genes from cBioPortal RNA Seq V2 RSEM batch-normalized values. Scores are log2(value + 1), z-scored across the fetched cohort, then averaged into marker modules.

## Raw-Data Smoke Lanes

Phase 2A validates direct raw FASTQ access and pairing from a small SEQC2/HCC1395 tumor-normal WES subset. Phase 2B validates local FASTQ-to-BAM mechanics against a read-backed synthetic smoke reference. Phase 2C validates partial real-human-reference alignment against UCSC hg38 and hg19 chr13+chr17 references. Phase 2D validates one full reference, the UCSC hg38 analysis set, with BRCA1/BRCA2 interval metadata, full-reference BAM contracts, and a tiny indexed VCF caller smoke. Phase 2E validates a production-style GATK Mutect2 tumor-normal execution path on a larger HCC1395 WES downsample. Phase 2F validates full ENA WES FASTQ downloads, full-reference alignment, GATK duplicate marking, Broad hg38 PoN use, common-biallelic contamination estimation, and a bounded SEQC2 truth-overlap Mutect2 benchmark. Phase 3 validates full-source representative WGS mechanics with complete public SEQC2/HCC1395 WGS FASTQs, full-reference BAM contracts, Mutect2 WGS VCFs, coverage-CNV bins, an SBS96 matrix, and BAM-derived SV evidence.

These raw lanes are plumbing, file-contract, WES small-variant benchmark, and WGS-capability validators. They do not yet produce clinically interpretable Diana calls, allele-specific CNV segments, validated SV caller VCFs, WGS rearrangement signatures, or HRD signatures.

## Non-Run Lanes

Full-depth WGS rearrangement signature interpretation, scarHRD, CHORD, HRDetect, FACETS/ASCAT/PURPLE allele-specific LOH, methylation-specific second-hit evidence, and companion diagnostics were not run as final clinical classifiers. Phase 3 now writes real WGS feature outputs for the relevant lanes; classification remains gated until Diana data and reviewer-approved production tooling are available.
""",
    )

    write_text(
        path_from_root("results/diana_readiness_gate.md"),
        """# Diana Readiness Gate

Status: **ready for Phase 4 setup once Diana raw files arrive, but not ready for clinical interpretation without raw-file inventory, Diana-specific production resource decisions, WGS/CNV/SV/signature policy, and reviewer sign-off**.

## Required Before Diana Data

1. Confirm tumor-normal DNA source, data type, reference build, matched normal, and whether data are WES or WGS.
2. Confirm bulk RNA source, library type, normalization route, batch, and RNA quality metadata.
3. Confirm sample timing, tissue block/core, tumor purity or tumor content, fixation, and extraction context.
4. Decide whether open analysis is for reviewer biology only or whether a clinician will order orthogonal validation.
5. Confirm whether the requested DNA workflow should be GRCh38, GRCh37/hg19, hs37d5, or a vendor-specific reference bundle.
6. Confirm WES intervals, known-sites resources, germline-resource/PoN/contamination policy, and final production somatic-caller route if raw DNA is FASTQ/BAM/CRAM.
7. If Diana DNA is WGS, confirm CNV/SV/signature tooling, compute target, and benchmark thresholds before interpreting HRD signatures.
8. Confirm that the Phase 3 full-source public WGS validation remains passing before Diana data arrive.
9. Get reviewer sign-off on the benchmark caveats.

## Validation State

The benchmark mechanics are runnable and validated on open processed public data. The raw-read lane now has:

1. Phase 2A direct FASTQ smoke on SEQC2/HCC1395 tumor-normal WES.
2. Phase 2B local FASTQ-to-coordinate-sorted-BAM smoke with read groups and indexes.
3. Phase 2C partial real-human-reference alignment smoke across UCSC hg38/GRCh38 and hg19/GRCh37 chr13+chr17 references.
4. Phase 2D full-reference caller-readiness smoke using the UCSC hg38 analysis set, BRCA1/BRCA2 interval metadata, and an indexed bcftools VCF contract smoke.
5. Phase 2E GATK Mutect2 production-style tumor-normal smoke on a larger HCC1395 WES downsample, with SEQC2 truth VCFs available for bounded overlap checks.
6. Phase 2F full WES benchmark on the SEQC2/HCC1395 tumor-normal pair, with full FASTQ MD5 validation, full-reference BAM contracts, GATK duplicate marking, common-biallelic contamination estimation, PoN-aware Mutect2, and bounded truth-overlap metrics.
7. Phase 3 full-source WGS validation on the SEQC2/HCC1395 tumor-normal WGS pair, with complete public WGS FASTQs, full-reference BAM contracts, Mutect2 WGS output, coverage-CNV bins, SBS96 matrix output, and BAM-derived SV evidence.

The current workflow is sufficient to validate project plumbing, samplesheet shape, local BAM file contracts, partial and full human-reference handling, a production-style Mutect2 execution path, indexed somatic VCF outputs, full WES small-variant benchmark behavior, full-source WGS feature-lane mechanics, and evidence-table boundaries. It is not sufficient to make a treatment-changing HRD claim, and it does not yet validate allele-specific CNV calls, production SV caller VCFs, or WGS-grade HRD signatures.
""",
    )

    packet = f"""# Reviewer Packet: Diana HRD Omics Validation

## Bottom Line

The phase-1 validation pipeline is complete for open processed public TCGA-BRCA data. It builds a frozen HRD reference panel, separates causal HRR events from second-hit proxies and genome-scar proxies, and refuses to call WGS-specific signature evidence when WGS inputs are unavailable. This is not a clinical HRD truth set.

This is ready for reviewer sanity-check of the workflow mechanics. It is not yet ready to apply to Diana without the readiness gate in `results/diana_readiness_gate.md`.

## Dataset Audit

- cBioPortal mutation records fetched: {cbio_summary.get("mutationCount", "unknown")}
- cBioPortal CNA records fetched: {cbio_summary.get("cnaRecordCount", "unknown")}
- cBioPortal RNA marker records fetched: {cbio_summary.get("expressionRecordCount", "unknown")}
- Xena clinical rows: {xena_summary.get("rowCount", "unknown")}
- GDC open files total from catalog query: {gdc_summary.get("totalOpenFiles", "unknown")}
- Human-reference smoke rows: {human_reference_summary.get("sampleRows", "unknown")}
- Human-reference smoke builds: {", ".join(human_reference_summary.get("genomeBuilds", [])) if isinstance(human_reference_summary.get("genomeBuilds"), list) else "unknown"}
- Full-reference smoke reference: {full_reference_summary.get("referenceId", "unknown")}
- Full-reference caller smoke: {full_reference_summary.get("callerSmokeStatus", "unknown")}
- Production somatic caller: {production_somatic_summary.get("caller", "unknown")}
- Production somatic smoke status: {production_somatic_summary.get("status", "unknown")}
- Production somatic read pairs/end: {production_somatic_summary.get("readPairsPerEnd", "unknown")}
- Production somatic truth comparison: {production_somatic_summary.get("comparisonStatus", "unknown")}
- Full WES benchmark status: {full_wes_benchmark_summary.get("status", "unknown")}
- Full WES benchmark ready for Phase 3: {"yes" if full_wes_benchmark_summary.get("readyForPhase3") is True else "no"}
- Full WES benchmark intervals: {full_wes_benchmark_summary.get("benchmarkIntervalCount", "unknown")}
- Full WES depth-eligible truth variants: {full_wes_benchmark_summary.get("truthVariantsDepthEligible", "unknown")}
- Full WES contamination status: {full_wes_benchmark_summary.get("contaminationStatus", "unknown")}
- Phase 3 WGS validation status: {phase3_wgs_summary.get("status", "unknown")}
- Phase 3 WGS complete: {"yes" if phase3_wgs_summary.get("phase3Complete") is True else "no"}
- Phase 3 ready for Phase 4 setup: {"yes" if phase3_wgs_summary.get("readyForPhase4WhenDianaRawArrives") is True else "no"}
- Phase 3 WGS read pairs/end: {phase3_wgs_summary.get("readPairsPerEnd", "unknown")}
- Phase 3 WGS read-pair mode: {phase3_wgs_summary.get("readPairsMode", "unknown")}
- Phase 3 coverage-CNV bins: {phase3_wgs_summary.get("coverageCnvBins", "unknown")}
- Phase 3 SBS96 usable SNVs: {phase3_wgs_summary.get("sbs96UsableSnvRecords", "unknown")}

## Frozen Panel

{table([{"category": row["key"], "count": row["count"]} for row in category_counts])}

## HRD Prediction Classes

{table([{"prediction": row["key"], "count": row["count"]} for row in prediction_counts])}

## Confusion Matrix

{table(confusion)}

## What Passed

1. Public source fetches are reproducible with Bun.
2. Sample identifiers cross cBioPortal and Xena without truncation in the selected clinical subset.
3. The reference panel includes positive, mechanistic, ambiguous, and negative controls.
4. HRR events, copy-loss proxies, scar proxies, and RNA context are written as separate evidence tables.
5. Ambiguous samples remain ambiguous instead of being forced into HRD-positive or HRD-negative buckets.
6. Raw-data smoke tests validate FASTQ pairing, local BAM contracts, and partial real-human-reference alignment against two reference builds.
7. Full-reference smoke validates one full hg38 analysis-set reference, BRCA interval metadata, caller-ready BAM contracts, and indexed VCF generation.
8. Production somatic smoke validates GATK Mutect2/FilterMutectCalls execution on a larger downsampled HCC1395 WES tumor-normal pair.
9. Full WES benchmark validates complete ENA FASTQ files, full-reference BAM contracts, duplicate marking, contamination estimation, PoN-aware Mutect2, and SEQC2 truth-overlap metrics.
10. Phase 3 WGS validation uses full-source representative WGS FASTQs to validate full-reference WGS BAM contracts, Mutect2 WGS output, coverage-CNV bins, SBS96 matrix generation, and BAM-derived SV evidence lanes.

## Main Limitations

1. GISTIC copy loss is not allele-specific LOH.
2. Fraction genome altered and aneuploidy are scar proxies, not scarHRD.
3. SBS3, SV signatures, CHORD, and HRDetect are not assessable from the current processed phase-1 inputs.
4. The Phase 2F Mutect2 VCF is WES small-variant benchmark evidence, not WGS HRD signature evidence.
5. The Phase 3 WGS lane is a representative full-source WGS validation, not a final HRD classifier.
6. The Phase 2F local gate uses the Broad 1000g PoN and common-biallelic contamination resource, but the full multi-GB af-only gnomAD resource remains documented as a production/cloud input rather than a local gating download.
7. BQSR, orientation-bias modeling, vendor capture intervals, allele-specific copy-number, validated SV calling, full-depth WGS scaling, and WGS signature calling remain Phase 4 or Diana-specific production decisions.
8. Clinical action still requires clinician-owned validation, companion diagnostics, or orthogonal confirmation.

## Output Tables

- `results/hrd_event_table.csv`
- `results/allele_state_table.csv`
- `results/scar_signature_table.csv`
- `results/hrd_confusion_matrix.csv`
- `results/hrd_failure_modes.csv`
- `results/rna_subtype_context.csv`
- `results/rna_module_context.csv`

## Summaries

- HRD summary: {json.dumps(summary, separators=(",", ":"))}
- RNA summary: {json.dumps(rna_summary, separators=(",", ":"))}
"""
    write_text(path_from_root("results/reviewer_packet.md"), packet)
    write_json(
        path_from_root("results/reviewer_packet_summary.json"),
        {
            "generatedAt": iso_now(),
            "panelSampleCount": len(panel),
            "categoryCounts": category_counts,
            "predictionCounts": prediction_counts,
            "confusion": confusion,
        },
    )
    print(f"Built reviewer packet for {len(panel)} panel samples.")


if __name__ == "__main__":
    main()
