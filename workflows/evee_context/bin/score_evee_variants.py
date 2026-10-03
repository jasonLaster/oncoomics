#!/usr/bin/env python3
"""Score VCF/TSV variants against the public EVEE ClinVar service.

This deliberately retrieves published EVEE values; it does not claim to
recreate Goodfire's unpublished probe-training or arbitrary-variant inference.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, TextIO, Tuple

DEFAULT_API_BASE = "https://xix0d0o8le.execute-api.us-east-1.amazonaws.com"
EVEE_DATASET_DOI = "10.5281/zenodo.19701997"
EVEE_DATASET_RELEASE = "2026-04-23"


def _open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8", newline="")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_chrom(value: str) -> str:
    value = value.strip()
    return value[3:] if value.lower().startswith("chr") else value


def _first(row: Mapping[str, str], names: Sequence[str], default: str = "") -> str:
    normalized = {str(key).strip().lower().lstrip("#"): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name.lower())
        if value not in (None, ""):
            return str(value)
    return default


def _variant_row(
    chrom: str,
    pos: str,
    ref: str,
    alt: str,
    source_index: int,
    source: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    source = source or {}
    return {
        "source_index": source_index,
        "chrom": _clean_chrom(chrom),
        "pos": int(pos),
        "ref": ref.upper(),
        "alt": alt.upper(),
        "reported_gene": _first(source, ("gene", "gene_name", "symbol")),
        "reported_variant": _first(source, ("variant", "variant_label", "hgvs", "hgvsp")),
        "reported_claim": _first(source, ("report_claim", "claim", "evee_prediction")),
        "supplied_evee_variant_id": _first(source, ("evee_variant_id",)),
    }


def parse_vcf(handle: Iterable[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in handle:
        if not line or line.startswith("#"):
            continue
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 5:
            raise ValueError("VCF row has fewer than five columns")
        for alt in fields[4].split(","):
            rows.append(_variant_row(fields[0], fields[1], fields[3], alt, len(rows) + 1))
    return rows


def parse_table(handle: TextIO) -> List[Dict[str, Any]]:
    sample = handle.read(4096)
    handle.seek(0)
    delimiter = "\t" if "\t" in sample.splitlines()[0] else ","
    reader = csv.DictReader(handle, delimiter=delimiter)
    rows: List[Dict[str, Any]] = []
    for source in reader:
        chrom = _first(source, ("chrom", "chr", "chromosome"))
        pos = _first(source, ("pos", "position", "start"))
        ref = _first(source, ("ref", "reference"))
        alt_field = _first(source, ("alt", "alternate"))
        if not all((chrom, pos, ref, alt_field)):
            raise ValueError("Variant table requires chrom, pos, ref, and alt columns")
        for alt in alt_field.split(","):
            rows.append(_variant_row(chrom, pos, ref, alt, len(rows) + 1, source))
    return rows


def load_variants(path: Path) -> List[Dict[str, Any]]:
    with _open_text(path) as handle:
        first = handle.readline()
        handle.seek(0)
        if first.startswith("##fileformat=VCF") or first.startswith("#CHROM"):
            return parse_vcf(handle)
        return parse_table(handle)


def evee_identity(row: Mapping[str, Any], genome_build: str) -> Tuple[Optional[str], str]:
    supplied = str(row.get("supplied_evee_variant_id") or "")
    if supplied:
        return supplied, "supplied"
    if genome_build.lower() not in {"grch38", "hg38"}:
        return None, "unsupported_build"
    ref = str(row["ref"])
    alt = str(row["alt"])
    if len(ref) != 1 or len(alt) != 1:
        return None, "indel_requires_explicit_evee_id"
    chrom = _clean_chrom(str(row["chrom"]))
    pos0 = int(row["pos"]) - 1
    if pos0 < 0:
        return None, "invalid_position"
    return f"chr{chrom}:{pos0}:{ref}:{alt}", "derived_snv_0_based"


def top_disruptions(record: Mapping[str, Any], limit: int) -> List[Dict[str, Any]]:
    disruptions: List[Dict[str, Any]] = []
    for key, ref_value in record.items():
        if not key.startswith("ref_"):
            continue
        name = key[4:]
        alt_value = record.get("var_" + name)
        if not isinstance(ref_value, (int, float)) or not isinstance(alt_value, (int, float)):
            continue
        if not math.isfinite(float(ref_value)) or not math.isfinite(float(alt_value)):
            continue
        delta = float(alt_value) - float(ref_value)
        if abs(delta) < 0.001:
            continue
        disruptions.append(
            {
                "annotation": name,
                "ref": round(float(ref_value), 6),
                "alt": round(float(alt_value), 6),
                "delta": round(delta, 6),
                "abs_delta": round(abs(delta), 6),
                "max_disruption_position": record.get("maxpos_" + name),
            }
        )
    disruptions.sort(key=lambda item: (-item["abs_delta"], item["annotation"]))
    return disruptions[:limit]


def fetch_evee_record(
    variant_id: str,
    api_base: str,
    retries: int = 3,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> Tuple[str, Optional[Dict[str, Any]], Optional[int]]:
    url = api_base.rstrip("/") + "/variants/" + urllib.parse.quote(variant_id, safe=":")
    request = urllib.request.Request(url, headers={"User-Agent": "diana-omics-evee-context/0.1"})
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=30) as response:
                return "found", json.load(response), getattr(response, "status", 200)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return "not_found", None, 404
            if error.code not in {429, 500, 502, 503, 504} or attempt == retries:
                return "http_error", None, error.code
            delay = float(error.headers.get("Retry-After", 2**attempt))
            sleeper(min(delay, 30.0))
        except (TimeoutError, urllib.error.URLError):
            if attempt == retries:
                return "network_error", None, None
            sleeper(float(2**attempt))
    return "network_error", None, None


def score_variants(
    rows: Sequence[Mapping[str, Any]],
    genome_build: str,
    api_base: str,
    online: bool,
    top_n: int,
) -> List[Dict[str, Any]]:
    cache: Dict[str, Tuple[str, Optional[Dict[str, Any]], Optional[int]]] = {}
    scored: List[Dict[str, Any]] = []
    for row in rows:
        variant_id, identity_status = evee_identity(row, genome_build)
        status = identity_status
        record: Optional[Dict[str, Any]] = None
        http_status: Optional[int] = None
        if variant_id and online:
            if variant_id not in cache:
                cache[variant_id] = fetch_evee_record(variant_id, api_base)
            status, record, http_status = cache[variant_id]
        elif variant_id:
            status = "not_queried"

        disruptions = top_disruptions(record or {}, top_n)
        scored.append(
            {
                **dict(row),
                "source_variant_id": "chr{}:{}:{}:{}".format(row["chrom"], row["pos"], row["ref"], row["alt"]),
                "genome_build": genome_build,
                "evee_variant_id": variant_id,
                "evee_identity_status": identity_status,
                "evee_status": status,
                "http_status": http_status,
                "evee_pathogenicity": (record or {}).get("pathogenicity"),
                "evee_eff_pathogenic": (record or {}).get("eff_pathogenic"),
                "evee_splice_disrupting": (record or {}).get("eff_splice_disrupting"),
                "evee_gene": (record or {}).get("gene_name"),
                "evee_hgvsp": (record or {}).get("hgvsp_short") or (record or {}).get("hgvsp"),
                "clinvar_significance": (record or {}).get("significance"),
                "consequence": (record or {}).get("consequence_display") or (record or {}).get("consequence"),
                "top_disruptions": disruptions,
            }
        )
    return scored


def write_outputs(input_path: Path, output_dir: Path, rows: Sequence[Mapping[str, Any]], args: argparse.Namespace) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    compact_rows: List[Dict[str, Any]] = []
    for row in rows:
        compact = dict(row)
        disruptions = list(compact.pop("top_disruptions", []))
        compact["top_disruption_annotation"] = disruptions[0]["annotation"] if disruptions else ""
        compact["top_disruption_delta"] = disruptions[0]["delta"] if disruptions else ""
        compact["top_disruption_abs_delta"] = disruptions[0]["abs_delta"] if disruptions else ""
        compact_rows.append(compact)

    fieldnames = list(compact_rows[0].keys()) if compact_rows else []
    with (output_dir / "variant_scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(compact_rows)

    (output_dir / "variant_scores.json").write_text(json.dumps(list(rows), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = Counter(str(row["evee_status"]) for row in rows)
    found = [row for row in rows if row["evee_status"] == "found"]
    summary = {
        "input_variant_count": len(rows),
        "status_counts": dict(sorted(counts.items())),
        "found_count": len(found),
        "not_found_is_not_benign": True,
        "highest_pathogenicity": max((row["evee_pathogenicity"] for row in found), default=None),
        "claim_boundary": (
            "Values are lookups from the public EVEE ClinVar service. They do not recreate the proprietary "
            "EVEE probe for variants absent from that service, and they do not establish oncogenicity or actionability."
        ),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "input": {"path": str(input_path.resolve()), "sha256": _sha256(input_path)},
        "genome_build": args.genome_build,
        "online": not args.no_network,
        "api_base": args.api_base,
        "evee_dataset_doi": EVEE_DATASET_DOI,
        "evee_dataset_release": EVEE_DATASET_RELEASE,
        "coordinate_rule": "SNVs use chr:POS-1:REF:ALT; indels require an explicitly supplied EVEE ID",
        "software": "workflows/evee_context/bin/score_evee_variants.py",
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Look up public EVEE scores for normalized variants")
    parser.add_argument("--input", required=True, type=Path, help="VCF, VCF.GZ, TSV, or CSV variant input")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--genome-build", default="GRCh38")
    parser.add_argument("--api-base", default=os.environ.get("EVEE_API_BASE_URL", DEFAULT_API_BASE))
    parser.add_argument("--top-disruptions", type=int, default=5)
    parser.add_argument("--no-network", action="store_true", help="Validate identities without querying EVEE")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    rows = load_variants(args.input)
    if not rows:
        raise SystemExit("No variants found")
    scored = score_variants(rows, args.genome_build, args.api_base, not args.no_network, args.top_disruptions)
    write_outputs(args.input, args.output_dir, scored, args)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "variant_count": len(scored),
                "status_counts": Counter(row["evee_status"] for row in scored),
            }
        )
    )


if __name__ == "__main__":
    main()
