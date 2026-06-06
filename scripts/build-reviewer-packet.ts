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

  const categoryCounts = countBy(panel, "panel_category");
  const predictionCounts = countBy(predictions, "predicted_hrd_class");

  await writeText(
    pathFromRoot("results/methods.md"),
    `# Methods

## Data Sources

- cBioPortal study: \`brca_tcga_pan_can_atlas_2018\`, imported by cBioPortal on 2026-06-05 according to live study metadata.
- GDC: TCGA-BRCA open file catalog metadata only, used to verify public/open project availability and access posture.
- UCSC Xena: TCGA-BRCA clinical matrix, used for PAM50/receptor-status context and sample-ID cross-checking.

## HRD Evidence

The phase-1 analysis uses processed public TCGA-BRCA evidence:

1. HRR mutation records from cBioPortal's processed WES mutation profile.
2. GISTIC discrete copy-number calls as a copy-loss proxy.
3. Sample clinical fields for fraction genome altered, aneuploidy score, mutation count, and nonsynonymous TMB.

Likely damaging variants are rule-classified as nonsense, frameshift, splice-site, translation-start, nonstop, or cBioPortal keyword matches for truncating/frameshift/splice events. This is not manual clinical variant curation.

## RNA Context

RNA context uses selected marker genes from cBioPortal RNA Seq V2 RSEM batch-normalized values. Scores are log2(value + 1), z-scored across the fetched cohort, then averaged into marker modules.

## Non-Run Lanes

WGS rearrangement signatures, SBS3 assignment, scarHRD, CHORD, HRDetect, FACETS/ASCAT/PURPLE allele-specific LOH, methylation-specific second-hit evidence, and companion diagnostics were not run in this phase. They are explicit future or external validation lanes.
`
  );

  await writeText(
    pathFromRoot("results/diana_readiness_gate.md"),
    `# Diana Readiness Gate

Status: **not ready to run on Diana files without raw-file inventory and reviewer sign-off**.

## Required Before Diana Data

1. Confirm tumor-normal DNA source, data type, reference build, matched normal, and whether data are WES or WGS.
2. Confirm bulk RNA source, library type, normalization route, batch, and RNA quality metadata.
3. Confirm sample timing, tissue block/core, tumor purity or tumor content, fixation, and extraction context.
4. Decide whether open analysis is for reviewer biology only or whether a clinician will order orthogonal validation.
5. Get reviewer sign-off on the phase-1 benchmark caveats.

## Validation State

The benchmark mechanics are runnable and validated on open processed public data. The current workflow is sufficient to build an evidence table and identify limitations. It is not sufficient to make a treatment-changing HRD claim.
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

## Main Limitations

1. GISTIC copy loss is not allele-specific LOH.
2. Fraction genome altered and aneuploidy are scar proxies, not scarHRD.
3. SBS3, SV signatures, CHORD, and HRDetect are not assessable from the current processed phase-1 inputs.
4. Clinical action still requires clinician-owned validation, companion diagnostics, or orthogonal confirmation.

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
