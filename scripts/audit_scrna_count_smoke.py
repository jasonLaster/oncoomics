#!/usr/bin/env python3
"""Independently compare synthetic STAR outputs with specified molecule counts, not another counter."""
import argparse
import json
import sys
from pathlib import Path

from scipy.io import mmread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from diana_omics.scrna_io import sha256_file  # noqa: E402


def audit(run: Path, expected_path: Path) -> dict:
    expected = json.loads(expected_path.read_text())
    answer = {(row["gene_id"], row["barcode"]): row["umis"] for row in expected["counts"]}
    barcodes = list(dict.fromkeys(row["barcode"] for row in expected["counts"]))
    called = set(barcodes[:expected["filtered_cells"]])
    checks, sums = {}, {}
    for state, selected in (("raw", set(barcodes)), ("filtered", called)):
        path = run / state
        genes = [row.split("\t")[0] for row in (path / "features.tsv").read_text().splitlines()]
        cells = (path / "barcodes.tsv").read_text().splitlines()
        counts = mmread(path / "matrix.mtx").tocoo()
        observed = {(genes[g], cells[c]): int(value) for g, c, value in zip(counts.row, counts.col, counts.data)}
        truth = {key: value for key, value in answer.items() if key[1] in selected}
        checks[state + "_UMIs_exact"] = observed == truth and all(value == int(value) for value in counts.data)
        checks[state + "_barcodes_match"] = len(cells) == len(selected) and set(cells) == selected
        checks[state + "_UMI_sum"] = int(counts.sum()) == sum(truth.values())
        sums[state] = int(counts.sum())
    receipt = json.loads((run / "count_receipt.json").read_text())
    checks["full_fastq_records_checked"] = receipt["full_records_checked"] == expected["records"]
    return {"evidence_level": "synthetic_mechanical_known_answer", "checks": checks,
            "raw_UMIs": sums["raw"], "filtered_UMIs": sums["filtered"], "paired_records": expected["records"],
            "expected_counts_sha256": sha256_file(expected_path), "audit_source_sha256": sha256_file(Path(__file__)),
            "artifact_index_sha256": sha256_file(run / "artifact_index.json"),
            "biological_cell_calling_validated": False, "clinical_ready": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run_dir, args.expected)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if all(result["checks"].values()) else 1)
