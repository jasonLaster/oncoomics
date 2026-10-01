import copy
import json
from pathlib import Path

import pytest

from diana_omics.scrna_io import validate_config
from diana_omics.scrna_qc import breast_audits, coarse_marker_scores, core_decisions, read_geo_matrix, thresholds, validate_author_metadata

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")


@pytest.fixture
def breast_config():
    return json.loads((Path(__file__).parents[1] / "manifests/scrna/breast/calibration.json").read_text())


def test_breast_manifest_and_technical_partition_custody(breast_config):
    validate_config(breast_config)
    breast_config["datasets"][1]["capture_id"] = breast_config["datasets"][0]["capture_id"]
    with pytest.raises(ValueError, match="capture cannot be split"):
        validate_config(breast_config)


@pytest.mark.parametrize("field", ["material", "sample_id", "treatment_status", "capture_scope", "upstream_processing"])
def test_breast_cohort_cannot_hide_missing_metadata(breast_config, field):
    del breast_config["datasets"][0][field]
    with pytest.raises(ValueError, match="metadata"):
        validate_config(breast_config)


def test_unvalidated_nuclei_and_ambient_inputs_are_rejected(breast_config):
    nuclei = copy.deepcopy(breast_config)
    nuclei["datasets"][0]["material"] = "nucleus"
    with pytest.raises(ValueError, match="nuclei"):
        validate_config(nuclei)
    breast_config["datasets"][0]["inputs"].append({"role": "raw_droplets"})
    with pytest.raises(ValueError, match="correction lane"):
        validate_config(breast_config)


def test_mixed_tissue_does_not_use_epithelial_median_to_drop_low_rna_cells():
    # Ninety large epithelial-like cells and ten lower-RNA immune-like cells.
    obs = pd.DataFrame({"n_genes_by_counts": np.r_[np.arange(90) + 5000, np.arange(10) + 300],
                        "total_counts": np.r_[np.arange(90) + 25000, np.arange(10) + 600],
                        "pct_counts_mt": np.linspace(10, 30, 100)})
    policy = thresholds(obs, 3, "human_breast_tumor")
    assert policy["min_genes"] <= np.quantile(obs.n_genes_by_counts, 0.05)
    assert policy["max_pct_mt"] > 25  # No PBMC cap for breast tissue.
    flags = core_decisions(obs, policy)
    assert flags.loc[:89, "passes_core_qc"].all()  # High RNA counts alone never exclude.
    assert flags.loc[90:, "passes_core_qc"].sum() >= 5
    assert core_decisions(obs, thresholds(obs, 3, "human_pbmc")).loc[90:, "fails_low_genes"].all()


def test_zero_mad_does_not_collapse_breast_mt_cutoff():
    obs = pd.DataFrame({"n_genes_by_counts": [400] * 100, "total_counts": [800] * 100,
                        "pct_counts_mt": [0] * 99 + [1]})
    assert core_decisions(obs, thresholds(obs, 3, "human_breast_tumor")).passes_core_qc.all()


def test_author_metadata_is_exact_and_sample_checked(breast_config):
    dataset = breast_config["datasets"][0]
    metadata = pd.DataFrame({"orig.ident": [dataset["sample_id"]] * 2,
                             "subtype": [dataset["clinical_subtype"]] * 2,
                             "celltype_major": ["Cancer Epithelial", "T-cells"]}, index=["b", "a"])
    aligned = validate_author_metadata(metadata, pd.Index(["a", "b"]), dataset)
    assert aligned.index.tolist() == ["a", "b"]
    for bad in (metadata.iloc[:1], pd.concat([metadata, metadata.iloc[:1]]), metadata.assign(subtype="wrong")):
        with pytest.raises(ValueError):
            validate_author_metadata(bad, pd.Index(["a", "b"]), dataset)


def test_geo_matrix_import_preserves_sparse_orientation_and_valid_index_names(breast_config, tmp_path):
    pytest.importorskip("anndata")
    from scipy.io import mmwrite
    from scipy.sparse import csr_matrix, issparse

    dataset = breast_config["datasets"][0]
    cells_by_genes = csr_matrix([[5, 2, 0], [1, 0, 7]])
    mmwrite(tmp_path / "count_matrix_sparse.mtx", cells_by_genes.T)
    (tmp_path / "count_matrix_genes.tsv").write_text("MT-CO1\nCD3D\nKRT8\n")
    (tmp_path / "count_matrix_barcodes.tsv").write_text("a\nb\n")
    pd.DataFrame({"orig.ident": [dataset["sample_id"]] * 2,
                  "subtype": [dataset["clinical_subtype"]] * 2,
                  "celltype_major": ["T-cells", "Cancer Epithelial"]}, index=["a", "b"]).to_csv(tmp_path / "metadata.csv")
    adata, metadata = read_geo_matrix(tmp_path, dataset)
    adata.var_names_make_unique()  # Regression: pandas' numeric column label cannot become index.name.
    assert adata.var_names.name is None
    assert adata.obs_names.name is None
    assert issparse(adata.X) and (cells_by_genes != adata.X).nnz == 0
    assert adata.obs_names.tolist() == metadata.index.tolist() == ["a", "b"]
    assert adata.var_names.tolist() == ["MT-CO1", "CD3D", "KRT8"]


def test_review_signals_and_author_labels_cannot_change_core_decisions():
    obs = pd.DataFrame({"n_genes_by_counts": [500, 800, 900], "total_counts": [900, 1800, 50000], "pct_counts_mt": [2, 3, 4]})
    policy = thresholds(obs, 3, "human_breast_tumor")
    first = core_decisions(obs, policy)
    obs["review_high_stress"] = True
    obs["review_high_cycling"] = True
    obs["author_compartment"] = "Cancer Epithelial"
    pd.testing.assert_frame_equal(first, core_decisions(obs, policy))


def test_breast_cytotoxic_scores_resolve_only_coarse_lineage():
    scores = pd.DataFrame({"T cells": [0.7, 0.1], "NK cells": [0.8, 0.2], "Myeloid": [0.1, 1.2]})
    grouped = coarse_marker_scores(scores, breast=True)
    assert "T cells" not in grouped and "NK cells" not in grouped
    assert grouped.idxmax(axis=1).tolist() == ["T / NK", "Myeloid"]
    pd.testing.assert_frame_equal(coarse_marker_scores(scores, breast=False), scores)


def test_proxy_capture_and_compartment_loss_block_readiness(breast_config, tmp_path):
    obs = pd.DataFrame({"n_genes_by_counts": [400, 500, 600, 700], "total_counts": [1000, 2000, 3000, 4000],
                        "pct_counts_mt": [1, 2, 3, 4], "author_compartment": ["Epithelial"] * 2 + ["T cells"] * 2,
                        "passes_core_qc": [True] * 4, "passes_QC": [True, False, True, True],
                        "fails_low_genes": [False] * 4, "fails_low_umis": [False] * 4, "fails_mt": [False] * 4,
                        "doublet_class": ["singlet", "doublet", "singlet", "singlet"]})
    audit = breast_audits(obs, breast_config["datasets"][0], breast_config["parameters"], tmp_path)
    assert not audit["production_ready"]
    assert any("capture map unresolved" in reason for reason in audit["readiness_blockers"])
    assert any("less than 70%" in reason for reason in audit["readiness_blockers"])
    assert audit["minimum_compartment_retention"] == 0.5
    assert (tmp_path / "qc_sensitivity.csv").exists()
