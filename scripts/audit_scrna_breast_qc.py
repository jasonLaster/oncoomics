#!/usr/bin/env python3
"""Independently compare collected breast count checkpoints with public source bytes."""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path

import anndata as ad
import numpy as np
from scipy.io import mmread
from scipy.sparse import csr_matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from diana_omics.scrna_io import safe_id, verify_file, write_json  # noqa: E402


def audit(run_id: str, input_cache: Path) -> dict:
    safe_id(run_id)
    root = ROOT / "results/scrna" / run_id
    manifest = json.loads((root / "run_manifest.json").read_text())
    receipt = json.loads((root / "s3_verification.json").read_text())
    if manifest["run_id"] != run_id or manifest["status"] != "complete" or receipt["status"] != "all_hashes_verified":
        raise ValueError("Collect and hash-verify a completed run first")
    verify_file(root / "artifact_index.json", manifest["artifact_index_sha256"])
    config = json.loads((root / "input_manifest.json").read_text())
    checks = {}
    for dataset in config["datasets"]:
        if dataset["format"] != "geo_breast_mtx_tar":
            raise ValueError("This independent audit expects GEO breast archives")
        item = next(i for i in dataset["inputs"] if i["role"] == "counts")
        source = input_cache / item["filename"]
        verify_file(source, item["sha256"])
        directory = root / dataset["dataset_id"]
        for name in ("all_cells_qc.h5ad", "analysis.h5ad"):
            relative = f"{dataset['dataset_id']}/{name}"
            verify_file(directory / name, receipt["objects"][relative]["sha256"])
        # Read the frozen archive directly, independently of the pipeline importer.
        with tarfile.open(source) as handle:
            def member(suffix):
                matches = [m for m in handle.getmembers() if m.isfile() and m.name.endswith(suffix)]
                if len(matches) != 1:
                    raise ValueError("Ambiguous source matrix bundle")
                return handle.extractfile(matches[0])

            with member("count_matrix_sparse.mtx") as stream:
                raw = csr_matrix(mmread(stream).T)
            with member("count_matrix_barcodes.tsv") as stream:
                barcodes = [line.decode().strip() for line in stream]
            with member("count_matrix_genes.tsv") as stream:
                genes = [line.decode().strip() for line in stream]
        all_cells = ad.read_h5ad(directory / "all_cells_qc.h5ad")
        analysis = ad.read_h5ad(directory / "analysis.h5ad")
        keep = all_cells.obs.passes_QC.to_numpy(dtype=bool)
        expected_barcodes = np.asarray(barcodes)[keep].tolist()
        result = {
            "source_sha256_verified": True,
            "input_barcode_order_exact": all_cells.obs_names.tolist() == barcodes,
            "input_gene_order_exact": all_cells.var_names.tolist() == genes,
            "all_raw_counts_exact": all_cells.shape == raw.shape and (csr_matrix(all_cells.X) != raw).nnz == 0,
            "retained_barcode_order_exact": analysis.obs_names.tolist() == expected_barcodes,
            "retained_gene_order_exact": analysis.var_names.tolist() == genes,
            "retained_raw_counts_exact": analysis.shape == raw[keep].shape and (csr_matrix(analysis.layers["counts"]) != raw[keep]).nnz == 0,
            "doublet_exclusion_exact": np.array_equal(keep, (all_cells.obs.passes_core_qc & all_cells.obs.doublet_class.eq("singlet")).to_numpy()),
            "malignancy_uncalled": all_cells.obs.malignancy_status.eq("not_assessed").all(),
        }
        checks[dataset["dataset_id"]] = {key: bool(value) for key, value in result.items()}
        del raw, all_cells, analysis
    report = {"run_id": run_id, "status": "pass" if all(all(row.values()) for row in checks.values()) else "failed",
              "checks": checks, "scope": "Exact source-to-all-barcode and retained raw-count custody; not independent biological truth"}
    if report["status"] != "pass":
        raise ValueError(f"Independent source count audit failed: {report}")
    target = ROOT / "results/scrna/validation" / run_id
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "independent_review.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--input-cache", type=Path, default=ROOT / "data/raw/scrna")
    args = parser.parse_args()
    print(json.dumps(audit(args.run_id, args.input_cache), indent=2))
