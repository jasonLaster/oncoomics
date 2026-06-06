import {
  ensureDir,
  groupBy,
  mean,
  parseCsv,
  pathFromRoot,
  pivotClinical,
  readJson,
  readText,
  round,
  standardDeviation,
  toNumber,
  writeCsv,
  writeJson
} from "./lib";

type ExpressionRecord = {
  sampleId: string;
  patientId: string;
  gene: { hugoGeneSymbol: string };
  value: number;
};

type ClinicalRecord = {
  sampleId?: string;
  patientId?: string;
  clinicalAttributeId: string;
  value: string;
};

const modules: Record<string, string[]> = {
  basal_marker: ["KRT5", "KRT14", "KRT17", "EGFR", "FOXC1"],
  lar_luminal_marker: ["AR", "FOXA1", "GATA3", "ESR1"],
  proliferation_marker: ["MKI67"],
  immune_inflammation_marker: ["CD8A", "CD274", "CXCL9", "IFNG"],
  epithelial_marker: ["EPCAM", "MUC1"],
  stromal_emt_marker: ["VIM"]
};

function expressionValue(record: ExpressionRecord) {
  return Math.log2((record.value ?? 0) + 1);
}

function classifyContext(moduleScores: Record<string, number | null>, subtype: string, pam50: string) {
  const basal = moduleScores.basal_marker ?? 0;
  const lar = moduleScores.lar_luminal_marker ?? 0;
  const immune = moduleScores.immune_inflammation_marker ?? 0;
  if (/Basal/i.test(subtype) || /Basal/i.test(pam50) || basal >= 0.75) {
    return "basal_like_context";
  }
  if (lar >= 0.75 && basal < 0.5) {
    return "lar_luminal_marker_context";
  }
  if (immune >= 0.75) {
    return "immune_inflamed_context";
  }
  return "mixed_or_non_basal_context";
}

async function main() {
  ensureDir(pathFromRoot("results/evidence_tables"));

  const panel = parseCsv(readText(pathFromRoot("manifests/hrd_reference_panel.csv")));
  const expression = readJson<ExpressionRecord[]>(pathFromRoot("data/raw/cbioportal/expression_marker_genes.json"));
  const patientClinical = pivotClinical(
    readJson<ClinicalRecord[]>(pathFromRoot("data/raw/cbioportal/clinical_patient_selected.json")),
    "patientId"
  );
  const xenaRows = parseCsv(readText(pathFromRoot("data/processed/xena/brca_clinical_subset.csv")));

  const expressionByGene = groupBy(expression, (record) => record.gene.hugoGeneSymbol);
  const expressionStats = new Map<string, { mean: number; sd: number }>();
  for (const [gene, records] of expressionByGene.entries()) {
    const values = records.map(expressionValue);
    expressionStats.set(gene, {
      mean: mean(values) ?? 0,
      sd: standardDeviation(values) ?? 1
    });
  }

  const zBySampleGene = new Map<string, number>();
  for (const record of expression) {
    const gene = record.gene.hugoGeneSymbol;
    const stats = expressionStats.get(gene);
    if (!stats) {
      continue;
    }
    zBySampleGene.set(`${record.sampleId}:${gene}`, (expressionValue(record) - stats.mean) / (stats.sd || 1));
  }

  const patientClinicalById = new Map(patientClinical.map((row) => [row.patientId, row]));
  const xenaBySample = new Map(xenaRows.map((row) => [row.sampleID, row]));
  const subtypeRows: Record<string, unknown>[] = [];
  const moduleRows: Record<string, unknown>[] = [];

  for (const panelRow of panel) {
    const sampleId = panelRow.sample_id;
    const patientId = panelRow.patient_id;
    const clinicalSubtype = patientClinicalById.get(patientId)?.SUBTYPE ?? "";
    const xena = xenaBySample.get(sampleId) ?? {};
    const pam50 = xena.PAM50Call_RNAseq || xena.PAM50_mRNA_nature2012 || clinicalSubtype;

    const moduleScores: Record<string, number | null> = {};
    for (const [moduleName, genes] of Object.entries(modules)) {
      moduleScores[moduleName] = mean(genes.map((gene) => zBySampleGene.get(`${sampleId}:${gene}`)));
    }

    const context = classifyContext(moduleScores, clinicalSubtype, pam50 ?? "");

    subtypeRows.push({
      sample_id: sampleId,
      source: "cBioPortal expression plus UCSC Xena clinical subset",
      tool: "marker-module context script",
      tool_version: "scripts/build-rna-context.ts",
      cbioportal_subtype: clinicalSubtype,
      xena_pam50_call_rnaseq: xena.PAM50Call_RNAseq ?? "",
      xena_pam50_mrna_nature2012: xena.PAM50_mRNA_nature2012 ?? "",
      er_status_nature2012: xena.ER_Status_nature2012 ?? "",
      pr_status_nature2012: xena.PR_Status_nature2012 ?? "",
      her2_status_nature2012: xena.HER2_Final_Status_nature2012 ?? "",
      inferred_context: context,
      confidence: clinicalSubtype || pam50 ? "processed_public_context" : "limited",
      caveat: "This is not TNBCtype/TNBC-DX/Reveal. It is a small marker-module context lane for the HRD validation panel."
    });

    moduleRows.push({
      sample_id: sampleId,
      source: "cBioPortal RNA Seq V2 RSEM batch-normalized marker expression",
      tool: "log2 expression z-score module means",
      tool_version: "scripts/build-rna-context.ts",
      basal_marker_z: round(moduleScores.basal_marker),
      lar_luminal_marker_z: round(moduleScores.lar_luminal_marker),
      proliferation_marker_z: round(moduleScores.proliferation_marker),
      immune_inflammation_marker_z: round(moduleScores.immune_inflammation_marker),
      epithelial_marker_z: round(moduleScores.epithelial_marker),
      stromal_emt_marker_z: round(moduleScores.stromal_emt_marker),
      marker_genes: Object.entries(modules)
        .map(([moduleName, genes]) => `${moduleName}:${genes.join("|")}`)
        .join("; "),
      caveat: "Module scores are cohort-relative marker means, not locked clinical classifier outputs."
    });
  }

  await writeCsv(pathFromRoot("results/rna_subtype_context.csv"), subtypeRows);
  await writeCsv(pathFromRoot("results/rna_module_context.csv"), moduleRows);
  await writeCsv(pathFromRoot("results/evidence_tables/rna_subtype_context.csv"), subtypeRows);
  await writeCsv(pathFromRoot("results/evidence_tables/rna_module_context.csv"), moduleRows);
  await writeJson(pathFromRoot("results/rna_context_summary.json"), {
    generatedAt: new Date().toISOString(),
    panelSampleCount: panel.length,
    expressionRecordCount: expression.length,
    moduleDefinitions: modules,
    boundary: "RNA context is a small marker-module lane and does not reproduce TNBCtype, TNBC-DX, or Reveal."
  });

  console.log(`Built RNA context tables for ${panel.length} panel samples.`);
}

await main();

