"""Prepare an offline modular-pathology review or score supplied aligned ROI masks."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from diana_omics.stil_modular import MASK_NAMES, prepare_review_queue, score_masks


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--run", type=Path, required=True)
    prepare.add_argument("--protocol", type=Path, default=Path("manifests/stil_modular_pipeline.json"))
    prepare.add_argument("--out", type=Path, required=True)
    score = commands.add_parser("score")
    score.add_argument("--contract", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.out.exists():
            parser.error("output directory must be new; original and previous reviews are preserved")
        source = args.run / "slide_results.json"
        queue, readiness = prepare_review_queue(json.loads(source.read_text()), json.loads(args.protocol.read_text()))
        readiness.update(source_results_sha256=digest(source), protocol_sha256=digest(args.protocol))
        args.out.mkdir(parents=True)
        (args.out / "readiness.json").write_text(json.dumps(readiness, indent=2) + "\n")
        with (args.out / "review_queue.csv").open("w") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(queue[0]) if queue else ["slide"])
            writer.writeheader()
            writer.writerows(queue)
        print(json.dumps(readiness, indent=2))
    else:
        import numpy as np

        if args.out.exists():
            parser.error("output file already exists")
        contract = json.loads(args.contract.read_text())
        artifacts = contract["artifacts"]
        masks = {}
        for name in MASK_NAMES:
            entry = artifacts[name]
            path = args.contract.parent / entry["path"]
            if digest(path) != entry["sha256"]:
                raise ValueError("mask artifact hash mismatch: " + name)
            masks[name] = np.load(path, allow_pickle=False)
        cells_path = args.contract.parent / artifacts["cells"]["path"]
        if digest(cells_path) != artifacts["cells"]["sha256"]:
            raise ValueError("cell classification hash mismatch")
        result = score_masks(masks, json.loads(cells_path.read_text()), contract)
        result.update(contract_sha256=digest(args.contract), artifacts=artifacts, grid=contract["grid"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x") as handle:
            handle.write(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
