from __future__ import annotations

from ..paths import path_from_root
from ..utils import (
    ensure_dir,
    fetch_json,
    fetch_text,
    iso_now,
    parse_delimited,
    pivot_clinical,
    post_json,
    write_csv,
    write_json,
    write_text,
)

CBIO = "https://www.cbioportal.org/api"
STUDY_ID = "brca_tcga_pan_can_atlas_2018"
XENA_CLINICAL = "https://tcga.xenahubs.net/download/TCGA.BRCA.sampleMap/BRCA_clinicalMatrix"
HRR_GENES = [
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
    "NBN",
]
RNA_MARKER_GENES = [
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
    "FOXC1",
]


def require_gene_ids(genes: list[dict], symbols: list[str]) -> list[int]:
    by_symbol = {gene["hugoGeneSymbol"]: gene["entrezGeneId"] for gene in genes}
    missing = [symbol for symbol in symbols if symbol not in by_symbol]
    if missing:
        raise RuntimeError(f"Missing Entrez IDs for: {', '.join(missing)}")
    return [by_symbol[symbol] for symbol in symbols]


def main() -> None:
    started_at = iso_now()
    for directory in [
        "data/raw/cbioportal",
        "data/raw/gdc",
        "data/raw/xena",
        "data/processed/catalog",
        "data/processed/cbioportal",
        "data/processed/gdc",
        "data/processed/xena",
        "manifests",
    ]:
        ensure_dir(path_from_root(directory))

    study = fetch_json(f"{CBIO}/studies/{STUDY_ID}?projection=DETAILED")
    molecular_profiles = fetch_json(f"{CBIO}/studies/{STUDY_ID}/molecular-profiles?projection=SUMMARY")
    sample_lists = fetch_json(f"{CBIO}/studies/{STUDY_ID}/sample-lists?projection=SUMMARY")
    write_json(path_from_root("data/raw/cbioportal/study.json"), study)
    write_json(path_from_root("data/raw/cbioportal/molecular_profiles.json"), molecular_profiles)
    write_json(path_from_root("data/raw/cbioportal/sample_lists.json"), sample_lists)

    sample_list_ids = [
        "brca_tcga_pan_can_atlas_2018_all",
        "brca_tcga_pan_can_atlas_2018_3way_complete",
        "brca_tcga_pan_can_atlas_2018_sequenced",
        "brca_tcga_pan_can_atlas_2018_cna",
        "brca_tcga_pan_can_atlas_2018_rna_seq_v2_mrna",
    ]
    sample_ids_by_list = {
        sample_list_id: fetch_json(f"{CBIO}/sample-lists/{sample_list_id}/sample-ids") for sample_list_id in sample_list_ids
    }
    write_json(path_from_root("data/raw/cbioportal/sample_ids_by_list.json"), sample_ids_by_list)

    genes = post_json(f"{CBIO}/genes/fetch?geneIdType=HUGO_GENE_SYMBOL&projection=SUMMARY", sorted(set(HRR_GENES + RNA_MARKER_GENES)))
    write_json(path_from_root("data/raw/cbioportal/genes.json"), genes)
    hrr_entrez_ids = require_gene_ids(genes, HRR_GENES)
    rna_marker_entrez_ids = require_gene_ids(genes, RNA_MARKER_GENES)

    mutations = post_json(
        f"{CBIO}/molecular-profiles/{STUDY_ID}_mutations/mutations/fetch?projection=DETAILED",
        {"entrezGeneIds": hrr_entrez_ids, "sampleListId": f"{STUDY_ID}_sequenced"},
    )
    write_json(path_from_root("data/raw/cbioportal/mutations_hrr.json"), mutations)
    write_csv(
        path_from_root("data/processed/cbioportal/mutations_hrr.csv"),
        [
            {
                "sampleId": mutation["sampleId"],
                "patientId": mutation["patientId"],
                "gene": mutation["gene"]["hugoGeneSymbol"],
                "entrezGeneId": mutation["entrezGeneId"],
                "mutationType": mutation["mutationType"],
                "proteinChange": mutation.get("proteinChange", ""),
                "tumorAltCount": mutation.get("tumorAltCount", ""),
                "tumorRefCount": mutation.get("tumorRefCount", ""),
                "normalAltCount": mutation.get("normalAltCount", ""),
                "normalRefCount": mutation.get("normalRefCount", ""),
                "ncbiBuild": mutation.get("ncbiBuild", ""),
                "chr": mutation.get("chr", ""),
                "startPosition": mutation.get("startPosition", ""),
                "endPosition": mutation.get("endPosition", ""),
                "keyword": mutation.get("keyword", ""),
            }
            for mutation in mutations
        ],
    )

    cna = post_json(
        f"{CBIO}/molecular-profiles/{STUDY_ID}_gistic/molecular-data/fetch?projection=DETAILED",
        {"entrezGeneIds": hrr_entrez_ids, "sampleListId": f"{STUDY_ID}_cna"},
    )
    write_json(path_from_root("data/raw/cbioportal/cna_hrr_gistic.json"), cna)
    write_csv(
        path_from_root("data/processed/cbioportal/cna_hrr_gistic.csv"),
        [
            {
                "sampleId": row["sampleId"],
                "patientId": row["patientId"],
                "gene": row["gene"]["hugoGeneSymbol"],
                "entrezGeneId": row["entrezGeneId"],
                "gisticValue": row["value"],
            }
            for row in cna
        ],
    )

    expression = post_json(
        f"{CBIO}/molecular-profiles/{STUDY_ID}_rna_seq_v2_mrna/molecular-data/fetch?projection=DETAILED",
        {"entrezGeneIds": rna_marker_entrez_ids, "sampleListId": f"{STUDY_ID}_rna_seq_v2_mrna"},
    )
    write_json(path_from_root("data/raw/cbioportal/expression_marker_genes.json"), expression)
    write_csv(
        path_from_root("data/processed/cbioportal/expression_marker_genes.csv"),
        [
            {
                "sampleId": row["sampleId"],
                "patientId": row["patientId"],
                "gene": row["gene"]["hugoGeneSymbol"],
                "entrezGeneId": row["entrezGeneId"],
                "expressionRsemBatchNormalized": row["value"],
            }
            for row in expression
        ],
    )

    all_sample_ids = sample_ids_by_list[f"{STUDY_ID}_all"]
    all_patient_ids = sorted(set(sample_id[:12] for sample_id in all_sample_ids))
    sample_clinical = post_json(
        f"{CBIO}/studies/{STUDY_ID}/clinical-data/fetch?clinicalDataType=SAMPLE&projection=SUMMARY",
        {
            "ids": all_sample_ids,
            "attributeIds": [
                "CANCER_TYPE_DETAILED",
                "SAMPLE_TYPE",
                "FRACTION_GENOME_ALTERED",
                "MUTATION_COUNT",
                "TMB_NONSYNONYMOUS",
                "ANEUPLOIDY_SCORE",
            ],
        },
    )
    patient_clinical = post_json(
        f"{CBIO}/studies/{STUDY_ID}/clinical-data/fetch?clinicalDataType=PATIENT&projection=SUMMARY",
        {"ids": all_patient_ids, "attributeIds": ["SUBTYPE"]},
    )
    write_json(path_from_root("data/raw/cbioportal/clinical_sample_selected.json"), sample_clinical)
    write_json(path_from_root("data/raw/cbioportal/clinical_patient_selected.json"), patient_clinical)
    write_csv(path_from_root("data/processed/cbioportal/clinical_sample_selected.csv"), pivot_clinical(sample_clinical, "sampleId"))
    write_csv(path_from_root("data/processed/cbioportal/clinical_patient_selected.csv"), pivot_clinical(patient_clinical, "patientId"))

    gdc_body = {
        "filters": {
            "op": "and",
            "content": [
                {"op": "in", "content": {"field": "cases.project.project_id", "value": ["TCGA-BRCA"]}},
                {"op": "in", "content": {"field": "access", "value": ["open"]}},
            ],
        },
        "fields": "file_id,file_name,data_category,data_type,experimental_strategy,access,file_size,md5sum",
        "format": "JSON",
        "size": "100",
        "sort": "data_category:asc",
    }
    gdc_files = post_json("https://api.gdc.cancer.gov/files", gdc_body)
    write_json(path_from_root("data/raw/gdc/tcga_brca_open_files_first100.json"), gdc_files)
    gdc_counts: dict[str, int] = {}
    for hit in gdc_files["data"]["hits"]:
        key = " | ".join(str(hit[field]) for field in ["data_category", "data_type", "experimental_strategy"] if hit.get(field))
        gdc_counts[key] = gdc_counts.get(key, 0) + 1
    write_json(
        path_from_root("data/processed/catalog/gdc_tcga_brca_open_summary.json"),
        {
            "source": "GDC files API",
            "project": "TCGA-BRCA",
            "query": gdc_body,
            "firstPageCount": len(gdc_files["data"]["hits"]),
            "totalOpenFiles": gdc_files["data"]["pagination"]["total"],
            "firstPageCounts": [{"category": key, "count": count} for key, count in gdc_counts.items()],
        },
    )

    xena_text = fetch_text(XENA_CLINICAL)
    write_text(path_from_root("data/raw/xena/brca_clinical_matrix.tsv"), xena_text)
    xena_rows = parse_delimited(xena_text, "\t")
    xena_columns = [
        "sampleID",
        "ER_Status_nature2012",
        "PR_Status_nature2012",
        "HER2_Final_Status_nature2012",
        "PAM50Call_RNAseq",
        "PAM50_mRNA_nature2012",
        "Integrated_Clusters_with_PAM50__nature2012",
    ]
    write_csv(
        path_from_root("data/processed/xena/brca_clinical_subset.csv"),
        [{column: row.get(column, "") for column in xena_columns} for row in xena_rows],
    )
    write_json(
        path_from_root("data/processed/catalog/xena_tcga_brca_clinical_summary.json"),
        {
            "source": XENA_CLINICAL,
            "rowCount": len(xena_rows),
            "columnCount": len(xena_rows[0]) if xena_rows else 0,
            "selectedColumns": xena_columns,
            "sampleIntersectionWithCbioAll": len([row for row in xena_rows if row.get("sampleID") in all_sample_ids]),
        },
    )

    write_json(
        path_from_root("data/processed/catalog/cbioportal_tcga_brca_summary.json"),
        {
            "fetchedAt": started_at,
            "studyId": STUDY_ID,
            "study": study,
            "molecularProfileCount": len(molecular_profiles),
            "sampleListCount": len(sample_lists),
            "sampleCounts": {key: len(rows) for key, rows in sample_ids_by_list.items()},
            "hrrGenes": HRR_GENES,
            "rnaMarkerGenes": RNA_MARKER_GENES,
            "mutationCount": len(mutations),
            "cnaRecordCount": len(cna),
            "expressionRecordCount": len(expression),
            "sampleClinicalRecordCount": len(sample_clinical),
            "patientClinicalRecordCount": len(patient_clinical),
        },
    )
    write_json(
        path_from_root("manifests/file_manifest.json"),
        {
            "fetchedAt": started_at,
            "generatedBy": "src/diana_omics/commands/fetch_phase1.py",
            "sources": [
                {
                    "id": "cbioportal-brca-pan-cancer",
                    "studyId": STUDY_ID,
                    "access": "open",
                    "files": [
                        "data/raw/cbioportal/study.json",
                        "data/raw/cbioportal/molecular_profiles.json",
                        "data/raw/cbioportal/sample_lists.json",
                        "data/raw/cbioportal/sample_ids_by_list.json",
                        "data/raw/cbioportal/genes.json",
                        "data/raw/cbioportal/mutations_hrr.json",
                        "data/raw/cbioportal/cna_hrr_gistic.json",
                        "data/raw/cbioportal/expression_marker_genes.json",
                        "data/raw/cbioportal/clinical_sample_selected.json",
                        "data/raw/cbioportal/clinical_patient_selected.json",
                    ],
                },
                {
                    "id": "gdc-tcga-brca-open-catalog",
                    "access": "open metadata only",
                    "files": ["data/raw/gdc/tcga_brca_open_files_first100.json"],
                },
                {"id": "ucsc-xena-tcga-brca-clinical", "access": "open", "files": ["data/raw/xena/brca_clinical_matrix.tsv"]},
            ],
        },
    )
    print(f"Fetched phase-1 data: {len(mutations)} HRR mutations, {len(cna)} CNA records, {len(expression)} expression records.")


if __name__ == "__main__":
    main()
