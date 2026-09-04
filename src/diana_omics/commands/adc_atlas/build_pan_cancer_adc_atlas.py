from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, quantile, read_text, round_value, write_csv, write_json, write_text

ATLAS_VERSION = "v1"
XENA_HUB = "https://toil.xenahubs.net"
XENA_DATASET = "TcgaTargetGtex_rsem_gene_tpm"
XENA_PHENOTYPE_URL = f"{XENA_HUB}/download/TcgaTargetGTEX_phenotype.txt.gz"
HPA_NORMAL_IHC_URL = "https://www.proteinatlas.org/download/tsv/normal_ihc_data.tsv.zip"
HPA_CANCER_IHC_URL = "https://www.proteinatlas.org/download/tsv/cancer_data.tsv.zip"
HPA_CPTAC_URL = "https://www.proteinatlas.org/download/tsv/cancer_cptac.tsv.zip"
TARGETS_MANIFEST = "manifests/adc_atlas_targets_v1.csv"
OUTPUT_ROOT = "results/pan_cancer_adc_atlas/v1"
VISUALIZATION_PATH = "docs/rosalind/visualizations/pan-cancer-adc-atlas-v1.html"
PATIENT_BRIDGE_POINTER = "manifests/adc_atlas_patient_bridge_current.json"


def xena_log_tpm_to_tpm(value: Any) -> float | None:
    """Convert UCSC Toil log2(TPM + 0.001) values to non-negative TPM."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, (2**number) - 0.001)


def summarize_values(values: Iterable[float]) -> dict[str, float | int]:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return {
            "sample_count": 0,
            "median_tpm": 0.0,
            "q1_tpm": 0.0,
            "q3_tpm": 0.0,
            "p90_tpm": 0.0,
            "p95_tpm": 0.0,
            "fraction_ge_1_tpm": 0.0,
            "fraction_ge_10_tpm": 0.0,
        }

    def rounded_quantile(q: float) -> float:
        value = quantile(clean, q)
        return round(value if value is not None else 0.0, 4)

    return {
        "sample_count": len(clean),
        "median_tpm": rounded_quantile(0.5),
        "q1_tpm": rounded_quantile(0.25),
        "q3_tpm": rounded_quantile(0.75),
        "p90_tpm": rounded_quantile(0.9),
        "p95_tpm": rounded_quantile(0.95),
        "fraction_ge_1_tpm": round(sum(value >= 1 for value in clean) / len(clean), 4),
        "fraction_ge_10_tpm": round(sum(value >= 10 for value in clean) / len(clean), 4),
    }


def _fetch_bytes(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "diana-omics-adc-atlas/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return bytes(response.read())


def _post_xena(query: str, timeout: int = 180) -> Any:
    request = urllib.request.Request(
        f"{XENA_HUB}/data/",
        data=query.encode("utf-8"),
        headers={"Content-Type": "text/plain", "User-Agent": "diana-omics-adc-atlas/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _edn_array(values: Sequence[str]) -> str:
    return "[" + " ".join(json.dumps(value) for value in values) + "]"


def fetch_xena_samples() -> list[str]:
    query = f"""
(map :value
  (query
    {{:select [:value]
     :from [:dataset]
     :join [:field [:= :dataset.id :dataset_id]
            :code [:= :field.id :field_id]]
     :where [:and
             [:= :dataset.name {json.dumps(XENA_DATASET)}]
             [:= :field.name \"sampleID\"] ]}}))
"""
    samples = _post_xena(query)
    if not isinstance(samples, list) or not samples:
        raise RuntimeError("UCSC Xena returned no samples for the harmonized dataset")
    return [str(sample) for sample in samples]


def fetch_xena_gene_scores(samples: Sequence[str], genes: Sequence[str]) -> dict[str, list[Any]]:
    query = f"""
(let [probemap (:probemap (car (query {{:select [:probemap]
                                      :from [:dataset]
                                      :where [:= :name {json.dumps(XENA_DATASET)}]}})))
      probes-for-gene (fn [gene]
        ((xena-query {{:select [\"name\"]
                      :from [probemap]
                      :where [:in :any \"genes\" [gene]]}}) \"name\"))
      avg (fn [scores] (mean scores 0))
      scores-for-gene (fn [gene]
        (let [probes (probes-for-gene gene)
              scores (fetch [{{:table {json.dumps(XENA_DATASET)}
                               :samples {_edn_array(list(samples))}
                               :columns probes}}])]
          {{:gene gene
            :scores (if (car probes) (avg scores) [[]])}}))]
  (map scores-for-gene {_edn_array(list(genes))}))
"""
    response = _post_xena(query)
    if not isinstance(response, list):
        raise RuntimeError("UCSC Xena returned an invalid gene-score response")
    result: dict[str, list[Any]] = {}
    for item in response:
        gene = str(item.get("gene", ""))
        scores = item.get("scores", [])
        vector = scores[0] if isinstance(scores, list) and len(scores) == 1 else []
        if len(vector) != len(samples):
            raise RuntimeError(f"UCSC Xena returned {len(vector)} scores for {gene}; expected {len(samples)}")
        result[gene] = vector
    missing = sorted(set(genes) - set(result))
    if missing:
        raise RuntimeError(f"UCSC Xena omitted requested genes: {', '.join(missing)}")
    return result


def _parse_gzip_tsv(raw: bytes) -> list[dict[str, str]]:
    # The frozen Xena phenotype table contains legacy single-byte characters
    # (for example 0xCA in a TARGET tissue label), so Latin-1 is lossless here.
    text = gzip.decompress(raw).decode("latin-1")
    return [dict(row) for row in csv.DictReader(io.StringIO(text), delimiter="\t")]


def _parse_zipped_tsv(raw: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".tsv")]
        if len(names) != 1:
            raise RuntimeError(f"Expected one TSV in archive, found {len(names)}")
        text = archive.read(names[0]).decode("utf-8")
    return [dict(row) for row in csv.DictReader(io.StringIO(text), delimiter="\t")]


def build_expression_summaries(
    targets: Sequence[Mapping[str, str]],
    samples: Sequence[str],
    phenotypes: Sequence[Mapping[str, str]],
    gene_scores: Mapping[str, Sequence[Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    phenotype_by_sample = {row.get("sample", ""): row for row in phenotypes if row.get("sample")}
    cancer_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    normal_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    matched = 0
    excluded_target = 0
    excluded_other = 0
    missing_scores = 0

    for index, sample in enumerate(samples):
        phenotype = phenotype_by_sample.get(sample)
        if not phenotype:
            continue
        study = phenotype.get("_study", "")
        sample_type = phenotype.get("_sample_type", "")
        if study == "TCGA" and sample_type == "Primary Tumor":
            cohort = phenotype.get("detailed_category") or phenotype.get("primary disease or tissue") or "Unspecified TCGA"
            lane = "cancer"
        elif study == "GTEX" and sample_type == "Normal Tissue":
            cohort = phenotype.get("_primary_site") or phenotype.get("primary disease or tissue") or "Unspecified GTEx"
            lane = "normal"
        else:
            if study == "TARGET":
                excluded_target += 1
            else:
                excluded_other += 1
            continue
        matched += 1
        for target in targets:
            score = gene_scores[target["query_gene"]][index]
            value = xena_log_tpm_to_tpm(score)
            if value is None:
                missing_scores += 1
                continue
            key = (target["target_id"], cohort)
            (cancer_groups if lane == "cancer" else normal_groups)[key].append(value)

    target_by_id = {target["target_id"]: target for target in targets}
    cancer_rows = []
    for (target_id, cohort), values in sorted(cancer_groups.items()):
        target = target_by_id[target_id]
        cancer_rows.append(
            {
                "target_id": target_id,
                "gene_symbol": target["gene_symbol"],
                "display_name": target["display_name"],
                "cancer": cohort,
                **summarize_values(values),
            }
        )
    normal_rows = []
    for (target_id, tissue), values in sorted(normal_groups.items()):
        target = target_by_id[target_id]
        normal_rows.append(
            {
                "target_id": target_id,
                "gene_symbol": target["gene_symbol"],
                "display_name": target["display_name"],
                "normal_tissue": tissue,
                **summarize_values(values),
            }
        )
    return (
        cancer_rows,
        normal_rows,
        {
            "matrix_samples": len(samples),
            "phenotype_rows": len(phenotypes),
            "analysis_samples": matched,
            "tcga_primary_tumors": sum(int(row["sample_count"]) for row in cancer_rows if row["target_id"] == targets[0]["target_id"]),
            "gtex_normal_tissues": sum(int(row["sample_count"]) for row in normal_rows if row["target_id"] == targets[0]["target_id"]),
            "target_samples_excluded": excluded_target,
            "other_samples_excluded": excluded_other,
            "missing_gene_values": missing_scores,
        },
    )


def build_hpa_summaries(
    targets: Sequence[Mapping[str, str]],
    cancer_rows: Sequence[Mapping[str, str]],
    normal_rows: Sequence[Mapping[str, str]],
    cptac_rows: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    symbols = {target["gene_symbol"] for target in targets}
    id_by_symbol = {target["gene_symbol"]: target["target_id"] for target in targets}
    cancer = [
        {
            "target_id": id_by_symbol[row["Gene name"]],
            "gene_symbol": row["Gene name"],
            "cancer": row["Cancer"],
            "high": int(row.get("High") or 0),
            "medium": int(row.get("Medium") or 0),
            "low": int(row.get("Low") or 0),
            "not_detected": int(row.get("Not detected") or 0),
            "evidence_status": "public_reference_ihc",
        }
        for row in cancer_rows
        if row.get("Gene name") in symbols
    ]
    level_rank = {"Not detected": 0, "Low": 1, "Medium": 2, "High": 3}
    grouped: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in normal_rows:
        if row.get("Gene name") in symbols:
            grouped[(row["Gene name"], row["Tissue"])].append(row)
    normal = []
    for (symbol, tissue), rows in sorted(grouped.items()):
        levels = [row.get("Level", "Not detected") for row in rows]
        max_level = max(levels, key=lambda level: level_rank.get(level, -1))
        normal.append(
            {
                "target_id": id_by_symbol[symbol],
                "gene_symbol": symbol,
                "tissue": tissue,
                "cell_types_assessed": len(rows),
                "max_level": max_level,
                "high_cell_types": sum(level == "High" for level in levels),
                "medium_cell_types": sum(level == "Medium" for level in levels),
                "low_cell_types": sum(level == "Low" for level in levels),
                "not_detected_cell_types": sum(level == "Not detected" for level in levels),
                "evidence_status": "public_reference_ihc",
            }
        )
    cptac = [
        {
            "target_id": id_by_symbol[row["Gene name"]],
            "gene_symbol": row["Gene name"],
            "cancer": row["Cancer"],
            "adjusted_p_value": row.get("p-value adjusted", ""),
            "log2_fold_change": row.get("logFC", ""),
            "evidence_status": "public_reference_proteomics",
        }
        for row in cptac_rows
        if row.get("Gene name") in symbols
    ]
    return cancer, normal, cptac


def build_target_and_candidate_summaries(
    targets: Sequence[Mapping[str, str]],
    cancer_expression: Sequence[Mapping[str, Any]],
    normal_expression: Sequence[Mapping[str, Any]],
    cancer_ihc: Sequence[Mapping[str, Any]],
    normal_ihc: Sequence[Mapping[str, Any]],
    cptac: Sequence[Mapping[str, Any]],
    patient_comparison: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_rows = []
    candidate_rows = []
    patient_by_target = {str(row["target_id"]): row for row in patient_comparison or []}
    for target in targets:
        target_id = target["target_id"]
        cancers = [row for row in cancer_expression if row["target_id"] == target_id]
        normals = [row for row in normal_expression if row["target_id"] == target_id]
        top_cancer = max(cancers, key=lambda row: float(row["median_tpm"])) if cancers else None
        top_normal = max(normals, key=lambda row: float(row["median_tpm"])) if normals else None
        cancer_median = float(top_cancer["median_tpm"]) if top_cancer else 0.0
        normal_median = float(top_normal["median_tpm"]) if top_normal else 0.0
        ratio = cancer_median / normal_median if normal_median > 0 else None
        has_cancer_ihc = any(row["target_id"] == target_id for row in cancer_ihc)
        has_normal_ihc = any(row["target_id"] == target_id for row in normal_ihc)
        has_cptac = any(row["target_id"] == target_id for row in cptac)
        patient = patient_by_target.get(target_id)
        patient_status = str(patient["comparison_status"]) if patient else "blocked_not_harmonized"
        target_rows.append(
            {
                **target,
                "top_cancer": top_cancer["cancer"] if top_cancer else "",
                "top_cancer_median_tpm": round(cancer_median, 4),
                "top_normal_tissue": top_normal["normal_tissue"] if top_normal else "",
                "max_normal_median_tpm": round(normal_median, 4),
                "top_cancer_to_max_normal_ratio": round_value(ratio, 4),
                "cancers_profiled": len(cancers),
                "normal_tissues_profiled": len(normals),
                "rna_reference_status": "public_processed_evidence" if cancers and normals else "no_call",
                "protein_reference_status": "public_reference_evidence"
                if has_cancer_ihc or has_normal_ihc or has_cptac
                else "not_available",
                "patient_comparison_status": patient_status,
                "patient_tpm": float(patient["patient_tpm"]) if patient else None,
                "patient_within_sample_protein_coding_percentile": (
                    float(patient["patient_protein_coding_percentile"])
                    if patient and patient.get("patient_protein_coding_percentile") not in (None, "")
                    else None
                ),
                "tcga_brca_median_tpm": float(patient["tcga_brca_median_tpm"]) if patient else None,
                "descriptive_patient_to_tcga_brca_median_ratio": (
                    float(patient["descriptive_patient_to_cohort_median_ratio"])
                    if patient and patient.get("descriptive_patient_to_cohort_median_ratio") not in (None, "")
                    else None
                ),
                "tcga_brca_quantile_band": str(patient["cohort_quantile_band"]) if patient else "not_available",
                "overall_status": "partial_evidence",
            }
        )
        candidate_rows.append(
            {
                "target_id": target_id,
                "gene_symbol": target["gene_symbol"],
                "display_name": target["display_name"],
                "target_or_epitope": target["epitope_or_isoform"],
                "payload_context": target["payload_context"],
                "public_tumor_rna_status": "public_processed_evidence" if cancers else "no_call",
                "public_normal_rna_status": "public_processed_evidence" if normals else "no_call",
                "hpa_cancer_ihc_status": "reference_available" if has_cancer_ihc else "not_available",
                "hpa_normal_ihc_status": "reference_available" if has_normal_ihc else "not_available",
                "cptac_proteomics_status": "reference_available" if has_cptac else "not_available",
                "patient_comparison_status": patient_status,
                "surface_localization_status": "no_call",
                "internalization_status": "no_call",
                "payload_sensitivity_status": "no_call",
                "overall_status": "partial_evidence",
                "next_gate": target["protein_gate"],
                "interpretation_boundary": target["caveat"],
            }
        )
    return target_rows, candidate_rows


def build_orthogonal_followup(
    target_rows: Sequence[Mapping[str, Any]], *, start: int = 0, limit: int = 8
) -> list[dict[str, Any]]:
    bridged = [row for row in target_rows if row.get("patient_comparison_status") == "directionally_comparable"]
    bridged.sort(key=lambda row: (-float(row["patient_tpm"]), str(row["display_name"])))
    return [
        {
            "review_order": index,
            "target_id": row["target_id"],
            "gene_symbol": row["gene_symbol"],
            "display_name": row["display_name"],
            "patient_tpm": row["patient_tpm"],
            "patient_within_sample_protein_coding_percentile": row[
                "patient_within_sample_protein_coding_percentile"
            ],
            "tcga_brca_quantile_band": row["tcga_brca_quantile_band"],
            "descriptive_patient_to_tcga_brca_median_ratio": row[
                "descriptive_patient_to_tcga_brca_median_ratio"
            ],
            "primary_protein_gate": row["protein_gate"],
            "supporting_route": "Total-protein review can triage the specimen; target-specific localization remains required.",
            "compartment_or_epitope_caveat": row["caveat"],
            "evidence_status": "partial_evidence",
            "prioritization_basis": f"Patient TPM rank {index} within the frozen 23-target RNA panel.",
            "interpretation_boundary": "RNA review order only; not a therapeutic ranking, eligibility call, or response prediction.",
        }
        for index, row in enumerate(bridged[start : start + limit], start=start + 1)
    ]


def _source_record(url: str, raw: bytes, label: str, version: str) -> dict[str, Any]:
    return {"label": label, "url": url, "version": version, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bridge_artifact(pointer: Mapping[str, Any], name: str) -> Path:
    record = pointer.get(name)
    if not isinstance(record, dict) or not record.get("path") or not record.get("sha256"):
        raise RuntimeError(f"Patient bridge pointer is missing {name} path or sha256")
    path = Path(str(record["path"]))
    resolved = path if path.is_absolute() else path_from_root(path.as_posix())
    if not resolved.is_file():
        raise RuntimeError(f"Patient bridge artifact is missing: {resolved}")
    observed = _sha256_file(resolved)
    if observed != record["sha256"]:
        raise RuntimeError(f"Patient bridge artifact hash mismatch: {resolved}")
    return resolved


def load_patient_bridge() -> dict[str, Any] | None:
    pointer_path = Path(os.environ.get("ADC_ATLAS_PATIENT_BRIDGE", str(path_from_root(PATIENT_BRIDGE_POINTER))))
    if not pointer_path.exists():
        return None
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    comparison_path = _bridge_artifact(pointer, "comparison_table")
    qa_path = _bridge_artifact(pointer, "qa_summary")
    run_manifest_path = _bridge_artifact(pointer, "run_manifest")
    comparisons = parse_csv(comparison_path.read_text(encoding="utf-8"))
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    if not str(qa.get("status", "")).startswith("passed_for_directional_comparison"):
        raise RuntimeError("Patient bridge QA did not pass for directional comparison")
    if run_manifest.get("status") != "completed_research_analysis":
        raise RuntimeError("Patient bridge run is not a completed research analysis")
    required = {
        "target_id",
        "patient_tpm",
        "patient_protein_coding_percentile",
        "tcga_brca_median_tpm",
        "descriptive_patient_to_cohort_median_ratio",
        "cohort_quantile_band",
        "comparison_status",
    }
    if not comparisons or any(not required.issubset(row) for row in comparisons):
        raise RuntimeError("Patient bridge comparison table is empty or incomplete")
    if len({row["target_id"] for row in comparisons}) != len(comparisons):
        raise RuntimeError("Patient bridge target ids must be unique")
    if any(row["comparison_status"] != "directionally_comparable" for row in comparisons):
        raise RuntimeError("Patient bridge includes a target that is not directionally comparable")
    return {
        "pointer": pointer,
        "pointer_path": pointer_path,
        "comparisons": comparisons,
        "qa": qa,
        "run_manifest": run_manifest,
    }


def _render_html(payload: Mapping[str, Any]) -> str:
    embedded = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    run_id = str(payload.get("patient_bridge", {}).get("run_id") or "")
    result_path = str(
        payload.get("patient_bridge", {}).get("public_result_path") or (f"results/workbench/{run_id}" if run_id else "results/workbench")
    )
    patient_run_url = (
        f"https://github.com/jasonLaster/oncoomics/tree/main/{quote(result_path, safe='/')}"
    )
    template = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>Pan-cancer ADC Atlas v1</title>
  <style>
    :root{--ink:#172225;--muted:#667477;--paper:#f4f1ea;--card:#fffdf8;--line:#d9d5ca;--accent:#005f65;--gold:#d59b37;--bad:#a34336;--radius:18px}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.shell{max-width:1540px;margin:auto;padding:28px}.hero{background:linear-gradient(135deg,#083f46,#0a6a6d 64%,#ba7d25);color:white;border-radius:24px;padding:38px;box-shadow:0 16px 40px #073e4524}.eyebrow{text-transform:uppercase;letter-spacing:.13em;font-weight:750;font-size:.74rem;opacity:.8}.hero h1{font-family:Georgia,serif;font-size:clamp(2.3rem,5vw,5.2rem);line-height:.96;margin:.35rem 0 1rem;max-width:900px}.hero p{max-width:780px;font-size:1.05rem;line-height:1.6;margin:0}.hero-meta{display:flex;flex-wrap:wrap;gap:9px;margin-top:22px}.pill{border:1px solid #ffffff55;background:#ffffff13;border-radius:999px;padding:8px 12px;font-size:.82rem}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.stat,.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 8px 24px #2534320b}.stat{padding:18px}.stat strong{display:block;font-size:1.8rem;font-family:Georgia,serif}.stat span{color:var(--muted);font-size:.82rem}.layout{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(310px,.7fr);gap:18px;align-items:start}.card{padding:20px;min-width:0}.card h2,.card h3{font-family:Georgia,serif;margin:.1rem 0 .7rem}.muted,.note{color:var(--muted);line-height:1.5}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.toolbar input,.toolbar select{font:inherit;border:1px solid var(--line);border-radius:10px;background:white;padding:10px 12px}.toolbar input{min-width:230px;flex:1}.heatwrap{overflow:auto;max-width:100%;border:1px solid var(--line);border-radius:13px;max-height:760px;background:white}.heat{border-collapse:separate;border-spacing:2px;width:max-content;min-width:100%}.heat th{position:sticky;top:0;z-index:2;background:#f7f5ee;padding:7px;font-size:.68rem;vertical-align:bottom;height:126px}.heat th span{display:block;writing-mode:vertical-rl;transform:rotate(180deg);margin:auto}.heat td{width:24px;height:25px;min-width:24px;text-align:center;border-radius:4px;font-size:0;cursor:pointer}.heat td:hover,.heat td:focus{outline:3px solid var(--gold);position:relative;z-index:3}.heat .rowlabel{position:sticky;left:0;z-index:1;min-width:150px;width:150px;background:#fff;padding:7px 9px;font-size:.78rem;text-align:left;font-weight:650;cursor:pointer}.legend{display:flex;align-items:center;gap:8px;font-size:.75rem;color:var(--muted);margin:10px 0}.gradient{width:150px;height:10px;border-radius:99px;background:linear-gradient(90deg,#eef2eb,#8fc0af,#0f6b72,#7f3153)}.detail{position:sticky;top:18px}.status{display:inline-block;border-radius:999px;padding:6px 10px;background:#f6e7c9;color:#6e4a0e;font-weight:750;font-size:.75rem}.kv{display:grid;grid-template-columns:1fr auto;gap:7px 14px;border-top:1px solid var(--line);padding-top:12px;margin-top:12px;font-size:.84rem}.kv dt{color:var(--muted)}.kv dd{margin:0;text-align:right;font-weight:650}.bars{display:grid;gap:7px;margin-top:13px}.barrow{display:grid;grid-template-columns:minmax(100px,1.2fr) 2fr 60px;gap:8px;align-items:center;font-size:.76rem}.track{height:9px;background:#ece9df;border-radius:99px;overflow:hidden}.fill{height:100%;background:var(--accent);border-radius:99px}.gates{display:grid;gap:8px;margin-top:14px}.gate{display:grid;grid-template-columns:12px 1fr;gap:9px;align-items:start;font-size:.8rem}.dot{width:10px;height:10px;border-radius:50%;margin-top:4px;background:#c6c1b5}.dot.have{background:var(--accent)}.dot.block{background:var(--bad)}.callout{border-left:4px solid var(--gold);padding:11px 13px;background:#faf0dc;border-radius:0 10px 10px 0;font-size:.84rem;line-height:1.5}.method{margin-top:18px}.method-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.method-grid article{padding:14px;border:1px solid var(--line);border-radius:12px;background:#fff}.method-grid h3{font-size:1rem}.method-grid p{font-size:.83rem;margin:0;color:var(--muted);line-height:1.5}.queue-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.queue-tabs button{font:inherit;font-size:.82rem;font-weight:700;min-height:44px;padding:8px 13px;border:1px solid #b7c9c7;border-radius:999px;background:#f3faf8;color:#005f65;cursor:pointer}.queue-tabs button:hover,.queue-tabs button:focus-visible{border-color:var(--gold);outline:3px solid #d59b3750;outline-offset:2px}.queue-tabs button.active{background:var(--accent);border-color:var(--accent);color:white}.queue-label{margin:0 0 9px;color:var(--muted);font-size:.78rem;font-weight:700}.queuewrap{overflow-x:auto;max-width:100%;border:1px solid var(--line);border-radius:12px;background:white}.queue-table{border-collapse:collapse;width:100%;min-width:720px;font-size:.82rem}.queue-table th,.queue-table td{padding:11px 12px;border-bottom:1px solid #ece8df;text-align:left;vertical-align:top}.queue-table th{background:#f7f5ee;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em}.queue-table tbody tr:last-child td{border-bottom:0}.queue-table td:nth-child(2),.queue-table td:nth-child(3){white-space:nowrap}.resource-links{display:flex;flex-wrap:wrap;gap:9px;margin-top:14px}.resource-links a{display:inline-flex;align-items:center;min-height:42px;padding:9px 12px;border:1px solid #b7c9c7;border-radius:10px;background:#f3faf8;color:#005f65;font-size:.82rem;font-weight:700;text-decoration:none}.resource-links a:hover,.resource-links a:focus-visible{border-color:var(--gold);outline:3px solid #d59b3750;outline-offset:2px}footer{padding:24px 4px;color:var(--muted);font-size:.76rem;line-height:1.5}a{color:#006a72}.empty{padding:32px;color:var(--muted)}
    .kv{grid-template-columns:minmax(0,1fr) minmax(0,1.15fr)}.kv dd{overflow-wrap:anywhere}.legend{flex-wrap:wrap}.resource-links a{min-height:44px}.heat thead .rowlabel{z-index:4;background:#f7f5ee}
    @media(max-width:900px){.shell{padding:14px}.hero{padding:26px 20px}.stats{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}.detail{position:static}.method-grid{grid-template-columns:1fr}.heatwrap{max-height:620px}.heat .rowlabel{min-width:125px;width:125px}.heat td{width:38px;min-width:38px;height:40px}.hero h1{font-size:2.55rem}}
    @media(max-width:480px){.stats{grid-template-columns:1fr 1fr}.stat{padding:13px}.stat strong{font-size:1.4rem}.toolbar{display:grid}.toolbar input{min-width:0;width:100%}.shell{padding:8px}.hero,.card{border-radius:14px}}
  </style>
</head>
<body><main class="shell">
  <section class="hero"><div class="eyebrow">Public reference • evidence-gated • version 1</div><h1>Pan-cancer ADC Atlas</h1><p>A target-first view of harmonized tumor RNA, normal-tissue RNA, public protein context, and a directional Diana RNA bridge. This is a hypothesis-ranking tool—not an exact patient percentile, ADC eligibility test, or treatment recommendation.</p><div class="hero-meta"><span class="pill">TCGA primary tumors</span><span class="pill">GTEx normal tissues</span><span class="pill">HPA IHC + CPTAC</span><span class="pill" id="patient-pill">Diana bridge pending</span><span class="pill">All candidates: partial evidence</span></div></section>
  <section class="stats" id="stats"></section>
  <section class="layout"><article class="card"><h2>Target × cancer RNA landscape</h2><p class="muted">Median TPM from the UCSC Toil harmonized recompute. Select a cell or target to inspect distributions and orthogonal evidence.</p><div class="toolbar"><input id="search" type="search" aria-label="Search ADC targets" placeholder="Find TROP-2, HER2, CLDN18…"><select id="tier" aria-label="Filter by target tier"><option value="all">All tiers</option><option value="anchor">Anchor</option><option value="expansion">Expansion</option><option value="lineage">Lineage</option><option value="discovery">Discovery</option></select></div><div class="legend"><span>lower</span><span class="gradient"></span><span>higher median TPM</span><span>• color uses log₂(TPM+1)</span></div><div class="heatwrap" id="heat"></div></article><aside class="card detail" id="detail" aria-live="polite"></aside></section>
  <section class="card method"><h2>Diana RNA-to-protein follow-up queue</h2><p class="muted">Review the 23 measured targets in RNA-ranked sets, paired with each target-specific orthogonal gate. The current second set covers ranks 9–16. This orders research follow-up; it is not a therapeutic ranking or evidence of accessible membrane antigen.</p><div class="queue-tabs" role="group" aria-label="Select RNA follow-up set"><button type="button" data-queue-page="0">First 8</button><button type="button" data-queue-page="1">Next 8</button><button type="button" data-queue-page="2">Remaining 7</button></div><div id="patient-queue"></div></section>
  <section class="card method"><h2>How to read v1</h2><div class="method-grid"><article><h3>1. RNA screen</h3><p>TCGA tumors and GTEx normals share one Toil/RSEM pipeline. Diana uses Salmon with the same GENCODE v23 feature model and TPM scale; its BRCA quartile band is directional because quantifier, library, specimen composition, and batch differ.</p></article><article><h3>2. Protein context</h3><p>HPA cancer and normal IHC plus CPTAC differential protein rows are orthogonal public context. They do not prove accessible membrane antigen in a specific specimen.</p></article><article><h3>3. ADC gates</h3><p>Surface localization, viable-cell membrane staining, heterogeneity, internalization, payload sensitivity, and safety remain unmeasured. No target in v1 is called ready.</p></article></div></section>
  <section class="card method"><h2>Reproducibility</h2><p class="muted">The public repository contains the target manifest, builder, frozen aggregate tables, QA records, Workbench wrapper, and bounded patient review bundle. Raw human sequencing data and credentials remain in approved private storage.</p><div class="resource-links"><a href="https://github.com/jasonLaster/oncoomics/tree/main/results/pan_cancer_adc_atlas/v1">Atlas result folder</a><a href="__PATIENT_RUN_URL__">Patient-bridge Workbench run</a><a href="https://github.com/jasonLaster/oncoomics/tree/main/docs/rosalind">Methods and interpretation</a><a href="https://github.com/jasonLaster/oncoomics/blob/main/scripts/modal/modal_s3_adc_atlas_patient_bridge.py">Modal/S3 runner</a></div></section>
  <footer>Sources: UCSC Xena Toil RNA-seq recompute and Human Protein Atlas v25.1 downloads. TARGET and non-primary TCGA samples are excluded. Generated <span id="generated"></span>. Source hashes and exact counts are in <code>source_manifest.json</code>.</footer>
</main><script id="atlas-data" type="application/json">__ATLAS_DATA__</script><script>
const D=JSON.parse(document.getElementById('atlas-data').textContent);let selected=D.targets[0]?.target_id;let selectedCancer=null;let queuePage=1;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const fmt=n=>Number(n).toLocaleString(undefined,{maximumFractionDigits:2});
const color=v=>{const x=Math.min(1,Math.log2(Number(v)+1)/8);const stops=[[238,242,235],[143,192,175],[15,107,114],[127,49,83]];const p=x*(stops.length-1),i=Math.min(stops.length-2,Math.floor(p)),t=p-i;return `rgb(${stops[i].map((a,j)=>Math.round(a+(stops[i+1][j]-a)*t)).join(',')})`};
function stats(){const s=D.summary;document.getElementById('stats').innerHTML=[[s.target_count,'ADC targets'],[s.cancer_count,'cancer cohorts'],[s.tcga_primary_tumors.toLocaleString(),'primary tumors'],[s.patient_bridge_target_count||0,'Diana targets bridged']].map(x=>`<article class="stat"><strong>${x[0]}</strong><span>${x[1]}</span></article>`).join('');document.getElementById('patient-pill').textContent=s.patient_bridge_target_count?`${D.patient_bridge.sample_label} directional RNA bridge`:'Diana bridge unavailable'}
function queue(){const all=D.targets.filter(t=>t.patient_comparison_status==='directionally_comparable').sort((a,b)=>b.patient_tpm-a.patient_tpm),start=queuePage*8,rows=all.slice(start,start+8);document.querySelectorAll('[data-queue-page]').forEach(button=>{const active=Number(button.dataset.queuePage)===queuePage;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active))});document.getElementById('patient-queue').innerHTML=rows.length?`<p class="queue-label">RNA ranks ${start+1}–${start+rows.length} of ${all.length}</p><div class="queuewrap"><table class="queue-table"><thead><tr><th>Rank</th><th>Target</th><th>Diana TPM</th><th>TCGA-BRCA band</th><th>Required next protein gate</th></tr></thead><tbody>${rows.map((t,i)=>`<tr><td>${start+i+1}</td><td><strong>${esc(t.display_name)}</strong><br><span class="muted">${esc(t.gene_symbol)}</span></td><td>${fmt(t.patient_tpm)}</td><td>${esc(t.tcga_brca_quantile_band.replaceAll('_',' '))}</td><td>${esc(t.protein_gate)}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">A QA-passed Diana patient bridge is required before this queue can be generated.</div>'}
function render(){const q=document.getElementById('search').value.toLowerCase(),tier=document.getElementById('tier').value;const targets=D.targets.filter(t=>(tier==='all'||t.tier===tier)&&(`${t.display_name} ${t.gene_symbol}`.toLowerCase().includes(q)));const matrix=new Map(D.cancer_expression.map(r=>[`${r.target_id}|${r.cancer}`,r]));if(targets.length&&!targets.some(t=>t.target_id===selected))selected=targets[0].target_id;let html='<table class="heat"><thead><tr><th class="rowlabel">Target</th>'+D.cancers.map(c=>`<th title="${esc(c)}"><span>${esc(c)}</span></th>`).join('')+'</tr></thead><tbody>';for(const t of targets){html+=`<tr><th tabindex="0" class="rowlabel" data-target="${t.target_id}" aria-label="Show ${esc(t.display_name)} details">${esc(t.display_name)} <small>${esc(t.gene_symbol)}</small></th>`;for(const c of D.cancers){const r=matrix.get(`${t.target_id}|${c}`),v=r?Number(r.median_tpm):0,label=`${t.display_name} • ${c} • median ${fmt(v)} TPM`;html+=`<td tabindex="0" data-target="${t.target_id}" data-cancer="${esc(c)}" style="background:${color(v)}" title="${esc(label)}" aria-label="${esc(label)}"></td>`}html+='</tr>'}html+='</tbody></table>';document.getElementById('heat').innerHTML=targets.length?html:'<div class="empty">No targets match this filter.</div>';document.querySelectorAll('[data-target]').forEach(el=>{el.addEventListener('click',()=>{selected=el.dataset.target;selectedCancer=el.dataset.cancer||null;detail()});el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click()}})});detail()}
function detail(){const t=D.targets.find(x=>x.target_id===selected);if(!t)return;const cancers=D.cancer_expression.filter(x=>x.target_id===selected).sort((a,b)=>b.median_tpm-a.median_tpm),normals=D.normal_expression.filter(x=>x.target_id===selected).sort((a,b)=>b.median_tpm-a.median_tpm),chosen=cancers.find(x=>x.cancer===selectedCancer)||cancers[0],max=Math.max(1,...cancers.slice(0,6).map(x=>x.median_tpm));const ci=D.cancer_ihc.filter(x=>x.target_id===selected),ni=D.normal_ihc.filter(x=>x.target_id===selected),cp=D.cptac.filter(x=>x.target_id===selected),bridged=t.patient_comparison_status==='directionally_comparable';document.getElementById('detail').innerHTML=`<span class="status">${esc(t.overall_status)}</span><h2>${esc(t.display_name)}</h2><p class="muted"><strong>${esc(t.gene_symbol)}</strong> · ${esc(t.tier)} · ${esc(t.target_scope)}</p><div class="callout">${esc(t.caveat)}</div><dl class="kv"><dt>Diana tumor RNA</dt><dd>${bridged?`${fmt(t.patient_tpm)} TPM`:'—'}</dd><dt>TCGA-BRCA band</dt><dd>${bridged?esc(t.tcga_brca_quantile_band.replaceAll('_',' ')):'—'}</dd><dt>Descriptive Diana / BRCA median</dt><dd>${bridged&&t.descriptive_patient_to_tcga_brca_median_ratio!==null?`${fmt(t.descriptive_patient_to_tcga_brca_median_ratio)}×`:'—'}</dd><dt>Patient bridge QA</dt><dd>${bridged?esc(D.patient_bridge.qa_status.replaceAll('_',' ')):'—'}</dd><dt>Salmon mapping</dt><dd>${bridged?`${fmt(D.patient_bridge.mapping_rate)}%`:'—'}</dd><dt>Selected cancer</dt><dd>${esc(chosen?.cancer||'No data')}</dd><dt>Median / IQR</dt><dd>${chosen?`${fmt(chosen.median_tpm)} / ${fmt(chosen.q1_tpm)}–${fmt(chosen.q3_tpm)} TPM`:'—'}</dd><dt>Top normal median</dt><dd>${normals[0]?`${esc(normals[0].normal_tissue)} · ${fmt(normals[0].median_tpm)}`:'—'}</dd><dt>HPA cancer IHC rows</dt><dd>${ci.length}</dd><dt>HPA normal IHC tissues</dt><dd>${ni.length}</dd><dt>CPTAC rows</dt><dd>${cp.length}</dd></dl><p class="note">Diana-to-BRCA values are directional, not exact cohort percentiles.</p><h3>Highest tumor medians</h3><div class="bars">${cancers.slice(0,6).map(x=>`<div class="barrow"><span>${esc(x.cancer)}</span><span class="track"><span class="fill" style="display:block;width:${Math.max(2,x.median_tpm/max*100)}%"></span></span><strong>${fmt(x.median_tpm)}</strong></div>`).join('')}</div><h3>Evidence gates</h3><div class="gates">${[['Harmonized public tumor RNA','have'],['Harmonized public normal RNA','have'],['Public HPA/CPTAC context',(ci.length||ni.length||cp.length)?'have':''],['Directional Diana-to-BRCA RNA bridge',bridged?'have':'block'],['Surface localization + internalization',''],['Payload sensitivity + safety','']].map(x=>`<div class="gate"><span class="dot ${x[1]}"></span><span>${x[0]}</span></div>`).join('')}</div><p class="note"><strong>Next gate:</strong> ${esc(t.protein_gate)}</p>`}
document.getElementById('search').addEventListener('input',render);document.getElementById('tier').addEventListener('change',render);document.querySelectorAll('[data-queue-page]').forEach(button=>button.addEventListener('click',()=>{queuePage=Number(button.dataset.queuePage);queue()}));document.getElementById('generated').textContent=D.summary.generated_at;stats();queue();render();
</script></body></html>"""
    return template.replace("__ATLAS_DATA__", embedded).replace("__PATIENT_RUN_URL__", patient_run_url)


def _read_targets() -> list[dict[str, str]]:
    path = Path(os.environ.get("ADC_ATLAS_TARGETS_MANIFEST", str(path_from_root(TARGETS_MANIFEST))))
    targets = parse_csv(path.read_text(encoding="utf-8"))
    required = {
        "target_id",
        "gene_symbol",
        "query_gene",
        "display_name",
        "tier",
        "target_scope",
        "epitope_or_isoform",
        "payload_context",
        "protein_gate",
        "caveat",
    }
    if not targets or any(not required.issubset(target) for target in targets):
        raise RuntimeError("ADC target manifest is empty or missing required columns")
    if len({target["target_id"] for target in targets}) != len(targets):
        raise RuntimeError("ADC target ids must be unique")
    return targets


def main() -> None:
    output_root = Path(os.environ.get("ADC_ATLAS_OUTPUT_ROOT", str(path_from_root(OUTPUT_ROOT))))
    visualization_path = Path(os.environ.get("ADC_ATLAS_VISUALIZATION_PATH", str(path_from_root(VISUALIZATION_PATH))))
    ensure_dir(output_root)
    targets = _read_targets()
    patient_bridge = load_patient_bridge()
    patient_comparison = patient_bridge["comparisons"] if patient_bridge else []

    samples = fetch_xena_samples()
    query_genes = list(dict.fromkeys(target["query_gene"] for target in targets))
    scores = fetch_xena_gene_scores(samples, query_genes)
    phenotype_raw = _fetch_bytes(XENA_PHENOTYPE_URL)
    hpa_normal_raw = _fetch_bytes(HPA_NORMAL_IHC_URL)
    hpa_cancer_raw = _fetch_bytes(HPA_CANCER_IHC_URL)
    hpa_cptac_raw = _fetch_bytes(HPA_CPTAC_URL)

    cancer_expression, normal_expression, counts = build_expression_summaries(targets, samples, _parse_gzip_tsv(phenotype_raw), scores)
    cancer_ihc, normal_ihc, cptac = build_hpa_summaries(
        targets,
        _parse_zipped_tsv(hpa_cancer_raw),
        _parse_zipped_tsv(hpa_normal_raw),
        _parse_zipped_tsv(hpa_cptac_raw),
    )
    target_summary, candidate_matrix = build_target_and_candidate_summaries(
        targets, cancer_expression, normal_expression, cancer_ihc, normal_ihc, cptac, patient_comparison
    )
    orthogonal_followup = build_orthogonal_followup(target_summary)
    orthogonal_followup_next = build_orthogonal_followup(target_summary, start=8)

    write_csv(output_root / "cancer_expression_summary.csv", cancer_expression)
    write_csv(output_root / "normal_expression_summary.csv", normal_expression)
    write_csv(output_root / "cancer_ihc_summary.csv", cancer_ihc)
    write_csv(output_root / "normal_ihc_summary.csv", normal_ihc)
    write_csv(output_root / "cptac_summary.csv", cptac)
    write_csv(output_root / "target_summary.csv", target_summary)
    write_csv(output_root / "candidate_matrix.csv", candidate_matrix)
    write_csv(output_root / "patient_bridge_summary.csv", patient_comparison)
    write_csv(output_root / "orthogonal_followup.csv", orthogonal_followup)
    write_csv(output_root / "orthogonal_followup_next.csv", orthogonal_followup_next)

    generated_at = iso_now()
    source_manifest = {
        "atlasVersion": ATLAS_VERSION,
        "generatedAt": generated_at,
        "targetManifest": TARGETS_MANIFEST,
        "targetManifestSha256": hashlib.sha256(read_text(path_from_root(TARGETS_MANIFEST)).encode("utf-8")).hexdigest(),
        "xena": {
            "hub": XENA_HUB,
            "dataset": XENA_DATASET,
            "release": "UCSC Toil RNA-seq recompute, 2016-09-03",
            "assembly": "hg38",
            "annotation": "GENCODE v23",
            "unit": "log2(TPM + 0.001), inverted to TPM",
            "queryGenes": query_genes,
            "matrixSampleCount": len(samples),
            "matrixSampleIdsSha256": hashlib.sha256("\n".join(samples).encode("utf-8")).hexdigest(),
            "queriedGeneSliceSha256": hashlib.sha256(json.dumps(scores, separators=(",", ":"), allow_nan=True).encode("utf-8")).hexdigest(),
        },
        "downloads": [
            _source_record(XENA_PHENOTYPE_URL, phenotype_raw, "UCSC Toil TCGA/TARGET/GTEx phenotype", "2016-09-15"),
            _source_record(HPA_CANCER_IHC_URL, hpa_cancer_raw, "HPA pathology IHC", "25.1"),
            _source_record(HPA_NORMAL_IHC_URL, hpa_normal_raw, "HPA normal tissue IHC", "25.1"),
            _source_record(HPA_CPTAC_URL, hpa_cptac_raw, "HPA CPTAC protein expression", "25.1"),
        ],
        "cohortPolicy": {
            "included": ["TCGA Primary Tumor", "GTEx Normal Tissue"],
            "excluded": ["TARGET", "TCGA non-primary sample types", "non-TCGA/non-GTEx studies"],
        },
        "counts": counts,
        "patientBridge": (
            {
                "sampleLabel": patient_bridge["pointer"]["sample_label"],
                "runId": patient_bridge["run_manifest"]["runId"],
                "referenceId": patient_bridge["run_manifest"]["reference"]["referenceId"],
                "method": patient_bridge["run_manifest"]["quantification"]["method"],
                "qaStatus": patient_bridge["qa"]["status"],
                "comparisonStatus": patient_bridge["qa"]["comparisonStatus"],
                "pointerPath": str(patient_bridge["pointer_path"]),
                "pointerSha256": _sha256_file(patient_bridge["pointer_path"]),
            }
            if patient_bridge
            else {"comparisonStatus": "blocked_not_harmonized"}
        ),
        "interpretationBoundary": "Reference RNA and public protein context rank hypotheses. They do not establish patient comparability, accessible membrane antigen, internalization, payload sensitivity, safety, or treatment benefit.",
    }
    write_json(output_root / "source_manifest.json", source_manifest)

    summary = {
        "atlas_version": ATLAS_VERSION,
        "generated_at": generated_at,
        "target_count": len(targets),
        "cancer_count": len({row["cancer"] for row in cancer_expression}),
        "normal_tissue_count": len({row["normal_tissue"] for row in normal_expression}),
        "candidate_count": len(candidate_matrix),
        "partial_evidence_count": sum(row["overall_status"] == "partial_evidence" for row in candidate_matrix),
        "ready_count": sum(row["overall_status"] == "ready" for row in candidate_matrix),
        "patient_bridge_target_count": len(patient_comparison),
        "primary_followup_count": len(orthogonal_followup),
        "next_followup_count": len(orthogonal_followup_next),
        "patient_comparison_status": ("directionally_comparable" if patient_comparison else "blocked_not_harmonized"),
        **counts,
    }
    write_json(output_root / "summary.json", summary)

    cancers = sorted({row["cancer"] for row in cancer_expression})
    payload = {
        "summary": summary,
        "targets": target_summary,
        "cancers": cancers,
        "cancer_expression": cancer_expression,
        "normal_expression": normal_expression,
        "cancer_ihc": cancer_ihc,
        "normal_ihc": normal_ihc,
        "cptac": cptac,
        "patient_bridge": {
            "sample_label": patient_bridge["pointer"]["sample_label"] if patient_bridge else "Unavailable",
            "run_id": patient_bridge["run_manifest"]["runId"] if patient_bridge else None,
            "public_result_path": patient_bridge["pointer"].get("public_result_path") if patient_bridge else None,
            "comparison_status": summary["patient_comparison_status"],
            "qa_status": patient_bridge["qa"]["status"] if patient_bridge else "not_available",
            "mapping_rate": patient_bridge["qa"]["salmon"]["percentMapped"] if patient_bridge else None,
            "reference_id": patient_bridge["run_manifest"]["reference"]["referenceId"] if patient_bridge else None,
        },
    }
    write_json(output_root / "atlas_payload.json", payload)
    write_text(visualization_path, _render_html(payload))
    write_text(
        output_root / "README.md",
        f"""# Pan-cancer ADC Atlas v1

Generated: {generated_at}

This run profiles {len(targets)} ADC targets across {summary["cancer_count"]} TCGA primary-tumor cohorts and {summary["normal_tissue_count"]} GTEx normal-tissue groups using the UCSC Toil harmonized RNA-seq recompute. HPA v25.1 cancer IHC, normal-tissue IHC, and CPTAC rows provide separate protein-context lanes.

## Status

- Candidate rows: {len(candidate_matrix)}
- `partial_evidence`: {summary["partial_evidence_count"]}
- `ready`: {summary["ready_count"]}
- Patient comparison: `{summary["patient_comparison_status"]}` across {summary["patient_bridge_target_count"]} targets. The same GENCODE v23 feature model and TPM scale support directional TCGA-BRCA bands, but Salmon versus Toil/RSEM and other technical/specimen differences preclude exact cohort percentiles.
- Protein follow-up queues: {summary["primary_followup_count"]} targets in ranks 1–8 and {summary["next_followup_count"]} targets in ranks 9–16.

## Interpretation boundary

This atlas ranks research hypotheses. RNA abundance is not surface-protein abundance, and public HPA/CPTAC context does not establish accessible membrane antigen, internalization, payload sensitivity, safety, or benefit in a patient. The exact source URLs, versions, hashes, query genes, filters, and sample counts are in `source_manifest.json`.
""",
    )
    artifact_paths = [
        output_root / "README.md",
        output_root / "atlas_payload.json",
        output_root / "cancer_expression_summary.csv",
        output_root / "cancer_ihc_summary.csv",
        output_root / "candidate_matrix.csv",
        output_root / "cptac_summary.csv",
        output_root / "normal_expression_summary.csv",
        output_root / "normal_ihc_summary.csv",
        output_root / "orthogonal_followup.csv",
        output_root / "orthogonal_followup_next.csv",
        output_root / "patient_bridge_summary.csv",
        output_root / "source_manifest.json",
        output_root / "summary.json",
        output_root / "target_summary.csv",
        visualization_path,
    ]
    artifact_index = [
        {
            "path": str(path.relative_to(path_from_root(""))) if path.is_relative_to(path_from_root("")) else str(path),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in artifact_paths
    ]
    write_json(output_root / "artifact_index.json", artifact_index)
    write_json(
        output_root / "run_manifest.json",
        {
            "runId": f"pan-cancer-adc-atlas-v1-{generated_at.replace(':', '').replace('-', '')}",
            "analysis": "pan-cancer ADC target reference atlas",
            "atlasVersion": ATLAS_VERSION,
            "status": "completed",
            "generatedAt": generated_at,
            "command": "python3 -m diana_omics build:pan-cancer-adc-atlas",
            "executionBackend": "local metadata/API aggregation",
            "targetManifest": TARGETS_MANIFEST,
            "sourceManifest": f"{OUTPUT_ROOT}/source_manifest.json",
            "artifactIndex": f"{OUTPUT_ROOT}/artifact_index.json",
            "artifactCount": len(artifact_index),
            "evidenceCeiling": "partial_evidence",
            "readyCandidateCount": summary["ready_count"],
            "patientComparisonStatus": summary["patient_comparison_status"],
        },
    )
    print(
        f"Built Pan-cancer ADC Atlas {ATLAS_VERSION}: {len(targets)} targets, "
        f"{summary['cancer_count']} cancers, {counts['tcga_primary_tumors']} primary tumors, "
        f"{counts['gtex_normal_tissues']} normal samples; ready={summary['ready_count']}."
    )


if __name__ == "__main__":
    main()
