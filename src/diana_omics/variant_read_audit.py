"""Bounded SNV read evidence. This is a diagnostic cross-check, never a variant caller."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Iterable


def validate_sites(sites: list[dict]) -> None:
    identities = set()
    for site in sites:
        identity = (site["chrom"], site["pos"], site["ref"], site["alt"])
        if site.get("build") != "GRCh38" or not isinstance(site["pos"], int) or site["pos"] < 1:
            raise ValueError("A positive, one-based GRCh38 position is required")
        if any(len(site[k]) != 1 or site[k] not in "ACGT" for k in ("ref", "alt")) or site["ref"] == site["alt"]:
            raise ValueError("This read audit accepts complete SNV alleles only")
        if identity in identities:
            raise ValueError("Duplicate locus/allele")
        identities.add(identity)
    if not 1 <= len(sites) <= 100:
        raise ValueError("Use a bounded panel of 1 to 100 SNVs")


def count_fragments(reads: Iterable, pos: int, ref: str, alt: str,
                    min_mapq: int = 30, min_baseq: int = 30, min_end_distance: int = 5) -> dict:
    """Collapse overlapping mates by RG and query name; conflicting bases provide no evidence.

    Count only aligned A/C/G/T observations, excluding duplicates, secondary and
    supplementary alignments, QC failures, deletions, reference skips, low quality
    and end-proximal bases. A fragment with only one qualifying mate is retained.
    No assumption that the reads are independent biological replicates is made.
    """
    exclusions = Counter()
    fragments = defaultdict(list)
    seen = 0
    for read in reads:
        seen += 1
        reason = next((name for name, flag in (
            ("unmapped", read.is_unmapped), ("secondary", read.is_secondary),
            ("supplementary", read.is_supplementary), ("duplicate", read.is_duplicate),
            ("qc_fail", read.is_qcfail), ("low_mapping_quality", read.mapping_quality < min_mapq),
        ) if flag), None)
        if reason:
            exclusions[reason] += 1
            continue
        qpos = next((q for q, r in read.get_aligned_pairs(matches_only=False) if r == pos - 1), None)
        if qpos is None:
            exclusions["no_aligned_base"] += 1
            continue
        if read.query_sequence is None or read.query_qualities is None or read.query_qualities[qpos] < min_baseq:
            exclusions["low_or_missing_base_quality"] += 1
            continue
        distance = min(qpos, len(read.query_sequence) - 1 - qpos)
        if distance < min_end_distance:
            exclusions["end_proximal"] += 1
            continue
        base = read.query_sequence[qpos].upper()
        if base not in "ACGT":
            exclusions["ambiguous_base"] += 1
            continue
        rg = read.get_tag("RG") if read.has_tag("RG") else ""
        fragments[(rg, read.query_name)].append({
            "base": base, "base_quality": int(read.query_qualities[qpos]),
            "mapping_quality": read.mapping_quality, "reverse": read.is_reverse,
            "end_distance": distance, "read1": read.is_read1,
        })
    bases = Counter()
    strands = {"ref": Counter(), "alt": Counter(), "other": Counter()}
    alt_quality = []
    conflicts = 0
    qualifying_reads = sum(map(len, fragments.values()))
    for observations in fragments.values():
        if len({o["base"] for o in observations}) != 1:
            conflicts += 1
            continue
        chosen = max(observations, key=lambda o: (o["base_quality"], o["mapping_quality"], o["read1"]))
        base = chosen["base"]
        bases[base] += 1
        kind = "ref" if base == ref else "alt" if base == alt else "other"
        strands[kind]["reverse" if chosen["reverse"] else "forward"] += 1
        if kind == "alt":
            alt_quality.append({k: chosen[k] for k in ("base_quality", "mapping_quality", "end_distance")})
    depth = sum(bases.values())
    ref_n, alt_n = bases[ref], bases[alt]
    return {
        "reads_fetched": seen, "qualifying_reads": qualifying_reads,
        "overlap_observations_collapsed": qualifying_reads - len(fragments),
        "discordant_fragments_excluded": conflicts, "fragment_depth": depth,
        "ref_fragments": ref_n, "alt_fragments": alt_n, "other_fragments": depth - ref_n - alt_n,
        "alt_fraction": alt_n / depth if depth else None,
        "zero_alt_one_sided_95pct_upper_fraction": -math.expm1(math.log(.05) / depth) if depth and not alt_n else None,
        "base_counts": dict(bases), "strand_counts": {k: dict(v) for k, v in strands.items()},
        "alt_fragment_quality": alt_quality, "read_exclusions": dict(exclusions),
        "filters": {"min_mapq": min_mapq, "min_baseq": min_baseq, "min_end_distance": min_end_distance},
    }


def evidence_state(tumor: dict, normal: dict, minimum_depth: int = 20) -> str:
    """Descriptive triage states; these do not imply PASS, pathogenicity or germline status."""
    if min(tumor["fragment_depth"], normal["fragment_depth"]) < minimum_depth:
        return "insufficient_depth"
    if normal["alt_fragments"] >= 3 and normal["alt_fraction"] >= .05:
        return "alternate_observed_in_normal"
    if tumor["alt_fragments"] == 0:
        return "alternate_not_observed_at_this_depth"
    if tumor["alt_fragments"] >= 3 and tumor["alt_fraction"] >= .05 and normal["alt_fragments"] == 0:
        return "tumor_enriched_read_support"
    return "ambiguous_read_support"


def audit_bam(path: str, sites: list[dict], reference_lengths: dict, index_path: str | None = None) -> dict:
    """Read local or exact-version remote BAM. Supply a local, hash-verified BAI for HTTP access."""
    import pysam

    validate_sites(sites)
    policies = [("relaxed_20_20_end0", 20, 20, 0), ("primary_30_30_end5", 30, 30, 5), ("strict_40_30_end10", 40, 30, 10)]
    results = []
    with pysam.AlignmentFile(path, "rb", index_filename=index_path) as bam:
        for contig, length in zip(bam.references, bam.lengths):
            if contig not in reference_lengths or length != reference_lengths[contig]:
                raise ValueError("BAM contig dictionary does not match locked reference lengths")
        for site in sites:
            if site["chrom"] not in bam.references or site["pos"] > reference_lengths[site["chrom"]]:
                raise ValueError("Requested locus is outside BAM/reference dictionary")
            counts = {}
            for name, mq, bq, end in policies:
                counts[name] = count_fragments(bam.fetch(site["chrom"], site["pos"] - 1, site["pos"]),
                                               site["pos"], site["ref"], site["alt"], mq, bq, end)
            results.append({"site": site, "policies": counts})
        header = bam.header.to_dict()
    return {"schema_version": 1, "sites": results, "bam_header": header, "pysam_version": pysam.__version__,
            "evidence_level": "bounded_read_diagnostics", "variant_caller_run": False,
            "somatic_status_established": False, "clinical_ready": False}
