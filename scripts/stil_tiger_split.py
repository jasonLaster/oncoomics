"""Freeze the TIGER wsitils development / locked-test split before any model is scored.

Usage:
  aws s3 cp --no-sign-request s3://tiger-training/wsitils/tiger-til-scores-wsitils.csv <dir>/
  python scripts/stil_tiger_split.py --scores <dir>/tiger-til-scores-wsitils.csv

The output records only slide IDs, source, score band, pitfall flags, split and
fold; scores stay in the CC BY-NC 4.0 TIGER source file, which is bound by SHA-256.
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from diana_omics.stil_benchmark import make_split  # noqa: E402

SCORES_SHA256 = "a70061c9ad5191963d199d3137f7e205bf4ccd52755df3031a333e8a0f54c846"
SEED = 20261022
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "manifests/stil_tiger_benchmark_split.json"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--check", action="store_true", help="fail unless --out already equals the regenerated split")
    args = p.parse_args()
    digest = hashlib.sha256(args.scores.read_bytes()).hexdigest()
    if digest != SCORES_SHA256:
        raise SystemExit("TIGER score file SHA-256 mismatch: " + digest)
    rows = list(csv.DictReader(args.scores.open(newline="")))
    split = make_split(rows, seed=SEED, n_dev=40, n_folds=5)
    split.update(source={"uri": "s3://tiger-training/wsitils/tiger-til-scores-wsitils.csv", "sha256": digest,
                         "license": "CC BY-NC 4.0 (TIGER training data; see s3://tiger-training/license.txt)",
                         "source_labels": {"numeric_SB": "Jules Bordet (S resection, B biopsy)", "TC": "Radboud UMC"}},
                 frozen="2026-10-22", generator="scripts/stil_tiger_split.py",
                 rule="development is for method work and 5-fold CV; locked_test is scored once per frozen pipeline")
    text = json.dumps(split, indent=2) + "\n"
    if args.check:
        if args.out.read_text() != text:
            raise SystemExit("frozen split differs from regenerated split")
        print("split matches")
        return
    if args.out.exists() and args.out.read_text() != text:
        raise SystemExit("refusing to overwrite a different frozen split: " + str(args.out))
    args.out.write_text(text)
    counts = {}
    for s in split["slides"]:
        counts[s["split"]] = counts.get(s["split"], 0) + 1
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
