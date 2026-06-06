import {
  ensureDir,
  fetchJson,
  fetchText,
  parseDelimited,
  pathFromRoot,
  pivotClinical,
  postJson,
  writeCsv,
  writeJson,
  writeText
} from "./lib";

const CBIO = "https://www.cbioportal.org/api";
const STUDY_ID = "brca_tcga_pan_can_atlas_2018";
const XENA_CLINICAL = "https://tcga.xenahubs.net/download/TCGA.BRCA.sampleMap/BRCA_clinicalMatrix";

const hrrGenes = [
  "BRCA1",
  "BRCA2",
  "PALB2",
  "RAD51",
  "RAD51B",
  "RAD51C",
  "RAD51D",
  "ATM",
  "CHEK2",
  "BARD1",
  "BRIP1",
  "FANCA",
  "RAD50",
  "MRE11",
  "NBN"
];

const rnaMarkerGenes = [
  "ESR1",
  "PGR",
  "ERBB2",
  "AR",
  "FOXA1",
  "GATA3",
  "MKI67",
  "CD8A",
  "CD274",
  "CXCL9",
  "IFNG",
  "KRT5",
  "KRT14",
  "KRT17",
  "EGFR",
  "VIM",
  "EPCAM",
  "MUC1",
  "FOXC1"
];

type Gene = {
  entrezGeneId: number;
  hugoGeneSymbol: string;
  type: string;
};

type MolecularProfile = {
  molecularProfileId: string;
  molecularAlterationType: string;
  datatype: string;
  name: string;
  description?: string;
};

type SampleList = {
  sampleListId: string;
  category: string;
  name: string;
  description: string;
};

type Mutation = {
  sampleId: string;
  patientId: string;
  entrezGeneId: number;
  gene: Gene;
  mutationType: string;
  proteinChange?: string;
  tumorAltCount?: number;
  tumorRefCount?: number;
  normalAltCount?: number;
  normalRefCount?: number;
  keyword?: string;
  ncbiBuild?: string;
  chr?: string;
  startPosition?: number;
  endPosition?: number;
};

type MolecularData = {
  sampleId: string;
  patientId: string;
  entrezGeneId: number;
  gene: Gene;
  value: number;
};

type ClinicalRecord = {
  sampleId?: string;
  patientId?: string;
  clinicalAttributeId: string;
  value: string;
};

function requireGeneIds(genes: Gene[], symbols: string[]) {
  const bySymbol = new Map(genes.map((gene) => [gene.hugoGeneSymbol, gene.entrezGeneId]));
  const missing = symbols.filter((symbol) => !bySymbol.has(symbol));
  if (missing.length > 0) {
    throw new Error(`Missing Entrez IDs for: ${missing.join(", ")}`);
  }
  return symbols.map((symbol) => bySymbol.get(symbol) as number);
}

async function main() {
  for (const dir of [
    "data/raw/cbioportal",
    "data/raw/gdc",
    "data/raw/xena",
    "data/processed/catalog",
    "data/processed/cbioportal",
    "data/processed/gdc",
    "data/processed/xena",
    "manifests"
  ]) {
    ensureDir(pathFromRoot(dir));
  }

  const startedAt = new Date().toISOString();
  const study = await fetchJson(`${CBIO}/studies/${STUDY_ID}?projection=DETAILED`);
  const molecularProfiles = await fetchJson<MolecularProfile[]>(`${CBIO}/studies/${STUDY_ID}/molecular-profiles?projection=SUMMARY`);
  const sampleLists = await fetchJson<SampleList[]>(`${CBIO}/studies/${STUDY_ID}/sample-lists?projection=SUMMARY`);

  await writeJson(pathFromRoot("data/raw/cbioportal/study.json"), study);
  await writeJson(pathFromRoot("data/raw/cbioportal/molecular_profiles.json"), molecularProfiles);
  await writeJson(pathFromRoot("data/raw/cbioportal/sample_lists.json"), sampleLists);

  const sampleListIds = [
    "brca_tcga_pan_can_atlas_2018_all",
    "brca_tcga_pan_can_atlas_2018_3way_complete",
    "brca_tcga_pan_can_atlas_2018_sequenced",
    "brca_tcga_pan_can_atlas_2018_cna",
    "brca_tcga_pan_can_atlas_2018_rna_seq_v2_mrna"
  ];
  const sampleIdsByList: Record<string, string[]> = {};
  for (const sampleListId of sampleListIds) {
    sampleIdsByList[sampleListId] = await fetchJson<string[]>(`${CBIO}/sample-lists/${sampleListId}/sample-ids`);
  }
  await writeJson(pathFromRoot("data/raw/cbioportal/sample_ids_by_list.json"), sampleIdsByList);

  const genes = await postJson<Gene[]>(`${CBIO}/genes/fetch?geneIdType=HUGO_GENE_SYMBOL&projection=SUMMARY`, [
    ...new Set([...hrrGenes, ...rnaMarkerGenes])
  ]);
  await writeJson(pathFromRoot("data/raw/cbioportal/genes.json"), genes);

  const hrrEntrezIds = requireGeneIds(genes, hrrGenes);
  const rnaMarkerEntrezIds = requireGeneIds(genes, rnaMarkerGenes);

  const mutations = await postJson<Mutation[]>(
    `${CBIO}/molecular-profiles/${STUDY_ID}_mutations/mutations/fetch?projection=DETAILED`,
    {
      entrezGeneIds: hrrEntrezIds,
      sampleListId: `${STUDY_ID}_sequenced`
    }
  );
  await writeJson(pathFromRoot("data/raw/cbioportal/mutations_hrr.json"), mutations);
  await writeCsv(
    pathFromRoot("data/processed/cbioportal/mutations_hrr.csv"),
    mutations.map((mutation) => ({
      sampleId: mutation.sampleId,
      patientId: mutation.patientId,
      gene: mutation.gene.hugoGeneSymbol,
      entrezGeneId: mutation.entrezGeneId,
      mutationType: mutation.mutationType,
      proteinChange: mutation.proteinChange ?? "",
      tumorAltCount: mutation.tumorAltCount ?? "",
      tumorRefCount: mutation.tumorRefCount ?? "",
      normalAltCount: mutation.normalAltCount ?? "",
      normalRefCount: mutation.normalRefCount ?? "",
      ncbiBuild: mutation.ncbiBuild ?? "",
      chr: mutation.chr ?? "",
      startPosition: mutation.startPosition ?? "",
      endPosition: mutation.endPosition ?? "",
      keyword: mutation.keyword ?? ""
    }))
  );

  const cna = await postJson<MolecularData[]>(
    `${CBIO}/molecular-profiles/${STUDY_ID}_gistic/molecular-data/fetch?projection=DETAILED`,
    {
      entrezGeneIds: hrrEntrezIds,
      sampleListId: `${STUDY_ID}_cna`
    }
  );
  await writeJson(pathFromRoot("data/raw/cbioportal/cna_hrr_gistic.json"), cna);
  await writeCsv(
    pathFromRoot("data/processed/cbioportal/cna_hrr_gistic.csv"),
    cna.map((row) => ({
      sampleId: row.sampleId,
      patientId: row.patientId,
      gene: row.gene.hugoGeneSymbol,
      entrezGeneId: row.entrezGeneId,
      gisticValue: row.value
    }))
  );

  const expression = await postJson<MolecularData[]>(
    `${CBIO}/molecular-profiles/${STUDY_ID}_rna_seq_v2_mrna/molecular-data/fetch?projection=DETAILED`,
    {
      entrezGeneIds: rnaMarkerEntrezIds,
      sampleListId: `${STUDY_ID}_rna_seq_v2_mrna`
    }
  );
  await writeJson(pathFromRoot("data/raw/cbioportal/expression_marker_genes.json"), expression);
  await writeCsv(
    pathFromRoot("data/processed/cbioportal/expression_marker_genes.csv"),
    expression.map((row) => ({
      sampleId: row.sampleId,
      patientId: row.patientId,
      gene: row.gene.hugoGeneSymbol,
      entrezGeneId: row.entrezGeneId,
      expressionRsemBatchNormalized: row.value
    }))
  );

  const allSampleIds = sampleIdsByList[`${STUDY_ID}_all`];
  const allPatientIds = Array.from(new Set(allSampleIds.map((sampleId) => sampleId.slice(0, 12))));
  const sampleClinical = await postJson<ClinicalRecord[]>(
    `${CBIO}/studies/${STUDY_ID}/clinical-data/fetch?clinicalDataType=SAMPLE&projection=SUMMARY`,
    {
      ids: allSampleIds,
      attributeIds: [
        "CANCER_TYPE_DETAILED",
        "SAMPLE_TYPE",
        "FRACTION_GENOME_ALTERED",
        "MUTATION_COUNT",
        "TMB_NONSYNONYMOUS",
        "ANEUPLOIDY_SCORE"
      ]
    }
  );
  const patientClinical = await postJson<ClinicalRecord[]>(
    `${CBIO}/studies/${STUDY_ID}/clinical-data/fetch?clinicalDataType=PATIENT&projection=SUMMARY`,
    {
      ids: allPatientIds,
      attributeIds: ["SUBTYPE"]
    }
  );

  await writeJson(pathFromRoot("data/raw/cbioportal/clinical_sample_selected.json"), sampleClinical);
  await writeJson(pathFromRoot("data/raw/cbioportal/clinical_patient_selected.json"), patientClinical);
  await writeCsv(pathFromRoot("data/processed/cbioportal/clinical_sample_selected.csv"), pivotClinical(sampleClinical, "sampleId"));
  await writeCsv(pathFromRoot("data/processed/cbioportal/clinical_patient_selected.csv"), pivotClinical(patientClinical, "patientId"));

  const gdcBody = {
    filters: {
      op: "and",
      content: [
        { op: "in", content: { field: "cases.project.project_id", value: ["TCGA-BRCA"] } },
        { op: "in", content: { field: "access", value: ["open"] } }
      ]
    },
    fields: "file_id,file_name,data_category,data_type,experimental_strategy,access,file_size,md5sum",
    format: "JSON",
    size: "100",
    sort: "data_category:asc"
  };
  const gdcFiles = await postJson<{ data: { hits: Array<Record<string, unknown>>; pagination: { total: number } } }>(
    "https://api.gdc.cancer.gov/files",
    gdcBody
  );
  await writeJson(pathFromRoot("data/raw/gdc/tcga_brca_open_files_first100.json"), gdcFiles);

  const gdcCounts = new Map<string, number>();
  for (const hit of gdcFiles.data.hits) {
    const key = [hit.data_category, hit.data_type, hit.experimental_strategy].filter(Boolean).join(" | ");
    gdcCounts.set(key, (gdcCounts.get(key) ?? 0) + 1);
  }
  await writeJson(pathFromRoot("data/processed/catalog/gdc_tcga_brca_open_summary.json"), {
    source: "GDC files API",
    project: "TCGA-BRCA",
    query: gdcBody,
    firstPageCount: gdcFiles.data.hits.length,
    totalOpenFiles: gdcFiles.data.pagination.total,
    firstPageCounts: Array.from(gdcCounts.entries()).map(([category, count]) => ({ category, count }))
  });

  const xenaClinicalText = await fetchText(XENA_CLINICAL);
  await writeText(pathFromRoot("data/raw/xena/brca_clinical_matrix.tsv"), xenaClinicalText);
  const xenaRows = parseDelimited(xenaClinicalText, "\t");
  const xenaColumns = [
    "sampleID",
    "ER_Status_nature2012",
    "PR_Status_nature2012",
    "HER2_Final_Status_nature2012",
    "PAM50Call_RNAseq",
    "PAM50_mRNA_nature2012",
    "Integrated_Clusters_with_PAM50__nature2012"
  ];
  await writeCsv(
    pathFromRoot("data/processed/xena/brca_clinical_subset.csv"),
    xenaRows.map((row) => Object.fromEntries(xenaColumns.map((column) => [column, row[column] ?? ""])))
  );
  await writeJson(pathFromRoot("data/processed/catalog/xena_tcga_brca_clinical_summary.json"), {
    source: XENA_CLINICAL,
    rowCount: xenaRows.length,
    columnCount: Object.keys(xenaRows[0] ?? {}).length,
    selectedColumns: xenaColumns,
    sampleIntersectionWithCbioAll: xenaRows.filter((row) => allSampleIds.includes(row.sampleID)).length
  });

  await writeJson(pathFromRoot("data/processed/catalog/cbioportal_tcga_brca_summary.json"), {
    fetchedAt: startedAt,
    studyId: STUDY_ID,
    study,
    molecularProfileCount: molecularProfiles.length,
    sampleListCount: sampleLists.length,
    sampleCounts: Object.fromEntries(Object.entries(sampleIdsByList).map(([id, rows]) => [id, rows.length])),
    hrrGenes,
    rnaMarkerGenes,
    mutationCount: mutations.length,
    cnaRecordCount: cna.length,
    expressionRecordCount: expression.length,
    sampleClinicalRecordCount: sampleClinical.length,
    patientClinicalRecordCount: patientClinical.length
  });

  await writeJson(pathFromRoot("manifests/file_manifest.json"), {
    fetchedAt: startedAt,
    generatedBy: "scripts/fetch-phase1.ts",
    sources: [
      {
        id: "cbioportal-brca-pan-cancer",
        studyId: STUDY_ID,
        access: "open",
        files: [
          "data/raw/cbioportal/study.json",
          "data/raw/cbioportal/molecular_profiles.json",
          "data/raw/cbioportal/sample_lists.json",
          "data/raw/cbioportal/sample_ids_by_list.json",
          "data/raw/cbioportal/genes.json",
          "data/raw/cbioportal/mutations_hrr.json",
          "data/raw/cbioportal/cna_hrr_gistic.json",
          "data/raw/cbioportal/expression_marker_genes.json",
          "data/raw/cbioportal/clinical_sample_selected.json",
          "data/raw/cbioportal/clinical_patient_selected.json"
        ]
      },
      {
        id: "gdc-tcga-brca-open-catalog",
        access: "open metadata only",
        files: ["data/raw/gdc/tcga_brca_open_files_first100.json"]
      },
      {
        id: "ucsc-xena-tcga-brca-clinical",
        access: "open",
        files: ["data/raw/xena/brca_clinical_matrix.tsv"]
      }
    ]
  });

  console.log(`Fetched phase-1 data: ${mutations.length} HRR mutations, ${cna.length} CNA records, ${expression.length} expression records.`);
}

await main();

