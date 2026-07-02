from __future__ import annotations

import os
import sys
from typing import Any, Optional

from ... import vendor_normalize as vn
from ...paths import path_from_root
from ...tcga_standard import tcga_standard_contract
from ...utils import (
    ensure_dir,
    iso_now,
    parse_csv,
    parse_delimited,
    read_text,
    to_number,
    write_csv,
    write_json,
    write_text,
)


def selected_manifest() -> str:
    return os.environ.get("DIANA_VENDOR_MANIFEST", vn.VENDOR_MANIFEST_DEFAULT)


def require_data() -> bool:
    return os.environ.get("DIANA_VENDOR_REQUIRE_DATA") == "1"


def analysis_id() -> str:
    return os.environ.get("DIANA_VENDOR_ANALYSIS_ID", "diana_vendor_initial")


def _read_delimited_file(relative_or_absolute: str) -> list[dict[str, str]]:
    path = path_from_root(relative_or_absolute) if not os.path.isabs(relative_or_absolute) else relative_or_absolute
    text = read_text(path)
    delimiter = "," if str(relative_or_absolute).lower().endswith(".csv") else "\t"
    return parse_delimited(text, delimiter)


def _resolve(relative_or_absolute: str) -> str:
    return relative_or_absolute if os.path.isabs(relative_or_absolute) else str(path_from_root(relative_or_absolute))


def write_template() -> None:
    rows = vn.vendor_manifest_template_rows()
    write_csv(path_from_root(vn.VENDOR_MANIFEST_TEMPLATE), rows, vn.VENDOR_MANIFEST_COLUMNS)


def normalize_sample(row: dict[str, str]) -> dict[str, Any]:
    sample_id = row.get("sample_id", "")
    patient_id = row.get("patient_id", "") or sample_id
    build = row.get("reference_build", "")
    ploidy = to_number(row.get("ploidy")) or 2.0

    mutations: list[dict[str, Any]] = []
    drop_counts: dict[str, int] = {}
    variants_in = 0
    variants_in_hrr = 0
    unmapped_consequences: set[str] = set()

    variant_file = row.get("variant_file", "")
    if variant_file:
        fmt = vn.detect_variant_format(variant_file, row.get("variant_format", ""))
        text = read_text(_resolve(variant_file))
        records = vn.parse_variant_file(text, fmt, row.get("tumor_sample_column", ""), row.get("normal_sample_column", ""))
        variants_in = len(records)
        for record in records:
            if vn.tcga.is_hrr_gene(str(record.get("gene", ""))):
                variants_in_hrr += 1
            kept, reason = vn.filter_variant(record)
            if not kept:
                drop_counts[reason] = drop_counts.get(reason, 0) + 1
                continue
            classification = vn.tcga.variant_classification(
                str(record.get("consequence", "")), str(record.get("ref", "")), str(record.get("alt", ""))
            )
            if not classification and record.get("consequence"):
                unmapped_consequences.add(str(record.get("consequence")))
            mutations.append(vn.to_canonical_mutation(record, sample_id, patient_id, build))

    cna_by_gene: dict[str, int] = {}
    if row.get("cnv_gene_file"):
        cna_by_gene = vn.gene_cnv_to_gistic(_read_delimited_file(row["cnv_gene_file"]), ploidy)

    fga_from_seg: Optional[float] = None
    if row.get("cnv_seg_file"):
        fga_from_seg = vn.fraction_genome_altered(_read_delimited_file(row["cnv_seg_file"]), ploidy)

    cna_records = [
        {"sampleId": sample_id, "patientId": patient_id, "gene": {"hugoGeneSymbol": gene}, "value": value}
        for gene, value in sorted(cna_by_gene.items())
    ]

    # TMB / mutation count: prefer vendor-provided QC, else derive from kept HRR
    # variants normalized by capture size (clearly a partial HRR-only estimate).
    capture_mb = to_number(row.get("capture_megabases"))
    nonsyn = sum(1 for mutation in mutations if vn.tcga.is_nonsynonymous(str(mutation["mutationType"])))
    mutation_count = to_number(row.get("mutation_count"))
    tmb = to_number(row.get("tmb_nonsynonymous"))
    if tmb is None and mutation_count is not None and capture_mb and capture_mb > 0:
        tmb = mutation_count / capture_mb
    fga = fga_from_seg
    aneuploidy = to_number(row.get("aneuploidy_score"))

    clinical = vn.clinical_records(
        sample_id,
        fga=fga,
        mutation_count=mutation_count,
        tmb=tmb,
        aneuploidy=aneuploidy,
        sample_type=row.get("sample_type", ""),
        cancer_type_detailed=row.get("cancer_type_detailed", ""),
    )

    build_compatible = vn.tcga.position_compatible_with_tcga(build)
    report = {
        "sampleId": sample_id,
        "patientId": patient_id,
        "vendor": row.get("vendor", ""),
        "assay": row.get("assay", ""),
        "referenceBuildIn": build,
        "referenceBuildCanonical": vn.tcga.normalize_build(build),
        "positionCompatibleWithTcga": build_compatible,
        "variantsIn": variants_in,
        "variantsInHrr": variants_in_hrr,
        "mutationsKept": len(mutations),
        "nonsynonymousKept": nonsyn,
        "droppedByRule": drop_counts,
        "cnaGenesNormalized": len(cna_records),
        "fractionGenomeAltered": fga,
        "tmbNonsynonymous": round(tmb, 4) if tmb is not None else None,
        "mutationCount": int(mutation_count) if mutation_count is not None else None,
        "unmappedConsequences": sorted(unmapped_consequences),
        "somaticFiltersApplied": variant_file != "",
        "caveats": _sample_caveats(row, build_compatible, capture_mb, fga, variant_file),
    }
    return {"mutations": mutations, "cna": cna_records, "clinical": clinical, "report": report}


def _sample_caveats(
    row: dict[str, str], build_compatible: bool, capture_mb: Optional[float], fga: Optional[float], variant_file: str
) -> list[str]:
    caveats: list[str] = []
    if not build_compatible:
        caveats.append("Reference build differs from TCGA GRCh37; gene-level joins hold but position-level comparisons require liftover.")
    if not variant_file:
        caveats.append("No vendor variant file provided; mutation table is empty for this sample.")
    if to_number(row.get("tmb_nonsynonymous")) is None and to_number(row.get("mutation_count")) is None:
        caveats.append("No vendor MUTATION_COUNT/TMB supplied; exome-wide mutational burden is not reconstructed from HRR-only variants.")
    if fga is None and not row.get("cnv_gene_file"):
        caveats.append("No CNV input; FRACTION_GENOME_ALTERED and copy-number second-hit proxy are unavailable.")
    if capture_mb is None and (row.get("assay") or "").upper() == "WES":
        caveats.append("WES capture_megabases missing; TMB normalization cannot be computed from vendor counts.")
    return caveats


def main() -> None:
    manifest = selected_manifest()
    manifest_path = path_from_root(manifest)
    output_dir = f"{vn.VENDOR_RESULTS}/{analysis_id()}"
    ensure_dir(path_from_root(vn.VENDOR_RESULTS))
    write_template()

    if not manifest_path.exists():
        status = "missing_vendor_manifest" if require_data() else "waiting_for_vendor_data"
        write_json(
            path_from_root(f"{vn.VENDOR_RESULTS}/normalization_status.json"),
            {
                "generatedAt": iso_now(),
                "status": status,
                "manifest": manifest,
                "template": vn.VENDOR_MANIFEST_TEMPLATE,
                "tcgaStandard": tcga_standard_contract(),
            },
        )
        if require_data():
            print(f"error: missing {manifest}. Copy {vn.VENDOR_MANIFEST_TEMPLATE} and fill in real vendor paths.", file=sys.stderr)
            raise SystemExit(1)
        print(f"Vendor normalization waiting for data; template ready at {vn.VENDOR_MANIFEST_TEMPLATE}.")
        return

    rows = parse_csv(read_text(manifest_path))
    missing_columns = [column for column in vn.VENDOR_MANIFEST_COLUMNS if rows and column not in rows[0]]
    if missing_columns:
        print(f"error: vendor manifest missing columns: {', '.join(missing_columns)}", file=sys.stderr)
        raise SystemExit(1)

    ensure_dir(path_from_root(output_dir))
    all_mutations: list[dict[str, Any]] = []
    all_cna: list[dict[str, Any]] = []
    all_clinical: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("sample_id"):
            continue
        result = normalize_sample(row)
        all_mutations.extend(result["mutations"])
        all_cna.extend(result["cna"])
        all_clinical.extend(result["clinical"])
        reports.append(result["report"])

    write_json(path_from_root(f"{output_dir}/mutations_hrr.json"), all_mutations)
    write_json(path_from_root(f"{output_dir}/cna_hrr_gistic.json"), all_cna)
    write_json(path_from_root(f"{output_dir}/clinical_sample_selected.json"), all_clinical)
    write_csv(
        path_from_root(f"{output_dir}/mutations_hrr.csv"),
        [
            {
                "sampleId": mutation["sampleId"],
                "patientId": mutation["patientId"],
                "gene": mutation["gene"]["hugoGeneSymbol"],
                "mutationType": mutation["mutationType"],
                "proteinChange": mutation["proteinChange"],
                "tumorAltCount": mutation["tumorAltCount"],
                "tumorRefCount": mutation["tumorRefCount"],
                "ncbiBuild": mutation["ncbiBuild"],
                "chr": mutation["chr"],
                "startPosition": mutation["startPosition"],
            }
            for mutation in all_mutations
        ],
    )
    write_csv(
        path_from_root(f"{output_dir}/cna_hrr_gistic.csv"),
        [{"sampleId": row["sampleId"], "gene": row["gene"]["hugoGeneSymbol"], "gisticValue": row["value"]} for row in all_cna],
    )
    report_rows = [
        {
            "sample_id": report["sampleId"],
            "vendor": report["vendor"],
            "assay": report["assay"],
            "reference_build_in": report["referenceBuildIn"],
            "reference_build_canonical": report["referenceBuildCanonical"],
            "position_compatible_with_tcga": "yes" if report["positionCompatibleWithTcga"] else "no",
            "variants_in": report["variantsIn"],
            "variants_in_hrr": report["variantsInHrr"],
            "mutations_kept": report["mutationsKept"],
            "nonsynonymous_kept": report["nonsynonymousKept"],
            "cna_genes_normalized": report["cnaGenesNormalized"],
            "fraction_genome_altered": "" if report["fractionGenomeAltered"] is None else report["fractionGenomeAltered"],
            "tmb_nonsynonymous": "" if report["tmbNonsynonymous"] is None else report["tmbNonsynonymous"],
            "mutation_count": "" if report["mutationCount"] is None else report["mutationCount"],
            "dropped_total": sum(report["droppedByRule"].values()),
        }
        for report in reports
    ]
    write_csv(path_from_root(f"{output_dir}/normalization_report.csv"), report_rows)
    write_json(
        path_from_root(f"{output_dir}/normalization_report.json"),
        {
            "generatedAt": iso_now(),
            "status": "normalized",
            "analysisId": analysis_id(),
            "manifest": manifest,
            "outputDir": output_dir,
            "sampleCount": len(reports),
            "mutationCount": len(all_mutations),
            "cnaRecordCount": len(all_cna),
            "clinicalRecordCount": len(all_clinical),
            "perSample": reports,
            "tcgaStandard": tcga_standard_contract(),
            "downstreamContract": {
                "mutationsFile": f"{output_dir}/mutations_hrr.json",
                "cnaFile": f"{output_dir}/cna_hrr_gistic.json",
                "clinicalFile": f"{output_dir}/clinical_sample_selected.json",
                "note": "These files match the cBioPortal-derived shapes consumed by analyze:hrd, so Diana vendor samples can be scored on the same standard as the TCGA reference panel.",
            },
            "interpretationBoundary": "Normalization enforces TCGA-equivalent somatic filters and schema. It does not assert any HRD result; reviewer sign-off and full-feature HRD signatures are still required.",
        },
    )
    write_text(
        path_from_root(f"{output_dir}/README.md"),
        f"""# Diana Vendor Normalization Packet

Status: **normalized**.

Analysis ID: `{analysis_id()}`

Manifest: `{manifest}`

Samples normalized: `{len(reports)}`

Mutations kept (TCGA-filtered): `{len(all_mutations)}`

CNA gene records: `{len(all_cna)}`

## What This Does

Vendor (Personalis/Natera/...) WES/WGS variant and copy-number deliverables are
mapped onto the common TCGA-BRCA schema and filtered to the same somatic
standard the TCGA reference panel meets:

- HUGO gene-symbol normalization and HRR-gene scoping.
- VEP/SnpEff/MAF consequence vocabulary mapped to MAF Variant_Classification.
- PASS-only, depth/alt-count/VAF, and clean-normal somatic filters.
- Vendor copy number (absolute CN or log2) discretized to GISTIC {{-2..2}}.
- FRACTION_GENOME_ALTERED computed from segments; TMB/mutation count normalized.
- Reference build harmonized and position-compatibility with TCGA flagged.

## Downstream

`mutations_hrr.json`, `cna_hrr_gistic.json`, and `clinical_sample_selected.json`
match the shapes consumed by `analyze:hrd`, so a normalized Diana sample can be
scored beside the public reference panel without bespoke parsing.

## Boundary

Normalization standardizes and filters inputs. It does not make an HRD call.
""",
    )
    print(f"Normalized {len(reports)} vendor sample(s): {len(all_mutations)} mutations, {len(all_cna)} CNA records -> {output_dir}")


if __name__ == "__main__":
    main()
