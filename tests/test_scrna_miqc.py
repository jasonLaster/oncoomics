import subprocess

import pytest

from diana_omics.scrna_miqc import assess_miqc

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")


def metrics():
    return pd.DataFrame({"n_genes_by_counts": [600, 1200, 2000], "pct_counts_mt": [3, 20, 8],
                         "fails_mt": [False, True, False]}, index=["a", "b", "c"])


def test_unidentifiable_miqc_is_no_call_without_keep_all_fallback(tmp_path, monkeypatch):
    def run(*args, **kwargs):
        for seed in (42, 43):
            (tmp_path / "miqc" / f"status-{seed}.txt").write_text("not_assessable: one component")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    obs = metrics()
    active = obs.fails_mt.copy()
    result = assess_miqc(obs, tmp_path, 42)
    assert result["status"] == "not_assessable"
    assert obs.miqc_prob_compromised.isna().all() and obs.miqc_candidate_keep.isna().all()
    pd.testing.assert_series_equal(active, obs.fails_mt)


def test_missing_r_package_remains_an_execution_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "no miQC package"))
    with pytest.raises(subprocess.CalledProcessError):
        assess_miqc(metrics(), tmp_path, 42)
    assert not (tmp_path / "miqc/assessment.json").exists()


def test_barcode_mapping_and_probability_bounds_are_mandatory(tmp_path, monkeypatch):
    def run(*args, **kwargs):
        for seed in (42, 43):
            (tmp_path / "miqc" / f"status-{seed}.txt").write_text("fit_complete")
            pd.DataFrame({"barcode": ["a", "b", "c"], "prob_compromised": [0, np.inf, 0.1],
                          "candidate_keep": [True, False, True]}).to_csv(tmp_path / "miqc" / f"seed-{seed}.csv", index=False)
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="probabilities"):
        assess_miqc(metrics(), tmp_path, 42)


def test_nullable_no_call_fields_persist_in_anndata(tmp_path, monkeypatch):
    ad = pytest.importorskip("anndata")
    from scipy.sparse import csr_matrix

    def run(*args, **kwargs):
        for seed in (42, 43):
            (tmp_path / "miqc" / f"status-{seed}.txt").write_text("not_assessable: one component")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    obs = metrics()
    assess_miqc(obs, tmp_path, 42)
    adata = ad.AnnData(csr_matrix(np.eye(3)), obs=obs)
    adata.write_h5ad(tmp_path / "checkpoint.h5ad")
    restored = ad.read_h5ad(tmp_path / "checkpoint.h5ad")
    assert restored.obs.miqc_candidate_keep.isna().all()
