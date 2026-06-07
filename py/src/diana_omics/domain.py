from __future__ import annotations

import re
from typing import Any, Mapping, Optional

DAMAGING_TYPES = {
    "Nonsense_Mutation",
    "Frame_Shift_Del",
    "Frame_Shift_Ins",
    "Splice_Site",
    "Translation_Start_Site",
    "Nonstop_Mutation",
}
BRCA_GENES = {"BRCA1", "BRCA2"}


def gene_symbol(record: Mapping[str, Any]) -> str:
    gene = record.get("gene") or {}
    return str(gene.get("hugoGeneSymbol", ""))


def mutation_class(mutation: Mapping[str, Any]) -> str:
    mutation_type = str(mutation.get("mutationType", ""))
    keyword = str(mutation.get("keyword", ""))
    if mutation_type in DAMAGING_TYPES or re.search(r"truncating|frameshift|splice", keyword, re.I):
        return "likely_damaging"
    if re.search(r"Missense", mutation_type, re.I):
        return "missense_or_vus"
    return "other"


def score_mutation(mutation: Mapping[str, Any]) -> int:
    classification = mutation_class(mutation)
    if classification == "likely_damaging":
        return 3
    if classification == "missense_or_vus":
        return 1
    return 0


def cna_state(value: Optional[float]) -> str:
    if value is None:
        return "not_available"
    if value <= -2:
        return "deep_deletion"
    if value == -1:
        return "shallow_loss"
    if value == 0:
        return "neutral"
    if value == 1:
        return "gain"
    if value >= 2:
        return "amplification"
    return str(value)


def scar_proxy_class(fga: Optional[float], aneuploidy: Optional[float]) -> str:
    if (fga or 0) >= 0.35 or (aneuploidy or 0) >= 12:
        return "copy_number_scar_proxy_high"
    if (fga or 0) >= 0.2 or (aneuploidy or 0) >= 6:
        return "copy_number_scar_proxy_intermediate"
    if fga is not None or aneuploidy is not None:
        return "copy_number_scar_proxy_low"
    return "not_assessable"


def prediction_class(
    panel_row: Mapping[str, str],
    best_mutation: Optional[Mapping[str, Any]],
    best_cna: Optional[float],
    fga: Optional[float],
    aneuploidy: Optional[float],
) -> str:
    event_class = mutation_class(best_mutation) if best_mutation else "none"
    is_brca = gene_symbol(best_mutation) in BRCA_GENES if best_mutation else False
    second_hit = best_cna is not None and best_cna <= -1
    scar = scar_proxy_class(fga, aneuploidy)
    if is_brca and event_class == "likely_damaging" and second_hit and scar == "copy_number_scar_proxy_high":
        return "strong_hrd_like_candidate"
    if (
        event_class == "likely_damaging"
        and second_hit
        and scar
        in {
            "copy_number_scar_proxy_high",
            "copy_number_scar_proxy_intermediate",
        }
    ):
        return "suggestive_hrd_like_candidate"
    if not best_mutation and panel_row.get("expected_hrd_label") == "expected_hrd_negative" and scar == "copy_number_scar_proxy_low":
        return "low_evidence_negative_candidate"
    if best_mutation:
        return "ambiguous_or_incomplete"
    return "not_assessable"


def confusion_bucket(prediction: str) -> str:
    if "hrd_like" in prediction:
        return "predicted_hrd_like"
    if "negative" in prediction:
        return "predicted_negative"
    return "predicted_ambiguous_or_not_assessable"
