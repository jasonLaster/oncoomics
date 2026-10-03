"""Resolution selection must be reproducible, label-free, and fail visibly when no stable partition exists."""
import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
sc = pytest.importorskip("scanpy")
pytest.importorskip("leidenalg")

from anndata import AnnData  # noqa: E402

from diana_omics.scrna import stable_leiden  # noqa: E402

PARAMETERS = {"seed": 42, "leiden_resolution": 0.5, "leiden_iterations": -1,
              "leiden_resolution_grid": [0.2, 0.5, 1.0], "stability_seeds": 4}
ACCEPTANCE = {"clusters_min": 4, "clusters_max": 25}


def blobs():
    rng = np.random.default_rng(0)
    centers = rng.normal(0, 20, (5, 10))
    points = np.vstack([center + rng.normal(0, 1, (80, 10)) for center in centers])
    data = AnnData(np.zeros((len(points), 1)), obs=pd.DataFrame(index=[f"cell-{i}" for i in range(len(points))]))
    data.obsm["X_pca"] = points
    sc.pp.neighbors(data, n_neighbors=15, use_rep="X_pca", random_state=0)
    return data


def test_selects_stable_in_bounds_partition_and_records_sweep(tmp_path):
    data = blobs()
    data.obs["author_label"] = "decoy"  # Unrelated annotations must not influence selection.
    result = stable_leiden(data, PARAMETERS, ACCEPTANCE, tmp_path)
    sweep = pd.read_csv(tmp_path / "cluster_stability.csv")
    assert list(sweep.resolution) == PARAMETERS["leiden_resolution_grid"] and sweep.selected.sum() == 1
    chosen = sweep[sweep.selected].iloc[0]
    assert chosen.eligible and chosen.median_pairwise_ari == sweep[sweep.eligible].median_pairwise_ari.max()
    assert result["median_pairwise_ari"] >= 0.85 and result["pairs_per_resolution"] == 6
    assert result["reported_seed"] in result["seeds"] and "_stability" not in data.obs
    assert ACCEPTANCE["clusters_min"] <= data.obs.leiden.nunique() <= ACCEPTANCE["clusters_max"]
    again = blobs()
    (tmp_path / "again").mkdir()
    stable_leiden(again, PARAMETERS, ACCEPTANCE, tmp_path / "again")
    assert (again.obs.leiden.astype(str).to_numpy() == data.obs.leiden.astype(str).to_numpy()).all()


def test_no_eligible_resolution_keeps_default_and_reports_it(tmp_path):
    result = stable_leiden(blobs(), PARAMETERS, {"clusters_min": 50, "clusters_max": 60}, tmp_path)
    assert result["eligible_resolutions"] == 0 and result["selected_resolution"] == PARAMETERS["leiden_resolution"]
