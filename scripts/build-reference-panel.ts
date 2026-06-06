import {
  ensureDir,
  groupBy,
  pathFromRoot,
  pivotClinical,
  readJson,
  toNumber,
  writeCsv,
  writeJson,
  writeText
} from "./lib";

type Mutation = {
  sampleId: string;
  patientId: string;
  gene: { hugoGeneSymbol: string };
  mutationType: string;
  proteinChange?: string;
  keyword?: string;
  tumorAltCount?: number;
  tumorRefCount?: number;
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
const brcaGenes = new Set(["BRCA1", "BRCA2"]);

function mutationClass(mutation: Mutation) {
  if (damagingTypes.has(mutation.mutationType) || /truncating|frameshift|splice/i.test(mutation.keyword ?? "")) {
    return "likely_damaging";
  }
  if (/Missense/i.test(mutation.mutationType)) {
    return "missense_or_vus";
  }
  return "other";
}

function scoreMutation(mutation: Mutation) {
  if (mutationClass(mutation) === "likely_damaging") {
    return 3;
  }
  if (mutationClass(mutation) === "missense_or_vus") {
    return 1;
  }
  return 0;
}

function cnaDescription(value: number | undefined) {
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

function getRowScore(row: PanelCandidate) {
  if (row.panel_category === "positive_control") {
    return 1000 + row.fraction_genome_altered * 100 + row.best_event_score;
  }
  if (row.panel_category === "mechanistic_control") {
    return 800 + row.fraction_genome_altered * 100 + row.best_event_score;
  }
  if (row.panel_category === "ambiguous_control") {
    return 500 + row.best_event_score + row.fraction_genome_altered;
  }
  if (row.panel_category === "negative_control") {
    return 300 - row.fraction_genome_altered * 100;
  }
  return 0;
}

type PanelCandidate = {
  sample_id: string;
  patient_id: string;
  panel_category: string;
  expected_hrd_label: string;
  label_strength: string;
  label_source: string;
  primary_event_gene: string;
  primary_event: string;
  primary_event_class: string;
  copy_number_context: string;
  second_hit_proxy: string;
  fraction_genome_altered: number;
  aneuploidy_score: number | null;
  mutation_count: number | null;
  tmb_nonsynonymous: number | null;
  cbioportal_subtype: string;
  caveat: string;
  best_event_score: number;
};

async function main() {
  ensureDir(pathFromRoot("manifests"));
  ensureDir(pathFromRoot("docs"));

  const sampleIdsByList = readJson<Record<string, string[]>>(pathFromRoot("data/raw/cbioportal/sample_ids_by_list.json"));
  const mutations = readJson<Mutation[]>(pathFromRoot("data/raw/cbioportal/mutations_hrr.json"));
  const cna = readJson<Cna[]>(pathFromRoot("data/raw/cbioportal/cna_hrr_gistic.json"));
  const sampleClinical = pivotClinical(
    readJson<ClinicalRecord[]>(pathFromRoot("data/raw/cbioportal/clinical_sample_selected.json")),
    "sampleId"
  );
  const patientClinical = pivotClinical(
    readJson<ClinicalRecord[]>(pathFromRoot("data/raw/cbioportal/clinical_patient_selected.json")),
    "patientId"
  );

  const clinicalBySample = new Map(sampleClinical.map((row) => [row.sampleId, row]));
  const clinicalByPatient = new Map(patientClinical.map((row) => [row.patientId, row]));
  const mutationsBySample = groupBy(mutations, (mutation) => mutation.sampleId);
  const cnaBySampleGene = new Map(cna.map((row) => [`${row.sampleId}:${row.gene.hugoGeneSymbol}`, row.value]));

  const candidates: PanelCandidate[] = [];
  for (const sampleId of sampleIdsByList.brca_tcga_pan_can_atlas_2018_3way_complete) {
    const patientId = sampleId.slice(0, 12);
    const sampleClinicalRow = clinicalBySample.get(sampleId) ?? {};
    const patientClinicalRow = clinicalByPatient.get(patientId) ?? {};
    const sampleMutations = mutationsBySample.get(sampleId) ?? [];
    const rankedMutations = [...sampleMutations].sort((a, b) => scoreMutation(b) - scoreMutation(a));
    const bestMutation = rankedMutations[0];
    const primaryGene = bestMutation?.gene.hugoGeneSymbol ?? "";
    const primaryCna = primaryGene ? cnaBySampleGene.get(`${sampleId}:${primaryGene}`) : undefined;
    const brca1Cna = cnaBySampleGene.get(`${sampleId}:BRCA1`);
    const brca2Cna = cnaBySampleGene.get(`${sampleId}:BRCA2`);
    const mutationClasses = sampleMutations.map(mutationClass);
    const damagingBrca = sampleMutations.some((mutation) => brcaGenes.has(mutation.gene.hugoGeneSymbol) && mutationClass(mutation) === "likely_damaging");
    const damagingOtherHrr = sampleMutations.some((mutation) => !brcaGenes.has(mutation.gene.hugoGeneSymbol) && mutationClass(mutation) === "likely_damaging");
    const hasAnyHrrMutation = sampleMutations.length > 0;
    const fga = toNumber(sampleClinicalRow.FRACTION_GENOME_ALTERED) ?? 0;
    const aneuploidy = toNumber(sampleClinicalRow.ANEUPLOIDY_SCORE);
    const mutationCount = toNumber(sampleClinicalRow.MUTATION_COUNT);
    const tmb = toNumber(sampleClinicalRow.TMB_NONSYNONYMOUS);
    const secondHitProxy = primaryCna !== undefined && primaryCna <= -1 ? "copy_loss_proxy_present" : primaryGene ? "copy_loss_proxy_absent" : "no_causal_event";

    let panelCategory = "background";
    let expectedLabel = "not_selected";
    let labelStrength = "not_selected";
    let caveat = "Not selected for the frozen phase-1 panel.";

    if (damagingBrca && primaryCna !== undefined && primaryCna <= -1 && fga >= 0.3) {
      panelCategory = "positive_control";
      expectedLabel = "expected_hrd_like";
      labelStrength = "processed_public_positive_candidate";
      caveat = "Damaging BRCA1/2 event plus GISTIC copy-loss proxy and high fraction genome altered; not a WGS signature truth label.";
    } else if (damagingOtherHrr && primaryCna !== undefined && primaryCna <= -1 && fga >= 0.25) {
      panelCategory = "mechanistic_control";
      expectedLabel = "expected_hrd_like_mechanistic";
      labelStrength = "processed_public_mechanistic_candidate";
      caveat = "Damaging non-BRCA HRR event plus copy-loss proxy and elevated fraction genome altered; mechanism is less direct than BRCA1/2.";
    } else if (hasAnyHrrMutation) {
      panelCategory = "ambiguous_control";
      expectedLabel = "expected_ambiguous";
      labelStrength = mutationClasses.includes("likely_damaging") ? "event_without_complete_support" : "vus_or_missense_only";
      caveat = "HRR alteration exists but phase-1 processed data does not prove functional HRD.";
    } else if (!hasAnyHrrMutation && (brca1Cna ?? 0) === 0 && (brca2Cna ?? 0) === 0 && fga <= 0.15 && (mutationCount ?? 0) <= 80) {
      panelCategory = "negative_control";
      expectedLabel = "expected_hrd_negative";
      labelStrength = "processed_public_negative_candidate";
      caveat = "No fetched HRR mutation, neutral BRCA1/2 GISTIC calls, low fraction genome altered, and modest mutation count in processed public data.";
    }

    candidates.push({
      sample_id: sampleId,
      patient_id: patientId,
      panel_category: panelCategory,
      expected_hrd_label: expectedLabel,
      label_strength: labelStrength,
      label_source: "cBioPortal TCGA-BRCA PanCancer Atlas processed mutation/CNA/sample clinical data",
      primary_event_gene: primaryGene,
      primary_event: bestMutation ? `${bestMutation.gene.hugoGeneSymbol} ${bestMutation.proteinChange ?? bestMutation.mutationType}` : "none",
      primary_event_class: bestMutation ? mutationClass(bestMutation) : "none",
      copy_number_context: primaryGene ? cnaDescription(primaryCna) : `BRCA1=${cnaDescription(brca1Cna)}; BRCA2=${cnaDescription(brca2Cna)}`,
      second_hit_proxy: secondHitProxy,
      fraction_genome_altered: fga,
      aneuploidy_score: aneuploidy,
      mutation_count: mutationCount,
      tmb_nonsynonymous: tmb,
      cbioportal_subtype: patientClinicalRow.SUBTYPE ?? "",
      caveat,
      best_event_score: bestMutation ? scoreMutation(bestMutation) : 0
    });
  }

  const selected = [
    ...candidates.filter((row) => row.panel_category === "positive_control").sort((a, b) => getRowScore(b) - getRowScore(a)).slice(0, 8),
    ...candidates.filter((row) => row.panel_category === "mechanistic_control").sort((a, b) => getRowScore(b) - getRowScore(a)).slice(0, 4),
    ...candidates.filter((row) => row.panel_category === "ambiguous_control").sort((a, b) => getRowScore(b) - getRowScore(a)).slice(0, 8),
    ...candidates.filter((row) => row.panel_category === "negative_control").sort((a, b) => getRowScore(b) - getRowScore(a)).slice(0, 8)
  ].sort((a, b) => a.panel_category.localeCompare(b.panel_category) || a.sample_id.localeCompare(b.sample_id));

  const publicRows = selected.map(({ best_event_score, ...row }) => row);
  await writeCsv(pathFromRoot("manifests/hrd_reference_panel.csv"), publicRows);
  await writeJson(pathFromRoot("manifests/reference_panel_validation.json"), {
    generatedAt: new Date().toISOString(),
    selectedSampleCount: selected.length,
    availableCandidatesByCategory: Object.fromEntries(
      Array.from(groupBy(candidates, (row) => row.panel_category).entries()).map(([key, rows]) => [key, rows.length])
    ),
    selectedByCategory: Object.fromEntries(
      Array.from(groupBy(selected, (row) => row.panel_category).entries()).map(([key, rows]) => [key, rows.length])
    ),
    validationRules: [
      "Positive controls require damaging BRCA1/2 event plus GISTIC copy-loss proxy and high fraction genome altered.",
      "Negative controls require no fetched HRR mutation, neutral BRCA1/2 GISTIC calls, low fraction genome altered, and modest mutation count.",
      "Ambiguous controls are explicitly allowed and should not be forced into binary HRD labels.",
      "No sample is treated as WGS-signature validated in this phase-1 panel."
    ]
  });

  await writeText(
    pathFromRoot("docs/reference-panel-label-rules.md"),
    `# HRD Reference Panel Label Rules

This frozen phase-1 panel uses open processed TCGA-BRCA PanCancer Atlas data from cBioPortal. It is a validation panel for workflow mechanics, not a clinical HRD truth set.

## Positive Controls

Positive controls require all of the following:

1. A likely damaging BRCA1/2 event in the fetched HRR mutation table.
2. A GISTIC copy-loss proxy for the same gene.
3. Elevated fraction genome altered in sample clinical data.

These are labeled expected HRD-like, but still carry a caveat that WGS structural-signature and companion-diagnostic evidence are not available in this phase.

## Mechanistic Controls

Mechanistic controls use likely damaging non-BRCA HRR events with copy-loss proxy and elevated fraction genome altered. These are useful stress tests, but less direct than BRCA1/2 controls.

## Ambiguous Controls

Ambiguous controls include HRR alterations without enough second-hit or scar-proxy support. They are intentionally included so the workflow can prove it does not force hard cases into binary labels.

## Negative Controls

Negative controls require no fetched HRR mutation, neutral BRCA1/2 GISTIC calls, low fraction genome altered, and modest mutation count. They are processed-data negative candidates, not proof of homologous-recombination proficiency.

## Boundary

No phase-1 label is based on WGS rearrangement signatures, SBS3 assignment, HRDetect, CHORD, Myriad myChoice, or clinician-owned companion-diagnostic review. Those remain future or external validation lanes.
`
  );

  console.log(`Selected ${selected.length} reference-panel samples.`);
}

await main();

