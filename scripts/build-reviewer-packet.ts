import { parseCsv, pathFromRoot, readJson, readText, writeJson, writeText } from "./lib";

function countBy(rows: Record<string, string>[], column: string) {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const key = row[column] || "(blank)";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Array.from(counts.entries()).map(([key, count]) => ({ key, count }));
}

function table(rows: Record<string, unknown>[]) {
  if (rows.length === 0) {
    return "";
  }
  const columns = Object.keys(rows[0]);
  return [
    `| ${columns.join(" | ")} |`,
    `| ${columns.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${columns.map((column) => String(row[column] ?? "").replaceAll("|", "/")).join(" | ")} |`)
  ].join("\n");
}

async function main() {
  const panel = parseCsv(readText(pathFromRoot("manifests/hrd_reference_panel.csv")));
  const predictions = parseCsv(readText(pathFromRoot("results/hrd_predictions.csv")));
  const confusion = parseCsv(readText(pathFromRoot("results/hrd_confusion_matrix.csv")));
  const summary = readJson<Record<string, unknown>>(pathFromRoot("results/hrd_analysis_summary.json"));
  const rnaSummary = readJson<Record<string, unknown>>(pathFromRoot("results/rna_context_summary.json"));
  const cbioSummary = readJson<Record<string, unknown>>(pathFromRoot("data/processed/catalog/cbioportal_tcga_brca_summary.json"));
  const xenaSummary = readJson<Record<string, unknown>>(pathFromRoot("data/processed/catalog/xena_tcga_brca_clinical_summary.json"));
  const gdcSummary = readJson<Record<string, unknown>>(pathFromRoot("data/processed/catalog/gdc_tcga_brca_open_summary.json"));
  const humanReferenceSummary = readJson<Record<string, unknown>>(
    pathFromRoot("results/human_reference_smoke/human_reference_alignment_summary.json")
  );
  const fullReferenceSummary = readJson<Record<string, unknown>>(
    pathFromRoot("results/full_reference_smoke/full_reference_alignment_summary.json")
  );
  const productionSomaticSummary = readJson<Record<string, unknown>>(
    pathFromRoot("results/production_somatic_smoke/production_somatic_summary.json")
  );
  const fullWesBenchmarkSummary = readJson<Record<string, unknown>>(
    pathFromRoot("results/full_wes_benchmark/full_wes_benchmark_summary.json")
  );
  const phase3WgsSummary = readJson<Record<string, unknown>>(
    pathFromRoot("results/phase3_wgs_smoke/phase3_wgs_summary.json")
  );

  const categoryCounts = countBy(panel, "panel_category");
  const predictionCounts = countBy(predictions, "predicted_hrd_class");

  await writeText(
    pathFromRoot("results/methods.md"),
    `# Methods

## Data Sources

- cBioPortal study: \`brca_tcga_pan_can_atlas_2018\`, imported by cBioPortal on 2026-06-05 according to live study metadata.
- GDC: TCGA-BRCA open file catalog metadata only, used to verify public/open project availability and access posture.
- UCSC Xena: TCGA-BRCA clinical matrix, used for PAM50/receptor-status context and sample-ID cross-checking.
- SEQC2/HCC1395: public tumor-normal WES/WGS raw-data benchmark metadata and small FASTQ subsets used for raw-read and alignment smoke tests.
- UCSC Genome Browser: hg38/GRCh38 and hg19/GRCh37 chr13+chr17 FASTA references used for Phase 2C partial human-reference alignment smoke.
- UCSC Genome Browser: hg38/GRCh38 analysisSet FASTA used for Phase 2D full-reference caller-readiness smoke.
- GATK/SEQC2: GATK Mutect2/FilterMutectCalls and SEQC2 HCC1395 high-confidence SNV/INDEL truth VCFs used for Phase 2E production-style somatic-caller smoke, Phase 2F full WES truth-overlap benchmarking, and Phase 3 WGS-capable smoke calling.

## HRD Evidence

The phase-1 analysis uses processed public TCGA-BRCA evidence:

1. HRR mutation records from cBioPortal's processed WES mutation profile.
2. GISTIC discrete copy-number calls as a copy-loss proxy.
3. Sample clinical fields for fraction genome altered, aneuploidy score, mutation count, and nonsynonymous TMB.

Likely damaging variants are rule-classified as nonsense, frameshift, splice-site, translation-start, nonstop, or cBioPortal keyword matches for truncating/frameshift/splice events. This is not manual clinical variant curation.

## RNA Context

RNA context uses selected marker genes from cBioPortal RNA Seq V2 RSEM batch-normalized values. Scores are log2(value + 1), z-scored across the fetched cohort, then averaged into marker modules.

## Raw-Data Smoke Lanes

Phase 2A validates direct raw FASTQ access and pairing from a small SEQC2/HCC1395 tumor-normal WES subset. Phase 2B validates local FASTQ-to-BAM mechanics against a read-backed synthetic smoke reference. Phase 2C validates partial real-human-reference alignment against UCSC hg38 and hg19 chr13+chr17 references. Phase 2D validates one full reference, the UCSC hg38 analysis set, with BRCA1/BRCA2 interval metadata, full-reference BAM contracts, and a tiny indexed VCF caller smoke. Phase 2E validates a production-style GATK Mutect2 tumor-normal execution path on a larger HCC1395 WES downsample. Phase 2F validates full ENA WES FASTQ downloads, full-reference alignment, GATK duplicate marking, Broad hg38 PoN use, common-biallelic contamination estimation, and a bounded SEQC2 truth-overlap Mutect2 benchmark. Phase 3 validates a real representative WGS FASTQ subset through full-reference alignment, Mutect2, coverage-derived CNV bins, an SBS96 matrix, and BAM-derived SV evidence.

These raw lanes are plumbing, file-contract, WES small-variant benchmark, and WGS-capability validators. They do not yet produce clinically interpretable Diana calls, allele-specific CNV/SV calls, full-depth WGS rearrangement signatures, or final HRD signatures.

## Non-Run Lanes

Full-depth WGS rearrangement signature interpretation, scarHRD, CHORD, HRDetect, FACETS/ASCAT/PURPLE allele-specific LOH, methylation-specific second-hit evidence, and companion diagnostics were not run as final clinical classifiers. Phase 3 now writes real WGS smoke feature outputs for the relevant lanes; classification remains gated until full-depth Diana data and reviewer-approved production tooling are available.
`
  );

  await writeText(
    pathFromRoot("results/diana_readiness_gate.md"),
    `# Diana Readiness Gate

Status: **ready for Phase 4 setup once Diana raw files arrive, but not ready for clinical interpretation without raw-file inventory, Diana-specific production resource decisions, WGS/CNV/SV/signature policy, and reviewer sign-off**.

## Required Before Diana Data

1. Confirm tumor-normal DNA source, data type, reference build, matched normal, and whether data are WES or WGS.
2. Confirm bulk RNA source, library type, normalization route, batch, and RNA quality metadata.
3. Confirm sample timing, tissue block/core, tumor purity or tumor content, fixation, and extraction context.
4. Decide whether open analysis is for reviewer biology only or whether a clinician will order orthogonal validation.
5. Confirm whether the requested DNA workflow should be GRCh38, GRCh37/hg19, hs37d5, or a vendor-specific reference bundle.
6. Confirm WES intervals, known-sites resources, germline-resource/PoN/contamination policy, and final production somatic-caller route if raw DNA is FASTQ/BAM/CRAM.
7. If Diana DNA is WGS, confirm CNV/SV/signature production tooling, compute target, and benchmark thresholds before interpreting HRD signatures.
8. Get reviewer sign-off on the benchmark caveats.

## Validation State

The benchmark mechanics are runnable and validated on open processed public data. The raw-read lane now has:

1. Phase 2A direct FASTQ smoke on SEQC2/HCC1395 tumor-normal WES.
2. Phase 2B local FASTQ-to-coordinate-sorted-BAM smoke with read groups and indexes.
3. Phase 2C partial real-human-reference alignment smoke across UCSC hg38/GRCh38 and hg19/GRCh37 chr13+chr17 references.
4. Phase 2D full-reference caller-readiness smoke using the UCSC hg38 analysis set, BRCA1/BRCA2 interval metadata, and an indexed bcftools VCF contract smoke.
5. Phase 2E GATK Mutect2 production-style tumor-normal smoke on a larger HCC1395 WES downsample, with SEQC2 truth VCFs available for bounded overlap checks.
6. Phase 2F full WES benchmark on the SEQC2/HCC1395 tumor-normal pair, with full FASTQ MD5 validation, full-reference BAM contracts, GATK duplicate marking, common-biallelic contamination estimation, PoN-aware Mutect2, and bounded truth-overlap metrics.
7. Phase 3 representative WGS smoke on the SEQC2/HCC1395 HiSeq X tumor-normal pair, with full-reference BAM contracts, Mutect2 VCF output, coverage-CNV bins, SBS96 matrix output, BAM-derived SV evidence, and explicit CHORD/scarHRD/SigProfiler interpretability gates.

The current workflow is sufficient to validate project plumbing, samplesheet shape, local BAM file contracts, partial and full human-reference handling, a production-style Mutect2 execution path, indexed somatic VCF outputs, full WES small-variant benchmark behavior, representative WGS feature-output mechanics, and evidence-table boundaries. It is not sufficient to make a treatment-changing HRD claim.
`
  );

  const packet = `# Reviewer Packet: Diana HRD Omics Validation

## Bottom Line

The phase-1 validation pipeline is complete for open processed public TCGA-BRCA data. It builds a frozen HRD reference panel, separates causal HRR events from second-hit proxies and genome-scar proxies, and refuses to call WGS-specific signature evidence when WGS inputs are unavailable. This is not a clinical HRD truth set.

This is ready for reviewer sanity-check of the workflow mechanics. It is not yet ready to apply to Diana without the readiness gate in \`results/diana_readiness_gate.md\`.

## Dataset Audit

- cBioPortal mutation records fetched: ${(cbioSummary.mutationCount as number) ?? "unknown"}
- cBioPortal CNA records fetched: ${(cbioSummary.cnaRecordCount as number) ?? "unknown"}
- cBioPortal RNA marker records fetched: ${(cbioSummary.expressionRecordCount as number) ?? "unknown"}
- Xena clinical rows: ${(xenaSummary.rowCount as number) ?? "unknown"}
- GDC open files total from catalog query: ${(gdcSummary.totalOpenFiles as number) ?? "unknown"}
- Human-reference smoke rows: ${(humanReferenceSummary.sampleRows as number) ?? "unknown"}
- Human-reference smoke builds: ${Array.isArray(humanReferenceSummary.genomeBuilds) ? humanReferenceSummary.genomeBuilds.join(", ") : "unknown"}
- Full-reference smoke reference: ${(fullReferenceSummary.referenceId as string) ?? "unknown"}
- Full-reference caller smoke: ${(fullReferenceSummary.callerSmokeStatus as string) ?? "unknown"}
- Production somatic caller: ${(productionSomaticSummary.caller as string) ?? "unknown"}
- Production somatic smoke status: ${(productionSomaticSummary.status as string) ?? "unknown"}
- Production somatic read pairs/end: ${(productionSomaticSummary.readPairsPerEnd as number) ?? "unknown"}
- Production somatic truth comparison: ${(productionSomaticSummary.comparisonStatus as string) ?? "unknown"}
- Full WES benchmark status: ${(fullWesBenchmarkSummary.status as string) ?? "unknown"}
- Full WES benchmark ready for Phase 3: ${(fullWesBenchmarkSummary.readyForPhase3 as boolean) === true ? "yes" : "no"}
- Full WES benchmark intervals: ${(fullWesBenchmarkSummary.benchmarkIntervalCount as number) ?? "unknown"}
- Full WES depth-eligible truth variants: ${(fullWesBenchmarkSummary.truthVariantsDepthEligible as number) ?? "unknown"}
- Full WES contamination status: ${(fullWesBenchmarkSummary.contaminationStatus as string) ?? "unknown"}
- Phase 3 WGS smoke status: ${(phase3WgsSummary.status as string) ?? "unknown"}
- Phase 3 WGS smoke reads/end: ${(phase3WgsSummary.readPairsPerEnd as number) ?? "unknown"}
- Phase 3 WGS smoke parallel alignment: ${(phase3WgsSummary.parallelAlign as boolean) === true ? "yes" : "no"}
- Phase 3 WGS smoke CNV bins: ${(phase3WgsSummary.coverageCnvBins as number) ?? "unknown"}
- Phase 3 WGS smoke SBS96 usable SNVs: ${(phase3WgsSummary.sbs96UsableSnvRecords as number) ?? "unknown"}
- Phase 3 ready for Diana raw arrival: ${(phase3WgsSummary.readyForPhase4WhenDianaRawArrives as boolean) === true ? "yes" : "no"}

## Frozen Panel

${table(categoryCounts.map((row) => ({ category: row.key, count: row.count })))}

## HRD Prediction Classes

${table(predictionCounts.map((row) => ({ prediction: row.key, count: row.count })))}

## Confusion Matrix

${table(confusion)}

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
10. Phase 3 WGS smoke validates representative WGS FASTQ, BAM, VCF, CNV-bin, SBS96-matrix, and SV-evidence outputs with real tools and explicit low-depth interpretability gates.

## Main Limitations

1. GISTIC copy loss is not allele-specific LOH.
2. Fraction genome altered and aneuploidy are scar proxies, not scarHRD.
3. SBS3, SV signatures, CHORD, and HRDetect are not assessable from the current processed phase-1 inputs.
4. The Phase 2F Mutect2 VCF is WES small-variant benchmark evidence, not WGS HRD signature evidence.
5. The Phase 3 WGS lane is a representative WGS smoke, not full-depth WGS sensitivity or a final HRD classifier.
6. The Phase 2F local gate uses the Broad 1000g PoN and common-biallelic contamination resource, but the full multi-GB af-only gnomAD resource remains documented as a production/cloud input rather than a local gating download.
7. BQSR, orientation-bias modeling, vendor capture intervals, allele-specific copy-number, validated SV calling, and WGS signature classification remain Diana-specific production decisions.
8. Clinical action still requires clinician-owned validation, companion diagnostics, or orthogonal confirmation.

## Output Tables

- \`results/hrd_event_table.csv\`
- \`results/allele_state_table.csv\`
- \`results/scar_signature_table.csv\`
- \`results/hrd_confusion_matrix.csv\`
- \`results/hrd_failure_modes.csv\`
- \`results/rna_subtype_context.csv\`
- \`results/rna_module_context.csv\`

## Summaries

- HRD summary: ${JSON.stringify(summary)}
- RNA summary: ${JSON.stringify(rnaSummary)}
`;

  await writeText(pathFromRoot("results/reviewer_packet.md"), packet);
  await writeJson(pathFromRoot("results/reviewer_packet_summary.json"), {
    generatedAt: new Date().toISOString(),
    panelSampleCount: panel.length,
    categoryCounts,
    predictionCounts,
    confusion
  });

  console.log(`Built reviewer packet for ${panel.length} panel samples.`);
}

await main();
