"""Independent numerical audit from the vendor H5 to exploratory outputs."""

from __future__ import annotations

import json
from pathlib import Path


def strings(values):
    return [x.decode() if isinstance(x, bytes) else str(x) for x in values]


def audit_exploratory_counts(lib: dict, source: Path, d: Path) -> dict:
    import h5py
    import numpy as np
    import pandas as pd

    from .scrna_io import sha256_file

    summary = json.loads((d / "summary.json").read_text())
    obs = pd.read_csv(d / "all_vendor_barcodes.csv.gz", index_col=0)
    target = pd.read_csv(d / "target_expression_by_group.csv")
    percell = pd.read_csv(d / "target_umi_per_barcode.csv.gz", index_col=0)
    checks = {}
    expected = next(x for x in lib["inputs"] if x["role"] == "filtered_h5")
    checks["input_sha256_matches_arrival"] = sha256_file(source) == expected["sha256"] and source.stat().st_size == expected["size_bytes"]
    checks["library_identity_and_expected_barcodes"] = (
        summary["library_id"] == lib["library_id"] and summary["input_cells"] == lib["expected_cells"]
    )
    with h5py.File(source, "r") as a, h5py.File(d / "all_vendor_cells_counts.h5ad", "r") as b:
        g = a["matrix"]
        x = b["X"]
        source_bcs = strings(g["barcodes"][:])
        ids = strings(g["features/id"][:])
        symbols = strings(g["features/name"][:])
        checks["gene_expression_only_source"] = set(strings(g["features/feature_type"][:])) == {"Gene Expression"}
        checkpoints = strings(b["obs"][b["obs"].attrs["_index"]][:])
        out_ids = strings(b["var/gene_ids"][:])
        checks["all_vendor_barcodes_preserved"] = source_bcs == checkpoints == obs.index.tolist() == percell.index.tolist()
        checks["stable_gene_ids_preserved"] = ids == out_ids
        checks["raw_counts_x_encoding"] = x.attrs["encoding-type"] == "csr_matrix"
        for source_key, output_key in [("data", "data"), ("indices", "indices"), ("indptr", "indptr")]:
            equal = g[source_key].shape == x[output_key].shape
            for start in range(0, g[source_key].size, 4000000):
                if not np.array_equal(g[source_key][start : start + 4000000], x[output_key][start : start + 4000000]):
                    equal = False
                    break
            checks["original_sparse_" + source_key + "_unchanged"] = equal
        ptr = g["indptr"][:]
        n = len(source_bcs)
        total = np.zeros(n, dtype=np.int64)
        mt = np.zeros(n, dtype=np.int64)
        positive = True
        mt_genes = np.array([s.startswith("MT-") for s in symbols])
        from scipy.sparse import coo_matrix, csr_matrix

        selected_positions = {gene: np.flatnonzero(np.array(symbols) == gene) for gene in percell.columns}
        map_rows = []
        map_cols = []
        for j, positions in enumerate(selected_positions.values()):
            map_rows.extend(positions)
            map_cols.extend([j] * len(positions))
        selector = coo_matrix(
            (np.ones(len(map_rows), dtype=np.int64), (map_rows, map_cols)), shape=(len(symbols), len(selected_positions))
        ).tocsr()
        reproduced = {gene: np.zeros(n, dtype=np.int64) for gene in percell.columns}
        for first in range(0, n, 1000):
            last = min(first + 1000, n)
            offset = int(ptr[first])
            end = int(ptr[last])
            v = g["data"][offset:end]
            ind = g["indices"][offset:end]
            starts = ptr[first:last] - offset
            positive &= bool((v > 0).all())
            total[first:last] = np.add.reduceat(v, starts)
            mt[first:last] = np.add.reduceat(np.where(mt_genes[ind], v, 0), starts)
            block = csr_matrix((v, ind, ptr[first : last + 1] - offset), shape=(last - first, len(symbols)))
            small = (block @ selector).toarray()
            for j, gene in enumerate(selected_positions):
                reproduced[gene][first:last] = small[:, j]
        checks["counts_positive_and_integer"] = positive and g["data"].dtype.kind in "iu"
        checks["per_barcode_umi_totals"] = np.array_equal(total, obs.total_counts.to_numpy())
        checks["per_barcode_detected_genes"] = np.array_equal(np.diff(ptr), obs.n_genes_by_counts.to_numpy())
        checks["per_barcode_mito_percent"] = bool(np.allclose(mt / total * 100, obs.pct_counts_mt, atol=1e-7, rtol=0))
        checks["every_target_per_barcode_umi"] = all(np.array_equal(v, percell[gene].to_numpy()) for gene, v in reproduced.items())
        from .scrna_exploratory import TARGETS

        checks["requested_target_inventory_complete"] = (
            set(percell.columns) == set(TARGETS).intersection(symbols) and percell.columns.is_unique
        )
        checks["all_summary_aggregates"] = True
        group_labels = {
            "all_vendor_barcodes": np.repeat("all", n),
            "coarse_marker_hint": obs.coarse_label_hint.to_numpy(),
            "diagnostic_cluster": obs.leiden_diagnostic_r05.astype(str).to_numpy(),
            "diagnostic_doublet_class": obs.diagnostic_doublet_class.to_numpy(),
            "conditional_whole_cell_core_flag": np.where(
                obs.conditional_whole_cell_passes_core_qc, "conditional_core_pass", "conditional_core_flag"
            ),
        }
        expected_inventory = {
            (grouping, str(label), gene) for grouping, labels in group_labels.items() for label in set(labels) for gene in TARGETS
        }
        observed_inventory = [(row.grouping, str(row.group), row.gene) for row in target.itertuples()]
        checks["summary_inventory_complete"] = set(observed_inventory) == expected_inventory and len(observed_inventory) == len(
            expected_inventory
        )
        for row in target.itertuples():
            if not row.feature_present:
                if row.gene in reproduced:
                    checks["all_summary_aggregates"] = False
                continue
            mask = group_labels[row.grouping] == str(row.group)
            v = reproduced[row.gene][mask]
            good = int(mask.sum()) == row.cells and int(v.sum()) == row.umi_sum and int((v > 0).sum()) == row.detected_cells
            good &= np.isclose((v > 0).mean(), row.detected_fraction, atol=1e-9, rtol=0)
            good &= np.isclose(v.sum() / total[mask].sum() * 1e6, row.pseudobulk_umi_cpm, atol=1e-6, rtol=0)
            good &= np.isclose(np.log1p(v * 10000 / total[mask]).mean(), row.mean_log1p_cp10k, atol=1e-9, rtol=0)
            good &= np.isclose(np.median(np.log1p(v * 10000 / total[mask])), row.median_log1p_cp10k, atol=1e-9, rtol=0)
            if not good:
                checks["all_summary_aggregates"] = False
                break
        checks["metadata_hold_and_no_clinical_release"] = (
            summary["metadata_hold"] is True and summary["clinical_ready"] is False and summary["production_ready"] is False
        )
        checks["no_cell_filter_applied"] = (
            n == summary["input_cells"] == summary["analysis_cells"] and not summary["conditional_flags_applied"]
        )
        checks["raw_filtered_lineage"] = summary["lineage"]["exact_count_lineage"]
        checks["diagnostic_doublet_classes_complete"] = obs.diagnostic_doublet_class.isin(["singlet", "doublet"]).all()
    result = {
        "library_id": lib["library_id"],
        "checks": {k: bool(v) for k, v in checks.items()},
        "status": "passed" if all(checks.values()) else "failed",
        "clinical_ready": False,
        "metadata_hold": True,
    }
    (d / "independent_numeric_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(lib["library_id"], "independent numeric audit", result["status"], sum(checks.values()), "/", len(checks))
    return result
