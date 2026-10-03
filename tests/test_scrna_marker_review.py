"""Review hints must preserve the original counts and never change cell selection."""
import numpy as np
import pandas as pd
import pytest
from anndata import AnnData
from scipy.sparse import csr_matrix

from diana_omics.scrna import all_barcode_marker_review


@pytest.mark.parametrize("markers", [True, False])
def test_loss_review_preserves_counts_and_decisions_even_without_marker_coverage(tmp_path, monkeypatch, markers):
    symbols = ["MT-CO1", "EPCAM", "KRT8", "COL1A1", "DCN", "LUM"] if markers else ["MT-CO1"]
    genes = symbols + [f"GENE_{i}" for i in range(1000)]
    matrix = csr_matrix(np.random.default_rng(42).poisson(1, (10, len(genes))))
    obs = pd.DataFrame({"passes_QC": [True] * 7 + [False] * 3, "fails_low_genes": [False] * 7 + [True] * 3,
                        "fails_low_umis": False, "fails_mt": False, "doublet_class": "singlet"}, index=[f"cell-{i}" for i in range(10)])
    data = AnnData(matrix.copy(), obs=obs.copy(), var=pd.DataFrame(index=genes))
    original_dense = csr_matrix.toarray
    def limited_dense(self, *args, **kwargs):
        assert self.shape[1] < 10  # Only the small selected marker panel may be dense.
        return original_dense(self, *args, **kwargs)
    monkeypatch.setattr(csr_matrix, "toarray", limited_dense)
    all_barcode_marker_review(data, tmp_path, breast=True)
    assert (matrix != data.X).nnz == 0
    pd.testing.assert_frame_equal(data.obs[obs.columns], obs)
    losses = pd.read_csv(tmp_path / "provisional_compartment_losses.csv")
    assert losses.input_cells.sum() == 10 and losses.retained_cells.sum() == 7
    if not markers:
        assert list(data.obs.review_marker_hint_all_barcodes.unique()) == ["Unknown / mixed"]
