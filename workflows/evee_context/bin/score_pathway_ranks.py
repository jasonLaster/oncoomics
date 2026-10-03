#!/usr/bin/env python3
"""Compute transparent within-sample pathway rank scores and cohort percentiles."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def delimiter(path: Path) -> str:
    return "," if path.suffix.lower() == ".csv" else "\t"


def read_expression(path: Path, gene_column: str) -> Tuple[List[str], Dict[str, Dict[str, float]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter(path))
        if not reader.fieldnames or gene_column not in reader.fieldnames:
            raise ValueError(f"Expression matrix is missing gene column {gene_column!r}")
        samples = [name for name in reader.fieldnames if name != gene_column]
        values: Dict[str, Dict[str, float]] = {sample: {} for sample in samples}
        for row in reader:
            gene = row[gene_column].strip().upper()
            if not gene:
                continue
            for sample in samples:
                raw = row.get(sample, "")
                try:
                    value = float(raw) if raw not in (None, "") else float("nan")
                except ValueError:
                    value = float("nan")
                if math.isfinite(value):
                    values[sample][gene] = value
    return samples, values


def read_gmt(path: Path) -> Dict[str, Set[str]]:
    gene_sets: Dict[str, Set[str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            gene_sets[fields[0]] = {gene.strip().upper() for gene in fields[2:] if gene.strip()}
    if not gene_sets:
        raise ValueError("No gene sets found in GMT")
    return gene_sets


def read_groups(path: Path, sample_column: str, group_column: str) -> Dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter(path))
        return {row[sample_column]: row[group_column] for row in reader if row.get(sample_column) and row.get(group_column)}


def percentile_ranks(values: Mapping[str, float]) -> Dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    ranks: Dict[str, float] = {}
    index = 0
    count = len(ordered)
    while index < count:
        end = index + 1
        while end < count and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        normalized = (average_rank - 0.5) / count
        for offset in range(index, end):
            ranks[ordered[offset][0]] = normalized
        index = end
    return ranks


def score_sample(expression: Mapping[str, float], genes: Set[str], min_genes: int) -> Dict[str, Any]:
    ranks = percentile_ranks(expression)
    observed = sorted(genes.intersection(ranks))
    coverage = len(observed) / len(genes) if genes else 0.0
    if len(observed) < min_genes:
        return {"score": None, "observed_genes": len(observed), "set_genes": len(genes), "coverage": coverage}
    return {
        "score": sum(ranks[gene] for gene in observed) / len(observed),
        "observed_genes": len(observed),
        "set_genes": len(genes),
        "coverage": coverage,
    }


def empirical_percentile(value: float, reference: Sequence[float]) -> Optional[float]:
    if not reference:
        return None
    less = sum(item < value for item in reference)
    equal = sum(item == value for item in reference)
    return 100.0 * (less + 0.5 * equal) / len(reference)


def compute(
    samples: Sequence[str],
    expression: Mapping[str, Mapping[str, float]],
    gene_sets: Mapping[str, Set[str]],
    groups: Mapping[str, str],
    patient_sample: str,
    min_genes: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    by_pathway_group: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    patient_scores: Dict[str, Optional[float]] = {}
    for sample in samples:
        for pathway, genes in gene_sets.items():
            result = score_sample(expression[sample], genes, min_genes)
            score = result["score"]
            group = groups.get(sample, "unassigned")
            row = {"sample_id": sample, "group": group, "pathway": pathway, **result}
            rows.append(row)
            if sample == patient_sample:
                patient_scores[pathway] = score
            elif score is not None:
                by_pathway_group[(pathway, group)].append(score)

    percentile_rows: List[Dict[str, Any]] = []
    reference_groups = sorted({group for sample, group in groups.items() if sample != patient_sample})
    for pathway in sorted(gene_sets):
        patient_score = patient_scores.get(pathway)
        patient_row = next(row for row in rows if row["sample_id"] == patient_sample and row["pathway"] == pathway)
        for group in reference_groups:
            reference = by_pathway_group[(pathway, group)]
            percentile_rows.append(
                {
                    "patient_sample": patient_sample,
                    "pathway": pathway,
                    "method": "mean_within_sample_percentile_rank",
                    "patient_score": patient_score,
                    "comparison_group": group,
                    "reference_n": len(reference),
                    "empirical_percentile": empirical_percentile(patient_score, reference) if patient_score is not None else None,
                    "observed_genes": patient_row["observed_genes"],
                    "set_genes": patient_row["set_genes"],
                    "coverage": patient_row["coverage"],
                }
            )
    return rows, percentile_rows


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute rank-based pathway scores and empirical cohort percentiles")
    parser.add_argument("--expression", required=True, type=Path, help="Gene-by-sample TSV/CSV matrix")
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--gene-sets", required=True, type=Path, help="GMT file")
    parser.add_argument("--patient-sample", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gene-column", default="gene")
    parser.add_argument("--sample-column", default="sample_id")
    parser.add_argument("--group-column", default="comparison_group")
    parser.add_argument("--min-genes", default=10, type=int)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    samples, expression = read_expression(args.expression, args.gene_column)
    if args.patient_sample not in samples:
        raise SystemExit(f"Patient sample {args.patient_sample!r} is absent from expression matrix")
    groups = read_groups(args.metadata, args.sample_column, args.group_column)
    groups.setdefault(args.patient_sample, "patient")
    gene_sets = read_gmt(args.gene_sets)
    scores, percentiles = compute(samples, expression, gene_sets, groups, args.patient_sample, args.min_genes)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "pathway_scores.csv", scores)
    write_csv(args.output_dir / "patient_pathway_percentiles.csv", percentiles)
    manifest = {
        "expression": {"path": str(args.expression.resolve()), "sha256": sha256(args.expression)},
        "metadata": {"path": str(args.metadata.resolve()), "sha256": sha256(args.metadata)},
        "gene_sets": {"path": str(args.gene_sets.resolve()), "sha256": sha256(args.gene_sets)},
        "patient_sample": args.patient_sample,
        "method": "mean_within_sample_percentile_rank",
        "formula": "rank genes within each sample; tie-average ranks; normalize as (rank-0.5)/N; average genes in each set",
        "percentile_formula": "100 * (reference scores below patient + 0.5 * ties) / reference N",
        "claim_boundary": (
            "This transparent rank score is not GSVA/ssGSEA and is not a clinical biomarker. "
            "Its cohort percentile is valid only for the pinned matrix, preprocessing, metadata, and GMT inputs."
        ),
    }
    (args.output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pathways": len(gene_sets), "samples": len(samples), "percentile_rows": len(percentiles)}))


if __name__ == "__main__":
    main()
