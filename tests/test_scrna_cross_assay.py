from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from diana_omics.scrna_cross_assay import stable_gene_id, summarize_targets  # noqa: E402


def fixture():
    index = pd.Index(["barcode1", "barcode2", "barcode3"])
    return pd.DataFrame({"GENE": [2, 0, 4]}, index=index), pd.Series([10, 20, 40], index=index), {"all": pd.Series("all", index=index)}


def test_descriptive_counts_and_correct_same_layer_denominator():
    targets, totals, groups = fixture()
    row = summarize_targets("library1", targets, totals, groups, "original_counts", 1)[0]
    assert row["detected_fraction"] == pytest.approx(2 / 3)
    assert row["pseudobulk_umi_cpm"] == pytest.approx(6 / 70 * 1e6)
    assert row["clinical_ready"] is False
    assert row["target_umi_sum"] == 6


def test_shuffled_labels_cannot_silently_join_by_position():
    targets, totals, groups = fixture()
    groups["all"] = groups["all"].iloc[::-1]
    with pytest.raises(ValueError):
        summarize_targets("library1", targets, totals, groups, "original_counts", 1)


def test_tiny_vendor_groups_are_not_ranked_as_biology():
    targets, totals, groups = fixture()
    row = summarize_targets("library1", targets, totals, groups, "original_counts")[0]
    assert row["status"] == "insufficient_group"
    assert row["detected_fraction"] is row["pseudobulk_umi_cpm"] is None


def test_overlapping_barcode_strings_do_not_merge_libraries():
    targets, totals, groups = fixture()
    rows = [summarize_targets(lib, targets, totals, groups, "original_counts", 1)[0] for lib in ("library1", "library2")]
    assert [r["library_id"] for r in rows] == ["library1", "library2"]
    assert sum(r["barcodes"] for r in rows) == 6


@pytest.mark.parametrize("count", [-1, float("nan"), 1.5, 1000])
def test_invalid_target_counts_fail_closed(count):
    targets, totals, groups = fixture()
    targets = targets.astype(float)
    targets.iloc[0, 0] = count
    with pytest.raises(ValueError):
        summarize_targets("library1", targets, totals, groups, "original_counts", 1)


def test_ensembl_versions_do_not_change_gene_identity():
    assert stable_gene_id("ENSG00000141510.18") == "ENSG00000141510"
    with pytest.raises(ValueError):
        stable_gene_id("TP53")
