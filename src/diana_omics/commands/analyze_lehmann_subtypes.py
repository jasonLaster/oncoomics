from __future__ import annotations

import gzip
import json
import math
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence
from xml.etree import ElementTree

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_text, round_value, write_csv, write_json, write_text

LEHMANN_S1_URL = "https://doi.org/10.1371/journal.pone.0157368.s006"
LEHMANN_SIGNATURE_SOURCE = "https://github.com/BCTL-Bordet/TNBC_molecularsubtypes/blob/main/lehmann.RData"
LEHMANN_S1_RAW = "data/raw/lehmann/pone0157368s006.xlsx"
LEHMANN_SIGNATURE_PROCESSED = "data/processed/lehmann/lehmann_signature_genes.csv"
LEHMANN_S1_PROCESSED = "data/processed/lehmann/tcga_tnbc_lehmann_s1_calls.csv"
LEHMANN_SIGNATURE_EXPRESSION_RAW = "data/raw/lehmann/cbioportal_tcga_tnbc_lehmann_signature_expression.json.gz"
LEHMANN_SIGNATURE_VALIDATION_OUTPUT = "results/lehmann_signature_tcga_validation.csv"
LEHMANN_SIGNATURE_VALIDATION_EVIDENCE = "results/evidence_tables/lehmann_signature_tcga_validation.csv"
LEHMANN_SIGNATURE_VALIDATION_SUMMARY = "results/lehmann_signature_tcga_validation_summary.json"
LEHMANN_SIGNATURE_VALIDATION_MD = "results/lehmann_signature_tcga_validation.md"
PANEL_OUTPUT = "results/lehmann_tnbc_tcga_panel.csv"
EVIDENCE_OUTPUT = "results/evidence_tables/lehmann_tnbc_tcga_panel.csv"
SUMMARY_JSON = "results/lehmann_tnbc_feasibility_summary.json"
SUMMARY_MD = "results/lehmann_tnbc_feasibility.md"
CBIO_EXPRESSION_URL = (
    "https://www.cbioportal.org/api/molecular-profiles/"
    "brca_tcga_pan_can_atlas_2018_rna_seq_v2_mrna/molecular-data/fetch?projection=DETAILED"
)
SUBTYPE_ORDER = ["basal_like_1", "basal_like_2", "immunomodulatory", "mesenchymal", "mesenchymal_stem_like", "luminal_ar"]
SUBTYPE_SHORT = {
    "basal_like_1": "BL1",
    "basal_like_2": "BL2",
    "immunomodulatory": "IM",
    "mesenchymal": "M",
    "mesenchymal_stem_like": "MSL",
    "luminal_ar": "LAR",
}


def column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + ord(char.upper()) - ord("A") + 1
    return index - 1


def xml_text(element: ElementTree.Element) -> str:
    return "".join(element.itertext())


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        shared_xml = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(shared_xml)
    return [xml_text(item) for item in root.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si")]


def read_first_sheet_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = read_shared_strings(archive)
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    root = ElementTree.fromstring(sheet_xml)
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rows: list[list[str]] = []
    for row in root.findall(f".//{namespace}row"):
        values: list[str] = []
        for cell in row.findall(f"{namespace}c"):
            ref = cell.attrib.get("r", "")
            index = column_index(ref)
            while len(values) <= index:
                values.append("")
            raw_value = cell.find(f"{namespace}v")
            inline_value = cell.find(f"{namespace}is")
            if inline_value is not None:
                value = xml_text(inline_value)
            elif raw_value is None:
                value = ""
            elif cell.attrib.get("t") == "s":
                value = shared_strings[int(raw_value.text or "0")]
            else:
                value = raw_value.text or ""
            values[index] = value.strip() if isinstance(value, str) else str(value)
        rows.append(values)
    return rows


def fetch_if_missing(url: str, relative_path: str) -> Path:
    path = path_from_root(relative_path)
    if path.exists() and path.stat().st_size > 0:
        return path
    ensure_dir(path.parent)
    request = urllib.request.Request(url, headers={"User-Agent": "diana-omics/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    path.write_bytes(data)
    return path


def parse_lehmann_s1(path: Path) -> list[dict[str, str]]:
    rows = read_first_sheet_rows(path)
    if len(rows) < 3:
        raise RuntimeError(f"Lehmann S1 table has too few rows: {path}")
    headers = [value.strip() for value in rows[1]]
    parsed_rows = []
    for row in rows[2:]:
        record = {header: row[index].strip() if index < len(row) else "" for index, header in enumerate(headers) if header}
        patient_id = record.get("TCGA_Barcode", "")
        if not patient_id:
            continue
        parsed_rows.append(
            {
                "patient_id": patient_id,
                "sample_id": f"{patient_id}-01",
                "slide_id": record.get("Slide_ID", ""),
                "til_fraction": record.get("% of mononuclear cells within section", ""),
                "til_score_category": record.get("IM_SCORE_CAT", ""),
                "lehmann_tnbctype": record.get("TNBCtype", ""),
                "lehmann_refined_tnbctype": record.get("Refined TNBCtype", ""),
                "lehmann_im_corr": record.get("IM", ""),
                "lehmann_bl1_corr": record.get("BL1", ""),
                "lehmann_msl_corr": record.get("MSL", ""),
                "lehmann_m_corr": record.get("M", ""),
                "lehmann_bl2_corr": record.get("BL2", ""),
                "lehmann_lar_corr": record.get("LAR", ""),
            }
        )
    return parsed_rows


def valid_entrez(value: str) -> bool:
    return value.strip().isdigit()


def post_json(url: str, body: object, timeout: int = 120) -> object:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "diana-omics/0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_signature_rows() -> list[dict[str, str]]:
    path = path_from_root(LEHMANN_SIGNATURE_PROCESSED)
    if not path.exists():
        raise RuntimeError(
            f"Missing {LEHMANN_SIGNATURE_PROCESSED}. This file is the CSV conversion of {LEHMANN_SIGNATURE_SOURCE}."
        )
    rows = parse_csv(read_text(path))
    required = {"signature", "gene", "entrez", "coefficient"}
    if rows and not required.issubset(rows[0]):
        raise RuntimeError(f"{LEHMANN_SIGNATURE_PROCESSED} is missing required columns: {sorted(required)}")
    return rows


def read_expression_cache(path: Path) -> list[dict[str, object]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise RuntimeError(f"{path} must contain a JSON list.")
    return [record for record in data if isinstance(record, dict)]


def write_expression_cache(path: Path, records: list[dict[str, object]]) -> None:
    ensure_dir(path.parent)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(records, handle, separators=(",", ":"))


def fetch_signature_expression(signature_rows: Sequence[dict[str, str]], official_rows: Sequence[dict[str, str]]) -> list[dict[str, object]]:
    path = path_from_root(LEHMANN_SIGNATURE_EXPRESSION_RAW)
    if path.exists() and path.stat().st_size > 0:
        return read_expression_cache(path)

    sample_ids = [row["sample_id"] for row in official_rows]
    entrez_ids = sorted({int(row["entrez"]) for row in signature_rows if valid_entrez(row.get("entrez", ""))})
    records: list[dict[str, object]] = []
    chunk_size = 250
    for start in range(0, len(entrez_ids), chunk_size):
        chunk = entrez_ids[start : start + chunk_size]
        fetched = post_json(CBIO_EXPRESSION_URL, {"entrezGeneIds": chunk, "sampleIds": sample_ids})
        if not isinstance(fetched, list):
            raise RuntimeError("cBioPortal expression endpoint returned a non-list payload.")
        records.extend(record for record in fetched if isinstance(record, dict))
        print(
            f"Fetched Lehmann expression chunk {start // chunk_size + 1}/{math.ceil(len(entrez_ids) / chunk_size)} "
            f"records={len(fetched)} total={len(records)}",
            flush=True,
        )
    write_expression_cache(path, records)
    return records


def expression_value(record: dict[str, object]) -> Optional[float]:
    value = record.get("value")
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return math.log2(number + 1.0) if math.isfinite(number) and number >= 0 else None


def build_z_scores(records: Sequence[dict[str, object]], sample_ids: Sequence[str]) -> tuple[dict[tuple[int, str], float], set[int], set[str]]:
    by_gene_sample: dict[tuple[int, str], float] = {}
    available_entrez: set[int] = set()
    available_samples: set[str] = set()
    for record in records:
        sample_id = str(record.get("sampleId", ""))
        entrez = record.get("entrezGeneId")
        value = expression_value(dict(record))
        if not sample_id or value is None:
            continue
        try:
            entrez_id = int(str(entrez))
        except (TypeError, ValueError):
            continue
        by_gene_sample[(entrez_id, sample_id)] = value
        available_entrez.add(entrez_id)
        available_samples.add(sample_id)

    z_scores: dict[tuple[int, str], float] = {}
    for entrez_id in sorted(available_entrez):
        values = [by_gene_sample.get((entrez_id, sample_id)) for sample_id in sample_ids]
        clean = [value for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
        if len(clean) < 2:
            continue
        average = sum(clean) / len(clean)
        sd = math.sqrt(sum((value - average) ** 2 for value in clean) / (len(clean) - 1)) or 1.0
        for sample_id, value in zip(sample_ids, values):
            if isinstance(value, (int, float)) and math.isfinite(value):
                z_scores[(entrez_id, sample_id)] = (value - average) / sd
    return z_scores, available_entrez, available_samples


def signature_score(signature_rows: Sequence[dict[str, str]], z_scores: dict[tuple[int, str], float], sample_id: str) -> Optional[float]:
    positive: list[float] = []
    negative: list[float] = []
    for row in signature_rows:
        entrez = row.get("entrez", "")
        if not valid_entrez(entrez):
            continue
        value = z_scores.get((int(entrez), sample_id))
        if value is None:
            continue
        try:
            coefficient = float(row.get("coefficient", ""))
        except ValueError:
            continue
        if coefficient > 0:
            positive.append(value * coefficient)
        else:
            negative.append(value * coefficient)
    if not positive and not negative:
        return None
    positive_mean = sum(positive) / len(positive) if positive else None
    negative_mean = sum(negative) / len(negative) if negative else None
    if positive_mean is None:
        return negative_mean
    if negative_mean is None:
        return positive_mean
    return (positive_mean + negative_mean) / 2.0


def run_signature_validation(official_rows: Sequence[dict[str, str]]) -> tuple[dict[str, object], list[dict[str, object]]]:
    signature_rows = load_signature_rows()
    signatures: dict[str, list[dict[str, str]]] = {subtype: [] for subtype in SUBTYPE_ORDER}
    for row in signature_rows:
        signature = row.get("signature", "")
        if signature in signatures:
            signatures[signature].append(row)

    records = fetch_signature_expression(signature_rows, official_rows)
    sample_ids = [row["sample_id"] for row in official_rows]
    z_scores, available_entrez, available_samples = build_z_scores(records, sample_ids)

    coverage_by_subtype: dict[str, dict[str, object]] = {}
    for subtype in SUBTYPE_ORDER:
        expected_entrez = {int(row["entrez"]) for row in signatures[subtype] if valid_entrez(row.get("entrez", ""))}
        observed_entrez = expected_entrez & available_entrez
        coverage_by_subtype[subtype] = {
            "signatureEntrezCount": len(expected_entrez),
            "availableEntrezCount": len(observed_entrez),
            "coverage": round(len(observed_entrez) / len(expected_entrez), 4) if expected_entrez else 0,
        }

    validation_rows: list[dict[str, object]] = []
    for row in official_rows:
        sample_id = row["sample_id"]
        scores = {subtype: signature_score(signatures[subtype], z_scores, sample_id) for subtype in SUBTYPE_ORDER}
        callable_subtypes = [subtype for subtype, score in scores.items() if score is not None]
        if callable_subtypes:
            local_subtype = max(callable_subtypes, key=lambda subtype: scores[subtype] if scores[subtype] is not None else float("-inf"))
            local_tnbctype = SUBTYPE_SHORT[local_subtype]
            local_refined = local_tnbctype
            if local_tnbctype in {"IM", "MSL"}:
                refined_candidates = [subtype for subtype in callable_subtypes if SUBTYPE_SHORT[subtype] not in {"IM", "MSL"}]
                refined_subtype = (
                    max(refined_candidates, key=lambda subtype: scores[subtype] if scores[subtype] is not None else float("-inf"))
                    if refined_candidates
                    else ""
                )
                local_refined = SUBTYPE_SHORT.get(refined_subtype, "")
            missing_reason = ""
        else:
            local_tnbctype = ""
            local_refined = ""
            missing_reason = "no_expression_scores_for_sample"
        output_row: dict[str, object] = {
            "sample_id": sample_id,
            "patient_id": row["patient_id"],
            "official_tnbctype": row.get("lehmann_tnbctype", ""),
            "official_refined_tnbctype": row.get("lehmann_refined_tnbctype", ""),
            "local_signature_tnbctype": local_tnbctype,
            "local_signature_refined_tnbctype": local_refined,
            "matches_official_tnbctype": str(bool(local_tnbctype) and local_tnbctype == row.get("lehmann_tnbctype", "")).lower()
            if local_tnbctype
            else "",
            "matches_official_refined_tnbctype": str(bool(local_refined) and local_refined == row.get("lehmann_refined_tnbctype", "")).lower()
            if local_refined
            else "",
            "assessable_from_cbioportal_signature_expression": str(bool(callable_subtypes)).lower(),
            "missing_reason": missing_reason,
        }
        for subtype in SUBTYPE_ORDER:
            output_row[f"score_{SUBTYPE_SHORT[subtype].lower()}"] = round_value(scores[subtype])
        validation_rows.append(output_row)

    assessable = [row for row in validation_rows if row["assessable_from_cbioportal_signature_expression"] == "true"]
    tnbctype_matches = sum(row["matches_official_tnbctype"] == "true" for row in assessable)
    refined_matches = sum(row["matches_official_refined_tnbctype"] == "true" for row in assessable)
    summary: dict[str, object] = {
        "generatedAt": iso_now(),
        "runMode": "non_dry_expression_classifier_validation",
        "status": "completed",
        "method": "Python port of the public BCTL Lehmann signature-score helper using cBioPortal PanCan Atlas RNA Seq V2 RSEM values.",
        "boundary": "This validates expression acquisition and signature scoring, but it is not the Vanderbilt TNBCtype centroid/permutation web-tool implementation.",
        "signatureSource": LEHMANN_SIGNATURE_SOURCE,
        "signatureCsv": LEHMANN_SIGNATURE_PROCESSED,
        "rawExpressionCache": LEHMANN_SIGNATURE_EXPRESSION_RAW,
        "officialTcgaTnbcSamples": len(official_rows),
        "assessableSamples": len(assessable),
        "missingExpressionSamples": [
            str(row["sample_id"]) for row in validation_rows if row["assessable_from_cbioportal_signature_expression"] != "true"
        ],
        "signatureRows": len(signature_rows),
        "signatureUniqueEntrezRequested": len({int(row["entrez"]) for row in signature_rows if valid_entrez(row.get("entrez", ""))}),
        "expressionRecordsFetched": len(records),
        "availableSignatureEntrez": len(available_entrez),
        "availableExpressionSamples": len(available_samples),
        "coverageBySubtype": coverage_by_subtype,
        "localTnbctypeMatches": tnbctype_matches,
        "localTnbctypeMatchRate": round(tnbctype_matches / len(assessable), 4) if assessable else 0,
        "localRefinedMatches": refined_matches,
        "localRefinedMatchRate": round(refined_matches / len(assessable), 4) if assessable else 0,
    }
    return summary, validation_rows


def is_negative(value: str) -> bool:
    return value.strip().lower() == "negative"


def receptor_status(row: dict[str, str]) -> str:
    values = [row.get("er_status_nature2012", ""), row.get("pr_status_nature2012", ""), row.get("her2_status_nature2012", "")]
    if all(is_negative(value) for value in values):
        return "xena_triple_negative"
    if any(value.strip().lower() in {"positive", "equivocal"} for value in values):
        return "not_tnbc_from_xena_receptor_fields"
    if any(is_negative(value) for value in values):
        return "incomplete_receptor_fields"
    return "no_receptor_fields_in_subset"


def evidence_status(panel_row: dict[str, str], rna_row: dict[str, str], official_call: Optional[dict[str, str]]) -> str:
    if official_call:
        return "confirmed_from_lehmann_tcga_s1"
    receptor = receptor_status(rna_row)
    if receptor == "not_tnbc_from_xena_receptor_fields":
        return "not_applicable_not_tnbc_from_available_fields"
    if receptor == "xena_triple_negative":
        return "needs_classifier_run_not_in_official_s1"
    subtype = panel_row.get("cbioportal_subtype", "")
    pam50 = rna_row.get("xena_pam50_call_rnaseq", "")
    if "Basal" in subtype or pam50 == "Basal":
        return "basal_context_but_not_official_lehmann_tnbc"
    return "no_call_not_in_official_lehmann_tcga_tnbc"


def next_action(status: str) -> str:
    if status == "confirmed_from_lehmann_tcga_s1":
        return "Use as TCGA confirmation value for subtype cross-checking."
    if status == "needs_classifier_run_not_in_official_s1":
        return "Acquire genome-wide normalized RNA expression and run the locked TNBCtype classifier; do not infer from marker context."
    if status == "basal_context_but_not_official_lehmann_tnbc":
        return "Treat as no-call for Lehmann subtype unless the sample is re-qualified as TNBC and run through TNBCtype."
    if status == "not_applicable_not_tnbc_from_available_fields":
        return "Do not compute Lehmann TNBC subtype for receptor-positive or equivocal samples."
    return "No official Lehmann TCGA TNBC value found; keep no-call."


def markdown_table(rows: Sequence[dict[str, str]], columns: Sequence[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def build_markdown(summary: dict[str, object], overlap_rows: Sequence[dict[str, str]], status_counts: Counter[str]) -> str:
    status_rows = [{"status": status, "count": str(count)} for status, count in sorted(status_counts.items())]
    classifier = summary.get("classifierValidation", {})
    classifier_summary = classifier if isinstance(classifier, dict) else {}
    classifier_block = ""
    if classifier_summary:
        classifier_block = f"""
## Non-Dry Expression Classifier Validation

- Run mode: `{classifier_summary.get("runMode", "unknown")}`
- Expression records fetched: {classifier_summary.get("expressionRecordsFetched", "unknown")}
- Assessable TCGA TNBC samples: {classifier_summary.get("assessableSamples", "unknown")} / {classifier_summary.get("officialTcgaTnbcSamples", "unknown")}
- Local TNBCtype match rate: {classifier_summary.get("localTnbctypeMatches", "unknown")} / {classifier_summary.get("assessableSamples", "unknown")} ({classifier_summary.get("localTnbctypeMatchRate", "unknown")})
- Local refined TNBCtype match rate: {classifier_summary.get("localRefinedMatches", "unknown")} / {classifier_summary.get("assessableSamples", "unknown")} ({classifier_summary.get("localRefinedMatchRate", "unknown")})

This confirms the expression-data acquisition and signature-scoring path works end to end. It does not replace the locked Vanderbilt TNBCtype centroid/permutation implementation, because the local signature-score helper is a related public method rather than the exact official classifier.
"""
    overlap_table = markdown_table(
        overlap_rows,
        [
            "sample_id",
            "lehmann_tnbctype",
            "lehmann_refined_tnbctype",
            "xena_er",
            "xena_pr",
            "xena_her2",
        ],
    )
    status_table = markdown_table(status_rows, ["status", "count"])
    return f"""# Lehmann TNBC Subtype Feasibility

## Bottom Line

The current 28-sample HRD reference panel can be cross-checked against the official Lehmann TCGA TNBC supplementary table, but it cannot be used to compute new Lehmann/TNBCtype calls from the current RNA marker lane. The panel has {summary["panelWithOfficialLehmannCount"]} official TCGA Lehmann calls and {summary["panelMissingOfficialLehmannCount"]} no-calls relative to the 2016 TCGA TNBC table.

For Diana's sample, Lehmann subtype computation belongs in the RNA/WTS lane. It needs genome-wide tumor expression, TNBC-only normalization or an equivalent locked classifier input, clinical ER/PR/HER2 confirmation, and a locked TNBCtype/TNBCtype-4 implementation or documented Vanderbilt web-tool run.

## Current TCGA Panel Cross-Check

{overlap_table}

## Evidence Status Counts

{status_table}

## Feasibility Notes

- Source table: `{LEHMANN_S1_URL}`.
- The current repo RNA context uses marker genes only; it is not TNBCtype.
- The Vanderbilt TNBCtype tool expects a genome-wide gene-expression CSV and recommends preprocessing/normalization on TNBC samples only.
- Missing panel rows should stay no-call for Lehmann subtype unless they are re-qualified as TNBC and run through a locked classifier.
{classifier_block}
"""


def build_signature_validation_markdown(summary: dict[str, object]) -> str:
    coverage = summary.get("coverageBySubtype", {})
    coverage_rows = []
    if isinstance(coverage, dict):
        for subtype, row in coverage.items():
            if isinstance(row, dict):
                coverage_rows.append(
                    {
                        "subtype": subtype,
                        "available": str(row.get("availableEntrezCount", "")),
                        "signature": str(row.get("signatureEntrezCount", "")),
                        "coverage": str(row.get("coverage", "")),
                    }
                )
    coverage_table = markdown_table(coverage_rows, ["subtype", "available", "signature", "coverage"]) if coverage_rows else ""
    missing = summary.get("missingExpressionSamples", [])
    missing_text = ", ".join(str(sample) for sample in missing) if isinstance(missing, list) and missing else "none"
    return f"""# Lehmann Signature TCGA Validation

## Bottom Line

The non-dry expression path completed. It fetched {summary.get("expressionRecordsFetched", "unknown")} cBioPortal expression records for the public Lehmann signature genes and produced subtype scores for {summary.get("assessableSamples", "unknown")} of {summary.get("officialTcgaTnbcSamples", "unknown")} official TCGA TNBC samples.

The local signature-score approximation matched {summary.get("localRefinedMatches", "unknown")} refined official calls out of {summary.get("assessableSamples", "unknown")} assessable samples. That confirms the expression fetch and scoring mechanics work, but the mismatch means this should remain a validation approximation until a locked Vanderbilt TNBCtype implementation or archived web-tool output is used for Diana.

## Signature Coverage

{coverage_table}

## Missing Expression Samples

{missing_text}

## Boundary

{summary.get("boundary", "")}
"""


def main() -> None:
    ensure_dir(path_from_root("data/raw/lehmann"))
    ensure_dir(path_from_root("data/processed/lehmann"))
    ensure_dir(path_from_root("results/evidence_tables"))

    xlsx_path = fetch_if_missing(LEHMANN_S1_URL, LEHMANN_S1_RAW)
    official_rows = parse_lehmann_s1(xlsx_path)
    official_by_patient = {row["patient_id"]: row for row in official_rows}

    panel = parse_csv(read_text(path_from_root("manifests/hrd_reference_panel.csv")))
    rna_rows = parse_csv(read_text(path_from_root("results/rna_subtype_context.csv")))
    rna_by_sample = {row["sample_id"]: row for row in rna_rows}

    panel_rows = []
    for panel_row in panel:
        sample_id = panel_row["sample_id"]
        patient_id = panel_row["patient_id"]
        rna_row = rna_by_sample.get(sample_id, {})
        official_call = official_by_patient.get(patient_id)
        status = evidence_status(panel_row, rna_row, official_call)
        row = {
            "sample_id": sample_id,
            "patient_id": patient_id,
            "panel_category": panel_row.get("panel_category", ""),
            "expected_hrd_label": panel_row.get("expected_hrd_label", ""),
            "cbioportal_subtype": panel_row.get("cbioportal_subtype", ""),
            "xena_er": rna_row.get("er_status_nature2012", ""),
            "xena_pr": rna_row.get("pr_status_nature2012", ""),
            "xena_her2": rna_row.get("her2_status_nature2012", ""),
            "xena_pam50": rna_row.get("xena_pam50_call_rnaseq", ""),
            "rna_marker_context": rna_row.get("inferred_context", ""),
            "official_lehmann_source": "PLOS One 2016 S1 Table" if official_call else "",
            "lehmann_tnbctype": official_call.get("lehmann_tnbctype", "") if official_call else "",
            "lehmann_refined_tnbctype": official_call.get("lehmann_refined_tnbctype", "") if official_call else "",
            "lehmann_im_corr": round_value(float(official_call["lehmann_im_corr"])) if official_call else "",
            "lehmann_bl1_corr": round_value(float(official_call["lehmann_bl1_corr"])) if official_call else "",
            "lehmann_msl_corr": round_value(float(official_call["lehmann_msl_corr"])) if official_call else "",
            "lehmann_m_corr": round_value(float(official_call["lehmann_m_corr"])) if official_call else "",
            "lehmann_bl2_corr": round_value(float(official_call["lehmann_bl2_corr"])) if official_call else "",
            "lehmann_lar_corr": round_value(float(official_call["lehmann_lar_corr"])) if official_call else "",
            "evidence_status": status,
            "next_action": next_action(status),
        }
        panel_rows.append(row)

    write_csv(path_from_root(LEHMANN_S1_PROCESSED), official_rows)
    write_csv(path_from_root(PANEL_OUTPUT), panel_rows)
    write_csv(path_from_root(EVIDENCE_OUTPUT), panel_rows)

    signature_summary, signature_rows = run_signature_validation(official_rows)
    write_csv(path_from_root(LEHMANN_SIGNATURE_VALIDATION_OUTPUT), signature_rows)
    write_csv(path_from_root(LEHMANN_SIGNATURE_VALIDATION_EVIDENCE), signature_rows)
    write_json(path_from_root(LEHMANN_SIGNATURE_VALIDATION_SUMMARY), signature_summary)
    write_text(path_from_root(LEHMANN_SIGNATURE_VALIDATION_MD), build_signature_validation_markdown(signature_summary))

    status_counts = Counter(row["evidence_status"] for row in panel_rows)
    overlap_rows = [row for row in panel_rows if row["evidence_status"] == "confirmed_from_lehmann_tcga_s1"]
    marker_genes = {
        row["gene"]
        for row in parse_csv(read_text(path_from_root("data/processed/cbioportal/expression_marker_genes.csv")))
        if row.get("gene")
    }
    summary: dict[str, object] = {
        "generatedAt": iso_now(),
        "source": {
            "name": "Lehmann et al. 2016 PLOS One S1 Table",
            "url": LEHMANN_S1_URL,
            "rawCache": LEHMANN_S1_RAW,
        },
        "classifierValidation": signature_summary,
        "officialTcgaTnbcCount": len(official_rows),
        "panelSampleCount": len(panel_rows),
        "panelWithOfficialLehmannCount": len(overlap_rows),
        "panelMissingOfficialLehmannCount": len(panel_rows) - len(overlap_rows),
        "statusCounts": dict(sorted(status_counts.items())),
        "currentRnaMarkerGeneCount": len(marker_genes),
        "currentRnaBoundary": "Current RNA context is a marker-module lane, not a genome-wide TNBCtype classifier input.",
        "dianaRequirements": [
            "Clinical ER/PR/HER2 confirmation that the tumor is TNBC.",
            "Genome-wide RNA expression from tumor RNA-seq/WTS or a validated expression assay.",
            "Normalization on TNBC samples only, or an equivalent locked TNBCtype input contract.",
            "Locked TNBCtype/TNBCtype-4 implementation or archived Vanderbilt web-tool run with coefficients and p-values.",
            "TCGA positive controls from the official S1 table for regression testing.",
        ],
    }
    write_json(path_from_root(SUMMARY_JSON), summary)
    write_text(path_from_root(SUMMARY_MD), build_markdown(summary, overlap_rows, status_counts))
    print(
        f"Built Lehmann TNBC outputs for {len(panel_rows)} panel samples; "
        f"{len(overlap_rows)} official calls; {signature_summary['assessableSamples']} expression-scored TCGA TNBC controls."
    )


if __name__ == "__main__":
    main()
