from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence


def parse_gtf_attributes(value: str) -> dict[str, str]:
    return {key: item for key, item in re.findall(r'(\w+)\s+"([^"]*)"', value)}


def transcript_gene_map(gtf_lines: Iterable[str]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for line in gtf_lines:
        if not line or line.startswith("#"):
            continue
        fields = line.rstrip("\n").split("\t")
        if len(fields) != 9 or fields[2] != "transcript":
            continue
        attributes = parse_gtf_attributes(fields[8])
        transcript_id = attributes.get("transcript_id")
        gene_id = attributes.get("gene_id")
        if not transcript_id or not gene_id:
            continue
        mapping[transcript_id] = {
            "gene_id": gene_id,
            "gene_symbol": attributes.get("gene_name", gene_id),
            "gene_type": attributes.get("gene_type", attributes.get("gene_biotype", "unknown")),
        }
    return mapping


def aggregate_salmon_to_genes(
    quant_rows: Sequence[Mapping[str, Any]],
    tx2gene: Mapping[str, Mapping[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"gene_symbol": "", "gene_type": "unknown", "tpm": 0.0, "estimated_reads": 0.0, "transcript_count": 0}
    )
    missing_transcripts: list[str] = []
    for row in quant_rows:
        transcript_id = str(row["Name"])
        gene = tx2gene.get(transcript_id)
        if gene is None:
            missing_transcripts.append(transcript_id)
            continue
        record = aggregates[gene["gene_id"]]
        record["gene_symbol"] = gene["gene_symbol"]
        record["gene_type"] = gene["gene_type"]
        record["tpm"] += float(row["TPM"])
        record["estimated_reads"] += float(row["NumReads"])
        record["transcript_count"] += 1
    rows = [
        {
            "gene_id": gene_id,
            "gene_symbol": record["gene_symbol"],
            "gene_type": record["gene_type"],
            "tpm": round(record["tpm"], 6),
            "estimated_reads": round(record["estimated_reads"], 3),
            "transcript_count": record["transcript_count"],
        }
        for gene_id, record in aggregates.items()
    ]
    rows.sort(key=lambda row: (-float(row["tpm"]), str(row["gene_symbol"]), str(row["gene_id"])))
    return rows, {
        "quantified_transcripts": len(quant_rows),
        "mapped_transcripts": len(quant_rows) - len(missing_transcripts),
        "unmapped_transcripts": len(missing_transcripts),
        "transcript_mapping_fraction": round((len(quant_rows) - len(missing_transcripts)) / len(quant_rows), 6) if quant_rows else 0.0,
        "gene_count": len(rows),
        "gene_tpm_sum": round(sum(float(row["tpm"]) for row in rows), 6),
    }


def percentile_rank(value: float, population: Sequence[float]) -> float | None:
    clean = sorted(item for item in population if math.isfinite(item))
    if not clean:
        return None
    below = sum(item < value for item in clean)
    equal = sum(item == value for item in clean)
    return round((below + 0.5 * equal) / len(clean) * 100, 2)


def cohort_band(value: float, cohort: Mapping[str, Any]) -> str:
    q1 = float(cohort["q1_tpm"])
    median = float(cohort["median_tpm"])
    q3 = float(cohort["q3_tpm"])
    p90 = float(cohort["p90_tpm"])
    p95 = float(cohort["p95_tpm"])
    if value < q1:
        return "below_q1"
    if value < median:
        return "q1_to_median"
    if value < q3:
        return "median_to_q3"
    if value < p90:
        return "q3_to_p90"
    if value < p95:
        return "p90_to_p95"
    return "at_or_above_p95"


def build_target_comparison(
    targets: Sequence[Mapping[str, str]],
    gene_rows: Sequence[Mapping[str, Any]],
    breast_reference: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    gene_by_symbol = {str(row["gene_symbol"]): row for row in gene_rows}
    reference_by_target = {str(row["target_id"]): row for row in breast_reference}
    protein_coding_tpm = [
        float(row["tpm"]) for row in gene_rows if row.get("gene_type") == "protein_coding" and math.isfinite(float(row["tpm"]))
    ]
    comparisons = []
    for target in targets:
        patient = gene_by_symbol.get(target["query_gene"])
        reference = reference_by_target.get(target["target_id"])
        patient_tpm = float(patient["tpm"]) if patient else 0.0
        median = float(reference["median_tpm"]) if reference else 0.0
        comparisons.append(
            {
                "target_id": target["target_id"],
                "gene_symbol": target["gene_symbol"],
                "quantification_symbol": target["query_gene"],
                "display_name": target["display_name"],
                "patient_tpm": round(patient_tpm, 6),
                "patient_protein_coding_percentile": percentile_rank(patient_tpm, protein_coding_tpm),
                "tcga_brca_sample_count": int(reference["sample_count"]) if reference else 0,
                "tcga_brca_q1_tpm": float(reference["q1_tpm"]) if reference else None,
                "tcga_brca_median_tpm": median if reference else None,
                "tcga_brca_q3_tpm": float(reference["q3_tpm"]) if reference else None,
                "tcga_brca_p90_tpm": float(reference["p90_tpm"]) if reference else None,
                "tcga_brca_p95_tpm": float(reference["p95_tpm"]) if reference else None,
                "descriptive_patient_to_cohort_median_ratio": round(patient_tpm / median, 4) if median > 0 else None,
                "cohort_quantile_band": cohort_band(patient_tpm, reference) if reference else "not_available",
                "comparison_status": "directionally_comparable" if patient and reference else "not_comparable",
                "evidence_status": "partial_evidence",
                "comparison_caveat": (
                    "Same GENCODE v23 feature model and TPM scale, but private Salmon and public Toil/RSEM quantifiers, "
                    "library preparation, tumor composition, and batch differ; the band and ratio are descriptive, not an exact percentile."
                ),
            }
        )
    return comparisons
