from __future__ import annotations

import copy
import json

import pytest

from diana_omics.scrna_exploratory import TARGETS, validate_plan
from diana_omics.scrna_exploratory_audit import audit_exploratory_counts
from diana_omics.scrna_io import sha256_file
from diana_omics.scrna_private import BUCKET, run_prefix


def plan():
    return {
        "schema_version": 1,
        "run_id": "synthetic-exploratory",
        "output_prefix": run_prefix("synthetic-exploratory"),
        "evidence_lane": "patient_research",
        "metadata_hold": True,
        "clinical_ready": False,
        "libraries": [
            {
                "library_id": "synthetic1",
                "expected_cells": 100,
                "inputs": [
                    {
                        "role": role,
                        "bucket": BUCKET,
                        "key": "private/scrna/synthetic/" + role,
                        "version_id": "version1",
                        "sha256": "a" * 64,
                        "size_bytes": 100,
                        "local_name": role + ".h5",
                    }
                    for role in ("raw_h5", "filtered_h5")
                ],
            }
        ],
    }


def test_valid_plan_preserves_patient_lane_despite_public_originals():
    validate_plan(plan())


@pytest.mark.parametrize("field,value", [("metadata_hold", False), ("clinical_ready", True), ("evidence_lane", "public_patient")])
def test_exploration_cannot_promote_release(field, value):
    value_plan = plan()
    value_plan[field] = value
    with pytest.raises(ValueError):
        validate_plan(value_plan)


@pytest.mark.parametrize(
    "field,value", [("version_id", "null"), ("sha256", "a" * 32), ("local_name", "../escape.h5"), ("bucket", "public")]
)
def test_input_receipts_and_paths_fail_closed(field, value):
    value_plan = plan()
    value_plan["libraries"][0]["inputs"][0][field] = value
    with pytest.raises(ValueError):
        validate_plan(value_plan)


def test_library_alias_cannot_reuse_same_matrix_as_independent_capture():
    value_plan = plan()
    other = copy.deepcopy(value_plan["libraries"][0])
    other["library_id"] = "synthetic2"
    value_plan["libraries"].append(other)
    with pytest.raises(ValueError):
        validate_plan(value_plan)


def synthetic_outputs(root):
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")
    h5py = pytest.importorskip("h5py")
    ad = pytest.importorskip("anndata")
    sparse = pytest.importorskip("scipy.sparse")
    counts = sparse.csr_matrix(np.array([[2, 0, 1], [0, 4, 2], [1, 3, 1]], dtype=np.int32))
    barcodes = ["bc1", "bc2", "bc3"]
    ids = ["ENSG00000000001", "ENSG00000000002", "ENSG00000000003"]
    symbols = ["TACSTD2", "BRCA1", "MT-ND1"]
    source = root / "source.h5"
    transposed = counts.T.tocsc()
    with h5py.File(source, "w") as handle:
        group = handle.create_group("matrix")
        for name in ("data", "indices", "indptr"):
            group.create_dataset(name, data=getattr(transposed, name))
        group.create_dataset("shape", data=transposed.shape)
        group.create_dataset("barcodes", data=np.array(barcodes, dtype="S"))
        features = group.create_group("features")
        for name, values in (("id", ids), ("name", symbols), ("feature_type", ["Gene Expression"] * 3)):
            features.create_dataset(name, data=np.array(values, dtype="S"))
    output = root / "outputs"
    output.mkdir()
    total = np.array([3, 6, 5])
    obs = pd.DataFrame(
        {
            "total_counts": total,
            "n_genes_by_counts": [2, 2, 3],
            "pct_counts_mt": [100 / 3, 100 / 3, 20],
            "coarse_label_hint": "Unknown / mixed",
            "leiden_diagnostic_r05": ["0", "0", "1"],
            "diagnostic_doublet_class": ["singlet", "doublet", "singlet"],
            "conditional_whole_cell_passes_core_qc": True,
        },
        index=barcodes,
    )
    checkpoint = ad.AnnData(counts, obs=obs, var=pd.DataFrame({"gene_ids": ids, "gene_symbols": symbols}, index=symbols))
    checkpoint.write_h5ad(output / "all_vendor_cells_counts.h5ad")
    obs.to_csv(output / "all_vendor_barcodes.csv.gz")
    target_counts = pd.DataFrame({"BRCA1": [0, 4, 3], "TACSTD2": [2, 0, 1]}, index=barcodes)
    target_counts.to_csv(output / "target_umi_per_barcode.csv.gz")
    groupings = {
        "all_vendor_barcodes": np.repeat("all", 3),
        "coarse_marker_hint": obs.coarse_label_hint.to_numpy(),
        "diagnostic_cluster": obs.leiden_diagnostic_r05.to_numpy(),
        "diagnostic_doublet_class": obs.diagnostic_doublet_class.to_numpy(),
        "conditional_whole_cell_core_flag": np.repeat("conditional_core_pass", 3),
    }
    rows = []
    for grouping, labels in groupings.items():
        for label in set(labels):
            mask = labels == label
            for gene in TARGETS:
                row = {
                    "grouping": grouping,
                    "group": label,
                    "gene": gene,
                    "feature_present": gene in target_counts,
                    "cells": int(mask.sum()),
                }
                if gene in target_counts:
                    values = target_counts[gene].to_numpy()[mask]
                    logs = np.log1p(values * 10000 / total[mask])
                    row.update(
                        umi_sum=int(values.sum()),
                        detected_cells=int((values > 0).sum()),
                        detected_fraction=float((values > 0).mean()),
                        pseudobulk_umi_cpm=values.sum() / total[mask].sum() * 1e6,
                        mean_log1p_cp10k=logs.mean(),
                        median_log1p_cp10k=np.median(logs),
                    )
                rows.append(row)
    pd.DataFrame(rows).to_csv(output / "target_expression_by_group.csv", index=False)
    summary = {
        "library_id": "synthetic1",
        "metadata_hold": True,
        "clinical_ready": False,
        "production_ready": False,
        "input_cells": 3,
        "analysis_cells": 3,
        "conditional_flags_applied": False,
        "lineage": {"exact_count_lineage": True},
    }
    (output / "summary.json").write_text(json.dumps(summary))
    library = {
        "library_id": "synthetic1",
        "expected_cells": 3,
        "inputs": [{"role": "filtered_h5", "sha256": sha256_file(source), "size_bytes": source.stat().st_size}],
    }
    return library, source, output


def test_original_counts_and_every_numeric_aggregate_are_audited(tmp_path):
    result = audit_exploratory_counts(*synthetic_outputs(tmp_path))
    assert result["status"] == "passed"
    assert all(result["checks"].values())
    assert result["clinical_ready"] is False


def test_normalized_checkpoint_cannot_pass_as_counts(tmp_path):
    h5py = pytest.importorskip("h5py")
    lib, source, output = synthetic_outputs(tmp_path)
    with h5py.File(output / "all_vendor_cells_counts.h5ad", "r+") as handle:
        handle["X/data"][0] = 10000
    result = audit_exploratory_counts(lib, source, output)
    assert result["status"] == "failed"
    assert result["checks"]["original_sparse_data_unchanged"] is False


def test_dropped_or_altered_target_summaries_fail_audit(tmp_path):
    pd = pytest.importorskip("pandas")
    lib, source, output = synthetic_outputs(tmp_path)
    path = output / "target_expression_by_group.csv"
    table = pd.read_csv(path).iloc[1:].copy()
    table.loc[table.gene.eq("BRCA1"), "umi_sum"] = 999
    table.to_csv(path, index=False)
    result = audit_exploratory_counts(lib, source, output)
    assert result["status"] == "failed"
    assert result["checks"]["summary_inventory_complete"] is False
    assert result["checks"]["all_summary_aggregates"] is False
