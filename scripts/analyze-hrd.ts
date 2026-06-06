import {
  ensureDir,
  groupBy,
  parseCsv,
  pathFromRoot,
  pivotClinical,
  readJson,
  readText,
  round,
  toNumber,
  writeCsv,
  writeJson
} from "./lib";

type Mutation = {
  sampleId: string;
  patientId: string;
  gene: { hugoGeneSymbol: string };
  entrezGeneId: number;
  mutationType: string;
  proteinChange?: string;
  keyword?: string;
  tumorAltCount?: number;
  tumorRefCount?: number;
  normalAltCount?: number;
  normalRefCount?: number;
  ncbiBuild?: string;
};

type Cna = {
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

const damagingTypes = new Set([
  "Nonsense_Mutation",
  "Frame_Shift_Del",
  "Frame_Shift_Ins",
  "Splice_Site",
  "Translation_Start_Site",
  "Nonstop_Mutation"
]);

function mutationClass(mutation: Mutation) {
  if (damagingTypes.has(mutation.mutationType) || /truncating|frameshift|splice/i.test(mutation.keyword ?? "")) {
    return "likely_damaging";
  }
  if (/Missense/i.test(mutation.mutationType)) {
    return "missense_or_vus";
  }
  return "other";
}

function cnaState(value: number | undefined) {
  if (value === undefined) {
    return "not_available";
  }
  if (value <= -2) {
    return "deep_deletion";
  }
  if (value === -1) {
    return "shallow_loss";
  }
  if (value === 0) {
    return "neutral";
  }
  if (value === 1) {
    return "gain";
  }
  if (value >= 2) {
    return "amplification";
  }
  return String(value);
}

function scarProxyClass(fga: number | null, aneuploidy: number | null) {
  if ((fga ?? 0) >= 0.35 || (aneuploidy ?? 0) >= 12) {
    return "copy_number_scar_proxy_high";
  }
  if ((fga ?? 0) >= 0.2 || (aneuploidy ?? 0) >= 6) {
    return "copy_number_scar_proxy_intermediate";
  }
  if (fga !== null || aneuploidy !== null) {
    return "copy_number_scar_proxy_low";
  }
  return "not_assessable";
}

function predictionClass(row: Record<string, string>, bestMutation: Mutation | undefined, bestCna: number | undefined, fga: number | null, aneuploidy: number | null) {
  const eventClass = bestMutation ? mutationClass(bestMutation) : "none";
  const isBrca = bestMutation ? ["BRCA1", "BRCA2"].includes(bestMutation.gene.hugoGeneSymbol) : false;
  const secondHit = bestCna !== undefined && bestCna <= -1;
  const scar = scarProxyClass(fga, aneuploidy);
  if (isBrca && eventClass === "likely_damaging" && secondHit && scar === "copy_number_scar_proxy_high") {
    return "strong_hrd_like_candidate";
  }
  if (eventClass === "likely_damaging" && secondHit && (scar === "copy_number_scar_proxy_high" || scar === "copy_number_scar_proxy_intermediate")) {
    return "suggestive_hrd_like_candidate";
  }
  if (!bestMutation && row.expected_hrd_label === "expected_hrd_negative" && scar === "copy_number_scar_proxy_low") {
    return "low_evidence_negative_candidate";
  }
  if (bestMutation) {
    return "ambiguous_or_incomplete";
  }
  return "not_assessable";
}

function confusionBucket(prediction: string) {
  if (prediction.includes("hrd_like")) {
    return "predicted_hrd_like";
  }
  if (prediction.includes("negative")) {
    return "predicted_negative";
  }
  return "predicted_ambiguous_or_not_assessable";
}

async function main() {
  ensureDir(pathFromRoot("results/evidence_tables"));

  const panel = parseCsv(readText(pathFromRoot("manifests/hrd_reference_panel.csv")));
  const mutations = readJson<Mutation[]>(pathFromRoot("data/raw/cbioportal/mutations_hrr.json"));
  const cna = readJson<Cna[]>(pathFromRoot("data/raw/cbioportal/cna_hrr_gistic.json"));
  const clinical = pivotClinical(
    readJson<ClinicalRecord[]>(pathFromRoot("data/raw/cbioportal/clinical_sample_selected.json")),
    "sampleId"
  );

  const mutationsBySample = groupBy(mutations, (mutation) => mutation.sampleId);
  const cnaBySampleGene = new Map(cna.map((row) => [`${row.sampleId}:${row.gene.hugoGeneSymbol}`, row.value]));
  const clinicalBySample = new Map(clinical.map((row) => [row.sampleId, row]));

  const eventRows: Record<string, unknown>[] = [];
  const alleleRows: Record<string, unknown>[] = [];
  const scarRows: Record<string, unknown>[] = [];
  const failureRows: Record<string, unknown>[] = [];
  const predictionRows: Record<string, string>[] = [];

  for (const panelRow of panel) {
    const sampleId = panelRow.sample_id;
    const sampleMutations = mutationsBySample.get(sampleId) ?? [];
    const clinicalRow = clinicalBySample.get(sampleId) ?? {};
    const fga = toNumber(clinicalRow.FRACTION_GENOME_ALTERED);
    const aneuploidy = toNumber(clinicalRow.ANEUPLOIDY_SCORE);
    const mutationCount = toNumber(clinicalRow.MUTATION_COUNT);
    const tmb = toNumber(clinicalRow.TMB_NONSYNONYMOUS);
    const rankedMutations = [...sampleMutations].sort((a, b) => {
      const aScore = mutationClass(a) === "likely_damaging" ? 2 : mutationClass(a) === "missense_or_vus" ? 1 : 0;
      const bScore = mutationClass(b) === "likely_damaging" ? 2 : mutationClass(b) === "missense_or_vus" ? 1 : 0;
      return bScore - aScore;
    });
    const bestMutation = rankedMutations[0];
    const bestCna = bestMutation ? cnaBySampleGene.get(`${sampleId}:${bestMutation.gene.hugoGeneSymbol}`) : undefined;
    const prediction = predictionClass(panelRow, bestMutation, bestCna, fga, aneuploidy);

    if (sampleMutations.length === 0) {
      eventRows.push({
        sample_id: sampleId,
        source: "cBioPortal TCGA-BRCA PanCancer Atlas",
        tool: "cBioPortal processed WES mutation profile",
        tool_version: "study import 2026-06-05",
        gene: "",
        alteration: "none_in_fetched_hrr_gene_set",
        mutation_type: "",
        event_class: "none",
        vaf_proxy: "",
        confidence: "no_event_in_selected_hrr_gene_set",
        caveat: "Absence is limited to fetched HRR genes and processed mutation calls."
      });
    }

    for (const mutation of sampleMutations) {
      const alt = mutation.tumorAltCount ?? null;
      const ref = mutation.tumorRefCount ?? null;
      const vaf = alt !== null && ref !== null && alt + ref > 0 ? alt / (alt + ref) : null;
      eventRows.push({
        sample_id: sampleId,
        source: "cBioPortal TCGA-BRCA PanCancer Atlas",
        tool: "cBioPortal processed WES mutation profile",
        tool_version: "study import 2026-06-05",
        gene: mutation.gene.hugoGeneSymbol,
        alteration: mutation.proteinChange ?? mutation.mutationType,
        mutation_type: mutation.mutationType,
        event_class: mutationClass(mutation),
        vaf_proxy: round(vaf),
        reference_build: mutation.ncbiBuild ?? "GRCh37",
        confidence: mutationClass(mutation) === "likely_damaging" ? "causal_event_supported" : "variant_requires_review",
        caveat: "Processed WES mutation record; pathogenicity is rule-based, not manual clinical curation."
      });
    }

    const alleleMutationRows = sampleMutations.length > 0 ? sampleMutations : [undefined];
    for (const mutation of alleleMutationRows) {
      const gene = mutation?.gene.hugoGeneSymbol ?? "BRCA1/BRCA2";
      const cnaValue = mutation ? cnaBySampleGene.get(`${sampleId}:${gene}`) : undefined;
      alleleRows.push({
        sample_id: sampleId,
        source: "cBioPortal TCGA-BRCA PanCancer Atlas",
        tool: "GISTIC discrete CNA plus processed WES mutation profile",
        tool_version: "study import 2026-06-05",
        gene,
        causal_event_class: mutation ? mutationClass(mutation) : "none",
        gistic_value: cnaValue ?? "",
        copy_number_state: cnaState(cnaValue),
        second_hit_status:
          mutation && mutationClass(mutation) === "likely_damaging" && cnaValue !== undefined && cnaValue <= -1
            ? "copy_loss_proxy_supports_second_hit"
            : mutation
              ? "second_hit_not_proven"
              : "no_causal_event_to_assess",
        confidence: mutation && cnaValue !== undefined && cnaValue <= -1 ? "proxy_support" : "incomplete",
        caveat: "GISTIC is not allele-specific purity/ploidy; LOH and biallelic status require FACETS/ASCAT/PURPLE-style evidence."
      });
    }

    const scarProxy = scarProxyClass(fga, aneuploidy);
    scarRows.push({
      sample_id: sampleId,
      source: "cBioPortal TCGA-BRCA PanCancer Atlas sample clinical fields",
      tool: "processed proxy summary",
      tool_version: "study import 2026-06-05",
      fraction_genome_altered: round(fga),
      aneuploidy_score: aneuploidy ?? "",
      mutation_count: mutationCount ?? "",
      tmb_nonsynonymous: round(tmb),
      scar_proxy_class: scarProxy,
      sbs3_signature_status: "not_assessable_from_phase1_processed_data",
      structural_variant_signature_status: "not_assessable_from_phase1_processed_data",
      hrd_classifier_status: "not_run_without_WGS_or_required_feature_matrix",
      predicted_hrd_class: prediction,
      confidence: prediction.includes("strong") ? "high_for_processed_public_candidate" : prediction.includes("suggestive") ? "moderate_for_processed_public_candidate" : "limited",
      caveat: "FGA/aneuploidy are copy-number scar proxies, not scarHRD/CHORD/HRDetect/SBS3 outputs."
    });

    failureRows.push({
      sample_id: sampleId,
      failure_mode: "no_wgs_signature_inputs",
      severity: "expected_phase1_limitation",
      detail: "SBS3, rearrangement signatures, CHORD, and HRDetect-style outputs are not assessable from this processed cBioPortal phase-1 data alone."
    });
    failureRows.push({
      sample_id: sampleId,
      failure_mode: "no_allele_specific_purity_ploidy",
      severity: "expected_phase1_limitation",
      detail: "GISTIC copy loss is only a second-hit proxy; biallelic status needs allele-specific copy number and purity/ploidy."
    });
    if (bestMutation && !(bestCna !== undefined && bestCna <= -1)) {
      failureRows.push({
        sample_id: sampleId,
        failure_mode: "second_hit_not_proven",
        severity: "sample_specific_limitation",
        detail: `${bestMutation.gene.hugoGeneSymbol} event lacks GISTIC copy-loss proxy in this phase-1 evidence table.`
      });
    }

    predictionRows.push({
      sample_id: sampleId,
      expected_hrd_label: panelRow.expected_hrd_label,
      predicted_hrd_class: prediction,
      expected_bucket: panelRow.expected_hrd_label.includes("negative")
        ? "expected_negative"
        : panelRow.expected_hrd_label.includes("ambiguous")
          ? "expected_ambiguous"
          : "expected_hrd_like",
      predicted_bucket: confusionBucket(prediction)
    });
  }

  const matrix = new Map<string, number>();
  for (const row of predictionRows) {
    const key = `${row.expected_bucket}|${row.predicted_bucket}`;
    matrix.set(key, (matrix.get(key) ?? 0) + 1);
  }
  const matrixRows = Array.from(matrix.entries()).map(([key, count]) => {
    const [expected_bucket, predicted_bucket] = key.split("|");
    return { expected_bucket, predicted_bucket, count };
  });

  await writeCsv(pathFromRoot("results/hrd_event_table.csv"), eventRows);
  await writeCsv(pathFromRoot("results/allele_state_table.csv"), alleleRows);
  await writeCsv(pathFromRoot("results/scar_signature_table.csv"), scarRows);
  await writeCsv(pathFromRoot("results/hrd_confusion_matrix.csv"), matrixRows);
  await writeCsv(pathFromRoot("results/hrd_failure_modes.csv"), failureRows);
  await writeCsv(pathFromRoot("results/hrd_predictions.csv"), predictionRows);

  await writeCsv(pathFromRoot("results/evidence_tables/hrd_event_table.csv"), eventRows);
  await writeCsv(pathFromRoot("results/evidence_tables/allele_state_table.csv"), alleleRows);
  await writeCsv(pathFromRoot("results/evidence_tables/scar_signature_table.csv"), scarRows);
  await writeCsv(pathFromRoot("results/evidence_tables/hrd_failure_modes.csv"), failureRows);

  await writeJson(pathFromRoot("results/hrd_analysis_summary.json"), {
    generatedAt: new Date().toISOString(),
    panelSampleCount: panel.length,
    eventRowCount: eventRows.length,
    alleleStateRowCount: alleleRows.length,
    scarSignatureRowCount: scarRows.length,
    failureModeRowCount: failureRows.length,
    confusionMatrix: matrixRows,
    boundary: "Phase-1 HRD classes are processed public-data candidates. WGS signatures, allele-specific LOH, CHORD, HRDetect, and companion diagnostics are not run."
  });

  console.log(`Built HRD evidence tables for ${panel.length} panel samples.`);
}

await main();

