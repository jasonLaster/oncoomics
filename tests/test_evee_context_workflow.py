from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "workflows" / "evee_context" / "bin"


def load_module(name: str, filename: str):
    sys.path.insert(0, str(BIN))
    spec = importlib.util.spec_from_file_location(name, BIN / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVEE = load_module("evee_score_test", "score_evee_variants.py")
PATHWAYS = load_module("pathway_score_test", "score_pathway_ranks.py")
EVO2 = load_module("evo2_score_test", "score_evo2_zero_shot.py")


def test_evee_snv_identity_uses_zero_based_position() -> None:
    row = {"chrom": "17", "pos": 43092919, "ref": "G", "alt": "A", "supplied_evee_variant_id": ""}
    variant_id, status = EVEE.evee_identity(row, "GRCh38")
    assert variant_id == "chr17:43092918:G:A"
    assert status == "derived_snv_0_based"


def test_evee_indel_requires_explicit_identity() -> None:
    row = {"chrom": "7", "pos": 117559590, "ref": "ATCT", "alt": "A", "supplied_evee_variant_id": ""}
    variant_id, status = EVEE.evee_identity(row, "GRCh38")
    assert variant_id is None
    assert status == "indel_requires_explicit_evee_id"


def test_top_disruptions_ranks_absolute_delta_without_conflating_pathogenicity() -> None:
    record = {
        "pathogenicity": 0.4003,
        "ref_ptm": 0.2,
        "var_ptm": 0.9,
        "ref_domain": 0.7,
        "var_domain": 0.4,
    }
    rows = EVEE.top_disruptions(record, 2)
    assert rows[0]["annotation"] == "ptm"
    assert rows[0]["delta"] == 0.7
    assert "pathogenicity" not in rows[0]


def test_percentile_ranks_average_ties() -> None:
    ranks = PATHWAYS.percentile_ranks({"A": 1.0, "B": 2.0, "C": 2.0, "D": 4.0})
    assert ranks == {"A": 0.125, "B": 0.5, "C": 0.5, "D": 0.875}


def test_pathway_score_and_empirical_percentile() -> None:
    samples = ["patient", "basal_low", "basal_high", "tnbc"]
    expression = {
        "patient": {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0},
        "basal_low": {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0},
        "basal_high": {"A": 4.0, "B": 3.0, "C": 1.0, "D": 2.0},
        "tnbc": {"A": 2.0, "B": 1.0, "C": 4.0, "D": 3.0},
    }
    groups = {"patient": "patient", "basal_low": "Basal", "basal_high": "Basal", "tnbc": "TNBC"}
    _, percentiles = PATHWAYS.compute(samples, expression, {"SET": {"A", "B"}}, groups, "patient", 2)
    basal = next(row for row in percentiles if row["comparison_group"] == "Basal")
    assert basal["reference_n"] == 2
    assert basal["empirical_percentile"] == 75.0


def test_evo2_window_replaces_only_the_requested_snv() -> None:
    reference, alternate, offset = EVO2.build_snv_window("AACCGGTT", 4, "C", "A", 6)
    assert reference == "AACCGG"
    assert alternate == "AACAGG"
    assert offset == 3


def test_report_highlight_manifest_has_expected_coordinates() -> None:
    rows = EVEE.load_variants(ROOT / "manifests" / "evee_report_highlights.tsv")
    assert len(rows) == 9
    cul3 = next(row for row in rows if row["reported_gene"] == "CUL3")
    assert cul3["pos"] == 224506102
    assert cul3["ref"] == "G"
    assert cul3["alt"] == "A"
