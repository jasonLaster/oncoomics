#!/usr/bin/env python3
"""Compute open Evo 2 zero-shot SNV delta-likelihood scores on a CUDA host.

The method follows Arc Institute's public BRCA1 notebook: score an 8,192-base
reference window and its single-base alternate, then subtract reference score
from alternate score. This is an independent score, not an EVEE pathogenicity
probe value.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from score_evee_variants import load_variants

EVO2_SOURCE_REVISION = "53f195997257c56c00e5ef8d33a54f5baad143a6"
DEFAULT_MODEL = "evo2_1b_base"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_snv_window(sequence: str, pos1: int, ref: str, alt: str, window_size: int) -> Tuple[str, str, int]:
    if len(ref) != 1 or len(alt) != 1:
        raise ValueError("zero-shot v1 accepts SNVs only")
    position0 = pos1 - 1
    start = max(0, position0 - window_size // 2)
    end = min(len(sequence), position0 + window_size // 2)
    ref_sequence = sequence[start:end].upper()
    offset = position0 - start
    if offset < 0 or offset >= len(ref_sequence):
        raise ValueError("variant position is outside reference sequence")
    if ref_sequence[offset] != ref.upper():
        raise ValueError(f"reference mismatch at 1-based position {pos1}: FASTA={ref_sequence[offset]} input={ref.upper()}")
    alt_sequence = ref_sequence[:offset] + alt.upper() + ref_sequence[offset + 1 :]
    return ref_sequence, alt_sequence, offset


def score_batches(model: Any, sequences: Sequence[str], batch_size: int) -> List[float]:
    scores: List[float] = []
    for start in range(0, len(sequences), batch_size):
        scores.extend(float(value) for value in model.score_sequences(list(sequences[start : start + batch_size])))
    return scores


def prepare_sequences(
    rows: Sequence[Mapping[str, Any]], fasta: Any, window_size: int
) -> Tuple[List[Dict[str, Any]], List[str], List[str], List[int]]:
    prepared: List[Dict[str, Any]] = []
    reference_sequences: List[str] = []
    reference_index: Dict[str, int] = {}
    alternate_sequences: List[str] = []
    row_reference_indexes: List[int] = []
    for row in rows:
        ref = str(row["ref"])
        alt = str(row["alt"])
        if len(ref) != 1 or len(alt) != 1:
            prepared.append({**dict(row), "evo2_status": "unsupported_non_snv"})
            continue
        chrom = str(row["chrom"])
        candidates = (chrom, "chr" + chrom) if not chrom.lower().startswith("chr") else (chrom, chrom[3:])
        record = next((fasta[name] for name in candidates if name in fasta), None)
        if record is None:
            prepared.append({**dict(row), "evo2_status": "contig_not_found"})
            continue
        try:
            reference, alternate, offset = build_snv_window(str(record), int(row["pos"]), ref, alt, window_size)
        except ValueError as error:
            prepared.append({**dict(row), "evo2_status": "reference_mismatch", "error": str(error)})
            continue
        if reference not in reference_index:
            reference_index[reference] = len(reference_sequences)
            reference_sequences.append(reference)
        row_reference_indexes.append(reference_index[reference])
        alternate_sequences.append(alternate)
        prepared.append(
            {
                **dict(row),
                "evo2_status": "ready",
                "window_length": len(reference),
                "variant_offset": offset,
            }
        )
    return prepared, reference_sequences, alternate_sequences, row_reference_indexes


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute open Evo 2 zero-shot SNV delta-likelihood scores")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--window-size", default=8192, type=int)
    parser.add_argument("--batch-size", default=16, type=int)
    parser.add_argument("--dry-run", action="store_true", help="Validate windows without loading Evo 2")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    try:
        from pyfaidx import Fasta
    except ImportError as error:
        raise SystemExit("pyfaidx is required on the CUDA execution host") from error

    rows = load_variants(args.input)
    fasta = Fasta(str(args.reference), as_raw=True, sequence_always_upper=True)
    prepared, reference_sequences, alternate_sequences, reference_indexes = prepare_sequences(rows, fasta, args.window_size)
    ready = [row for row in prepared if row["evo2_status"] == "ready"]

    if not args.dry_run and ready:
        try:
            from evo2.models import Evo2
        except ImportError as error:
            raise SystemExit("evo2 is required on the CUDA execution host") from error
        model = Evo2(args.model)
        reference_scores = score_batches(model, reference_sequences, args.batch_size)
        alternate_scores = score_batches(model, alternate_sequences, args.batch_size)
        for row, ref_index, alt_score in zip(ready, reference_indexes, alternate_scores):
            ref_score = reference_scores[ref_index]
            row["evo2_reference_likelihood"] = ref_score
            row["evo2_alternate_likelihood"] = alt_score
            row["evo2_delta_likelihood"] = alt_score - ref_score
            row["evo2_status"] = "scored"

    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in prepared for key in row})
    with (args.output_dir / "evo2_zero_shot_scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(prepared)
    manifest = {
        "input": {"path": str(args.input.resolve()), "sha256": sha256(args.input)},
        "reference": {"path": str(args.reference.resolve()), "sha256": sha256(args.reference)},
        "model": args.model,
        "evo2_source_revision": EVO2_SOURCE_REVISION,
        "window_size": args.window_size,
        "score": "alternate sequence likelihood minus reference sequence likelihood",
        "direction": "more negative means the alternate is less likely under Evo 2",
        "dry_run": args.dry_run,
        "claim_boundary": (
            "This is the Arc Institute zero-shot delta-likelihood method, not the EVEE pathogenicity probe. "
            "It is not calibrated as a pathogenicity probability and does not establish oncogenicity or actionability."
        ),
    }
    (args.output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"input_variants": len(rows), "ready_or_scored": len(ready), "dry_run": args.dry_run}))


if __name__ == "__main__":
    main()
