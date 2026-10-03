"""Independent source-to-checkpoint reader audit. Establishes mechanics, not biological accuracy."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from .scrna_io import sha256_file
from .scrna_private import digest_json
from .scrna_trust import verify_patient_run


def audit_patient_counts(run: Path, contract: dict, delivery: Path) -> dict:
    import anndata as ad
    import h5py
    import numpy as np
    import pandas as pd
    from scipy.io import mmread
    from scipy.sparse import csc_matrix, csr_matrix

    _, _, metrics = verify_patient_run(run)
    manifest = json.loads((run / "run_manifest.json").read_text())
    if digest_json(contract) != manifest["intake_id"]:
        raise ValueError("Independent audit source contract belongs to another intake")
    checks = {}
    for capture in contract["captures"]:
        paths = {item["role"]: delivery / item["path"] for item in capture["files"]}
        for item in capture["files"]:
            path = paths[item["role"]]
            if not path.resolve().is_relative_to(delivery.resolve()) or sha256_file(path) != item["sha256"] or path.stat().st_size != item["size_bytes"]:
                raise ValueError("Independent source file custody mismatch")
        def strings(values):
            return [v.decode() if isinstance(v, bytes) else str(v) for v in values]
        if capture["format"] == "10x_h5":
            with h5py.File(paths["filtered_h5"], "r") as source:
                matrix = source["matrix"]
                counts = csc_matrix((matrix["data"][:], matrix["indices"][:], matrix["indptr"][:]), shape=tuple(matrix["shape"][:])).T.tocsr()
                genes = strings(matrix["features/id"][:])
                gex = np.array(strings(matrix["features/feature_type"][:])) == "Gene Expression"
                genes = list(np.asarray(genes)[gex])
                counts = counts[:, gex]
                barcodes = strings(matrix["barcodes"][:])
        elif capture["format"] == "10x_mtx":
            opener = gzip.open if paths["filtered_matrix"].suffix == ".gz" else open
            with opener(paths["filtered_matrix"], "rb") as source:
                counts = csr_matrix(mmread(source).T)
            features = pd.read_csv(paths["filtered_features"], sep="\t", header=None, dtype=str)
            gex = features[2].eq("Gene Expression").to_numpy()
            genes = features.loc[gex, 0].tolist()
            counts = counts[:, gex]
            barcodes = pd.read_csv(paths["filtered_barcodes"], sep="\t", header=None, dtype=str)[0].tolist()
        else:
            raise ValueError("Count checkpoint audits require post-count inputs")
        full = ad.read_h5ad(run / capture["capture_id"] / "all_cells_qc.h5ad")
        retained = ad.read_h5ad(run / capture["capture_id"] / "analysis.h5ad")
        flags = pd.read_csv(run / capture["capture_id"] / "all_cells_qc.csv", index_col=0)
        original_exact = full.shape == counts.shape and list(full.obs_names) == barcodes and list(full.var.gene_ids) == genes and (counts != full.X).nnz == 0
        indices = {barcode: index for index, barcode in enumerate(barcodes)}
        selected = np.array([indices[b] for b in retained.obs_names])
        kept_exact = list(retained.var.gene_ids) == genes and "counts" in retained.layers and (retained.layers["counts"] != counts[selected]).nnz == 0
        full_flags = full.obs.passes_QC.astype(bool)
        expected = full.obs_names[full_flags]
        candidate_valid = "soupx_counts_candidate" not in full.layers or (np.isfinite(full.layers["soupx_counts_candidate"].data).all() and (full.layers["soupx_counts_candidate"].data >= 0).all() and np.equal(full.layers["soupx_counts_candidate"].data, np.round(full.layers["soupx_counts_candidate"].data)).all() and not (full.layers["soupx_counts_candidate"] > counts).nnz)
        capture_checks = {
            "source_to_all_cells_exact": bool(original_exact), "retained_counts_exact": bool(kept_exact),
            "all_vendor_barcodes_preserved": list(full.obs_names) == barcodes and len(flags) == len(barcodes),
            "retained_selection_exact": list(retained.obs_names) == list(expected),
            "qc_csv_matches_checkpoint": list(flags.index) == list(full.obs_names) and flags.passes_QC.astype(bool).equals(pd.Series(full_flags.to_numpy(), index=flags.index, name="passes_QC")),
            "core_failures_excluded": not bool(full.obs.loc[full_flags, ["fails_low_genes", "fails_low_umis", "fails_mt"]].any().any()),
            "doublets_excluded": full.obs.loc[full_flags, "doublet_class"].eq("singlet").all().item(),
            "candidate_correction_monotone": bool(candidate_valid),
            "malignancy_not_assessed": "malignancy_status" not in full.obs or full.obs.malignancy_status.eq("not_assessed").all().item(),
            "summary_matches_barcodes": metrics[capture["capture_id"]]["input_cells"] == len(barcodes) and metrics[capture["capture_id"]]["retained_cells"] == retained.n_obs,
        }
        if not all(capture_checks.values()):
            raise ValueError("Independent source/checkpoint audit failed")
        checks[capture["capture_id"]] = capture_checks
    return {"schema_version": 1, "status": "counts_integrity_pass", "evidence_level": "mechanical_smoke",
            "intake_id": manifest["intake_id"], "artifact_index_sha256": sha256_file(run / "artifact_index.json"),
            "audit_source_sha256": sha256_file(Path(__file__)),
            "captures": checks, "biological_accuracy_established": False, "clinical_ready": False}
